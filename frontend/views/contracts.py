"""Contracts: add a contract as a numbered filing; the filing log shows each indexing step."""

import datetime as dt

import streamlit as st
from components import nav, ui
from components.contracts import (
    DOC_TYPES,
    MAX_UPLOAD_MB,
    UPLOAD_TYPES,
    contract_documents,
    file_document,
    list_contracts,
    refresh_contracts,
    slugify,
    too_big,
    valid_date,
)
from components.layout import frame, refresh_frame
from components.state import init_state

api = init_state()
frame(api, "contracts")
contracts = list_contracts(api)
by_id = {c["id"]: c for c in contracts}
st.session_state.setdefault("form_gen", 0)  # bumping it gives every field a fresh state (Cancel)
st.session_state.setdefault("amendment_slots", [])
st.session_state.setdefault("slot_counter", 0)
gen = st.session_state["form_gen"]


def key(name: str) -> str:
    return f"{name}-{gen}"


def cancel() -> None:
    st.session_state["form_gen"] += 1
    st.session_state["amendment_slots"] = []
    st.rerun()


# ---- which filing: a new contract, or one more document for the contract being checked ----------

active = st.session_state.get("active_contract")
adding_to = by_id.get(active)
mode = "new"
if adding_to:
    options = ["Add a contract", f"Add a document to {adding_to['name']}"]
    chosen = st.segmented_control(
        "What to file", options, default=options[0], key=key("mode"), label_visibility="collapsed"
    )
    mode = "existing" if chosen == options[1] else "new"

kicker = "Contracts / New filing" if mode == "new" else f"Contracts / {adding_to['name']}"
st.html(
    ui.docket(
        kicker, "Add a contract" if mode == "new" else f"Add a document to {adding_to['name']}"
    )
)
st.html(
    '<div class="cc-lede">File the main agreement with its amendments. Each amendment is linked to '
    "the clause it changes, so checks always report the term in force.</div>"
    if mode == "new"
    else '<div class="cc-lede">File an amendment or another document for this contract. Name the '
    "document an amendment changes, so checks report the term in force.</div>"
)
st.html('<hr class="cc-rule">')

left, right = st.columns([3, 2], gap="large")
with right:
    log_box = st.empty()
    log_box.html(ui.filing_idle())
    done_box = st.container()


def problem(message: str) -> None:
    log_box.html(ui.warning_note(message))


# ---- the form -----------------------------------------------------------------------------------

existing_docs = contract_documents(api, adding_to["id"]) if mode == "existing" else []
doc_choices = {d.get("title") or d["doc_id"]: d["doc_id"] for d in existing_docs}

with left:
    name = ""
    if mode == "new":
        st.html(ui.step_heading(1, "The contract"))
        name = st.text_input(
            "Contract name", key=key("name"), placeholder="Example: Brightline Packaging 2025"
        )

    st.html(
        ui.step_heading(
            2 if mode == "new" else 1,
            "Main agreement" if mode == "new" else "The document",
            f"PDF, DOCX, HTML or TXT, up to {MAX_UPLOAD_MB} MB. Scanned PDFs need a text layer.",
        )
    )
    main = st.file_uploader(
        "Main agreement" if mode == "new" else "Document",
        type=UPLOAD_TYPES,
        key=key("main"),
        label_visibility="collapsed",
    )
    first, second = st.columns(2)
    type_options = list(DOC_TYPES) if mode == "new" else ["Amendment", *DOC_TYPES]
    doc_label = first.selectbox("Document type", type_options, key=key("type"))
    effective = second.text_input("Effective date", key=key("effective"), placeholder="YYYY-MM-DD")
    second.html(
        '<div class="cc-hint">As written in the contract, not today. Leave it empty to read it '
        "from the document.</div>"
    )
    changes = None
    if mode == "existing" and doc_label == "Amendment" and doc_choices:
        changes = st.selectbox("Changes", list(doc_choices), key=key("changes"))

    slots: list[int] = st.session_state["amendment_slots"]
    amendments = []
    if mode == "new":
        st.html(
            ui.step_heading(
                3,
                "Amendments",
                "Add them in the order they were signed. The first changes the main agreement.",
            )
        )
        for position, slot in enumerate(slots, 1):
            row = st.columns([3, 1.4, 2, 0.9], vertical_alignment="bottom")
            file = row[0].file_uploader(
                f"Amendment {position}", type=UPLOAD_TYPES, key=key(f"amd-file-{slot}")
            )
            date = row[1].text_input(
                "Effective", key=key(f"amd-date-{slot}"), placeholder="YYYY-MM-DD"
            )
            earlier = ["The main agreement"] + [f"Amendment {n}" for n in range(1, position)]
            target = row[2].selectbox("Changes", earlier, key=key(f"amd-changes-{slot}"))
            if row[3].button("Remove", key=key(f"amd-remove-{slot}"), type="tertiary"):
                slots.remove(slot)
                st.rerun()
            amendments.append({"file": file, "date": date, "target": earlier.index(target)})
        if st.button("+ Add an amendment", key=key("add-amendment"), type="tertiary"):
            st.session_state["slot_counter"] += 1
            slots.append(st.session_state["slot_counter"])
            st.rerun()

    buttons = st.columns([1.5, 1.2, 5])
    file_clicked = buttons[0].button("File and index", key=key("file"), type="primary")
    if buttons[1].button("Cancel", key=key("cancel")):
        cancel()


