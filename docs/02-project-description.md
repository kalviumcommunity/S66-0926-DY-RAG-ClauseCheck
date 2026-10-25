# ClauseCheck — Project Description

**Sprint:** Simulated Work, Sprint 2: AI Application Development with RAG
**Track:** AI Application (RAG)
**Repository:** `FirstName_ClauseCheck_Kalvium-Community`
**Related documents:** [01-project-overview.md](01-project-overview.md)

---

## 1. Background

Enterprise procurement teams negotiate terms with hundreds of suppliers: prices and volume discounts, payment terms, delivery penalties, renewal conditions, liability caps, and compliance obligations. These terms are captured in **master agreements, statements of work, amendments, pricing schedules, and compliance documents**, usually stored as PDFs in shared folders or contract repositories.

The negotiation is done once, but the terms are **checked constantly**: when a buyer raises a purchase order, when an invoice arrives, when a contract approaches renewal, and when an audit asks whether a supplier's certification is current. Every check means finding the right document, confirming no later amendment changed it, and locating the exact clause.

## 2. Problem Statement

> An enterprise procurement team holds supplier contracts, pricing agreements, and compliance documents, but buyers cannot quickly verify negotiated terms because the answers are spread across hundreds of contracts.

### Why this is hard

| Difficulty | Consequence |
|---|---|
| **Volume**: hundreds of contracts across many suppliers | Manual search is slow; buyers skip verification |
| **Fragmentation**: terms split across MSAs, SOWs, amendments, and schedules | The first clause found may not be the one in force |
| **Precision**: answers are numbers, dates, and clause-specific conditions | A near-miss answer is a wrong answer |
| **Formats**: legal prose, pricing tables, scanned certificates | Generic search tools handle tables and structure poorly |
| **Trust**: buyers act on the answer financially | An unverifiable or invented answer is worse than no answer |

### Cost of the problem

Overpaying invoices that exceed agreed prices, missing early-payment discounts, missing renewal notice windows (and being locked into another term), and relying on expired supplier certifications.

## 3. Objectives

1. Let a buyer ask a question in plain language and receive the **exact negotiated term** in seconds.
2. Attach a **verifiable citation** (supplier, document, clause, page) to every answer.
3. **Refuse rather than guess** when the contracts do not contain the answer.
4. **Measure** retrieval and answer quality against a labelled test set, rather than judging by impression.
5. Deliver a **deployed, documented, reproducible** application by the end of the sprint.

## 4. Users and Use Cases

### Users

- **Procurement buyer (primary):** raises POs, checks invoices, needs fast and exact answers.
- **Category / procurement manager:** prepares renewals and negotiations, needs current terms and their history.
- **Compliance / vendor-risk analyst:** checks NDAs, DPAs, certifications, and insurance requirements.

### Representative questions

| Category | Example question |
|---|---|
| Payment | "What are the payment terms with Supplier X? Is there an early-payment discount?" |
| Pricing | "What is the unit price for SKU A-114 at 500 units under the Supplier X price schedule?" |
| Penalties | "Is there a late-delivery penalty in the Acme supply agreement?" |
| Renewal | "Does the Acme contract auto-renew, and how much notice do we need to terminate?" |
| Liability | "What is the liability cap with our logistics vendor?" |
| Termination | "Can we terminate the Supplier Y agreement for convenience?" |
| Warranty | "How long is the warranty period on Supplier Z's products?" |
| Compliance | "Is Supplier Y's ISO 27001 certificate still valid? Do we have a signed DPA with them?" |
| Follow-up | "And what about their notice period?" (after a previous question about Supplier Y) |
| Unanswerable | "What are our terms with Supplier Q?" (Supplier Q is not in the corpus → refusal) |

## 5. Proposed Solution

**ClauseCheck** is a Retrieval-Augmented Generation (RAG) assistant over the contract repository. Retrieval finds the relevant clauses; the language model only phrases an answer from those clauses and cites them.

### 5.1 Pipeline

