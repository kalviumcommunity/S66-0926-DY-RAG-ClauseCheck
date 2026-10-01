# ClauseCheck — API Design

**Version:** v1 (draft)
**Status:** Sprint 2 — AI Application Development with RAG
**Owner:** ClauseCheck team

---

## 1. Overview

ClauseCheck is a negotiated-terms Q&A assistant for enterprise procurement buyers. Buyers ask natural-language questions ("What is the payment term with Supplier X?", "Does our Acme contract allow price escalation?") and receive answers **grounded in uploaded supplier contracts, pricing agreements and compliance documents**, with **clause-level citations**.

This document specifies the HTTP API between the frontend (Streamlit / web UI) and the backend RAG service.

| Endpoint | Method(s) | Purpose |
|---|---|---|
| `/api/v1/ask` | `POST` | Ask a question, receive a complete cited answer |
| `/api/v1/ask/stream` | `POST` | Ask a question, receive the answer as a token stream (SSE) |
| `/api/v1/upload` | `POST` | Upload one or more documents for ingestion |
| `/api/v1/documents` | `GET`, `GET /{id}`, `DELETE /{id}` | List, inspect and remove indexed documents |
| `/api/v1/health` | `GET` | Liveness / readiness of the service and its dependencies |

### 1.1 Architecture context

```
Client ──► API (FastAPI)
              │
              ├── /upload ──► Ingestion worker ──► Parser ─► Chunker ─► Embedder ─► Vector DB
              │                                                                    (+ metadata store)
              │
              └── /ask ─────► Retriever (vector + optional BM25) ─► Reranker ─► LLM ─► Answer + citations
```

- **Retrieval** returns the top-k chunks; each chunk carries `document_id`, `page`, `section` / `clause_ref` so the answer can cite precisely.
- **Ingestion** is asynchronous: `/upload` returns immediately with a `processing` status; clients poll `/documents/{id}`.

---

## 2. Conventions

### 2.1 Base URL & versioning
- Base path: `/api/v1`
- Breaking changes ship under `/api/v2`; additive fields may be added to v1 responses without notice, so clients must **ignore unknown fields**.

### 2.2 Formats
- Request / response bodies: `application/json; charset=utf-8` (except `/upload` → `multipart/form-data`, `/ask/stream` → `text/event-stream`).
- Field naming: `snake_case`.
- Timestamps: ISO 8601 UTC, e.g. `2026-10-01T07:58:00Z`.
- IDs: prefixed opaque strings — `doc_…` (document), `req_…` (request), `chk_…` (chunk).

### 2.3 Authentication
- Header: `Authorization: Bearer <api_key>`
- `/health` is unauthenticated (needed by load balancers / uptime checks).
- Missing or invalid key → `401 UNAUTHORIZED`.

> For the sprint demo a single static key from an env var (`CLAUSECHECK_API_KEY`) is sufficient. Per-user keys / OAuth are out of scope.

### 2.4 Request tracing
- Every response includes `X-Request-ID`. Clients may send their own; otherwise the server generates one (`req_…`).
- The same ID appears in logs and in error bodies for debugging.

### 2.5 Error format

All non-2xx responses use one envelope:

```json
{
  "error": {
    "code": "DOCUMENT_NOT_FOUND",
    "message": "No document with id doc_8f2a1c exists.",
    "details": { "document_id": "doc_8f2a1c" },
    "request_id": "req_31b9e0"
  }
}
```

