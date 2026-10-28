"""The page registry: `app.py` registers the pages once, the page scripts link to each other.

A page script run on its own (in a test, say) has no registry, so a link falls back to plain text
instead of failing.
"""

import streamlit as st

PAGES: dict[str, object] = {}


def register(pages: dict[str, object]) -> None:
    PAGES.clear()
    PAGES.update(pages)


def link(key: str, label: str) -> None:
    """A text link to another page, drawn by Streamlit so the session is kept."""
    if key in PAGES:
        st.page_link(PAGES[key], label=label)
    else:
        st.markdown(label)


def go(key: str) -> None:
    """Switch to another page now."""
    if key in PAGES:
        st.switch_page(PAGES[key])
