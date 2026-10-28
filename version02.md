# Version 2: one conversation per contract, and a New contract analyser

Work done after `v1.0.0`. The fixes that led to version 1 are in [debugging.md](debugging.md); this
file covers only what came after it.

## Why

- A conversation could cover any contract: the sidebar had an "All suppliers" option, and a
  question that named another company switched the search to it. Screenshots showed one chat
  answering about Orion, Helixa and Sapphire in turn.
- There was no separate place to create a contract and ask about just that contract.

A screen-only fix was not enough. With the search limited to one contract, a question that names
another one ("payment terms with Orion" inside the Sapphire chat) would be answered from Sapphire's
clauses and read as if it were about Orion. So the limit is also enforced in the backend.

## What changed

### Backend
- **`strict_scope` on chat requests** (`ChatRequest.strict_scope`, default false). When true and a
  `supplier_id` is given, `QueryService.answer` and `QueryService.stream` refuse a question that
  names another contract, before any search or model call: outcome `refused`, reason
  `other_contract`, and a message naming both contracts ("This conversation is about Sapphire. To
  ask about Orion, open that contract and ask there."). The refusal is logged, never cached and not
  added to the conversation history. Supporting code: `SupplierDetector.other_supplier` and
  `SupplierDetector.display_name`.
- **409 for a moved conversation.** `/chat` and `/chat/stream` return 409 if a request moves an
  existing conversation to a different contract (`SessionStore.scope_of`). For streaming the check
  runs before the stream starts, while a status code can still be sent.
- **`display_name` on upload.** `POST /documents` takes an optional `display_name`, used when an
  upload creates a contract. An existing contract keeps its name and aliases. The route and the
  chat route pass the new options only when they are set, so a service without them keeps working.
- **Why `strict_scope` is opt-in:** `test_supplier_filter_overrides_detection` (PR 13) requires that a
  plain supplier filter overrides name detection. That test is unchanged; the new pages turn
  `strict_scope` on.

### Frontend
`frontend/app.py` now uses `st.navigation`; the pages are in `frontend/views/`.

- **Chat** (`views/contracts.py`)
  - A required contract picker. There is no "All suppliers" option and no chat box until a
    contract is chosen.
  - One conversation and one backend session per contract. Switching contracts switches
    conversations, and nothing carries over.
  - "Documents in this contract" lists each file, its date and which agreement an amendment changes.
  - "Add a document to this contract" uploads another file to it (for example a later amendment).
  - "New conversation" resets the current contract only.
- **New contract analyser** (`views/analyser.py`)
  - Fields: contract name, contract file, optional amendments.
  - The original is indexed first and each amendment after it, so every amendment is linked to the
    agreement it changes and answers use the amended terms.
  - It then shows a summary of the documents, warns about any amendment that did not link, and opens
    a chat about that contract. A name already in use is rejected. If an amendment fails, the
    contract is still created and the page says which file was not added.
- **Insights** (`views/insights.py`): unchanged, moved into a page.
- **Shared code:** `components/state.py` (session setup), `components/contracts.py` (contract list,
  slug, upload-and-wait helpers) and `components/conversation.py` (one conversation per contract).
  `components/api_client.py` gained `documents(supplier_id)` and a `display_name` option on
  `upload`.
- **Removed:** `components/sidebar.py` (the supplier box and the Supplier ID upload form).

### Documentation
- `README.md`: the description, "Using the app" (three pages and how each works), the folder map,
  one troubleshooting row, and the known limits (the "one conversation can switch between contracts"
  limit is gone). In the second pass: the "How an answer is produced" diagram and a note on how the
  pages send the chosen contract; and a rewritten "Tests and evaluation" section with a table of the
  five test folders and their counts, how to run one folder, how to run the end-to-end tests, and
  why `test_corpus_targets` is left out.

## Tests

304 passed, 4 skipped (the end-to-end tests that need a running backend); `ruff` and `black` clean.
Before this work: 262 passed, 2 skipped. By folder: unit 212, integration 30, api 27, frontend 35.

Added:
- `tests/integration/test_contract_scope.py`: strict scope refuses another contract (not cached, not
  in the history, generator and search not called), still answers its own contract and follow-ups,
  streams the refusal in the usual event order, and the plain filter still overrides detection.
- `tests/unit/test_contract_scope_helpers.py`: `other_supplier`, `display_name`, `scope_of`.
- `tests/api/test_contract_scope_api.py`: 409 for a moved conversation (both endpoints), the allowed
  cases, and `strict_scope` and `display_name` passed on only when set.
- `tests/integration/test_upload_display_name.py`: a new contract gets the typed name; an existing
  one keeps its own.
- `tests/frontend/test_contract_pages.py`: slug, document descriptions, every outcome of
  `upload_and_wait`, the job timeout, no chat until a contract is chosen, two contracts keep
  separate conversations and sessions, "New conversation" resets only one, and an empty server reply
  is shown as an error and not saved.

Added in a second pass, to cover the whole system and the upload forms:
- `tests/frontend/test_upload_pages.py` (11 tests): the New contract analyser form, driven with
  Streamlit's test tool and a stand-in API. The original is indexed first and the amendments after
  it by file name, under one ID and the typed name; the new contract gets its own conversation
  limited to it; "Analyse another contract" brings the form back; blank name, missing file and a
  name already in use are rejected with nothing sent; a failed original means nothing else is
  uploaded and no contract is made; a failed amendment still makes the contract and says which file
  is missing; an unlinked amendment is flagged. On the Chat page: "Add a document to this
  contract" uploads to the chosen contract and confirms, asks for a file when there is none, and
  reports a duplicate and a failed upload. This closes the gap noted under "Not checked" below:
  the forms are now exercised through the page itself, not only through the helper.
- `tests/unit/test_eval_cli.py` (5 tests): runs `python -m eval.run_eval` as a real command. The
  earlier `NameError` (the `__main__` guard sat above the stage functions) never showed in tests
  that import the module.
- `tests/unit/test_settings_defaults.py` (3 tests): locks the tuned values (`RELEVANCE_THRESHOLD`
  -8.0, `LLM_PRIMARY` groq), checks that every value in `.env.example` equals the code default, and
  that the keys are empty there.
- `tests/e2e/test_live_scope.py` (2 tests, opt-in): against a running backend, a question naming
  another contract is refused and a conversation cannot be moved to another contract.

Checks on the new tests:
- **They catch breakage.** Temporarily removing the amendment sort in the analyser made
  `test_analysing_indexes_the_original_first_then_each_amendment` fail; sending no contract with
  each question made two conversation tests fail. Both files were restored afterwards.
- **The end-to-end tests pass for real:** `CLAUSECHECK_E2E=1 CLAUSECHECK_API_URL=http://localhost:7860
  pytest tests/e2e -q` gave 4 passed against the running backend (the two existing tests and the
  two new ones).
- **One mistake along the way:** an early version of `test_upload_pages.py` patched `time.sleep` for
  the whole process, which made Streamlit's own wait loop spin and the first test time out after 30
  seconds. The patch was not needed (the stand-in jobs finish at once) and was removed.

Changed: `tests/frontend/test_app_smoke.py` asserted the old two-tab layout (`len(at.tabs) == 2`).
It now asserts the Chat page's "no contracts" state with the backend down.

## Checked end to end

On a throwaway backend (its own port, index and upload folder), so the real index and uploads were
not touched:

| Step | Result |
|---|---|
| Upload a contract, then its amendment, with the helper the analyser page calls | both indexed; the amendment typed `amendment`, dated 2025-07-01 and linked to the agreement |
| Ask "payment terms" in the Acme chat | "Net 60", replacing "Net 30" |
| Ask the same in the Zeta chat | "Net 15", no leakage from Acme |
| Ask about Zeta inside the Acme chat | refused (`other_contract`), in normal and streaming mode |
| Move a conversation bound to Acme to Zeta | HTTP 409, in both modes |

On the real backend, the same refusal was seen between Sapphire and Orion, and each contract's own
questions still answered. Streamlit was also started against the real backend and served its page.

## Not checked, and limits

- **Not checked:** the pages in a real browser. The page logic, including both upload forms, is
  covered by Streamlit's `AppTest`, which does not render or run a real browser or a real file picker.
- A contract is a supplier ID plus its documents, so two unrelated agreements under one ID share a
  contract.
- A company name mentioned in passing in a question can trigger the other-contract refusal.
- If the main file of a new contract fails to index, its name may be taken and a different name is
  needed.
- Conversation history is still kept in memory, so it is lost when the backend restarts.

## Files

Changed: `README.md`, `clausecheck/api/routes/chat.py`, `clausecheck/api/routes/documents.py`,
`clausecheck/api/schemas.py`, `clausecheck/rag/supplier_detector.py`,
`clausecheck/services/ingestion_service.py`, `clausecheck/services/query_service.py`,
`clausecheck/services/sessions.py`, `frontend/app.py`, `frontend/components/api_client.py`,
`tests/frontend/test_app_smoke.py`.

Added: `frontend/views/` (`contracts.py`, `analyser.py`, `insights.py`),
`frontend/components/state.py`, `frontend/components/contracts.py`,
`frontend/components/conversation.py`, the test files above (nine new files in all), and this file.

Removed: `frontend/components/sidebar.py`.
