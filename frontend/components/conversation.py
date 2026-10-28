import streamlit as st

from components.api_client import ApiUnavailable
from components.chat import StreamCollector, escape_dollars, render_message

BACKEND_ERROR = (
    'ClauseCheck couldn\'t generate an answer right now. This is a system error, not a "not found".'
)


def get_conversation(contract_id: str) -> dict:
    """The conversation for one contract; each contract has its own messages and backend session."""
    return st.session_state["conversations"].setdefault(
        contract_id, {"messages": [], "session_id": None}
    )


def reset_conversation(contract_id: str) -> None:
    """Start over for this contract only; other contracts keep their conversations."""
    st.session_state["conversations"].pop(contract_id, None)


def render_conversation(contract_id: str, display_name: str, api) -> None:
    """Show the conversation for one contract and answer new questions about that contract only."""
    conv = get_conversation(contract_id)
    for msg in conv["messages"]:
        if msg.get("role") == "assistant":
            render_message(msg, api)
        else:
            st.markdown(escape_dollars(msg.get("content", "")))

    question = st.chat_input(f"Ask about {display_name}", key=f"chat-input-{contract_id}")
    if not question:
        return
    if conv["session_id"] is None:
        try:
            conv["session_id"] = api.new_session()
        except ApiUnavailable:
            conv["session_id"] = None
    st.markdown(escape_dollars(question))

    payload = {
        "question": question,
        "session_id": conv["session_id"],
        "supplier_id": contract_id,  # the search is limited to this contract
        "strict_scope": True,  # and a question that names another contract is refused
    }
    try:
        from components.sse_client import stream_chat

        collector = StreamCollector(stream_chat(st.session_state["api_base_url"], payload))
        # stream into a placeholder, then clear it: render_message draws the final copy
        holder = st.empty()
        with holder.container():
            st.write_stream(collector)
        holder.empty()
        # the collector keeps the raw text; the stream above showed an escaped copy
        msg = collector.message
    except ApiUnavailable:
        st.error(BACKEND_ERROR)
        return
    if not msg.get("content") and not msg.get("error"):
        st.error(BACKEND_ERROR)  # the server sent no answer at all (for example a rejected request)
        return
    conv["messages"].append({"role": "user", "content": question})
    conv["messages"].append(msg)
    render_message(msg, api)
