# PR 11 · Citation validator, answer metrics and threshold sweep

**Branch:** `b-citation-validator-answer-eval` · **Owner:** Teammate (Generation, Application & Delivery) · **Week:** 4 · **Depends on:** PR 10

## Context

This PR closes grounded generation. After the model answers, nothing it says is trusted until it is checked against the clauses it was given:
- the **citation validator** drops markers that point at nothing and flags claims with no citation
- **answer metrics** measure correctness, citation accuracy and refusals
- `--stage answer` runs the full answer path on the tuning split, and `--sweep` chooses the relevance threshold from measured data instead of a guess

Read before starting:
- `docs/architecture/rag-architecture-design.md`: query pipeline steps 8–9
- `docs/requirements/PRD.md`: the answer contract
- `docs/ux/ui-states.md`: the unsupported-value warning

## Scope (only these files)

| Path | Action |
|---|---|
| `clausecheck/rag/citation_validator.py` | add |
| `eval/metrics.py` | modify: add answer metrics |
| `eval/run_eval.py` | modify: `--stage answer`, `--sweep` |
| `.env.example` | modify: set `RELEVANCE_THRESHOLD` to the chosen value |
| `tests/unit/test_citation_validator.py`, `tests/unit/test_answer_metrics.py` | add |

## Specification

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
- `contains_expected(answer: str, expected: str) -> bool`: compares lowercased answer and expected value with spaces collapsed and `,` removed from numbers. Used for the `exact` group until the judge arrives in PR 14.

### `eval/run_eval.py` additions

- `--stage answer` runs `hybrid_rerank` → gate → context → generator → validator for each question in the split.
  - Grading: `exact` uses `contains_expected`; `real` uses `contains_expected` as a temporary rule and is marked `needs_judge`.
  - Writes per-question rows (answer, citations, outcome, grade) and the four metrics.
- `--sweep start:stop:step` re-runs **only the gate** over cached retrieval and generation results for each threshold. It writes `{date}_sweep_{split}.csv` with columns `threshold, refusal_accuracy, false_refusal_rate, answer_correctness`.

## Tests

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
2. Run `python -m eval.run_eval --split tune --stage answer`. Targets on tuning: **citation accuracy ≥ 90%**, **correct refusals ≥ 90%**, and exact-group correctness ≥ 85% (real-group correctness is confirmed with the judge in PR 14). Record the numbers with the prompt version and index version.
3. Run `python -m eval.run_eval --split tune --stage answer --sweep -5:5:0.5`. Pick the threshold that meets refusal accuracy ≥ 90% with the lowest false-refusal rate. Set `RELEVANCE_THRESHOLD` in your local `.env` and in `.env.example`, and paste the sweep table into the PR description.
4. Ask 3 unanswerable questions in a Python shell. Each should get exactly `REFUSAL_TEXT`, with no invented terms.
5. Ask about a redacted value. The answer should say the value is redacted and cite the clause.
6. Ask about an amended term. The answer should give the new term, name the old one, and cite both.

## Definition of done

Answers are grounded and cited, weak evidence produces a refusal, the threshold is chosen from a measured sweep, and every test passes.