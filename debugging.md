# Debugging log

Everything done to find and fix what was broken, in order, starting on branch `a-hybrid-rerank`
and released as **version 1 (`v1.0.0`)** from branch `debugging`.
Status per item: **Fixed** (edited and verified), **Edited, not re-run** (edited, but not
re-tested), **Open** (not done), **Not reproducible**.

## Version 1 (`v1.0.0`)

The first version that runs end to end: ask a question about the supplier contracts and get a
cited answer, with uploads and amendments handled.

### What works in v1
- **Chat over contracts:** hybrid retrieval (vector + BM25, fused), cross-encoder re-ranking,
  grounded answers with `[C1]`-style citations, refusals when the contracts do not answer.
- **Amendments:** an uploaded amendment is recognised, dated and linked to its agreement; answers
  give the amended term and say what it replaced (for example Net 45 replacing Net 30).
- **Uploads:** PDF, HTML, DOCX and TXT through the Streamlit sidebar; a Supplier ID is required.
- **Models:** Groq `openai/gpt-oss-120b` answers first (`LLM_PRIMARY=groq`), Gemini
  `gemini-3.1-flash-lite` is the fallback; embeddings run locally (`EMBED_PROVIDER=local`,
  `all-MiniLM-L6-v2`), so they need no API quota.
- **Deployment files:** `Dockerfile`, `.dockerignore`, `scripts/bootstrap.py`,
  `scripts/usage_report.py`, CI jobs (`clean-clone-ingest`, `eval-smoke`). The Hugging Face
  `deploy` job was removed (2.36): Docker Spaces need a paid plan and nothing is deployed.
- **Index:** 167 documents, 8,288 chunks, 8,288 vectors (158 corpus documents + uploads).

### How to run it
```bash
pip install -e . -r requirements.txt && pip install sentence-transformers==6.2.0
cp .env.example .env        # then fill GEMINI_API_KEY and GROQ_API_KEY; .env is git-ignored
python scripts/fetch_sources.py            # corpus, manifest, suppliers
python -m clausecheck.ingest --rebuild     # SQLite, BM25 and local vectors
uvicorn clausecheck.api.main:get_app --factory --port 7860
streamlit run frontend/app.py              # in a second terminal
```
After rebuilding the index or changing `RELEVANCE_THRESHOLD`, clear the cache:
`sqlite3 index/clausecheck.db "DELETE FROM answer_cache;"` (see 2.16 and 2.27).

### Measured for v1 (40 `tune` questions, real models, cache off)
- Answerable questions wrongly refused: **1 of 31** (Q009, `no_citations`).
- Should-refuse questions refused: **9 of 9**. LLM errors: 0 in that run.
- Correct clause in the re-ranker's top 5: **29 of 31**.
- Tests: **262 passed**, 2 skipped (e2e need a deployed server); `ruff` and `black` clean.
- Typical answer time 1 to 5 seconds; 12 seconds for the first question after a restart.

### Settings that were changed for v1 (and why)
| Setting | Now | Was | Item |
|---|---|---|---|
| `GEMINI_MODEL` | `gemini-3.1-flash-lite` | `gemini-2.0-flash` | 2.12, 2.17 |
| `EMBED_MODEL` (Gemini embeddings, unused while local) | `gemini-embedding-001` | `text-embedding-004` | 2.12 |
| `GROQ_MODEL`, `JUDGE_MODEL` | `openai/gpt-oss-120b` | `llama-3.3-70b-versatile` | 2.29 |
| `LLM_PRIMARY` | `groq` (new) | Gemini was hard-wired first | 2.33 |
| `RELEVANCE_THRESHOLD` | `-8.0` | `0.0` | 2.25, 2.27, 2.32 |
| `EMBED_PROVIDER` (in `.env`) | `local` | `gemini` | 2.14 |

### Known limits in v1 (not fixed)
- **No per-contract conversations:** one chat can switch between contracts; the separate chat per
  contract and the "New Contract Analyser" page are not built.
- **Rate limits:** when both Groq and Gemini fail, a request can take 40+ seconds and end in the
  generic error (2.35). The log now shows the HTTP status of each failure.
- **Model refusals:** about 3% of answerable tune questions are still declined or lose their
  citation (Q009); the relevance gate is now loose, so the model decides.
- **Not re-ingested:** the 158 corpus documents were not re-ingested with the header/footer
  cleaner (2.24); only uploads benefit from it.
- **Amendment order:** an amendment uploaded before its original is not linked (2.24).
- **Small eval:** thresholds and model choice were tuned on 40 questions.
- **Not done:** the held-out evaluation, `docs/evaluation/final-report.md`, `docs/qa.md`, building
  the Docker image, and a fresh `pip install -r requirements.txt` check (2.1).
- **`mypy`:** 5 stub/plugin-noise errors remain (2.3).

### Before using v1 anywhere shared
- Rotate the Gemini, Groq and Grok keys: they were pasted into a chat session during this work.
  They are not in the repository (`.env` is git-ignored and a scan of the committed files found no
  key patterns), but treat them as exposed.

## 1. How the problems were found

