from pathlib import Path
from unittest.mock import patch

import pytest
from components.api_client import ApiClient
from components.contracts import _load_contracts
from streamlit.testing.v1 import AppTest

VIEWS = Path(__file__).resolve().parents[2] / "frontend" / "views"
MAIN, AMD1, AMD2 = "ACME-SUPPLY.txt", "A-AMD1.txt", "B-AMD2.txt"
SLUG, NAME = "acme-supply-deal", "Acme Supply Deal"


class Backend:
    """A stand-in for the API that records uploads and can be told to fail or duplicate files."""

    def __init__(self):
        self.suppliers = [{"supplier_id": "S-OLD", "display_name": "Old Corp", "aliases": []}]
        self.uploads = []  # (filename, doc_type, contract_id, display_name)
        self.fail, self.duplicate = set(), set()
        self.link_amendments = True

    def created(self):
        names = {u[2]: u[3] for u in self.uploads if u[3]}
        return [{"supplier_id": c, "display_name": n, "aliases": []} for c, n in names.items()]

    def upload(self, filename, content, supplier_id, doc_type="contract", display_name=None):
        self.uploads.append((filename, doc_type, supplier_id, display_name))
        if filename in self.duplicate:
            return {"duplicate": True, "doc_id": "d0"}
        return {"job_id": filename}

    def job(self, job_id):
        if job_id in self.fail:
            return {"status": "failed", "error": "EmptyDocumentError"}
        return {"status": "done", "doc_id": f"doc-{job_id}"}

    def documents(self, supplier_id):
        docs = []
        for filename, doc_type, contract, _ in self.uploads:
            if contract == supplier_id and filename not in self.fail | self.duplicate:
                parent = f"doc-{MAIN}" if doc_type == "amendment" and self.link_amendments else None
                docs.append(
                    {
                        "doc_id": f"doc-{filename}",
                        "title": filename,
                        "doc_type": doc_type,
                        "effective_date": "2025-01-01",
                        "parent_doc_id": parent,
                    }
                )
        return docs


@pytest.fixture
def backend():
    _load_contracts.clear()
    be = Backend()
    streamed = []

    def fake_stream(base_url, payload, **kw):
        streamed.append(payload)
        yield "meta", {"query_id": "q1", "supplier_id": payload["supplier_id"]}
        yield "sources", {"sources": []}
        yield "token", {"text": "Net 60 [C1]."}
        yield "citations", {"citations": [], "unsupported": False}
        yield "done", {"outcome": "answered", "refusal_reason": None, "timings": {}}

    be.streamed = streamed
    with (
        patch.object(ApiClient, "health", lambda self: {"status": "ok"}),
        patch.object(ApiClient, "suppliers", lambda self: be.suppliers + be.created()),
        patch.object(ApiClient, "documents", lambda self, supplier_id: be.documents(supplier_id)),
        patch.object(ApiClient, "upload", lambda self, *a, **k: be.upload(*a, **k)),
        patch.object(ApiClient, "job", lambda self, job_id: be.job(job_id)),
        patch.object(ApiClient, "new_session", lambda self: "session-1"),
        patch("components.sse_client.stream_chat", fake_stream),
    ):
        yield be
    _load_contracts.clear()


def _page(name):
    at = AppTest.from_file(str(VIEWS / name), default_timeout=30)
    at.run()
    return at


def _button(at, label):
    return next(b for b in at.button if b.label == label)


def _analyse(at, name=NAME, main=True, amendments=(AMD2, AMD1)):
    at.text_input[0].set_value(name)
    if main:
        at.file_uploader[0].upload(MAIN, b"contract text")
    for filename in amendments:
        at.file_uploader[1].upload(filename, b"amendment text")
    _button(at, "Analyse contract").click().run()


# ---- New contract analyser -------------------------------------------------------------------


def test_the_analyser_starts_with_an_empty_form_and_no_chat(backend):
    at = _page("analyser.py")
    assert not at.exception
    assert [t.label for t in at.text_input] == ["Contract name"]
    assert len(at.file_uploader) == 2 and len(at.chat_input) == 0


def test_analysing_indexes_the_original_first_then_each_amendment(backend):
    at = _page("analyser.py")
    _analyse(at)
    assert not at.exception
    # the original first, then the amendments by file name, all under one contract ID and name
    assert backend.uploads == [
        (MAIN, "contract", SLUG, NAME),
        (AMD1, "amendment", SLUG, NAME),
        (AMD2, "amendment", SLUG, NAME),
    ]
    assert at.session_state["analysed_contract"] == SLUG
    assert at.session_state["active_contract"] == SLUG
    assert any("is ready" in s.value for s in at.success)
    assert at.chat_input[0].placeholder == f"Ask about {NAME}"
    assert not at.warning


