import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st
from components.api_client import ApiClient, ApiUnavailable
from components.chat import StreamCollector, escape_dollars, render_message
from components.insights import render_insights
from components.sidebar import render_sidebar

st.set_page_config(page_title="ClauseCheck", layout="wide")

if "api_base_url" not in st.session_state:
    try:
        st.session_state["api_base_url"] = st.secrets.get("API_BASE_URL")
    except Exception:
        st.session_state["api_base_url"] = None
    if not st.session_state["api_base_url"]:
        st.session_state["api_base_url"] = os.environ.get("API_BASE_URL", "http://localhost:7860")
if "session_id" not in st.session_state:
    st.session_state["session_id"] = None
if "messages" not in st.session_state:
    st.session_state["messages"] = []
if "supplier_filter" not in st.session_state:
    st.session_state["supplier_filter"] = None
if "upload_job_id" not in st.session_state:
    st.session_state["upload_job_id"] = None

api = ApiClient(st.session_state["api_base_url"])

# health check
health_ok = True
health_body = None
try:
    health_body = api.health()
except ApiUnavailable:
    health_ok = False

if not health_ok:
    st.error(
        'ClauseCheck couldn\'t generate an answer right now. This is a system error, not a "not found".'
    )
else:
    if health_body and health_body.get("chunks", 0) == 0:
        st.info("No contracts indexed yet.")

tab_chat, tab_insights = st.tabs(["Chat", "Insights"])

with tab_chat:
    supplier_filter = render_sidebar(api)
    st.session_state["supplier_filter"] = supplier_filter

    for msg in st.session_state["messages"]:
        if msg.get("role") == "assistant":
            render_message(msg, api)
        else:
            st.markdown(escape_dollars(msg.get("content", "")))

    question = st.chat_input("Ask a question")
    if question:
        if st.session_state["session_id"] is None:
            try:
                st.session_state["session_id"] = api.new_session()
            except ApiUnavailable:
                st.session_state["session_id"] = None
        st.session_state["messages"].append({"role": "user", "content": question})
        st.markdown(escape_dollars(question))

        payload = {
            "question": question,
            "session_id": st.session_state["session_id"],
            "supplier_id": st.session_state["supplier_filter"],
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
            st.session_state["messages"].append(msg)
            render_message(msg, api)
        except ApiUnavailable:
            st.error(
                'ClauseCheck couldn\'t generate an answer right now. This is a system error, not a "not found".'
            )

with tab_insights:
    render_insights(api)
