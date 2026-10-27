# PR 12 · Streamlit frontend, deployment and the final report

**Branch:** `b-frontend-deploy` · **Owner:** Teammate (Generation, Application & Delivery) · **Week:** 5 · **Depends on:** PR 11

## Context

The frontend is a Streamlit app on **Streamlit Community Cloud**. It only calls the backend API and holds just one secret, `API_BASE_URL`. The backend runs as a Docker container on **Hugging Face Spaces** (port 7860).

The UI follows the mock UX:
- answers stream in, with sources as one expander per citation and a "view full clause" button
- refusals appear in a grey `st.info` box so they can't be mistaken for a term
- the sidebar has a supplier filter, new conversation, an upload form with job polling, and index status
- an **Insights** tab shows five KPI cards above the fold, plus charts and tables

This PR also produces the **held-out evaluation report**, the QA checklist and the final README.

Read before starting:
- `docs/ux/mock-ux.md`: screens S-01 to S-12, the copy deck, the KPI cards and fold line, the Insights tab
- `docs/ux/ui-states.md`: loading, streaming, refusal, error and empty-corpus states
- `docs/architecture/tdd.md` §9 (frontend components, session state) and §10 (deployment)
- `docs/planning/development-plan.md` §15 (final submission checklist)

## Scope (only these files)

| Path | Action |
|---|---|
| `frontend/app.py` | add (remove `frontend/.gitkeep`) |
| `frontend/components/__init__.py`, `api_client.py`, `sse_client.py`, `chat.py`, `sources.py`, `sidebar.py`, `insights.py` | add |
| `frontend/requirements.txt` | add: `streamlit`, `httpx`, `pandas`, pinned |
| `requirements.txt` | modify: add `streamlit` (pinned, same version) so CI can run the frontend tests |
| `frontend/.streamlit/config.toml`, `frontend/.streamlit/secrets.toml.example` | add |
| `Dockerfile`, `.dockerignore` | add |
| `scripts/bootstrap.py`, `scripts/usage_report.py` | add |
| `clausecheck/core/config.py`, `.env.example` | modify: `index_archive_url: str = ""` |
| `.github/workflows/ci.yml` | modify: see spec |
| `tests/frontend/__init__.py`, `tests/frontend/conftest.py`, `tests/frontend/test_sse_client.py`, `test_api_client.py`, `test_chat_helpers.py`, `test_insights_format.py`, `test_app_smoke.py` | add |
| `tests/unit/test_bootstrap.py`, `tests/unit/test_usage_report.py`, `tests/unit/test_deploy_files.py` | add |
| `tests/e2e/__init__.py`, `tests/e2e/test_live.py` | add |
| `eval/results/<date>_e2e_heldout.json` | add: one held-out run, W5 D4 |
| `docs/evaluation/final-report.md`, `docs/qa.md` | add |
| `docs/architecture/tdd.md`, `docs/planning/development-plan.md`, `README.md` | modify |

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

### Deployment files

- **`Dockerfile`**:
  - `python:3.11-slim` base, non-root user, `WORKDIR /app`
  - copy `pyproject.toml`, `requirements.txt`, `clausecheck/`, `scripts/` and `data/*.csv`, then `pip install --no-cache-dir -e .`
  - pre-download the re-ranker into the image (`python -c "from sentence_transformers import CrossEncoder; CrossEncoder('<RERANK_MODEL>')"`)
  - `ENV INDEX_DIR=/data/index SQLITE_PATH=/data/index/clausecheck.db`
  - `EXPOSE 7860`
  - `CMD ["sh", "-c", "python scripts/bootstrap.py && uvicorn clausecheck.api.main:get_app --factory --host 0.0.0.0 --port 7860"]`
  - Never copies `.env`.
- **`.dockerignore`**: `.env`, `.git`, `.venv`, `index/`, `data/raw/`, `data/uploads/`, `tests/`, `notebooks/`, `frontend/`, `**/__pycache__`.
- **`scripts/bootstrap.py`**:
  - `ensure_index(settings, build_fn=None, download_fn=None) -> str`:
    - if the SQLite DB exists and has more than 0 chunks, return `"present"`
    - else if `settings.index_archive_url` is set, call `download_fn(url, settings.index_dir)` (default: download and extract a `.tar.gz`) and return `"restored"`
    - else call `build_fn()` (default: run `fetch_sources`, `generate_synthetic --seed 42`, then `python -m clausecheck.ingest --rebuild`) and return `"built"`
  - `pack(index_dir, out_path) -> Path` creates the `.tar.gz` that is uploaded wherever `INDEX_ARCHIVE_URL` points (for example a Hugging Face dataset repo or a GitHub release asset, whichever `tdd.md` §10 chose).
  - `main()` prints the result.
