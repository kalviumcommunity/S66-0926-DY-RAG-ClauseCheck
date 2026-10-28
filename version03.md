# Version 3: the redesign

The interface was rebuilt to `ClauseCheck_Redesign_Spec.pdf` (8 pages), and the backend gained what
the new screens need to show only verified facts. `debugging.md` is unchanged. Everything here is
uncommitted and nothing has been pushed.

Contents: 1 Summary · 2 Interface · 3 Backend · 4 Data fixes · 5 Landing page · 6 Configuration ·
7 Tests · 8 How to run it · 9 Differences from the spec · 10 Not done or not checked · 11 File list

## 1. Summary

| Before (version 2) | Now |
|---|---|
| Sidebar with Chat, New contract analyser, Insights | No sidebar. Masthead tabs Ask, Contracts, Insights |
| Chat messages with a "View full clause" expander | A check record per question: answer, Terms found table, seal, annotated clause page |
| Answer shown whether or not figures were verifiable | Seal lists only what the backend verified; unverified numbers are named |
| Spinner while waiting | The real steps with their timings |
| Upload with a spinner | A numbered filing form and a timestamped filing log |
| Insights: JSON and metric tiles | A dated service report with scorecard, figures and tables |
| Answer rate ignored errors | Answer rate counts failures, against an 80% target |
| 300 of 593 questions "other" | A keyword topic classifier; what it misses is shown as "Not classified" |

## 2. Interface

Streamlit supplies inputs and state (search box, selects, file uploader, buttons, session state);
the distinctive parts are our own HTML through `st.html`, with every value escaped (`ui.esc`).

**Shared frame** (`components/layout.py`, `components/nav.py`). Every page calls `frame(api, active)`:
it injects `frontend/static/app.css`, draws the masthead (§ wordmark in Source Serif 4, tabs, index
status), the double rule, and the status line. The active tab is drawn by us because Streamlit sets
no `aria-current`. `st.navigation(position="hidden")` keeps Streamlit's own menu away. The status
line shows the window, the question count and four measures, each with its target and a met or not
met mark; citation accuracy reads "not measured" until it has a value. If the backend is down every
page shows a red "System failure, not a finding" note instead.

**Ask** (`views/ask.py`).
- *Register*: numbered rows (`001`...) with contract name, documents, latest effective date and when
  it was last checked, most recently checked first, a **Check** button per row, "Show all", a search
  box, and a **Recent checks** column. `?contract=<id>` opens a contract directly.
- *Contract view*: heading with the document IDs, **Change contract**, **Documents (n)** (a popover
  listing files, dates and which file each amendment changes, with a link to add one), **New check**
  (clears this contract only). Left: the records and the question box; right: the clause page.
  Before the first question it offers the five questions most often asked of that contract (from
  the log), or generic starters when there are none.
- *Check record* (`ui.check_record`): the question in serif, the answer with figures in bold and
  citations as small `c1` references, **Terms found** (term, value in the clause, source, status),
  the seal, and a timing line. **Checked** is green and lists "n of n citations found in the
  documents", "n of n numbers match the clause text" and each amendment applied. **Verify** is amber
  and names the first number that was not found and where it looked.
- *Clause page* (`ui.sheet`): document, page, effective date and clause number, the clause text in
  serif with the words the answer relies on highlighted, and C1, C2... tabs (`st.segmented_control`).
- *Outcome states*: **Working** (found N clauses in N documents with its time, writing, checking),
  **No term found** (grey, "Nothing was guessed", with the number of documents searched and a link
  to add a document), **Verify**, **Failed** (red, "System failure, not a finding", **Try again**
  repeats the same question). A cached answer says it is a repeat and keeps its checks.
- **Download as a note** saves the last check as text (question, answer, terms, seal status).

