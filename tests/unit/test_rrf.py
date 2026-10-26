import pytest

from clausecheck.rag.hybrid_retriever import rrf_fuse


def test_rrf_order_and_scores():
    fused = rrf_fuse([["a", "b", "c"], ["b", "c", "d"]], k=60)
    assert [i for i, _ in fused] == ["b", "c", "a", "d"]
    assert dict(fused)["b"] == pytest.approx(1 / 62 + 1 / 61)


def test_rrf_single_list_keeps_order():
    assert [i for i, _ in rrf_fuse([["x", "y", "z"]])] == ["x", "y", "z"]


def test_rrf_empty():
    assert rrf_fuse([[], []]) == []
