# PR 16 · Document upload, feedback and Insights endpoints

**Branch:** `b-upload-feedback-insights` · **Owner:** Teammate (Generation, Application & Delivery) · **Week:** 5 · **Depends on:** PR 15

## Context

PR 15 gave the API its core. This PR adds the rest of the backend surface:
- **document upload with async indexing**, so a new file becomes answerable without a restart
- the document listing and job-status endpoints
- **feedback** (👍/👎) stored against a query
- the FR-12 **Insights** dashboard data (KPIs, charts, tables)

It also extends the AC-N2.7 sentinel test so that **every** endpoint is covered.

Read before starting:
- `docs/architecture/api-design.md` (as rewritten in PR 15)
- `docs/requirements/functional-requirements.md` (FR-12 Insights dashboard)
- `docs/requirements/non-functional-requirements.md` NFR-2 (AC-N2.7)
- `docs/ux/ui-states.md` (upload and error states)

## Scope (only these files)

| Path | Action |
|---|---|
| `clausecheck/api/routes/documents.py`, `feedback.py`, `insights.py` | add |
| `clausecheck/api/main.py`, `clausecheck/api/container.py` | modify: include the new routers, wire `UploadService` |
| `clausecheck/services/ingestion_service.py` | modify: add `UploadService` |
| `clausecheck/services/insights_service.py` | add |
| `clausecheck/store/query_log.py` | modify: feedback table and methods |
| `clausecheck/core/schema.py` | modify: add `"upload"` to `SOURCES` |
| `clausecheck/core/config.py`, `.env.example` | modify: `max_upload_mb: int = 20`, `allowed_types: str = "pdf,html,htm,docx,txt"`, `uploads_dir: Path = Path("data/uploads")` |
| `requirements.txt` | modify: add `python-multipart` |
| `tests/api/conftest.py`, `tests/api/test_secrets_sentinel.py` | modify: replace with the versions below |
| `tests/api/test_documents.py`, `tests/api/test_insights_feedback.py`, `tests/integration/test_upload_service.py` | add |
| `docs/architecture/api-design.md` | modify: add the endpoints below |

## Specification

### `clausecheck/api/container.py` (changes)

- `from_settings` now also builds an `UploadService` whose `on_indexed` callback rebuilds the retriever's BM25 index, and assigns it to `upload_service`. This is what makes a new upload answerable without a restart.
- `main.py` includes the `documents`, `feedback` and `insights` routers.

### Endpoints

| Method and path | Request | Response |
|---|---|---|
| `GET /documents` | query `supplier_id?`, `limit=50` (max 200), `cursor?` | `200 {"items": [document rows without path], "next_cursor": str \| null}`, ordered by `doc_id`; the cursor is the last `doc_id` |
| `POST /documents` | multipart: `file`, `supplier_id` (required), `doc_type` (default `contract`) | `202 {"job_id"}`; `413` over `max_upload_mb`; `415` for a disallowed extension; `409 {"detail": "duplicate", "doc_id"}` for an identical file |
| `GET /documents/jobs/{job_id}` | none | `200 {"job_id", "status": queued\|running\|done\|failed, "doc_id", "error"}`; `404` |
| `POST /feedback` | `{"query_id", "rating": "up"\|"down", "comment": str?}` | `204`; `404` for an unknown `query_id` |
| `GET /insights/kpis` | none | `200 {"questions_asked", "answer_rate", "median_time_to_checked_answer_ms", "median_ttft_ms", "citation_accuracy"}` |
| `GET /insights/charts` | `days=14` | `200 {"outcomes_by_day", "latency_by_day", "questions_by_topic", "documents_by_source"}` |
| `GET /insights/tables` | none | `200 {"supplier_activity", "unanswered", "evaluation", "coverage"}` |

