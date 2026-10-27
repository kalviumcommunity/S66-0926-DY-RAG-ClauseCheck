# PR 10 · Context builder and relevance gate

**Branch:** `b-context-relevance-gate` · **Owner:** Teammate (Generation, Application & Delivery) · **Week:** 4 · **Depends on:** PR 9

## Context

This PR sits between retrieval and the model. It does two jobs:
- turn the re-ranked hits into one numbered evidence block (`[C1]..[Cn]`) that fits a token budget, so every claim can later be traced to a clause
- decide whether the evidence is strong enough to answer at all (the relevance gate). **When evidence is weak, refusing is the correct outcome.**

`relevance_threshold` is only a placeholder (`0.0`) here. PR 11 picks the real value from a measured sweep.

Read before starting:
- `docs/architecture/rag-architecture-design.md`: query pipeline steps 6–7 and the design principles
- `docs/ux/ui-states.md`: refusal states

## Scope (only these files)

| Path | Action |
|---|---|
| `clausecheck/rag/context_builder.py` | add |
| `clausecheck/rag/relevance_gate.py` | add |
| `clausecheck/core/config.py`, `.env.example` | modify: `context_token_budget: int = 3000`, `relevance_threshold: float = 0.0` |
| `tests/unit/test_context_builder.py`, `tests/unit/test_relevance_gate.py` | add |

## Specification

### `clausecheck/rag/context_builder.py`

```python
@dataclass
class Context:
    text: str
    marker_map: dict[str, SearchHit]   # "C1" -> hit
    used: list[SearchHit]
    token_count: int

def build_context(hits: list[SearchHit], budget_tokens: int) -> Context: ...
```

- Each hit becomes a block:
  - The first line is `[C{n}] {title or doc_id} | page {page} | section {section or "-"} | clause {clause_no or "-"}`.
  - Add ` | AMENDMENT of {parent_doc_id}, effective {effective_date}` when `doc_type == "amendment"`, and ` | contains redacted values` when `has_redaction`.
  - Then the chunk text.
- Blocks are joined with a blank line. Markers are numbered from 1 in the order of the blocks **actually included**, so a skipped hit leaves no gap.
- Budget: add whole blocks in order while the running `count_tokens(text)` stays within `budget_tokens`. **Never split a block.** Always include the first block, even if it exceeds the budget. Skip a block that doesn't fit, but keep trying later, smaller ones.

### `clausecheck/rag/relevance_gate.py`

- `GateResult(passed: bool, reason: str | None, top_score: float | None)`
- `check(hits, threshold, *, supplier_required=False, supplier_id=None) -> GateResult`:
  - `supplier_required and supplier_id is None` → `unknown_supplier`
  - no hits → `no_hits`
  - top score (the first non-expanded hit's `rerank_score` if set, otherwise `score`) below `threshold` → `low_score`
  - otherwise pass

## Tests

### `tests/unit/test_context_builder.py`

```python
from clausecheck.rag.context_builder import build_context
from clausecheck.rag.types import SearchHit


def _hit(i, text="Payment is due Net 45 days.", **meta):
    base = {"doc_id": f"doc-{i}", "page": i, "section": "2. Payment", "clause_no": f"2.{i}",
            "doc_type": "contract", "has_redaction": False}
    base.update(meta)
    return SearchHit(f"c{i}", 1.0, text, base)


def test_markers_numbered_in_order_with_source_lines():
    ctx = build_context([_hit(1), _hit(2), _hit(3)], budget_tokens=2000)
    assert [m for m in ctx.marker_map] == ["C1", "C2", "C3"]
    assert ctx.marker_map["C2"].chunk_id == "c2"
    assert ctx.text.index("[C1]") < ctx.text.index("[C2]") < ctx.text.index("[C3]")
    assert "page 1" in ctx.text and "clause 2.1" in ctx.text


def test_amendment_and_redaction_flags():
    ctx = build_context([_hit(1, doc_type="amendment", parent_doc_id="doc-0", effective_date="2020-03-01",
                              has_redaction=True)], budget_tokens=2000)
    assert "AMENDMENT of doc-0" in ctx.text and "2020-03-01" in ctx.text
    assert "redacted" in ctx.text


def test_budget_never_splits_blocks_and_keeps_first():
    big = "word " * 400
    ctx = build_context([_hit(1, text=big), _hit(2, text=big), _hit(3, text="short")], budget_tokens=500)
    assert [h.chunk_id for h in ctx.used] == ["c1", "c3"]
    assert ctx.text.count("word") == 400
```

### `tests/unit/test_relevance_gate.py`

```python
from clausecheck.rag.relevance_gate import check
from clausecheck.rag.types import SearchHit


def test_no_hits():
    assert check([], 0.5).reason == "no_hits"


def test_low_and_high_score_uses_rerank_score():
    hits = [SearchHit("a", 0.9, "t", rerank_score=0.2)]
    assert check(hits, 0.5).passed is False and check(hits, 0.5).reason == "low_score"
    assert check(hits, 0.1).passed is True


def test_falls_back_to_score_and_skips_expanded():
    hits = [SearchHit("x", 0.0, "t", expanded=True), SearchHit("a", 0.7, "t")]
    assert check(hits, 0.5).passed and check(hits, 0.5).top_score == 0.7


def test_unknown_supplier():
    r = check([SearchHit("a", 1.0, "t")], 0.1, supplier_required=True, supplier_id=None)
    assert (r.passed, r.reason) == (False, "unknown_supplier")
```

## Manual checks

1. Run `pytest -q`. Every test should pass.
2. In a Python shell, retrieve and re-rank for one real question exactly as the PR 8 eval does (`retriever.retrieve(...)` then `reranker.rerank(...)`), then run `build_context(hits, 3000)` and print `ctx.text`. Check that:
   - markers run `C1, C2, C3…` with no gaps
   - each block's first line shows title, page, section and clause
   - an amendment block shows `AMENDMENT of <parent>, effective <date>`
   - a block with redacted values shows `contains redacted values`
3. Check `ctx.token_count`. It should stay within 3000, except when the very first block alone is larger (that block is always kept).
4. Run `check(hits, threshold)` and print `top_score` for **5 answerable and 5 unanswerable** questions. Write both score ranges in the PR description. PR 11 uses them to choose the sweep range.

## Definition of done

Hits become a numbered, budget-safe context with source lines, the gate refuses on unknown supplier, no hits and low score, and every test passes.