"""Chat page: pick one contract and talk about that contract only."""

import streamlit as st
from components.contracts import (
    DOC_TYPES,
    UPLOAD_TYPES,
    contract_documents,
    describe_documents,
    list_contracts,
    refresh_contracts,
    upload_and_wait,
)
from components.conversation import get_conversation, render_conversation, reset_conversation
from components.state import init_state

api = init_state()
contracts = list_contracts(api)
names = {c["supplier_id"]: c.get("display_name") or c["supplier_id"] for c in contracts}

if not names:
    st.info("There are no contracts yet. Create one under **New contract analyser**.")
    st.stop()

ids = list(names)
active = st.session_state.get("active_contract")
choice = st.sidebar.selectbox(
    "Contract",
    ids,
    index=ids.index(active) if active in ids else None,
    format_func=names.get,
    placeholder="Choose a contract",
)
st.session_state["active_contract"] = choice

if choice is None:
    st.info(
        "Choose a contract in the sidebar. Each contract has its own conversation, "
        "so questions never mix contracts."
    )
    st.stop()

name = names[choice]
st.title(name)
if flash := st.session_state.pop("flash", None):
    st.success(flash)

if st.sidebar.button("New conversation", help=f"Start over for {name} only"):
    reset_conversation(choice)
    st.rerun()

docs = contract_documents(api, choice)
with st.expander(f"Documents in this contract ({len(docs)})"):
    for line in describe_documents(docs):
        st.markdown(f"- {line}")

with st.expander("Add a document to this contract"):
    st.caption(
        "For an amendment, upload the original agreement first. The amendment is then linked "
        "to it automatically and answers use the amended terms."
    )
    with st.form(f"add-document-{choice}", clear_on_submit=True):
        file = st.file_uploader("File", type=UPLOAD_TYPES)
        doc_type = st.selectbox("Document type", DOC_TYPES)
        submitted = st.form_submit_button("Upload")
    if submitted and file is None:
        st.warning("Choose a file first.")
    elif submitted and file is not None:
        with st.spinner(f"Indexing {file.name}..."):
            result = upload_and_wait(api, file.name, file.getvalue(), choice, doc_type)
        if result["status"] == "done":
            refresh_contracts()
            # reload so the document list above shows the new file; the message survives the reload
            st.session_state["flash"] = f"{file.name} was added to {name}."
            st.rerun()
        elif result["status"] == "duplicate":
            st.warning(result["message"])
        else:
            st.error(f"{file.name} could not be added: {result['message'] or result['status']}.")

get_conversation(choice)  # makes sure this contract has its own conversation
render_conversation(choice, name, api)