```
Documents (PDF / HTML / TXT / DOCX)
        │
        ▼
[1] Ingestion ─ load, extract text and tables, clean, attach source identity
        │
        ▼
[2] Clause-aware chunking ─ split on section/clause headings, token-sized, with overlap
        │                    metadata: supplier, doc_type, clause_no, page, effective_date
        ▼
[3] Embedding ─ batch API calls with retries, backoff, and cost tracking
        │
        ▼
[4] Vector store ─ embeddings + text + metadata; BM25 index alongside
        │
   ─ ─ ─ ─ ─ ─ ─ ─ ─ ─  query time  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
        │
[5] Query handling ─ rewrite follow-ups using chat history; detect supplier name
        │
        ▼
[6] Hybrid retrieval ─ supplier-filtered vector search + BM25 → merge → cross-encoder re-rank
        │
        ▼
[7] Relevance gate ─ if top scores are weak → refuse
        │
        ▼
[8] Grounded generation ─ inject top chunks within token budget; answer only from context
        │
        ▼
[9] Response ─ answer + citations as JSON → streamed to chat UI
```

### 5.2 Key design decisions

| Decision | Rationale |
|---|---|
| **Clause-aware chunking** instead of fixed-size splits | Contract meaning lives at clause level; fixed splits cut conditions in half |
| **Supplier metadata filtering** | Nearly every question names a supplier; filtering removes most wrong candidates |
| **Hybrid search (vector + BM25)** | Semantic search misses exact tokens like "Net 45", clause numbers, and SKUs |
| **Cross-encoder re-ranking** | Improves precision of the few chunks sent to the model |
| **Relevance gate before generation** | The model cannot invent an answer if weak retrieval blocks it first |
| **Structured JSON output** | Makes citations machine-checkable and renderable in the UI |
| **`effective_date` and `parent_doc_id` metadata** | Lets answers surface amendments that changed an original term |

## 6. Requirements

### 6.1 Functional

| ID | Requirement |
|---|---|
| FR-1 | Ingest PDF, HTML, TXT, and DOCX documents into plain text, preserving source identity |
| FR-2 | Extract tables from pricing schedules without losing row/column structure |
| FR-3 | Chunk documents by clause, with token-based sizing and overlap |
| FR-4 | Store each chunk with supplier, document type, clause number, page, and effective date |
| FR-5 | Answer natural-language questions using hybrid, supplier-filtered retrieval |
| FR-6 | Return every answer with at least one citation mapping to a real document and clause |
| FR-7 | Refuse with a clear message when retrieval confidence is below threshold |
| FR-8 | Support follow-up questions within a conversation |
| FR-9 | Allow new documents to be uploaded and indexed at runtime |
| FR-10 | Stream answers to a chat UI that displays sources |
| FR-11 | Log queries, retrieved chunks, answers, latency, and token usage |

### 6.2 Non-functional

| ID | Requirement |
|---|---|
| NFR-1 | Median time to first streamed token under 3 seconds |
| NFR-2 | API keys stored only in `.env`; `.env.example` committed; no secrets in the repository |
| NFR-3 | Ingestion and indexing reproducible from a single documented command |
| NFR-4 | Graceful handling of API rate limits (retries with exponential backoff) |
| NFR-5 | Repeated queries served from cache |

## 7. Data

### 7.1 Sources

| Source | Contents | Role | Licence |
|---|---|---|---|
| **CUAD** (Atticus Project) | Real commercial contracts: supply, manufacturing, outsourcing, service, maintenance, distributor, hosting | Core contract corpus + clause-level ground truth | CC BY 4.0 |
| **SEC EDGAR** (EX-10 exhibits) | Additional contracts and amendments paired with originals | Tests amendment handling | Public filings |
| **Public vendor DPAs / SLAs** | Real compliance documents | Compliance questions | Publicly published; URLs recorded |
| **Synthetic documents** | Price schedules with volume tiers; compliance and insurance certificates with expiry dates | Exact-number and date questions | Generated; tagged `is_synthetic` |

### 7.2 Target corpus

About **120–200 contracts**, **20–40 amendments**, **30–50 price schedules**, and **30–50 compliance documents** across **30–50 suppliers**, in at least three formats.

### 7.3 Manifest

`data/manifest.csv` records every document:
`doc_id, supplier, doc_type, effective_date, parent_doc_id, source, source_url, license, format, is_synthetic`

