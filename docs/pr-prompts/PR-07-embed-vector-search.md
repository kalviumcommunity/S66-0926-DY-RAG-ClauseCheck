# PR 7 · Embeddings and vector search

**Branch:** `a-embed-vector-search` · **Owner:** Diya (Data, Retrieval & Platform Foundations) · **Week:** 3 · **Depends on:** PR 5 and PR 6

## Context

Every chunk gets a vector, which is stored in ChromaDB with its metadata, so ClauseCheck can do top-k semantic search with a supplier filter. Embeddings are cached in SQLite by text and model, so re-indexing never re-embeds unchanged text. This PR also records the **vector-only recall@5 baseline** that PR 8 has to beat.

Read before starting:
- `docs/architecture/rag-architecture-design.md`: the embeddings and vector store decisions
- `docs/architecture/tdd.md` §4.2 and §5 (`ingest/embedder`, `store/vector_store`)
- `docs/02-project-description.md` §9 (Gemini embeddings, with sentence-transformers as the local alternative)

**One rule:** vectors from different models must never share an index. The embedding model is **chosen by setting** (`EMBED_PROVIDER=gemini|local`) and is part of the collection name. There is **no automatic switch** from one model to the other in the middle of a run. If Gemini embeddings are unavailable, set `EMBED_PROVIDER=local` and rebuild.

## Scope (only these files)

| Path | Action |
|---|---|
| `clausecheck/rag/types.py` | add |
| `clausecheck/ingest/embedder.py` | add |
| `clausecheck/store/vector_store.py` | add |
| `clausecheck/rag/vector_retriever.py` | add |
| `clausecheck/ingest/indexer.py` | modify: use `embedder` and `vector_store` when given |
| `clausecheck/ingest/__main__.py` | modify: build the embedder and store from settings; add `--no-embed` |
| `clausecheck/core/config.py`, `.env.example` | modify: see spec |
| `eval/run_eval.py` | modify: register the `vector` retriever |
| `requirements.txt` | modify: add `chromadb`, `sentence-transformers` |
| `tests/unit/test_embedder.py`, `tests/unit/test_vector_store.py`, `tests/unit/test_vector_retriever.py`, `tests/integration/test_index_vectors.py` | add |

## Specification

### `clausecheck/rag/types.py`

```python
@dataclass
class SearchHit:
    chunk_id: str
    score: float
    text: str = ""
    metadata: dict = field(default_factory=dict)   # Chunk fields except text
    source: str = "vector"                          # vector | bm25 | hybrid | expansion
    expanded: bool = False
    rerank_score: float | None = None
```

### Settings to add

- `embed_provider: Literal["gemini", "local"] = "gemini"`
- `embed_model: str = "text-embedding-004"`
- `local_embed_model: str = "sentence-transformers/all-MiniLM-L6-v2"`
- `embed_batch: int = 32`
- `index_version: str = "v1"`
- `top_k: int = 5`

### `clausecheck/ingest/embedder.py`

```python
EmbedFn = Callable[[list[str]], list[list[float]]]

class Embedder:
    def __init__(self, embed_fn: EmbedFn, conn, model_name: str, batch_size: int = 32): ...
    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...
    @classmethod
    def from_settings(cls, settings, conn) -> "Embedder": ...
```

- The constructor creates the table `embedding_cache(key TEXT PRIMARY KEY, model TEXT, dim INTEGER, vector TEXT)` if it doesn't exist. The vector is stored as JSON.
- `key = sha256(model_name + "\x00" + text)`.
- `embed_texts` looks up every text in the cache, then sends **only the misses** to `embed_fn` in batches of `batch_size`. It stores the new vectors and returns vectors **in input order**. It returns `[]` for `[]` without calling `embed_fn`.
- `embed_query` uses the same path (queries are cached too).
- `from_settings`:
  - `gemini`: uses `LLMClient.from_settings(settings).embed` with `GeminiProvider` built with `embed_model`
  - `local`: lazily loads `SentenceTransformer(local_embed_model)` and returns `model.encode(texts, normalize_embeddings=True).tolist()`

### `clausecheck/store/vector_store.py`

```python
def collection_name(index_version: str, model_name: str) -> str: ...
class VectorStore:
    def __init__(self, path: Path, collection: str): ...
    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None: ...
    def search(self, vector: list[float], k: int, supplier_id: str | None = None) -> list[SearchHit]: ...
    def delete_doc(self, doc_id: str) -> None: ...
    def count(self) -> int: ...
    @classmethod
    def from_settings(cls, settings) -> "VectorStore": ...  # path = index_dir / "chroma"
```