| HTTP | `code` | When |
|---|---|---|
| 400 | `INVALID_REQUEST` | Malformed JSON, missing / invalid field |
| 401 | `UNAUTHORIZED` | Missing / invalid API key |
| 404 | `DOCUMENT_NOT_FOUND` | Unknown `document_id` |
| 409 | `DUPLICATE_DOCUMENT` | Same file (by SHA-256) already indexed |
| 413 | `FILE_TOO_LARGE` | File exceeds size limit |
| 415 | `UNSUPPORTED_FILE_TYPE` | File type not allowed |
| 422 | `NO_DOCUMENTS_INDEXED` | `/ask` called with an empty or fully filtered-out corpus |
| 429 | `RATE_LIMITED` | Too many requests (see `Retry-After`) |
| 500 | `INTERNAL_ERROR` | Unhandled server error |
| 502 | `LLM_UPSTREAM_ERROR` | LLM / embedding provider failed |
| 503 | `SERVICE_UNAVAILABLE` | Vector DB or model not ready |
| 504 | `UPSTREAM_TIMEOUT` | LLM / retrieval exceeded timeout |

### 2.6 Rate limits

| Endpoint | Limit (per API key) |
|---|---|
| `/ask`, `/ask/stream` | 30 req / min |
| `/upload` | 10 req / min |
| `/documents`, `/health` | 120 req / min |

Responses include `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`.

---

## 3. Shared schemas

### 3.1 `Citation`
Links a part of the answer back to an exact source passage.

```json
{
  "citation_id": 1,
  "document_id": "doc_8f2a1c",
  "document_name": "Acme_Supply_Agreement_2025.pdf",
  "page": 7,
  "section": "4. Payment Terms",
  "clause_ref": "4.2",
  "chunk_id": "chk_19a7",
  "snippet": "Supplier shall invoice monthly; Buyer shall pay within forty-five (45) days of receipt…",
  "relevance_score": 0.87
}
```

| Field | Type | Notes |
|---|---|---|
| `citation_id` | int | Matches inline markers `[1]`, `[2]` in `answer` |
| `document_id` | string | |
| `document_name` | string | Original filename |
| `page` | int \| null | 1-based; null for non-paginated sources |
| `section` | string \| null | Nearest heading detected at ingestion |
| `clause_ref` | string \| null | Clause number if detected (e.g. `4.2`, `Schedule B §3`) |
| `chunk_id` | string | Retrieved chunk |
| `snippet` | string | ≤ 400 chars of the supporting text |
| `relevance_score` | float | 0–1, reranker score |

### 3.2 `Document`

```json
{
  "document_id": "doc_8f2a1c",
  "filename": "Acme_Supply_Agreement_2025.pdf",
  "content_type": "application/pdf",
  "size_bytes": 482113,
  "sha256": "c1f0…9ab2",
  "status": "ready",
  "doc_type": "contract",
  "supplier": "Acme Industrial Ltd.",
  "effective_date": "2025-04-01",
  "expiry_date": "2027-03-31",
  "page_count": 24,
  "chunk_count": 61,
  "tags": ["raw-materials", "tier-1"],
  "error": null,
  "created_at": "2026-10-01T07:58:00Z",
  "updated_at": "2026-10-01T07:58:41Z"
}
```

**`status` lifecycle**

```
uploaded ─► processing ─► ready
                    └───► failed   (error.message populated)
```

**`doc_type`** enum: `contract` · `pricing_agreement` · `compliance` · `amendment` · `other`

---

## 4. Endpoints

### 4.1 `POST /api/v1/ask`

Ask a question and receive a complete, cited answer in one response.

**Request**

```json
{
  "question": "What are the payment terms in the Acme supply agreement?",
  "filters": {
    "document_ids": ["doc_8f2a1c"],
    "supplier": "Acme Industrial Ltd.",
    "doc_type": ["contract", "amendment"],
    "tags": ["tier-1"]
  },
  "top_k": 6,
  "include_sources": true,
  "conversation_id": "conv_42d1",
  "history": [
    { "role": "user", "content": "Which suppliers do we have for steel?" },
    { "role": "assistant", "content": "Acme Industrial and Northline Metals [1][2]." }
  ]
}
```

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `question` | string | ✅ | — | 3–1000 chars |
| `filters` | object | | `{}` | All filters are AND-ed; lists inside a filter are OR-ed |
| `filters.document_ids` | string[] | | | Restrict retrieval to these docs |
| `filters.supplier` | string | | | Case-insensitive match on extracted supplier |
| `filters.doc_type` | string[] | | | See `doc_type` enum |
| `filters.tags` | string[] | | | |
| `top_k` | int | | `6` | 1–20 chunks passed to the LLM after reranking |
| `include_sources` | bool | | `true` | If false, `citations` is omitted (markers still appear) |
| `conversation_id` | string | | null | Client-generated, used for logging / follow-ups |
| `history` | Message[] | | `[]` | Last ≤ 6 turns for follow-up questions; used to rewrite the query, **not** as a source of facts |

