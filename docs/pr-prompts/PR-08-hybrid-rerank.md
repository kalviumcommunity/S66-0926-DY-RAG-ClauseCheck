# PR 8 · BM25, hybrid fusion, amendment expansion, re-ranking and supplier detection

**Branch:** `a-hybrid-rerank` · **Owner:** Diya (Data, Retrieval & Platform Foundations) · **Week:** 3 · **Depends on:** PR 7

## Context

Exact tokens matter in contracts. "Net 45", "7.2", "A-114" and "$1,250.00" must match literally, not only semantically. So retrieval becomes:

1. **Supplier detection**: a fuzzy match against names and aliases.
2. **Hybrid search**: vector and BM25 (per supplier and global), fused with **Reciprocal Rank Fusion**.
3. **Amendment expansion**: an amended clause always arrives together with the original it changes.
4. **Cross-encoder re-ranking** of the candidates.

This PR closes week 3 with an **ablation table**. Target: **recall@5 ≥ 0.85** on the tuning split.

Read before starting:
- `docs/architecture/rag-architecture-design.md`: query pipeline steps 2–5, design principles 3 and 5, decisions D1–D6
- `docs/architecture/tdd.md` §4.2 and §16
- `docs/data/data-validation-report.md` DV-10 (amendment chains)

## Scope (only these files)

| Path | Action |
|---|---|
| `clausecheck/store/bm25_index.py` | add |
| `clausecheck/rag/hybrid_retriever.py` | add |
| `clausecheck/rag/reranker.py` | add |
| `clausecheck/rag/supplier_detector.py` | add |
| `clausecheck/ingest/__main__.py` | modify: build BM25 once after ingest and print its size (validation only; BM25 stays in memory) |
| `clausecheck/core/config.py`, `.env.example` | modify: see spec |
| `eval/run_eval.py` | modify: retrievers `bm25`, `hybrid`, `hybrid_rerank`; `--supplier-filter on\|off`; `--ablation` |
| `requirements.txt` | modify: add `rank-bm25`, `rapidfuzz` |
| `tests/unit/test_bm25.py`, `tests/unit/test_rrf.py`, `tests/unit/test_reranker.py`, `tests/unit/test_supplier_detector.py`, `tests/unit/test_ablation.py`, `tests/integration/test_hybrid_retrieval.py` | add |
| `docs/architecture/rag-architecture-design.md` | modify: final k values, RRF k, re-rank sizes and the ablation result |

## Specification

### Settings to add

- `rrf_k: int = 60`
- `vector_k: int = 20`
- `bm25_k: int = 20`
- `rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"`
- `rerank_candidates: int = 20`
- `rerank_top_n: int = 5`
- `supplier_match_min: int = 85`

### `clausecheck/store/bm25_index.py`

- `TOKEN_RE = re.compile(r"\$?\d+(?:,\d{3})*(?:\.\d+)?%?|[a-z0-9]+(?:-[a-z0-9]+)*")`
- `tokenize(text: str) -> list[str]` runs `TOKEN_RE.findall(text.lower())`. No stemming and no stop-word removal, because exact tokens matter.
- `class BM25Index`:
  - `__init__(self, chunks: list[Chunk])` builds one `BM25Okapi` over all chunks, plus one per `supplier_id`.
  - `@classmethod from_conn(cls, conn)` builds from every chunk in SQLite.
  - `search(query, k=20, supplier_id=None) -> list[SearchHit]` uses the supplier's index when given (an unknown supplier returns `[]`). It returns hits with `source="bm25"`, the raw score, the chunk text and metadata. It returns **only chunks that share at least one token with the query**, sorted by score descending with ties in corpus order. Use the token-overlap rule rather than "score > 0": on small per-supplier indexes, Okapi IDF can be zero or negative even for a term that matches.
  - `size() -> int` returns the number of chunks.

### `clausecheck/rag/hybrid_retriever.py`

