import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st
from components import nav

st.set_page_config(
    page_title="ClauseCheck",
    page_icon=str(Path(__file__).parent / "static" / "favicon.png"),
    layout="wide",
    initial_sidebar_state="collapsed",
)

pages = {
    "ask": st.Page("views/ask.py", title="Ask", default=True, url_path="ask"),
    "contracts": st.Page("views/contracts.py", title="Contracts", url_path="contracts"),
    "insights": st.Page("views/insights.py", title="Insights", url_path="insights"),
}
nav.register(pages)
# the masthead draws its own tabs, so Streamlit's menu stays hidden and there is no sidebar
st.navigation(list(pages.values()), position="hidden").run()
