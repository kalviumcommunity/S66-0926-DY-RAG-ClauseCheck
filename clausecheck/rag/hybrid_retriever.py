"""Hybrid retrieval: vector search and BM25 fused with RRF, plus amendment expansion."""

import re
import sqlite3
from dataclasses import asdict

from clausecheck.rag.types import SearchHit
from clausecheck.store import sqlite as db
from clausecheck.store.bm25_index import BM25Index

CLAUSE_REF_RE = re.compile(r"(?:Section|Clause|Paragraph)\s+(\d+(?:\.\d+)*)", re.I)
MAX_CHAIN_DEPTH = 3


def rrf_fuse(rank_lists: list[list[str]], k: int = 60) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion: score = sum of 1 / (k + rank), ranks being 1-based per list."""
    scores: dict[str, float] = {}
    for ranks in rank_lists:
        for rank, chunk_id in enumerate(ranks, 1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1 / (k + rank)
    # dicts keep insertion order and sorted() is stable, so ties keep first appearance
    return sorted(scores.items(), key=lambda item: -item[1])


def _expansion_hit(chunk) -> SearchHit:
    data = asdict(chunk)
    data.pop("chunk_id")
    data.pop("text")
    return SearchHit(
        chunk_id=chunk.chunk_id,
        score=0.0,
        text=chunk.text,
        metadata=data,
        source="expansion",
        expanded=True,
    )


def expand_amendments(hits: list[SearchHit], conn: sqlite3.Connection) -> list[SearchHit]:
    """Return `hits` followed by the amended or amending clauses they are linked to.

    A hit in an amendment pulls in the parent's clauses it references by number ("Section 6.1").
    A hit in an original pulls in the child clauses that reference its clause number.
    Chains are followed up to 3 levels.
    """
    out = list(hits)
    seen = {h.chunk_id for h in hits}
    frontier = []
    for hit in hits:
        meta = hit.metadata
        if "doc_id" not in meta:
            chunk = db.get_chunk(conn, hit.chunk_id)
            if chunk is None:
                continue
            meta = {"doc_id": chunk.doc_id, "clause_no": chunk.clause_no}
        frontier.append((meta["doc_id"], meta.get("clause_no"), hit.text))

    for _ in range(MAX_CHAIN_DEPTH):
        next_frontier = []
        for doc_id, clause_no, text in frontier:
            doc = db.get_document(conn, doc_id)
            found = []
            if doc and doc.get("parent_doc_id"):
                # Only clauses the amendment names. An amendment numbers its own clauses (its
                # 4.2 is "Counterparts"), so sharing a number with the parent means nothing.
                refs = set(CLAUSE_REF_RE.findall(text))
                found += [
                    c
                    for c in db.get_chunks(conn, doc_id=doc["parent_doc_id"])
                    if c.clause_no and c.clause_no in refs
                ]
            if clause_no:
                for child in conn.execute(
                    "SELECT doc_id FROM documents WHERE parent_doc_id=?", (doc_id,)
                ):
                    found += [
                        c
                        for c in db.get_chunks(conn, doc_id=child["doc_id"])
                        if clause_no in CLAUSE_REF_RE.findall(c.text)
                    ]
            for chunk in found:
                if chunk.chunk_id in seen:
                    continue
                seen.add(chunk.chunk_id)
                out.append(_expansion_hit(chunk))
                next_frontier.append((chunk.doc_id, chunk.clause_no, chunk.text))
        frontier = next_frontier
        if not frontier:
            break
    return out


class HybridRetriever:
    """Vector and BM25 search with the same supplier filter, fused with RRF."""

    def __init__(
        self,
        vector_retriever,
        bm25: BM25Index,
        conn: sqlite3.Connection,
        vector_k: int = 20,
        bm25_k: int = 20,
        rrf_k: int = 60,
        expand: bool = True,
    ):
        self.vector_retriever = vector_retriever
        self.bm25 = bm25
        self.conn = conn
        self.vector_k = vector_k
        self.bm25_k = bm25_k
        self.rrf_k = rrf_k
        self.expand = expand

    def retrieve(self, query: str, supplier_id: str | None = None, k: int = 20) -> list[SearchHit]:
        """Top `k` fused hits; expanded amendment hits are added after them."""
        vector_hits = self.vector_retriever.retrieve(query, supplier_id, k=self.vector_k)
        bm25_hits = self.bm25.search(query, self.bm25_k, supplier_id)
        by_id: dict[str, SearchHit] = {}
        for hit in [*vector_hits, *bm25_hits]:
            by_id.setdefault(hit.chunk_id, hit)
        fused = rrf_fuse(
            [[h.chunk_id for h in vector_hits], [h.chunk_id for h in bm25_hits]], self.rrf_k
        )
        hits = [
            SearchHit(
                chunk_id=chunk_id,
                score=score,
                text=by_id[chunk_id].text,
                metadata=by_id[chunk_id].metadata,
                source="hybrid",
            )
            for chunk_id, score in fused[:k]
        ]
        return expand_amendments(hits, self.conn) if self.expand else hits

    @classmethod
    def from_settings(cls, settings, conn: sqlite3.Connection) -> "HybridRetriever":
        """Build the retriever, with its embedder, vector store and BM25 index, from settings."""
        from clausecheck.ingest.embedder import Embedder
        from clausecheck.rag.vector_retriever import VectorRetriever
        from clausecheck.store.vector_store import VectorStore

        vector = VectorRetriever(
            Embedder.from_settings(settings, conn), VectorStore.from_settings(settings)
        )
        return cls(
            vector,
            BM25Index.from_conn(conn),
            conn,
            vector_k=settings.vector_k,
            bm25_k=settings.bm25_k,
            rrf_k=settings.rrf_k,
        )
