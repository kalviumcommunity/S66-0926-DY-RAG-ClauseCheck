# ClauseCheck: Procurement contract assistant

ClauseCheck answers plain-English questions about supplier contracts, amendments, price schedules
and compliance certificates, and backs every answer with a clause-level citation. If the contracts
do not answer the question, it says so instead of guessing.

> Example: *"What are the payment terms with Orion?"* returns "Net 45, which replaced the original
> Net 30 term [C1]", because an uploaded amendment changed clause 5.1, and the answer says so.

**Version 1** (`v1.0.0`). What changed to get here, and what is still open, is in
[debugging.md](debugging.md).

## What it does

- **Answers with citations.** Each statement ends with a marker such as `[C1]` that links to the
  exact clause (document, page, section, clause number). An answer with no valid citation is turned
  into a refusal.
- **Understands amendments.** An uploaded amendment is recognised, dated and linked to the agreement
  it changes. Answers give the amended term and say what it replaced.
- **Keeps the conversation.** Follow-ups ("And for disaster recovery?") are rewritten into full
  questions and stay on the same supplier.
- **Takes your own documents.** Upload PDF, HTML, DOCX or TXT files from the sidebar.
- **Warns about unsupported numbers.** If a sentence in the answer has no citation, the app shows a
  "check it before acting" notice.

## How an answer is produced

```
question -> rewrite follow-up -> find the supplier -> hybrid search (vector + keyword, fused)
         -> add linked amendment clauses -> re-rank -> relevance check -> build numbered context
         -> LLM answer -> check citations -> stream to the browser
```

| Part | What is used |
|---|---|
| Answer model | Groq `openai/gpt-oss-120b` first, Gemini `gemini-3.1-flash-lite` as the fallback (`LLM_PRIMARY`) |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2`, run on your machine (`EMBED_PROVIDER=local`) |
| Vector store | ChromaDB in `index/chroma` |
| Keyword search | BM25 over every chunk, built in memory at start-up |
| Re-ranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` |
| Storage | SQLite (`index/clausecheck.db`) for documents, chunks, suppliers, the answer cache, the query log and feedback. Conversation history is kept in memory, so it is lost when the backend restarts. |
| Backend | FastAPI on port 7860 (`/chat`, `/chat/stream`, `/documents`, `/suppliers`, `/health`, ...) |
| Frontend | Streamlit on port 8501 |

## The data

158 documents, about 8,000 chunks, built by `scripts/fetch_sources.py`:

| Source | Documents | Notes |
|---|---|---|
| CUAD v1 contracts | 58 | Distributor, supply and service agreements from SEC filings |
| SEC EDGAR amendments | 12 | Six amendments, each with its original (needs `EDGAR_USER_AGENT`) |
| Vendor documents | 18 | Public DPAs and SLAs from six vendors |
| Synthetic | 70 | Price schedules (DOCX) and certificates (TXT), generated with a fixed seed |

Attribution is in [NOTICE](NOTICE).

## Run it locally

