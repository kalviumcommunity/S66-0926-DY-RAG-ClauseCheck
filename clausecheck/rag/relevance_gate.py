from dataclasses import dataclass

from clausecheck.rag.types import SearchHit


@dataclass
class GateResult:
    """Outcome of the relevance gate."""

    passed: bool
    reason: str | None
    top_score: float | None


def check(
    hits: list[SearchHit],
    threshold: float,
    *,
    supplier_required: bool = False,
    supplier_id: str | None = None,
) -> GateResult:
    """Decide whether retrieved evidence is strong enough to answer."""
    if supplier_required and supplier_id is None:
        return GateResult(passed=False, reason="unknown_supplier", top_score=None)
    if not hits:
        return GateResult(passed=False, reason="no_hits", top_score=None)

    top_score: float | None = None
    for hit in hits:
        if getattr(hit, "expanded", False):
            continue
        if hit.rerank_score is not None:
            top_score = hit.rerank_score
        else:
            top_score = hit.score
        break
    if top_score is None and hits:
        hit = hits[0]
        top_score = hit.rerank_score if hit.rerank_score is not None else hit.score

    if top_score is None or top_score < threshold:
        return GateResult(passed=False, reason="low_score", top_score=top_score)
    return GateResult(passed=True, reason=None, top_score=top_score)
