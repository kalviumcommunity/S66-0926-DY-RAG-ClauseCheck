import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st
from components.api_client import ApiUnavailable
from components.state import init_state

st.set_page_config(page_title="ClauseCheck", layout="wide")
api = init_state()

st.sidebar.title("ClauseCheck")
try:
    health = api.health()
except ApiUnavailable:
    st.error(
        'ClauseCheck couldn\'t generate an answer right now. This is a system error, not a "not found".'
    )
else:
    if health.get("chunks", 0) == 0:
        st.info("No contracts indexed yet.")
    st.sidebar.caption(
        f"{health.get('documents')} documents · {health.get('chunks')} chunks · "
        f"{health.get('suppliers')} contracts · {health.get('status')}"
    )

pages = [
    st.Page("views/contracts.py", title="Chat", default=True),
    st.Page("views/analyser.py", title="New contract analyser"),
    st.Page("views/insights.py", title="Insights"),
]
st.navigation(pages).run()
