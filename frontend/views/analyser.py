"""New contract analyser: upload one contract (and its amendments), then ask about it only."""

import streamlit as st
from components.contracts import (
    UPLOAD_TYPES,
    contract_documents,
    describe_documents,
    list_contracts,
    refresh_contracts,
    slugify,
    unlinked_amendments,
    upload_and_wait,
)
from components.conversation import render_conversation
from components.state import init_state

api = init_state()
st.title("New contract analyser")
st.caption(
    "Upload a contract, and its amendments if it has any, then ask questions about that contract "
    "only. It gets its own conversation, separate from every other contract."
)

analysed = st.session_state.get("analysed_contract")

if analysed is None:
    with st.form("analyse"):
        name = st.text_input("Contract name", placeholder="Example: Helixa cloud services 2024")
        main = st.file_uploader("Contract", type=UPLOAD_TYPES)
        amendments = st.file_uploader(
            "Amendments (optional)", type=UPLOAD_TYPES, accept_multiple_files=True
        )
        submitted = st.form_submit_button("Analyse contract")

    if submitted:
        contract_id = slugify(name)
        existing = {c["supplier_id"] for c in list_contracts(api)}
        if not contract_id:
            st.error("Give the contract a name.")
        elif main is None:
            st.error("Choose the contract file.")
        elif contract_id in existing:
            st.error(
                f"A contract called '{name.strip()}' already exists. Choose another name, or open "
                "it on the Chat page."
            )
        else:
            # the original must be indexed before its amendments, or they cannot be linked to it
            files = [(main, "contract")] + [
                (f, "amendment") for f in sorted(amendments, key=lambda f: f.name)
            ]
            problems: list[str] = []
            main_ok = True
            with st.status("Analysing the contract...", expanded=True) as status:
                for file, doc_type in files:
                    st.write(f"Reading {file.name} ({doc_type})...")
                    result = upload_and_wait(
                        api,
                        file.name,
                        file.getvalue(),
                        contract_id,
                        doc_type,
                        display_name=name.strip(),
                    )
                    if result["status"] == "done":
                        st.write(f"Indexed {file.name}.")
                    elif result["status"] == "duplicate" and doc_type == "amendment":
                        st.write(f"{file.name} was already indexed; skipped.")
                    else:
                        reason = result["message"] or result["status"]
                        st.write(f"{file.name} could not be indexed: {reason}")
                        problems.append(f"{file.name}: {reason}")
                        if doc_type == "contract":
                            main_ok = False
                            break  # amendments cannot be linked without the original
                status.update(
                    label="Contract ready" if main_ok else "Something went wrong",
                    state="complete" if main_ok else "error",
                )
            if not main_ok:
                st.error(
                    "The contract was not created. Fix the problem above and try again with a "
                    "different contract name."
                )
            else:
                refresh_contracts()
                st.session_state["analysed_contract"] = contract_id
                st.session_state["active_contract"] = contract_id
                st.session_state["analysis_problems"] = problems
                st.rerun()
else:
    names = {
        c["supplier_id"]: c.get("display_name") or c["supplier_id"] for c in list_contracts(api)
    }
    name = names.get(analysed, analysed)
    st.success(f"**{name}** is ready. Ask about it below, or open it any time on the Chat page.")
    docs = contract_documents(api, analysed)
    with st.expander(f"Documents analysed ({len(docs)})", expanded=True):
        for line in describe_documents(docs):
            st.markdown(f"- {line}")
    for problem in st.session_state.get("analysis_problems", []):
        st.warning(f"Not added: {problem}. You can add it later on the Chat page.")
    for title in unlinked_amendments(docs):
        st.warning(
            f"{title} was not linked to the contract, so answers will not use its changes. "
            "Upload the original agreement first, then the amendment."
        )
    if st.button("Analyse another contract"):
        st.session_state["analysed_contract"] = None
        st.session_state["analysis_problems"] = []
        st.rerun()
    render_conversation(analysed, name, api)