- **`scripts/usage_report.py`**: `summarize(conn) -> dict` with keys `total`, `by_outcome`, `median_latency_ms`, `median_ttft_ms` and `cache_hit_rate`, and a `main()` that prints them.
- **`.github/workflows/ci.yml` additions**:
  1. A `clean-clone-ingest` job on PRs that runs `python -m clausecheck.ingest --dry-run` on `tests/fixtures`-style generated data, by calling a small step that builds the fixtures and a manifest.
  2. On `push` to `main`: an `eval-smoke` job that runs 10 tuning questions with the real APIs, using the `GEMINI_API_KEY` and `GROQ_API_KEY` secrets.
  3. A `deploy` job, `needs: [lint, secrets, test, eval-smoke]`, that pushes to the Hugging Face Space with the `HF_TOKEN` secret.

### Final documents

- **`docs/evaluation/final-report.md`**:
  - the held-out results vs every target (recall@5 ≥ 0.85, correctness ≥ 85%, citation accuracy ≥ 90%, correct refusals ≥ 90%, median TTFT < 3 s)
  - the ablation table, the threshold curve, latency (median and p90), judge agreement
  - index version, prompt versions and settings
  - an honest explanation of any shortfall
- **`docs/qa.md`**: the manual checklist below as `- [ ]` items, with results and dates filled in.

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

### `tests/unit/test_bootstrap.py`

```python
import importlib.util
from pathlib import Path

from clausecheck.core.config import Settings
from clausecheck.store import sqlite as db
from tests.helpers import make_chunk

ROOT = Path(__file__).resolve().parents[2]


def _mod():
    spec = importlib.util.spec_from_file_location("bootstrap", ROOT / "scripts/bootstrap.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_builds_when_missing_and_skips_when_present(tmp_path):
    boot = _mod()
    s = Settings(_env_file=None, index_dir=tmp_path / "idx", sqlite_path=tmp_path / "idx" / "c.db")
    built = []

    def build():
        conn = db.connect(s.sqlite_path)
        db.init_db(conn)
        db.upsert_document(conn, {"doc_id": "doc-a", "supplier_id": "S-ACME", "doc_type": "contract"})
        db.replace_chunks(conn, "doc-a", [make_chunk()])
        built.append(True)

    assert boot.ensure_index(s, build_fn=build) == "built"
    assert boot.ensure_index(s, build_fn=build) == "present"
    assert built == [True]


def test_restores_from_archive_url(tmp_path):
    boot = _mod()
    s = Settings(_env_file=None, index_dir=tmp_path / "idx", sqlite_path=tmp_path / "idx" / "c.db",
                 index_archive_url="https://example.com/index.tar.gz")
    calls = []
    assert boot.ensure_index(s, build_fn=lambda: None, download_fn=lambda url, d: calls.append(url)) == "restored"
    assert calls == ["https://example.com/index.tar.gz"]


def test_pack_creates_archive(tmp_path):
    boot = _mod()
    (tmp_path / "idx").mkdir()
    (tmp_path / "idx" / "c.db").write_bytes(b"x")
    out = boot.pack(tmp_path / "idx", tmp_path / "index.tar.gz")
    assert out.exists() and out.stat().st_size > 0
```

### `tests/unit/test_usage_report.py`

```python
import importlib.util
from pathlib import Path

from clausecheck.store import sqlite as db
from clausecheck.store.query_log import QueryLog

ROOT = Path(__file__).resolve().parents[2]


def test_summarize(tmp_path):
    spec = importlib.util.spec_from_file_location("usage_report", ROOT / "scripts/usage_report.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    conn = db.connect(tmp_path / "u.db")
    log = QueryLog(conn)
    for i, (outcome, ms, cached) in enumerate([("answered", 1000, False), ("refused", 3000, False),
                                               ("answered", 2000, True)]):
        log.log({"query_id": f"q{i}", "created_at": f"2026-11-2{i}T10:00:00", "question": "q",
                 "outcome": outcome, "latency_ms": ms, "ttft_ms": ms / 2, "cached": cached})
    s = mod.summarize(conn)
    assert s["total"] == 3 and s["by_outcome"] == {"answered": 2, "refused": 1}
    assert s["median_latency_ms"] == 2000 and s["cache_hit_rate"] == 1 / 3
```