**Response `200 OK`**

```json
{
  "request_id": "req_31b9e0",
  "answer": "Acme invoices monthly, and payment is due within 45 days of invoice receipt [1]. A 1.5% early-payment discount applies if paid within 10 days [2].",
  "citations": [
    { "citation_id": 1, "document_id": "doc_8f2a1c", "document_name": "Acme_Supply_Agreement_2025.pdf", "page": 7, "section": "4. Payment Terms", "clause_ref": "4.2", "chunk_id": "chk_19a7", "snippet": "…pay within forty-five (45) days of receipt…", "relevance_score": 0.87 },
    { "citation_id": 2, "document_id": "doc_8f2a1c", "document_name": "Acme_Supply_Agreement_2025.pdf", "page": 8, "section": "4. Payment Terms", "clause_ref": "4.4", "chunk_id": "chk_19b2", "snippet": "…a discount of one and one-half percent (1.5%)…", "relevance_score": 0.81 }
  ],
  "answerable": true,
  "confidence": "high",
  "usage": {
    "retrieved_chunks": 20,
    "used_chunks": 6,
    "prompt_tokens": 2810,
    "completion_tokens": 74
  },
  "latency_ms": {
    "retrieval": 142,
    "rerank": 88,
    "generation": 1630,
    "total": 1875
  },
  "model": "gpt-4o-mini",
  "created_at": "2026-10-01T08:01:12Z"
}
```

| Field | Notes |
|---|---|
| `answer` | Markdown text with inline `[n]` markers that map to `citations[].citation_id` |
| `answerable` | `false` when retrieved context doesn't support an answer — see 4.1.1 |
| `confidence` | `high` · `medium` · `low`, derived from top rerank scores and citation coverage |
| `usage`, `latency_ms` | For observability and the sprint's evaluation report |

#### 4.1.1 Grounding rules (behavioural contract)
1. Every factual sentence in `answer` must carry at least one citation marker.
2. If no retrieved chunk scores above the relevance threshold (default `0.35`), the service returns **`200`** with:
   ```json
   {
     "answer": "I couldn't find this in the indexed documents. Try uploading the relevant contract or rephrasing the question.",
     "citations": [],
     "answerable": false,
     "confidence": "low"
   }
   ```
   It must **not** fall back to the LLM's general knowledge.
3. If sources conflict (e.g. an amendment overrides the base contract), the answer states both and cites each; amendments with a later `effective_date` are ranked first.
4. Citation markers that don't match a returned citation are stripped before responding.

**Errors:** `400`, `401`, `422 NO_DOCUMENTS_INDEXED`, `429`, `502`, `503`, `504`.

---

### 4.2 `POST /api/v1/ask/stream`

Same request body as `/ask`. The response is a **Server-Sent Events** stream so the UI can render tokens as they're generated.

**Request headers**

```
Accept: text/event-stream
Content-Type: application/json
Authorization: Bearer <api_key>
```

**Response `200 OK`** — `Content-Type: text/event-stream`

Events are emitted in this order:

| Order | `event` | `data` payload | Purpose |
|---|---|---|---|
| 1 | `meta` | `{ "request_id", "conversation_id", "model" }` | Sent immediately |
| 2 | `sources` | `{ "citations": [Citation, …] }` | Sent after retrieval + rerank, **before** generation, so the UI can show sources early |
| 3…n | `token` | `{ "delta": "text" }` | One or more tokens per event |
| n+1 | `done` | `{ "answerable", "confidence", "usage", "latency_ms" }` | Final event; stream closes after it |
| any | `error` | Error object (§2.5 `error` body) | Terminal; stream closes after it |
| any | `ping` | `{}` | Keep-alive every 15 s |