Needs **Python 3.11 or newer** (tested on 3.13), an internet connection for the first run, and two
API keys: a [Gemini key](https://ai.google.dev/gemini-api/docs/api-key) and a [Groq key](https://console.groq.com).
Run every command from the repository root; `.env` is read from the current folder.

**1. Install**

```bash
git clone https://github.com/kalviumcommunity/S66-0926-DY-RAG-ClauseCheck.git
cd S66-0926-DY-RAG-ClauseCheck
git checkout debugging            # skip this once the branch is merged into main

python3 -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\activate
pip install -e . -r requirements.txt
pip install sentence-transformers==6.2.0
```

`sentence-transformers` pulls in PyTorch, so it is a large download. If a download times out, add
`--default-timeout 120 --retries 10` to the `pip install` command.

**2. Add your keys**

```bash
cp .env.example .env
```

Open `.env` and set:

```
GEMINI_API_KEY=your-gemini-key
GROQ_API_KEY=your-groq-key
EMBED_PROVIDER=local
```

`.env.example` has `EMBED_PROVIDER=gemini`; change it to `local`, otherwise indexing needs Gemini
embedding quota. `.env` is git-ignored: never commit it.

**3. Download the contracts and build the index** (one time)

```bash
python scripts/fetch_sources.py
python -m clausecheck.ingest
```

The first command downloads the corpus into `data/raw/` and writes `data/manifest.csv` and
`data/suppliers.csv`. To include the EDGAR amendments, put a contact in `.env` first, for example
`EDGAR_USER_AGENT=Your Name you@example.com`; without it EDGAR is skipped. The second command takes
a few minutes and ends with lines like:

```
total chunks: 8062
vectors in chunks_v1_sentence-transformers_all-MiniLM-L6-v2: 8062
```

The first run also downloads the two models from Hugging Face (about 175 MB).

**4. Start the backend** (terminal 1)

```bash
source .venv/bin/activate
uvicorn clausecheck.api.main:get_app --factory --port 7860
```

Check it:

```bash
curl -s localhost:7860/health
```

You want `"status":"ok"`. `"degraded"` means the index is empty or has no vectors; repeat step 3.

**5. Start the app** (terminal 2)

```bash
source .venv/bin/activate
streamlit run frontend/app.py
```

Open <http://localhost:8501>. If the backend is somewhere else, start the app with
`API_BASE_URL=http://host:port streamlit run frontend/app.py`.

**Stop** with `Ctrl+C` in each terminal. If port 7860 is still busy: `lsof -ti tcp:7860 | xargs kill`.

## Using the app

- **Ask a question.** Pick a supplier in the sidebar to limit the search to that supplier, or leave
  "All suppliers" and name the supplier in the question. Open a citation under the answer and click "View full clause" to read it.
- **Upload a document.** Choose the file, enter a **Supplier ID** (required, for example
  `helixa-cloud-systems`) and a document type, then click Upload.
- **Upload the original agreement before its amendment.** The amendment is then linked to it
  automatically and answers use the amended terms. Use the same Supplier ID for both.
- **Thumbs up or down** on an answer is saved in the database (`feedback` table). The Insights tab
  shows usage figures from the query log.

## Settings

All settings are environment variables, read through `clausecheck.core.config.Settings`.
[`.env.example`](.env.example) lists every one, and `tests/unit/test_env_example.py` fails if it and
`Settings` differ. The ones you are most likely to change:

| Setting | Value | What it does |
|---|---|---|
| `GEMINI_API_KEY`, `GROQ_API_KEY` | required | Keys are `SecretStr` and are redacted from logs. Groq is optional; without it Gemini answers and there is no fallback. |
| `LLM_PRIMARY` | `groq` | Which provider answers first; the other is the fallback. |
| `GROQ_MODEL`, `GEMINI_MODEL` | `openai/gpt-oss-120b`, `gemini-3.1-flash-lite` | Model names change; if a call returns "model not found", pick a current one. |
| `EMBED_PROVIDER` | `local` | `local` or `gemini`. Changing it, or the embedding model, means rebuilding the index. |
| `RELEVANCE_THRESHOLD` | `-8.0` | Re-ranker score below which a question is refused before the model sees it. |
| `INDEX_VERSION` | `v1` | Names the vector collection and is part of the answer-cache key. |
| `LOG_LEVEL` | `INFO` | |

## Maintenance

```bash
# After rebuilding the index or changing RELEVANCE_THRESHOLD, clear the answer cache
sqlite3 index/clausecheck.db "DELETE FROM answer_cache;"

# Rebuild the vectors from scratch (needed when EMBED_PROVIDER or the embedding model changes)
python -m clausecheck.ingest --rebuild

# Usage summary from the query log
python scripts/usage_report.py
```

**`--rebuild` deletes the whole vector store and re-indexes only the corpus in
`data/manifest.csv`. Documents you uploaded are not re-indexed, so upload them again.**

## Tests and evaluation

```bash
pytest -q -m "not targets"        # 262 pass; 2 end-to-end tests are skipped without a server
ruff check . && black --check .

# Ten live questions from the labelled set through the whole pipeline (uses your API keys)
python -m eval.run_eval --split tune --stage e2e --limit 10
```

The labelled questions are in `eval/questions.jsonl`; results are written to `eval/results/`.
See [eval/README.md](eval/README.md). CI (`.github/workflows/ci.yml`) runs lint, a secrets scan,
the tests and a dry-run ingest on pull requests, and the `eval-smoke` job on pushes to `main`.

## If something goes wrong

| What you see | Why, and what to do |
|---|---|
| App shows "backend down" or "couldn't generate an answer" | The backend is not running, or both models failed. Check `curl localhost:7860/health`, then the backend terminal; a failed model call is logged with its HTTP status. |
| `/health` says `degraded` | The index is empty or has no vectors. Run `python -m clausecheck.ingest`. |
| `address already in use` | An older server holds the port: `lsof -ti tcp:7860 | xargs kill`. |
| Old answers after changing the index or threshold | The cache. Run the `DELETE FROM answer_cache` command above. |
| "I couldn't find this" for something in a contract | Name the supplier in the question or pick it in the sidebar, and upload the original before its amendment. Rewording usually helps. |
| `404 model not found` in the log | A provider retired the model; set a current `GEMINI_MODEL` or `GROQ_MODEL`. |
| `pip install` times out | Add `--default-timeout 120 --retries 10`. On a network that inspects HTTPS, pip may also need the proxy's certificate. |

## Known limits in version 1

- One conversation can switch between contracts; separate chats per contract are not built yet.
- When both Groq and Gemini fail (rate limits), a request can take 40+ seconds and end in the
  generic error message.
- About 1 in 30 answerable test questions is still declined by the model.
- Thresholds and model choices were tuned on 40 labelled questions, a small sample.
- A `Dockerfile` is included but has not been built or tested, and nothing is deployed.

## Folder map

| Path | What is in it |
|---|---|
| `clausecheck/` | The Python package: `core`, `ingest`, `rag`, `store`, `llm`, `services`, `api`, `prompts` |
| `frontend/` | Streamlit app |
| `scripts/` | Corpus download, synthetic data, validation, bootstrap and usage report |
| `eval/` | Labelled questions, evaluation runner and results |
| `data/` | Corpus manifest and suppliers list; `raw/` and `uploads/` are git-ignored |
| `index/` | SQLite database and vector store (created by the ingest, git-ignored) |
| `tests/` | `unit/`, `integration/`, `api/`, `frontend/` and `e2e/` tests |
| `notebooks/` | Exploration notebooks (outputs stripped by `nbstripout`) |
| `docs/` | Requirements, planning, architecture, data and UX documents; start with the [team charter](docs/team-charter.md) and the [PRD](docs/requirements/PRD.md) |
| `debugging.md` | Log of everything fixed on the way to version 1 |

Contributors: `pre-commit install` sets up the lint, formatting and secret-scan hooks.
