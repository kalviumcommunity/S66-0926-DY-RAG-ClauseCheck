from pathlib import Path
from unittest.mock import patch

import pytest
from components.api_client import ApiClient, ApiUnavailable
from components.chat import StreamCollector
from components.contracts import (
    _load_contracts,
    describe_documents,
    slugify,
    unlinked_amendments,
    upload_and_wait,
    wait_for_job,
)
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[2] / "frontend" / "app.py"
SUPPLIERS = [
    {"supplier_id": "S-ACME", "display_name": "Acme Corp", "aliases": []},
    {"supplier_id": "S-BETA", "display_name": "Beta Industries", "aliases": []},
]
HEALTH = {"status": "ok", "documents": 2, "chunks": 10, "suppliers": 2}


def test_slugify_makes_an_id_from_a_name():
    assert slugify("Q3 Supply Deal (2025)") == "q3-supply-deal-2025"
    assert slugify("  Helixa -- Cloud  ") == "helixa-cloud"
    assert slugify("???") == ""


DOCS = [
    {"doc_id": "a", "title": "SERVICE.pdf", "doc_type": "contract", "effective_date": "2023-02-01"},
    {
        "doc_id": "b",
        "title": "AMD1.pdf",
        "doc_type": "amendment",
        "effective_date": "2024-04-01",
        "parent_doc_id": "a",
    },
    {"doc_id": "c", "title": "LOOSE.pdf", "doc_type": "amendment", "effective_date": ""},
]


def test_documents_are_described_with_what_an_amendment_changes():
    lines = describe_documents(DOCS)
    assert any("AMD1.pdf" in line and "amends SERVICE.pdf" in line for line in lines)
    assert any("LOOSE.pdf" in line and "not linked to an agreement" in line for line in lines)
    assert unlinked_amendments(DOCS) == ["LOOSE.pdf"]


class FakeApi:
    def __init__(self, upload=None, jobs=()):
        self._upload, self._jobs = upload, list(jobs)

    def upload(self, filename, content, contract_id, doc_type, display_name=None):
        if isinstance(self._upload, Exception):
            raise self._upload
        return self._upload

    def job(self, job_id):
        return self._jobs.pop(0)


def _wait(api):
    return upload_and_wait(api, "a.pdf", b"x", "c1", "contract", sleep=lambda s: None)


def test_upload_and_wait_reports_each_outcome():
    done = FakeApi({"job_id": "j"}, [{"status": "running"}, {"status": "done", "doc_id": "d1"}])
    assert _wait(done) == {"status": "done", "message": "", "doc_id": "d1"}
    failed = FakeApi({"job_id": "j"}, [{"status": "failed", "error": "EmptyDocumentError"}])
    assert (
        _wait(failed)["status"] == "failed"
        and "Empty"
        in _wait(FakeApi({"job_id": "j"}, [{"status": "failed", "error": "EmptyDocumentError"}]))[
            "message"
        ]
    )
    assert _wait(FakeApi({"duplicate": True, "doc_id": "d0"}))["status"] == "duplicate"
    assert _wait(FakeApi(ValueError("file too large")))["status"] == "rejected"
    assert _wait(FakeApi(ApiUnavailable("down")))["status"] == "error"


def test_wait_for_job_gives_up_after_the_timeout():
    api = FakeApi(jobs=[{"status": "running"}] * 5)
    assert wait_for_job(api, "j", timeout=0, sleep=lambda s: None) == {"status": "timeout"}


@pytest.fixture
def app():
    _load_contracts.clear()
    sessions = iter(f"session-{i}" for i in range(1, 50))
    payloads = []

    def fake_stream(base_url, payload, **kw):
        payloads.append(payload)
        yield "meta", {"query_id": f"q{len(payloads)}", "supplier_id": payload["supplier_id"]}
        yield "sources", {"sources": []}
        yield "token", {"text": f"Answer {len(payloads)} [C1]."}
        yield "citations", {"citations": [], "unsupported": False}
        yield "done", {"outcome": "answered", "refusal_reason": None, "timings": {}}

    with (
        patch.object(ApiClient, "health", lambda self: HEALTH),
        patch.object(ApiClient, "suppliers", lambda self: SUPPLIERS),
        patch.object(ApiClient, "documents", lambda self, supplier_id: []),
        patch.object(ApiClient, "new_session", lambda self: next(sessions)),
        patch("components.sse_client.stream_chat", fake_stream),
    ):
        at = AppTest.from_file(str(APP), default_timeout=30)
        at.run()
        at.payloads = payloads
        yield at
    _load_contracts.clear()


def test_no_chat_until_a_contract_is_chosen(app):
    assert not app.exception
    assert [o for o in app.sidebar.selectbox[0].options] == ["Acme Corp", "Beta Industries"]
    assert app.sidebar.selectbox[0].value is None
    assert len(app.chat_input) == 0
    assert any("Choose a contract" in i.value for i in app.info)


def test_each_contract_has_its_own_separate_conversation(app):
    app.sidebar.selectbox[0].select("S-ACME").run()
    assert app.chat_input[0].placeholder == "Ask about Acme Corp"
    app.chat_input[0].set_value("What are the payment terms?").run()
    assert not app.exception

    app.sidebar.selectbox[0].select("S-BETA").run()
    assert app.chat_input[0].placeholder == "Ask about Beta Industries"
    app.chat_input[0].set_value("And the notice period?").run()

    conversations = app.session_state["conversations"]
    assert [m["content"] for m in conversations["S-ACME"]["messages"] if m["role"] == "user"] == [
        "What are the payment terms?"
    ]
    assert [m["content"] for m in conversations["S-BETA"]["messages"] if m["role"] == "user"] == [
        "And the notice period?"
    ]
    # separate backend sessions, and each question is limited to its own contract
    assert conversations["S-ACME"]["session_id"] != conversations["S-BETA"]["session_id"]
    assert [(p["supplier_id"], p["strict_scope"]) for p in app.payloads] == [
        ("S-ACME", True),
        ("S-BETA", True),
    ]

    # going back to the first contract shows only its own messages
    app.sidebar.selectbox[0].select("S-ACME").run()
    shown = [m.value for m in app.markdown]
    assert any("Answer 1" in text for text in shown)
    assert not any("Answer 2" in text for text in shown)


def test_new_conversation_resets_only_the_current_contract(app):
    for contract, question in (("S-ACME", "first"), ("S-BETA", "second")):
        app.sidebar.selectbox[0].select(contract).run()
        app.chat_input[0].set_value(question).run()
    next(b for b in app.sidebar.button if b.label == "New conversation").click().run()
    conversations = app.session_state["conversations"]
    assert (
        conversations["S-BETA"]["messages"] == [] and conversations["S-BETA"]["session_id"] is None
    )
    assert len(conversations["S-ACME"]["messages"]) == 2


def test_an_empty_reply_from_the_server_is_shown_as_an_error_and_not_saved(app):
    with patch("components.sse_client.stream_chat", lambda *a, **k: iter(())):
        app.sidebar.selectbox[0].select("S-ACME").run()
        app.chat_input[0].set_value("anything").run()
    assert len(app.error) >= 1
    assert app.session_state["conversations"]["S-ACME"]["messages"] == []


def test_stream_collector_is_still_used_for_the_message_shape():
    collector = StreamCollector([("token", {"text": "x"}), ("done", {"outcome": "answered"})])
    assert "".join(collector) == "x" and collector.message["content"] == "x"
