"""What every page shares: the stylesheet, the masthead with its tabs, and the status line."""

from functools import lru_cache
from pathlib import Path

import streamlit as st

from components import nav, ui
from components.api_client import ApiClient

STATIC = Path(__file__).resolve().parents[1] / "static"
TABS = [("ask", "Ask"), ("contracts", "Contracts"), ("insights", "Insights")]


@lru_cache(maxsize=1)
def _css() -> str:
    return (STATIC / "app.css").read_text()


@st.cache_data(ttl=20, show_spinner=False)
def _frame_data(base_url: str) -> tuple[dict | None, dict | None]:
    """The index status and the report for the status line; `(None, None)` if no backend."""
    api = ApiClient(base_url, timeout=8.0)
    try:
        return api.health(), api.report("7")
    except Exception:
        return None, None


def refresh_frame() -> None:
    """Call after something changed the index or the log, so the masthead is not stale."""
    _frame_data.clear()


def frame(api: ApiClient, active: str) -> tuple[dict | None, dict | None]:
    """Draw the stylesheet, masthead, double rule and status line; return `(health, report)`."""
    st.html(f"<style>{_css()}</style>")
    health, report = _frame_data(api.base_url)
    # wordmark | the three tabs | space | index status, all on one line
    widths = [2.1, *[0.75, 1.15, 1.05], 2.6, 3.6]
    columns = st.columns(widths, vertical_alignment="center")
    columns[0].html(ui.wordmark())
    for column, (key, label) in zip(columns[1:4], TABS, strict=True):
        with column:
            if key == active:  # the current tab is drawn by us: Streamlit does not mark it
                st.html(f'<span class="cc-tab cc-tab--active">{label}</span>')
            else:
                nav.link(key, label)
    last = (report or {}).get("index", {}).get("last_indexed")
    columns[5].html(ui.index_status(health, last))
    st.html(ui.double_rule())
    if report is None:
        st.html(ui.backend_down())
    else:
        st.html(ui.status_line(report))
    return health, report
