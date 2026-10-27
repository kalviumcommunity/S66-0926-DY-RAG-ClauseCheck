# PR 9 · Grounded generation, relevance gate and citation validation

**Branch:** `b-grounded-generation` · **Owner:** Teammate (Generation, Application & Delivery) · **Week:** 4 · **Depends on:** PR 8

## Context

Retrieval finds the clauses, and the language model only **phrases** an answer from them and cites them. **A refusal is a correct outcome; an invented term is the worst outcome.**

This PR adds:
- the versioned answer prompt
- context building with `[C1]..[Cn]` markers
- the relevance gate (refuse when evidence is weak)
- the generator (blocking and streamed)
- the citation validator (drop markers that point at nothing, flag claims with no citation)
- answer metrics and a threshold sweep

Read before starting:
- `docs/architecture/rag-architecture-design.md`: query pipeline steps 6–9 and the design principles
- `docs/requirements/PRD.md`: the answer contract (cite every factual claim, flag conflicts, latest term wins visibly, no outside knowledge)
- `docs/ux/mock-ux.md`: the **copy deck**, for the exact refusal sentence and the redaction wording
- `docs/ux/ui-states.md`: refusal states

## Scope (only these files)

| Path | Action |
|---|---|
| `clausecheck/prompts/answer.txt` | add (remove `.gitkeep`) |
| `clausecheck/prompts/__init__.py`, `clausecheck/prompts/loader.py` | add |
| `clausecheck/rag/context_builder.py` | add |
| `clausecheck/rag/relevance_gate.py` | add |
| `clausecheck/rag/generator.py` | add |
| `clausecheck/rag/citation_validator.py` | add |
| `clausecheck/core/config.py`, `.env.example` | modify: `gen_temperature: float = 0.0`, `context_token_budget: int = 3000`, `relevance_threshold: float = 0.0` |
| `pyproject.toml` | modify: include `clausecheck/prompts/*.txt` as package data |
| `eval/metrics.py` | modify: add answer metrics |
| `eval/run_eval.py` | modify: `--stage answer`, `--sweep` |
| `tests/unit/test_prompts.py`, `test_context_builder.py`, `test_relevance_gate.py`, `test_generator.py`, `test_citation_validator.py`, `test_answer_metrics.py` | add |

## Specification

### `clausecheck/prompts/answer.txt`

- The first line is exactly `# v1`. Each later change bumps the version (`# v2` and so on).
- The body contains the placeholders `{{context}}` and `{{question}}` (double braces, replaced with `str.replace`, because contract text can contain `{}`).
- Rules it must state, in plain sentences:
  1. Answer **only** from the numbered clauses in the context. Never use outside knowledge.
  2. Put a citation marker such as `[C2]` **before the full stop** of every sentence that states a term, number, date or obligation. Cite only markers that appear in the context.
  3. If the clauses don't answer the question, reply with exactly the refusal sentence and nothing else.
  4. When an amendment changes a term, give the **amended** term, say what it replaced, and cite both.
  5. If two clauses conflict and neither is an amendment of the other, say they conflict and cite both.
  6. Never present a redaction marker as a value. Say the value is redacted, using the copy-deck wording.
  7. Be brief: at most 4 sentences, unless the question asks for a list.
- It must contain `REFUSAL_TEXT` verbatim.

### `clausecheck/prompts/loader.py`

`Prompt` dataclass (`name`, `version`, `text`), and `load_prompt(name: str, prompts_dir: Path | None = None) -> Prompt`:
- reads `<prompts_dir or this package's dir>/<name>.txt`
- parses `# v<N>` from the first line into `version="v<N>"`
- returns `text` without the header line
- raises `ValueError` if the header is missing

### `clausecheck/rag/generator.py`

- `REFUSAL_TEXT: str`: copy the exact refusal sentence from the `mock-ux.md` copy deck. If there isn't one, use `"I couldn't find this in the contracts I have for this supplier."`
- `class Generator`:
  - `__init__(self, client, prompt: Prompt, temperature: float = 0.0)`
  - `build_prompt(question, context_text) -> str`
  - `generate(question, context_text) -> str`: `client.complete(prompt, temperature=...)`, stripped
  - `stream(question, context_text) -> Iterator[str]`: `client.stream(...)`
  - `@classmethod from_settings(cls, settings)`

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