### `tests/unit/test_deploy_files.py`

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_dockerfile():
    text = (ROOT / "Dockerfile").read_text()
    assert "EXPOSE 7860" in text and "bootstrap.py" in text and "--factory" in text
    assert ".env" not in text.replace(".env.example", "")


def test_dockerignore_excludes_secrets_and_data():
    lines = {l.strip() for l in (ROOT / ".dockerignore").read_text().splitlines()}
    assert {".env", "index/", "data/raw/"} <= lines


def test_frontend_secrets_example_only():
    import shutil
    import subprocess

    assert (ROOT / "frontend/.streamlit/secrets.toml.example").exists()
    if shutil.which("git") and (ROOT / ".git").exists():
        tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.splitlines()
        assert "frontend/.streamlit/secrets.toml" not in tracked


def test_ci_has_deploy_and_eval_smoke():
    text = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "HF_TOKEN" in text and "eval-smoke" in text and "deploy" in text
```

### `tests/e2e/test_live.py`

```python
"""Runs against a deployed backend. Skipped unless CLAUSECHECK_E2E=1 and CLAUSECHECK_API_URL are set."""
import os

import httpx
import pytest

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(os.getenv("CLAUSECHECK_E2E") != "1", reason="set CLAUSECHECK_E2E=1 to run"),
]
API = os.getenv("CLAUSECHECK_API_URL", "http://localhost:7860")
QUESTION = os.getenv("CLAUSECHECK_E2E_QUESTION", "What are the payment terms?")


def test_health_ok():
    body = httpx.get(f"{API}/health", timeout=30).json()
    assert body["status"] == "ok" and body["chunks"] > 0


def test_chat_answers_or_refuses_cleanly():
    body = httpx.post(f"{API}/chat", json={"question": QUESTION}, timeout=60).json()
    assert body["outcome"] in {"answered", "refused"}
    if body["outcome"] == "answered":
        assert body["citations"]
```

## Manual checks (copy these into `docs/qa.md`)

1. Run `pytest -q` on the whole repo. Everything should pass, with `e2e` tests skipped.
2. Local run: start `uvicorn clausecheck.api.main:get_app --factory --port 7860` in one terminal, and `cd frontend && API_BASE_URL=http://localhost:7860 streamlit run app.py` in another.
3. In the browser window at **1366×768**:
   - [ ] The five KPI cards on the Insights tab are visible without scrolling.
   - [ ] A question streams, and the sources show one expander per citation. "View full clause" opens the text.
   - [ ] An unanswerable question shows the grey refusal box.
   - [ ] A follow-up ("and their notice period?") keeps the supplier.
   - [ ] The supplier filter restricts the answers.
   - [ ] Upload: a new file is polled until done and is then answerable. Duplicate, too-large and wrong-type uploads show the right messages.
   - [ ] Stopping the backend shows the "backend down" message, and the page doesn't crash.
   - [ ] Feedback buttons work. (Check with `SELECT * FROM feedback`.)
4. Docker: run `docker build -t clausecheck .` and `docker run -p 7860:7860 --env-file .env -v $PWD/index:/data/index clausecheck`. `/health` should show `ok`.
5. Deploy the backend to the HF Space (Docker) with the secrets `GEMINI_API_KEY`, `GROQ_API_KEY` and `INDEX_ARCHIVE_URL`, and the frontend to Streamlit Cloud with the secret `API_BASE_URL`. Repeat step 3 on the public URLs in a private window.
6. Run `CLAUSECHECK_E2E=1 CLAUSECHECK_API_URL=<space url> pytest tests/e2e -q`. Expect 2 passed.
7. **W5 D4 only:** run `python -m eval.run_eval --split heldout --stage e2e --allow-heldout` once, then write `docs/evaluation/final-report.md`.
8. Run `gitleaks detect` on the full history. Expect 0 findings (AC-N2.4).
9. Make a fresh clone and follow only the README. The index should rebuild with one command.
10. Tick every item in `development-plan.md` §15.

## Definition of done

The public URLs work end to end, the held-out report is written, the QA checklist is complete, the README is final, and every test passes.
