# PR 15 · FastAPI core: app factory, chat (blocking and streaming), catalog and health

**Branch:** `b-api-core` · **Owner:** Teammate (Generation, Application & Delivery) · **Week:** 5 · **Depends on:** PR 14

## Context

All the real work happens in FastAPI. The Streamlit frontend (PR 17) only calls these endpoints. This PR builds the app and everything the chat screen needs:
- the app factory, dependency container, request-id middleware, CORS and the global error handler
- chat, both blocking and **SSE streaming**
- sessions, suppliers, full-clause lookup and a health check

It also proves that **no secret appears in any response, header or log line** (AC-N2.7) for every endpoint added here. Document upload, feedback and the Insights endpoints come in PR 16, which extends the same sentinel test.

Read before starting:
- `docs/architecture/api-design.md`. **It still says `/ask`.** This PR rewrites it to match what is built here, and the paths below win.
- `docs/requirements/non-functional-requirements.md` NFR-2 (AC-N2.7 sentinel test)
- `docs/ux/ui-states.md` (stream events and error states)
- `docs/architecture/tdd.md` §10 (Hugging Face Spaces, port 7860)

## Scope (only these files)

| Path | Action |
|---|---|
| `clausecheck/api/main.py`, `schemas.py`, `deps.py` | add |
| `clausecheck/api/routes/__init__.py`, `chat.py`, `sessions.py`, `catalog.py`, `health.py` | add |
| `clausecheck/api/container.py` | add |
| `clausecheck/core/config.py`, `.env.example` | modify: `frontend_origin: str = "http://localhost:8501"`, `port: int = 7860` |
| `requirements.txt` | modify: add `fastapi`, `uvicorn[standard]`, `httpx` |
| `tests/api/conftest.py`, `tests/api/test_chat.py`, `tests/api/test_catalog_health.py`, `tests/api/test_secrets_sentinel.py` | add |
| `docs/architecture/api-design.md` | modify: rewrite to the endpoints below (PR 16 adds the rest) |

## Specification

### `clausecheck/api/container.py`

```python
@dataclass
class AppContainer:
    settings: Settings
    conn: sqlite3.Connection
    query_service: Any            # .answer(...) / .stream(...)
    sessions: SessionStore
    query_log: QueryLog
    upload_service: Any = None    # wired in PR 16
    vector_count: Callable[[], int] | None = None

    @classmethod
    def from_settings(cls, settings) -> "AppContainer": ...
```

`from_settings` opens SQLite and runs `init_db`, builds the embedder, vector store and `QueryService.from_settings` (sharing one `SessionStore`), and loads the re-ranker once. `upload_service` stays `None` until PR 16.

### `clausecheck/api/main.py`

- `create_app(container: AppContainer | None = None) -> FastAPI`:
  - With a container (tests), use it directly.
  - Without one, a lifespan builds `AppContainer.from_settings(get_settings())` and calls `setup_logging`.
  - Store the container in `app.state.container`. `deps.get_container(request)` returns it.
- Add a `RedactionFilter` built from every `SecretStr` in settings to the `logging.getLogger("clausecheck.api")` logger. All API logging uses that logger.
- CORS: allow `settings.frontend_origin`.
- Middleware: an `X-Request-ID` header on every response, using the incoming value or a new uuid4 hex.
- Global exception handler: returns `500 {"detail": "internal error", "request_id": …}` and logs `"unhandled error"` with the request id and **exception type only** at ERROR level. The exception message and traceback are never logged, because the message can contain secrets.
- `app = create_app()` at module level is **not** wanted, because it builds real services on import. Provide `def get_app() -> FastAPI` and run with `uvicorn clausecheck.api.main:get_app --factory --port 7860`.

### Endpoints

| Method and path | Request | Response |
|---|---|---|
| `POST /sessions` | none | `201 {"session_id"}` |
| `POST /chat` | `{"question": str (1–1000 chars), "session_id": str?, "supplier_id": str?}` | `200 ChatResponse`; `422` on an invalid body |
| `POST /chat/stream` | same as `/chat` | `200 text/event-stream`. Each event is `event: <type>\ndata: <json>\n\n`, in the order from PR 13. An exception while streaming yields `error {"message": "Something went wrong. Please try again."}` and then `done {"outcome": "error"}` |
| `GET /suppliers` | none | `200 [{"supplier_id", "display_name", "aliases"}]` |
| `GET /chunks/{chunk_id}` | none | `200` chunk fields including `text`; `404 {"detail": "chunk not found"}` |
| `GET /health` | none | `{"status", "documents", "chunks", "suppliers", "index_version", "checks": {"sqlite", "vector_store", "llm_configured"}}`. `ok`: all checks pass and chunks > 0. `degraded`: chunks = 0 or vector store failing, still 200. `down`: SQLite failing, 503 |

**`ChatResponse`** fields: `query_id`, `answer`, `outcome`, `refusal_reason`, `supplier_id`, `cached`, `unsupported`, `timings`, and `citations: [{"marker", "chunk_id", "doc_id", "page", "section", "clause_no"}]`.