def test_the_new_contract_gets_its_own_conversation_limited_to_it(backend):
    at = _page("analyser.py")
    _analyse(at)
    at.chat_input[0].set_value("What are the payment terms?").run()
    assert not at.exception
    assert backend.streamed == [
        {
            "question": "What are the payment terms?",
            "session_id": "session-1",
            "supplier_id": SLUG,
            "strict_scope": True,
        }
    ]
    assert list(at.session_state["conversations"]) == [SLUG]


def test_analyse_another_contract_brings_back_the_form(backend):
    at = _page("analyser.py")
    _analyse(at)
    _button(at, "Analyse another contract").click().run()
    assert at.session_state["analysed_contract"] is None
    assert _button(at, "Analyse contract") and len(at.chat_input) == 0


def test_the_form_checks_its_input(backend):
    at = _page("analyser.py")
    _analyse(at, name="  ", main=True)
    assert any("name" in e.value.lower() for e in at.error)

    at = _page("analyser.py")
    _analyse(at, main=False, amendments=())
    assert any("contract file" in e.value.lower() for e in at.error)

    # a name whose ID is already taken is refused, and nothing is sent
    backend.suppliers.append({"supplier_id": "old-corp", "display_name": "Old Corp", "aliases": []})
    _load_contracts.clear()
    at = _page("analyser.py")
    _analyse(at, name="Old Corp")
    assert any("already exists" in e.value for e in at.error)
    assert backend.uploads == []  # nothing was sent for any of the three bad submissions


def test_if_the_original_fails_nothing_else_is_uploaded_and_no_contract_is_made(backend):
    backend.fail = {MAIN}
    at = _page("analyser.py")
    _analyse(at)
    assert [u[0] for u in backend.uploads] == [MAIN]  # the amendments were not attempted
    assert at.session_state["analysed_contract"] is None
    assert any("was not created" in e.value for e in at.error)


def test_if_an_amendment_fails_the_contract_is_still_made_and_says_what_is_missing(backend):
    backend.fail = {AMD1}
    at = _page("analyser.py")
    _analyse(at)
    assert at.session_state["analysed_contract"] == SLUG
    assert any(f"Not added: {AMD1}" in w.value for w in at.warning)
    assert len(at.chat_input) == 1


def test_an_amendment_that_did_not_link_is_flagged(backend):
    backend.link_amendments = False
    at = _page("analyser.py")
    _analyse(at, amendments=(AMD1,))
    assert any("was not linked" in w.value and AMD1 in w.value for w in at.warning)


# ---- Chat page: add a document to a contract --------------------------------------------------


def _chat_page(backend):
    backend.suppliers = [{"supplier_id": "S-ACME", "display_name": "Acme Corp", "aliases": []}]
    at = _page("contracts.py")
    at.sidebar.selectbox[0].select("S-ACME").run()
    return at


def _add(at, filename="LATER-AMD.txt", doc_type="amendment", with_file=True):
    if with_file:
        at.file_uploader[0].upload(filename, b"text")
    next(s for s in at.selectbox if s.label == "Document type").select(doc_type)
    _button(at, "Upload").click().run()


def test_adding_a_document_uploads_it_to_this_contract_and_confirms(backend):
    at = _chat_page(backend)
    _add(at)
    assert not at.exception
    assert backend.uploads == [("LATER-AMD.txt", "amendment", "S-ACME", None)]
    assert any("LATER-AMD.txt was added to Acme Corp" in s.value for s in at.success)


def test_adding_without_a_file_asks_for_one(backend):
    at = _chat_page(backend)
    _add(at, with_file=False)
    assert any("Choose a file" in w.value for w in at.warning) and backend.uploads == []


def test_a_duplicate_and_a_failed_upload_are_reported(backend):
    backend.duplicate = {"SAME.txt"}
    at = _chat_page(backend)
    _add(at, "SAME.txt")
    assert any("already indexed" in w.value for w in at.warning)

    backend.fail = {"BAD.txt"}
    at = _chat_page(backend)
    _add(at, "BAD.txt")
    assert any("BAD.txt could not be added" in e.value for e in at.error)