# ---- filing -------------------------------------------------------------------------------------


def total_clauses(contract_id: str) -> int:
    return sum(d.get("n_chunks") or 0 for d in contract_documents(api, contract_id))


def file_items(contract_id: str, display_name: str, items: list[dict]) -> bool:
    """File each item in order, redrawing the log on every poll. False if the first one failed."""
    doc_ids: list[str | None] = []
    for index, item in enumerate(items):
        amends = item.get("amends_doc")
        if amends is None and item.get("amends_index") is not None:
            amends = doc_ids[item["amends_index"]] if item["amends_index"] < len(doc_ids) else None
        final = None
        for kind, data in file_document(
            api,
            item["file"].name,
            item["file"].getvalue(),
            contract_id,
            item["doc_type"],
            display_name=display_name,
            effective_date=item["date"].strip() or None,
            amends=amends,
        ):
            if kind == "job":
                final = data
                failed = data["status"] in ("failed", "timeout")
                log_box.html(
                    ui.filing_log(f"{display_name} · {item['file'].name}", data["steps"], failed)
                )
            elif kind == "duplicate":
                problem(f"{item['file'].name} is already filed (the same file). It was skipped.")
                final = {"status": "duplicate", "doc_id": data.get("doc_id")}
            else:
                problem(f"{item['file'].name} could not be filed: {data['message']}")
                final = {"status": "rejected"}
        doc_ids.append((final or {}).get("doc_id"))
        if index == 0 and (final or {}).get("status") not in ("done", "duplicate"):
            return False
    return True


if file_clicked:
    items = []
    error = None
    if mode == "new":
        contract_id, display = slugify(name), name.strip()
        if not contract_id:
            error = "Give the contract a name."
        elif contract_id in by_id:
            error = f"A contract called “{display}” already exists. Choose another name, or add a document to it."
    else:
        contract_id, display = adding_to["id"], adding_to["name"]
    if not error and main is None:
        error = "Choose the file to file."
    if not error:
        picked = [(main, doc_label, effective, None, changes)]
        for amendment in amendments:
            if amendment["file"] is not None:
                picked.append(
                    (amendment["file"], "Amendment", amendment["date"], amendment["target"], None)
                )
        for file, label, date, target, change_title in picked:
            if (message := too_big(file.name, file.size)) or not valid_date(date):
                error = message or f"{file.name}: write the effective date as YYYY-MM-DD."
                break
            items.append(
                {
                    "file": file,
                    "doc_type": (
                        "amendment" if label == "Amendment" else DOC_TYPES.get(label, "contract")
                    ),
                    "date": date,
                    "amends_index": target,
                    "amends_doc": doc_choices.get(change_title) if change_title else None,
                }
            )
    if error:
        problem(error)
    elif file_items(contract_id, display, items):
        refresh_contracts()
        refresh_frame()
        st.session_state["filed"] = {
            "id": contract_id,
            "name": display,
            "documents": len(items),
            "clauses": total_clauses(contract_id),
            "at": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        st.session_state["active_contract"] = contract_id

filed = st.session_state.get("filed")
if filed:
    with done_box:
        st.html(ui.filed_line(filed))
        if st.button(f"Check {filed['name']}", key="check-filed", type="tertiary"):
            st.session_state["active_contract"] = filed["id"]
            nav.go("ask")
