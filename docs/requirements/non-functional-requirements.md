# ClauseCheck: Non-Functional Requirements

Sprint 2, Simulated Work (AI Application Development with RAG)
Repo: `FirstName_ClauseCheck_Kalvium-Community`
See also: `PRD.md` (section 9.2 lists NFR-1 to NFR-8), `functional-requirements.md`, `rag-architecture-design.md` (sections 11, 13, 14), `tdd.md` (sections 10, 13, 14), `development-plan.md`
Version: 1.0, 2026-10-01
Status: submitted with the PRD for M1 review.

This document expands NFR-1 to NFR-5 in `PRD.md` section 9.2 into **testable acceptance criteria**. NFR-6 (failing safely), NFR-7 (upload safety) and NFR-8 (clear labelling) are already covered by criteria in `functional-requirements.md` (AC-5.11, AC-7.7, AC-9.2, AC-9.9, AC-10.8, AC-10.11) and get their own document only if the mentor asks for one.

The same precedence rules apply as for the functional requirements: if this document disagrees with the PRD on scope or targets, the PRD wins. If it disagrees with `rag-architecture-design.md` on a mechanism or parameter, the design wins, and this document is updated.

| Version | Date | Change | Approved by |
|---|---|---|---|
| 1.0 | 2026-10-01 | First version for M1 review | |

---

## Contents

