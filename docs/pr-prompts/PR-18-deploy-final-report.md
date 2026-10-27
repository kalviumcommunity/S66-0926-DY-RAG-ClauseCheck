# PR 18 · Deployment, held-out evaluation and the final report

**Branch:** `b-deploy-final-report` · **Owner:** Teammate (Generation, Application & Delivery) · **Week:** 5 · **Depends on:** PR 17

## Context

This is the last PR. The backend runs as a Docker container on **Hugging Face Spaces** (port 7860) and the Streamlit frontend runs on **Streamlit Community Cloud** with the single secret `API_BASE_URL`.

This PR adds:
- the Dockerfile, the index bootstrap script and the usage report
- the CI additions (clean-clone ingest, eval smoke, deploy)
- the **held-out evaluation run**, the final report, the QA checklist and the final README

Read before starting:
- `docs/ux/ui-states.md`: error and empty-corpus states (re-checked on the public URLs)
- `docs/architecture/tdd.md` §10 (deployment)
- `docs/planning/development-plan.md` §15 (final submission checklist)

## Scope (only these files)

| Path | Action |
|---|---|
| `Dockerfile`, `.dockerignore` | add |
| `scripts/bootstrap.py`, `scripts/usage_report.py` | add |
| `clausecheck/core/config.py`, `.env.example` | modify: `index_archive_url: str = ""` |
| `.github/workflows/ci.yml` | modify: see spec |
| `tests/unit/test_bootstrap.py`, `test_usage_report.py`, `test_deploy_files.py` | add |
| `tests/e2e/__init__.py`, `tests/e2e/test_live.py` | add |
| `eval/results/<date>_e2e_heldout.json` | add: one held-out run, W5 D4 |
| `docs/evaluation/final-report.md`, `docs/qa.md` | add |
| `docs/architecture/tdd.md`, `docs/planning/development-plan.md`, `README.md` | modify |

`development-plan.md` should also show the final PR list (PR 9 to PR 18) so it matches what was actually merged.

## Specification

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

For `docs/qa.md`, include the browser checklist from PR 17 (with its results) **and** the checks listed under "Manual checks" below.

## Tests

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
2. Docker: run `docker build -t clausecheck .` and `docker run -p 7860:7860 --env-file .env -v $PWD/index:/data/index clausecheck`. `/health` should show `ok`.
3. Deploy the backend to the HF Space (Docker) with the secrets `GEMINI_API_KEY`, `GROQ_API_KEY` and `INDEX_ARCHIVE_URL`, and the frontend to Streamlit Cloud with the secret `API_BASE_URL`. Repeat the **PR 17 browser checklist** on the public URLs in a private window.
4. Run `CLAUSECHECK_E2E=1 CLAUSECHECK_API_URL=<space url> pytest tests/e2e -q`. Expect 2 passed.
5. **W5 D4 only:** run `python -m eval.run_eval --split heldout --stage e2e --allow-heldout` once, then write `docs/evaluation/final-report.md`.
6. Run `gitleaks detect` on the full history. Expect 0 findings (AC-N2.4).
7. Make a fresh clone and follow only the README. The index should rebuild with one command.
8. Tick every item in `development-plan.md` §15.

## Definition of done

The public URLs work end to end, the held-out report is written, the QA checklist is complete, the README is final, and every test passes.