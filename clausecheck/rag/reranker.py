"""Cross-encoder re-ranking of retrieved candidates."""

from collections.abc import Callable

from clausecheck.rag.hybrid_retriever import CLAUSE_REF_RE
from clausecheck.rag.types import SearchHit

DEFAULT_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
Scorer = Callable[[list[tuple[str, str]]], list[float]]


def _related(hit: SearchHit, expanded: SearchHit) -> bool:
    """True if `expanded` is in the parent or child document of `hit` (or metadata is missing)."""
    a, b = hit.metadata, expanded.metadata
    if not a.get("doc_id") or not b.get("doc_id"):
        return True
    return b["doc_id"] == a.get("parent_doc_id") or a["doc_id"] == b.get("parent_doc_id")


def _amends(child: SearchHit, parent: SearchHit) -> bool:
    """True if `child` is a clause of an amendment of `parent`'s document that names its clause."""
    c, p = child.metadata, parent.metadata
    if (
        not c.get("parent_doc_id")
        or c["parent_doc_id"] != p.get("doc_id")
        or not p.get("clause_no")
    ):
        return False
    return p["clause_no"] in CLAUSE_REF_RE.findall(child.text)


class Reranker:
    """Scores (query, passage) pairs and keeps the best; amendments stay next to their originals."""

    def __init__(self, scorer: Scorer | None = None, model_name: str = DEFAULT_MODEL):
        self._scorer = scorer
        self.model_name = model_name

    def _score(self, pairs: list[tuple[str, str]]) -> list[float]:
        if self._scorer is None:  # load lazily: the import and the download are slow
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as exc:
                raise RuntimeError(
                    "re-ranking needs sentence-transformers: "
                    "pip install sentence-transformers==6.2.0"
                ) from exc
            model = CrossEncoder(self.model_name)
            self._scorer = lambda p: [float(s) for s in model.predict(p)]
        return self._scorer(pairs)

    def rerank(self, query: str, hits: list[SearchHit], top_n: int = 5) -> list[SearchHit]:
        """Top `top_n` hits by cross-encoder score, plus every expanded hit after its anchor."""
        if not hits:
            return []
        scores = self._score([(query, h.text) for h in hits])
        for hit, score in zip(hits, scores, strict=True):
            hit.rerank_score = float(score)
        ranked = sorted((h for h in hits if not h.expanded), key=lambda h: -(h.rerank_score or 0.0))
        kept = ranked[:top_n]
        out: list[SearchHit] = list(kept)
        # A candidate that amends a kept clause (or is amended by one) must not be cut: the answer
        # would quote the old term. Keep it right after its partner.
        for other in ranked[top_n:]:
            partner = next((k for k in kept if _amends(other, k) or _amends(k, other)), None)
            if partner is not None:
                pos = out.index(partner) + 1
                while pos < len(out) and (out[pos].expanded or out[pos] not in kept):
                    pos += 1
                out.insert(pos, other)
        leftovers = []
        for exp in (h for h in hits if h.expanded):
            anchor = next((h for h in ranked if _related(h, exp)), None)
            if anchor is not None and anchor in out:
                # after the anchor and any expanded hits already placed behind it
                pos = out.index(anchor) + 1
                while pos < len(out) and out[pos].expanded:
                    pos += 1
                out.insert(pos, exp)
            else:
                leftovers.append(exp)
        return out + leftovers