**Insights data** (`services/insights_service.py`, computed from `query_log`, `documents`, `chunks` and the newest `eval/results/*_e2e_*.json`):
- `answer_rate` = answered ÷ (answered + refused)
- `citation_accuracy` is taken from the newest e2e result file, or `null`
- `questions_by_topic` uses a keyword map defined in the service (payment, term/renewal, liability, termination, price, certificate, other)
- `unanswered` lists the latest refused questions with a `can_upload: true` hint
- `evaluation` lists metrics vs targets (0.85 / 85% / 90% / 90% / 3000 ms)

If FR-12 names these differently, keep the keys above (the tests and frontend depend on them) and document the mapping in `api-design.md`.

### `UploadService` (in `ingestion_service.py`)

```python
class DuplicateDocumentError(Exception):
    def __init__(self, doc_id: str): ...

class UploadService:
    def __init__(self, conn_factory: Callable[[], sqlite3.Connection], settings, *,
                 embedder=None, vector_store=None, on_indexed: Callable[[], None] | None = None,
                 executor: Executor | None = None): ...
    def submit(self, filename: str, content: bytes, supplier_id: str, doc_type: str = "contract") -> str: ...
    def get_job(self, job_id: str) -> dict | None: ...
```

- `submit`:
  - computes sha256. If any document already has that sha256, it raises `DuplicateDocumentError(existing_doc_id)`.
  - saves the file to `uploads_dir/<sha[:12]>_<safe filename>`.
  - inserts a `jobs` row with status `queued`.
  - submits the work to the executor (default `ThreadPoolExecutor(max_workers=1)`) and returns `job_id`.
- The work, using its **own connection** from `conn_factory`:
  1. Set status `running`.
  2. Build a manifest row: `source="upload"`, `licence="user upload"`, `is_synthetic="false"`, `doc_id = ids.doc_id("upload", sha)`, `format` from the extension (htm counts as html).
  3. Upsert the supplier if it's unknown, with display name = id.
  4. Call `ingest_document`, then set status `done` with `doc_id`, or `failed` with `error`.
  5. Call `on_indexed()` on success.

### `QueryLog` additions

- Table `feedback(query_id, rating, comment, created_at)`
- `exists(query_id) -> bool`
- `add_feedback(query_id, rating, comment=None)`

## Tests

Replace `tests/api/conftest.py` and `tests/api/test_secrets_sentinel.py` with the versions below. They add the fake upload service, `max_upload_mb=1`, `uploads_dir`, and sentinel calls for every endpoint.

### `tests/api/conftest.py`