- `rrf_fuse(rank_lists: list[list[str]], k: int = 60) -> list[tuple[str, float]]`: `score(id) = Σ 1 / (k + rank)`, where rank is 1-based within each list. Sorted by score descending; ties keep the order of first appearance.
- `CLAUSE_REF_RE = re.compile(r"(?:Section|Clause|Paragraph)\s+(\d+(?:\.\d+)*)", re.I)`
- `expand_amendments(hits: list[SearchHit], conn) -> list[SearchHit]` returns `hits` followed by any added chunks (no duplicates). For each hit's document:
  - **If it has a parent** (`documents.parent_doc_id`): add the parent's chunks whose `clause_no` is referenced in the hit's text (via `CLAUSE_REF_RE`) or equals the hit's `clause_no`.
  - **If it has children** (documents whose `parent_doc_id` is this doc): add the child chunks whose text references the hit's `clause_no`.
  - Follow chains up to 3 levels deep.
  - Added hits get `expanded=True`, `source="expansion"`, `score=0.0`, and the chunk's text and metadata.
- `class HybridRetriever`:
  - `__init__(self, vector_retriever, bm25: BM25Index, conn, vector_k=20, bm25_k=20, rrf_k=60, expand=True)`
  - `retrieve(query, supplier_id=None, k=20) -> list[SearchHit]` runs both searches with the same `supplier_id`, fuses the ranked IDs, and returns the top `k` as hits with `source="hybrid"` and `score` set to the RRF score, carrying text and metadata from whichever search found them. When `expand` is true, it then applies `expand_amendments` (expanded hits are added after the top `k`).
  - `@classmethod from_settings(cls, settings, conn)`

### `clausecheck/rag/reranker.py`

`class Reranker`:
- `__init__(self, scorer: Callable[[list[tuple[str, str]]], list[float]] | None = None, model_name: str = ...)`: if `scorer` is `None`, it lazily loads `sentence_transformers.CrossEncoder(model_name)` on first use and uses its `predict`.
- `rerank(query, hits, top_n=5) -> list[SearchHit]` scores `(query, hit.text)` pairs, sets `rerank_score`, and returns the top `top_n` by `rerank_score` descending. **Expanded hits are always kept** right after the hit they belong to, even beyond `top_n`, so an amendment never loses its original. `[]` returns `[]`.

### `clausecheck/rag/supplier_detector.py`

`class SupplierDetector`:
- `__init__(self, suppliers: list[dict], min_score: int = 85)`, where each dict holds `supplier_id`, `display_name` and `aliases: list[str]`
- `@classmethod from_conn(cls, conn, min_score=85)` uses `sqlite.list_suppliers`
- `detect(question: str, previous: str | None = None) -> str | None`: for every name (the display name plus aliases, at least 3 characters), it computes `rapidfuzz.fuzz.partial_ratio(name.lower(), question.lower())`. The best score at or above `min_score` wins, and ties go to the longer name. If nothing matches, it returns `previous`. A clear new match **replaces** `previous`.

### `eval/run_eval.py` (modified)

- Registry factories now take `supplier_filter: bool = True`. Update `vector` accordingly. With the filter off, pass `supplier_id=None`.
- `bm25`, `hybrid` and `hybrid_rerank` build from settings. `hybrid_rerank` retrieves `rerank_candidates` and then re-ranks.
- `--ablation` runs the 4 retrievers × filter on/off on the chosen split. It writes `{date}_ablation_{split}.json` and `.md` and prints the table.
- `ablation_table(results: dict[tuple[str, bool], dict]) -> str` returns a Markdown table with columns `retriever | supplier filter | recall@5 | MRR`. Rows are sorted by recall@5 descending, and numbers are shown with 3 decimals.

## Tests

### `tests/unit/test_bm25.py`

```python
from clausecheck.store.bm25_index import BM25Index, tokenize
from tests.helpers import make_chunk


def test_tokenize_keeps_exact_tokens():
    assert tokenize("Payment is due Net 45 days.") == ["payment", "is", "due", "net", "45", "days"]
    assert tokenize("$1,250.00 and 7.2% for A-114, total 1,250.") == [
        "$1,250.00", "and", "7.2%", "for", "a-114", "total", "1,250"]


def _index():
    return BM25Index([
        make_chunk(chunk_id="c1", text="Payment is due Net 45 days from invoice.", supplier_id="S-ACME"),
        make_chunk(chunk_id="c2", text="The initial term is two years.", supplier_id="S-ACME"),
        make_chunk(chunk_id="c3", text="Unit price for A-114 is $1,250.00.", supplier_id="S-ACME"),
        make_chunk(chunk_id="c4", text="Payment is due Net 30 days.", supplier_id="S-BETA"),
        make_chunk(chunk_id="c5", text="Liability is capped at fees paid.", supplier_id="S-BETA"),
    ])


def test_literal_match_ranks_first():
    hits = _index().search("net 45", k=3)
    assert hits[0].chunk_id == "c1" and hits[0].source == "bm25"


def test_exact_value_tokens():
    assert _index().search("A-114 price", k=1)[0].chunk_id == "c3"


def test_supplier_index_excludes_others():
    hits = _index().search("payment net days", k=5, supplier_id="S-BETA")
    assert {h.metadata["supplier_id"] for h in hits} == {"S-BETA"}
    assert _index().search("payment", supplier_id="S-NONE") == []


def test_chunks_without_query_tokens_dropped():
    assert _index().search("zebra", k=5) == []
```

