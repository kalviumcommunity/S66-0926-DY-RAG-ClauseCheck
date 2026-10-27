from clausecheck.rag.reranker import Reranker
from clausecheck.rag.types import SearchHit


def scorer(pairs):
    return [float(text.count("payment")) for _, text in pairs]


def test_rerank_orders_by_score_and_cuts_top_n():
    hits = [SearchHit("a", 0.1, "term two years"), SearchHit("b", 0.1, "payment payment"),
            SearchHit("c", 0.1, "payment due")]
    out = Reranker(scorer=scorer).rerank("payment terms", hits, top_n=2)
    assert [h.chunk_id for h in out] == ["b", "c"]
    assert out[0].rerank_score == 2.0


def test_expanded_hits_follow_their_parent_hit():
    hits = [SearchHit("orig", 0.1, "payment payment"), SearchHit("x", 0.1, "payment"),
            SearchHit("amend", 0.0, "nothing", expanded=True, source="expansion")]
    out = Reranker(scorer=scorer).rerank("q", hits, top_n=1)
    assert [h.chunk_id for h in out] == ["orig", "amend"]


def test_empty():
    assert Reranker(scorer=scorer).rerank("q", [], top_n=5) == []