1. [How to read this document](#1-how-to-read-this-document)
2. [Summary of requirements](#2-summary-of-requirements)
3. [NFR-1 Latency](#nfr-1-latency)
4. [NFR-2 Secrets](#nfr-2-secrets)
5. [NFR-3 Reproducible rebuild](#nfr-3-reproducible-rebuild)
6. [NFR-4 Rate limits and retries](#nfr-4-rate-limits-and-retries)
7. [NFR-5 Caching](#nfr-5-caching)
8. [How the NFRs interact](#8-how-the-nfrs-interact)
9. [Traceability](#9-traceability)
10. [Open questions](#10-open-questions)

---

## 1. How to read this document

### 1.1 Structure of each requirement

Every NFR has the same three parts as the functional requirements:

1. **Requirement card**: the statement, priority, stories or risks it serves, owner, where it is implemented, and what it depends on.
2. **Acceptance criteria**: numbered `AC-N<n>.<m>` (the `N` separates them from functional criteria, so `AC-N1.3` is NFR-1, criterion 3). Each is a single checkable statement with a pass condition and a verification method.
3. **Not covered**: behaviour that belongs elsewhere, so nobody tests the wrong thing.

### 1.2 Verification methods

The codes from `functional-requirements.md` section 1.2 apply, plus two more that non-functional checks need:

| Code | Method | Where it lives |
|---|---|---|
| **UT** | Unit test on a fixture | `tests/unit/` |
| **IT** | Integration test across modules (SQLite, Chroma, BM25) | `tests/integration/` |
| **API** | Test against the FastAPI app with `TestClient` and mocked LLM calls | `tests/api/` |
| **EVAL** | `eval/run_eval.py` on the labelled set | `eval/results/<date>_<tag>.md` |
| **QA** | Scripted manual check | `docs/qa.md` |
| **CI** | A job in GitHub Actions that fails the build when the check fails | `.github/workflows/` |
| **DEP** | Measurement on the deployed app (Hugging Face Spaces backend, Streamlit Cloud frontend) | `eval/results/<date>_deployed.md` |

Criteria marked **[gate]** are tied to an acceptance gate in PRD section 6.2. Criteria marked **[proposal]** depend on an open question in section 10; if the mentor rejects the proposal, the criterion is changed in a new version of this document, not silently dropped.

### 1.3 Definition of done for an NFR

An NFR is done when:

1. every criterion not marked **[proposal]** passes, and every **[proposal]** criterion either passes or has been resolved in section 10;
2. the checks that can be automated (UT, IT, API, CI) run on every merge to `main`;
3. the evidence is linked in the traceability table (section 9).

### 1.4 Parameters

Criteria quote the **default** values from `rag-architecture-design.md` section 11 and `tdd.md` section 14.1. New parameters introduced here (marked *new*) are added to `.env.example` and to the parameter register when this document is approved.

| Parameter | Default | Source |
|---|---|---|
| `RETRIEVE_K` | 20 | RAG design 11 |
| `RERANK_TIMEOUT_MS` | 1500 | RAG design 11 |
| `EMBED_BATCH_SIZE` | 50 | RAG design 11 |
| `ANSWER_CACHE_TTL_DAYS` | 7 | RAG design 11 |
| `RATE_LIMIT_PER_MIN` | 30 | TDD 14.1 |
| `RETRY_MAX_ATTEMPTS` | 5 | TDD 13 |
| `RETRY_BACKOFF_MIN_S` / `RETRY_BACKOFF_MAX_S` | 1 / 32 | TDD 13 |
| `QUERY_RETRY_BUDGET_MS` | 2000 | *new*, see Q-N1 |
| `CACHE_ENABLED` | `true` (prod), `false` (eval) | *new*, see AC-N5.12 |

---

## 2. Summary of requirements

| ID | Requirement | Priority | Owner | Main week |
|---|---|---|---|---|
| NFR-1 | **Latency**: time to first token p50 under 3 s on the deployed app, with every stage timed and held to a budget | P0 (gate) | D (C measures) | W5 |
| NFR-2 | **Secrets**: API keys exist only in `.env` and host secret stores, never in the repo, frontend, responses or logs | P0 | D | W1, W5 |
| NFR-3 | **Rebuild**: the whole index can be rebuilt from a clean clone with one command, and every reported number can be reproduced | P0 | A | W1, W3 |
| NFR-4 | **Rate limits and retries**: transient API failures are retried with bounded backoff, then fall back; our own API limits each client | P0 | B (LLM client), D (API limit) | W1, W3, W5 |
| NFR-5 | **Caching**: a repeated question is answered from the cache with no LLM call, and a cached answer is never served once it may be stale | P0 | B (embedding cache), D (answer cache) | W3, W5 |

Workstreams: **A** corpus and ingestion, **B** retrieval, **C** generation and evaluation, **D** app and platform.

---

## NFR-1 Latency

| | |
|---|---|
| **Requirement** | On the deployed app, the median time from the API receiving a question to sending the first answer token is under 3 seconds. Every stage of the query pipeline is timed on every request, so a slow answer can be traced to the stage that caused it. |
| **Priority** | P0, acceptance gate (KPI-07) |
| **Stories / risks** | US-01; R-09 (TTFT over 3 s when deployed); A-7 (free CPU host is enough) |
| **Owner** | Workstream D (API, deployment); Workstream C (measurement in eval) |
| **Implemented in** | Stage timers in `rag/pipeline.py`; `ttft_ms` and stage fields in `query_log`; `/chat/stream` SSE |
| **Depends on** | FR-10 (streaming), FR-11 (logging), NFR-5 (cache must be off while measuring) |

### Latency budget

From `rag-architecture-design.md` section 13.1. The budget is diagnostic: only the total is a gate.

| Stage | Logged as | Budget (p50) |
|---|---|---|
| Rewrite (follow-ups only) | `rewrite_ms` | 0–600 ms |
| Supplier resolution + cache lookup | part of `retrieve_ms` | < 15 ms |
| Query embedding | `embed_ms` | 150–300 ms |
| Vector search + BM25 + RRF | `retrieve_ms` | < 80 ms |
| Cross-encoder re-ranking (20 pairs, CPU) | `rerank_ms` | 300–700 ms (hard cap 1,500 ms) |
| LLM first token | `ttft_ms − (sum of earlier stages)` | 500–1,000 ms |
| **Total to first token** | `ttft_ms` | **~1.2–2.7 s; gate < 3 s** |

### Acceptance criteria

**Definition and measurement**

| ID | Criterion | Verified by |
|---|---|---|
| AC-N1.1 | `ttft_ms` is measured **on the server**, from the moment the FastAPI handler receives the request to the moment the first `token` event is written to the response. Network time to the browser is not included in the gate; it is reported separately by the usability session (KPI-01). | UT (timer placement), code review |
| AC-N1.2 | The gate run uses these conditions, all recorded in the result file: the deployed backend; the full eval set (tuning + held-out questions, run sequentially, one request at a time); `CACHE_ENABLED=false`; one discarded warm-up request after the container starts. Cold-start time is measured separately under NFR-3 (AC-N3.5). | DEP |
| AC-N1.3 | Only requests with `outcome = answered` count toward TTFT p50/p95, because refusals stream no tokens. | EVAL (computed from `query_log`) |

**Targets**

| ID | Criterion | Verified by |
|---|---|---|
| AC-N1.4 **[gate]** | TTFT p50 < **3,000 ms** on the deployed app under the conditions in AC-N1.2 (KPI-07). | DEP |
| AC-N1.5 **[proposal]** | TTFT p95 < **5,000 ms** under the same conditions (Q-N2). p95 is always reported, whether or not this target is approved. | DEP |
| AC-N1.6 **[proposal]** | Time to outcome for refusals that make no generation call (`refused_low_score`, `refused_unknown_supplier`, `clarify_multiple_suppliers`, `out_of_scope_aggregation`) has p50 < **1,500 ms**, measured as `total_ms` (Q-N3). | DEP |
| AC-N1.7 | A cache hit returns its `done` event with `total_ms` p50 < **500 ms** (no embedding, re-ranking or LLM call is made). | API (local), DEP |

**Traceability of slow requests**

| ID | Criterion | Verified by |
|---|---|---|
| AC-N1.8 | Every request writes `rewrite_ms`, `embed_ms`, `retrieve_ms`, `rerank_ms`, `ttft_ms` and `total_ms` to `query_log` (AC-11.2). Stages that did not run log `0`, not null, so sums are well defined. | API |
| AC-N1.9 | The deployed eval report contains a table of p50 and p95 per stage next to the budget above, and flags every stage whose p50 is over budget. | DEP |
| AC-N1.10 | Re-ranking never adds more than `RERANK_TIMEOUT_MS` (1,500 ms): when exceeded, RRF order is used for that request and `rerank_timeout` is logged (AC-5.10). | UT (slowed mock) |
| AC-N1.11 | The first message of a session makes no rewrite call (`rewrite_ms = 0`, AC-8.2), and a follow-up that names a known supplier with no pronouns skips the rewrite (AC-8.6). | API |

**Remediation**

| ID | Criterion | Verified by |
|---|---|---|
| AC-N1.12 | If the measured p50 is ≥ 3 s, the fixes in RAG design section 13.1 are applied **one at a time, in order**: (1) `RETRIEVE_K` 20 → 12; (2) skip the rewrite when a supplier is named and there are no pronouns; (3) send the `meta` event before generation starts. TTFT is re-measured after each, and the Recall@5 on the tuning split is re-run after fix (1). Each step is a row in the deployed eval report. | DEP, EVAL |
| AC-N1.13 | No latency fix may lower Recall@5 below 0.85 or change refusal behaviour. If fix (1) does, it is reverted and the next fix is tried. | EVAL |

### Not covered

Time from question to opening a cited clause (KPI-01, usability session, AC-10.15). Ingestion and upload speed (FR-9 job states have no time target in v1). Concurrent load: v1 is a single-user demo with a per-IP limit, and no throughput target is set.

---

## NFR-2 Secrets

| | |
|---|---|
| **Requirement** | API keys (Gemini, Groq) exist only in a local `.env` file that is never committed, and in the secret stores of the hosts and CI. They never appear in the repository or its history, the frontend, any HTTP response, or any log line. |
| **Priority** | P0 |
| **Stories / risks** | All (the app can't run without keys); A-2 (free-tier APIs on public data only) |
| **Owner** | Workstream D |
| **Implemented in** | `.gitignore`, `.env.example`, `.pre-commit-config.yaml`, `.secrets.baseline`, `clausecheck/config.py` (`pydantic-settings`), log redaction filter in `clausecheck/logging.py`, Hugging Face Space secrets, Streamlit Cloud secrets, GitHub Actions secrets |
| **Depends on** | None. This is set up on W1 before the first key is created. |

### Where each secret may live

| Location | `GEMINI_API_KEY`, `GROQ_API_KEY` | Notes |
|---|---|---|
| Developer `.env` (local, ignored) | ✅ | Each developer uses their own key |
| `.env.example` (committed) | Name only, empty value | Documents every setting |
| Hugging Face Space secrets (backend) | ✅ | Production |
| GitHub Actions secrets | ✅ | Only for the eval smoke test and index build on `main` |
| Streamlit Cloud secrets (frontend) | ❌ | Holds `API_BASE_URL` only |
| Source code, notebooks, tests, docs | ❌ | Tests use a fake sentinel key |
| Logs, HTTP responses, `/health`, error bodies | ❌ | Redacted if they ever reach a log |

### Acceptance criteria

**Repository**

| ID | Criterion | Verified by |
|---|---|---|
| AC-N2.1 | `.env` is listed in `.gitignore`, and `git ls-files` returns no file named `.env` or matching `*.env` other than `.env.example`. | CI |
| AC-N2.2 | `.env.example` is committed and contains **every** setting declared in `clausecheck/config.py`, with secret values left empty. A test compares the field names of the settings class with the keys in `.env.example` and fails on any difference. | UT |
| AC-N2.3 | A `detect-secrets` pre-commit hook runs against `.secrets.baseline`, and a CI job runs the same scan on every pull request. A new finding fails the build. | CI |
| AC-N2.4 **[proposal]** | The full git history is scanned (`gitleaks detect`) once at W1 D5 and once before final submission (W5 D5), with **0** findings (Q-N4). | CI (manual workflow), result in `docs/qa.md` |

**Runtime**

| ID | Criterion | Verified by |
|---|---|---|
| AC-N2.5 | Secret settings are typed as `SecretStr`, so printing or logging the settings object shows `**********`, never the value. | UT |
| AC-N2.6 | If a required secret is missing, the backend refuses to start and prints the **name** of the missing variable. It never prints the value of any setting. | UT |
| AC-N2.7 | **Sentinel test.** The test suite sets both keys to a recognisable fake value (e.g. `TEST-SENTINEL-7f3a`). After exercising every endpoint (`/chat`, `/chat/stream` including an `error` event, `/health`, `/suppliers`, `/chunks/{id}`, `/documents`, `/documents/jobs/{id}`, `/feedback`) and forcing an LLM client exception, the sentinel appears in **no** response body, header or captured log line. | API |
| AC-N2.8 | A logging filter masks secret values and `key=` query parameters in log messages and exception traces, because the Gemini REST client can put the key in the request URL and some HTTP errors include the URL. Fixture: an exception whose message contains `...?key=TEST-SENTINEL-7f3a` is logged as `...?key=[REDACTED]`. | UT |
| AC-N2.9 | The frontend holds only `API_BASE_URL`. A scan of `frontend/` and of the Streamlit secrets template finds no key names or values (AC-10.12). | QA, secret scan |

**Hosts and CI**

| ID | Criterion | Verified by |
|---|---|---|
| AC-N2.10 | On the deployed backend, keys are read from Hugging Face Space secrets, not from a file in the image. `docker history` and the image filesystem contain no `.env`. | DEP (W5 D4 checklist) |
| AC-N2.11 | Jobs that use API keys (eval smoke test, index build) run only on pushes to `main`, never on pull requests from forks, and never print environment variables. | CI (workflow review) |
| AC-N2.12 | If a key is ever found in a commit, log or screenshot, it is revoked and replaced the same day, and the event is recorded in the team journal. Removing it from history alone is not enough. | QA (runbook in `docs/qa.md`) |

### Not covered

Upload validation and HTML safety (NFR-7, AC-9.2, AC-9.9). CORS (TDD 14.2). Login and access control on documents (out of scope, PRD 8.2). Prompt injection (AC-6.15).

---

## NFR-3 Reproducible rebuild

| | |
|---|---|
| **Requirement** | The whole index (SQLite, Chroma, BM25) can be rebuilt from a clean clone with one command, produces the same chunks every time, and is restored automatically when the free host restarts. Every reported number can be traced to the exact index, prompt and parameters that produced it. |
| **Priority** | P0 |
| **Stories / risks** | US-15; KPI-12; R-08 (host wipes disk), R-11 (chunker changes break eval mapping) |
| **Owner** | Workstream A (ingestion, seeds); Workstream D (CI artifact, bootstrap) |
| **Implemented in** | `python -m clausecheck.ingest`, `scripts/fetch_sources.py`, `scripts/generate_synthetic.py`, `scripts/bootstrap.py`, CI index-build job, `README.md` |
| **Depends on** | FR-1 to FR-4; NFR-5 (embedding cache keeps rebuilds within rate limits) |

### Acceptance criteria

| ID | Criterion | Verified by |
|---|---|---|
| AC-N3.1 | On a clean clone with a filled `.env`, `python -m clausecheck.ingest --manifest data/manifest.csv --rebuild` completes without manual steps and writes the ingestion report (KPI-12). | CI on every merge to `main` |
| AC-N3.2 | Every random choice is seeded, and the seeds are listed in the README: synthetic generator (`--seed 42`), CUAD sample selection, and the eval tuning/held-out split. Regenerating the synthetic documents produces files with identical `sha256`. | UT |
| AC-N3.3 | Two rebuilds from the same manifest with the same `chunker_version` and embedding model produce identical `chunk_id`s, chunk text and `index_version` (extends AC-3.9 to the whole corpus). | IT |
| AC-N3.4 | `requirements.txt` pins every dependency to an exact version, and the Docker image uses a fixed base (`python:3.11-slim`) with the re-ranker weights downloaded at build time. | CI (pin check), code review |
| AC-N3.5 | When the container starts with no `/data/chroma`, `scripts/bootstrap.py` downloads the latest index zip from the GitHub release, unpacks it and builds BM25 from SQLite. For ~15k chunks the BM25 build takes ≤ **5 s**, and `/health` then reports `ok` with the same `index_version` as the release. | DEP (restart test on W5 D3) |
| AC-N3.6 | Every eval result file records `index_version`, prompt version, `chunker_version`, `RELEVANCE_THRESHOLD`, `AS_OF_DATE`, the split used and all retrieval and generation parameters (AC-11.8), so the run can be repeated. | EVAL |
| AC-N3.7 | `scripts/fetch_sources.py --check` reports any vendor page whose `sha256` has changed since indexing. A changed page is reported, never replaced silently. | UT (fixture with a changed hash) |

### Not covered

Persistence of uploaded documents across host restarts (accepted risk R-08; the UI warns about it). Rebuilding with a different embedding model, which creates a separate Chroma collection by design (RAG design 6.4).

---

## NFR-4 Rate limits and retries

| | |
|---|---|
| **Requirement** | Calls to Gemini and Groq that fail for transient reasons (rate limits, server errors, timeouts) are retried with exponential backoff and jitter, within a time budget that fits the path they are on, and then fall back to a backup model or a degraded mode. Our own API limits each client so the shared free-tier quota is not used up by one user. |
| **Priority** | P0 |
| **Stories / risks** | US-01; R-01 (free-tier rate limits); A-5 (current Gemini/Groq limits fit our plan) |
| **Owner** | Workstream B (LLM and embedding client); Workstream D (API rate limit) |
| **Implemented in** | `clausecheck/llm/client.py` (`tenacity`), `ingest/embedder.py`, rate-limit middleware in `clausecheck/api/main.py`, `scripts/usage_report.py` |
| **Depends on** | NFR-1 (query-path budget), NFR-5 (cache reduces calls) |

### Retry policy

Two paths with different budgets, because a five-try policy with waits up to 32 s is fine for a background ingestion job but would break the 3 s TTFT gate on a user's question.

| | Ingestion path (index build, upload jobs) | Query path (embedding, rewrite, generation) |
|---|---|---|
| Retry on | HTTP 429, 500, 502, 503, 504; connection errors; timeouts | Same |
| Never retry | 400, 401, 403, 404, and other 4xx | Same |
| Backoff | Exponential with full jitter, 1 s → 32 s | Exponential with full jitter, starting at 250 ms |
| Stop after | `RETRY_MAX_ATTEMPTS` (5) | `QUERY_RETRY_BUDGET_MS` (2,000 ms) of total waiting, or 3 attempts, whichever comes first **[proposal]** |
| Then | Job fails cleanly with `embedding API error after retries` | Fallback (table below) |

| Call that failed | Fallback | User sees |
|---|---|---|
| Query embedding | BM25-only retrieval, re-rank and gate as usual | "Semantic search unavailable" notice (AC-5.11) |
| Rewrite | Use the raw question with supplier carry-over | Nothing different (logged) |
| Gemini generation (before first token) | Groq generation, same prompt, own retry policy | Nothing different (`fallback_used = true`) |
| Groq generation too | No answer | `error` event, HTTP 503, Retry button (AC-7.7) |
| Generation **after** tokens have streamed | No retry, no fallback **[proposal]** | `error` event; streamed text replaced by the error and Retry button |

### Acceptance criteria

**Retries**

| ID | Criterion | Verified by |
|---|---|---|
| AC-N4.1 | **Mocked 429.** With the client mocked to return 429, 429, then 200, an ingestion-path call succeeds on attempt 3, waits between attempts are within the backoff bounds, and 3 attempts are logged. | UT |
| AC-N4.2 | With the client mocked to return 429 on every call, an ingestion-path call stops after exactly **5** attempts and raises a retry-exhausted error; no single wait exceeds 32 s. | UT (time mocked) |
| AC-N4.3 | Responses 400, 401, 403 and 404 are **not** retried: exactly 1 attempt is made and the error is raised immediately. | UT, one case per status |
| AC-N4.4 **[proposal]** | When a 429 carries a `Retry-After` header, the next wait is at least that value, capped at 32 s on the ingestion path. On the query path, a `Retry-After` longer than the remaining budget skips straight to the fallback (Q-N5). | UT |
| AC-N4.5 **[proposal]** | On the query path, total time spent waiting between retries for one call never exceeds `QUERY_RETRY_BUDGET_MS` (2,000 ms), after which the fallback in the table runs (Q-N1). | UT (time mocked) |
| AC-N4.6 | Every retry is logged with the call type, attempt number, status code and wait time. `scripts/usage_report.py` reports 429 counts per day and per model. | UT |

**Fallbacks**

| ID | Criterion | Verified by |
|---|---|---|
| AC-N4.7 | When Gemini generation exhausts its retries before any token is sent, Groq is called with the same prompt; the answer streams normally and `query_log.fallback_used = true`. | API (mocked) |
| AC-N4.8 | When both Gemini and Groq fail, the response is an `error` event with HTTP 503, never a refusal (AC-7.7), and nothing is cached (AC-N5.5). | API (mocked) |
| AC-N4.9 **[proposal]** | When generation fails after at least one `token` event has been sent, no retry or fallback is attempted (it would repeat or contradict text already shown). An `error` event follows, the UI replaces the partial answer with the error and Retry button, and the partial answer is not cached (Q-N6). | API (mocked mid-stream failure), QA |
| AC-N4.10 | When the query embedding fails after retries, the request continues with BM25 only and the `semantic_search_unavailable` warning (AC-5.11). | API (mocked) |
| AC-N4.11 | Retrying an embedding batch never creates duplicate rows: Chroma upserts and SQLite writes are keyed by `chunk_id`, so a batch that half-succeeded and is retried leaves exactly one record per chunk. | IT |

**Our own API limit and quota use**

| ID | Criterion | Verified by |
|---|---|---|
| AC-N4.12 | Each client IP may make `RATE_LIMIT_PER_MIN` (30) requests to `/chat` and `/chat/stream` per minute. The 31st request within 60 s returns **429** with a `Retry-After` header and a JSON error body, and makes **0** LLM or embedding calls. | API |
| AC-N4.13 **[proposal]** | `/health` and `/suppliers` are not counted toward the per-IP limit, so the UI header and sidebar keep working while a user is limited (Q-N7). | API |
| AC-N4.14 | When the client disconnects mid-answer, generation stops within one chunk of output, no further tokens are requested, and `client_cancelled` is logged (TDD 13). | API |
| AC-N4.15 | Indexing embeds in batches of `EMBED_BATCH_SIZE` (50): a full build of ~15k chunks makes about 300 embedding calls, and an unchanged rebuild makes **0** (AC-1.9, AC-N5.9). | IT (call count on fixture corpus) |

### Not covered

Choice of fallback embedding model for indexing (RAG design 6.4: local MiniLM in its own Chroma collection). Paid-tier quotas (out of scope). Upload size limits (NFR-7).

---

## NFR-5 Caching

| | |
|---|---|
| **Requirement** | A question that has already been answered, for the same supplier, against the same index, prompt and settings, is served from the answer cache with no embedding or LLM call. Unchanged chunks are never re-embedded. A cached entry is never served once anything that could change its answer has changed. |
| **Priority** | P0 |
| **Stories / risks** | US-01; KPI-13; R-01 (rate limits) |
| **Owner** | Workstream B (embedding cache); Workstream D (answer cache) |
| **Implemented in** | `store/cache.py` (`answer_cache` and `embedding_cache` tables in SQLite), cache lookup in `rag/pipeline.py`, `GET /suppliers` cache in `frontend/app.py` |
| **Depends on** | FR-4 (`index_version`), FR-8 (rewritten question), FR-11 (logging) |

### What is cached

| Cache | Key | Stored | Lifetime |
|---|---|---|---|
| Embedding (documents) | `sha256(text + model_name)` | Vector | Until the embedding model changes |
| Embedding (queries) | `sha256(normalised query + model_name + "query")` | Vector | `ANSWER_CACHE_TTL_DAYS` (7) |
| Answer | `sha256(normalised rewritten question, supplier_id, index_version, prompt_version, config_version)` | Outcome, answer, citations, warnings | 7 days, or shorter (AC-N5.6) |
| Supplier list (frontend) | — | `GET /suppliers` response | 5 minutes; cleared on upload (AC-9.7) |

`config_version` **[proposal]** is a hash of every retrieval and generation parameter in RAG design section 11 (including `RELEVANCE_THRESHOLD`), so that re-tuning a parameter does not serve answers produced under the old one (Q-N8).

Normalising the question means: lowercase, collapse whitespace, strip trailing punctuation. Numbers, clause numbers and SKU codes are left as written.

### Acceptance criteria

**Hits**

| ID | Criterion | Verified by |
|---|---|---|
| AC-N5.1 | The same question asked twice for the same supplier returns `cache_hit: true` on the second request, with **0** LLM calls and **0** embedding calls (KPI-13, AC-11.11). | API (mock call counts) |
| AC-N5.2 | The cache lookup happens after the rewrite and supplier resolution, so the key uses the **rewritten** question and the resolved `supplier_id`. Two sessions whose follow-ups rewrite to the same stand-alone question share one entry; the session history itself is not part of the key. | API |
| AC-N5.3 | Questions that differ only in case, extra spaces or a trailing `?` hit the same entry. Questions that differ in any number, clause number or code (`Net 30` vs `Net 45`, `A-114` vs `A-115`) do **not**. | UT |
| AC-N5.4 | A cached answer is replayed through the same SSE events as a fresh one (`meta`, `token`, `citations`, `done`), with identical answer text and citations and `cache_hit: true` in `done` (AC-10.4). | API |

**What is and isn't stored**

| ID | Criterion | Verified by |
|---|---|---|
| AC-N5.5 | `answered` outcomes and the refusals `refused_low_score`, `refused_model_not_found` and `refused_no_citation` are cached (AC-7.11). `error` outcomes, client-cancelled streams and partial answers are **never** cached. | API, one case per outcome |
| AC-N5.6 **[proposal]** | An answer whose context included a certificate chunk expires at the end of its `AS_OF_DATE` day, not after 7 days, because certificate validity is computed against today's date and can change overnight (Q-N9). | UT (date mocked across midnight) |
| AC-N5.7 **[proposal]** | An answer produced in a degraded mode (`semantic_search_unavailable`) is not cached, so a temporary outage does not fix a weaker answer in place for 7 days (Q-N10). | API |

**Invalidation**

| ID | Criterion | Verified by |
|---|---|---|
| AC-N5.8 | Changing any one of `index_version` (e.g. after an upload, AC-9.7), `prompt_version` or `config_version` makes every earlier entry a miss. Entries older than `ANSWER_CACHE_TTL_DAYS` (7) are misses and are deleted at startup and once a day. | IT |
| AC-N5.9 | Re-running ingestion on an unchanged corpus makes **0** document embedding calls (AC-1.9). Changing one chunk's text re-embeds that chunk only. Changing the embedding model re-embeds everything into a new Chroma collection. | IT (call counts) |

**Robustness and observability**

| ID | Criterion | Verified by |
|---|---|---|
| AC-N5.10 | If reading or writing the cache raises an error (e.g. locked SQLite file), the request continues as a cache miss, the user gets a normal answer, and a `cache_error` warning is logged. A cache failure never fails a request. | API (mocked failure) |
| AC-N5.11 | Every request logs `cache_hit` (AC-11.2), and `scripts/usage_report.py` reports the daily hit rate and the number of LLM calls saved. | UT |
| AC-N5.12 | `eval/run_eval.py` sets `CACHE_ENABLED=false` for every metric run, so accuracy and latency are measured on fresh answers. The only eval check that uses the cache is the KPI-13 test, and the result file records the cache setting. | EVAL |

### Not covered

Caching of retrieval results or re-ranker scores (not needed for the latency budget). Sharing the cache across replicas (v1 runs one container). Persisting the answer cache across host restarts: it starts empty after a restart, which only costs extra calls.

---

## 8. How the NFRs interact

Several of these requirements pull against each other. The design choices above resolve each conflict explicitly instead of leaving it to whoever writes the code.

| Conflict | Resolution | Criteria |
|---|---|---|
| Retries (NFR-4) vs latency (NFR-1): five tries with waits up to 32 s would take a question well past 3 s | Two retry policies: full policy for ingestion, a 2 s budget on the query path before falling back | AC-N4.5, AC-N1.4 |
| Caching (NFR-5) vs latency measurement (NFR-1): cache hits would make TTFT look better than it is | Eval and the TTFT gate run with the cache off; cache-hit latency is measured separately | AC-N1.2, AC-N1.7, AC-N5.12 |
| Caching (NFR-5) vs correctness: a cached answer can go stale | Key includes index, prompt and config versions; certificate answers expire daily; degraded answers aren't stored | AC-N5.6 to AC-N5.8 |
| Fallbacks (NFR-4) vs streaming: switching models after text has streamed would repeat or contradict it | Fall back only before the first token; after that, send an error | AC-N4.9 |
| Rebuild in CI (NFR-3) vs rate limits (NFR-4): a full rebuild on every merge would spend ~300 embedding calls each time | Embedding cache carried between CI runs (Q-N11) | AC-N3.1, AC-N5.9 |
| Logging everything (FR-11) vs secrets (NFR-2) | Redaction filter and sentinel test on every log path | AC-N2.7, AC-N2.8 |

---

## 9. Traceability

### 9.1 Requirements to KPIs, risks and evidence

| NFR | KPIs / gates | Risks | Main evidence |
|---|---|---|---|
| NFR-1 Latency | KPI-07 **[gate]** | R-09, A-7 | `eval/results/<date>_deployed.md` (TTFT p50/p95, per-stage table) |
| NFR-2 Secrets | — | A-2 | `detect-secrets` CI job, `tests/api/test_secrets_sentinel.py`, gitleaks report |
| NFR-3 Rebuild | KPI-12 | R-08, R-11 | Clean-clone CI job, restart test on W5 D3 |
| NFR-4 Retries | — | R-01, A-5 | `tests/unit/test_llm_retry.py`, `tests/api/test_rate_limit.py`, usage report |
| NFR-5 Caching | KPI-13 | R-01 | `tests/api/test_cache.py`, usage report hit rate |

### 9.2 Delivery by week

From `development-plan.md` section 12.

| NFR | W1 | W2 | W3 | W4 | W5 |
|---|---|---|---|---|---|
| NFR-1 | | | search latency | first TTFT estimate | **deployed measurement, fixes** |
| NFR-2 | **`.env`, `.env.example`, detect-secrets** | | | | **host secrets, sentinel test** |
| NFR-3 | **seeds, fetch script** | ingest CLI | **clean-clone rebuild in CI** | | index zip, bootstrap |
| NFR-4 | **LLM client retries** | | **batched embedding** | Groq fallback | **per-IP limit** |
| NFR-5 | | | **embedding cache** | | **answer cache** |

### 9.3 Cross-references to functional criteria

| NFR criterion | Relies on |
|---|---|
| AC-N1.8 | AC-11.2 |
| AC-N1.10 | AC-5.10 |
| AC-N1.11 | AC-8.2, AC-8.6 |
| AC-N2.9 | AC-10.12 |
| AC-N3.3 | AC-3.9 |
| AC-N3.6 | AC-11.8 |
| AC-N4.8 | AC-7.7 |
| AC-N4.10 | AC-5.11 |
| AC-N5.1 | AC-11.11 |
| AC-N5.4 | AC-10.4 |
| AC-N5.5 | AC-7.11 |
| AC-N5.8 | AC-9.7 |
| AC-N5.9 | AC-1.9 |

---

## 10. Open questions

These came up while writing testable criteria and are not settled in the PRD, TDD or RAG design. The proposals are ours and need confirmation at the M1 review.

| ID | Question | Affects | Proposal |
|---|---|---|---|
| Q-N1 | The TDD's retry policy (5 tries, 1–32 s) applies to every Gemini call, which on the query path could hold a question for over a minute. Should the query path have its own budget? | AC-N4.5, AC-N1.4 | Yes: `QUERY_RETRY_BUDGET_MS = 2000`, max 3 attempts, then fall back. Ingestion keeps the TDD policy. Update TDD section 13. |
| Q-N2 | Should TTFT p95 have a target, or only be reported? | AC-N1.5 | Target p95 < 5 s as a guardrail, not an acceptance gate. |
| Q-N3 | Refusals stream no tokens, so TTFT doesn't measure them. Do they need a speed target? | AC-N1.6 | Yes, p50 `total_ms` < 1.5 s for refusals that skip generation, tracked as a guardrail. |
| Q-N4 | `detect-secrets` checks files, not history. Do we scan the git history? | AC-N2.4 | Yes, `gitleaks` on W1 D5 and W5 D5. |
| Q-N5 | Should `Retry-After` from the provider be honoured? | AC-N4.4 | Yes on ingestion (capped at 32 s); on the query path, a wait longer than the remaining budget goes straight to the fallback. |
| Q-N6 | What happens when generation fails after tokens have streamed? | AC-N4.9 | Send an `error` event; no retry or fallback mid-stream; nothing cached. |
| Q-N7 | Do `/health` and `/suppliers` count toward the 30/min per-IP limit? | AC-N4.13 | No; only `/chat` and `/chat/stream` are limited. |
| Q-N8 | The development plan keys the answer cache on question, supplier, index and prompt versions. A change to `RELEVANCE_THRESHOLD` or `CONTEXT_K` would still serve old answers. | AC-N5.8 | Add `config_version` (hash of RAG design section 11 parameters) to the key. |
| Q-N9 | A cached certificate answer ("valid: YES") can become wrong when the certificate expires inside the 7-day TTL. | AC-N5.6 | Answers whose context included a certificate chunk expire at the end of their `AS_OF_DATE` day. |
| Q-N10 | Should answers produced in BM25-only mode be cached? | AC-N5.7 | No. |
| Q-N11 | KPI-12 rebuilds the index from a clean clone on every merge to `main`, which spends ~300 embedding calls each time and risks R-01. | AC-N3.1 | Restore the embedding cache from the previous CI run (GitHub Actions cache keyed by embedding model), so a rebuild with an unchanged corpus makes 0 embedding calls. A truly cold rebuild runs weekly. |

---

ClauseCheck gives information from contracts. It does not give legal advice.
