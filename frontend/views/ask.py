"""Ask: choose a contract from the register, then check terms against it, one record per check."""

from pathlib import Path

import streamlit as st
from components import nav, ui
from components.checks import get_conversation, reset_conversation, run_check
from components.contracts import contract_documents, list_contracts
from components.layout import frame, refresh_frame
from components.state import init_state

STARTERS = [
    "What are the payment terms?",
    "Who are the parties to the agreement?",
    "When does the agreement end, and can it renew?",
    "What is the liability cap?",
    "What notice is needed to terminate?",
]

api = init_state()
frame(api, "ask")
contracts = list_contracts(api)
by_id = {c["id"]: c for c in contracts}

# a link such as ?contract=orion opens that contract
wanted = st.query_params.get("contract")
if wanted in by_id and st.session_state.get("active_contract") is None:
    st.session_state["active_contract"] = wanted


def choose(contract_id: str | None) -> None:
    st.session_state["active_contract"] = contract_id
    if contract_id:
        st.query_params["contract"] = contract_id
    elif "contract" in st.query_params:
        del st.query_params["contract"]
    st.rerun()


def show_register() -> None:
    st.html(ui.docket("Checking", "Choose a contract"))
    if not contracts:
        st.html(
            '<div class="cc-lede">There are no contracts yet. File the first one under '
            "Contracts, then come back here to check its terms.</div>"
        )
        nav.link("contracts", "Add a contract")
        return
    query = st.text_input(
        "Find a contract",
        key="register_search",
        placeholder="Find a contract by name or document ID",
        label_visibility="collapsed",
    ).strip()
    st.html(
        '<div class="cc-lede">Each check runs against one contract and its amendments only. Answers '
        "quote the clause they come from, and every quote is checked against the document before "
        "you see it.</div>"
    )
    left, right = st.columns([3, 1.3], gap="large")
    with left:
        needle = query.lower()
        matches = [c for c in contracts if needle in c["name"].lower() or needle in c["id"].lower()]
        show_all = st.session_state.get("register_all", False) or bool(needle)
        shown = matches if show_all else matches[:6]
        if not matches:
            st.html(
                f'<div class="cc-fine">No contract matches “{ui.esc(query)}”. Clear the search, or '
                "add the contract under Contracts.</div>"
            )
        else:
            head_cell, head_end = st.columns([10, 1.3])
            head_cell.html(ui.register_head())
            head_end.html('<div class="cc-reg-head cc-end">&nbsp;</div>')
        for no, contract in enumerate(shown, 1):
            row, pick = st.columns([10, 1.3], vertical_alignment="center")
            row.html(ui.register_row(no, contract))
            if pick.button("Check", key=f"pick-{contract['id']}", type="tertiary"):
                choose(contract["id"])
        if matches:
            note = f"{len(shown)} of {len(contracts)}" + (
                "" if show_all else ", most recently checked first"
            )
            st.html(f'<div class="cc-reg-foot">{note}</div>')
            if not show_all and len(matches) > len(shown):
                if st.button(f"Show all {len(matches)}", key="register_show_all", type="tertiary"):
                    st.session_state["register_all"] = True
                    st.rerun()
            nav.link("contracts", "Add a contract")
    with right:
        try:
            recent = api.recent_checks(5)
        except Exception:
            recent = []
        st.html(ui.recent_checks(recent))


def note_text(rec: dict, name: str) -> str:
    """A check as plain text, for a download: question, answer, terms and sources."""
    lines = [f"{name}", f"Q: {rec['question']}", "", f"A: {rec['checks']['answer']}", ""]
    lines += [
        f"- {t['term']}: {t['value']} ({t['marker']} {t['source']}; {t['status']})"
        for t in rec.get("terms", [])
    ]
    status = "Checked" if rec["kind"] == "checked" else "Verify before relying on it"
    return "\n".join(lines + ["", f"{status}. Checked by ClauseCheck against the contract text."])


def show_contract(contract: dict) -> None:
    contract_id, name = contract["id"], contract["name"]
    docs = contract_documents(api, contract_id)
    conv = get_conversation(contract_id)
    checks = conv["checks"]
    ids = [Path(d.get("title") or d["doc_id"]).stem for d in docs][:3]

    top = st.columns([6, 1.5, 1.7, 1.2], vertical_alignment="bottom")
    top[0].html(ui.docket("Checking", name, ids))
    if top[1].button("Change contract", key="change-contract", type="tertiary"):
        choose(None)
    with top[2].popover(f"Documents ({len(docs)})"):
        st.html(ui.documents_list(docs))
        nav.link("contracts", f"Add a document to {name}")
    if top[3].button("New check", key="new-check"):
        reset_conversation(contract_id)
        st.rerun()
    st.html('<hr class="cc-hair" style="margin-top:12px">')

    left, right = st.columns([3, 2], gap="large")
    with left:
        records_box, work_box, form_box = st.container(), st.container(), st.container()

    question = None
    with form_box:
        with st.form(f"ask-{contract_id}", clear_on_submit=True, border=False):
            field, submit = st.columns([8, 1.3], vertical_alignment="bottom")
            label = f"Ask a follow-up about {name}" if checks else f"Ask about {name}"
            text = field.text_input(
                label,
                key=f"question-{contract_id}",
                placeholder=label,
                label_visibility="collapsed",
            )
            if submit.form_submit_button("Check", type="primary") and text.strip():
                question = text.strip()

    with records_box:
        if not checks:
            try:
                common = api.common_questions(contract_id, 5)
            except Exception:
                common = []
            heading = f"Asked most often about {name}" if common else "Common questions"
            st.html(f'<div class="cc-kicker">{ui.esc(heading)}</div>')
            for i, suggestion in enumerate((common or STARTERS)[:5]):
                if st.button(suggestion, key=f"suggest-{contract_id}-{i}", type="tertiary"):
                    question = suggestion
        for number, rec in enumerate(checks, 1):
            st.html(ui.check_record(rec, number, name, len(docs)))
            if rec["kind"] == "failed" and number == len(checks):
                if st.button("Try again", key=f"retry-{contract_id}-{number}"):
                    checks.pop()
                    question = rec["question"]
            if rec["kind"] == "none" and number == len(checks):
                nav.link("contracts", f"Add a document to {name}")
        last = checks[-1] if checks else None
        if last and last["kind"] in ("checked", "verify"):
            st.download_button(
                "Download as a note",
                note_text(last, name),
                file_name=f"{contract_id}-check-{len(checks)}.txt",
                key=f"note-{contract_id}-{len(checks)}",
                type="tertiary",
            )

    if question:
        with work_box:
            checks.append(run_check(api, contract_id, name, question))
        refresh_frame()
        st.rerun()

    with right:
        answered = [c for c in checks if c["kind"] in ("checked", "verify")]
        if not answered:
            st.html(ui.sheet(None, None))
        else:
            clauses = answered[-1]["checks"]["clauses"]
            markers = list(clauses)
            pick = st.segmented_control(
                "Source",
                markers,
                default=markers[0],
                key=f"source-{contract_id}-{len(checks)}",
                label_visibility="collapsed",
                format_func=lambda m: f"{m} · §{clauses[m].get('clause_no') or '-'}",
            )
            marker = pick or markers[0]
            st.html(ui.sheet(clauses[marker], marker))


active = st.session_state.get("active_contract")
if active in by_id:
    show_contract(by_id[active])
else:
    if active:
        st.session_state["active_contract"] = None
    show_register()
