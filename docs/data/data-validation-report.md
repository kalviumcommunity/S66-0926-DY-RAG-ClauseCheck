# ClauseCheck: Data Validation Report
 
Sprint 2, Simulated Work (AI Application Development with RAG)
Repo: `FirstName_ClauseCheck_Kalvium-Community`
See also: `PRD.md` (section 5), `data-sourcing.md`, `functional-requirements.md` (FR-1, FR-4)
Version: 1.0, 2026-10-06
Status: submitted with PRD v1.1 in response to the M1 review.
 
The M1 review asked us to **fully confirm and validate every dataset field and remove all "To check" statuses**. This report records what we checked, how, and what we found. Every field in PRD section 5 now has one of two statuses, each pointing to evidence in this report:
 
- **Confirmed**: checked on the actual data (or the source's published file listing), with the check and result recorded below.
- **Known issue (handled)**: checked, a problem was found, and a fixed rule handles it. The rule is part of ingestion, so nothing depends on a future check.
Checks were run on 2026-10-06. The CUAD checks are scripted (`scripts/validate_cuad.py`, committed) and can be re-run by anyone with one command.
 
---
 
## Contents
 
- [ClauseCheck: Data Validation Report](#clausecheck-data-validation-report)
  - [Contents](#contents)
  - [1. Summary](#1-summary)
  - [2. CUAD v1](#2-cuad-v1)
    - [2.1 What we checked and where](#21-what-we-checked-and-where)
    - [2.2 Results of the scripted check (E-04)](#22-results-of-the-scripted-check-e-04)
    - [2.3 Field status](#23-field-status)
  - [3. SEC EDGAR EX-10](#3-sec-edgar-ex-10)
    - [3.1 What we checked](#31-what-we-checked)
    - [3.2 What the two amendments showed](#32-what-the-two-amendments-showed)
    - [3.3 Field status](#33-field-status)
  - [4. Vendor DPAs and SLAs](#4-vendor-dpas-and-slas)
    - [4.1 What we checked](#41-what-we-checked)
    - [4.2 Field status](#42-field-status)
  - [5. Synthetic documents](#5-synthetic-documents)
  - [6. Decisions made because of the validation](#6-decisions-made-because-of-the-validation)
  - [7. What changed in the PRD and other documents](#7-what-changed-in-the-prd-and-other-documents)
  - [8. How to re-run the checks](#8-how-to-re-run-the-checks)
---
 
## 1. Summary
 
| Source | Fields checked | Confirmed | Known issue (handled) | Biggest finding |
|---|---|---|---|---|
| CUAD v1 | 14 | 8 | 6 | Contracts come from 106 different companies, so most suppliers have one CUAD contract (supplier target reshaped, DV-7) |
| SEC EDGAR EX-10 | 7 | 3 | 4 | Amendments come in chains ("Fifth Amendment", "Modification of the Second Amendment") and some have no calendar effective date (DV-9, DV-10) |
| Vendor DPAs / SLAs | 6 | 3 | 3 | 1 of 5 sampled documents had no date (excluded by our rule) and 1 was an index page, not an SLA (DV-11) |
| Synthetic | 3 | 3 | 0 | None: values are set by our generator |
| **Total** | **30** | **17** | **13** | **0 fields left "To check"** |
 
---
 
## 2. CUAD v1
 
### 2.1 What we checked and where
 
| Evidence | What it is |
|---|---|
| E-01 | `git clone https://github.com/TheAtticusProject/cuad` (commit `67faa0e`). `data.zip` contains `CUADv1.json` (40.1 MB, version `aok_v1.0`), `train_separate_questions.json`, `test.json`. |
| E-02 | Hugging Face mirror `theatticusproject/cuad`, folder `CUAD_v1/`: `CUAD_v1.json` (40.1 MB), `master_clauses.csv` (3.96 MB), `master_clauses.xlsx`, `full_contract_pdf/`, `full_contract_txt/`, `label_group_xlsx/`, `CUAD v1 ReadMe _ Datasheet/`. `full_contract_pdf/` is split into `Part_I`, `Part_II`, `Part_III`, each with one sub-folder per contract type (e.g. `Supply`, `Service`, `Hosting`). |
| E-03 | Zenodo record 4595826: `CUAD_v1.zip`, 105.9 MB, CC BY 4.0, published 2021-03-11; "510 commercial legal contracts", "41 categories". |
| E-04 | `scripts/validate_cuad.py` run on `CUADv1.json` (results in 2.2). |
| E-05 | One PDF opened in full: `full_contract_pdf/Part_I/Supply/LohaCompanyltd_20191209_F-1_EX-10.16_11917878_EX-10.16_Supply Agreement.pdf` (text layer present, 6 pages, numbered clauses from "1. General provisions", per-page footer "Source: LOHA CO. LTD., F-1, 12/9/2019"). |
 
### 2.2 Results of the scripted check (E-04)
 
**Size and structure**
 
| Check | Result |
|---|---|
| Contracts | 510 |
| Clause categories | 41 |
| Labelled answer spans | 13,823 |
| Spans whose `answer_start` offset points to exactly the labelled text | **13,823 of 13,823 (100%)** |
| Categories with "payment", "invoice" or "net" in the name | 0 |
| The 18 categories ClauseCheck uses (PRD 5.2) present in the file | 18 of 18 |
 
**File names (contract titles)**
 
| Pattern | Example | Count |
|---|---|---|
| Old: `FILER_MM_DD_YYYY-EX-10-TYPE` | `LIMEENERGYCO_09_09_1999-EX-10-DISTRIBUTOR AGREEMENT` | 301 |
| New: `Filer_YYYYMMDD_FORM_EX-10.x_ID_EX-10.x_Type` | `LohaCompanyltd_20191209_F-1_EX-10.16_11917878_EX-10.16_Supply Agreement` | 168 |
| Free-form, no filing date | `MetLife, Inc. - Remarketing Agreement` | 41 |
 
Filing dates in parsed titles run from 1994 to 2020.
 
**Procurement-type contracts** (title contains Supply, Manufacturing, Outsourcing, Service, Maintenance, Distributor or Hosting)
 
| Type | Contracts |
|---|---|
| Service | 35 |
| Distributor | 34 |
| Maintenance | 34 |
| Supply | 25 |
| Hosting | 20 |
| Outsourcing | 17 |
| Manufacturing | 13 |
| **Total** | **178** |
| Of these, with labels in at least 3 procurement categories (our selection rule) | **137** |
 
The selection target in PRD 5.1 (minimum 120 contracts) is met: 137 contracts qualify. The fetch script takes the type from the PDF folder name (E-02), which is authoritative; the title count above is a cross-check and may differ by a few contracts.
 
**Label coverage in the 178 procurement contracts**
 
| Category | Contracts with a label | Use in the eval set |
|---|---|---|
| Parties | 178 | Supplier name and aliases |
| Agreement Date | 162 | `effective_date` fallback |
| Expiration Date | 154 | Renewal questions |
| Governing Law | 151 | Metadata check |
| Effective Date | 136 | `effective_date` |
| Cap on Liability | 112 | Liability questions |
| Audit Rights | 85 | Compliance questions |
| Renewal Term | 81 | Renewal questions |
| Termination for Convenience | 74 | Termination questions |
| Insurance | 67 | Compliance questions |
| Minimum Commitment | 63 | Pricing questions |
| Warranty Duration | 57 | Warranty questions |
| Notice Period to Terminate Renewal | 56 | Renewal questions |
| Uncapped Liability | 44 | Liability questions |
| Liquidated Damages | 27 | Penalty questions |
| Volume Restriction | 24 | Pricing questions |
| Price Restrictions | 11 | At most 2 questions |
| Most Favored Nation | 8 | At most 2 questions; also a source of hand-checked "no such clause" questions |
 
171 of the 178 have an Effective Date or an Agreement Date label.
 
**Label length.** Median label length is 306 characters for Cap on Liability, 302 for Notice Period, 273 for Renewal Term, 245 for Insurance and 20 for Effective Date. 33.1% of all labels are longer than 300 characters. This confirms that clause-type labels cover the whole clause, not the short answer.
 
**Redactions in the 178 procurement contracts**
 
| Check | Result |
|---|---|
| Contracts with at least one redaction marker | 74 (42%) |
| Marker forms found (occurrences) | `[*****]` 2,221 · `[***]` 1,809 · `[*]` 1,740 · `***` 1,019 · "confidential treatment" 658 · `[**]` 417 |
| Label spans that contain a marker | 294 of 4,707 (6.2%) |
 
**Text and layout**
 
| Check | Result |
|---|---|
| Contracts whose text contains form-feed page breaks | 0 of 510 |
| Contracts with 3 or more stand-alone page-number lines (e.g. `- 1 -`, `12`) | 222 of 510 |
| Contracts with the EDGAR footer `Source: {COMPANY}, {FORM}, {date}` | 180 of 510 (repeated once per page, up to 111 times) |
| Procurement contracts where the clause-heading pattern finds 3 or more headings | 140 of 178 (79%); the other 38 use the fallback split |
| Procurement contracts with payment-term wording (`Net 30`, "within 30 days of receipt of invoice", early-payment discount) | 11 of 178 |
| Procurement contracts per filing company | 178 contracts from 106 companies; only 4 companies have 2 or more |
| Text length (characters) | min 1,660 · median 36,275 · max 338,211 |
 
### 2.3 Field status
 
| Field | Status | Evidence | Finding and rule |
|---|---|---|---|
| `CUAD_v1.json` contract text (`context`) | Confirmed | E-01, E-04 | 510 contracts, all with text. This text is what the labels index into, so it is our TXT input (DV-2). |
| `CUAD_v1.json` labels and character offsets | Confirmed | E-04 | 13,823 of 13,823 offsets exact. Our label source (DV-1). |
| `master_clauses.csv` | Confirmed (not used for ground truth) | E-02 | File exists (3.96 MB). Same annotations as the JSON but without offsets, so we use it only as a human-readable cross-reference (DV-1). |
| `full_contract_pdf/Part_{I,II,III}/<Type>/*.pdf` | Confirmed | E-02, E-05 | Path has an extra `Part_*` level and folder names vary between parts (`Affiliate_Agreements` vs `Affiliate Agreement`). The fetch script normalises folder names (DV-3). |
| PDF text layer | Known issue (handled) | E-05 | Sampled PDF has a text layer. Rule: a PDF yielding under 200 characters per page on average is not parsed as PDF; the contract is loaded from its JSON text instead (TXT loader), so no contract is lost and nothing needs OCR. The count is in the ingestion report. |
| File name / title | Known issue (handled) | E-04 | Two patterns (301 + 168) plus 41 free-form titles. Rule: parse both patterns; free-form titles are excluded from selection because they can't be traced to a filing date (DV-4). |
| Contract type | Confirmed | E-02, E-04 | All 7 procurement types exist as folders in every part. 178 procurement contracts, 137 meet the selection rule. |
| Label categories (18 used) | Confirmed | E-04 | All present. No payment-terms category, so payment questions use EDGAR and synthetic documents (unchanged plan). |
| Label coverage | Known issue (handled) | E-04 | Most Favored Nation (8) and Price Restrictions (11) are thin. Rule: at most 2 eval questions each. An empty label is never used as an unanswerable question without a hand check. |
| Label length | Known issue (handled) | E-04 | Whole-clause labels (median about 300 characters). Rule: the LLM judge compares meaning, not exact text (unchanged plan). |
| Redaction markers | Known issue (handled) | E-04 | Six marker forms, not just `[***]`. Rule: `has_redaction` uses one pattern covering all six forms (DV-5); the 294 label spans with markers are excluded from answerable questions and are candidates for the 2–3 redacted-value questions. |
| Page numbers in TXT | Known issue (handled) | E-04, E-05 | No form-feed page breaks; page-number lines and per-page EDGAR footers are mixed into the text. Rule: the cleaner removes stand-alone page-number lines and `Source:` footers; TXT citations show the clause only (decision D3, unchanged) (DV-6). |
| `effective_date` | Confirmed | E-04 | 171 of 178 have an Effective Date or Agreement Date label. Rule: Effective Date label, else Agreement Date label, else read from the text by hand; a contract with no date in the text is dropped (DV-8). |
| Supplier (`Parties`) | Confirmed | E-04 | 178 of 178 have a Parties label, used for supplier names and aliases. |
 
---
 
## 3. SEC EDGAR EX-10
 
### 3.1 What we checked
 
| Evidence | What it is |
|---|---|
| E-06 | EDGAR full-text search API, query `"amendment to supply agreement"`, forms 8-K, 10-K, 10-Q: **973 hits**. 9 of the first 10 hits are EX-10 exhibits (filed 2003–2011), all `.htm`. Each hit returns the company CIK, accession number and file name. |
| E-07 | Exhibit opened in full: Cygne Designs, EX-10.33, filed 2007-06-14, `https://www.sec.gov/Archives/edgar/data/906782/000119312507135798/dex1033.htm` |
| E-08 | Exhibit opened in full: Tully's Coffee, EX-10.2, filed 2003-11-12, `https://www.sec.gov/Archives/edgar/data/944136/000119312503078438/dex102.htm` |
 
### 3.2 What the two amendments showed
 
| Check | E-07 Cygne Designs | E-08 Tully's Coffee |
|---|---|---|
| Title | Fifth Amendment to Supply Agreement | Modification of the Second Amendment to Supply Agreement |
| Recital names the original and its date | Yes: "Supply Agreement dated July 31, 2005, as amended" | Yes: "On April 26, 2001, Seller and Foodx … entered into that certain Tully's Coffee Supply Agreement" |
| Effective date in the text | Yes, a calendar date: "effective February 1, 2007" | No calendar date: "Effective upon the full execution and delivery of the Third Amendment to the License Agreement" |
| Redaction markers | None | None |
| Changed values | Yes: gross margins 35% and 25% | Yes: "at least forty new … Stores", deadline "November 30, 2003" |
| Numbered sections | Yes (1–3 with (a), (b)) | Yes (1–6) |
| Party names | Original signed by an affiliate (AZT International) of the current party | A party renamed ("Foodx (formerly known as Tully's Coffee Japan Co., Ltd.)") |
 
### 3.3 Field status
 
| Field | Status | Evidence | Finding and rule |
|---|---|---|---|
| Exhibit file and format | Confirmed | E-06, E-07, E-08 | EX-10 exhibits found in volume; sampled files are HTML. Rule unchanged: keep the native format. |
| `source_url` (archive URL) | Confirmed | E-06, E-07, E-08 | Pattern `https://www.sec.gov/Archives/edgar/data/{CIK}/{accession without dashes}/{file}`, built from the search result. Both sampled URLs resolve. |
| Amendment recitals (`parent_doc_id`) | Confirmed | E-07, E-08 | Both recitals name the original agreement and its date, which is what pairing needs. |
| Amendment chains | Known issue (handled) | E-07, E-08 | Amendments amend earlier amendments. Rule: `parent_doc_id` always points to the original agreement; `doc_id` uses the amendment number from the title (`AMD5`); a chain is used for an eval question only if every earlier amendment touching the same clause is also indexed, or the later amendment restates the whole clause (DV-10). |
| `effective_date` | Known issue (handled) | E-07, E-08 | Some amendments have only a conditional effective date. Rule: calendar effective date from the text; else the signature date in the document; else the amendment is dropped. Never the filing date (DV-9). |
| Redactions | Known issue (handled) | E-04, E-06 | None in the two amendments, but 42% of CUAD procurement contracts (also EDGAR filings) have markers. Same six-form rule as CUAD (DV-5). |
| Supplier names across a pair | Known issue (handled) | E-07, E-08 | Affiliates and renamed companies. Rule: both names go into the supplier's alias list in `suppliers.csv`. |
 
Amendment volume (assumption A-9, at least 20 pairs): one query alone returns 973 filings, so the supply is there. Building the pairs is W1 D5 work in the pairing log; the fields it needs are confirmed above.
 
---
 
## 4. Vendor DPAs and SLAs
 
### 4.1 What we checked
 
Five candidate documents from four vendors were opened on 2026-10-06.
 
| Evidence | Document | Date shown | Finding | Kept? |
|---|---|---|---|---|
| E-09 | Google Cloud Compute Engine SLA (HTML) | "Last modified March 4, 2025" | Service-credit table: 99.00% to < 99.99% → 10%; 95.00% to < 99.00% → 25%; < 95.00% → 100% (Premium Tier, most regions) | Yes |
| E-10 | AWS Compute SLA (HTML) | "Last Updated: May 25, 2022" | Two tables on one page: region-level (10% / 30% / 100%) and instance-level (thresholds from 99.5%) | Yes |
| E-11 | Atlassian Data Processing Addendum (HTML) | "Effective starting: August 17, 2026" | Breach notice "without undue delay and, where feasible, no later than seventy-two (72) hours"; 30 days' notice of new sub-processors | Yes |
| E-12 | AWS Data Processing Addendum (PDF) | None found | Text layer present; incident notice "without undue delay"; no version or date | **No**: fails the date rule |
| E-13 | Twilio "Service Level Agreements" page (HTML) | "Last Updated: April 9, 2026" | An index page linking three separate SLAs; no credit table | **No**: index page; the linked SLA document is used instead |
 
### 4.2 Field status
 
| Field | Status | Evidence | Finding and rule |
|---|---|---|---|
| Document text | Confirmed | E-09 to E-13 | All five reachable without signing in; HTML and PDF both have text. |
| "Last updated" date (`effective_date`) | Known issue (handled) | E-09 to E-12 | Three different wordings ("Last modified", "Last Updated", "Effective starting"); one document had none. Rule: the date parser accepts these labels; a document with no date is excluded (E-12). |
| Service-credit tables | Known issue (handled) | E-09, E-10 | Several tables per page, each for a different scope (region vs instance, tier). Rule: each table chunk starts with its caption and the heading above it, so the scope travels with the numbers (FR-2, AC-2.3). |
| Page type | Known issue (handled) | E-13 | Some "SLA" URLs are index pages. Rule: a document is kept only if it contains the terms themselves (selection rule 2 in `data-sourcing.md` 6.3, now checked on every candidate). |
| `retrieved_at`, `sha256`, archive URL | Confirmed | Fetch design | Written by `fetch_sources.py`; independent of page content. |
| Standard terms label | Confirmed | E-09 to E-11 | All are published standard terms. The UI label "standard terms (not negotiated)" stays. |
 
The Atlassian DPA's effective date (August 2026) shows how recently these pages change, which is what the hash check (R-13) is for.
 
---
 
## 5. Synthetic documents
 
| Field | Status | Evidence | Note |
|---|---|---|---|
| SKU, unit price, tier bounds, payment terms | Confirmed | Generator spec, seed 42 | Values are written by `generate_synthetic.py` together with their answers. |
| Certificate type, issue date, expiry date | Confirmed | Generator spec | Validity computed in code against `AS_OF_DATE` (D2). |
| `is_synthetic = true` | Confirmed | Generator spec | Always labelled in the UI. |
 
---
 
## 6. Decisions made because of the validation
 
| ID | Decision | Why | Changes |
|---|---|---|---|
| DV-1 | CUAD ground truth comes from `CUAD_v1.json`, not `master_clauses.csv` | The JSON has character offsets and all 13,823 were verified; the CSV has no offsets | PRD 5.2, `data-sourcing.md` 4.1, 4.5 |
| DV-2 | CUAD TXT input is the `context` text from `CUAD_v1.json` | It is the exact text the labels point into, so gold-chunk mapping needs no fuzzy matching | PRD 5.2, `data-sourcing.md` 4.3 |
| DV-3 | Contract type comes from the PDF folder name, normalised across `Part_I`–`Part_III` | Folder names differ between parts | `data-sourcing.md` 4.3 |
| DV-4 | Parse both title patterns; exclude the 41 free-form titles | They can't be traced to a filing date | PRD 5.2, `data-sourcing.md` 4.3 |
| DV-5 | `has_redaction` matches six marker forms | `[***]` alone would miss most markers | PRD 5.2, 5.7; AC-4.3 |
| DV-6 | Cleaner removes page-number lines and `Source:` footers from CUAD text | Present in 222 and 180 contracts; they would end up inside chunks | PRD 10.2; `data-sourcing.md` 11 |
| DV-7 | Supplier target: about 100–140 suppliers in total, of which 30–50 are "deep" suppliers with 2–6 documents | 178 procurement contracts come from 106 companies; most suppliers will have one CUAD contract. Deep suppliers get the amendments, price schedules, certificates and follow-up questions | PRD 2.1, 5.1, 8.3; `data-sourcing.md` 8 |
| DV-8 | CUAD `effective_date`: Effective Date label → Agreement Date label → text → drop | 171 of 178 covered by labels | PRD 5.2 |
| DV-9 | EDGAR `effective_date`: calendar date in text → signature date → drop; never the filing date | Conditional effective dates exist (E-08) | PRD 5.3; AC-4.5 |
| DV-10 | `parent_doc_id` points to the original; chains used only when complete for the clause | Fifth amendments and modifications of amendments exist (E-07, E-08) | PRD 5.3; `data-sourcing.md` 5.4 |
| DV-11 | Vendor documents need a date label and must be the terms themselves; table chunks carry their caption | E-12, E-13, E-10 | PRD 5.4; `data-sourcing.md` 6.3 |
 
---
 
## 7. What changed in the PRD and other documents
 
| Document | Change |
|---|---|
| `PRD.md` v1.1 | Section 5: every "To check" replaced with Confirmed or Known issue (handled) and an evidence ID. R-10 likelihood lowered. A-6 confirmed, A-9 partly confirmed. Validation checklist item 5 done. |
| `data-sourcing.md` v1.1 | Paths, label source, title patterns, redaction forms, supplier target shape and amendment-chain rule updated to match this report. |
| `functional-requirements.md` v1.1 | AC-4.3 lists the six redaction forms; AC-4.5 adds the conditional-date rule. |
 
---
 
## 8. How to re-run the checks
 
```bash
# CUAD (scripted; prints the numbers in section 2.2)
git clone https://github.com/TheAtticusProject/cuad && unzip cuad/data.zip -d data/sources/cuad_json
python scripts/validate_cuad.py data/sources/cuad_json/CUADv1.json > data/sources/cuad_validation.json
 
# EDGAR and vendor documents: every manifest row is re-checked by the fetch script
python scripts/fetch_sources.py --check
```
 
`scripts/validate_cuad.py` also runs in CI after `fetch_sources.py --cuad`, and fails if any label offset stops matching.
 
ClauseCheck gives information from contracts. It does not give legal advice.
 