## Tests

### `tests/api/conftest.py`

```python
import pytest
from fastapi.testclient import TestClient

from clausecheck.api.container import AppContainer
from clausecheck.api.main import create_app
from clausecheck.core.config import Settings
from clausecheck.rag.citation_validator import Citation
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


@pytest.fixture
def container(tmp_path):
    settings = Settings(_env_file=None, sqlite_path=tmp_path / "api.db")
    conn = db.connect(settings.sqlite_path)
    db.init_db(conn)
    db.upsert_supplier(conn, "S-ACME", "Acme Corp", ["Acme"])
    db.upsert_document(conn, {"doc_id": "doc-a", "supplier_id": "S-ACME", "source": "cuad",
                              "doc_type": "contract", "format": "pdf", "path": "data/raw/a.pdf", "title": "A"})
    db.replace_chunks(conn, "doc-a", [make_chunk(chunk_id="doc-a:p2:2_1", doc_id="doc-a", page=2)])
    query_log = QueryLog(conn)
    return AppContainer(settings=settings, conn=conn, query_service=FakeQueryService(query_log),
                        sessions=SessionStore(3), query_log=query_log,
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

### `tests/api/test_chat.py`

```python
from tests.api.conftest import parse_sse


def test_sessions(client):
    r = client.post("/sessions")
    assert r.status_code == 201 and len(r.json()["session_id"]) == 32


def test_chat_answered(client):
    r = client.post("/chat", json={"question": "Payment terms with Acme?"})
    assert r.status_code == 200
    body = r.json()
    assert body["outcome"] == "answered" and body["citations"][0]["chunk_id"] == "doc-a:p2:2_1"
    assert {"query_id", "answer", "refusal_reason", "supplier_id", "cached", "unsupported", "timings"} <= body.keys()
    assert r.headers["x-request-id"]


def test_chat_refused(client):
    body = client.post("/chat", json={"question": "please refuse"}).json()
    assert body["outcome"] == "refused" and body["citations"] == []


def test_chat_validation(client):
    assert client.post("/chat", json={"question": ""}).status_code == 422
    assert client.post("/chat", json={"question": "x" * 1001}).status_code == 422


def test_stream_event_order(client):
    r = client.post("/chat/stream", json={"question": "Payment terms with Acme?"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    types = [e for e, _ in parse_sse(r.text)]
    assert types == ["meta", "sources", "token", "token", "citations", "done"]


def test_stream_error_event(client, container):
    container.query_service.fail_with = RuntimeError("provider exploded")
    events = parse_sse(client.post("/chat/stream", json={"question": "x"}).text)
    assert [e for e, _ in events][-2:] == ["error", "done"]
    assert "exploded" not in events[-2][1]["message"]
    assert events[-1][1]["outcome"] == "error"


def test_chat_internal_error_is_generic(client, container):
    container.query_service.fail_with = RuntimeError("provider exploded")
    r = client.post("/chat", json={"question": "x"})
    assert r.status_code == 500 and r.json()["detail"] == "internal error" and "request_id" in r.json()
```

### `tests/api/test_catalog_health.py`

```python
def test_suppliers(client):
    assert client.get("/suppliers").json() == [
        {"supplier_id": "S-ACME", "display_name": "Acme Corp", "aliases": ["Acme"]}]


def test_chunk_found_and_missing(client):
    r = client.get("/chunks/doc-a:p2:2_1")
    assert r.status_code == 200 and r.json()["text"] and r.json()["page"] == 2
    assert client.get("/chunks/missing").status_code == 404


def test_health_ok(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert (body["documents"], body["chunks"], body["suppliers"]) == (1, 1, 1)
    assert body["checks"] == {"sqlite": True, "vector_store": True, "llm_configured": True}


def test_health_degraded_without_chunks(client, container):
    container.conn.execute("DELETE FROM chunks")
    container.conn.commit()
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "degraded"
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

## Manual checks

1. Run `pytest -q`. Every test should pass, including the sentinel test.
2. Run `uvicorn clausecheck.api.main:get_app --factory --port 7860` and open `http://localhost:7860/docs`. Every endpoint in the table above should be listed.
3. Run `curl -s localhost:7860/health | python -m json.tool`. Expect `"status": "ok"` with real counts.
4. Run:
   ```bash
   curl -N -X POST localhost:7860/chat/stream -H "Content-Type: application/json" \
     -d '{"question":"What are the payment terms with <real supplier>?"}'
   ```
   Events should arrive live, in the order `meta`, `sources`, `token`…, `citations`, `done`.
5. Check that every response carries an `X-Request-ID` header, and that a request that already sends one gets the same value back.
6. Check the server log while doing all of the above. No key should appear, and errors should show only a request id and the exception type.

## Definition of done

Chat (blocking and streaming), sessions, suppliers, chunk lookup and health all work and are documented in `api-design.md`, the sentinel test passes for them, and every test passes.