1. Listed every tracked file (`git ls-files`) and read the retrieval code
   (`hybrid_retriever.py`, `reranker.py`, `vector_retriever.py`, `vector_store.py`,
   `bm25_index.py`, `embedder.py`).
2. Ran `pytest` with the system Python. Collection failed with `No module named 'fastapi'` and
   `No module named 'tiktoken'`: the global interpreter has none of the project dependencies.
3. Created a clean virtualenv and ran `pip install -e . -r requirements.txt`. The install failed
   with `ResolutionImpossible` (see 2.1).
4. Dropped the conflicting pins one at a time to get a working environment, then ran the full
   suite: `pytest -q -m "not targets"` gave **220 passed, 3 failed**.
5. Ran `ruff check .` (clean), `black --check .` (clean) and `mypy clausecheck`
   (35 errors; most are missing stubs because the system Python lacks the packages).
6. Inspected the data: `data/suppliers.csv`, `data/manifest.csv`, `data/raw/*`, and the SQLite
   index with `sqlite3`.
7. After the first round of fixes, the user's own run showed 2 failed, 221 passed, and 8 mypy
   errors, including 3 new ones in `llm/gemini.py` that the first run had hidden.

## 2. Findings and fixes

### 2.1 `requirements.txt` cannot be installed: **Edited, fresh install not re-run**
- Symptom: `ResolutionImpossible`.
- Cause 1: `httpx==0.27.2` conflicts with `google-genai==2.33.0`, which needs `httpx>=0.28`.
- Cause 2: `streamlit==1.40.0` requires `pandas<3`, but the file pins `pandas==3.1.0`.
- Cause 3: the "API" block listed `uvicorn`, `httpx` and `python-multipart` twice.
- Fix: `httpx==0.28.1`, `streamlit==1.56.0` (the version that resolved with pandas 3.1.0 in the
  test venv), duplicates removed. Same pins applied in `frontend/requirements.txt`.
- Evidence: the test venv ran with httpx 0.28.1, streamlit 1.56.0, pandas 3.1.0 and
  fastapi 0.115.0, and the API and frontend tests passed.
- Not verified: a fresh `pip install -r requirements.txt` with the new pins.

### 2.2 `sentence-transformers` missing: **Open (documented, left optional)**
- `Reranker` and `EMBED_PROVIDER=local` import it, but it pulls in PyTorch (several GB), so
  `requirements.txt` keeps it as a commented optional install and CI does not install it.
- Consequence: re-ranking with the default scorer raises a clear `RuntimeError` on a fresh
  install; the unit tests pass a fake scorer, so nothing exercises the real cross-encoder.
- Decision needed: install it in the deployment, or give `Reranker` a non-torch fallback.

### 2.3 mypy errors in project code: **Fixed**
| File | Problem | Change |
|---|---|---|
| `clausecheck/rag/reranker.py` | `-h.rerank_score` where the value is `float \| None` | `-(h.rerank_score or 0.0)` |
| `clausecheck/api/routes/chat.py` | passed dicts where `ChatResponse` expects `CitationOut` | build `CitationOut(...)` objects, import added |
| `clausecheck/api/routes/documents.py` | `args = []` inferred as `list[str]`, then an int was appended | `args: list[str \| int] = []` |
| `clausecheck/ingest/loaders.py` | `find_all` on BeautifulSoup union types | use `select("table")`, `select("tr")`, `select("th, td")`, which return `Tag` lists |
| `clausecheck/llm/gemini.py` | `embed_content` stub rejects `list[str]`; `response.embeddings` and `.values` may be `None` | `or []` guards plus a targeted `# type: ignore[arg-type]` on `contents` |

Verified with `mypy clausecheck`: 5 errors remain, none in logic. `sentence_transformers` and
`rank_bm25` have no stubs, and `core/config.py:84` ("Missing named argument" for `Settings()`)
is a false positive: pydantic-settings reads the required keys from the environment, which mypy
does not know without the pydantic plugin.

### 2.4 and 2.5 `suppliers.csv` header-only, `manifest.csv` synthetic-only: **Fixed**
- `fetch_sources.py` rebuilds both files from the fetched entries plus the synthetic documents.
  The committed files came from a run where the real entries were empty, so only the 70
  synthetic rows were written, and `suppliers.csv` (built only from those entries) was empty.
- Fix: re-ran `python scripts/fetch_sources.py` with no `--only`. The raw CUAD, EDGAR and vendor
  files were already on disk. Result: `manifest: 158 documents, 69 suppliers`
  (cuad 58, edgar 12, vendor 18, plus 70 synthetic), which matches the 158 documents in
  `index/clausecheck.db`. It also rewrote `data/fetch_log.csv`.

### 2.6 Checksum mismatch for synthetic documents: **Fixed (same cause as 2.4)**
- The generator is already deterministic (fixed seed, fixed docx timestamps), so this was not a
  generator bug. `generate_synthetic.py` picks its 40 supplier names from `suppliers.csv`. With
  that file empty, the files on disk were written under the default names and no longer matched
  the manifest hashes. Rebuilding both files in one run (2.4) regenerated the synthetic files and
  their hashes together.

