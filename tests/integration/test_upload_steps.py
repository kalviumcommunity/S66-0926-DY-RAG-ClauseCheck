import time

import pytest

from clausecheck.core.config import Settings
from clausecheck.services.ingestion_service import UploadService, describe_step
from clausecheck.store import sqlite as db


def wait(service, job_id, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        job = service.get_job(job_id)
        if job["status"] in {"done", "failed"}:
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


@pytest.fixture
def setup(tmp_path):
    settings = Settings(_env_file=None, sqlite_path=tmp_path / "u.db", uploads_dir=tmp_path / "up")
    conn = db.connect(settings.sqlite_path)
    db.init_db(conn)
    return conn, UploadService(lambda: db.connect(settings.sqlite_path), settings)


def test_an_upload_keeps_a_filing_log_with_real_counts(setup, fixture_paths):
    conn, service = setup
    job = wait(service, service.submit("a.txt", fixture_paths["txt"].read_bytes(), "S-NEW"))
    assert job["status"] == "done", job["error"]
    steps = job["steps"]
    assert [s["id"] for s in steps] == ["checked", "extracted", "split", "embedding", "ready"]
    assert [s["label"] for s in steps] == [
        "File checked",
        "Text extracted",
        "Split into clauses",
        "Embedding clauses",
        "Ready to check",
    ]
    clauses = len(db.get_chunks(conn, doc_id=job["doc_id"]))
    assert (
        steps[2]["detail"] == f"{clauses} clauses"
        and steps[4]["detail"] == f"{clauses} clauses indexed"
    )
    assert steps[0]["detail"].endswith("not a duplicate") and "TXT" in steps[0]["detail"]
    assert all(s["at"].endswith("Z") for s in steps)  # timestamped, in UTC


def test_a_failed_upload_says_where_it_stopped(setup):
    _, service = setup
    job = wait(service, service.submit("empty.txt", b"   \n  ", "S-NEW"))
    assert job["status"] == "failed"
    assert [s["id"] for s in job["steps"]][-1] == "failed"
    assert job["steps"][-1]["label"] == "Could not be filed"


def test_the_effective_date_the_user_types_beats_the_one_read_from_the_text(setup, fixture_paths):
    conn, service = setup
    text = b"Supply Agreement effective from 1 January 2025.\n\n1.1 Payment. Net 30 days.\n"
    job = wait(service, service.submit("a.txt", text, "S-NEW", effective_date="2020-02-02"))
    assert db.get_document(conn, job["doc_id"])["effective_date"] == "2020-02-02"
    other = wait(service, service.submit("b.txt", text + b"More.\n", "S-NEW"))
    assert db.get_document(conn, other["doc_id"])["effective_date"] == "2025-01-01"


def test_naming_the_document_an_amendment_changes_links_it_and_marks_it_an_amendment(setup):
    conn, service = setup
    original = wait(service, service.submit("a.txt", b"Agreement.\n\n1.1 Fee. $10.\n", "S-NEW"))
    amendment = wait(
        service,
        service.submit(
            "b.txt",
            b"Changes.\n\n1.1 Fee. $20.\n",
            "S-NEW",
            doc_type="contract",
            amends=original["doc_id"],
        ),
    )
    doc = db.get_document(conn, amendment["doc_id"])
    assert (doc["doc_type"], doc["parent_doc_id"]) == ("amendment", original["doc_id"])


def test_describe_step_words():
    assert describe_step("extracted", {"pages": 18, "text_pages": 18})["detail"] == (
        "18 pages, all with a text layer"
    )
    assert describe_step("extracted", {"pages": 1, "text_pages": 1})["detail"] == (
        "1 page, all with a text layer"
    )
    assert describe_step("extracted", {"pages": 10, "text_pages": 7})["detail"] == (
        "10 pages, 7 with a text layer"
    )
    assert describe_step("checked", {"bytes": 2202009, "type": "PDF"})["detail"] == (
        "2.1 MB PDF · not a duplicate"
    )
    assert describe_step("unknown", {}) == {"label": "unknown", "detail": ""}