**Example stream**

```
event: meta
data: {"request_id":"req_7c11aa","conversation_id":"conv_42d1","model":"gpt-4o-mini"}

event: sources
data: {"citations":[{"citation_id":1,"document_id":"doc_8f2a1c","document_name":"Acme_Supply_Agreement_2025.pdf","page":7,"clause_ref":"4.2","snippet":"…within forty-five (45) days…","relevance_score":0.87}]}

event: token
data: {"delta":"Acme invoices monthly, and payment"}

event: token
data: {"delta":" is due within 45 days of receipt [1]."}

event: done
data: {"answerable":true,"confidence":"high","usage":{"prompt_tokens":2810,"completion_tokens":74},"latency_ms":{"total":1910}}
```

**Notes**
- Errors **before** the stream opens (auth, validation, rate limit) return normal JSON errors with the matching HTTP status.
- Errors **after** the stream opens are sent as an `error` event (HTTP status is already `200`).
- Unsupported-answer case: the stream sends `sources` with an empty list, the fallback message as `token`(s), then `done` with `answerable: false`.
- Client disconnect cancels generation server-side to save tokens.
- Server sets `Cache-Control: no-cache` and `X-Accel-Buffering: no` (disables proxy buffering).

**Client snippet (JS)** — `EventSource` only supports GET, so use `fetch` and read the body:

```js
const res = await fetch("/api/v1/ask/stream", {
  method: "POST",
  headers: { "Content-Type": "application/json", "Authorization": `Bearer ${KEY}` },
  body: JSON.stringify({ question })
});
const reader = res.body.getReader();
// decode chunks, split on "\n\n", parse "event:" and "data:" lines
```

---

### 4.3 `POST /api/v1/upload`

Upload one or more documents. Files are stored, de-duplicated, and queued for ingestion (parse → chunk → embed → index).

**Request** — `multipart/form-data`

| Part | Type | Required | Notes |
|---|---|---|---|
| `files` | file (repeatable) | ✅ | 1–10 files per request |
| `doc_type` | string | | Applied to all files; defaults to auto-detect |
| `supplier` | string | | Overrides auto-extracted supplier |
| `tags` | string | | Comma-separated, e.g. `raw-materials,tier-1` |
| `overwrite` | bool | | `false` default; if `true`, a duplicate replaces the existing doc instead of returning 409 |

**Constraints**

| Rule | Value |
|---|---|
| Allowed types | `.pdf`, `.docx`, `.txt`, `.md` (validated by magic bytes, not just extension) |
| Max size per file | 20 MB |
| Max total per request | 100 MB |
| Scanned PDFs | Accepted; OCR is applied if no text layer is found (slower) |

**Example (curl)**

```bash
curl -X POST https://<host>/api/v1/upload \
  -H "Authorization: Bearer $CLAUSECHECK_API_KEY" \
  -F "files=@Acme_Supply_Agreement_2025.pdf" \
  -F "files=@Acme_Pricing_Schedule_B.pdf" \
  -F "doc_type=contract" \
  -F "tags=raw-materials,tier-1"
```

**Response `202 Accepted`** — accepted for asynchronous processing.

```json
{
  "request_id": "req_a19f02",
  "accepted": [
    { "document_id": "doc_8f2a1c", "filename": "Acme_Supply_Agreement_2025.pdf", "status": "processing" },
    { "document_id": "doc_b33e70", "filename": "Acme_Pricing_Schedule_B.pdf", "status": "processing" }
  ],
  "rejected": [
    { "filename": "notes.xlsx", "error": { "code": "UNSUPPORTED_FILE_TYPE", "message": "Only PDF, DOCX, TXT and MD are supported." } }
  ]
}
```

