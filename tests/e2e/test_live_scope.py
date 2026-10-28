"""One conversation per contract, against a running backend with a built index.

Skipped unless CLAUSECHECK_E2E=1. Uses the first two contracts the server lists, so it needs an
index with at least two contracts that have different names. It makes two model calls.
"""

import os

import httpx
import pytest

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(os.getenv("CLAUSECHECK_E2E") != "1", reason="set CLAUSECHECK_E2E=1 to run"),
]
API = os.getenv("CLAUSECHECK_API_URL", "http://localhost:7860")


def _two_contracts():
    suppliers = httpx.get(f"{API}/suppliers", timeout=30).json()
    named = [s for s in suppliers if len(s["display_name"]) >= 8]
    for a in named:
        for b in named:
            first_a, first_b = (
                a["display_name"].split()[0].lower(),
                b["display_name"].split()[0].lower(),
            )
            if a is not b and first_a != first_b and first_a not in b["display_name"].lower():
                return a, b
    pytest.skip("the index needs two contracts with different names")


def test_a_question_naming_another_contract_is_refused():
    this, other = _two_contracts()
    body = {
        "question": f"What are the payment terms with {other['display_name']}?",
        "supplier_id": this["supplier_id"],
        "strict_scope": True,
    }
    reply = httpx.post(f"{API}/chat", json=body, timeout=60).json()
    assert reply["outcome"] == "refused" and reply["refusal_reason"] == "other_contract"
    assert this["display_name"] in reply["answer"] and other["display_name"] in reply["answer"]


def test_a_conversation_cannot_be_moved_to_another_contract():
    this, other = _two_contracts()
    session = httpx.post(f"{API}/sessions", timeout=30).json()["session_id"]
    first = httpx.post(
        f"{API}/chat",
        json={
            "question": "What is the term?",
            "supplier_id": this["supplier_id"],
            "session_id": session,
        },
        timeout=60,
    )
    assert first.status_code == 200
    moved = httpx.post(
        f"{API}/chat",
        json={
            "question": "What is the term?",
            "supplier_id": other["supplier_id"],
            "session_id": session,
        },
        timeout=60,
    )
    assert moved.status_code == 409 and "another contract" in moved.json()["detail"]
