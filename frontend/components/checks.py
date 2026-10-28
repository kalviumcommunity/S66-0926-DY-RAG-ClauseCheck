"""Checks: one conversation per contract, and the code that runs a check and records its outcome.

A conversation is a list of check records. Each record keeps the question, how it ended (`kind`:
`checked`, `verify`, `none`, `failed`, or `plain` when the backend sent no checks), and what the
backend verified, so a record can be drawn again without asking the model again.
"""

import datetime as dt

import streamlit as st

from components import ui
from components.api_client import ApiUnavailable


def get_conversation(contract_id: str) -> dict:
    """The conversation for one contract: its checks and its backend session."""
    return st.session_state["conversations"].setdefault(
        contract_id, {"checks": [], "session_id": None}
    )


def reset_conversation(contract_id: str) -> None:
    """Start over for this contract only; every other contract keeps its checks."""
    st.session_state["conversations"].pop(contract_id, None)


def record_from_events(question: str, events: list[tuple[str, dict]], asked_at: str) -> dict:
    """Turn the events of one stream into a check record. Pure, so it can be tested without a UI."""
    tokens = "".join(d.get("text", "") for e, d in events if e == "token")
    checks = next((d for e, d in events if e == "checks"), None)
    done = next((d for e, d in events if e == "done"), None)
    failed = done is None or done.get("outcome") == "error" or any(e == "error" for e, _ in events)
    record = {
        "question": question,
        "asked_at": asked_at,
        "timings": (done or {}).get("timings"),
        "cached": bool((done or {}).get("cached")),
        "query_id": next((d.get("query_id") for e, d in events if e == "meta"), None),
    }
    if failed:
        return {**record, "kind": "failed"}
    if done.get("outcome") == "refused":
        # The wording of a refusal belongs to the backend only when it explains something specific.
        specific = done.get("refusal_reason") == "other_contract"
        return {**record, "kind": "none", "message": tokens if specific else None}
    if checks is None:
        return {**record, "kind": "plain", "text": tokens}
    kind = "checked" if checks["status"] == "checked" else "verify"
    return {**record, "kind": kind, "checks": checks, "terms": checks["terms"]}


def run_check(api, contract_id: str, contract_name: str, question: str) -> dict:
    """Ask `question` about one contract, showing the real steps as they happen.

    The search is limited to the contract and a question that names another contract is refused;
    `detail` asks the backend for the step and check events the screen shows.
    """
    from components.sse_client import stream_chat

    conv = get_conversation(contract_id)
    if conv["session_id"] is None:
        try:
            conv["session_id"] = api.new_session()
        except ApiUnavailable:
            conv["session_id"] = None
    payload = {
        "question": question,
        "session_id": conv["session_id"],
        "supplier_id": contract_id,
        "strict_scope": True,
        "detail": True,
    }
    asked_at = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    holder = st.empty()
    steps: dict[str, dict] = {}
    events: list[tuple[str, dict]] = []
    holder.html(ui.working_record(question, contract_name, steps))
    try:
        for event, data in stream_chat(st.session_state["api_base_url"], payload):
            events.append((event, data))
            if event == "step":
                steps[data["id"]] = data
                holder.html(ui.working_record(question, contract_name, steps))
    except (ApiUnavailable, OSError):
        events.append(("error", {}))
    except Exception:  # a dropped connection or a malformed stream is a failure, not a finding
        events.append(("error", {}))
    holder.empty()
    return record_from_events(question, events, asked_at)