```python
import pytest
from fastapi.testclient import TestClient

from clausecheck.api.container import AppContainer
from clausecheck.api.main import create_app
from clausecheck.core.config import Settings
from clausecheck.rag.citation_validator import Citation
from clausecheck.services.ingestion_service import DuplicateDocumentError
from clausecheck.services.query_service import QueryResult, StreamEvent
from clausecheck.services.sessions import SessionStore
from clausecheck.store import sqlite as db
from clausecheck.store.query_log import QueryLog
from tests.helpers import make_chunk

CITATION = Citation("C1", "doc-a:p2:2_1", "doc-a", 2, "2. Payment", "2.1")


def result(outcome="answered", answer="Payment is due Net 45 days [C1].", query_id="q-1"):
    return QueryResult(
        query_id=query_id, question="q", rewritten_question="q", supplier_id="S-ACME", answer=answer,
        citations=[CITATION] if outcome == "answered" else [], outcome=outcome,
        refusal_reason=None if outcome == "answered" else "low_score", unsupported=False, cached=False,
        timings={"total": 120.0}, prompt_version="v1", index_version="v1",
        chunk_ids=["doc-a:p2:2_1"] if outcome == "answered" else [],
    )


class FakeQueryService:
    def __init__(self, query_log):
        self.query_log = query_log
        self.fail_with = None

    def answer(self, question, session_id=None, supplier_filter=None):
        if self.fail_with:
            raise self.fail_with
        r = result("refused", "I couldn't find this.") if "refuse" in question else result()
        self.query_log.log({"query_id": r.query_id, "created_at": "2026-11-20T10:00:00", "question": question,
                            "outcome": r.outcome, "latency_ms": 120.0, "ttft_ms": 800.0})
        return r

    def stream(self, question, session_id=None, supplier_filter=None):
        if self.fail_with:
            raise self.fail_with
        yield StreamEvent("meta", {"query_id": "q-2", "supplier_id": "S-ACME", "rewritten_question": question})
        yield StreamEvent("sources", {"sources": [{"marker": "C1", "chunk_id": "doc-a:p2:2_1"}]})
        yield StreamEvent("token", {"text": "Payment is due "})
        yield StreamEvent("token", {"text": "Net 45 days [C1]."})
        yield StreamEvent("citations", {"citations": [{"marker": "C1", "chunk_id": "doc-a:p2:2_1"}],
                                        "unsupported": False})
        yield StreamEvent("done", {"outcome": "answered", "refusal_reason": None, "cached": False,
                                   "timings": {"ttft": 400.0}})


class FakeUploadService:
    def __init__(self):
        self.jobs = {}

    def submit(self, filename, content, supplier_id, doc_type="contract"):
        if content == b"duplicate":
            raise DuplicateDocumentError("doc-a")
        job_id = f"job-{len(self.jobs) + 1}"
        self.jobs[job_id] = {"job_id": job_id, "status": "done", "doc_id": "upload-x", "error": None}
        return job_id

    def get_job(self, job_id):
        return self.jobs.get(job_id)


@pytest.fixture
def container(tmp_path):
    settings = Settings(_env_file=None, max_upload_mb=1, sqlite_path=tmp_path / "api.db",
                        uploads_dir=tmp_path / "uploads")
    conn = db.connect(settings.sqlite_path)
    db.init_db(conn)
    db.upsert_supplier(conn, "S-ACME", "Acme Corp", ["Acme"])
    db.upsert_document(conn, {"doc_id": "doc-a", "supplier_id": "S-ACME", "source": "cuad",
                              "doc_type": "contract", "format": "pdf", "path": "data/raw/a.pdf", "title": "A"})
    db.replace_chunks(conn, "doc-a", [make_chunk(chunk_id="doc-a:p2:2_1", doc_id="doc-a", page=2)])
    query_log = QueryLog(conn)
    return AppContainer(settings=settings, conn=conn, query_service=FakeQueryService(query_log),
                        upload_service=FakeUploadService(), sessions=SessionStore(3), query_log=query_log,
                        vector_count=lambda: 1)


@pytest.fixture
def client(container):
    return TestClient(create_app(container), raise_server_exceptions=False)


def parse_sse(text: str) -> list[tuple[str, dict]]:
    import json

    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        events.append((lines["event"], json.loads(lines["data"])))
    return events
```

### `tests/api/test_documents.py`

```python
def _upload(client, name="contract.pdf", content=b"%PDF-1.4 test", supplier="S-ACME"):
    return client.post("/documents", files={"file": (name, content)}, data={"supplier_id": supplier})


def test_upload_accepted_and_job_status(client):
    r = _upload(client)
    assert r.status_code == 202
    job = client.get(f"/documents/jobs/{r.json()['job_id']}").json()
    assert job["status"] == "done" and job["doc_id"] == "upload-x"


def test_upload_duplicate(client):
    r = _upload(client, content=b"duplicate")
    assert r.status_code == 409 and r.json()["doc_id"] == "doc-a"


def test_upload_too_large(client):
    assert _upload(client, content=b"x" * (1024 * 1024 + 1)).status_code == 413


def test_upload_bad_type(client):
    assert _upload(client, name="virus.exe").status_code == 415


def test_upload_requires_supplier(client):
    r = client.post("/documents", files={"file": ("a.pdf", b"%PDF")})
    assert r.status_code == 422


def test_unknown_job(client):
    assert client.get("/documents/jobs/nope").status_code == 404


def test_list_documents_hides_path(client):
    body = client.get("/documents").json()
    assert [d["doc_id"] for d in body["items"]] == ["doc-a"]
    assert "path" not in body["items"][0] and body["next_cursor"] is None
```

### `tests/api/test_insights_feedback.py`

