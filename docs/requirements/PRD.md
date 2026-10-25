# ClauseCheck: Product Requirement Document

Sprint 2, Simulated Work (AI Application Development with RAG)
Repo: `FirstName_ClauseCheck_Kalvium-Community`
See also: [01-project-overview.md](../01-project-overview.md), [02-project-description.md](../02-project-description.md), [data-sourcing.md](../data/data-sourcing.md), [data-validation-report.md](../data/data-validation-report.md), [mock-ux.md](../ux/mock-ux.md), [tdd.md](../architecture/tdd.md), [rag-architecture-design.md](../architecture/rag-architecture-design.md), [development-plan.md](../planning/development-plan.md), [roadmap.md](../planning/roadmap.md)
Version: 1.1, 2026-10-06
Status: resubmitted for review (milestone M1) after the M1 review comments. We start building only after this PRD and the RAG architecture design are approved.

This PRD covers what we are building and why: the problem, who it is for, what is in and out of scope, how we will measure success, and what could go wrong. How retrieval and generation work is covered in [rag-architecture-design.md](../architecture/rag-architecture-design.md). If the two documents disagree on scope or success criteria, this one is updated first and the design follows.

| Version | Date | Change | Approved by |
|---|---|---|---|
| 1.0 | 2026-10-01 | First version for M1 review | |
| 1.1 | 2026-10-06 | M1 review fixes: (1) every dataset field validated, no "To check" left (section 5, [data-validation-report.md](../data/data-validation-report.md)); (2) KPI cards above the fold on the main screen (F-16, section 11); (3) Insights dashboard with charts and data tables (F-17, FR-12, section 6.4). Full list in section 16.3. | |

Changes to scope (section 8), KPIs (section 6) or acceptance gates need a new version of this document and a row in the table above.

## Contents

