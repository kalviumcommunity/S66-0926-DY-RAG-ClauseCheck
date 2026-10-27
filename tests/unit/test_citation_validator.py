from clausecheck.rag.citation_validator import validate
from clausecheck.rag.generator import REFUSAL_TEXT
from clausecheck.rag.types import SearchHit

MAP = {
    "C1": SearchHit("doc-a:p2:2_1", 1.0, "t", {"doc_id": "doc-a", "page": 2, "section": "2. Payment", "clause_no": "2.1"}),
    "C2": SearchHit("doc-b:p1:1", 1.0, "t", {"doc_id": "doc-b", "page": 1, "section": None, "clause_no": "1"}),
}


def test_valid_citations_kept_in_order_and_unique():
    r = validate("Payment is Net 30 [C2]. It replaced Net 45 [C1][C2].", MAP)
    assert [c.marker for c in r.citations] == ["C2", "C1"]
    assert r.citations[1].chunk_id == "doc-a:p2:2_1" and r.citations[1].page == 2
    assert r.unsupported is False and r.dropped == []


def test_invalid_marker_dropped_and_sentence_flagged():
    r = validate("Payment is Net 45 [C1]. The term is two years [C9].", MAP)
    assert r.dropped == ["C9"]
    assert "[C9]" not in r.answer and "two years." in r.answer
    assert r.unsupported is True


def test_exempt_sentences():
    r = validate("Here is what the contract says: Payment is Net 45 [C1]. Want the late fee too?", MAP)
    assert r.unsupported is False


def test_refusal_has_no_citations_and_is_supported():
    r = validate(REFUSAL_TEXT, MAP)
    assert r.citations == [] and r.unsupported is False
