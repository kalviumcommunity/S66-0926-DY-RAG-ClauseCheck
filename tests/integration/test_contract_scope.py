import pytest

from clausecheck.rag.supplier_detector import SupplierDetector
from clausecheck.services.query_service import OTHER_CONTRACT, QueryService
from clausecheck.services.sessions import SessionStore
from clausecheck.store import sqlite as db
from clausecheck.store.cache import AnswerCache
from clausecheck.store.query_log import QueryLog
from tests.integration.test_query_service import (
    SUPPLIERS,
    FakeGenerator,
    FakeReranker,
    FakeRetriever,
    FakeRewriter,
)


@pytest.fixture
def svc(tmp_path):
    conn = db.connect(tmp_path / "scope.db")
    service = QueryService(
        rewriter=FakeRewriter(),
        supplier_detector=SupplierDetector(SUPPLIERS),
        retriever=FakeRetriever(),
        reranker=FakeReranker(5.0),
        generator=FakeGenerator(),
        sessions=SessionStore(3),
        cache=AnswerCache(conn, 3600),
        query_log=QueryLog(conn),
        threshold=0.0,
        context_budget=3000,
        index_version="test-v1",
    )
    return service, conn


def test_strict_scope_refuses_a_question_about_another_contract(svc):
    service, conn = svc
    r = service.answer(
        "What are the payment terms with Acme Corp?",
        session_id="s1",
        supplier_filter="S-BETA",
        strict_scope=True,
    )
    assert (r.outcome, r.refusal_reason, r.supplier_id) == ("refused", OTHER_CONTRACT, "S-BETA")
    assert "Beta Industries" in r.answer and "Acme Corp" in r.answer
    assert service.generator.calls == 0 and service.retriever.calls == []
    # logged, but not cached and not added to the conversation history
    assert QueryLog(conn).recent(1)[0]["refusal_reason"] == OTHER_CONTRACT
    assert service.sessions.get_or_create("s1").turns == []
    again = service.answer(
        "What are the payment terms with Acme Corp?",
        session_id="s1",
        supplier_filter="S-BETA",
        strict_scope=True,
    )
    assert not again.cached


def test_strict_scope_still_answers_about_its_own_contract_and_follow_ups(svc):
    service, _ = svc
    own = service.answer(
        "What are the payment terms with Beta Industries?",
        supplier_filter="S-BETA",
        strict_scope=True,
    )
    assert own.outcome == "answered" and service.retriever.calls[-1][1] == "S-BETA"
    follow_up = service.answer(
        "And their notice period?", supplier_filter="S-BETA", strict_scope=True
    )
    assert follow_up.outcome == "answered"


def test_without_strict_scope_the_filter_still_overrides_detection(svc):
    service, _ = svc
    r = service.answer("What are the payment terms with Acme Corp?", supplier_filter="S-BETA")
    assert r.outcome == "answered" and service.retriever.calls[-1][1] == "S-BETA"


def test_strict_scope_streams_the_refusal_in_the_usual_event_order(svc):
    service, _ = svc
    events = list(
        service.stream(
            "What are the payment terms with Acme Corp?",
            supplier_filter="S-BETA",
            strict_scope=True,
        )
    )
    assert [e.type for e in events] == ["meta", "sources", "token", "citations", "done"]
    assert "Beta Industries" in events[2].data["text"]
    assert events[-1].data["outcome"] == "refused"
    assert events[-1].data["refusal_reason"] == OTHER_CONTRACT
    assert service.generator.calls == 0
