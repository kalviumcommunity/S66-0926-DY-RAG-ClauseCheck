"""The three pages through Streamlit's AppTest, with the backend patched."""

import re

import pytest
from components.api_client import ApiClient, ApiUnavailable

from tests.frontend.conftest import CHECKS, CONTRACTS, DOCS, REPORT


def html(at) -> str:
    """All the HTML the page drew (st.html elements are unknown to AppTest, so read the proto)."""
    body = " ".join(getattr(e.proto, "body", "") for e in at.get("html"))
    return re.sub(r"<style>.*?</style>", "", body, flags=re.S)  # the stylesheet names every class


def test_ask_lists_the_register_without_a_sidebar(run_app):
    at = run_app("ask")
    assert not at.exception
    text = html(at)
    assert "Orion" in text and "Helixa Cloud Systems" in text
    assert len(at.sidebar.children) == 0
    assert {b.label for b in at.button} >= {"Check"}


def test_ask_with_no_backend_says_system_failure_not_a_finding(run_app):
    def down(self):
        raise ApiUnavailable("down")

    def down_report(self, days="7", contract_id=None):
        raise ApiUnavailable("down")

    at = run_app("ask", health=down, report=down_report, contracts=down)
    assert not at.exception
    assert "System failure, not a finding" in html(at)
    assert len(at.chat_input) == 0


def test_ask_with_an_empty_register_points_to_contracts(run_app):
    at = run_app("ask", contracts=lambda self: [])
    assert not at.exception
    assert "There are no contracts yet" in html(at)


def test_choosing_a_contract_opens_its_own_check_page(run_app):
    at = run_app("ask")
    next(b for b in at.button if b.key == "pick-orion").click().run()
    assert not at.exception
    assert at.session_state["active_contract"] == "orion"
    assert any(b.label == "New check" for b in at.button)
    assert any("Ask about Orion" in (t.placeholder or "") for t in at.text_input)


def _streams(events):
    def fake(base_url, payload, **kw):
        fake.payloads.append(payload)
        yield from events

    fake.payloads = []
    return fake


def _ask(at, question):
    at.text_input(key="question-orion").input(question)
    next(
        b for b in at.get("button") if getattr(b, "label", "") == "Check" and b.proto.form_id
    ).click()
    return at.run()


def test_a_check_is_scoped_to_one_contract_and_shows_its_record(run_app, monkeypatch):
    fake = _streams(
        [
            ("meta", {"query_id": "q1"}),
            ("step", {"id": "found", "state": "done", "clauses": 1, "documents": 2, "ms": 120}),
            ("token", {"text": CHECKS["answer"]}),
            ("checks", CHECKS),
            ("done", {"outcome": "answered", "refusal_reason": None, "timings": {}}),
        ]
    )
    monkeypatch.setattr("components.sse_client.stream_chat", fake)
    at = run_app("ask")
    next(b for b in at.button if b.key == "pick-orion").click().run()
    _ask(at, "What are the payment terms?")
    assert not at.exception
    payload = fake.payloads[0]
    assert payload["supplier_id"] == "orion" and payload["strict_scope"] and payload["detail"]
    text = html(at)
    assert at.session_state["conversations"]["orion"]["checks"][0]["kind"] == "checked"
    assert "What are the payment terms?" in text
    assert "Payment terms" in text and "§4.1, ORION.pdf" in text
    assert "Checked" in text and "1 of 1 citations found" in text


def test_an_unverified_number_turns_the_seal_to_verify_and_names_it(run_app, monkeypatch):
    unverified = {
        **CHECKS,
        "status": "verify",
        "numbers": {
            "matched": 0,
            "total": 1,
            "unverified": [{"value": "60 days", "marker": "C1"}],
        },
    }
    monkeypatch.setattr(
        "components.sse_client.stream_chat",
        _streams(
            [
                ("token", {"text": "Due in 60 days [C1]."}),
                ("checks", unverified),
                ("done", {"outcome": "answered", "timings": {}}),
            ]
        ),
    )
    at = run_app("ask")
    next(b for b in at.button if b.key == "pick-orion").click().run()
    _ask(at, "When is payment due?")
    text = html(at)
    assert "Verify" in text and "“60 days” does not appear in C1" in text


@pytest.mark.parametrize(
    ("events", "expected"),
    [
        ([("done", {"outcome": "refused", "refusal_reason": "no_match"})], "Nothing was guessed"),
        ([("error", {"message": "x"})], "System failure, not a finding"),
    ],
)
def test_outcomes_without_an_answer_are_worded_as_they_are(run_app, monkeypatch, events, expected):
    monkeypatch.setattr("components.sse_client.stream_chat", _streams(events))
    at = run_app("ask")
    next(b for b in at.button if b.key == "pick-orion").click().run()
    _ask(at, "Anything?")
    assert not at.exception
    assert expected in html(at)


def test_a_new_check_clears_only_this_contract(run_app, monkeypatch):
    monkeypatch.setattr(
        "components.sse_client.stream_chat",
        _streams([("done", {"outcome": "refused", "refusal_reason": "no_match"})]),
    )
    at = run_app("ask")
    next(b for b in at.button if b.key == "pick-orion").click().run()
    _ask(at, "Anything?")
    at.session_state["conversations"]["helixa"] = {"checks": [{"kind": "none"}], "session_id": "s"}
    next(b for b in at.button if b.label == "New check").click().run()
    assert (
        "orion" not in at.session_state["conversations"]
        or not at.session_state["conversations"]["orion"]["checks"]
    )
    assert at.session_state["conversations"]["helixa"]["checks"]


def test_contracts_page_shows_the_numbered_filing_form(run_app):
    at = run_app("contracts")
    assert not at.exception
    text = html(at)
    assert "Add a contract" in text and "Filing log" in text
    assert any(b.label == "File and index" for b in at.button)
    assert any(t.label == "Effective date" for t in at.text_input)


def test_filing_without_a_name_is_refused_in_words(run_app):
    at = run_app("contracts")
    next(b for b in at.button if b.label == "File and index").click().run()
    assert not at.exception
    assert "Give the contract a name." in html(at)


def test_filing_an_existing_name_is_refused(run_app):
    at = run_app("contracts")
    at.text_input[0].input("Orion").run()
    next(b for b in at.button if b.label == "File and index").click().run()
    assert "already exists" in html(at)


def test_a_name_with_no_file_asks_for_the_file(run_app):
    at = run_app("contracts")
    at.text_input[0].input("Brightline Packaging").run()
    next(b for b in at.button if b.label == "File and index").click().run()
    assert "Choose the file to file." in html(at)


def test_insights_reads_as_a_service_report(run_app):
    at = run_app("insights")
    assert not at.exception
    text = html(at)
    assert REPORT["headline"] in text
    assert "Not measured" in text
    assert "Not classified" in text
    assert "What is the parental leave policy?" in text
    assert "Answer rate counts system failures as unanswered." in text
    assert any(d.label.startswith("Download") for d in at.get("download_button"))


def test_insights_without_a_backend_stops_with_a_failure_note(run_app):
    def down(self, days="7", contract_id=None):
        raise ApiUnavailable("down")

    at = run_app("insights", report=down)
    assert not at.exception
    assert "System failure, not a finding" in html(at)


def test_the_documents_list_is_available_for_a_contract(run_app):
    from components import ui

    assert "AMD1.pdf" in ui.documents_list(DOCS)
    assert "ORION.pdf" in ui.documents_list(DOCS)
    assert CONTRACTS and ApiClient