### `tests/unit/test_rrf.py`

```python
import pytest

from clausecheck.rag.hybrid_retriever import rrf_fuse


def test_rrf_order_and_scores():
    fused = rrf_fuse([["a", "b", "c"], ["b", "c", "d"]], k=60)
    assert [i for i, _ in fused] == ["b", "c", "a", "d"]
    assert dict(fused)["b"] == pytest.approx(1 / 62 + 1 / 61)


def test_rrf_single_list_keeps_order():
    assert [i for i, _ in rrf_fuse([["x", "y", "z"]])] == ["x", "y", "z"]


def test_rrf_empty():
    assert rrf_fuse([[], []]) == []
```

### `tests/unit/test_reranker.py`

```python
from clausecheck.rag.reranker import Reranker
from clausecheck.rag.types import SearchHit


def scorer(pairs):
    return [float(text.count("payment")) for _, text in pairs]


def test_rerank_orders_by_score_and_cuts_top_n():
    hits = [SearchHit("a", 0.1, "term two years"), SearchHit("b", 0.1, "payment payment"),
            SearchHit("c", 0.1, "payment due")]
    out = Reranker(scorer=scorer).rerank("payment terms", hits, top_n=2)
    assert [h.chunk_id for h in out] == ["b", "c"]
    assert out[0].rerank_score == 2.0


def test_expanded_hits_follow_their_parent_hit():
    hits = [SearchHit("orig", 0.1, "payment payment"), SearchHit("x", 0.1, "payment"),
            SearchHit("amend", 0.0, "nothing", expanded=True, source="expansion")]
    out = Reranker(scorer=scorer).rerank("q", hits, top_n=1)
    assert [h.chunk_id for h in out] == ["orig", "amend"]


def test_empty():
    assert Reranker(scorer=scorer).rerank("q", [], top_n=5) == []
```

For `test_expanded_hits_follow_their_parent_hit`, "belongs to" means: an expanded hit sits right after the highest-ranked non-expanded hit whose document is its parent or child. With no metadata (as in this test), it attaches to the top hit.

### `tests/unit/test_supplier_detector.py`

```python
from clausecheck.rag.supplier_detector import SupplierDetector

SUPPLIERS = [
    {"supplier_id": "S-ACME", "display_name": "Acme Corp", "aliases": ["Acme", "ACME Corporation"]},
    {"supplier_id": "S-BETA", "display_name": "Beta Industries", "aliases": ["Beta"]},
]


def d():
    return SupplierDetector(SUPPLIERS, min_score=85)


def test_exact_and_alias():
    assert d().detect("What are the payment terms with Acme Corp?") == "S-ACME"
    assert d().detect("Does Beta have a liability cap?") == "S-BETA"


def test_misspelling():
    assert d().detect("Payment terms for Acme Corproation?") == "S-ACME"


def test_no_supplier():
    assert d().detect("What is a typical payment term?") is None


def test_follow_up_keeps_previous_and_new_name_overrides():
    assert d().detect("And their notice period?", previous="S-ACME") == "S-ACME"
    assert d().detect("What about Beta Industries?", previous="S-ACME") == "S-BETA"
```

### `tests/unit/test_ablation.py`

```python
from eval.run_eval import ablation_table


def test_ablation_table_sorted_markdown():
    results = {("vector", True): {"recall_at_k": 0.71, "mrr": 0.5},
               ("hybrid_rerank", True): {"recall_at_k": 0.88, "mrr": 0.7}}
    table = ablation_table(results)
    lines = [l for l in table.splitlines() if l.startswith("|")]
    assert "recall@5" in lines[0]
    assert "hybrid_rerank" in lines[2] and "0.880" in lines[2]
```