1. [Summary](#1-summary)
2. [Business problem](#2-business-problem)
3. [Stakeholders](#3-stakeholders)
4. [Business impact](#4-business-impact)
5. [Data sources](#5-data-sources)
6. [KPIs and success metrics](#6-kpis-and-success-metrics)
7. [Users, user stories and workflow](#7-users-user-stories-and-workflow)
8. [Scope](#8-scope)
9. [Requirements](#9-requirements)
10. [Data workflow](#10-data-workflow)
11. [UI layout and states](#11-ui-layout-and-states)
12. [Risks](#12-risks)
13. [Assumptions](#13-assumptions)
14. [Dependencies, approvals and timeline](#14-dependencies-approvals-and-timeline)
15. [Validation checklist](#15-validation-checklist)
16. [AI-assisted review and M1 review response](#16-ai-assisted-review-and-m1-review-response)
17. [Decisions, open questions and sign-off](#17-decisions-open-questions-and-sign-off)
18. [Appendix](#18-appendix)

---

## 1. Summary

**Problem.** Procurement buyers can't quickly check negotiated supplier terms (price, payment, penalties, renewal, liability, compliance) because the answers are spread across hundreds of contracts, amendments, price schedules and compliance documents. Looking one up by hand takes several minutes, so buyers often skip it. That leads to overpaid invoices, missed discounts and renewal windows, and expired supplier certificates going unnoticed.

**What we're building.** ClauseCheck, a question-answering assistant for one supplier at a time. It finds the relevant clauses with hybrid search, answers only from those clauses, cites the clause for every term, and says "not found" when the contracts don't contain the answer. It comes with a FastAPI backend, a Streamlit app, document upload, an evaluation suite and a public deployment. The app's main screen shows **five KPI cards above the fold** (questions asked, answer rate, time to checked answer, time to first token, citation accuracy), and an **Insights dashboard** shows charts and data tables of usage, answer quality and corpus coverage.

**What we're not building.** Questions across the whole portfolio, comparisons between suppliers, a contract-term portfolio dashboard (renewal timelines, liability-cap mix), legal advice, drafting, OCR or ERP integration (section 8.2).

**How we'll know it works.** On the held-out evaluation questions at the end of week 5: recall@5 of at least 0.85, at least 85% correct answers, at least 90% correct citations, at least 90% correct refusals, no more than 10% wrong refusals, and a median time to first token under 3 seconds. In a usability session, testers should get to a checked answer in 30 seconds or less (median). Every dashboard figure must match a direct recomputation from the logs (KPI-15).

**What we need.** The CUAD dataset, EDGAR amendments, public vendor DPAs and SLAs, our synthetic generator, Gemini and Groq free-tier keys, Hugging Face Spaces and Streamlit Community Cloud, and approval of this PRD (M1) and the RAG design (M2). All dataset fields were validated on 2026-10-06 ([data-validation-report.md](../data/data-validation-report.md)).

**Main risks.** Free-tier rate limits, amendments not being retrieved (so an old term is returned), the refusal threshold overfitting our eval set, a corpus that is easier than a real company's, and dashboard numbers being misread when samples are small. All are in section 12, and the assumptions behind them are in section 13.

---

## 2. Business problem

### 2.1 Problem statement

| | |
|---|---|
| Problem | An enterprise procurement team keeps contracts, pricing agreements and compliance documents for about 100 to 140 suppliers, 30 to 50 of which are key suppliers with several documents each (about 120 to 200 contracts, 20 to 40 amendments, 30 to 50 price schedules and 30 to 50 compliance documents). To check a term, a buyer has to find the right document, check whether a later amendment changed it, and then find the clause. We estimate this takes about 10 minutes per question (assumption A-3, which we will measure in week 2). Because it's slow, buyers skip it, and mistakes cost money: invoices paid above the agreed price, early-payment discounts missed, renewal notice deadlines missed, and expired certificates relied on. |
| Goal | A buyer asks one question about one supplier and gets the term currently in force, with a link to the clause, in 30 seconds or less (median, including reading the clause). When the contracts don't contain the answer, the buyer gets a fixed refusal message instead of a guess. |
| Primary users | Procurement buyers who raise purchase orders and approve invoices. |
| Secondary users | Category managers, compliance / vendor-risk analysts, and the procurement team lead who tracks whether the tool is used and trusted. |
| Success criteria | All six acceptance gates in section 6.2 met on the held-out split by W5 D4, plus a median time to checked answer of 30 s or less and at least 80% task success in the W5 usability session (KPI-01, KPI-09). |
| Boundary | Questions about one supplier's terms in the indexed documents. Portfolio questions such as "which suppliers auto-renew next quarter?" are not part of v1. |

The supplier count reflects what the data validation found: the 178 procurement-type CUAD contracts come from 106 different companies, so most suppliers have one contract, and the amendments, price schedules and certificates are concentrated on 30 to 50 key suppliers (decision DV-7 in [data-validation-report.md](../data/data-validation-report.md)).

### 2.2 Why it's hard

| Difficulty | What happens today | What ClauseCheck has to do |
|---|---|---|
| Volume: hundreds of documents, many suppliers | Searching takes too long, so buyers don't | Search only the named supplier's documents |
| Fragmentation: terms split across MSAs, SOWs, amendments and schedules | The first clause found may have been replaced | Link amendments to originals and give the amended term |
| Precision: answers are numbers, dates and conditions | A close answer is still a wrong answer | Match exact text like `Net 45`, `7.2`, `A-114`; copy values as written; check numbers against the cited clause |
| Formats: legal text, pricing tables, certificates | Ordinary search handles tables badly | Split by clause; keep tables together with their header row |
| Trust: buyers act on the answer with money | A wrong answer that looks right is worse than no answer | Cite every term; refuse when the evidence is weak |
| Visibility: nobody can see whether lookups happen or work | The team lead can't tell if the tool is used, fast or trusted | Show usage, quality and speed as KPI cards and a dashboard |

### 2.3 The question ClauseCheck answers

What is the negotiated term (price, payment, penalty, renewal or liability) with a given supplier, and where exactly in the contracts does it say so?

A second, smaller question is answered for the team running the tool: is ClauseCheck being used, is it answering, and is it meeting its targets?

The traceability table in section 18.1 links every requirement back to these questions.

---

## 3. Stakeholders

### 3.1 Stakeholder map

| Type | Who | Role | What they need | How often |
|---|---|---|---|---|
| Primary users | Procurement buyers (P1) | Check terms before raising POs and approving invoices | Exact price, payment and penalty terms with a clause they can open | Many times a day |
| Secondary users | Category managers (P2) | Prepare renewals and negotiations | Current renewal, notice, termination and liability terms, and what amendments changed | Weekly, and before renewals |
| Secondary users | Compliance / vendor-risk analysts (P3) | Check DPAs, SLAs and certificates | Whether a certificate is valid today; DPA and SLA terms | Weekly and during audits |
| Secondary users | Document maintainer (P4, a team member) | Adds new contracts and amendments | Upload a file and have it answerable after one job; see which questions go unanswered | When documents arrive; weekly review of gaps |
| Secondary users | Procurement team lead (P6) | Sponsors the tool and reports on it | Usage, answer rate, speed and quality at a glance | Daily glance; weekly review |
| Data owners | The Atticus Project | Publishes CUAD (contracts and clause labels) | Attribution under CC BY 4.0 | Static release |
| Data owners | U.S. SEC (EDGAR) | Hosts public contract filings and amendments | Fair-access rules: declared User-Agent, under 10 requests/s (we use 2) | Static |
| Data owners | Vendors publishing DPAs and SLAs | Own the copyright on their documents | No redistribution; URL shown in citations | Pages change without notice |
| Data owners | Workstream A (team) | Owns the manifest, supplier list, synthetic generator, ingestion and data validation | Manifest passes validation; seeds recorded | Ongoing |
| Approvers | Sprint mentor | Business sign-off on the PRD and mock UX (M1) and final submission (M7) | A clear, measurable, bounded PRD | M1, weekly reviews, M7 |
| Approvers | Sprint mentor | Technical sign-off on the RAG design (M2) | A defensible design with acceptance gates | M2 |
| Builders | Workstreams B, C, D (team) | Retrieval; generation and evaluation; app, dashboard and platform | Clear scope, KPIs and requirements | Daily |

Owners and reviewers for each workstream are named in the team charter. Each PR is reviewed by someone from a different workstream.

### 3.2 Who decides what

R = responsible, A = accountable, C = consulted, I = informed.

| Decision | Users (personas) | A | B | C | D | Mentor |
|---|---|---|---|---|---|---|
| Problem and scope (this PRD) | C | R | C | R | C | A |
| Corpus, manifest, licensing, data validation | I | R/A | C | C | I | I |
| Retrieval design and parameters | I | C | R/A | C | I | C |
| Prompts, refusals, eval set | C | C | C | R/A | I | C |
| API, UI, deployment | C | I | I | C | R/A | I |
| KPI cards and dashboard metrics | C (P6) | I | I | C | R/A | C |
| Acceptance on the held-out split | I | R | R | R | R | A |

The personas are simulated. We consult them through the mock UX review and the week 5 usability session.

---

## 4. Business impact

ClauseCheck runs on a simulated enterprise repository (assumption A-1), so the numbers below come from a simple model. Each input is listed, and where we can measure an input during the sprint, we will replace our estimate with the measured value.

### 4.1 Operational impact

| Input | Value | Where it comes from |
|---|---|---|
| Buyers on the team | 10 | Our assumption (A-8) |
| Term checks per buyer per day | 12 | Our assumption (A-8) |
| Minutes per manual check | about 10 | Assumption A-3, measured in W2 by timing team members on 20 tuning questions |
| Minutes per check with ClauseCheck | 0.5 or less | KPI-01 target |

Today: 10 × 12 × 10 = 1,200 minutes, or 20 hours of buyer time a day. With ClauseCheck: 10 × 12 × 0.5 = 60 minutes, about 95% less. We will update this once we have the W2 measurement.

The bigger effect is that a 30-second check is quick enough to do every time, so buyers stop skipping it. Once the app is live, the "time to checked answer" KPI card (M-03) measures this from real use instead of from our estimate.

### 4.2 Cost impact

| Problem | How money is lost | Example (illustrative only) |
|---|---|---|
| Missed early-payment discounts | Buyer doesn't know a "2% if paid within 10 days" clause exists | $10M yearly spend on 2/10 terms, 10% of eligible invoices paid late, 2% discount: $20,000 a year |
| Overpaid invoices | Invoice price is above the agreed tier and no one checks | Each 1% overcharge on $10M: $100,000 a year |
| Missed renewal notice | An auto-renewing contract renews because notice wasn't sent in time | One unwanted 12-month renewal of a $200k/year contract: $200,000 |
| Expired certificates | A supplier's ISO 27001 or insurance certificate lapsed | Audit finding and contractual exposure (not estimated) |

These are worked examples on made-up inputs, not figures for a real company. They show the scale: a single avoided renewal is worth far more than the cost of building the tool.

### 4.3 User experience impact

| Today | With ClauseCheck |
|---|---|
| Search folders and guess which document applies | Ask one question in plain English |
| No easy way to tell if an amendment changed the term | The amended term is given, along with the term it replaced |
| Answers from memory or colleagues can't be checked | Each term has a `[C#]` citation that opens the clause |
| A wrong answer looks the same as a right one | Weak evidence gives a grey "not found" box instead of an answer |
| Every follow-up starts from scratch | "And their notice period?" stays on the same supplier |
| Nobody knows how often lookups fail or which documents are missing | The dashboard lists unanswered questions by supplier, so the maintainer knows what to upload |

### 4.4 Why now

- This is the problem assigned in the sprint brief, and the corpus plan in [data-sourcing.md](../data/data-sourcing.md) is ready and validated ([data-validation-report.md](../data/data-validation-report.md)).
- Everything we need (embeddings, hybrid search, a small re-ranker, Streamlit charts) is available on free tiers, so we can build it in five weeks without paying for licences.
- The roadmap ([roadmap.md](../planning/roadmap.md), Part B) builds portfolio questions and renewal/expiry alerts on top of v1, using the same citations.

---

## 5. Data sources

Every field below was validated on 2026-10-06 against the actual data or the source's published file listing. The checks, numbers and evidence IDs (`E-##`) are in [data-validation-report.md](../data/data-validation-report.md). Each field has one of two statuses:

- **Confirmed**: checked on the data, with the result recorded.
- **Known issue (handled)**: checked, a problem was found, and a fixed ingestion rule handles it. Decisions made because of a finding are numbered `DV-#`.

No field is waiting on a future check.

### 5.1 Sources

| Source | Owner | What we use | Target | Formats | Licence | Refresh |
|---|---|---|---|---|---|---|
| CUAD v1 | The Atticus Project | Supply, manufacturing, outsourcing, service, maintenance, distributor and hosting contracts, plus expert clause labels | 120–137 contracts (137 qualify, E-04) | PDF, TXT | CC BY 4.0 | Fixed release; sample chosen with a fixed seed |
| SEC EDGAR EX-10 | U.S. SEC | Amendments paired with their originals; supply contracts with payment terms | 20–40 pairs (973 candidate filings for one query, E-06) | HTML, TXT, some PDF | Public filings | Fixed (filings don't change) |
| Vendor DPAs and SLAs | Each vendor | Data processing addenda, service level agreements | 30–50 compliance docs, with certificates | HTML, PDF | Vendor copyright; not redistributed | Re-checked by file hash (`fetch_sources.py --check`) before each weekly review |
| Synthetic documents | Workstream A | Price schedules with volume tiers; ISO-style and insurance certificates | 30–50 schedules and certificates, on the 30–50 key suppliers | PDF, DOCX | Ours | Regenerated with `generate_synthetic.py --seed 42` |
| Uploads | Document maintainer | Any new PDF, HTML, TXT or DOCX | No fixed number, 20 MB max each | All four | Supplied by the user | Indexed when uploaded; may be lost when the free host restarts (R-08) |
| App logs | Workstream D | `query_log`, `retrieval_log`, `clause_open_log`, eval result files | All questions asked in the app | SQLite, JSON | Ours | Written on every request; read by the dashboard (FR-12) |

### 5.2 CUAD v1

| File or field | Used for | Status | Evidence | Notes |
|---|---|---|---|---|
| `CUAD_v1.json` contract text (`context`) | TXT loader input (about 20% of contracts, and every contract whose PDF has no text layer) | Confirmed | E-01, E-04 | 510 contracts, all with text. It is the exact text the labels point into (DV-2). |
| `CUAD_v1.json` labels and `answer_start` offsets | Ground truth for about 30 eval questions; mapping each answer to our `chunk_id` | Confirmed | E-04 | 13,823 of 13,823 offsets point exactly to the labelled text (DV-1). Mapping is re-run whenever the chunker changes (R-11). |
| `master_clauses.csv` | Human-readable cross-reference only | Confirmed | E-02 | Exists (3.96 MB) but has no offsets, so it is not the ground-truth source (DV-1). |
| `full_contract_pdf/Part_{I,II,III}/<Type>/*.pdf` | Main input to the PDF loader | Confirmed | E-02, E-05 | Extra `Part_*` level; folder names vary between parts and are normalised (DV-3). |
| PDF text layer | Parsing | Known issue (handled) | E-05 | Sampled PDF has a text layer. Rule: a PDF averaging under 200 characters per page is loaded from its `CUAD_v1.json` text instead, so no contract is lost and no OCR is needed. Count reported by ingestion. |
| Title / file name | Tracing back to EDGAR; filing date | Known issue (handled) | E-04 | Two patterns: `FILER_MM_DD_YYYY-EX-10-TYPE` (301) and `Filer_YYYYMMDD_FORM_EX-10.x_ID_EX-10.x_Type` (168). 41 free-form titles have no date and are excluded (DV-4). Saved in `data/sources/cuad_index.csv`. |
| Contract type | Filtering to procurement types | Confirmed | E-02, E-04 | 178 procurement-type contracts; 137 have labels in at least 3 procurement categories. |
| Label categories | Renewal Term, Notice Period to Terminate Renewal, Expiration Date, Cap on Liability, Uncapped Liability, Termination for Convenience, Warranty Duration, Liquidated Damages, Price Restrictions, Most Favored Nation, Minimum Commitment, Volume Restriction, Insurance, Audit Rights, Parties, Effective Date, Agreement Date, Governing Law | Confirmed | E-04 | All 18 present. No payment-terms category exists (0 of 41), so payment questions use EDGAR and synthetic documents. |
| Label coverage | Number of eval questions per category | Known issue (handled) | E-04 | Most Favored Nation (8 contracts) and Price Restrictions (11) are thin: at most 2 questions each. An empty label becomes an unanswerable question only after a hand check. |
| Label length | LLM judge reference | Known issue (handled) | E-04 | Median about 300 characters for clause categories; labels cover whole clauses, so the judge compares meaning, not wording. |
| Redaction markers | `has_redaction`; excluding redacted values | Known issue (handled) | E-04 | 74 of 178 contracts (42%) have markers, in six forms: `[*****]`, `[***]`, `[*]`, `***`, `[**]`, "confidential treatment". One pattern covers all six (DV-5). 294 of 4,707 label spans contain a marker and are never used as answerable questions. |
| Page numbers and footers in text | Cleaning; citations | Known issue (handled) | E-04, E-05 | No form-feed page breaks; page-number lines in 222 contracts and `Source: {COMPANY}, {FORM}, {date}` footers in 180. The cleaner removes both (DV-6). TXT citations show the clause only (decision D3). |
| `effective_date` | Term in force | Confirmed | E-04 | 171 of 178 have an Effective Date or Agreement Date label. Rule: Effective Date → Agreement Date → read from text → drop (DV-8). |
| Supplier (`Parties` label) | `supplier_id`, aliases | Confirmed | E-04 | 178 of 178 labelled. |

### 5.3 SEC EDGAR EX-10

| Field | Used for | Status | Evidence | Notes |
|---|---|---|---|---|
| Exhibit file (`.htm`, `.txt`, `.pdf`) | Contract and amendment text | Confirmed | E-06, E-07, E-08 | 973 filings for `"amendment to supply agreement"`; 9 of the first 10 are EX-10 exhibits; sampled files are HTML. |
| Archive URL | `source_url` | Confirmed | E-06 to E-08 | `https://www.sec.gov/Archives/edgar/data/{CIK}/{accession}/{file}`; rows without it are rejected. |
| Amendment recitals ("amends the Supply Agreement dated …") | Linking an amendment to its original (`parent_doc_id`) | Confirmed | E-07, E-08 | Both sampled amendments name the original and its date. A pair is kept only if we find both documents. |
| Amendment chains | Term in force | Known issue (handled) | E-07, E-08 | "Fifth Amendment … as amended", "Modification of the Second Amendment". `parent_doc_id` always points to the original; a chain is used for eval only when every amendment touching that clause is indexed or the latest restates the clause in full (DV-10). |
| Effective date in the text | `effective_date` | Known issue (handled) | E-07, E-08 | One sample has a calendar date, the other only a condition ("effective upon full execution of …"). Rule: calendar date → signature date → drop; never the filing date (DV-9). |
| Redactions and party names | `has_redaction`; supplier aliases | Known issue (handled) | E-04, E-07, E-08 | Same six-form redaction rule as CUAD. Affiliates and renamed parties ("formerly known as") are added to the supplier's aliases. |

### 5.4 Vendor DPAs and SLAs

| Field | Used for | Status | Evidence | Notes |
|---|---|---|---|---|
| Document text | Compliance answers (breach notification, sub-processors, service credits) | Confirmed | E-09 to E-13 | All 5 sampled documents reachable without login, with text. These are standard terms, labelled that way in the prompt and UI. |
| "Last updated" date | `effective_date` | Known issue (handled) | E-09 to E-12 | Three wordings ("Last modified", "Last Updated", "Effective starting"); the AWS DPA PDF shows no date and is excluded (DV-11). |
| Service-credit tables | Penalty answers with exact numbers | Known issue (handled) | E-09, E-10 | Several tables per page with different scopes (region vs instance level). Each table chunk starts with its caption and heading so the scope stays with the numbers. |
| Page type | Selection | Known issue (handled) | E-13 | Some SLA URLs are index pages linking the real SLAs; only pages containing the terms are kept. |
| `retrieved_at`, `sha256`, archive URL | Knowing which version we indexed | Confirmed | Fetch design | Pages change (Atlassian's DPA is effective from August 2026). A changed hash is reported, never replaced silently. |

### 5.5 Synthetic documents

| Field | Used for | Status | Evidence | Notes |
|---|---|---|---|---|
| SKU, unit price, tier bounds, payment terms | About 20 exact-value questions, including tier boundaries | Confirmed | Generator spec | Answers written when the documents are generated |
| Certificate type, issue date, expiry date | Certificate validity questions | Confirmed | Generator spec | Validity is worked out in code against `AS_OF_DATE` (decision D2) |
| `is_synthetic = true` | UI label | Confirmed | Generator spec | Always shown |

### 5.6 Manifest (`data/manifest.csv`)

| Column | Type | Checked at ingestion |
|---|---|---|
| `doc_id` | string, primary key | Unique; `{SUPPLIER}-{TYPE}-{YEAR}`, amendments `{SUPPLIER}-AMD{n}-{YEAR}` with `n` from the amendment's title |
| `supplier` | string, refers to `suppliers.csv` | Must exist |
| `doc_type` | one of `msa`, `supply`, `service`, `sow`, `amendment`, `price_schedule`, `dpa`, `sla`, `nda`, `certificate` | Must be in the list |
| `effective_date` | ISO date | From the document text or label (DV-8, DV-9); never the filing date |
| `parent_doc_id` | string, refers to `doc_id` | Required for amendments; points to the original agreement; must exist |
| `source` | `cuad`, `edgar`, `vendor_public`, `synthetic`, `upload` | Must be in the list |
| `source_url` | URL | Required |
| `license` | string | Required |
| `format` | `pdf`, `html`, `txt`, `docx` | Must be in the list |
| `is_synthetic` | bool | `true` only for generated documents |

### 5.7 Chunk metadata

| Field | Example | Used by |
|---|---|---|
| `chunk_id` | `ACME-MSA-2021::7.2::0` | Citations |
| `supplier_id` | `acme-industrial` | Retrieval filter, dashboard breakdowns |
| `doc_type`, `clause_no`, `clause_title` | `amendment`, `4.1`, `Payment Terms` | Prompt header, keyword search, citations |
| `page_start`, `page_end` | `14`, `14` (PDF only) | Citations |
| `effective_date`, `expiry_date`, `parent_doc_id` | `2023-04-01`, empty, `ACME-MSA-2021` | Term in force; certificate validity |
| `is_table`, `has_redaction`, `is_synthetic` | `true`, `false`, `false` | Prompt formatting, UI labels (`has_redaction` covers all six marker forms) |
| `token_count` | `384` | Fitting chunks into the prompt |

Supplier and document names in examples are made up.

### 5.8 Log fields used by the dashboard

These are written by the app, not taken from a source, so their status is set by the logging requirement (FR-11, FR-12) and tested by KPI-15.

| Table | Fields the dashboard reads | Added in v1.1 |
|---|---|---|
| `query_log` | `query_id`, `created_at`, `client`, `supplier_id`, `topic`, `outcome`, `ttft_ms`, `total_ms`, `cache_hit`, warnings | `client` (`ui`, `eval`, `api`) so eval runs don't count as usage; `topic` (rule-based, section 6.4) |
| `clause_open_log` | `query_id`, `chunk_id`, `opened_at` | New table, written when "View clause" calls `GET /chunks/{id}?query_id=…` |
| `eval/results/<date>_<tag>.json` | KPI-02 to KPI-11, split, run date, `index_version` | JSON copy of the existing Markdown report |
| `documents` | `supplier_id`, `doc_type`, `source`, `effective_date`, `parent_doc_id` | No change |

### 5.9 Constraints on the data

- Nothing confidential goes into the corpus, because chunks are sent to free-tier APIs (Gemini, Groq).
- Many CUAD and EDGAR contracts are 10 to 25 years old (filed 1994–2020). "Current" means the latest amendment, not "not yet expired".
- Documents from many real companies are treated as one company's repository (A-1). In each contract, the party selling goods or services is the supplier.
- The dashboard shows question text from the public demo. Questions are never sent to an LLM by the dashboard.

---

## 6. KPIs and success metrics

Each KPI has a metric, a measurement method, a target and a date. Eval results go in `eval/results/<date>_<tag>.md` (and a `.json` copy for the dashboard) together with the index version, prompt version, threshold and parameters, so every number can be reproduced.

### 6.1 KPIs

| ID | Metric | How it's measured | Target | When |
|---|---|---|---|---|
| KPI-01 | Time to checked answer (ask, then read the cited clause) | Baseline: team members answer 20 tuning questions by hand from the raw documents, timed. Product: at least 5 testers answer the same 20 in ClauseCheck, timed from sending the question to opening the cited clause (`docs/qa.md`). Live: dashboard metric M-03. | From about 10 min (A-3) to a median of 30 s or less | Baseline W2 D5; product W5 D4 |
| KPI-02 | Recall@5 | `eval/run_eval.py`: share of answerable questions with a correct chunk in the top 5 after re-ranking (for amendment questions, the amended chunk) | 0.85 or more | Tuning split W3 D5; held-out W5 D4 |
| KPI-03 | Answer correctness | Exact-value questions: normalised value matches and no outdated value is given as current. Prose questions: graded by an LLM judge from a different model family (partly correct counts as 0.5). | 85% or more | Tuning W4 D5; held-out W5 D4 |
| KPI-04 | Citation accuracy | Answered questions where at least one cited chunk is correct and no cited chunk belongs to another supplier | 90% or more | Tuning W4 D5; held-out W5 D4 |
| KPI-05 | Correct refusals | Share of the ~15 unanswerable questions that get a refusal or clarification | 90% or more | Tuning W4 D4; held-out W5 D4 |
| KPI-06 | Wrong refusals | Share of answerable questions that get refused | 10% or less | Tuning W4 D4; held-out W5 D4 |
| KPI-07 | Time to first token | `query_log.ttft_ms` on the deployed app across the full eval run (p50 and p95) | p50 under 3 s | Estimate W4 D5; deployed W5 D4 |
| KPI-08 | Outdated-term answers | Amendment questions (at least 10) where the answer gives only the replaced value | 0 | Tuning W4 D5; held-out W5 D4 |
| KPI-09 | Task success | At least 5 testers do 11 set tasks (lookup, follow-up, recognising a refusal, upload, opening a clause, reading the dashboard). A task succeeds if they find the right term and clause, or the right dashboard figure. | 80% or more | W5 D4 |
| KPI-10 | Unsupported-number warnings (proposed by us as a guardrail) | Share of answers flagged with `unsupported_number` in the eval run | 5% or less | Tuning W4 D5; held-out W5 D4 |
| KPI-11 | Judge agreement | Hand-check 10% of the LLM judge's grades | 85% agreement or more; otherwise we fix the judge prompt before reporting | W4 D5 and W5 D4 |
| KPI-12 | Rebuild from scratch | CI runs `python -m clausecheck.ingest --manifest data/manifest.csv --rebuild` on a clean clone | Passes on every run on `main` | W3 D5 to submission |
| KPI-13 | Cache | Same question asked twice returns `cache_hit: true` with no LLM call | Passes the API test | W5 D2 |
| KPI-14 | Delivery | Public frontend and backend URLs answer a question; `/health` returns `ok` | Live by W5 D3 (M6); submitted W5 D5 (M7) | W5 |
| KPI-15 | Dashboard accuracy | `tests/api/test_metrics.py` loads a fixture log of 200 queries with known outcomes and timings; every card and chart value from the metrics API is compared with an independent SQL recomputation | 100% of values match (rounded to the displayed precision); dashboard loads in under 2 s with 10,000 log rows | W5 D2 |

### 6.2 Acceptance gates

The product is done when all six pass on the held-out split.

| Gate | KPI | Target |
|---|---|---|
| Finds the right clause | KPI-02 | Recall@5 ≥ 0.85 |
| Answers correctly | KPI-03 | ≥ 85% |
| Citations are right | KPI-04 | ≥ 90% |
| Doesn't make things up | KPI-05 | ≥ 90% |
| Doesn't refuse things it knows | KPI-06 | ≤ 10% |
| Fast enough | KPI-07 | p50 < 3 s on the deployed app |

KPI-05 and KPI-06 are tuned together, since refusing everything would pass one and answering everything would pass the other. KPI-15 is a delivery requirement for the dashboard, not an acceptance gate on answer quality.

### 6.3 Evaluation set

| Group | Count | Where the answers come from |
|---|---|---|
| Real-contract questions | ~30 | CUAD labels from `CUAD_v1.json` mapped to our chunk IDs |
| Exact-value questions | ~20 | Synthetic generator, including tier boundaries |
| Amendment questions (within the groups above) | 10 or more | Hand-labelled EDGAR pairs, with the outdated clause recorded |
| Redacted-value questions | 2–3 | Correct answer: "redacted in the filed copy", with the clause cited |
| Follow-up pairs | 5 or more | Written by hand |
| Unanswerable | ~15 | Unknown suppliers and hand-checked missing clauses |

About 60% of the questions are for tuning (choosing thresholds and settings). The other 40% are held out and run once, on W5 D4, for the reported numbers.

### 6.4 Live metrics on the KPI cards and dashboard

The KPI cards (F-16) and the Insights dashboard (F-17) show these metrics. All are computed in SQL from the logs in section 5.8 by the metrics API (FR-12); none needs an LLM call. Live metrics count only questions with `client = ui`, so eval runs don't inflate usage. The default window is the last 7 days; the dashboard also offers 30 days and "all", and a supplier filter.

| ID | Metric | Formula | Shown as | Target or threshold | Linked KPI |
|---|---|---|---|---|---|
| M-01 | Questions asked | Count of `query_log` rows in the window | **KPI card K1** with change vs the previous window, and a 7-day sparkline | No target (adoption trend) | n/a |
| M-02 | Answer rate | (`answered` + answered with warning) ÷ (all questions − errors) | **KPI card K2**, with the "not found" share as a sub-line | Amber below 80% (monitoring threshold, not a gate) | KPI-05, KPI-06 |
| M-03 | Median time to checked answer | Median of (first `clause_open_log.opened_at` − `query_log.created_at`) over answered questions where a clause was opened | **KPI card K3** | ≤ 30 s | KPI-01 |
| M-04 | Time to first token | p50 of `ttft_ms` (p95 as sub-line) | **KPI card K4** | p50 < 3 s | KPI-07 |
| M-05 | Citation accuracy (latest eval) | KPI-04 from the newest `eval/results/*.json`, with split and run date | **KPI card K5** | ≥ 90% | KPI-04 |
| M-06 | Questions per day by outcome | Daily count, stacked by answered / answered with warning / not found / clarify or out of scope / error | Stacked bar chart | n/a | KPI-05, KPI-06 |
| M-07 | Response time per day | Daily p50 and p95 of `ttft_ms` | Line chart with a 3 s target line | p50 < 3 s | KPI-07 |
| M-08 | Questions by topic | Count per `topic` | Horizontal bar chart | n/a | n/a |
| M-09 | Supplier activity | Per supplier: questions, answer rate, median time to first token, last asked | Data table, top 10 by questions, sortable | Answer rate below 80% highlighted | KPI-04 |
| M-10 | Unanswered questions | Latest 20 questions with a refusal outcome: time, supplier, question, outcome, top score | Data table with "Upload a document for this supplier" action | n/a | US-20 |
| M-11 | Eval results vs targets | KPI-02 to KPI-10 from the latest tuning and held-out runs | Data table with target and pass/fail per row | Section 6.1 targets | KPI-02 to KPI-10 |
| M-12 | Corpus coverage | Documents by source and `doc_type`; per supplier: documents, amendments, price schedule on file, latest effective date | Stacked bar chart + data table | n/a | n/a |

**Topic rules (M-08).** `topic` is set in code by keyword match on the rewritten question, first match wins: payment (payment, invoice, net, discount), price (price, SKU, tier, unit), renewal (renew, notice, expire, term), liability (liability, cap, indemn), termination (terminat, convenience), penalty (penalty, liquidated, credit, late), compliance (DPA, SLA, certificate, ISO, insurance, breach, audit), other. The rule list is a constant in `rag/topics.py`.

**Small samples.** When a window has fewer than 20 questions, cards K1–K4 show the value with "low sample (n = …)" so a single slow answer isn't read as a trend.

---

## 7. Users, user stories and workflow

### 7.1 Personas

| ID | Persona | Situation | Problem today | A good answer |
|---|---|---|---|---|
| P1 | Procurement buyer (primary) | Raises POs and approves invoices, deals with many suppliers a day | Lookups take minutes so they get skipped; can't tell if an amendment changed a term | The exact value and the clause, in seconds |
| P2 | Category manager | Owns supplier relationships, handles renewals and negotiations | Not sure the terms discussed match what was signed | The current term and what it replaced |
| P3 | Compliance / vendor-risk analyst | Checks DPAs, SLAs and certificates for onboarding and audits | Documents are scattered and validity needs date maths | Valid or not as of today, with the document cited |
| P4 | Document maintainer | Team member who adds documents | New documents need a full rebuild to become searchable; no list of what's missing | Upload, and it's answerable after one job; a list of unanswered questions by supplier |
| P5 | Sprint reviewer | Mentor and team judging quality | Quality judged by gut feel | One command that produces comparable numbers, and the latest results on screen |
| P6 | Procurement team lead | Sponsors ClauseCheck and reports on it to management | Can't see whether buyers use the tool or whether it answers well | Five numbers on the main screen and a dashboard behind them |

### 7.2 User stories

P0 stories are needed for acceptance. P1 stories are in v1 but are on the cut list (section 8.4).

| ID | Story | Acceptance criteria | Priority | Requirements |
|---|---|---|---|---|
| US-01 | As a procurement buyer, I want to ask "What are the payment terms with Supplier X, and is there an early-payment discount?" so that I approve the invoice for the right due date and take the discount before it expires. | Payment period and discount are given exactly as written; each sentence has a `[C#]` citation pointing to supplier, document, clause and page (for PDFs); median time to first token under 3 s | P0 | FR-5, FR-6, FR-10 |
| US-02 | As a procurement buyer, I want to ask the unit price for a SKU at a given quantity so that I raise the PO at the agreed price and reject invoices above it. | Price copied exactly from the right tier, including boundaries (e.g. exactly 500 when a tier is 500–999); the table is cited | P0 | FR-2, FR-5, FR-6 |
| US-03 | As a procurement buyer, I want to be given the amended term and told which original it replaced, so that I don't act on an outdated term. | Amended value given as current; the original is mentioned only as replaced; no outdated-term answers (KPI-08) | P0 | FR-4, FR-5, FR-6 |
| US-04 | As a procurement buyer, I want a clear "not found" message when the contracts don't contain the answer, so that I don't make a payment decision on a made-up term. | Grey box with fixed text, no generated term; refusal KPIs met | P0 | FR-7 |
| US-05 | As a procurement buyer, I want to ask "And what about their notice period?" without naming the supplier again, so that I can check several terms in one conversation. | Follow-up is rewritten to name the same supplier; all follow-up pairs resolve correctly | P0 | FR-8 |
| US-06 | As a procurement buyer, I want to open the full text of a cited clause, so that I can check it myself before acting. | Each citation expands to the full clause on the same screen | P0 | FR-6, FR-10 |
| US-07 | As a procurement buyer, I want to be told when a value is redacted in the filed contract, so that I ask for the full copy instead of trusting a guess. | Answer says "redacted in the filed copy" and cites the clause; no estimate | P0 | FR-6, FR-7 |
| US-08 | As a category manager, I want to ask whether a contract auto-renews and how much notice is needed to end it, so that I send notice before the deadline. | Two facts, two citations; amended terms take priority | P0 | FR-5, FR-6 |
| US-09 | As a category manager, I want to ask a supplier's liability cap and whether we can terminate for convenience, so that I know what's signed before negotiating. | Cap and conditions given exactly; if there's no such clause, a refusal | P0 | FR-5, FR-6, FR-7 |
| US-10 | As a compliance analyst, I want to ask whether a supplier's ISO 27001 or insurance certificate is valid today, so that I catch lapsed certificates before an audit does. | Valid / not valid worked out in code from `expiry_date` and `AS_OF_DATE`, with the expiry date and certificate cited | P0 | FR-4, FR-6 |
| US-11 | As a compliance analyst, I want to ask about a supplier's DPA or SLA (breach notification time, service credits), so that I can assess vendor risk without reading the whole document. | DPA or SLA clause cited and labelled "standard terms (not negotiated)" | P0 | FR-1, FR-2, FR-6 |
| US-12 | As a procurement buyer, I want to pick a supplier in the sidebar, so that every answer comes from that supplier's documents. | Sidebar choice overrides detection; no citations from other suppliers (KPI-04) | P0 | FR-5 |
| US-13 | As a procurement buyer, I want to be asked which supplier I mean when I name two, so that I don't get an answer that mixes them up. | `clarify_multiple_suppliers` with fixed text; no answer generated | P0 | FR-7 |
| US-14 | As a document maintainer, I want to upload a contract or amendment with its supplier, type and date, so that it becomes answerable without rebuilding the whole index. | `POST /documents` returns 202 and a job ID; job completes; the new document can be cited; a failed file leaves nothing half-indexed | P0 | FR-9 |
| US-15 | As a sprint reviewer, I want one command that runs the eval set and writes a versioned report, so that quality is judged on numbers. | `eval/run_eval.py` writes KPI-02 to KPI-11 with index and prompt versions and parameters | P0 | FR-11, NFR-3 |
| US-16 | As a team member fixing a wrong answer, I want each query's retrieved chunks, scores, outcome and timings logged, so that I can see which step failed. | One `query_log` row per question, one `retrieval_log` row per candidate | P0 | FR-11 |
| US-17 | As a procurement buyer, I want a warning when a number in the answer isn't in the cited clause, so that I double-check before acting. | `unsupported_number` warning shown with the answer; KPI-10 met | P0 | FR-6 |
| US-18 | As a procurement buyer, I want to give an answer a thumbs up or down, so that the team can see which answers people don't trust. | Rating saved against the `query_id` | P1 (cut item 1) | FR-11 |
| US-19 | As a procurement team lead, I want to see questions asked, answer rate, time to checked answer, time to first token and citation accuracy as cards at the top of the main screen, so that I know at a glance whether ClauseCheck is used and meeting its targets without running a script. | Five KPI cards visible without scrolling at 1366 × 768; each shows value, target or threshold, status and change vs the previous window; values match KPI-15 | P0 | FR-12 |
| US-20 | As a document maintainer, I want a table of recent unanswered questions by supplier, so that I know which contracts to upload next. | Insights dashboard table M-10 with the 20 latest refusals; "Upload a document for this supplier" opens the upload panel pre-filled | P0 | FR-12, FR-9 |
| US-21 | As a sprint reviewer, I want charts of questions by outcome and response time per day, and a table of the latest eval results against targets, so that I spot a regression the day it happens. | Charts M-06 and M-07 and table M-11 on the Insights dashboard; 3 s target line drawn; failing eval rows marked | P0 | FR-12, FR-11 |

Features with no story behind them (for example, dark mode or exporting chat history) are not in v1.

### 7.3 Workflow before and after

```mermaid
%%{init: {"theme": "base", "themeVariables": {"background": "transparent", "primaryColor": "transparent", "clusterBkg": "transparent", "clusterBorder": "#999", "lineColor": "#666", "primaryBorderColor": "#666"}}}%%
flowchart LR
    classDef default fill:none,stroke:#666

    subgraph BEFORE["Today"]
        direction TB
        B1["Invoice or PO arrives"] --> B2["Search shared folders"]
        B2 --> B3["Open MSA, SOWs, schedules"]
        B3 --> B4["Check for amendments<br/>(often skipped)"]
        B4 --> B5["Find the clause"]
        B5 --> B6["Act on the term<br/>(~10 min, or skipped)"]
    end

    subgraph AFTER["With ClauseCheck"]
        direction TB
        A1["Invoice or PO arrives"] --> A2["Ask one question"]
        A2 --> A3["Answer with citations"]
        A3 --> A4["Open the cited clause"]
        A4 --> A5["Act on the term<br/>(30 s or less)"]
        A2 -.-> A6["Not found: escalate<br/>or upload the document"]
        A3 -.-> A7["Logged: KPI cards and<br/>dashboard update"]
    end

    style BEFORE fill:none,stroke:#999,stroke-dasharray:4 3
    style AFTER fill:none,stroke:#999,stroke-dasharray:4 3
```

---

## 8. Scope

### 8.1 In scope for v1

| ID | Feature | Stories | Week |
|---|---|---|---|
| F-01 | Loading PDF, HTML, TXT and DOCX, with table extraction and redaction flags | US-02, US-07, US-11 | W2 |
| F-02 | Splitting documents by clause, with metadata (supplier, type, clause, page, dates, parent document) | US-03, US-06, US-10 | W2 |
| F-03 | Working out the supplier (sidebar, name, fuzzy match, previous turn), including unknown and multiple suppliers | US-04, US-12, US-13 | W3 |
| F-04 | Hybrid search (vector + BM25, merged with RRF), pulling in amendments, and re-ranking | US-01, US-02, US-03, US-08, US-09 | W3 |
| F-05 | Relevance check and fixed refusal messages | US-04, US-07, US-13 | W4 |
| F-06 | Answers built only from retrieved clauses, with `[C#]` citations checked in code and numbers checked against the clause | US-01 to US-11, US-17 | W4 |
| F-07 | Follow-up questions (rewriting, keeping the supplier, sessions) | US-05 | W4 |
| F-08 | Certificate validity worked out in code against `AS_OF_DATE` | US-10 | W4 |
| F-09 | FastAPI backend with streaming answers (`/chat/stream`), `/chunks/{id}`, `/suppliers`, `/health` | US-01, US-06, US-12 | W5 |
| F-10 | Document upload with background indexing and job status | US-14 | W5 |
| F-11 | Streamlit chat UI with streamed answers, sources, refusal box, warnings and labels | US-01, US-04, US-06, US-17 | W5 |
| F-12 | Answer cache, query, retrieval and clause-open logs, rate limiting | US-16 | W4–W5 |
| F-13 | Evaluation suite (question set, tuning and held-out split, comparisons, LLM judge), with a JSON copy of each result | US-15 | W2–W5 |
| F-14 | Public deployment (backend on Hugging Face Spaces, frontend on Streamlit Community Cloud), with the index restored after a restart | All | W5 |
| F-15 | Thumbs up / down feedback | US-18 | W5 (cut item 1) |
| F-16 | KPI cards: five cards (K1–K5) above the fold on the main "Ask" screen, from `GET /metrics/summary` | US-19 | W5 D1–D2 |
| F-17 | Insights dashboard: a second tab with filters, three charts (M-06, M-07, M-08), a corpus chart (M-12) and four data tables (M-09, M-10, M-11, M-12) | US-20, US-21 | W5 D1–D2 |

### 8.2 Out of scope for v1

Each item has a set behaviour in v1, so nobody has to guess what happens if a user asks for it.

| Not in v1 | Why | What v1 does instead | Later |
|---|---|---|---|
| Portfolio questions ("which suppliers auto-renew next quarter?") | Search only sees 5 chunks, so the list would be incomplete and nobody could tell | Fixed message `out_of_scope_aggregation`, no LLM call | Roadmap H1–H2 |
| Comparing suppliers ("compare Acme and Brightline payment terms") | Doubles the cost and isn't in the eval set | Asks the user to pick one supplier (`clarify_multiple_suppliers`) | Roadmap H4 |
| Contract-term portfolio dashboard (renewal timeline, liability-cap mix, payment-term mix) | Needs every term extracted and normalised for every supplier (roadmap H1), which v1 doesn't do | The v1 dashboard shows usage, answer quality and corpus coverage only, all computed from logs and the manifest | Roadmap H3 |
| Legal advice, drafting, redlining | Not what the product is for | Prompt rules out recommendations; UI says "Not legal advice" | Not planned |
| OCR for scanned documents | Our corpus has text layers; CUAD PDFs without one fall back to the CUAD text | Scanned uploads are listed in the ingestion report and skipped | Roadmap H4 |
| ERP / invoice system integration | Needs systems we don't have | Not available | Roadmap H4 |
| Login, roles, audit trail | Only public and synthetic data | Open demo with a per-IP rate limit; dashboard is visible to everyone using the demo | Roadmap H4, needed before any real contracts |
| Confidential contracts, private model | We use free-tier external APIs | Only public and synthetic documents are indexed | Roadmap H4 |
| Renewal and expiry alerts | Depends on portfolio queries | Not available | Roadmap H3 |
| Dashboard export (CSV, PDF), scheduled reports | No user story in v1 | Tables can be copied from the screen | After the sprint |
| Mobile app, other languages | Not needed for our users in the sprint | English web UI only | Not planned |
| LLM re-ranking, live vendor-page sync | Cost and latency on the free tier | Small cross-encoder; vendor pages re-checked weekly by hash | After the sprint |

### 8.3 Technical constraints

| Area | v1 rule |
|---|---|
| Data refresh | The corpus is a fixed snapshot rebuilt from `manifest.csv`. Uploads are indexed when they arrive. Nothing syncs live. |
| Uploads on free hosting | Uploaded files can be lost when the host restarts, and the UI says so (R-08). |
| Logs on free hosting | Logs live in SQLite on the same disk and can also be lost on restart. The dashboard shows "since {first log date}" so a reset window is visible (R-16). |
| Models | Gemini free tier for answers and embeddings, Groq as backup for answers, local MiniLM as backup for embeddings. Model names are set in `.env`. |
| Compute | CPU only. Re-ranker: `cross-encoder/ms-marco-MiniLM-L-6-v2`. |
| Size | Up to about 20k chunks and 150 suppliers on one container. |
| Uploads | `.pdf`, `.html`/`.htm`, `.txt`, `.docx`; 20 MB max; file type checked. |
| Rate limit | 30 requests a minute per IP. Metrics endpoints are cached for 60 s and don't count towards the limit. |
| Charts | Streamlit built-ins and Altair (bundled with Streamlit); no extra charting service. |
| Language | English only. |

### 8.4 Cut list

If we fall behind, we drop these in order:

1. Feedback buttons and endpoint (F-15). Logging still works.
2. Pulling in the parent clause from an amendment. Pulling in amendments from the original stays.
3. DOCX upload through the app. Batch ingestion still handles DOCX.
4. The Render backup deployment.
5. The fixed-size vs clause-based chunking comparison.

We don't cut hybrid search, the supplier filter, the relevance check, citations and their validation, the held-out eval, streaming, deployment, the KPI cards or the Insights dashboard, because the acceptance gates and the M1 approval conditions depend on them.

### 8.5 Handling new requests

- A "can we also add…" request mid-sprint becomes a GitHub issue labelled `v2-backlog` and is checked against section 8.2. It only enters v1 through a new version of this PRD approved by the mentor, and something else has to come out or the timeline has to move. Version 1.1 is an example: F-16 and F-17 entered through the M1 review.
- Anything not listed in 8.1 or 8.3 is out of scope. If someone finds a case this PRD doesn't cover, they add it to section 17.2 instead of deciding on their own.

---

## 9. Requirements

### 9.1 Functional

| ID | Requirement | Stories | Checked by |
|---|---|---|---|
| FR-1 | Load PDF, HTML, TXT and DOCX into text, keeping track of where each came from | US-11, US-14 | Unit test per format; ingestion report |
| FR-2 | Extract tables from price schedules and SLAs without losing rows or columns | US-02, US-11 | Exact-value eval questions |
| FR-3 | Split documents by clause, with size limits and overlap; split by page when fewer than 3 headings are found | US-06 | Heading tests on 30 real headings; chunk-size histogram |
| FR-4 | Store each chunk with supplier, type, clause number, page, effective and expiry dates, parent document, and table/redaction/synthetic flags | US-03, US-10 | Integration test on every field |
| FR-5 | Answer questions using supplier-filtered hybrid search and re-ranking | US-01, US-02, US-08, US-09, US-12 | KPI-02 and comparisons |
| FR-6 | Give every answer at least one citation to a real document and clause; check markers and numbers | US-01 to US-11, US-17 | KPI-04, KPI-10 |
| FR-7 | Refuse with fixed text when the evidence is weak, the supplier is unknown, no valid citation is left, or the question is out of scope | US-04, US-07, US-13 | KPI-05, KPI-06 |
| FR-8 | Handle follow-up questions in a conversation | US-05 | Follow-up pairs; manual QA |
| FR-9 | Upload and index new documents as background jobs | US-14 | API test; job states |
| FR-10 | Stream answers to a chat UI that shows sources | US-01, US-06 | KPI-07; manual QA |
| FR-11 | Log queries, retrieved chunks, scores, outcomes, timings, token use, clause opens and feedback | US-15, US-16, US-18 | Log-row test |
| FR-12 | Show five KPI cards above the fold on the main screen and an Insights dashboard with charts and data tables, all computed from the logs, the manifest and eval results without LLM calls | US-19, US-20, US-21 | KPI-15; QA at 1366 × 768 |

### 9.2 Non-functional

| ID | Requirement | How we check it |
|---|---|---|
| NFR-1 | Speed | Time to first token p50 under 3 s on the deployed app (KPI-07); KPI cards and dashboard load in under 2 s with 10,000 log rows (KPI-15) |
| NFR-2 | Secrets | API keys only in `.env` and host secrets; `.env.example` committed; `detect-secrets` passes in CI |
| NFR-3 | Rebuild | Whole index rebuilt from a clean clone with one command (KPI-12); seeds in the README |
| NFR-4 | Rate limits | Retries with backoff; Groq and local fallbacks; unit test with a mocked 429 passes |
| NFR-5 | Caching | A repeated question comes from the cache (KPI-13); metrics responses cached 60 s |
| NFR-6 | Failing safely | Embedding API down: keyword search only, with a notice. Both LLMs down: error and retry button. Metrics API down: cards show "—" with "Metrics unavailable" and the chat still works. Never a silent wrong answer. |
| NFR-7 | Upload safety | Extension and file-type checks, 20 MB limit, generated file names; HTML is parsed, never run |
| NFR-8 | Clear labelling | UI marks synthetic documents, standard terms and redactions; "Not legal advice" always visible; every KPI card names its window and source |
| NFR-9 | Readable charts | Every chart has a title, labelled axes and units; colour is never the only signal (status also shown as text); charts readable down to 1024 px wide |

---

## 10. Data workflow

### 10.1 From documents to answers to metrics

```mermaid
%%{init: {"theme": "base", "themeVariables": {"background": "transparent", "primaryColor": "transparent", "clusterBkg": "transparent", "clusterBorder": "#999", "lineColor": "#666", "primaryBorderColor": "#666"}}}%%
flowchart TB
    classDef default fill:none,stroke:#666
    classDef gate fill:none,stroke:#b33,stroke-width:2px

    subgraph S1["1. Ingestion (offline and on upload)"]
        M["manifest.csv + uploads"] --> V{"Row valid?<br/>licence, URL, supplier, parent"}
        V -- no --> ERR["ingestion_errors"]
        V -- yes --> P["Parse by format<br/>PyMuPDF, pdfplumber, BeautifulSoup, python-docx"]
    end

    subgraph S2["2. Cleaning and chunking"]
        P --> CL["Clean headers, footers, page numbers,<br/>hyphenation (numbers untouched)"]
        CL --> CH["Clause chunks and table chunks<br/>with metadata and redaction flags"]
    end

    subgraph S3["3. Indexing"]
        CH --> EM["Embed in batches of 50<br/>(cached by hash)"]
        EM --> IX[("ChromaDB, BM25 per supplier + global, SQLite")]
    end

    subgraph S4["4. Answering a question"]
        Q["Question + history"] --> RW["Rewrite follow-up"]
        RW --> SR["Work out supplier"]
        SR --> HY["Hybrid search, RRF,<br/>add amendments, re-rank"]
        HY --> G{"Relevance check"}
        G -- fail --> RF["Fixed refusal"]
        G -- pass --> GEN["Generate answer<br/>with [C1]..[Cn]"]
        GEN --> VF["Check citations and numbers"]
    end

    subgraph S5["5. Delivery"]
        VF --> API["FastAPI, streamed"]
        RF --> API
        API --> UI["Streamlit Ask tab: answer, sources,<br/>refusal box, warnings"]
        API --> LOG[("query_log, retrieval_log,<br/>clause_open_log, cache")]
    end

    subgraph S6["6. Metrics"]
        LOG --> MET["Metrics API<br/>(SQL only, cached 60 s)"]
        EV[("eval/results/*.json")] --> MET
        IX --> MET
        MET --> CARDS["KPI cards K1–K5<br/>(Ask tab, above the fold)"]
        MET --> DASH["Insights tab:<br/>charts and tables"]
    end

    IX --> HY
    class G gate

    style S1 fill:none,stroke:#999,stroke-dasharray:4 3
    style S2 fill:none,stroke:#999,stroke-dasharray:4 3
    style S3 fill:none,stroke:#999,stroke-dasharray:4 3
    style S4 fill:none,stroke:#999,stroke-dasharray:4 3
    style S5 fill:none,stroke:#999,stroke-dasharray:4 3
    style S6 fill:none,stroke:#999,stroke-dasharray:4 3
```

### 10.2 What each stage does

| Stage | In and out | Rules | Owner |
|---|---|---|---|
| 1. Ingestion | Manifest row to text and tables | Reject rows with no licence or URL, an unknown supplier or a missing parent; skip files that haven't changed; CUAD PDFs without a text layer load from the CUAD JSON text | A |
| 2. Cleaning and chunking | Pages to chunks with metadata | Remove `Source:` footers and stand-alone page-number lines; split on clause headings; 512 tokens max per chunk, long clauses in 400-token windows with 60 overlap and the heading repeated; tables kept whole with header rows and caption; flag all six redaction marker forms | A |
| 3. Indexing | Chunks to vector, keyword and SQL indexes | One Chroma collection per embedding model; SQLite holds the master copy; one transaction, undone on failure; index version updated | A, B |
| 4. Answering | Question to checked answer or refusal | Filter by supplier first; relevance check before any answer is generated; citation markers mapped in code; numbers checked against the cited chunks | B, C |
| 5. Delivery | Answer to the UI; one log row per question | Streamed events `meta`, `token`, `citations`, `done` (or `refusal`, `error`); API keys stay on the backend; `client` and `topic` logged; clause opens logged | D |
| 6. Metrics | Logs, eval results and index to cards and dashboard | SQL aggregations only; `client = ui` rows only for live metrics; cached 60 s; no LLM calls | D |

### 10.3 How we stop made-up answers

| Check | What it catches |
|---|---|
| Unknown supplier | Questions about suppliers we don't have |
| Supplier filter | Answers taken from another supplier's contract |
| Relevance check | Answering when nothing relevant was found (no LLM call is made) |
| Prompt rules and `NOT_FOUND` | The model adding outside knowledge |
| Citation check | Invented `[C#]` markers; answers with no valid citation become refusals |
| Number check | Numbers that aren't in the cited clause (shown as a warning) |
| Visible sources | Anything else: the user can open the clause |

The full design is in [rag-architecture-design.md](../architecture/rag-architecture-design.md), sections 6 to 8 and 11.

---

## 11. UI layout and states

The full mock, with every screen, state, flow and string, is in [mock-ux.md](../ux/mock-ux.md) (v1.1). This section is the summary.

### 11.1 Main screen ("Ask" tab) with KPI cards above the fold

Layout target: 1366 × 768 browser window. The header (56 px), the tab bar (40 px) and the KPI card row (104 px) take the top 200 px, so all five cards and the start of the conversation are visible without scrolling.

```text
+-----------------------------------------------------------------------------------------------+
|  ClauseCheck                                             Index: 248 docs · 121 suppliers · OK  |
+------------------------+----------------------------------------------------------------------+
| Supplier               |  [ Ask ]  [ Insights ]                         Last 7 days · all sup. |
| [ All suppliers    v ] | +-------------+-------------+-------------+-------------+-----------+ |
|                        | |K1 QUESTIONS |K2 ANSWERED  |K3 CHECKED   |K4 FIRST     |K5 CITATION| |
| [ New conversation ]   | |   ASKED     |  WITH SOURCE|   ANSWER    |   TOKEN p50 |  ACCURACY | |
|                        | |    342      |    86%      |    24 s     |    1.6 s    |    92%    | |
| > Upload a document    | | ▲ 18% vs    | 11% not     | target ≤30 s| target <3 s | target≥90%| |
|                        | |  prev 7 d   |  found      | ✔ on target | ✔ on target | eval 10-04| |
|                        | +-------------+-------------+-------------+-------------+-----------+ |
|                        |                                                                      |
|                        |   You: What are the payment terms with Acme?                         |
| Not legal advice.      |   ClauseCheck: Invoices are payable within 45 days of receipt [C1].  |
| Synthetic documents    |   ...                                                                |
| are labelled.          +----------------------------------------------------------------------+
| Uploads may reset on   |  [ Ask about a supplier's terms…                          ] [Send]   |
| restart (free tier).   |                                                                      |
+------------------------+----------------------------------------------------------------------+
```

Values are made up. Clicking a card opens the Insights tab scrolled to the chart or table behind it.

| Card | Metric | Value format | Sub-line | Status rule |
|---|---|---|---|---|
| K1 Questions asked | M-01 | Integer | Change vs previous window (▲/▼ %) | No status (trend) |
| K2 Answered with sources | M-02 | Percent, no decimals | "{n}% not found" | ✔ at or above 80%; ⚠ below 80% |
| K3 Time to checked answer | M-03 | Seconds, no decimals | "target ≤ 30 s" | ✔ ≤ 30 s; ⚠ above |
| K4 Time to first token (p50) | M-04 | Seconds, 1 decimal | "p95 {x} s · target < 3 s" | ✔ < 3 s; ⚠ otherwise |
| K5 Citation accuracy | M-05 | Percent, no decimals | "{split} eval, {date}" | ✔ ≥ 90%; ⚠ below; "No eval yet" before the first run |

### 11.2 Insights dashboard ("Insights" tab)

```text
+------------------------+----------------------------------------------------------------------+
| (sidebar unchanged)    |  [ Ask ]  [ Insights ]                                               |
|                        |  Period [ Last 7 days v ]  Supplier [ All v ]   Data since 2026-11-02 |
|                        |  [ K1 ][ K2 ][ K3 ][ K4 ][ K5 ]   (same five cards)                  |
|                        |  +--------------------------------+  +-----------------------------+  |
|                        |  | Questions per day by outcome   |  | Time to first token per day |  |
|                        |  | (stacked bars)        M-06     |  | p50, p95, 3 s line   M-07   |  |
|                        |  +--------------------------------+  +-----------------------------+  |
|                        |  +--------------------------------+  +-----------------------------+  |
|                        |  | Questions by topic   M-08      |  | Supplier activity    M-09   |  |
|                        |  | (horizontal bars)              |  | (table, top 10)             |  |
|                        |  +--------------------------------+  +-----------------------------+  |
|                        |  Unanswered questions (latest 20)                         M-10       |
|                        |  Latest evaluation vs targets                             M-11       |
|                        |  Corpus coverage (chart + table)                          M-12       |
+------------------------+----------------------------------------------------------------------+
```

### 11.3 States

| State | When | What the user sees |
|---|---|---|
| Answered | Relevance check passes and at least one citation is valid | Streamed answer with `[C#]` markers and a sources list |
| Answered with a warning | `unsupported_number` | Answer plus a note: "A number in this answer wasn't found in the cited clause. Check it before acting." |
| Amendment | A cited chunk comes from an amendment | Source line shows "Amendment · effective … · Amends …" |
| Labels | Chunk flags | "standard terms (not negotiated)", "synthetic document", "contains redacted values" |
| Not found | `refused_low_score`, `refused_model_not_found`, `refused_no_citation` | Grey box: "I couldn't find this in the contracts for {supplier}. Try rephrasing, or check that the document has been uploaded." |
| Unknown supplier | `refused_unknown_supplier` | Grey box: "{Name} is not in the contract repository." |
| Two suppliers named | `clarify_multiple_suppliers` | "ClauseCheck answers one supplier at a time. Which supplier do you want me to check?" |
| Portfolio question | `out_of_scope_aggregation` | Says that questions across all suppliers aren't supported yet |
| Reduced mode | Embedding API down | "Semantic search unavailable, using keyword search only." |
| Error | Both LLMs down (503) | Error message and a Retry button |
| Upload | Job states | queued, parsing, chunking, embedding, indexing, then completed or failed with the reason |
| KPI cards: no data | No `ui` questions in the window | Cards K1–K4 show "—" and "No questions yet in this period"; K5 shows "No eval yet" until the first run |
| KPI cards: low sample | Fewer than 20 questions in the window | Values shown with "low sample (n = …)" |
| Metrics unavailable | Metrics API error or timeout | Cards show "—" and "Metrics unavailable"; chat unaffected |
| Dashboard: empty chart | No rows for the filter | Chart area shows "No questions match these filters" instead of empty axes |

### 11.4 Streamlit components

| Area | Component | Backend call |
|---|---|---|
| Tabs | `st.tabs(["Ask", "Insights"])` | none |
| KPI cards (both tabs) | `st.columns(5)` with `st.metric` (value, delta) and `st.caption` for target and status | `GET /metrics/summary?days=7&supplier_id=` (cached 60 s) |
| Sidebar: supplier filter | `st.selectbox` | `GET /suppliers` (cached 5 min) |
| Sidebar: new conversation | `st.button` | `POST /sessions` |
| Sidebar: upload | `st.file_uploader` and fields | `POST /documents`, then `GET /documents/jobs/{id}` every 2 s |
| Header: index status | text | `GET /health` |
| Chat: answer | `st.write_stream` | `POST /chat/stream` |
| Chat: sources | one `st.expander` per citation | `GET /chunks/{id}?query_id=…` (logs the clause open) |
| Chat: refusal | `st.info` | |
| Chat: feedback | buttons | `POST /feedback` (P1) |
| Insights: filters | `st.selectbox` (period), `st.selectbox` (supplier) | passed to every metrics call |
| Insights: M-06, M-07, M-08, M-12 charts | `st.altair_chart` (stacked bar, line with target rule, horizontal bar) | `GET /metrics/daily`, `GET /metrics/breakdown?by=topic`, `GET /metrics/corpus` |
| Insights: M-09, M-10, M-11, M-12 tables | `st.dataframe` with column formatting | `GET /metrics/breakdown?by=supplier`, `GET /metrics/unanswered`, `GET /metrics/eval`, `GET /metrics/corpus` |

---

## 12. Risks

| ID | Risk | Likelihood | Impact | Mitigation | Owner | How we'd notice |
|---|---|---|---|---|---|---|
| R-01 | Free-tier rate limits while embedding the corpus | High | Medium: ingestion slows and W3 slips | Batches of 50, backoff, embedding cache, local MiniLM backup, overnight runs | B | Usage report, 429 counts |
| R-02 | An amendment isn't retrieved, so an old term is returned | Medium | High: buyer acts on an outdated term | Pull in amendments via `parent_doc_id`; prompt rule to give the amended term; outdated-term eval (KPI-08); chains used only when complete (DV-10) | B, C | Amendment question results |
| R-03 | The relevance threshold fits our eval set too closely | Medium | Medium: too many or too few refusals in real use | Tuning and held-out split; held-out run only once | C | Gap between tuning and held-out; live answer rate (K2) |
| R-04 | The model ignores the rules and makes up a term | Low | High | Relevance check first, `NOT_FOUND` rule, citation and number checks | C | Refusal and warning rates |
| R-05 | Heading pattern misses unusual numbering | Medium | Medium: chunks span clauses and citations are wrong | Page-based fallback; tests on 30 real headings; add patterns from the ingestion report. Validation found 3+ headings in 79% of procurement contracts (E-04) | A | Chunk histogram, flagged documents |
| R-06 | Wrong supplier picked | Low | High: confident answer from the wrong contract | Supplier IDs with aliases (including affiliates and former names), fuzzy threshold 90, supplier shown in the UI, sidebar override | B | Logs, KPI-04 |
| R-07 | Our corpus is easier than a real company's because suppliers are so different | High | Medium: our numbers look better than they would be in practice | Stated as a limitation; report the no-filter comparison as the harder case | C | Comparison table |
| R-08 | Free host wipes its disk on restart | High | Low for the index, medium for uploads and logs | Index zip built in CI and restored at startup; UI warns about uploads; dashboard shows "data since" | D | `/health` after a restart |
| R-09 | Time to first token over 3 s when deployed | Medium | Medium: KPI-07 missed | In order: lower `RETRIEVE_K` from 20 to 12; skip the rewrite when the supplier is named; send sources first | D | Measurement on W5 D3; card K4 |
| R-10 | A dataset field turns out missing or wrong | Low (was Medium; all fields validated on 2026-10-06) | High: features planned on data we don't have | Field-level validation done ([data-validation-report.md](../data/data-validation-report.md)); `validate_cuad.py` re-runs in CI; `fetch_sources.py --check` before each weekly review | A | CI failure; validation report |
| R-11 | Chunker changes break the eval answer mapping | Medium | Medium: eval numbers quietly wrong | Re-run the mapping on every chunker change; chunker version in every result file | C | Eval script checks every answer chunk exists |
| R-12 | Instructions hidden in an uploaded document | Low | Medium: answer manipulated | Context blocks clearly marked; prompt says to ignore instructions in documents; number check; fixed refusal text | C, D | Injection test in `docs/qa.md` |
| R-13 | Vendor page changes or is taken down | Medium | Low | Hash, fetch date and archive link stored; changes reported, never replaced silently | A | `fetch_sources.py --check` |
| R-14 | RAG design approved after W2 D1 | Medium | High: whole build slips | Start on loaders (already agreed in the TDD) while waiting; ask for review early | Team lead | Review status on W2 D1 |
| R-15 | LLM judge grades badly | Medium | Medium: KPI-03 can't be trusted | Judge from a different model family; hand-check 10%; KPI-11 | C | KPI-11 |
| R-16 | Dashboard numbers are misread: eval traffic counted as usage, tiny samples read as trends, or a restart silently resets the window | Medium | Medium: wrong conclusions about adoption or speed | `client = ui` filter; "low sample (n = …)" below 20 questions; "data since" date shown; KPI-15 fixture test | D | KPI-15; QA review of cards |
| R-17 | Adding the dashboard overloads W5 | Medium | Medium: W5 slips | Metrics are SQL over logs that exist from W4; endpoints and cards built W5 D1–D2 before the UI polish; charts use Streamlit built-ins; F-15 is cut first if needed | D | Burn-down on W5 D2 |

---

## 13. Assumptions

An assumption is something we believe but haven't confirmed. The linked risk is what happens if we're wrong.

| ID | Assumption | Status | How we'll check | By | Linked risk |
|---|---|---|---|---|---|
| A-1 | Public contracts from many companies can stand in for one company's repository | Accepted as a limitation | No-filter comparison shows the harder case | W3 D5 | R-07 |
| A-2 | Free-tier APIs are fine because only public and synthetic data is used | Confirmed by the data-sourcing rules | Review licence and source columns in the manifest | W1 D5 | |
| A-3 | A manual lookup takes about 10 minutes | Not confirmed | Time 20 manual lookups (KPI-01 baseline) | W2 D5 | Section 4 numbers change |
| A-4 | Most questions name exactly one supplier | Not confirmed | Share of eval and usability questions matched to a supplier by name; live share from `resolved_by` in the logs | W4 D5 | R-06 |
| A-5 | Current Gemini and Groq models and limits fit our plan | Not confirmed | Check in AI Studio and the Groq console; record in `.env.example` | W1 D5 | R-01 |
| A-6 | CUAD label categories match our question types | **Confirmed** (2026-10-06): all 18 categories present, 137 contracts with 3+ procurement labels; MFN and Price Restrictions thin | `validate_cuad.py` (E-04) | Done | R-10 |
| A-7 | The free CPU host has enough memory for the re-ranker and Chroma | Not confirmed | Deploy a test build; check `/health` and timing | W5 D3 | R-08, R-09 |
| A-8 | 10 buyers doing 12 checks a day is a reasonable team size | Made-up example | Not checked; only used for section 4 | | Section 4 numbers |
| A-9 | We can find at least 20 amendment pairs on EDGAR | **Partly confirmed** (2026-10-06): 973 candidate filings for one query; 2 of 2 sampled amendments name their original and its date | Pairing log | W1 D5 | R-02 |
| A-10 | Users read the grey box as "no answer", not as an error | Not confirmed | Refusal task in the usability session (KPI-09) | W5 D4 | R-04 |
| A-11 | Five cards are enough for the team lead to judge the tool at a glance | Not confirmed | Usability task T-11 (read a card and say whether it is on target) | W5 D4 | R-16 |

---

## 14. Dependencies, approvals and timeline

### 14.1 Dependencies

| What | Needed for | Needed by | Status |
|---|---|---|---|
| Gemini API key (AI Studio) | Embeddings, answers, rewriting | W1 D2 | Pending |
| Groq API key | Backup answers, LLM judge | W1 D2 | Pending |
| Contact email for the EDGAR User-Agent | SEC fair-access rules | W1 D3 | Pending |
| Hugging Face Spaces | Backend hosting | W5 D3 | Pending |
| Streamlit Community Cloud | Frontend hosting | W5 D3 | Pending |
| GitHub Actions | CI, index zip, eval smoke test, `validate_cuad.py` | W1 D4 | Pending |
| Re-ranker weights (`ms-marco-MiniLM-L-6-v2`) | Re-ranking | W3 D5 | Public, available |
| CUAD v1 (`CUAD_v1.json`, PDFs) | Corpus and ground truth | W1 D5 | Available and validated (E-01 to E-05) |
| Altair | Dashboard charts | W5 D1 | Bundled with Streamlit |

### 14.2 Approvals

| Approval | By | Evidence | Due | Blocks |
|---|---|---|---|---|
| PRD and mock UX | Sprint mentor | Sign-off table in 17.3 | W1 D5 (M1); resubmitted 2026-10-06 | Final scope and KPIs |
| RAG architecture design | Sprint mentor | Sign-off in [rag-architecture-design.md](../architecture/rag-architecture-design.md) section 0.2 | W2 D1 (M2) | All build work |
| Final acceptance | Sprint mentor | Held-out eval report meeting section 6.2 | W5 D5 (M7) | Submission |

### 14.3 Timeline

| Phase | Week | Outcome | Exit gate | Milestone |
|---|---|---|---|---|
| 1. Foundations and planning | W1 | Team, repo, CI, corpus, validated manifest, PRD, mock UX | PRD submitted, manifest valid, model names confirmed | M1 (W1 D5) |
| 2. Design and ingestion | W2 | Design approved, all documents chunked, eval set drafted | Full dry run passes, eval set split | M2 (W2 D1), M3 (W2 D5) |
| 3. Embeddings and retrieval | W3 | Hybrid search with re-ranking | Recall@5 ≥ 0.85 on tuning | M4 (W3 D5) |
| 4. Grounded generation | W4 | Cited answers, refusals, follow-ups; `client`, `topic` and clause-open logging | KPI-03 to KPI-06 met on tuning | M5 (W4 D5) |
| 5. App and delivery | W5 | Metrics API, KPI cards and Insights dashboard (D1–D2); API, UI, deployment, final eval | KPI-15 passes (D2); all gates met on held-out; app live | M6 (W5 D3), M7 (W5 D5) |

Day-by-day tasks are in [development-plan.md](../planning/development-plan.md).

---

## 15. Validation checklist

Status as of this version.

| # | Question | Status | Where |
|---|---|---|---|
| 1 | Is the business problem specific and quantified with evidence? | Done; baseline measured in W2 | 2.1, 4, A-3 |
| 2 | Does every KPI have a numeric target, method and timeline? | Done | 6.1, 6.4 |
| 3 | Are all stakeholders named with roles and ownership? | Done | 3.1, 3.2 |
| 4 | Is the primary user clearly defined with a specific use case? | Done | P1; US-01, US-02 |
| 5 | Has the dataset been confirmed with the data team? | **Done**: 30 fields validated on 2026-10-06; 0 left "To check" | 5, [data-validation-report.md](../data/data-validation-report.md) |
| 6 | Does every user story follow role + action + business benefit? | Done | 7.2 |
| 7 | Is v1 scope bounded with an out-of-scope list? | Done | 8.1 to 8.5 |
| 8 | Is the data workflow documented end to end? | Done | 10 |
| 9 | Are all assumptions documented as risks? | Done | 13, linked to 12 |
| 10 | Is a wireframe or layout plan included? | Done | 11, [mock-ux.md](../ux/mock-ux.md) |
| 11 | Is the PRD free of vague language ("should", "might", "probably")? | Done | Requirements use measurable criteria; see 18.2 |
| 12 | Has AI-assisted review been done and the gaps fixed? | Done (two passes) | 16 |
| 13 | Are naming and formatting consistent? | Done | 18.2 |
| 14 | Has a stakeholder alignment review been done? | M1 review held; comments addressed in v1.1; awaiting sign-off | 16.3, 17 |
| 15 | Can a non-technical reader understand what this is for? | Done | 1, 2, 4, glossary in 18.3 |
| 16 | Does the main screen show distinct KPI cards above the fold? | **Done**: five cards K1–K5 in the top 200 px at 1366 × 768 | 6.4, 11.1, [mock-ux.md](../ux/mock-ux.md) S-01 |
| 17 | Does the analytics dashboard include charts and data tables? | **Done**: four charts and four tables, each with a defined metric | 6.4, 11.2, [mock-ux.md](../ux/mock-ux.md) S-13 |

---

## 16. AI-assisted review and M1 review response

### 16.1 Prompts

1. Business problem: "Review this PRD business problem statement. Check: (1) Is the user named specifically? (2) Is the pain quantified with a number? (3) Does the success criterion have a numeric target and timeline? (4) Is the business impact documented? Flag any missing element with a specific suggestion to fix it."
2. KPIs: "Review each KPI in this PRD section. For each KPI, verify it has: (1) a metric name, (2) a measurement method, (3) a numeric target, and (4) a timeline. For any KPI missing one of these, rewrite it with all four elements included."
3. User stories: "Review each user story in this PRD. Each must follow: 'As a [specific role], I want to [specific action], so that [specific business benefit].' Flag any story that is missing the role or the business benefit. Rewrite the flagged stories with all three elements."
4. Risks and assumptions: "Review this PRD for unconfirmed assumptions — statements presented as facts that have not been validated with the data team, engineering team, or business stakeholders. For each assumption found, rewrite it as a documented risk with likelihood, impact, and mitigation plan."
5. Final review: "You are a senior product manager reviewing this PRD for an analytics internship submission. Check: problem statement specificity, KPI completeness, user story format, scope boundary clarity, data source validation status, risk documentation quality, and submission standards. Rate each section 1-5 and list the top 3 improvements needed before this PRD is submission-ready."

### 16.2 First pass

| Prompt | Problem found | What we changed |
|---|---|---|
| 1 | Lookup time and cost figures were written as facts with no source | Turned section 4 into a model with listed inputs; lookup time became assumption A-3, measured in W2 |
| 1 | Success was only measured with system metrics | Added KPI-01 (time to checked answer) and KPI-09 (task success) |
| 2 | Unsupported numbers were tracked with no target | Added KPI-10 with a 5% limit |
| 2 | No number for amendment answers | Added KPI-08 (zero outdated-term answers) |
| 3 | Upload and evaluation had no user story | Added US-14 and US-15 |
| 3 | Feedback had no stated benefit | Wrote US-18 with a benefit and put it first on the cut list |
| 4 | Data fields read as if already checked on our copies | Added a status to every field in section 5 and risk R-10 |
| 4 | We assumed free hosting would be enough without saying so | Added A-7, linked to R-08 and R-09 |
| 5 | Out-of-scope items had no defined behaviour | Added the "what v1 does instead" column in 8.2 |

### 16.3 M1 review response (v1.1)

The mentor's M1 review asked for three fixes before approval.

| # | Review comment | What we changed | Where |
|---|---|---|---|
| 1 | Fully confirm and validate your dataset fields (remove all "To check" statuses) | Validated all 30 fields on 2026-10-06: scripted checks over all 510 CUAD contracts (13,823 of 13,823 label offsets exact), EDGAR full-text search and two amendments read in full, five vendor documents read in full. 17 fields Confirmed, 13 Known issue with an ingestion rule. Eleven decisions (DV-1 to DV-11) changed the plan: label source, TXT source, title patterns, six redaction forms, footer cleaning, supplier target (100–140 suppliers, 30–50 key), date rules, amendment chains, vendor selection. | Section 5, 2.1, 10.2, R-10, A-6, A-9; [data-validation-report.md](../data/data-validation-report.md) |
| 2 | Add distinct KPI cards above the fold on your main screen | Five cards (K1 questions asked, K2 answer rate, K3 time to checked answer, K4 time to first token, K5 citation accuracy), each with formula, target or threshold, status and window, placed in the top 200 px of the Ask screen at 1366 × 768. New story US-19, feature F-16, requirement FR-12, delivery KPI-15. | 6.4, 7.2, 8.1, 9.1, 11.1; [mock-ux.md](../ux/mock-ux.md) S-01 |
| 3 | Incorporate basic charts or data tables to fully satisfy the analytics dashboard requirements | Insights tab with four charts (outcomes per day, response time per day with target line, questions by topic, corpus coverage) and four tables (supplier activity, unanswered questions, eval vs targets, corpus by supplier), with period and supplier filters, empty and low-sample states. New stories US-20, US-21, feature F-17, persona P6. | 6.4, 7.1, 7.2, 8.1, 11.2; [mock-ux.md](../ux/mock-ux.md) S-13 |

Second AI-assisted pass on v1.1 (prompts 2, 4 and 5):

| Prompt | Problem found | What we changed |
|---|---|---|
| 2 | New dashboard metrics had no targets or thresholds | Each card has a target (from an existing KPI) or a stated monitoring threshold; KPI-15 added for dashboard accuracy |
| 4 | "Dashboard shows real usage" assumed eval runs wouldn't be counted | `client` field and the `client = ui` filter; R-16 |
| 5 | Dashboard scope could be read as the H3 portfolio dashboard | Out-of-scope row added in 8.2 separating usage/quality analytics (v1) from contract-term analytics (H3) |

Still to do before final submission:

1. Replace A-3 with the measured W2 baseline and update section 4.
2. Record the mentor's decision on v1.1 in section 17.3.

---

## 17. Decisions, open questions and sign-off

### 17.1 Decisions

| ID | Question | Answer | Affects |
|---|---|---|---|
| D1 | ChromaDB or Qdrant? | ChromaDB; switch only if filtered search p95 goes over 100 ms (measured in W3) | Nothing in scope |
| D2 | Does code (not the model) work out certificate validity? | Yes, against `AS_OF_DATE` | F-08, US-10 |
| D3 | How do we cite HTML and TXT files with no real pages? | Clause number only, never an estimated page | Citation format |
| D4 | What do we say about redacted values? | "Redacted in the filed copy", with the clause cited, never an estimate | US-07 |
| D5 | Do we support questions about more than one supplier in v1? | No, we ask the user to pick one | US-13, 8.2 |
| D6 | Is a wrong-refusal rate of 10% or less an acceptance gate? | Yes | KPI-06, 6.2 |
| D7 | Where do the KPI cards and charts live? | Cards on both tabs, above the conversation on Ask; charts and tables only on the Insights tab, so the chat stays one click from the input | F-16, F-17 |
| D8 | Do eval runs count in live metrics? | No: live metrics use `client = ui` only; eval results appear only in K5 and table M-11 | M-01 to M-04, R-16 |
| DV-1 to DV-11 | Data decisions from the validation | See [data-validation-report.md](../data/data-validation-report.md) section 6 | Section 5 |

### 17.2 Open questions for the M1 review

| ID | Question | Our proposal |
|---|---|---|
| Q1 | Is KPI-10 (unsupported-number rate ≤ 5%) a guardrail or only tracked? | A guardrail, not an acceptance gate |
| Q2 | Is KPI-01 (30 s to a checked answer) the main user-facing KPI? | Yes, and it is card K3 |
| Q3 | How many usability testers for KPI-01 and KPI-09? | 5: team members from other workstreams plus classmates |
| Q4 | Is the 80% answer-rate threshold on card K2 right for a live demo where people ask unanswerable questions on purpose? | Keep 80% as an amber threshold, not a gate; revisit after a week of live data |

### 17.3 Sign-off

| Role | Name | Decision | Date | Comments |
|---|---|---|---|---|
| Sprint mentor (business) | | ☐ Approved ☐ Approved with changes ☐ Rejected | | v1.0 returned with 3 changes; v1.1 resubmitted 2026-10-06 |
| Sprint mentor (technical, RAG design) | | ☐ Approved ☐ Approved with changes ☐ Rejected | | |
| Team lead | | ☐ Agreed | | |
| Workstream A owner | | ☐ Agreed | | |
| Workstream B owner | | ☐ Agreed | | |
| Workstream C owner | | ☐ Agreed | | |
| Workstream D owner | | ☐ Agreed | | |

---

## 18. Appendix

### 18.1 Traceability

| Problem (2.2) | Stories | Features | Requirements | KPIs |
|---|---|---|---|---|
| Volume | US-01, US-12 | F-03, F-04 | FR-5 | KPI-01, KPI-02, KPI-07 |
| Fragmentation | US-03, US-08 | F-02, F-04 | FR-4, FR-5 | KPI-08 |
| Precision | US-02, US-07, US-17 | F-01, F-06 | FR-2, FR-6 | KPI-03, KPI-10 |
| Formats | US-02, US-11, US-14 | F-01, F-10 | FR-1, FR-2, FR-9 | KPI-03 |
| Trust | US-04, US-06, US-10, US-13 | F-05, F-06, F-08, F-11 | FR-6, FR-7 | KPI-04, KPI-05, KPI-06, KPI-09 |
| Measuring quality | US-15, US-16 | F-12, F-13 | FR-11, NFR-3 | KPI-11, KPI-12 |
| Visibility | US-19, US-20, US-21 | F-16, F-17 | FR-12, NFR-1, NFR-9 | KPI-15 (and KPI-01, -04, -07 on cards) |

### 18.2 Naming and wording

| Prefix | Meaning | Section |
|---|---|---|
| `P#` | Persona | 7.1 |
| `US-##` | User story | 7.2 |
| `F-##` | Feature | 8.1 |
| `FR-#`, `NFR-#` | Requirement | 9 |
| `KPI-##` | KPI | 6.1 |
| `M-##` | Live metric on cards or dashboard | 6.4 |
| `K#` | KPI card | 11.1 |
| `R-##` | Risk | 12 |
| `A-#` | Assumption | 13 |
| `D#` | Design decision | 17.1 |
| `DV-#` | Data decision from validation | [data-validation-report.md](../data/data-validation-report.md) |
| `E-##` | Validation evidence | [data-validation-report.md](../data/data-validation-report.md) |
| `Q#` | Open question | 17.2 |
| `M#` | Milestone | 14.3 |
| `W# D#` | Sprint week and day | throughout |

Wording we avoided, and what we wrote instead:

| Avoided | Used |
|---|---|
| "The assistant should be fast" | "Time to first token p50 under 3 s on the deployed app" |
| "Answers should be accurate" | "Answer correctness of 85% or more on the held-out split" |
| "We will use appropriate data" | "CUAD v1, EDGAR EX-10, vendor DPAs/SLAs and synthetic documents (seed 42), with owners and fields in section 5" |
| "The data is probably clean" | "Validated on 2026-10-06: 17 fields confirmed, 13 known issues each with an ingestion rule" |
| "We might add comparisons" | "Supplier comparison: out of scope, handled by `clarify_multiple_suppliers`, roadmap H4" |
| "A dashboard with useful metrics" | "Five KPI cards and eight charts and tables, each with a formula in section 6.4" |

### 18.3 Glossary

| Term | Meaning |
|---|---|
| RAG | Retrieval-Augmented Generation: find relevant text first, then have a language model answer using only that text |
| Chunk | A clause, part of a long clause, or part of a table, stored and searched as one unit |
| Citation `[C#]` | A marker after a sentence pointing to a numbered passage; code maps it to a real document, clause and page |
| Hybrid search | Combining meaning-based (vector) search with exact-word (BM25) search |
| RRF | Reciprocal Rank Fusion: merges two ranked lists using only positions |
| Re-ranker | A small model that reads the question and each passage together to put the best ones first |
| Relevance check | A score check that decides whether the system answers at all |
| Refusal | A fixed "not found" message given instead of an answer |
| Amendment, term in force | A later document that changes an original term; the latest one is the term in force |
| Recall@5 | Share of answerable questions whose correct clause is in the top 5 results |
| Time to first token | How long until the first word of the answer appears |
| Tuning and held-out split | Questions used to choose settings, and questions kept back for the final numbers |
| Synthetic document | A generated price schedule or certificate, labelled as such |
| KPI card | A box at the top of the screen showing one metric, its target and whether it is on target |
| Above the fold | Visible when the page opens, without scrolling (here: in a 1366 × 768 window) |

ClauseCheck gives information from contracts. It does not give legal advice.
