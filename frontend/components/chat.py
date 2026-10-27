import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from clausecheck.rag.generator import REFUSAL_TEXT

REFUSAL_COPY = REFUSAL_TEXT


class StreamCollector:
    def __init__(self, events):
        self._events = list(events)
        self._tokens: list[str] = []
        self._meta: dict = {}
        self._sources: list = []
        self._citations: list = []
        self._outcome: str = "answered"
        self._refusal_reason: str | None = None
        self._query_id: str | None = None
        self._unsupported: bool = False
        self._error: str | None = None
        self._done = False

    def __iter__(self):
        for typ, data in self._events:
            if typ == "meta":
                self._meta = data
                self._query_id = data.get("query_id")
            elif typ == "sources":
                self._sources = data.get("sources", [])
            elif typ == "token":
                text = data.get("text", "")
                self._tokens.append(text)
                yield text
            elif typ == "citations":
                self._citations = data.get("citations", [])
                self._unsupported = data.get("unsupported", False)
            elif typ == "error":
                self._error = data.get("message")
            elif typ == "done":
                self._outcome = data.get("outcome", self._outcome)
                self._refusal_reason = data.get("refusal_reason")
                self._done = True
        if self._outcome == "refused" and self._refusal_reason == "no_citations":
            self._content = REFUSAL_COPY
        else:
            self._content = "".join(self._tokens)

    @property
    def message(self) -> dict:
        return {
            "role": "assistant",
            "content": self._content if hasattr(self, "_content") else "".join(self._tokens),
            "citations": self._citations,
            "sources": self._sources,
            "outcome": self._outcome,
            "refusal_reason": self._refusal_reason,
            "query_id": self._query_id,
            "unsupported": self._unsupported,
            "error": self._error,
        }


def render_message(msg, api):
    outcome = msg.get("outcome")
    if outcome == "refused":
        st.info(msg.get("content", ""))
    elif outcome == "error":
        st.error(msg.get("error") or "Something went wrong.")
    else:
        st.markdown(msg.get("content", ""))
    if msg.get("unsupported"):
        st.warning(
            "A number in this answer wasn't found in the cited clause. Check it before acting."
        )
    if outcome not in ("refused", "error"):
        # sources + feedback
        try:
            from components.sources import render_sources

            render_sources(msg.get("citations", []), msg.get("sources", []), api)
        except Exception:
            pass
        qid = msg.get("query_id")
        if qid:
            c1, c2 = st.columns(2)
            if c1.button("👍", key=f"up-{qid}"):
                try:
                    api.feedback(qid, "up")
                except Exception:
                    pass
            if c2.button("👎", key=f"down-{qid}"):
                try:
                    api.feedback(qid, "down")
                except Exception:
                    pass
