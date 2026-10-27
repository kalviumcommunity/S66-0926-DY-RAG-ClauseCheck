# PR 17 · Streamlit frontend

**Branch:** `b-streamlit-frontend` · **Owner:** Teammate (Generation, Application & Delivery) · **Week:** 5 · **Depends on:** PR 16

## Context

The frontend is a Streamlit app (to be hosted on **Streamlit Community Cloud** in PR 18). It only calls the backend API and holds just one secret, `API_BASE_URL`.

The UI follows the mock UX:
- answers stream in, with sources as one expander per citation and a "view full clause" button
- refusals appear in a grey `st.info` box so they can't be mistaken for a term
- the sidebar has a supplier filter, new conversation, an upload form with job polling, and index status
- an **Insights** tab shows five KPI cards above the fold, plus charts and tables

This PR is local only. It must run against `uvicorn` on your machine. Docker, deployment and the final report are PR 18.

Read before starting:
- `docs/ux/mock-ux.md`: screens S-01 to S-12, the copy deck, the KPI cards and fold line, the Insights tab
- `docs/ux/ui-states.md`: loading, streaming, refusal, error and empty-corpus states
- `docs/architecture/tdd.md` §9 (frontend components, session state)

## Scope (only these files)

| Path | Action |
|---|---|
| `frontend/app.py` | add (remove `frontend/.gitkeep`) |
| `frontend/components/__init__.py`, `api_client.py`, `sse_client.py`, `chat.py`, `sources.py`, `sidebar.py`, `insights.py` | add |
| `frontend/requirements.txt` | add: `streamlit`, `httpx`, `pandas`, pinned |
| `requirements.txt` | modify: add `streamlit` (pinned, same version) so CI can run the frontend tests |
| `frontend/.streamlit/config.toml`, `frontend/.streamlit/secrets.toml.example` | add |
| `tests/frontend/__init__.py`, `conftest.py`, `test_sse_client.py`, `test_api_client.py`, `test_chat_helpers.py`, `test_insights_format.py`, `test_app_smoke.py` | add |

## Specification

### `frontend/components/api_client.py`

- `class ApiUnavailable(Exception)`
- `class ApiClient(base_url: str, timeout: float = 15.0, client: httpx.Client | None = None)` with methods:
  - `health()`, `suppliers()`, `new_session()`, `chunk(chunk_id)`
  - `upload(filename, content, supplier_id, doc_type)`, which returns `{"job_id"}`, or `{"duplicate": True, "doc_id"}` on 409, and raises `ValueError(detail)` on 413/415
  - `job(job_id)`, `feedback(query_id, rating)`, `kpis()`, `charts()`, `tables()`
- Connection errors and timeouts raise `ApiUnavailable`. Other non-2xx responses raise `httpx.HTTPStatusError`.

### `frontend/components/sse_client.py`

- `parse_sse(lines: Iterable[str]) -> Iterator[tuple[str, dict]]`: understands `event:` and `data:` lines, with a blank line ending an event. It ignores comment lines starting with `:` and joins multi-line `data`.
- `stream_chat(base_url, payload: dict, client: httpx.Client | None = None, timeout=60.0) -> Iterator[tuple[str, dict]]`: POSTs to `/chat/stream` with `httpx.stream` and yields parsed events. If the connection fails, it yields `("error", {"message": BACKEND_DOWN})` and then `("done", {"outcome": "error"})`.
- `BACKEND_DOWN`: the copy-deck message for a backend that can't be reached.

### `frontend/components/chat.py`

- `class StreamCollector(events: Iterable[tuple[str, dict]])`: iterating it yields **only token texts**, which makes it usable with `st.write_stream`, and stores everything else. Afterwards `.message` returns `{"role": "assistant", "content", "citations", "sources", "outcome", "refusal_reason", "query_id", "unsupported", "error"}`.
- **No-citation rule:** if `done.outcome == "refused"` and `refusal_reason == "no_citations"`, `.message["content"]` is replaced with `REFUSAL_COPY`. The UI shows the refusal box instead of the streamed text, as described in `ui-states.md`.
- `render_message(msg, api)`:
  - outcome `refused`: a grey `st.info` box
  - outcome `error`: `st.error`
  - `unsupported=True`: an `st.warning` under the answer using the copy-deck wording
  - otherwise: markdown, then `sources.render_sources(...)` and 👍/👎 feedback buttons
- `REFUSAL_COPY` is taken from the copy deck and must match the backend's `REFUSAL_TEXT`.

### `frontend/components/sources.py`

