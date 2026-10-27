import pytest

from clausecheck.llm.client import LLMError
from clausecheck.prompts.loader import Prompt
from clausecheck.rag.generator import REFUSAL_TEXT
from clausecheck.rag.supplier_detector import SupplierDetector
from clausecheck.rag.types import SearchHit
from clausecheck.services.query_service import QueryService
from clausecheck.services.sessions import SessionStore
from clausecheck.store import sqlite as db
from clausecheck.store.cache import AnswerCache
from clausecheck.store.query_log import QueryLog

SUPPLIERS = [{"supplier_id": "S-ACME", "display_name": "Acme Corp", "aliases": ["Acme"]},
             {"supplier_id": "S-BETA", "display_name": "Beta Industries", "aliases": ["Beta"]}]


class FakeRewriter:
    def __init__(self):
        self.calls = []

    def rewrite(self, question, history):
        self.calls.append((question, list(history)))
        return question


class FakeRetriever:
    def __init__(self):
        self.calls = []

    def retrieve(self, query, supplier_id=None, k=20):
        self.calls.append((query, supplier_id))
        meta = {"doc_id": "doc-a", "page": 2, "section": "2. Payment", "clause_no": "2.1",
                "supplier_id": supplier_id or "S-ACME", "doc_type": "contract", "has_redaction": False}
        return [SearchHit("doc-a:p2:2_1", 0.03, "2.1 Payment is due Net 45 days.", dict(meta))]


class FakeReranker:
    def __init__(self, score):
        self.score = score

    def rerank(self, query, hits, top_n=5):
        for h in hits:
            h.rerank_score = self.score
        return hits[:top_n]


class FakeGenerator:
    prompt = Prompt("answer", "v1", "")

    def __init__(self, reply="Payment is due Net 45 days [C1].", fail=False):
        self.reply, self.fail, self.calls = reply, fail, 0

    def generate(self, question, context_text):
        self.calls += 1
        if self.fail:
            raise LLMError("All LLM providers failed: gemini, groq")
        return self.reply

    def stream(self, question, context_text):
        self.calls += 1
        if self.fail:
            raise LLMError("All LLM providers failed: gemini, groq")
        yield from ["Payment is due ", "Net 45 days [C1]."]


@pytest.fixture
def build(tmp_path):
    def _build(score=5.0, generator=None):
        conn = db.connect(tmp_path / "qs.db")
        parts = dict(rewriter=FakeRewriter(), retriever=FakeRetriever(), generator=generator or FakeGenerator())
        svc = QueryService(
            rewriter=parts["rewriter"], supplier_detector=SupplierDetector(SUPPLIERS),
            retriever=parts["retriever"], reranker=FakeReranker(score), generator=parts["generator"],
            sessions=SessionStore(3), cache=AnswerCache(conn, 3600), query_log=QueryLog(conn),
            threshold=0.0, context_budget=3000, index_version="test-v1",
        )
        return svc, parts, conn
    return _build

def test_answered_with_citation_and_logged(build):
    svc, parts, conn = build()
    r = svc.answer("What are the payment terms with Acme Corp?")
    assert r.outcome == "answered" and r.supplier_id == "S-ACME"
    assert [c.chunk_id for c in r.citations] == ["doc-a:p2:2_1"]
    assert r.chunk_ids == ["doc-a:p2:2_1"] and r.prompt_version == "v1" and r.index_version == "test-v1"
    row = QueryLog(conn).recent(1)[0]
    assert row["outcome"] == "answered" and row["chunk_ids"] == ["doc-a:p2:2_1"]


def test_low_score_refuses_without_calling_generator(build):
    svc, parts, _ = build(score=-3.0)
    r = svc.answer("What is Acme's liability cap?")
    assert (r.outcome, r.answer, r.refusal_reason) == ("refused", REFUSAL_TEXT, "low_score")
    assert parts["generator"].calls == 0


def test_answer_without_citation_becomes_refusal(build):
    svc, _, _ = build(generator=FakeGenerator(reply="Payment is due Net 45 days."))
    r = svc.answer("Payment terms with Acme?")
    assert (r.outcome, r.refusal_reason, r.answer) == ("refused", "no_citations", REFUSAL_TEXT)


def test_follow_up_keeps_supplier_and_passes_history(build):
    svc, parts, _ = build()
    sid = "s1"
    svc.answer("What are the payment terms with Acme Corp?", session_id=sid)
    svc.answer("And their notice period?", session_id=sid)
    assert parts["retriever"].calls[-1][1] == "S-ACME"
    question, history = parts["rewriter"].calls[-1]
    assert question == "And their notice period?" and len(history) == 1


def test_supplier_filter_overrides_detection(build):
    svc, parts, _ = build()
    svc.answer("What are the payment terms with Acme Corp?", supplier_filter="S-BETA")
    assert parts["retriever"].calls[-1][1] == "S-BETA"


def test_repeat_question_served_from_cache(build):
    svc, parts, conn = build()
    first = svc.answer("What are the payment terms with Acme Corp?")
    second = svc.answer("what are the payment terms with acme corp")
    assert second.cached and second.answer == first.answer and second.query_id != first.query_id
    assert parts["generator"].calls == 1
    assert len(QueryLog(conn).recent(10)) == 2


def test_llm_error_is_generic_and_not_cached(build):
    svc, parts, _ = build(generator=FakeGenerator(fail=True))
    r = svc.answer("Payment terms with Acme?")
    assert r.outcome == "error" and "gemini" not in r.answer
    r2 = svc.answer("Payment terms with Acme?")
    assert not r2.cached


def test_stream_event_order(build):
    svc, _, _ = build()
    events = list(svc.stream("What are the payment terms with Acme Corp?"))
    types = [e.type for e in events]
    assert types[0] == "meta" and types[1] == "sources"
    assert types[-2:] == ["citations", "done"]
    assert set(types[2:-2]) == {"token"}
    assert "".join(e.data["text"] for e in events if e.type == "token") == "Payment is due Net 45 days [C1]."
    assert events[-1].data["outcome"] == "answered" and "ttft" in events[-1].data["timings"]


def test_stream_refusal_and_error(build):
    svc, _, _ = build(score=-3.0)
    events = list(svc.stream("Liability cap for Acme?"))
    assert [e.data["text"] for e in events if e.type == "token"] == [REFUSAL_TEXT]
    assert events[-1].data["outcome"] == "refused"

    svc, _, _ = build(generator=FakeGenerator(fail=True))
    types = [e.type for e in svc.stream("Payment terms with Acme?")]
    assert types[-2:] == ["error", "done"]