**Contracts** (`views/contracts.py`, `components/contracts.py`). Steps 1 to 3: the contract (name,
which becomes its ID by `slugify`), the main agreement (file, document type, effective date), and
amendments (file, effective date, and which earlier document each changes). A second mode adds a
document to the contract being checked. Validation is in words: no name, a name already in the
register, no file, a file over 20 MB, a date not written YYYY-MM-DD. **File and index** files the
main agreement first and each amendment after it, passing the user's `effective_date` and `amends`
so a document's date and the document it changes are what the user said, not guessed. The right
column is the **filing log**: file checked, text extracted (pages and how many have a text layer),
split into clauses, embedding, ready, or failed with the reason, each with a clock time. Before
anything is filed it says what will appear there. **Cancel** resets every field (a generation
counter changes all widget keys). When done, "Filed" and a **Check <name>** link.

**Insights** (`views/insights.py`). Window (7 days, 30 days, all) and contract selects; a one-sentence
headline that states the result; the **scorecard** (measure, result with a meter, target, status,
basis); **Figure 1** outcome bar (answered, no term found, system failure); **Figure 2** topics as
bars, with "Not classified" hatched; **Table 2** unanswered questions; failure causes; notes about
how the numbers were made; **Download CSV**. Bars are plain HTML.

**Style** (`frontend/static/app.css`). Tokens on `:root` (paper `#F4F1EA`, sheet `#FFFEFB`, ink,
green `#1D5C47`, amber, red, highlight), no cards, no shadows except the clause page edge, 2 px
radius on buttons only, one serif, one sans, one mono. Fonts are self-hosted woff2 (Source Serif 4
regular and semibold; IBM Plex Sans 400, 500, 600; IBM Plex Mono 400) served through Streamlit's
static serving at `/app/static/`. Streamlit's hidden chrome (header, toolbar, sidebar, input hint)
is removed. The CSS styles `data-testid` and `st-key-*` hooks, never `st-emotion-cache` classes.

**Copy rules** applied everywhere: sentence case; no "chunks" (clauses), no "ok", no raw JSON or
floats; seconds to one decimal (`2.3 s`), percentages whole (`68%`), dates `YYYY-MM-DD` or "28 Oct
2026"; "Not measured" instead of 0 or a dash. One helper module, `components/format.py`.

**Frontend modules**: `components/ui.py` (all HTML builders), `format.py`, `layout.py`, `nav.py`,
`checks.py` (conversation state and `run_check`, which streams the answer and updates a placeholder
as each real step arrives), `contracts.py` (register loading, `file_document` generator, validators),
`api_client.py` (adds `contracts`, `recent_checks`, `common_questions`, `report`, and `upload` with
`display_name`, `effective_date`, `amends`). One conversation per contract is kept in
`st.session_state["conversations"]`.

## 3. Backend

**Streaming detail.** `POST /chat` accepts `strict_scope` (refuse a question that names another
contract; used by Ask and Contracts) and `detail` (send extra events). With `detail` the SSE stream
adds:
- `step` `found` (clauses, documents, ms, cached), `write` (state active or done, ms) and `check`
  (active or done);
- `checks`: `status` (`checked` or `verify`), `answer` (the validated text), `citations`
  (found, total), `numbers` (matched, total, unverified list with the marker), `uncited_sentences`,
  `amendments` (title, clause, the clause it replaces), `terms`, and `clauses` keyed by marker with
  text, document, page, section and highlight spans.
Without `detail` the stream is unchanged, so earlier clients keep working.

**Verification** (`clausecheck/rag/checks.py`). `check_answer` normalises numbers and looks for each
figure in the union of every clause cited anywhere in the answer (a figure cited to C1 that appears
only in C2 is still found, because the answer may combine clauses; an invented figure is not).
Citations are "found" when the marker maps to a retrieved clause. Uncited sentences are counted.
`key_figures` pulls money, percentages and durations (including `(45) days`); bare small numbers and
years are skipped. `highlight_spans` marks the words to highlight. `terms_found` builds the Terms
table deterministically from the cited clauses: `term_name` (clause heading, or "Section X (Name)"),
the figures or first sentence as the value, and a status: "In force since <date>", "Replaced by C#"
or "Amended by <title>"; fragments under 60 characters with no figure are skipped. No extra model
call is made.

**Query service** (`services/query_service.py`). Emits the events above; `strict_scope` and
`OTHER_CONTRACT` implement the refusal; the cache stores the checks and replays them for a repeat
question, and a cache entry without checks is bypassed in detail mode so a repeat is never shown
unverified. Failures are logged with a cause.