### 2.7 No vector index on disk: **Open**
- `index/` contains only `clausecheck.db`; there is no `index/chroma`. Vector search returns
  nothing, so hybrid retrieval silently degrades to BM25 only.
- Not run: `python -m clausecheck.ingest` embeds every chunk through the Gemini API, which needs
  the key in `.env`, network access and quota. Run it yourself, or use `EMBED_PROVIDER=local`
  after installing sentence-transformers.

### 2.8 `tests/frontend/test_app_smoke.py` failure in the full run: **Not reproducible**
- It failed once in the first full run (the error line was not captured). It passed alone, with
  the other frontend and API tests, and in every later full run, including the user's. Treat it as
  intermittent: the test starts the Streamlit app against `http://127.0.0.1:9` with a 30-second
  timeout, and the first run imports Streamlit cold. Nothing was changed.

### 2.9 `test_corpus_targets` deselected: **Open (needs a decision)**
- Corpus is 64 of 120 contracts and 6 of 20 amendments; supplier count 63 is outside 30 to 50.
  This is a documented decision in `docs/data/data-sourcing.md` section 14, not a code bug.

### 2.10 API crashes at start-up with empty keys: **Fixed**
- Symptom: `uvicorn clausecheck.api.main:get_app --factory` died with
  `ValueError: No API key was provided` while building the container.
- Cause: `GeminiProvider` and `GroqProvider` created their SDK clients in `__init__`, and both
  keys in `.env` were empty.
- Fix: the clients are now built on first use (a lazy `_client` property), so a missing key fails
  the call, not the start-up. `LLMClient.from_settings` drops the Groq fallback when
  `GROQ_API_KEY` is empty, and `/health` counts Gemini alone as "LLM configured".
- Verified: the API starts and `/health` answers (`degraded`, 8,081 chunks, no vectors).

### 2.11 Wiring bugs in `api/container.py` and `/health`: **Fixed**
- The container looked for `retriever.vector`, but `HybridRetriever` names it `vector_retriever`,
  so uploads never got the embedder or vector store. Fixed.
- `vector_count` counted SQLite chunks, so `/health` could never notice a missing vector index.
  It now counts the Chroma collection, and `/health` reports `vector_store: false` (status
  `degraded`) when chunks exist but no vectors do.

### 2.12 Retired Gemini models: **Fixed**
- Both defaults returned `404`: `gemini-2.0-flash` ("no longer available") and
  `text-embedding-004` (not supported for `embedContent`).
- Listed the models the key can use and switched to `gemini-2.5-flash` and
  `gemini-embedding-001` in `config.py`, `llm/gemini.py`, `.env.example` and `.env`.
- Vectors from different models are never mixed, so the index must be rebuilt with the new model.

### 2.13 `python -m eval.run_eval` crashed for most stages: **Fixed**
- `if __name__ == "__main__": raise SystemExit(main())` sat in the middle of the file, before
  `_run_answer`, `_run_sweep`, `_run_e2e` and `_run_agreement` were defined, so those stages
  raised `NameError` when run from the command line (imports in tests were fine).
- Moved the guard to the end of the file. Also added the `--limit N` option the CI smoke job uses.

### 2.14 Gemini embedding quota exhausted: **Fixed by using local embeddings**
- Embedding calls returned `429 RESOURCE_EXHAUSTED`, even for one text. The ingest run embedded
  466 of about 8,081 chunks before it hit the limit, and was stopped.
- Fix: `EMBED_PROVIDER=local` in `.env` (model `all-MiniLM-L6-v2`, runs on this machine).
- `pip install sentence-transformers==6.2.0` first failed with `Read timed out (read
  timeout=15)` / `incomplete-download` (slow network, probably a Sophos proxy: an earlier
  install showed `SSLCertVerificationError: Sophos SSL CA ... not trusted`). It succeeded with
  `--default-timeout 120 --resume-retries 20 --retries 10`.
- `python -m clausecheck.ingest --rebuild`: 158 documents, 8,081 chunks, 8,081 vectors in
  collection `chunks_v1_sentence-transformers_all-MiniLM-L6-v2`.

### 2.16 Stale server and stale cache hid the fixed index: **Fixed**
- An API server started before the rebuild still held port 7860 with the old settings, so the new
  server could not bind (`address already in use`) and `/health` kept saying `vector_store: false`.
  Stopped it (`lsof -ti tcp:7860 | xargs kill`) and started a fresh one.
- Refusals from the broken run (`no_hits`) were cached in `answer_cache` for 24 hours. The cache
  key uses `INDEX_VERSION`, which did not change when the index was rebuilt, so the stale refusal
  kept being served. Cleared with `DELETE FROM answer_cache`. After rebuilding an index, either
  clear the cache or bump `INDEX_VERSION` (which also starts a new vector collection).

### 2.17 `gemini-2.5-flash` listed but closed to new users: **Fixed**
- The model list showed it, but `generate_content` returned `404 ... no longer available to new
  users` (also `gemini-2.5-flash-lite`). `gemini-3.1-flash-lite` worked, so it is now the default
  in `config.py`, `.env.example` and `.env`.