`render_sources(citations, sources, api)`: one `st.expander` per citation, titled `[C1] doc · page · clause`. A button inside loads `/chunks/{id}` and shows the full clause text.

### `frontend/components/sidebar.py`

- Supplier select box, with suppliers cached for 5 minutes via `st.cache_data(ttl=300)`.
- New conversation button (`POST /sessions`, then clears messages).
- Upload form (file, supplier, doc type): polls the job every 2 s until `done` or `failed`, and shows the result with the copy-deck messages for duplicate, too large and wrong type.
- Index status from `/health`, showing documents, chunks and suppliers, with a badge for `ok`, `degraded` or `down`.

### `frontend/components/insights.py`

- `format_kpi(key: str, value) -> str`:
  - rates (`answer_rate`, `citation_accuracy`) become `"87%"` (rounded)
  - `*_ms` values become `"1.2 s"` (one decimal), or `"850 ms"` below 1000
  - counts become `"1,234"`
  - `None` becomes `"—"`
- `KPI_LABELS: dict[str, str]`: the five card titles from the mock UX, in display order.
- `render_insights(api)`: five `st.metric` cards in one row at the top, then four charts (outcomes by day as stacked bars, latency by day with a 3 s target line, questions by topic, documents by source) and four tables (supplier activity, unanswered questions with an upload hint, evaluation vs targets, coverage).

### `frontend/app.py`

- Page config: wide layout, title "ClauseCheck".
- `API_BASE_URL` comes from `st.secrets` if present, then the environment variable, then `http://localhost:7860`.
- Session state keys from `tdd.md` §9.3: `session_id`, `messages`, `supplier_filter`, `upload_job_id`, `api_base_url`.
- Two tabs, **Chat** and **Insights**. The chat input sends `{"question", "session_id", "supplier_id"}` through `stream_chat`, wrapped in `StreamCollector` and rendered with `st.write_stream`. The message is then replaced with `render_message(collector.message)`.
- If `/health` raises `ApiUnavailable` at start-up, show `st.error(BACKEND_DOWN)` and keep the page usable. **Never crash.**
- An empty corpus (`chunks == 0`) shows the empty-corpus state from `ui-states.md`.

## Tests

### `tests/frontend/conftest.py`

```python
import sys
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
if str(FRONTEND) not in sys.path:
    sys.path.insert(0, str(FRONTEND))
```

### `tests/frontend/test_sse_client.py`

```python
import httpx

from components.sse_client import BACKEND_DOWN, parse_sse, stream_chat


def test_parse_sse_events():
    lines = ["event: meta", 'data: {"query_id": "q"}', "", ": keep-alive", "",
             "event: token", 'data: {"text": "Net "}', "", "event: token", 'data: {"text": "45"}', ""]
    assert list(parse_sse(lines)) == [("meta", {"query_id": "q"}), ("token", {"text": "Net "}),
                                      ("token", {"text": "45"})]


def test_stream_chat_parses_live_response():
    body = 'event: token\ndata: {"text": "Hi"}\n\nevent: done\ndata: {"outcome": "answered"}\n\n'

    def handler(request):
        assert request.url.path == "/chat/stream"
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://api")
    events = list(stream_chat("http://api", {"question": "q"}, client=client))
    assert events == [("token", {"text": "Hi"}), ("done", {"outcome": "answered"})]


def test_stream_chat_backend_down():
    def handler(request):
        raise httpx.ConnectError("refused")

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://api")
    events = list(stream_chat("http://api", {"question": "q"}, client=client))
    assert events == [("error", {"message": BACKEND_DOWN}), ("done", {"outcome": "error"})]
```

### `tests/frontend/test_api_client.py`

```python
import httpx
import pytest

from components.api_client import ApiClient, ApiUnavailable


def _client(handler):
    return ApiClient("http://api", client=httpx.Client(transport=httpx.MockTransport(handler), base_url="http://api"))


def test_health_and_suppliers():
    def handler(request):
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "chunks": 5})
        return httpx.Response(200, json=[{"supplier_id": "S-ACME", "display_name": "Acme Corp", "aliases": []}])

    api = _client(handler)
    assert api.health()["status"] == "ok"
    assert api.suppliers()[0]["supplier_id"] == "S-ACME"


def test_upload_outcomes():
    responses = iter([httpx.Response(202, json={"job_id": "j1"}),
                      httpx.Response(409, json={"detail": "duplicate", "doc_id": "doc-a"}),
                      httpx.Response(415, json={"detail": "unsupported file type"})])
    api = _client(lambda request: next(responses))
    assert api.upload("a.pdf", b"x", "S-ACME", "contract") == {"job_id": "j1"}
    assert api.upload("a.pdf", b"x", "S-ACME", "contract") == {"duplicate": True, "doc_id": "doc-a"}
    with pytest.raises(ValueError):
        api.upload("a.exe", b"x", "S-ACME", "contract")


def test_unavailable():
    def handler(request):
        raise httpx.ConnectError("down")

    with pytest.raises(ApiUnavailable):
        _client(handler).health()
```