### `clausecheck/rag/citation_validator.py`

```python
@dataclass
class Citation:
    marker: str        # "C1"
    chunk_id: str
    doc_id: str | None
    page: int | None
    section: str | None
    clause_no: str | None

@dataclass
class ValidationResult:
    answer: str              # invalid markers removed, spacing tidied
    citations: list[Citation]  # valid markers, unique, order of first use
    dropped: list[str]       # invalid markers, e.g. ["C9"]
    unsupported: bool        # a factual sentence has no valid marker

def validate(answer: str, marker_map: dict[str, SearchHit]) -> ValidationResult: ...
```

- `MARKER_RE = re.compile(r"\[C(\d+)\]")`
- Remove invalid markers, then tidy spaces before punctuation (`"x [C9]."` becomes `"x."`) and double spaces.
- Split sentences on `(?<=[.!?])\s+`. A sentence is **exempt** if it is empty, ends with `:` or `?`, or is the refusal sentence. Every other sentence needs at least one valid marker; otherwise `unsupported=True`.
- If the stripped answer equals `REFUSAL_TEXT`: no citations and `unsupported=False`.

### `eval/metrics.py` additions

- `answer_correctness(grades: list[str]) -> float`: the share of `"correct"`. Raises `ValueError` on an empty list.
- `citation_accuracy(cited: list[list[str]], gold: list[list[str]]) -> float`: among pairs where both lists are non-empty, the share where any cited ID is in gold. Raises `ValueError` if there are no such pairs.
- `refusal_accuracy(refused: list[bool], should_refuse: list[bool]) -> float`: among `should_refuse=True`, the share refused.
- `false_refusal_rate(refused, should_refuse) -> float`: among `should_refuse=False`, the share refused.
- `contains_expected(answer: str, expected: str) -> bool`: compares lowercased answer and expected value with spaces collapsed and `,` removed from numbers. Used for the `exact` group until the judge arrives in PR 10.

### `eval/run_eval.py` additions

- `--stage answer` runs `hybrid_rerank` → gate → context → generator → validator for each question in the split.
  - Grading: `exact` uses `contains_expected`; `real` uses `contains_expected` as a temporary rule and is marked `needs_judge`.
  - Writes per-question rows (answer, citations, outcome, grade) and the four metrics.
- `--sweep start:stop:step` re-runs **only the gate** over cached retrieval and generation results for each threshold. It writes `{date}_sweep_{split}.csv` with columns `threshold, refusal_accuracy, false_refusal_rate, answer_correctness`.

## Tests

### `tests/unit/test_prompts.py`

```python
import pytest

from clausecheck.prompts.loader import load_prompt
from clausecheck.rag.generator import REFUSAL_TEXT


def test_answer_prompt_header_and_placeholders():
    p = load_prompt("answer")
    assert p.name == "answer" and p.version.startswith("v")
    assert "{{context}}" in p.text and "{{question}}" in p.text
    assert not p.text.startswith("# v")


def test_answer_prompt_contains_refusal_sentence():
    assert REFUSAL_TEXT and REFUSAL_TEXT in load_prompt("answer").text


def test_missing_header_raises(tmp_path):
    (tmp_path / "bad.txt").write_text("no header here")
    with pytest.raises(ValueError):
        load_prompt("bad", prompts_dir=tmp_path)
```

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

### `tests/unit/test_generator.py`

```python
from clausecheck.prompts.loader import Prompt
from clausecheck.rag.generator import Generator


class FakeClient:
    def __init__(self):
        self.prompts = []

    def complete(self, prompt, **kw):
        self.prompts.append((prompt, kw))
        return "  Payment is due Net 45 days [C1].  "

    def stream(self, prompt, **kw):
        self.prompts.append((prompt, kw))
        yield from ["Payment ", "is ", "Net 45 [C1]."]


PROMPT = Prompt("answer", "v1", "Rules.\nContext:\n{{context}}\nQuestion: {{question}}")


def test_prompt_filled_with_braces_safe():
    g = Generator(FakeClient(), PROMPT)
    out = g.build_prompt("What are the terms {x}?", "[C1] doc | page 1\nfee {y}")
    assert "What are the terms {x}?" in out and "fee {y}" in out and "{{" not in out


def test_generate_strips_and_passes_temperature():
    client = FakeClient()
    assert Generator(client, PROMPT, temperature=0.0).generate("q", "ctx") == "Payment is due Net 45 days [C1]."
    assert client.prompts[0][1]["temperature"] == 0.0


def test_stream_yields_tokens():
    assert "".join(Generator(FakeClient(), PROMPT).stream("q", "ctx")) == "Payment is Net 45 [C1]."
```

