import sys
from pathlib import Path
from unittest.mock import patch

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
if str(FRONTEND) not in sys.path:
    sys.path.insert(0, str(FRONTEND))

APP = FRONTEND / "app.py"

HEALTH = {"status": "ok", "documents": 3, "chunks": 40, "suppliers": 2}
CONTRACTS = [
    {
        "id": "orion",
        "name": "Orion",
        "documents": 2,
        "kinds": {"contract": 1, "amendment": 1},
        "latest_effective": "2024-04-01",
        "last_checked": "2026-10-28T05:23:46Z",
    },
    {
        "id": "helixa",
        "name": "Helixa Cloud Systems",
        "documents": 1,
        "kinds": {"contract": 1},
        "latest_effective": "2023-02-01",
        "last_checked": None,
    },
]
DOCS = [
    {"doc_id": "a", "title": "ORION.pdf", "doc_type": "contract", "effective_date": "2023-02-01"},
    {
        "doc_id": "b",
        "title": "AMD1.pdf",
        "doc_type": "amendment",
        "effective_date": "2024-04-01",
        "parent_doc_id": "a",
    },
]


def scorecard(rate=0.68):
    def row(key, label, value, target, direction, status, basis):
        return {
            "key": key,
            "label": label,
            "value": value,
            "target": target,
            "direction": direction,
            "status": status,
            "basis": basis,
        }

    return [
        row("answered_rate", "Answered with sources", rate, 0.8, "min", "below", "412 of 603"),
        row("ttft_ms", "First words", 2300, 2000, "max", "above", "median of 500"),
        row("checked_ms", "Checked", 9000, 12000, "max", "met", "median of 400"),
        row("citation_accuracy", "Citation accuracy", None, 0.95, "min", "not_measured", "none"),
    ]


REPORT = {
    "generated_at": "2026-10-28T06:00:00Z",
    "window": {"days": 7, "label": "Last 7 days"},
    "contract_id": None,
    "contract": None,
    "index": {"contracts": 2, "documents": 3, "last_indexed": "2026-10-27T22:14:20Z"},
    "questions": 603,
    "outcomes": {"answered": 412, "refused": 163, "error": 28},
    "scorecard": scorecard(),
    "headline": "One of three measured targets was met.",
    "topics": [{"topic": "Price", "count": 101}, {"topic": "Not classified", "count": 47}],
    "unclassified_share": 0.08,
    "unanswered": [
        {
            "at": "2026-10-28T05:17:36Z",
            "contract": "Orion",
            "question": "What is the parental leave policy?",
            "outcome": "No term found",
            "kind": "none",
        }
    ],
    "failures": [{"cause": "Cause not recorded", "count": 28}],
    "days_with_data": 2,
    "daily": [],
    "notes": ["Answer rate counts system failures as unanswered."],
}

CHECKS = {
    "status": "checked",
    "answer": "Payment is due within **45 days** of the invoice [C1].",
    "citations": {"found": 1, "total": 1},
    "numbers": {"matched": 1, "total": 1, "unverified": []},
    "uncited_sentences": 0,
    "amendments": [],
    "terms": [
        {
            "term": "Payment terms",
            "value": "45 days",
            "marker": "C1",
            "source": "§4.1, ORION.pdf",
            "status": "In force since 2023-02-01",
            "status_kind": "in_force",
        }
    ],
    "clauses": {
        "C1": {
            "clause_no": "4.1",
            "heading": "Payment",
            "text": "Invoices are payable within 45 days of receipt.",
            "doc_title": "ORION.pdf",
            "highlights": [],
        }
    },
}


class FakeApi:
    """Records what the pages send and returns canned data; patched over ApiClient methods."""

    uploads: list = []

    @staticmethod
    def install(**overrides):
        patches = {
            "health": lambda self: HEALTH,
            "contracts": lambda self: CONTRACTS,
            "documents": lambda self, cid: DOCS,
            "recent_checks": lambda self, limit=5, contract_id=None: [],
            "common_questions": lambda self, cid, limit=5: [],
            "report": lambda self, days="7", contract_id=None: REPORT,
            "new_session": lambda self: "session-1",
        }
        patches.update(overrides)
        from components.api_client import ApiClient

        return [patch.object(ApiClient, name, fn) for name, fn in patches.items()]


@pytest.fixture(autouse=True)
def _fresh_caches():
    """Streamlit's data caches outlive a test; the pages read through them."""
    import streamlit as st

    st.cache_data.clear()
    yield
    st.cache_data.clear()


@pytest.fixture
def run_app():
    """Open the app on a page with the backend patched; patches stay active for the test."""
    from contextlib import ExitStack

    from streamlit.testing.v1 import AppTest

    stack = ExitStack()

    def start(page="ask", **overrides):
        for p in FakeApi.install(**overrides):
            stack.enter_context(p)
        at = AppTest.from_file(str(APP), default_timeout=30)
        at.run()
        if page != "ask":
            at.switch_page(f"views/{page}.py").run()
        return at

    yield start
    stack.close()
