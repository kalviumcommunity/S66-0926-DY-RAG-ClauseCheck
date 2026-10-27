import pytest

from eval.metrics import (
    answer_correctness,
    citation_accuracy,
    contains_expected,
    false_refusal_rate,
    refusal_accuracy,
)


def test_answer_correctness():
    assert answer_correctness(["correct", "wrong", "correct", "partial"]) == 0.5
    with pytest.raises(ValueError):
        answer_correctness([])


def test_citation_accuracy_ignores_empty_pairs():
    assert citation_accuracy([["a"], ["x"], [], ["b", "c"]], [["a"], ["y"], ["z"], ["c"]]) == pytest.approx(2 / 3)


def test_refusal_metrics():
    refused = [True, False, True, False]
    should = [True, True, False, False]
    assert refusal_accuracy(refused, should) == 0.5
    assert false_refusal_rate(refused, should) == 0.5


def test_contains_expected_normalises():
    assert contains_expected("The unit price is $1,250.00 [C1].", "1250.00")
    assert contains_expected("Payment is due  NET 45 days.", "net 45")
    assert not contains_expected("Net 30", "net 45")
