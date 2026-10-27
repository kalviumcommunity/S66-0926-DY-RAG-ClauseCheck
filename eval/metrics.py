"""Retrieval metrics: recall@k and mean reciprocal rank."""

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
