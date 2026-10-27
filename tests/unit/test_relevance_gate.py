from clausecheck.rag.relevance_gate import check
from clausecheck.rag.types import SearchHit


def test_no_hits():
    assert check([], 0.5).reason == "no_hits"


def test_low_and_high_score_uses_rerank_score():
    hits = [SearchHit("a", 0.9, "t", rerank_score=0.2)]
    assert check(hits, 0.5).passed is False and check(hits, 0.5).reason == "low_score"
    assert check(hits, 0.1).passed is True


def test_falls_back_to_score_and_skips_expanded():
    hits = [SearchHit("x", 0.0, "t", expanded=True), SearchHit("a", 0.7, "t")]
    assert check(hits, 0.5).passed and check(hits, 0.5).top_score == 0.7


def test_unknown_supplier():
    r = check([SearchHit("a", 1.0, "t")], 0.1, supplier_required=True, supplier_id=None)
    assert (r.passed, r.reason) == (False, "unknown_supplier")
