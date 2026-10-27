"""Runs against a deployed backend. Skipped unless CLAUSECHECK_E2E=1 and CLAUSECHECK_API_URL are set."""
import os

import httpx
import pytest

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(os.getenv("CLAUSECHECK_E2E") != "1", reason="set CLAUSECHECK_E2E=1 to run"),
]
API = os.getenv("CLAUSECHECK_API_URL", "http://localhost:7860")
QUESTION = os.getenv("CLAUSECHECK_E2E_QUESTION", "What are the payment terms?")


def test_health_ok():
    body = httpx.get(f"{API}/health", timeout=30).json()
    assert body["status"] == "ok" and body["chunks"] > 0


def test_chat_answers_or_refuses_cleanly():
    body = httpx.post(f"{API}/chat", json={"question": QUESTION}, timeout=60).json()
    assert body["outcome"] in {"answered", "refused"}
    if body["outcome"] == "answered":
        assert body["citations"]
