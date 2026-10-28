# ClauseCheck: Procurement contract assistant

ClauseCheck answers plain-English questions about supplier contracts, amendments, price schedules
and compliance certificates, and backs every answer with a clause-level citation. If the contracts
do not answer the question, it says so instead of guessing.

> Example: *"What are the payment terms with Orion?"* returns "Net 45, which replaced the original
> Net 30 term [C1]", because an uploaded amendment changed clause 5.1, and the answer says so.

**Version 1** (`v1.0.0`). What changed to get here, and what is still open, is in
[debugging.md](debugging.md). Since `v1.0.0`: every contract has its own conversation, and there
is a separate New contract analyser page ([version02.md](version02.md)); the interface was then
redesigned to the website spec, with a contract register, checked answers and a service report
([version03.md](version03.md)).

## What it does

- **Answers with citations.** Each statement ends with a marker such as `[C1]` that links to the
  exact clause (document, page, section, clause number). An answer with no valid citation is turned
  into a refusal.
- **Understands amendments.** An uploaded amendment is recognised, dated and linked to the agreement
  it changes. Answers give the amended term and say what it replaced.
- **One conversation per contract.** You choose a contract, and the search and the conversation
  are limited to it. Every contract keeps its own history, and a question that names a different
  contract is refused with a pointer to that contract, so an answer is never about the wrong one.
- **Keeps the conversation.** Follow-ups ("And for disaster recovery?") are rewritten into full
  questions and stay on the same contract.
- **Files your own contract.** The **Contracts** page takes a contract and its amendments (PDF,
  HTML, DOCX or TXT), shows each indexing step as it happens, and then lets you check its terms.
- **Warns about unsupported numbers.** If a sentence in the answer has no citation, the app shows a
  "check it before acting" notice.

## How an answer is produced

```
question -> rewrite follow-up -> stay on the chosen contract (refuse if it names another one)
         -> hybrid search (vector + keyword, fused) -> add linked amendment clauses -> re-rank
         -> relevance check -> build numbered context -> LLM answer -> check citations
         -> stream to the browser
```

The Ask and Contracts pages always send the chosen contract, so the search never
leaves it. Called without one, the API finds the supplier named in the question instead.

| Part | What is used |
|---|---|
| Answer model | Groq `openai/gpt-oss-120b` first, Gemini `gemini-3.1-flash-lite` as the fallback (`LLM_PRIMARY`) |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2`, run on your machine (`EMBED_PROVIDER=local`) |
| Vector store | ChromaDB in `index/chroma` |
| Keyword search | BM25 over every chunk, built in memory at start-up |
| Re-ranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` |
| Storage | SQLite (`index/clausecheck.db`) for documents, chunks, suppliers, the answer cache, the query log and feedback. Conversation history is kept in memory, so it is lost when the backend restarts. |
| Backend | FastAPI on port 7860 (`/chat`, `/chat/stream`, `/documents`, `/contracts`, `/checks/recent`, `/insights/report`, `/suppliers`, `/health`, ...) |
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

Run it from the repository root, so Streamlit finds `.streamlit/config.toml` (theme, 20 MB upload
limit) and the fonts in `frontend/static/`. After changing code or CSS, restart it. Open
<http://localhost:8501>. If the backend is somewhere else, start the app with
`API_BASE_URL=http://host:port streamlit run frontend/app.py`.

**Stop** with `Ctrl+C` in each terminal. If port 7860 is still busy: `lsof -ti tcp:7860 | xargs kill`.

## Using the app

There is no sidebar. The tabs at the top are **Ask**, **Contracts** and **Insights**, with the
index status beside them and the five headline numbers under them.

**Ask**
- The page opens on the **contract register**. Search it, or press **Check** on a row. Each contract
  has its own conversation, so nothing carries over between contracts.
- Type a question. While it runs you see the real steps and their times. The result is a **check
  record**: the answer, a **Terms found** table (value, source, status), and a seal. **Checked**
  means every citation and number was found in the cited clauses; **Verify** names what was not.
  The cited clause is shown on the right as a page, with the words the answer relies on
  highlighted; **C1, C2…** switch between clauses.
- **No term found** means the contract has nothing on it, and nothing was guessed. A red **System
  failure** is not a finding; use **Try again**.
- **Documents (n)** lists the contract's files and which agreement each amendment changes.
  **New check** starts over for this contract only. **Download as a note** saves a check as text.

**Contracts**
1. Name the contract, choose the main agreement, its type and its effective date (as written in
   the contract; leave it empty to read it from the document).