## 8. Evaluation Plan

A labelled question set in `eval/questions.jsonl` with three groups:

1. **Real-contract questions** (~30), derived from CUAD clause labels (renewal term, cap on liability, minimum commitment, termination for convenience, warranty duration, and others).
2. **Exact-value questions** (~20) on synthetic documents, with ground truth written at generation time.
3. **Unanswerable questions** (~15), to test refusals.

| Metric | Target |
|---|---|
| Retrieval recall@5 | ≥ 0.85 |
| Answer correctness | ≥ 85% |
| Citation accuracy (cited clause is the correct one) | ≥ 90% |
| Correct refusals on unanswerable questions | ≥ 90% |
| Median time to first token | < 3 s |

Every retrieval or prompt change is re-run against this set, and results are recorded in the PR description.

## 9. Technology Stack

| Layer | Tools |
|---|---|
| Parsing | PyMuPDF, pdfplumber (tables), BeautifulSoup, python-docx |
| Tokens | tiktoken / model token counter |
| LLM | Gemini API (free tier via AI Studio); Groq as backup |
| Embeddings | Gemini embedding API; sentence-transformers as local fallback |
| Vector store | ChromaDB or Qdrant |
| Keyword search | rank_bm25 |
| Re-ranking | Cross-encoder (ms-marco-MiniLM-L-6-v2) |
| Backend | FastAPI |
| Frontend | Streamlit |
| Logging / cache | Python logging, SQLite |
| Evaluation | Custom scripts; RAGAS (optional) |
| Deployment | Streamlit Community Cloud / Hugging Face Spaces / Render |
| Collaboration | GitHub (branches, issues, PRs, Kanban board) |

## 10. Timeline (5 weeks)

| Week | Phase | Key outputs |
|---|---|---|
| 1 | **Foundations & planning** | Team charter, repo setup, LLM basics, corpus sourcing, manifest, PRD and mock UX submitted |
| 2 | **Design & ingestion** | RAG architecture design approved; loading, cleaning, clause chunking, metadata, ingestion validation |
| 3 | **Embeddings & retrieval** | Batch embedding, vector store, top-k search, supplier filtering, hybrid search, re-ranking, recall testing |
| 4 | **Grounded generation** | Context injection, grounded answers, citations, refusal gate, conversational follow-ups, answer evaluation |
| 5 | **App & delivery** | FastAPI endpoints, upload endpoint, streaming chat UI, caching/logging, deployment, documentation, final submission |

Building (Phase 4 onward) starts only after the PRD and RAG architecture design are approved.

## 11. Deliverables

- Deployed ClauseCheck application (public URL)
- GitHub repository with README, team charter, setup instructions, and `.env.example`
- Reproducible ingestion and indexing scripts
- `data/manifest.csv` with source and licence information
- Evaluation set and results report
- PRD, mock UX, and RAG architecture design documents
- Daily PRs; concept walkthrough videos

## 12. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Free-tier API rate limits during batch embedding | Batching, exponential backoff, caching; local sentence-transformers fallback |
| Pricing tables break during extraction | pdfplumber table extraction; tables kept as single chunks with row context |
| Outdated terms returned when amendments exist | `effective_date` / `parent_doc_id` metadata; show the amendment in citations |
| Model answers beyond retrieved context | Relevance gate, strict grounding prompt, refusal tests in the eval set |
| Supplier names written inconsistently | Normalised supplier names in the manifest; alias list for query matching |
| Corpus not representative of one real enterprise | Stated explicitly as an assumption (see below) |

## 13. Assumptions and Limitations

- CUAD and EDGAR contracts come from many different companies; the project **simulates them as one enterprise's supplier contract repository**.
- Synthetic pricing and compliance documents fill gaps where no public data exists, and are labelled as synthetic.
- Free-tier LLM APIs are acceptable for public and synthetic data. A production deployment on confidential contracts would require a paid or privately hosted model.
- Portfolio-wide aggregation questions (e.g., "which suppliers renew next quarter?") are out of scope, because top-k retrieval cannot see every contract at once; this is listed as future work.
- ClauseCheck provides information from contracts; it does not give legal advice.
