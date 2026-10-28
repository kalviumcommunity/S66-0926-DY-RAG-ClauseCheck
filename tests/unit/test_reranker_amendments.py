from clausecheck.rag.reranker import Reranker
from clausecheck.rag.types import SearchHit


def _hit(chunk_id, text, **meta):
    return SearchHit(chunk_id, 0.0, text, dict(meta))


ORIGINAL = _hit(
    "orig:6_1", "6.1 Liability up to $25,000 per Shipment.", doc_id="orig", clause_no="6.1"
)
AMENDMENT = _hit(
    "amd:3_1",
    'In Section 6.1, "$25,000" is replaced with "$40,000".',
    doc_id="amd",
    clause_no="3.1",
    parent_doc_id="orig",
)
NOISE = [_hit(f"orig:n{i}", f"unrelated {i}", doc_id="orig", clause_no=f"9.{i}") for i in range(3)]
SCORES = {"orig:6_1": 5.0, "amd:3_1": -9.0, "orig:n0": 4.0, "orig:n1": 3.0, "orig:n2": 2.0}


def _rerank(hits, top_n):
    ids = {h.text: h.chunk_id for h in hits}
    return Reranker(scorer=lambda pairs: [SCORES[ids[text]] for _, text in pairs]).rerank(
        "liability", hits, top_n=top_n
    )


def test_amendment_of_a_kept_clause_is_kept_next_to_it():
    out = [h.chunk_id for h in _rerank([ORIGINAL, AMENDMENT, *NOISE], top_n=2)]
    assert out == ["orig:6_1", "amd:3_1", "orig:n0"]


def test_original_of_a_kept_amendment_is_kept_next_to_it():
    scores = dict(SCORES, **{"orig:6_1": -9.0, "amd:3_1": 9.0})
    hits = [ORIGINAL, AMENDMENT, *NOISE]
    ids = {h.text: h.chunk_id for h in hits}
    out = Reranker(scorer=lambda pairs: [scores[ids[t]] for _, t in pairs]).rerank(
        "liability", hits, top_n=2
    )
    assert {h.chunk_id for h in out} >= {"amd:3_1", "orig:6_1"}


def test_unlinked_low_scoring_clause_is_still_cut():
    other = _hit(
        "amd:5_1", "Payment is Net 45.", doc_id="amd", clause_no="5.1", parent_doc_id="orig"
    )
    scores = dict(SCORES, **{"amd:5_1": -9.0})
    hits = [ORIGINAL, other, *NOISE]
    ids = {h.text: h.chunk_id for h in hits}
    out = Reranker(scorer=lambda pairs: [scores[ids[t]] for _, t in pairs]).rerank(
        "liability", hits, top_n=2
    )
    assert "amd:5_1" not in [h.chunk_id for h in out]
