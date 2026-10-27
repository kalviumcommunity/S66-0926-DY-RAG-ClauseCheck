import time

import pytest

from clausecheck.core.config import Settings
from clausecheck.services.ingestion_service import DuplicateDocumentError, UploadService
from clausecheck.store import sqlite as db


def _wait(service, job_id, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        job = service.get_job(job_id)
        if job["status"] in {"done", "failed"}:
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_upload_indexes_document_and_rejects_duplicate(tmp_path, fixture_paths):
    settings = Settings(_env_file=None, sqlite_path=tmp_path / "u.db", uploads_dir=tmp_path / "up")
    conn = db.connect(settings.sqlite_path)
    db.init_db(conn)
    indexed = []
    service = UploadService(lambda: db.connect(settings.sqlite_path), settings,
                            on_indexed=lambda: indexed.append(True))
    content = fixture_paths["txt"].read_bytes()

    job = _wait(service, service.submit("acme_iso.txt", content, "S-NEW", "certificate"))
    assert job["status"] == "done", job["error"]
    assert db.get_chunks(conn, doc_id=job["doc_id"])
    assert db.get_document(conn, job["doc_id"])["source"] == "upload"
    assert indexed == [True]
    assert any(s["supplier_id"] == "S-NEW" for s in db.list_suppliers(conn))

    with pytest.raises(DuplicateDocumentError):
        service.submit("again.txt", content, "S-NEW", "certificate")
