import os

import streamlit as st

from components.api_client import ApiClient


def init_state() -> ApiClient:
    """Set up the session (once per browser tab) and return the API client.

    Every page calls this, so a page can be opened first or run on its own.
    `conversations` holds one conversation per contract: its messages and its backend session,
    so a conversation never mixes contracts.
    """
    if "api_base_url" not in st.session_state:
        try:
            st.session_state["api_base_url"] = st.secrets.get("API_BASE_URL")
        except Exception:
            st.session_state["api_base_url"] = None
        if not st.session_state["api_base_url"]:
            st.session_state["api_base_url"] = os.environ.get(
                "API_BASE_URL", "http://localhost:7860"
            )
    st.session_state.setdefault("conversations", {})  # contract id -> {"messages", "session_id"}
    st.session_state.setdefault("active_contract", None)  # the contract the Chat page shows
    st.session_state.setdefault("analysed_contract", None)  # set by the New contract analyser
    return ApiClient(st.session_state["api_base_url"])
