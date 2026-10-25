"""Embeddings with a SQLite cache keyed by text and model."""

import hashlib
import json
import sqlite3
from collections.abc import Callable

from clausecheck.store.vector_store import active_model_name

EmbedFn = Callable[[list[str]], list[list[float]]]
LOOKUP_CHUNK = 500  # stays under SQLite's variable limit


class Embedder:
    """Embeds texts in batches, sending only cache misses to `embed_fn`."""

    def __init__(
        self, embed_fn: EmbedFn, conn: sqlite3.Connection, model_name: str, batch_size: int = 32
    ):
        self.embed_fn = embed_fn
        self.conn = conn
        self.model_name = model_name
        self.batch_size = batch_size
        with conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS embedding_cache ("
                "key TEXT PRIMARY KEY, model TEXT, dim INTEGER, vector TEXT)"
            )

    def _key(self, text: str) -> str:
        return hashlib.sha256((self.model_name + "\x00" + text).encode()).hexdigest()

    def _lookup(self, keys: list[str]) -> dict[str, list[float]]:
        found: dict[str, list[float]] = {}
        for i in range(0, len(keys), LOOKUP_CHUNK):
            part = keys[i : i + LOOKUP_CHUNK]
            marks = ",".join("?" for _ in part)
            for row in self.conn.execute(
                f"SELECT key, vector FROM embedding_cache WHERE key IN ({marks})", part
            ):
                found[row[0]] = json.loads(row[1])
        return found

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Vectors for `texts`, in input order. Cached texts are never sent to the API."""
        if not texts:
            return []
        keys = [self._key(t) for t in texts]
        vectors = self._lookup(list(dict.fromkeys(keys)))
        misses = {k: t for k, t in zip(keys, texts, strict=True) if k not in vectors}
        items = list(misses.items())
        for i in range(0, len(items), self.batch_size):
            batch = items[i : i + self.batch_size]
            new = self.embed_fn([t for _, t in batch])
            if len(new) != len(batch):
                raise ValueError(f"embed_fn returned {len(new)} vectors for {len(batch)} texts")
            with self.conn:
                self.conn.executemany(
                    "INSERT OR REPLACE INTO embedding_cache (key, model, dim, vector) "
                    "VALUES (?, ?, ?, ?)",
                    [
                        (k, self.model_name, len(v), json.dumps(v))
                        for (k, _), v in zip(batch, new, strict=True)
                    ],
                )
            vectors.update({k: v for (k, _), v in zip(batch, new, strict=True)})
        return [vectors[k] for k in keys]

    def embed_query(self, text: str) -> list[float]:
        """Vector for a question; queries are cached like documents."""
        return self.embed_texts([text])[0]

    @classmethod
    def from_settings(cls, settings, conn: sqlite3.Connection) -> "Embedder":
        """Build the embedder for `EMBED_PROVIDER`. There is no automatic switch between them."""
        model = active_model_name(settings)
        if settings.embed_provider == "local":
            embed_fn = _local_embed_fn(model)
        else:
            from clausecheck.llm.client import LLMClient
            from clausecheck.llm.gemini import GeminiProvider

            provider = GeminiProvider(
                settings.gemini_api_key,
                settings.gemini_model,
                settings.llm_timeout_seconds,
                embed_model=model,
            )
            embed_fn = LLMClient(
                primary=provider,
                max_retries=settings.llm_max_retries,
                wait_seconds=settings.llm_retry_wait_seconds,
            ).embed
        return cls(embed_fn, conn, model, settings.embed_batch)


def _local_embed_fn(model_name: str) -> EmbedFn:
    holder: dict = {}

    def embed(texts: list[str]) -> list[list[float]]:
        if "model" not in holder:  # load lazily: the import and download are slow
            from sentence_transformers import SentenceTransformer

            holder["model"] = SentenceTransformer(model_name)
        return holder["model"].encode(texts, normalize_embeddings=True).tolist()

    return embed