### 2.18 Generation always failed: `temperature` passed as a keyword: **Fixed**
- Symptom: every answer was `outcome: error`, with three `LLM provider gemini failed` warnings
  within about a second (so not a quota or timeout problem).
- Cause: `Generator` calls `client.complete(prompt, temperature=...)`, and `GeminiProvider` passed
  `**kw` straight to `generate_content`. The google-genai SDK takes sampling options inside
  `config=GenerateContentConfig(...)`, so the call raised a `TypeError`, which the adapter turns
  into a bare `ProviderError` (the real message is deliberately hidden to keep secrets out).
  The unit tests use fake providers, so nothing caught it.
- Fix: `GeminiProvider._options` moves `temperature` into `config`. Test added:
  `tests/unit/test_gemini_options.py`.

### 2.19 End-to-end check: **Passed**
- `GET /health`: `status ok`, 158 documents, 8,081 chunks, `vector_store: true`.
- `POST /chat` with eval question Q001 ("Does our NETGEAR distributor agreement renew
  automatically, and for how long?"): `answered`, supplier `netgear`, citing
  `cuad-1fecc64e27e5:p6:15`, which is the gold chunk. Total 2.5 s.
- Other questions refused correctly: an unnamed supplier gave `model_refused`; AWS payment terms
  gave `low_score`.

### 2.15 Missing PR 18 deliverables: **Added**
- `Dockerfile`, `.dockerignore`, `scripts/bootstrap.py`, `scripts/usage_report.py`,
  `index_archive_url` setting, `tests/unit/test_bootstrap.py`, `test_usage_report.py`,
  `test_deploy_files.py`, `tests/e2e/test_live.py`, and the `clean-clone-ingest`, `eval-smoke`
  and `deploy` jobs in `.github/workflows/ci.yml` (`deploy` removed again in 2.36).
- Not done: `docs/evaluation/final-report.md`, `docs/qa.md`, and the held-out eval run. They need
  a working index and real API runs. The Docker image was not built.

### 2.20 Follow-up questions refused after an upload: **Fixed**
- Symptom (screenshot): after uploading `VERDANT-SUPPLY-2024.pdf` with supplier ID `abc`, the
  first question was answered and every later one was `I couldn't find this ...`.
- Diagnosis: `query_log` showed the later questions all had `supplier_id = mmi`, `refusal_reason
  = low_score` and `scores = []`: retrieval had been filtered to a different company's documents.
- Cause 1: `SupplierDetector` used `fuzz.partial_ratio`, which scores 100 when a short name is a
  substring of a longer word. "mmi" sits inside "co**mmi**tment" and "**mmi**ssion", so any such
  question was pinned to supplier MMI, and `previous` then carried it through the session.
- Fix 1: names shorter than 6 characters must match as whole words; longer names still match
  fuzzily (so misspellings like "Corproation" still work).
- Cause 2: the detector is built once at start-up, so a supplier created by an upload was unknown
  until a restart. Fix 2: `on_indexed` in `api/container.py` rebuilds it after each upload.
- Tests: `tests/unit/test_followup_regressions.py`.

### 2.21 False "A number in this answer wasn't found" warning: **Fixed**
- `citation_validator.validate` split sentences at every full stop, so `... Ltd. (the "Buyer")`
  was cut after "Ltd." and the second half had no `[C1]`, which raised `unsupported`.
- Fix: no split after common abbreviations (Ltd., Inc., Corp., Pvt., Co., No., ...). A genuinely
  uncited sentence is still flagged (tested).

### 2.22 Streamed answer shown twice in the chat: **Fixed**
- `frontend/app.py` streamed the reply with `st.write_stream` and then drew it again with
  `render_message`, so a refusal showed as plain text plus the blue box. The stream now goes into
  an `st.empty()` placeholder that is cleared before the final message is drawn.

### 2.23 Uploads with a throw-away supplier ID give wrong answers: **Open (usage)**
- The Verdant upload was registered as supplier `abc` (display name `abc`), so "Verdant" never
  maps to it and searches run across all suppliers. One replayed question ("When does the initial
  term ... end?") was then answered from another company's contract (Sutro).
- Use a real supplier ID and name when uploading (for example `verdant-polymers`). The existing
  `abc` upload would need its supplier changed (documents, chunks and vector metadata).

### 2.24 Questions refused after uploading an amendment: **Fixed**
- Symptom (screenshot): Orion questions were answered until `ORION-AMD1-2024.pdf` was uploaded;
  then "What is Orion's liability for goods lost in transit?" was refused. Earlier answers such as
  "Net 30" were also stale, because the amendment changes them (Net 45, liability $25,000 to
  $40,000, new lane SUR-HYD).
- Diagnosis: `query_log` and a retrieval trace (`hybrid candidates` then `after rerank`) showed
  the model was given the insurance clause, the title block and the signature block, not
  clause 6.1 or the amendment's 3.1. Three causes:
  1. **Upload never marked amendments.** `UploadService._run` hard-coded `parent_doc_id=""` and
     `effective_date=""`, and the form offered only contract, certificate and price schedule. The
     amendment was stored as an ordinary contract, so the amendment expansion and the context
     builder's "AMENDMENT of ..." label never applied.
  2. **Page headers and footers sat inside clause chunks.** The cleaner removed only lone page
     numbers, so "ClauseCheck synthetic document ... Page 2 of 4 Orion Freight Lines Pvt. Ltd. -
     Transportation Services Agreement No. ..." was glued onto clauses. The company name in the
     question matched those chunks, so the cross-encoder ranked them above the real clauses.
  3. **A linked clause could be cut.** Clause 3.1 of the amendment was already one of the 20
     candidates, so expansion skipped it as "already present"; it then lost the ranking and was
     dropped, leaving the old $25,000 in the answer.
- Fixes:
  - `clausecheck/services/amendments.py` (new): detects an amendment from its first 2,000
    characters, reads the agreement number and the "effective from <date>", and links it to the
    supplier's agreement (by number, else the only other non-amendment document; ambiguous means
    unlinked). `UploadService._run` calls it before ingesting. "amendment" added to the form.
  - `ingest/cleaner.py`: `strip_running_lines` drops lines repeated on at least half of the pages
    (digits are masked only on "page" lines, because masking every line also deleted body text in
    a first version, caught by a test).
  - `rag/reranker.py`: after choosing the top `n`, any other candidate that amends a kept clause
    (or is amended by one) is kept right after it.
  - The two Orion uploads were re-ingested in place (amendment now `doc_type=amendment`,
    `parent_doc_id` = the service agreement, `effective_date=2024-04-01`).
- Tests: `tests/unit/test_amendment_upload.py`, `tests/unit/test_reranker_amendments.py`.

### 2.25 Relevance gate too strict for paraphrased questions: **Fixed (tuned)**
- After 2.24 the question "How quickly must Orion ... place a vehicle after we book one?" was
  refused with `low_score`: the right clause (3.1 Vehicle Placement) was candidate 2 but the
  cross-encoder scored it -1.64, under the old threshold of 0.0. It had only passed before because
  a noisy chunk happened to score +0.42.
- Measured on the 40 labelled `tune` questions (full pipeline, real Gemini, cache off):

  | `RELEVANCE_THRESHOLD` | answerable wrongly refused | should-refuse correctly refused | LLM errors |
  |---|---|---|---|
  | -1.0 | 6/31 (3 were transient errors) | 9/9 | 3 |
  | **-2.0** | **3/31** | **9/9** | 0 |
  | -3.0 | 9/31 | 8/9 | 8 |

  (Re-ranker-only scores: answerable 31 questions, min -0.93 / median 5.35; should-refuse 9
  questions, min -8.1 / median -1.0, so the two groups overlap and no threshold separates them.)
- Set `-2.0` in `config.py` and `.env.example`. The 3 remaining wrong refusals (Q020, Q022, Q040)
  are the model declining, not the gate. Errors at -1.0 and -3.0 look like transient LLM failures.
- Caveats: 40 questions is a small sample. The answer cache key does not include the threshold,
  so clear `answer_cache` after changing it.

### 2.26 Service-contract questions refused after uploading Helixa files: **Fixed**
- Symptom (screenshot): questions about the Helixa amendment worked, but "Which law governs the
  Helixa Cloud Systems agreement and where are disputes arbitrated?" (a service-contract clause)
  was refused. Earlier answers also ignored the amendment ("20% credit", "no uptime specified").
- Diagnosis (`documents` table, `query_log`, retrieval trace):
  1. **Both uploads had `supplier_id = ''`.** The Supplier ID box was left empty and nothing
     rejected it. With no supplier filter a generic question (governing law, arbitration) searches
     all 8,209 chunks; hundreds of other contracts have the same clause, so Helixa's 12.1 and 12.2
     did not reach the context. Distinctive questions (uptime, fees) still worked.
  2. **The company name in the question made preamble chunks outrank the real clauses.** 12.1 was
     candidate 4 but the cross-encoder scored it below title blocks that repeat the party names.
  3. **Amendment expansion added unrelated clauses.** `expand_amendments` also pulled in parent
     clauses that merely shared the amendment's own clause number (its 4.2 "Counterparts" pulled
     the agreement's 4.2). That put four score -11 chunks in the context.
  4. **`UploadService._run` overwrote an existing supplier** (`upsert_supplier` replaces the
     display name and deletes all aliases) whenever another document was uploaded for it.
- Fixes:
  - `api/routes/documents.py` returns 422 for a blank `supplier_id`; the upload form shows an
    error. New suppliers get a readable name ("Helixa Cloud Systems") and the typed ID as alias;
    existing suppliers are left untouched.
  - `SupplierDetector.strip_names` removes the supplier's name from the question given to the
    re-ranker only (retrieval still sees the full question; falls back if under 3 words remain).
    Measured on the 40 tune questions: gold clause in top-5 27/31 to 29/31.
  - `expand_amendments` now pulls in only parent clauses the amendment names ("Section 6.1").
    This deviates from the PR 8 brief, which also said "or share its clause number". The
    existing tests do not depend on that rule. Re-measured on the 40 questions: no change.
  - The two Helixa documents were re-ingested under `helixa-cloud-systems`
    (the amendment is linked to the agreement).
- Tests: `tests/api/test_upload_blank_supplier.py`, `tests/integration/test_upload_supplier.py`,
  `tests/unit/test_strip_supplier_name.py`.

### 2.27 Relevance threshold re-tuned to -4.0: **Fixed**
- With name stripping, "What are the payment terms with Orion?" ranked the right clauses first
  but scored about -3.3, under the -2.0 gate. A short generic question scores low with this
  cross-encoder even when the clause is correct, so the 40 long eval questions overstated how
  safe a tight gate is.
- Full-pipeline runs (real Gemini, cache off) at -2.0 / -4.0 / -6.0 all refused 9/9 of the
  should-refuse questions (the model declines them itself) and wrongly refused the same 4 answerable
  ones (Q010, Q020, Q022, Q040: the model, not the gate). Extra "wrong refusals" at -4.0 and
  -6.0 were `error` outcomes from Gemini (reason `None`, in runs of consecutive questions: probably
  rate limiting), not the threshold.
- Set `RELEVANCE_THRESHOLD=-4.0` in `config.py` and `.env.example`.

### 2.28 Known limits after 2.24 to 2.27
- Four tune questions (Q010, Q020, Q022, Q040) are still declined by the model; not investigated.
- Gemini returns errors in bursts when many requests are sent quickly (seen in the 40-question
  runs); the app shows the generic error message in that case.
- `QueryService` wraps `reranker.rerank` in `except Exception: pass`, so a failing re-ranker would
  silently fall back to unranked hits. Left as is.
- The other 158 documents were not re-ingested with the header/footer cleaner (2.24).
- An amendment uploaded before its original is not linked.

### 2.29 Groq fallback and eval judge: **Fixed**
- `GROQ_API_KEY` was empty, so there was no fallback when Gemini errored (it errors in bursts under
  load, see 2.28) and the eval judge, which defaults to Groq, could not run.
- Added the key to `.env`. The default model `llama-3.3-70b-versatile` returned `404 model_not_found`
  on Groq (retired, like the Gemini defaults in 2.12 and 2.17). Listed the models the key can use
  and switched `GROQ_MODEL` and `JUDGE_MODEL` to `openai/gpt-oss-120b` in `config.py`,
  `.env.example` and `.env`.
- Verified the fallback on purpose: with Gemini set to a non-existent model, `LLMClient` failed
  three times on Gemini and then answered from Groq, for both `complete` and `stream`.
- Not yet run: the e2e eval with the judge (`python -m eval.run_eval --stage e2e`).

### 2.30 "Payment terms" refused for Sapphire: **Fixed**
- Symptom (screenshot): after uploading `SAPPHIRE-SERVICE-2022.docx` and `SAPPHIRE-AMD1-2024.docx`
  with supplier ID `Sapphire`, five questions were answered and "What are the payment terms with
  Sapphire Facility Services?" was refused (`model_refused`).
- Diagnosis: the uploads were set up correctly (supplier `Sapphire`, amendment linked, clauses 5.1
  and 5.2 present), but the context given to the model held the title block, a signature block and
  unrelated clauses, not 5.1. Re-ranking the same candidates with three versions of the question
  showed why:
  - original: title/preamble chunks first;
  - "...payment terms with Facility Services?" (what 2.26 produced): title/preamble chunks first;
  - "...payment terms with ?": both 5.1 clauses first.
- Cause: `SupplierDetector.strip_names` (2.26) removed only the stored name. The ID typed at upload
  was `Sapphire`, but the question says "Sapphire Facility Services", so "Facility Services" stayed
  and matched every preamble chunk again.
- Fix: after a matched name it also removes up to four following capitalised words and an
  apostrophe or `'s` ("Sapphire Facility Services Pvt. Ltd.'s"). Tests added to
  `tests/unit/test_strip_supplier_name.py`.
- Re-measured on the 40 tune questions (retrieval + re-rank only): gold clause in top-5 still
  29/31; no change in score separation.
- Replay: Sapphire payment (Net 30 replacing Net 45), lift breakdown (20 minutes replacing 30),
  fee (Rs 10,45,000 replacing Rs 9,80,000), plus Orion, Helixa and NETGEAR all answered; Sapphire
  parental leave refused.
- Note: stripping is a heuristic on the question text. A question that puts a capitalised word
  right after the name that is not part of it ("Orion Surat plant") loses that word from the
  re-ranker query only; retrieval and the model still see the full question.

### 2.31 Northstar: garbled price and a refused insurance question: **Fixed**
- Symptoms (screenshot, Northstar supply agreement plus amendment): (a) "The price for Shaft
  SH-450 is `44.10 per piece [C2]. This replaces the original price of ` 42.75 per piece" shown
  with a code-like green span; (b) "What insurance must Northstar Steel Components carry?" refused.
  "Does Northstar supply shaft SH-750?" refused before the amendment and answered after it, which
  is correct (the amendment adds that shaft).
- (a) was a display bug, not a model error: the cached answer text was correct ("$44.10 ... $42.75").
  Streamlit markdown treats text between two `$` signs as a formula. Fix: `escape_dollars` in
  `frontend/components/chat.py` is applied wherever chat text is drawn (answers, refusals, the
  user's own messages, and the live stream). The raw text is kept in `session_state`, so the
  escape is applied once at render time. `app.py` no longer stores the streamed (escaped) copy as
  the message content. Tests: `tests/frontend/test_dollar_escape.py`.
- (b) was the relevance gate (`low_score`). The clause existed (9.1, product liability insurance
  of $3,000,000) and was candidate 14 of 20. Re-ranking the same candidates:

  | Query given to the re-ranker | Clause 9.1 score |
  |---|---|
  | original, with the company name | -8.3 (title blocks first) |
  | name deleted: "What insurance must carry?" (2.26 and 2.30) | -5.2, under the -4.0 gate |
  | name replaced: "What insurance must the Supplier carry?" | +2.8 |

  Deleting the name left a broken sentence the cross-encoder scored badly. `strip_names` now
  replaces the supplier's name with "the Supplier" (keeping a possessive, and absorbing a leading
  "the/our/their/its"). Contracts name the party that way too.
- Re-measured on the 40 tune questions (re-rank only): gold clause in top-5 still 29/31; answerable
  minimum score -1.9 against the -4.0 gate; should-refuse questions under -4: 6/9.
- Replay of 10 questions (Northstar, Sapphire, Orion, Helixa, NETGEAR, parental leave): all as
  expected. Insurance now answers ($3,000,000 per occurrence, certificates on request).

### 2.32 "Does Orion Freight Lines have a rate for Hyderabad?" refused: **Fixed**
- Symptom (screenshot): refused with `low_score`, although the rate is in the amendment (clause
  1.1 and the Schedule A table; lane SUR-HYD, $870 for 9 MT and $1,270 for 16 MT).
- Not caused by a code change: the previous turn only read files. The same question under the
  three query forms: original best score 2.0 (a signature-block chunk, with the rate table 5th);
  name deleted -5.1; name replaced ("Does the Supplier have a rate for Hyderabad?") -7.3. The rate
  table ranked first in both stripped forms but its absolute score was under the -4.0 gate.
  Yes/no phrasings score low with this cross-encoder.
- This is the third time the absolute-score gate refused a question that had the right clause
  ranked first (2.25, 2.27, now). Full-pipeline run on the 40 tune questions at `-8.0`: all 9
  should-refuse questions still refused (by the model), and the answerable questions wrongly
  refused were the same model declines (Q010, Q020, Q040); three `None` reasons were provider
  errors, not the gate.
- Set `RELEVANCE_THRESHOLD=-8.0`. The gate now only stops clearly irrelevant retrievals (for
  example "What is the capital of France?" is still refused with `low_score`). Deciding between
  "answer" and "not in the contract" is left to the model, which is told to refuse if the clauses
  do not answer the question (rule 3 of the answer prompt) and whose answers need a valid citation.
- Replay of 10 questions: all as expected, including "Does Northstar Steel Components supply
  helicopters?" and "What is Orion Freight Lines' policy on employee parental leave?" (refused by
  the model).