- `collection_name` returns `f"chunks_{index_version}_{model}"`, with every character outside `[a-zA-Z0-9_-]` replaced by `_`, trimmed to 63 characters, and starting and ending with an alphanumeric character.
- Use `chromadb.PersistentClient(path=str(path))` and `get_or_create_collection(name, metadata={"hnsw:space": "cosine"})`.
- `upsert` uses `ids=chunk_id` and `documents=text`. Metadata is every other `Chunk` field, with `None` stored as `""` (Chroma rejects `None`) and bools kept as bools.
- `search` passes `where={"supplier_id": supplier_id}` when given. It returns hits sorted by `score = 1 - distance`, descending, with `source="vector"`. Metadata comes back with `""` turned into `None` for `section`, `clause_no`, `effective_date` and `parent_doc_id`.

### `clausecheck/rag/vector_retriever.py`

`VectorRetriever(embedder, store)` with `retrieve(query: str, supplier_id: str | None = None, k: int = 5) -> list[SearchHit]`.

### `indexer.index` (modified)

When both `embedder` and `vector_store` are given, after writing to SQLite it calls `vector_store.delete_doc(doc_id)`, embeds every chunk text, and upserts. The SQLite-only behaviour stays the same when they are `None`.

### `ingest/__main__.py` (modified)

Unless `--no-embed` or `--dry-run` is passed, build `Embedder.from_settings(settings, conn)` and `VectorStore.from_settings(settings)`, and pass them to `run_manifest`. Print the vector count at the end.

Also: `--rebuild` deletes and recreates the current Chroma collection before ingesting.

### `eval/run_eval.py` (modified)

Register `RETRIEVERS["vector"]`. It builds settings, the SQLite connection, the embedder, the store and a `VectorRetriever`, and returns `lambda q: [h.chunk_id for h in retriever.retrieve(q.question, q.supplier_id, k=max(k, 20))]`.

## Tests

### `tests/unit/test_embedder.py`

```python
import pytest

from clausecheck.ingest.embedder import Embedder
from clausecheck.store import sqlite as db


class FakeEmbed:
    def __init__(self, dim=4):
        self.dim = dim
        self.batches = []

    def __call__(self, texts):
        self.batches.append(list(texts))
        return [[float(len(t))] + [0.0] * (self.dim - 1) for t in texts]


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "e.db")
    db.init_db(c)
    return c


def test_batches_by_size(conn):
    fn = FakeEmbed()
    vectors = Embedder(fn, conn, "m1", batch_size=10).embed_texts([f"t{i}" for i in range(25)])
    assert len(vectors) == 25
    assert [len(b) for b in fn.batches] == [10, 10, 5]


def test_cache_hit_skips_api(conn):
    fn = FakeEmbed()
    e = Embedder(fn, conn, "m1", batch_size=10)
    first = e.embed_texts(["a", "bb"])
    calls = len(fn.batches)
    assert e.embed_texts(["a", "bb"]) == first
    assert len(fn.batches) == calls


def test_only_misses_are_sent_and_order_kept(conn):
    fn = FakeEmbed()
    e = Embedder(fn, conn, "m1")
    e.embed_texts(["a"])
    out = e.embed_texts(["ccc", "a", "bb"])
    assert fn.batches[-1] == ["ccc", "bb"]
    assert [v[0] for v in out] == [3.0, 1.0, 2.0]


def test_model_is_part_of_cache_key(conn):
    fn = FakeEmbed()
    Embedder(fn, conn, "m1").embed_texts(["a"])
    Embedder(fn, conn, "m2").embed_texts(["a"])
    assert len(fn.batches) == 2


def test_empty_input_no_call(conn):
    fn = FakeEmbed()
    assert Embedder(fn, conn, "m1").embed_texts([]) == []
    assert fn.batches == []


def test_embed_query(conn):
    assert len(Embedder(FakeEmbed(dim=6), conn, "m1").embed_query("hello")) == 6
```

### `tests/unit/test_vector_store.py`