**LLM errors** (`llm/client.py`). `LLMError` carries `reasons`; `safe_reason` reduces a provider
error to a short code (type and HTTP status only) so causes can be counted without logging messages
or keys.

**Filing** (`services/ingestion_service.py`, `api/routes/documents.py`). `POST /documents` takes
`effective_date` (validated, 422 if malformed), `amends` (the document it changes) and
`display_name`. Each job writes lines to a `job_steps` table and `GET /documents/jobs/{id}` returns
them as `steps` with a label and a detail line.

**New endpoints** (`api/routes/contracts.py`, `services/contracts_service.py`):
- `GET /contracts`: id, name, document count, kinds, latest effective date, last checked;
- `GET /checks/recent?limit=&contract_id=`: recent questions with contract, outcome and time;
- `GET /contracts/{id}/common-questions?limit=`: most asked questions for that contract;
- `GET /insights/report?days=7|30|all&contract_id=`: the report below.
The `query_log` table is created if it is missing, so a fresh database does not break the register.

**Report** (`services/insights_service.py`): `generated_at`, `window`, `index`, `questions`,
`outcomes`, `scorecard` (key, label, value, target, direction, status, basis), `headline`, `topics`,
`unclassified_share`, `unanswered`, `failures`, `daily`, `notes`. Targets: answered with sources
80%, first words 3.0 s, checked answer 30.0 s, citation accuracy 90%. `status` is `met`, `below`,
`above` or `not_measured`. The headline counts the met measures out of those measured ("One of
three measured targets was met...") and says which missed and by how much. Citation accuracy is read
from the newest `eval/results/*_e2e_heldout.json`; with none it is not measured. The notes say that
the answer rate counts failures (and what it would be without them), that topics come from a keyword
classifier, and that the log does not separate evaluation traffic from live use.

## 4. Data fixes from spec section 7.6

- **Answer rate** is answered over all questions, errors included, with the 80% target shown.
- **Topics**: `services/topics.py` is an ordered keyword list (governing law, insurance, warranty,
  audit and compliance, liability, termination, payment, price, term and renewal, service levels,
  commitments, parties and definitions, and more); first match wins, specific topics before general
  ones; unmatched questions are "Not classified" and shown, not hidden. Tuned on logged questions.
  Not yet re-read by hand against 50 samples as the spec asks.
- **Errors**: 28 failures in the log have no recorded cause (they predate the change); new ones
  record a cause, and the report counts them by cause.
- **Citation accuracy** needs `python -m eval.run_eval` on the held-out set; until then it is "Not
  measured" everywhere.

## 5. Landing page

`site/` is one static page and its assets, for GitHub Pages or any static host:
`index.html` (own title, meta description, Open Graph tags, favicon), `check-record.png` (a real
screenshot of the running app, 1440 px wide), `og-image.png` (the check record, cropped to 1200 by
630), the six fonts and `favicon.png`, and `results.json`. Sections: headline with audience line, the
screenshot, "How an answer is checked" (four numbered steps with the real output in mono), "What it
will not do", "Results so far" and "What's indexed". The Results table is filled in by script from
`results.json`; if the file cannot be loaded it says so and shows nothing. `scripts/
update_site_data.py [--days 7]` rewrites `results.json` from the query log and the held-out eval
(headline, scorecard with basis, index counts, date). Re-run it after the eval or when the log has
grown, and replace `check-record.png` if the interface changes. "Open ClauseCheck" links to
`http://localhost:8501`.

## 6. Configuration

`.streamlit/config.toml` is at the repo root because Streamlit reads it from the directory it is
launched in. It sets `toolbarMode = "minimal"`, `maxUploadSize = 20` (matching the backend's
`MAX_UPLOAD_MB`), `enableStaticServing = true` (serves `frontend/static`), the light theme with the
spec's colours, `baseRadius = "2px"`, and the font faces. `frontend/.streamlit/config.toml` was
deleted (it was ignored when run from the root); `frontend/.streamlit/secrets.toml.example` stays.
`NOTICE` now credits the fonts (SIL OFL 1.1). No new Python dependencies.

## 7. Tests

`pytest -q -m "not targets"`: **375 passed, 4 skipped**; ruff and black are clean.

Replaced: `tests/frontend/test_contract_pages.py`, `test_upload_pages.py` and `test_app_smoke.py` tested
pages that no longer exist (the sidebar picker, the analyser), so they were deleted and replaced.
Kept unchanged: `test_api_client.py`, `test_chat_helpers.py`, `test_dollar_escape.py`,
`test_insights_format.py`, `test_sse_client.py`.

New:
- `tests/frontend/test_pages.py` (AppTest, backend patched): register without a sidebar; backend down;
  empty register; choosing a contract; a scoped check sends `supplier_id`, `strict_scope` and
  `detail` and renders the record; verify names the number; no term found and failure wording; New
  check clears only one contract; filing form validation; the report page; report with no backend.
- `tests/frontend/test_components.py`: formatting helpers, `slugify`, dates, size limit, every
  record kind from events, `file_document` outcomes (done, duplicate, rejected, unreachable, failed,
  timeout), seal, verify note, answer HTML, failure wording, working steps, status line.
- `tests/frontend/conftest.py`: shared fixtures, and clears Streamlit's data caches around each test.
- Backend: `tests/unit/test_checks.py`, `test_topics.py`, `test_llm_error_reasons.py`;
  `tests/integration/test_stream_detail.py`, `test_report_and_register.py`, `test_upload_steps.py`;
  `tests/api/test_register_report_api.py`.

A pitfall found while writing them: AppTest treats `st.html` as an unknown element, so tests read
the element's `proto.body`, and strip the `<style>` block, which names every class.

## 8. How to run it

Same as before: backend `uvicorn clausecheck.api.main:get_app --factory --port 7860`, then
`streamlit run frontend/app.py` from the repo root (so the config and fonts are found), and open
<http://localhost:8501>. Streamlit caches imported modules and the stylesheet, so restart it to see
code or CSS changes. To refresh the landing page figures: `python scripts/update_site_data.py`.

## 9. Differences from the spec

- The Terms found table comes from the cited clauses, not a model.
- No "Full report" link and no feedback thumbs; **Download as a note** replaces **Copy**.
- Streamlit shows its own message for a file over 20 MB, in addition to ours.
- A contract is a supplier in the data model, so there is no separate Supplier column and the
  contract ID is the supplier ID.
- Figures are HTML bars, not Altair.
- The landing page omits the "free server may take a minute to wake" line: nothing is deployed.
- The spec's data section named 593 questions; the live log has grown since (604 at the last run).

## 10. Not done or not checked

- Screen reader behaviour, keyboard order and widths under 1024 px on the Streamlit pages. The
  landing page was checked at 1440 and 390 px (no horizontal scroll).
- The 50-question hand review of "Not classified" topics.
- Running the held-out eval, so citation accuracy has a value.
- Deploying either the app or the landing page.
- `components/chat.py`, `components/insights.py` and `components/sources.py` are no longer used by
  any page; only older helper tests import them. They can be removed with those tests.

## 11. File list

New: `.streamlit/config.toml`, `frontend/static/*` (css, fonts, favicon), `frontend/views/ask.py`,
`frontend/components/{checks,format,layout,nav,ui}.py`, `clausecheck/rag/checks.py`,
`clausecheck/services/{contracts_service,topics}.py`, `clausecheck/api/routes/contracts.py`,
`scripts/update_site_data.py`, `site/*`, and the test files in section 7.
Rewritten: `frontend/app.py`, `views/contracts.py`, `views/insights.py`, `components/contracts.py`.
Changed: `components/api_client.py`, `clausecheck/api/{main,schemas}.py`,
`api/routes/{chat,documents,insights}.py`, `llm/client.py`, `services/{ingestion,insights,query}_service.py`,
`pyproject.toml`, `README.md`, `NOTICE`.
Deleted: `frontend/.streamlit/config.toml`, `frontend/views/analyser.py`,
`frontend/components/conversation.py`, three old frontend tests.
