"""ChromaDB vector store, one collection per index version and embedding model."""

import re
from dataclasses import asdict
from pathlib import Path

from clausecheck.ingest.models import Chunk
from clausecheck.rag.types import SearchHit

NULLABLE_METADATA = (
    "section",
    "clause_no",
    "effective_date",
    "parent_doc_id",
    "token_start",
    "token_end",
)


def active_model_name(settings) -> str:
    """The embedding model selected by `EMBED_PROVIDER`; it names the cache and collection."""
    return (
        settings.local_embed_model if settings.embed_provider == "local" else settings.embed_model
    )


def collection_name(index_version: str, model_name: str) -> str:
    """A Chroma-safe collection name that includes the embedding model."""
    name = re.sub(r"[^a-zA-Z0-9_-]", "_", f"chunks_{index_version}_{model_name}")[:63]
    return name.strip("_-")


class VectorStore:
    """Chunk vectors with metadata, searchable by cosine similarity and supplier."""

    def __init__(self, path: Path, collection: str):
        import chromadb

        # Chroma needs 3 to 512 safe characters, starting and ending with a letter or digit
        self.collection_name = re.sub(r"[^a-zA-Z0-9_-]", "_", collection).strip("_-").ljust(3, "x")
        self._client = chromadb.PersistentClient(
            path=str(path), settings=chromadb.Settings(anonymized_telemetry=False)
        )
        self._collection = self._open()

    def _open(self):
        return self._client.get_or_create_collection(
            self.collection_name, metadata={"hnsw:space": "cosine"}
        )

    def reset(self) -> None:
        """Delete and recreate the collection."""
        self._client.delete_collection(self.collection_name)
        self._collection = self._open()

    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        """Insert or replace chunks with their vectors."""
        if not chunks:
            return
        metadatas = []
        for chunk in chunks:
            data = asdict(chunk)
            data.pop("chunk_id")
            data.pop("text")
            metadatas.append({k: "" if v is None else v for k, v in data.items()})
        self._collection.upsert(
            ids=[c.chunk_id for c in chunks],
            embeddings=vectors,
            documents=[c.text for c in chunks],
            metadatas=metadatas,
        )

    def search(
        self, vector: list[float], k: int, supplier_id: str | None = None
    ) -> list[SearchHit]:
        """Top-`k` chunks by cosine similarity, optionally only from one supplier."""
        total = self._collection.count()
        if total == 0:
            return []
        result = self._collection.query(
            query_embeddings=[vector],
            n_results=min(k, total),
            where={"supplier_id": supplier_id} if supplier_id else None,
            include=["documents", "metadatas", "distances"],
        )
        hits = []
        for chunk_id, text, meta, distance in zip(
            result["ids"][0],
            result["documents"][0],
            result["metadatas"][0],
            result["distances"][0],
            strict=True,
        ):
            meta = {
                k_: (None if k_ in NULLABLE_METADATA and v == "" else v) for k_, v in meta.items()
            }
            hits.append(
                SearchHit(
                    chunk_id=chunk_id, score=1 - distance, text=text, metadata=meta, source="vector"
                )
            )
        return sorted(hits, key=lambda h: h.score, reverse=True)

    def delete_doc(self, doc_id: str) -> None:
        """Remove every chunk of a document."""
        self._collection.delete(where={"doc_id": doc_id})

    def count(self) -> int:
        """Number of stored chunks."""
        return self._collection.count()

    @classmethod
    def from_settings(cls, settings) -> "VectorStore":
        """The store at `INDEX_DIR/chroma`, for the configured index version and model."""
        name = collection_name(settings.index_version, active_model_name(settings))
        return cls(Path(settings.index_dir) / "chroma", name)
