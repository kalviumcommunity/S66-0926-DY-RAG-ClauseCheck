"""In-memory BM25 keyword index that keeps exact tokens like `net`, `45`, `a-114`, `$1,250.00`."""

import re
import sqlite3
from dataclasses import asdict

from rank_bm25 import BM25Okapi

from clausecheck.ingest.models import Chunk
from clausecheck.rag.types import SearchHit
from clausecheck.store import sqlite as db

TOKEN_RE = re.compile(r"\$?\d+(?:,\d{3})*(?:\.\d+)?%?|[a-z0-9]+(?:-[a-z0-9]+)*")


def tokenize(text: str) -> list[str]:
    """Lowercase tokens. No stemming and no stop-word removal, because exact tokens matter."""
    return TOKEN_RE.findall(text.lower())


def _metadata(chunk: Chunk) -> dict:
    data = asdict(chunk)
    data.pop("chunk_id")
    data.pop("text")
    return data


class _Part:
    """One BM25 index over a list of chunks."""

    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self.tokens = [tokenize(c.text) for c in chunks]
        self.token_sets = [set(t) for t in self.tokens]
        self.bm25 = BM25Okapi(self.tokens) if any(self.tokens) else None

    def search(self, query: str, k: int) -> list[SearchHit]:
        q = tokenize(query)
        if self.bm25 is None or not q:
            return []
        scores = self.bm25.get_scores(q)
        wanted = set(q)
        # Token overlap, not "score > 0": on small indexes Okapi IDF can be zero or negative.
        ranked = sorted(
            (i for i, tokens in enumerate(self.token_sets) if tokens & wanted),
            key=lambda i: (-scores[i], i),
        )
        return [
            SearchHit(
                chunk_id=self.chunks[i].chunk_id,
                score=float(scores[i]),
                text=self.chunks[i].text,
                metadata=_metadata(self.chunks[i]),
                source="bm25",
            )
            for i in ranked[:k]
        ]


class BM25Index:
    """One index over all chunks, plus one per supplier."""

    def __init__(self, chunks: list[Chunk]):
        self._size = len(chunks)
        self._all = _Part(list(chunks))
        by_supplier: dict[str, list[Chunk]] = {}
        for chunk in chunks:
            by_supplier.setdefault(chunk.supplier_id, []).append(chunk)
        self._by_supplier = {sid: _Part(cs) for sid, cs in by_supplier.items()}

    @classmethod
    def from_conn(cls, conn: sqlite3.Connection) -> "BM25Index":
        """Build the index from every chunk in SQLite."""
        return cls(db.get_chunks(conn))

    def search(self, query: str, k: int = 20, supplier_id: str | None = None) -> list[SearchHit]:
        """Top-`k` chunks sharing a token with the query; an unknown supplier gives `[]`."""
        part = self._all if supplier_id is None else self._by_supplier.get(supplier_id)
        return part.search(query, k) if part else []

    def size(self) -> int:
        """Number of chunks in the index."""
        return self._size