2. Add amendments in the order they were signed, each with its date and the document it changes.
3. **File and index.** The filing log on the right lists each step with its time and counts. When
   it is ready, **Check** opens the contract on the Ask page. The same page can add a document to
   the contract you are checking.

**Insights** is a dated service report: a one-sentence headline, a scorecard against the targets,
the outcomes, what people asked about, the unanswered questions and the failures, with a CSV
download. The targets are 80% of questions answered with sources, first words within 3.0 s, a
checked answer within 30.0 s and 90% citation accuracy. A measure that has not been taken (citation
accuracy, until `python -m eval.run_eval` has run) is shown as "Not measured", not as zero.

**Landing page.** `site/index.html` is a static page (open it, or host it anywhere) with a real
screenshot of the app and the latest figures from `site/results.json`. Refresh the figures with
`python scripts/update_site_data.py`. Its "Open ClauseCheck" button points to
`http://localhost:8501`; change it when the app has a URL.

Everything about this redesign, including where it differs from the spec, is in
[version03.md](version03.md).

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
pytest -q -m "not targets"        # 375 pass, 4 are skipped (they need a running backend)
ruff check . && black --check .
```

| Folder | What it covers | Tests |
|---|---|---|
| `tests/unit/` | One module at a time: chunker, cleaner, retrieval fusion, re-ranker, supplier detector, citation checker, settings, the eval runner as a command | 247 |
| `tests/integration/` | Several parts together with fake models: ingest, hybrid retrieval, the query service, uploads, one conversation per contract | 54 |
| `tests/api/` | The FastAPI endpoints with a fake query service, including that no secret leaks | 34 |
| `tests/frontend/` | The Streamlit pages run with Streamlit's test tool and a stand-in API (register, scoped checks, every outcome state, the filing form, the report), plus the formatting and HTML helpers | 41 |
| `tests/e2e/` | The real backend and index; skipped unless you opt in (below) | 4 |

The tests never call a real model. The end-to-end tests and the evaluation do, and say so. One more
test, `test_corpus_targets`, is left out with `-m "not targets"` because the corpus is smaller than
its target (see `docs/data/data-sourcing.md`).

Run one folder, or the end-to-end tests against the backend you started in step 4:

```bash
pytest -q tests/frontend

# needs the backend running and an index with at least two contracts; makes a few model calls
CLAUSECHECK_E2E=1 CLAUSECHECK_API_URL=http://localhost:7860 pytest tests/e2e -q
```

**Evaluation.** Ten labelled questions through the whole pipeline, with the judge model (uses your API
keys):

```bash
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
| "I couldn't find this" for something in a contract | Check that the right contract is chosen on the Ask page, and that the original was uploaded before its amendment. Rewording usually helps. |
| "This conversation is about X. To ask about Y, open that contract" | You named a different contract in the question. Each conversation covers one contract; choose the other one in the register on the Ask page. |
| `404 model not found` in the log | A provider retired the model; set a current `GEMINI_MODEL` or `GROQ_MODEL`. |
| `pip install` times out | Add `--default-timeout 120 --retries 10`. On a network that inspects HTTPS, pip may also need the proxy's certificate. |

## Known limits

- When both Groq and Gemini fail (rate limits), a request can take 40+ seconds and end in the
  generic error message.
- About 1 in 30 answerable test questions is still declined by the model.
- Thresholds and model choices were tuned on 40 labelled questions, a small sample.
- A `Dockerfile` is included but has not been built or tested, and nothing is deployed.

## Folder map

| Path | What is in it |
|---|---|
| `clausecheck/` | The Python package: `core`, `ingest`, `rag`, `store`, `llm`, `services`, `api`, `prompts` |
| `site/` | The static landing page; `scripts/update_site_data.py` writes its `results.json` |
| `frontend/` | Streamlit app: `app.py` sets up the pages in `views/` (Ask, Contracts, Insights); shared code is in `components/` |
| `scripts/` | Corpus download, synthetic data, validation, bootstrap and usage report |
| `eval/` | Labelled questions, evaluation runner and results |
| `data/` | Corpus manifest and suppliers list; `raw/` and `uploads/` are git-ignored |
| `index/` | SQLite database and vector store (created by the ingest, git-ignored) |
| `tests/` | `unit/`, `integration/`, `api/`, `frontend/` and `e2e/` tests |
| `notebooks/` | Exploration notebooks (outputs stripped by `nbstripout`) |
| `docs/` | Requirements, planning, architecture, data and UX documents; start with the [team charter](docs/team-charter.md) and the [PRD](docs/requirements/PRD.md) |
| `debugging.md` | Log of everything fixed on the way to version 1 |

Contributors: `pre-commit install` sets up the lint, formatting and secret-scan hooks.