### `tests/unit/test_citation_validator.py`

```python
from clausecheck.rag.citation_validator import validate
from clausecheck.rag.generator import REFUSAL_TEXT
from clausecheck.rag.types import SearchHit

MAP = {
    "C1": SearchHit("doc-a:p2:2_1", 1.0, "t", {"doc_id": "doc-a", "page": 2, "section": "2. Payment", "clause_no": "2.1"}),
    "C2": SearchHit("doc-b:p1:1", 1.0, "t", {"doc_id": "doc-b", "page": 1, "section": None, "clause_no": "1"}),
}


def test_valid_citations_kept_in_order_and_unique():
    r = validate("Payment is Net 30 [C2]. It replaced Net 45 [C1][C2].", MAP)
    assert [c.marker for c in r.citations] == ["C2", "C1"]
    assert r.citations[1].chunk_id == "doc-a:p2:2_1" and r.citations[1].page == 2
    assert r.unsupported is False and r.dropped == []


def test_invalid_marker_dropped_and_sentence_flagged():
    r = validate("Payment is Net 45 [C1]. The term is two years [C9].", MAP)
    assert r.dropped == ["C9"]
    assert "[C9]" not in r.answer and "two years." in r.answer
    assert r.unsupported is True


def test_exempt_sentences():
    r = validate("Here is what the contract says: Payment is Net 45 [C1]. Want the late fee too?", MAP)
    assert r.unsupported is False


def test_refusal_has_no_citations_and_is_supported():
    r = validate(REFUSAL_TEXT, MAP)
    assert r.citations == [] and r.unsupported is False
```

### `tests/unit/test_answer_metrics.py`

```python
import pytest

from eval.metrics import (answer_correctness, citation_accuracy, contains_expected,
                          false_refusal_rate, refusal_accuracy)


def test_answer_correctness():
    assert answer_correctness(["correct", "wrong", "correct", "partial"]) == 0.5
    with pytest.raises(ValueError):
        answer_correctness([])


def test_citation_accuracy_ignores_empty_pairs():
    assert citation_accuracy([["a"], ["x"], [], ["b", "c"]], [["a"], ["y"], ["z"], ["c"]]) == pytest.approx(2 / 3)


def test_refusal_metrics():
    refused = [True, False, True, False]
    should = [True, True, False, False]
    assert refusal_accuracy(refused, should) == 0.5
    assert false_refusal_rate(refused, should) == 0.5


def test_contains_expected_normalises():
    assert contains_expected("The unit price is $1,250.00 [C1].", "1250.00")
    assert contains_expected("Payment is due  NET 45 days.", "net 45")
    assert not contains_expected("Net 30", "net 45")
```

## Manual checks

1. Run `pytest -q`. Every test should pass.
2. Run `python -m eval.run_eval --split tune --stage answer`. Targets on tuning: **citation accuracy ≥ 90%**, **correct refusals ≥ 90%**, and exact-group correctness ≥ 85% (real-group correctness is confirmed with the judge in PR 10). Record the numbers with the prompt version and index version.
3. Run `python -m eval.run_eval --split tune --stage answer --sweep -5:5:0.5`. Pick the threshold that meets both refusal accuracy ≥ 90% and the lowest false-refusal rate, set `RELEVANCE_THRESHOLD` in `.env` and `.env.example`, and paste the sweep table into the PR description.
4. Ask 3 unanswerable questions in a Python shell. Each should get exactly `REFUSAL_TEXT`, with no invented terms.
5. Ask about a redacted value. The answer should say the value is redacted and cite the clause.
6. Ask about an amended term. The answer should give the new term, name the old one, and cite both.

## Definition of done

Answers are grounded and cited, weak evidence produces a refusal, the threshold is chosen from a measured sweep, and every test passes.
