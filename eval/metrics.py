"""Retrieval metrics: recall@k and mean reciprocal rank."""

import re
from collections.abc import Callable

from eval.schema import Question


def recall_at_k(retrieved: list[str], gold: list[str], k: int) -> float:
    """Share of the gold chunk IDs found in the top `k` retrieved IDs."""
    if not gold:
        raise ValueError("gold must not be empty")
    return len(set(retrieved[:k]) & set(gold)) / len(set(gold))


def mrr(retrieved: list[str], gold: list[str]) -> float:
    """Reciprocal rank of the first gold ID (1-based), or 0.0 if none is retrieved."""
    for rank, chunk_id in enumerate(retrieved, 1):
        if chunk_id in gold:
            return 1 / rank
    return 0.0


def evaluate_retrieval(
    questions: list[Question], retrieve_fn: Callable[[Question], list[str]], k: int = 5
) -> dict:
    """Score a retriever on the answerable questions (unanswerable ones are skipped)."""
    per_question = []
    for q in questions:
        if q.should_refuse:
            continue
        retrieved = retrieve_fn(q)
        per_question.append(
            {
                "qid": q.qid,
                "recall": recall_at_k(retrieved, q.gold_chunk_ids, k),
                "rr": mrr(retrieved, q.gold_chunk_ids),
                "retrieved": retrieved,
            }
        )
    n = len(per_question)
    return {
        "k": k,
        "n": n,
        "recall_at_k": sum(p["recall"] for p in per_question) / n if n else 0.0,
        "mrr": sum(p["rr"] for p in per_question) / n if n else 0.0,
        "per_question": per_question,
    }


def answer_correctness(grades: list[str]) -> float:
    """Share of 'correct' grades."""
    if not grades:
        raise ValueError("grades must not be empty")
    return sum(1 for g in grades if g == "correct") / len(grades)


def citation_accuracy(cited: list[list[str]], gold: list[list[str]]) -> float:
    """Among pairs where both lists are non-empty, share where any cited ID is in gold."""
    pairs = [(c, g) for c, g in zip(cited, gold, strict=False) if c and g]
    if not pairs:
        raise ValueError("no non-empty cited/gold pairs")
    hits = sum(1 for c, g in pairs if set(c) & set(g))
    return hits / len(pairs)


def refusal_accuracy(refused: list[bool], should_refuse: list[bool]) -> float:
    """Among should_refuse=True, share refused."""
    denom = sum(1 for s in should_refuse if s)
    if denom == 0:
        return 0.0
    return sum(1 for r, s in zip(refused, should_refuse, strict=False) if s and r) / denom


def false_refusal_rate(refused: list[bool], should_refuse: list[bool]) -> float:
    """Among should_refuse=False, share refused."""
    denom = sum(1 for s in should_refuse if not s)
    if denom == 0:
        return 0.0
    return sum(1 for r, s in zip(refused, should_refuse, strict=False) if (not s) and r) / denom


def _normalise(text: str) -> str:
    text = text.lower().replace(",", "")
    return re.sub(r"\s+", " ", text).strip()


def contains_expected(answer: str, expected: str) -> bool:
    """Case-insensitive substring check with collapsed spaces and commas removed."""
    return _normalise(expected) in _normalise(answer)