- Partial success is allowed: valid files are accepted, invalid ones appear in `rejected`. If **all** files are rejected, the response is the matching 4xx error instead.
- Clients poll `GET /documents/{id}` until `status` is `ready` or `failed`.

**Ingestion pipeline (server-side, for reference)**

| Step | Default |
|---|---|
| Parse | PyMuPDF / python-docx; OCR fallback (Tesseract) |
| Structure detection | Headings and clause numbers via regex (`^\d+(\.\d+)*\s`, `Schedule [A-Z]`) |
| Chunking | Clause-aware: split on clause boundaries, max 800 tokens, 100-token overlap |
| Metadata extraction | Supplier, effective / expiry dates (LLM-assisted, best-effort) |
| Embedding | `text-embedding-3-small` (1536-d) or `all-MiniLM-L6-v2` (384-d) for local runs |
| Store | Vector DB (Chroma / FAISS / pgvector) + metadata table |

**Errors:** `400`, `401`, `409 DUPLICATE_DOCUMENT`, `413`, `415`, `429`.

---

### 4.4 `/api/v1/documents`

#### 4.4.1 `GET /api/v1/documents` — list documents

**Query parameters**

| Param | Type | Default | Notes |
|---|---|---|---|
| `status` | string | all | `processing` · `ready` · `failed` |
| `doc_type` | string | all | |
| `supplier` | string | | Partial, case-insensitive |
| `tag` | string | | |
| `q` | string | | Filename substring search |
| `sort` | string | `-created_at` | `created_at`, `filename`, `expiry_date`; prefix `-` for descending |
| `limit` | int | `20` | 1–100 |
| `cursor` | string | | Opaque cursor from previous `next_cursor` |

**Response `200 OK`**

```json
{
  "data": [ { "...": "Document object (§3.2)" } ],
  "pagination": {
    "limit": 20,
    "next_cursor": "eyJjcmVhdGVkX2F0IjoiMjAyNi0xMC0wMVQwNzo1ODowMFoifQ",
    "has_more": true
  },
  "total": 137
}
```

#### 4.4.2 `GET /api/v1/documents/{document_id}` — document detail

Returns the `Document` object plus ingestion details:

```json
{
  "...": "all Document fields",
  "ingestion": {
    "started_at": "2026-10-01T07:58:02Z",
    "completed_at": "2026-10-01T07:58:41Z",
    "ocr_used": false,
    "warnings": ["Page 19 contained no extractable text."]
  }
}
```

Optional query `?include_chunks=true&limit=50` returns `chunks: [{ chunk_id, page, section, clause_ref, text_preview }]` — useful for debugging retrieval.

**Errors:** `401`, `404 DOCUMENT_NOT_FOUND`.

#### 4.4.3 `DELETE /api/v1/documents/{document_id}` — remove document

Deletes the stored file, its metadata, **and all its vectors** so it can no longer be cited.

**Response `204 No Content`**

**Errors:** `401`, `404`, `409` if the document is still `processing` (retry after it finishes).

---

### 4.5 `GET /api/v1/health`

Unauthenticated. Two modes:

| Request | Purpose | Checks |
|---|---|---|
| `GET /health` | **Liveness** — is the process up? | None; always fast |
| `GET /health?deep=true` | **Readiness** — can it serve `/ask`? | Vector DB, embedding model, LLM provider, storage |

**Response `200 OK`** (healthy)

```json
{
  "status": "ok",
  "version": "1.0.0",
  "commit": "a1b2c3d",
  "uptime_s": 86412,
  "timestamp": "2026-10-01T08:05:00Z",
  "checks": {
    "vector_db":   { "status": "ok", "latency_ms": 12, "documents_indexed": 137, "chunks_indexed": 8421 },
    "embedding":   { "status": "ok", "model": "text-embedding-3-small" },
    "llm":         { "status": "ok", "model": "gpt-4o-mini", "latency_ms": 310 },
    "storage":     { "status": "ok" },
    "ingestion_queue": { "status": "ok", "pending": 2 }
  }
}
```