### `tests/integration/test_hybrid_retrieval.py`

```python
from clausecheck.rag.hybrid_retriever import HybridRetriever, expand_amendments
from clausecheck.rag.types import SearchHit
from clausecheck.store import sqlite as db
from clausecheck.store.bm25_index import BM25Index
from tests.helpers import make_chunk

ORIG = make_chunk(chunk_id="orig:p1:2_1", doc_id="orig", clause_no="2.1",
                  text="2.1 Payment is due Net 45 days from the invoice date.")
TERM = make_chunk(chunk_id="orig:p1:3_1", doc_id="orig", clause_no="3.1", text="3.1 The term is two years.")
AMEND = make_chunk(chunk_id="amd:p1:1", doc_id="amd", clause_no="1", doc_type="amendment", parent_doc_id="orig",
                   text="1. Section 2.1 of the Agreement is amended to read: Payment is due Net 30 days.")


def _conn(tmp_path):
    conn = db.connect(tmp_path / "h.db")
    db.init_db(conn)
    db.upsert_document(conn, {"doc_id": "orig", "supplier_id": "S-ACME", "doc_type": "contract"})
    db.upsert_document(conn, {"doc_id": "amd", "supplier_id": "S-ACME", "doc_type": "amendment",
                              "parent_doc_id": "orig"})
    db.replace_chunks(conn, "orig", [ORIG, TERM])
    db.replace_chunks(conn, "amd", [AMEND])
    return conn


def _hit(c):
    return SearchHit(c.chunk_id, 1.0, c.text, {"doc_id": c.doc_id, "clause_no": c.clause_no,
                                                "supplier_id": c.supplier_id})


def test_amendment_hit_pulls_in_original_clause(tmp_path):
    out = expand_amendments([_hit(AMEND)], _conn(tmp_path))
    assert [h.chunk_id for h in out] == ["amd:p1:1", "orig:p1:2_1"]
    assert out[1].expanded and out[1].source == "expansion"


def test_original_hit_pulls_in_amendment(tmp_path):
    out = expand_amendments([_hit(ORIG)], _conn(tmp_path))
    assert "amd:p1:1" in [h.chunk_id for h in out]
    assert "orig:p1:3_1" not in [h.chunk_id for h in out]


class FakeVector:
    def __init__(self, ids):
        self.ids = ids

    def retrieve(self, query, supplier_id=None, k=20):
        return [_hit(c) for c in [ORIG, TERM, AMEND] if c.chunk_id in self.ids][:k]


def test_hybrid_fuses_both_lists(tmp_path):
    conn = _conn(tmp_path)
    retriever = HybridRetriever(FakeVector(["orig:p1:3_1"]), BM25Index.from_conn(conn), conn, expand=False)
    ids = [h.chunk_id for h in retriever.retrieve("net 45 payment", supplier_id="S-ACME", k=3)]
    assert "orig:p1:2_1" in ids and "orig:p1:3_1" in ids
    assert all(h.source == "hybrid" for h in retriever.retrieve("net 45", k=3))


def test_hybrid_with_expansion_returns_amendment_with_original(tmp_path):
    conn = _conn(tmp_path)
    retriever = HybridRetriever(FakeVector([]), BM25Index.from_conn(conn), conn, expand=True)
    ids = [h.chunk_id for h in retriever.retrieve("Net 30 amended", k=1)]
    assert ids[0] == "amd:p1:1" and "orig:p1:2_1" in ids
```

## Manual checks

1. Run `pytest -q`. Every test should pass.
2. Run `python -m eval.run_eval --split tune --stage retrieval --ablation`. You should get an 8-row table, with `hybrid_rerank` and the filter on at or near the top. **recall@5 ≥ 0.85** is the target; if it's not reached, write down why and what you'll try next.
3. In a Python shell, ask a real question containing an exact value (for example a SKU or "Net 45"). The clause with that literal text should be in the top 3.
4. Ask about a real amended term. The amendment chunk and the original clause should both come back.
5. Ask using a misspelled supplier name. The detector should return the right `supplier_id`.
6. The first `hybrid_rerank` run downloads the cross-encoder (about 90 MB). Time a second query; re-ranking 20 candidates should take well under 1 second on CPU.

## Definition of done

The full retrieval stack works, the ablation table is in the PR description and the design doc, and recall@5 is at least 0.85 on tuning, or the gap is explained.