```python
def test_feedback(client):
    client.post("/chat", json={"question": "Payment terms with Acme?"})
    assert client.post("/feedback", json={"query_id": "q-1", "rating": "up"}).status_code == 204
    assert client.post("/feedback", json={"query_id": "nope", "rating": "up"}).status_code == 404
    assert client.post("/feedback", json={"query_id": "q-1", "rating": "meh"}).status_code == 422


def test_kpis(client):
    client.post("/chat", json={"question": "Payment terms with Acme?"})
    k = client.get("/insights/kpis").json()
    assert set(k) == {"questions_asked", "answer_rate", "median_time_to_checked_answer_ms",
                      "median_ttft_ms", "citation_accuracy"}
    assert k["questions_asked"] == 1 and k["answer_rate"] == 1.0


def test_charts_and_tables_shape(client):
    assert set(client.get("/insights/charts").json()) == {
        "outcomes_by_day", "latency_by_day", "questions_by_topic", "documents_by_source"}
    assert set(client.get("/insights/tables").json()) == {
        "supplier_activity", "unanswered", "evaluation", "coverage"}
```

### `tests/api/test_secrets_sentinel.py`

```python
"""AC-N2.7: the sentinel key never appears in any body, header or log line."""
import logging

from tests.constants import SENTINEL


def test_sentinel_never_leaks(client, container, caplog):
    caplog.set_level(logging.DEBUG)
    calls = [
        ("post", "/sessions", {}),
        ("post", "/chat", {"json": {"question": "Payment terms with Acme?"}}),
        ("post", "/chat/stream", {"json": {"question": "Payment terms with Acme?"}}),
        ("get", "/suppliers", {}),
        ("get", "/chunks/doc-a:p2:2_1", {}),
        ("get", "/chunks/missing", {}),
        ("get", "/documents", {}),
        ("post", "/documents", {"files": {"file": ("a.pdf", b"%PDF")}, "data": {"supplier_id": "S-ACME"}}),
        ("get", "/documents/jobs/job-1", {}),
        ("post", "/feedback", {"json": {"query_id": "q-1", "rating": "down"}}),
        ("get", "/insights/kpis", {}),
        ("get", "/insights/charts", {}),
        ("get", "/insights/tables", {}),
        ("get", "/health", {}),
    ]
    seen = []
    for method, path, kwargs in calls:
        r = getattr(client, method)(path, **kwargs)
        seen.append(r.text + str(dict(r.headers)))

    container.query_service.fail_with = RuntimeError(f"401 invalid key {SENTINEL}")
    for path in ["/chat", "/chat/stream"]:
        r = client.post(path, json={"question": "boom"})
        seen.append(r.text + str(dict(r.headers)))

    for text in seen:
        assert SENTINEL not in text
    assert SENTINEL not in caplog.text
```

### `tests/integration/test_upload_service.py`

```python
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
```

## Manual checks

1. Run `pytest -q`. Every test should pass, including the sentinel test.
2. Open `http://localhost:7860/docs`. **Every** endpoint from PR 15 and this PR should be listed.
3. Upload a document that no existing chunk can answer:
   ```bash
   curl -F file=@my_test.txt -F supplier_id=S-TEST -F doc_type=certificate localhost:7860/documents
   ```
   Poll `/documents/jobs/<id>` until `done`, then ask a question only that file answers. It should be answered with a citation to it, with no restart.
4. Upload the same file again. Expect `409`.
5. Upload a `.exe` (expect `415`) and a file over `MAX_UPLOAD_MB` (expect `413`).
6. Send feedback with curl, then run `sqlite3 index/clausecheck.db "SELECT * FROM feedback;"`. The row should be there.
7. Run `curl -s localhost:7860/insights/kpis | python -m json.tool`, and the same for `/insights/charts` and `/insights/tables`. The keys should match the spec exactly.
8. Check the server log while doing all of the above. No key should appear, and errors should show only a request id and the exception type.

## Definition of done

Uploads become answerable without a restart, feedback and the Insights data endpoints work, every endpoint is documented in `api-design.md`, the sentinel test covers every endpoint, and every test passes.