`checks` is included only when `deep=true`.

**Status semantics**

| `status` | HTTP | Meaning |
|---|---|---|
| `ok` | 200 | All checks pass |
| `degraded` | 200 | Non-critical issue (e.g. ingestion queue backed up, slow LLM) — `/ask` still works |
| `down` | 503 | Critical dependency failed (vector DB or LLM unreachable) |

- Deep checks are cached for 30 s to avoid hammering the LLM provider.
- No secrets, keys or internal hostnames appear in the response.

---

## 5. Non-functional requirements

| Area | Target |
|---|---|
| `/ask` latency | p50 < 2.5 s, p95 < 6 s |
| `/ask/stream` time-to-first-token | < 1.5 s |
| Ingestion | ~20-page PDF ready in < 60 s (no OCR) |
| Timeouts | Retrieval 5 s · LLM 30 s · total request 40 s |
| Citation accuracy | ≥ 90% of citations actually support their sentence (manual eval set) |
| "Not found" correctness | Unanswerable questions return `answerable: false` ≥ 90% of the time |
| CORS | Allow only the frontend origin(s) via env config |
| Logging | Structured JSON; log `request_id`, latency, token usage — **never** full document text or API keys |

---

## 6. Security notes
- Validate file type by content (magic bytes); reject executables and archives.
- Sanitize filenames; store files under generated IDs, not user-supplied names.
- **Prompt injection:** document text is placed in a clearly delimited context block; the system prompt instructs the model to treat it as data and ignore instructions inside documents.
- Contracts may be confidential — keep uploaded files in private storage; no public URLs.
- Run with least-privilege credentials for the vector DB and object storage.

---

## 7. Implementation sketch (FastAPI)

```python
from fastapi import FastAPI, UploadFile, File, Form, Depends, Query
from fastapi.responses import StreamingResponse

app = FastAPI(title="ClauseCheck API", version="1.0.0")

@app.post("/api/v1/ask", response_model=AskResponse, dependencies=[Depends(auth)])
async def ask(req: AskRequest): ...

@app.post("/api/v1/ask/stream", dependencies=[Depends(auth)])
async def ask_stream(req: AskRequest):
    return StreamingResponse(sse_generator(req), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.post("/api/v1/upload", status_code=202, dependencies=[Depends(auth)])
async def upload(files: list[UploadFile] = File(...),
                 doc_type: str | None = Form(None),
                 supplier: str | None = Form(None),
                 tags: str | None = Form(None),
                 overwrite: bool = Form(False)): ...

@app.get("/api/v1/documents", dependencies=[Depends(auth)])
async def list_documents(status: str | None = None, limit: int = Query(20, le=100),
                         cursor: str | None = None): ...

@app.get("/api/v1/documents/{document_id}", dependencies=[Depends(auth)])
async def get_document(document_id: str, include_chunks: bool = False): ...

@app.delete("/api/v1/documents/{document_id}", status_code=204, dependencies=[Depends(auth)])
async def delete_document(document_id: str): ...

@app.get("/api/v1/health")
async def health(deep: bool = False): ...
```

FastAPI auto-generates OpenAPI docs at `/docs` — keep this file and the Pydantic models in sync.

---

## 8. Open questions
1. Vector DB choice for deployment: Chroma (simple, file-based) vs pgvector (one DB for vectors + metadata)?
2. Hybrid search (BM25 + vectors) — needed for exact clause numbers and supplier names?
3. Should `/ask` support a `compare` mode (e.g. "compare payment terms across all steel suppliers") returning a structured table?
4. Persist conversation history server-side, or keep it client-only as in this draft?
5. Webhook / SSE notification when ingestion finishes, instead of polling?

---

## 9. Changelog
| Date | Version | Change |
|---|---|---|
| 2026-10-01 | v1 draft | Initial design: `/ask`, `/ask/stream`, `/upload`, `/documents`, `/health` |
