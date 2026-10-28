import pytest

from clausecheck.llm.client import LLMError
from clausecheck.rag.supplier_detector import SupplierDetector
from clausecheck.rag.types import SearchHit
from clausecheck.services.query_service import QueryService
from clausecheck.services.sessions import SessionStore
from clausecheck.store import sqlite as db
from clausecheck.store.cache import AnswerCache
from clausecheck.store.query_log import QueryLog
from tests.integration.test_query_service import (
    SUPPLIERS,
    FakeGenerator,
    FakeReranker,
    FakeRewriter,
)

QUESTION = "What are the payment terms with Acme Corp?"


class OneClauseRetriever:
    def retrieve(self, query, supplier_id=None, k=20):
        meta = {
            "doc_id": "doc-a",
            "page": 2,
            "section": "2. Payment",
            "clause_no": "2.1",
            "supplier_id": "S-ACME",
            "doc_type": "contract",
            "effective_date": "2023-01-15",
        }
        return [SearchHit("doc-a:p2:2_1", 0.03, "2.1 Payment is due Net 45 days.", meta)]


class Refusing(FakeGenerator):
    def stream(self, question, context_text):
        yield "I couldn't find this in the contracts I have for this supplier."


class FailingWithReasons(FakeGenerator):
    def generate(self, question, context_text):
        raise LLMError("All LLM providers failed", ["groq: RateLimitError 429", "gemini: error"])

    def stream(self, question, context_text):
        raise LLMError("All LLM providers failed", ["groq: RateLimitError 429", "gemini: error"])
        yield  # pragma: no cover


@pytest.fixture
def build(tmp_path):
    def _build(generator=None):
        conn = db.connect(tmp_path / "d.db")
        db.init_db(conn)
        db.upsert_document(
            conn,
            {
                "doc_id": "doc-a",
                "supplier_id": "S-ACME",
                "doc_type": "contract",
                "title": "ACME-MSA.pdf",
                "effective_date": "2023-01-15",
            },
        )
        return (
            QueryService(
                rewriter=FakeRewriter(),
                supplier_detector=SupplierDetector(SUPPLIERS),
                retriever=OneClauseRetriever(),
                reranker=FakeReranker(5.0),
                generator=generator or FakeGenerator(),
                sessions=SessionStore(3),
                cache=AnswerCache(conn, 3600),
                query_log=QueryLog(conn),
                threshold=0.0,
                context_budget=3000,
                index_version="test-v1",
                conn=conn,
            ),
            conn,
        )

    return _build


def test_the_plain_event_order_is_unchanged(build):
    service, _ = build()
    types = [e.type for e in service.stream(QUESTION)]
    assert types == ["meta", "sources", "token", "token", "citations", "done"]


def test_detail_adds_steps_and_a_checks_event_in_a_fixed_order(build):
    service, _ = build()
    events = list(service.stream(QUESTION, detail=True))
    assert [e.type for e in events] == [
        "meta",
        "step",
        "sources",
        "step",
        "token",
        "token",
        "step",
        "step",
        "checks",
        "step",
        "citations",
        "done",
    ]
    steps = [(e.data["id"], e.data["state"]) for e in events if e.type == "step"]
    assert steps == [
        ("found", "done"),
        ("write", "active"),
        ("write", "done"),
        ("check", "active"),
        ("check", "done"),
    ]
    found = next(e.data for e in events if e.type == "step")
    assert (found["clauses"], found["documents"]) == (1, 1)


def test_the_checks_event_reports_what_was_verified(build):
    service, _ = build()
    checks = next(e.data for e in service.stream(QUESTION, detail=True) if e.type == "checks")
    assert checks["status"] == "checked"
    assert checks["citations"] == {"found": 1, "total": 1}
    assert checks["numbers"] == {"matched": 1, "total": 1, "unverified": []}
    assert checks["answer"] == "Payment is due Net 45 days [C1]."
    # no heading in the clause text, so the term falls back to its section name
    assert checks["terms"][0]["value"] == "45 days" and checks["terms"][0]["term"] == "Payment"
    assert checks["terms"][0]["source"] == "§2.1, ACME-MSA.pdf, p.2"
    clause = checks["clauses"]["C1"]
    assert clause["doc_title"] == "ACME-MSA.pdf" and "Net 45" in clause["text"]
    assert clause["highlights"], "the figure the answer relies on is highlighted"


def test_a_refusal_has_no_checks_event(build):
    service, _ = build(generator=Refusing())
    types = [e.type for e in service.stream(QUESTION, detail=True)]
    assert "checks" not in types and types[-1] == "done"


def test_the_cause_of_a_failure_is_logged_not_just_the_generic_text(build):
    service, conn = build(generator=FailingWithReasons())
    result = service.answer(QUESTION)
    assert result.outcome == "error"
    assert QueryLog(conn).recent(1)[0]["error"] == "groq: RateLimitError 429; gemini: error"

    list(service.stream("Another question about Acme Corp?"))
    assert QueryLog(conn).recent(1)[0]["error"] == "groq: RateLimitError 429; gemini: error"


def test_a_cached_answer_replays_its_checks(build):
    service, _ = build()
    first = list(service.stream(QUESTION, detail=True))
    again = list(service.stream(QUESTION, detail=True))
    assert [e.type for e in again] == [
        "meta",
        "step",
        "sources",
        "token",
        "checks",
        "citations",
        "done",
    ]
    assert again[-1].data["cached"] is True and again[1].data["cached"] is True
    stored = next(e.data for e in first if e.type == "checks")
    assert next(e.data for e in again if e.type == "checks") == stored


def test_an_answer_cached_without_checks_is_answered_again_when_checks_are_wanted(build):
    service, _ = build()
    list(service.stream(QUESTION))  # an older client: no detail, so the cache holds no checks
    events = list(service.stream(QUESTION, detail=True))
    assert "checks" in [e.type for e in events]
    assert events[-1].data["cached"] is False
    # and now the cache holds the checks, so the next request is served from it
    assert list(service.stream(QUESTION, detail=True))[-1].data["cached"] is True
