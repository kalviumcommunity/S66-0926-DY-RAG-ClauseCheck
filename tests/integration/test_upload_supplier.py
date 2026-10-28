import time

from clausecheck.core.config import Settings
from clausecheck.services.ingestion_service import UploadService
from clausecheck.store import sqlite as db


def _wait(service, job_id, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        job = service.get_job(job_id)
        if job["status"] in {"done", "failed"}:
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def _service(tmp_path):
    settings = Settings(_env_file=None, sqlite_path=tmp_path / "u.db", uploads_dir=tmp_path / "up")
    conn = db.connect(settings.sqlite_path)
    db.init_db(conn)
    return conn, UploadService(lambda: db.connect(settings.sqlite_path), settings)


def test_new_supplier_gets_a_readable_name_and_alias(tmp_path, fixture_paths):
    conn, service = _service(tmp_path)
    content = fixture_paths["txt"].read_bytes()
    _wait(service, service.submit("a.txt", content, "helixa-cloud-systems", "certificate"))
    supplier = next(
        s for s in db.list_suppliers(conn) if s["supplier_id"] == "helixa-cloud-systems"
    )
    assert supplier["display_name"] == "Helixa Cloud Systems"
    assert "helixa-cloud-systems" in supplier["aliases"]


def test_upload_does_not_overwrite_an_existing_supplier(tmp_path, fixture_paths):
    conn, service = _service(tmp_path)
    db.upsert_supplier(conn, "S-ACME", "Acme Corp", ["Acme", "ACME Corporation"])
    content = fixture_paths["txt"].read_bytes()
    _wait(service, service.submit("a.txt", content, "S-ACME", "certificate"))
    supplier = next(s for s in db.list_suppliers(conn) if s["supplier_id"] == "S-ACME")
    assert supplier["display_name"] == "Acme Corp"
    assert sorted(supplier["aliases"]) == ["ACME Corporation", "Acme"]
