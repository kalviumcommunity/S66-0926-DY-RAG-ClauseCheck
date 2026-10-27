import pytest

from eval.metrics import evaluate_retrieval, mrr, recall_at_k
from eval.schema import Question


def test_recall_at_k():
    assert recall_at_k(["a", "b", "c"], ["b"], k=5) == 1.0
    assert recall_at_k(["a", "b", "c"], ["c"], k=2) == 0.0
    assert recall_at_k(["a", "b"], ["a", "z"], k=5) == 0.5
    with pytest.raises(ValueError):
        recall_at_k(["a"], [], k=5)


def test_mrr():
    assert mrr(["a", "b", "c"], ["a"]) == 1.0
    assert mrr(["a", "b", "c"], ["c"]) == pytest.approx(1 / 3)
    assert mrr(["a"], ["z"]) == 0.0


def _q(qid, gold, refuse=False):
    return Question(qid=qid, split="tune", group="unanswerable" if refuse else "real",
                    question="?", supplier_id="S-ACME", gold_chunk_ids=gold,
                    expected_answer="" if refuse else "x", should_refuse=refuse)


def test_evaluate_retrieval_skips_unanswerable():
    questions = [_q("Q1", ["a"]), _q("Q2", ["z"]), _q("Q3", [], refuse=True)]
    result = evaluate_retrieval(questions, lambda q: ["a", "b"], k=5)
    assert result["n"] == 2
    assert result["recall_at_k"] == 0.5
    assert result["mrr"] == 0.5
    assert {p["qid"] for p in result["per_question"]} == {"Q1", "Q2"}
