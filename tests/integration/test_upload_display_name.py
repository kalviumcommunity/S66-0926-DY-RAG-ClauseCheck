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


def test_a_new_contract_gets_the_name_the_user_typed(tmp_path, fixture_paths):
    conn, service = _service(tmp_path)
    content = fixture_paths["txt"].read_bytes()
    job = _wait(
        service, service.submit("a.txt", content, "q3-supply-deal", "contract", "Q3 Supply Deal")
    )
    assert job["status"] == "done", job["error"]
    supplier = next(s for s in db.list_suppliers(conn) if s["supplier_id"] == "q3-supply-deal")
    assert supplier["display_name"] == "Q3 Supply Deal"


def test_an_existing_contract_keeps_its_name(tmp_path, fixture_paths):
    conn, service = _service(tmp_path)
    db.upsert_supplier(conn, "q3-supply-deal", "Original Name", ["Q3"])
    content = fixture_paths["txt"].read_bytes()
    _wait(service, service.submit("a.txt", content, "q3-supply-deal", "contract", "Another Name"))
    supplier = next(s for s in db.list_suppliers(conn) if s["supplier_id"] == "q3-supply-deal")
    assert supplier["display_name"] == "Original Name" and supplier["aliases"] == ["Q3"]
