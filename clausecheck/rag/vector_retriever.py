"""Semantic retrieval over the vector store."""

from clausecheck.rag.types import SearchHit


class VectorRetriever:
    """Embeds a question and returns the nearest chunks."""

    def __init__(self, embedder, store):
        self.embedder = embedder
        self.store = store

    def retrieve(self, query: str, supplier_id: str | None = None, k: int = 5) -> list[SearchHit]:
        """Top-`k` chunks for `query`, optionally only from one supplier."""
        return self.store.search(self.embedder.embed_query(query), k, supplier_id)