- Cost: more should-refuse questions now reach the model (one LLM call each) instead of being
  stopped by the gate.

### 2.33 "How are minimum wage increases handled with Sapphire?" refused: **Fixed (model change)**
- Symptom (screenshot): refused (`model_refused`) although clause 4.2 ("Statutory minimum wage
  revisions are passed through at cost, with no margin, on fifteen (15) days' written notice") was
  in the context, as chunk 4 of 8.
- Reproduced the exact prompt against each model (same context, temperature 0):

  | Model | Wage question | Orion Hyderabad | Northstar helicopters (must refuse) | Time |
  |---|---|---|---|---|
  | gemini-3.1-flash-lite (was primary) | **refused** (twice) | answered | refused | 1.3 to 1.9 s |
  | gemini-3.5-flash | answered | answered | refused | 4.5 to 25 s |
  | gemini-3.8-flash | server errors | server errors | server errors | 39 to 89 s |
  | groq openai/gpt-oss-120b | answered, cited [C4] | answered | refused | 0.6 to 2.2 s |

  With the clause alone in the context even flash-lite answered, so it was refusing when the
  context also held other (amendment) clauses. The four tune questions the model kept declining
  (Q010, Q020, Q022, Q040) were the same problem.
- Fix: new setting `LLM_PRIMARY` (`groq` default, or `gemini`); the other provider is the
  fallback. Without a Groq key Gemini is primary. `LLMClient.from_settings` builds it. Tests:
  `tests/unit/test_llm_primary.py`.

### 2.34 Cited answers refused as `no_citations` (found while testing 2.33): **Fixed**
- With Groq first, three answerable tune questions were refused with `no_citations`. The answers
  were correct but the markers were look-alikes: `【C1】` (full-width brackets) and a narrow
  no-break space (U+202F) before `[C1]`. `validate` only knew `[C1]`.
- Fix: `normalise_markers` in `citation_validator.py` maps `【C1】`, `［C1］`, `(C1)`, `[ C1 ]` to
  `[C1]` and replaces U+202F, U+00A0, U+2009 with a space (U+200B removed) before validating.
  Tests: `tests/unit/test_citation_lookalikes.py`.
- Full-pipeline run on the 40 tune questions (threshold -8.0, cache off):

  | Setup | answerable wrongly refused | should-refuse refused | LLM errors |
  |---|---|---|---|
  | Gemini flash-lite first | 4/31 (model declines) | 9/9 | 0 to 3 |
  | Groq first, before 2.34 | 3/31 (`no_citations`) | 9/9 | 0 |
  | Groq first, with 2.34 | **1/31** (Q009, `no_citations`) | 9/9 | 0 |

### 2.35 LLM failures were invisible, and two answers errored: **Partly fixed**
- A replay right after the 40-question run returned `error` for two questions after 38 s and
  51 s (every attempt on both providers failed); a second replay a few minutes later had no
  failures. The logs said only "LLM provider groq failed (attempt n)", because the adapters hide
  provider messages to keep secrets out of logs. Probably rate limiting right after a burst, not
  confirmed.
- Added `describe_error` and `provider_error` in `llm/client.py`: the adapters now log the
  exception type and HTTP status only (for example `groq call failed: RateLimitError 429`),
  never the message. A first version logged the message from the client and the existing test
  `test_failures_logged_without_secret` caught it; the logging now lives in the adapters.
  Tests: `tests/unit/test_describe_error.py`.
- Not fixed: when both providers fail, a request can take 40+ seconds (3 attempts x 2 providers x
  timeout); not changed.
- Minor, not fixed: Groq's model sometimes writes citations as `[C1][C4]` with no space, and
  uses non-breaking hyphens (`SUR-HYD`); the app shows them as they are.

### 2.36 CI: `deploy` job removed, `eval-smoke` checked locally: **Done**
- Hugging Face Docker Spaces need a paid plan (the Create Space page marks Docker "Paid") and the
  user decided not to deploy, so the `deploy` job (and `HF_TOKEN` / `HF_SPACE`) was removed from
  `.github/workflows/ci.yml`. `tests/unit/test_deploy_files.py::test_ci_has_deploy_and_eval_smoke`
  asserted that `deploy` and `HF_TOKEN` exist; it is now `test_ci_has_eval_smoke_and_no_deploy_job`.
  `Dockerfile`, `.dockerignore` and `scripts/bootstrap.py` stay (they run anywhere with Docker).
- `eval-smoke` (runs only on a push to `main`) was changed to install `sentence-transformers`, set
  `EMBED_PROVIDER=local` and pass `EDGAR_USER_AGENT`, so it no longer spends the Gemini embedding
  quota. It had never run, so its last two steps were run locally against a temporary index
  (`INDEX_DIR` and `SQLITE_PATH` pointed at a scratch folder, real index untouched):
  - `python -m clausecheck.ingest --rebuild` with local embeddings: 158 documents ingested,
    8,062 chunks, 8,062 vectors, no failures.
  - `python -m eval.run_eval --split tune --stage e2e --limit 10` with the real Groq and Gemini
    keys: exit code 0, all 10 questions answered; answer correctness 0.8, citation accuracy 0.9,
    false refusal rate 0.0, median latency 7.3 s.
  - `refusal_accuracy` printed 0.0 only because the first 10 tune questions contain no
    should-refuse question (0 of 0); it is not a failure.
  - The result files the run created in `eval/results/` were deleted.
- What "passes" means: the job only fails if a step crashes; it does not enforce any metric
  threshold. Not verified: the GitHub runner itself (fresh `pip install` including PyTorch, the
  corpus download in `fetch_sources.py`, run time), and the 7.3 s median is above the 3 s target
  (this run also shared the machine with the test suite, and several questions include a cold
  model load).

## 3. Verification

- Orion replay after 2.24 and 2.25 (6 questions through `POST /chat`): all answered; liability
  $40,000 replacing $25,000, payment Net 45 replacing Net 30, Hyderabad lane $1,270.
- `pytest -q -m "not targets"`: **262 passed**, 2 skipped (e2e), 1 deselected, after all the
  changes above (before the data fix: 2 failed).
- `ruff check .` and `black --check .`: clean.
- `mypy clausecheck`: 5 remaining errors, all stub or plugin noise (see 2.3).
- Not verified: a fresh `pip install -r requirements.txt` with the new pins (2.1), and any
  Gemini or Groq call (no API usage was made).

## 4. Files changed

- `requirements.txt`, `frontend/requirements.txt`
- `clausecheck/rag/reranker.py`, `clausecheck/api/routes/chat.py`,
  `clausecheck/api/routes/documents.py`, `clausecheck/ingest/loaders.py`,
  `clausecheck/llm/gemini.py`
- `data/manifest.csv`, `data/suppliers.csv`, `data/fetch_log.csv` (regenerated)
- `debugging.md` (this file)