```python
from clausecheck.store.vector_store import VectorStore, collection_name
from tests.helpers import make_chunk


def _store(tmp_path):
    return VectorStore(tmp_path / "chroma", "test_chunks")


def _chunks():
    return [
        make_chunk(chunk_id="a:p1:1", doc_id="a", supplier_id="S-ACME", clause_no="1"),
        make_chunk(chunk_id="a:p1:2", doc_id="a", supplier_id="S-ACME", clause_no="2"),
        make_chunk(chunk_id="b:p1:1", doc_id="b", supplier_id="S-BETA", clause_no="1"),
    ]


VECTORS = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]


def test_collection_name_is_safe():
    name = collection_name("v1", "sentence-transformers/all-MiniLM-L6-v2")
    assert name.startswith("chunks_v1_") and len(name) <= 63
    assert all(ch.isalnum() or ch in "_-" for ch in name)


def test_search_returns_nearest_first(tmp_path):
    store = _store(tmp_path)
    store.upsert(_chunks(), VECTORS)
    hits = store.search([0.9, 0.1, 0.0], k=2)
    assert [h.chunk_id for h in hits] == ["a:p1:1", "a:p1:2"]
    assert hits[0].score > hits[1].score
    assert hits[0].source == "vector" and hits[0].text


def test_supplier_filter(tmp_path):
    store = _store(tmp_path)
    store.upsert(_chunks(), VECTORS)
    hits = store.search([0.0, 0.0, 1.0], k=3, supplier_id="S-ACME")
    assert {h.metadata["supplier_id"] for h in hits} == {"S-ACME"}


def test_none_metadata_roundtrip(tmp_path):
    store = _store(tmp_path)
    store.upsert(_chunks(), VECTORS)
    hit = store.search([1.0, 0.0, 0.0], k=1)[0]
    assert hit.metadata["parent_doc_id"] is None
    assert hit.metadata["has_redaction"] is False


def test_upsert_is_idempotent_and_delete_doc(tmp_path):
    store = _store(tmp_path)
    store.upsert(_chunks(), VECTORS)
    store.upsert(_chunks(), VECTORS)
    assert store.count() == 3
    store.delete_doc("a")
    assert store.count() == 1
```

### `tests/unit/test_vector_retriever.py`

```python
from clausecheck.rag.vector_retriever import VectorRetriever
from clausecheck.store.vector_store import VectorStore
from tests.helpers import make_chunk


class FakeEmbedder:
    def embed_query(self, text):
        return [1.0, 0.0] if "payment" in text.lower() else [0.0, 1.0]


def test_retrieve_uses_query_vector_and_filter(tmp_path):
    store = VectorStore(tmp_path / "chroma", "r")
    store.upsert(
        [make_chunk(chunk_id="pay", supplier_id="S-ACME"), make_chunk(chunk_id="term", supplier_id="S-ACME"),
         make_chunk(chunk_id="other", supplier_id="S-BETA")],
        [[1.0, 0.0], [0.0, 1.0], [1.0, 0.0]],
    )
    hits = VectorRetriever(FakeEmbedder(), store).retrieve("What are the payment terms?", "S-ACME", k=1)
    assert [h.chunk_id for h in hits] == ["pay"]
```

### `tests/integration/test_index_vectors.py`

```python
import hashlib

from clausecheck.ingest.embedder import Embedder
from clausecheck.services.ingestion_service import run_manifest
from clausecheck.store import sqlite as db
from clausecheck.store.vector_store import VectorStore
from tests.fixtures.make_fixtures import MANIFEST_ROWS
from tests.helpers import write_manifest


class HashEmbed:
    calls = 0

    def __call__(self, texts):
        HashEmbed.calls += 1
        return [[b / 255 for b in hashlib.sha256(t.encode()).digest()[:8]] for t in texts]


def test_index_writes_one_vector_per_chunk_and_reuses_cache(tmp_path, fixture_paths):
    manifest, suppliers = write_manifest(tmp_path, fixture_paths, MANIFEST_ROWS)
    conn = db.connect(tmp_path / "v.db")
    db.init_db(conn)
    embedder = Embedder(HashEmbed(), conn, "hash-8", batch_size=16)
    store = VectorStore(tmp_path / "chroma", "it")

    run_manifest(manifest, conn, suppliers_path=suppliers, embedder=embedder, vector_store=store)
    assert store.count() == db.counts(conn)["chunks"] > 0

    calls = HashEmbed.calls
    run_manifest(manifest, conn, rebuild=True, embedder=embedder, vector_store=store)
    assert store.count() == db.counts(conn)["chunks"]
    assert HashEmbed.calls == calls  # every text served from the cache
```

## Manual checks

1. Run `pytest -q`. Every test should pass.
2. Run `python -m clausecheck.ingest --rebuild`, then `python -m clausecheck.ingest`. The second run should report everything `unchanged` and make no embedding calls.
3. Run `python -c "from clausecheck.core.config import get_settings; from clausecheck.store.vector_store import VectorStore; print(VectorStore.from_settings(get_settings()).count())"`. The count should equal `SELECT COUNT(*) FROM chunks`.
4. Run `python -m eval.run_eval --split tune --stage retrieval --retriever vector`. Record recall@5 and MRR in the PR description as **the baseline**, with index version and embed model.
5. In a Python shell, run one real question with a supplier filter and print the top 5 hits. Every `supplier_id` should match, and the text should look relevant.

## Definition of done

Every chunk is embedded and searchable, re-runs cost no embedding calls, the supplier filter works, and the baseline recall@5 is recorded.