### `tests/frontend/test_chat_helpers.py`

```python
from components.chat import REFUSAL_COPY, StreamCollector


def _events(outcome="answered", reason=None):
    return [("meta", {"query_id": "q-1", "supplier_id": "S-ACME"}),
            ("sources", {"sources": [{"marker": "C1", "chunk_id": "c1"}]}),
            ("token", {"text": "Net "}), ("token", {"text": "45 [C1]."}),
            ("citations", {"citations": [{"marker": "C1", "chunk_id": "c1"}], "unsupported": False}),
            ("done", {"outcome": outcome, "refusal_reason": reason, "timings": {}})]


def test_collector_yields_only_tokens_and_builds_message():
    c = StreamCollector(_events())
    assert "".join(c) == "Net 45 [C1]."
    m = c.message
    assert m["role"] == "assistant" and m["content"] == "Net 45 [C1]." and m["query_id"] == "q-1"
    assert m["citations"][0]["chunk_id"] == "c1" and m["outcome"] == "answered"


def test_no_citation_refusal_replaces_content():
    c = StreamCollector(_events("refused", "no_citations"))
    list(c)
    assert c.message["content"] == REFUSAL_COPY and c.message["outcome"] == "refused"


def test_error_event_recorded():
    c = StreamCollector([("error", {"message": "Backend down"}), ("done", {"outcome": "error"})])
    assert list(c) == []
    assert c.message["outcome"] == "error" and c.message["error"] == "Backend down"


def test_refusal_copy_matches_backend():
    from clausecheck.rag.generator import REFUSAL_TEXT

    assert REFUSAL_COPY == REFUSAL_TEXT
```

### `tests/frontend/test_insights_format.py`

```python
from components.insights import KPI_LABELS, format_kpi


def test_format_kpi():
    assert format_kpi("answer_rate", 0.8666) == "87%"
    assert format_kpi("citation_accuracy", None) == "—"
    assert format_kpi("median_ttft_ms", 1234.0) == "1.2 s"
    assert format_kpi("median_ttft_ms", 850.0) == "850 ms"
    assert format_kpi("questions_asked", 1234) == "1,234"


def test_five_kpi_cards():
    assert list(KPI_LABELS) == ["questions_asked", "answer_rate", "median_time_to_checked_answer_ms",
                                "median_ttft_ms", "citation_accuracy"]
```

### `tests/frontend/test_app_smoke.py`

```python
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[2] / "frontend" / "app.py"


def test_app_renders_without_backend():
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.secrets["API_BASE_URL"] = "http://127.0.0.1:9"
    at.run()
    assert not at.exception
    assert len(at.error) >= 1
    assert len(at.tabs) == 2
```

## Manual checks

1. Run `pytest -q` on the whole repo. Everything should pass.
2. Local run: start `uvicorn clausecheck.api.main:get_app --factory --port 7860` in one terminal, and `cd frontend && API_BASE_URL=http://localhost:7860 streamlit run app.py` in another.
3. In the browser window at **1366×768**, tick each item and write the date and result next to it in the PR description (PR 18 copies this list into `docs/qa.md`):
   - [ ] The five KPI cards on the Insights tab are visible without scrolling.
   - [ ] A question streams, and the sources show one expander per citation. "View full clause" opens the text.
   - [ ] An unanswerable question shows the grey refusal box.
   - [ ] A follow-up ("and their notice period?") keeps the supplier.
   - [ ] The supplier filter restricts the answers.
   - [ ] Upload: a new file is polled until done and is then answerable. Duplicate, too-large and wrong-type uploads show the right messages.
   - [ ] Stopping the backend shows the "backend down" message, and the page doesn't crash.
   - [ ] Feedback buttons work. (Check with `SELECT * FROM feedback`.)
4. Open the app with an empty index (no chunks). The empty-corpus state from `ui-states.md` should appear.

## Definition of done

The UI runs locally against the API and passes every item of the checklist above, the refusal box, unsupported warning and backend-down states match `ui-states.md`, and every test passes.