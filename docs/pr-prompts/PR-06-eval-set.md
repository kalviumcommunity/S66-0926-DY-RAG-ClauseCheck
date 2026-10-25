# PR 6 · Labelled evaluation set and the eval runner

**Branch:** `a-eval-set` · **Owner:** Diya (Data, Retrieval & Platform Foundations) · **Week:** 2 · **Depends on:** PR 5 (gold chunk IDs come from the ingested DB). Can be built alongside PR 4 and PR 5, but must merge before PR 7.

## Context

Every retrieval or prompt change is measured against a fixed, labelled question set. The set has three groups:
- about 30 **real-contract** questions from CUAD clause labels
- about 20 **exact-value** questions from synthetic documents (ground truth from `ground_truth.jsonl`)
- about 15 **unanswerable** questions that test refusals

It is split into **tuning (~60%)** and **held-out (~40%)**. The held-out split is not run before W5 D4.

Read before starting:
- `docs/02-project-description.md` §8 (evaluation plan)
- `docs/architecture/tdd.md` §16 (metrics and targets)
- `docs/planning/development-plan.md` (held-out rule)
- `docs/requirements/PRD.md` (the question types users ask)

## Scope (only these files)

| Path | Action |
|---|---|
| `eval/__init__.py` | add (empty) |
| `eval/schema.py` | add |
| `eval/metrics.py` | add |
| `eval/run_eval.py` | add |
| `eval/questions.jsonl` | add |
| `eval/README.md` | add: how questions were written, how to run, the held-out rule |
| `tests/unit/test_eval_metrics.py`, `tests/unit/test_eval_set.py`, `tests/unit/test_run_eval.py` | add |

## Specification

### `eval/schema.py`

```python
class Question(BaseModel):
    qid: str                         # "Q001".. unique
    split: Literal["tune", "heldout"]
    group: Literal["real", "exact", "unanswerable"]
    question: str
    supplier_id: str | None          # None only when the question names no supplier on purpose
    gold_chunk_ids: list[str]        # empty only for unanswerable
    expected_answer: str             # "" for unanswerable
    should_refuse: bool              # True exactly for unanswerable
    notes: str = ""

def load_questions(path: Path, split: str | None = None) -> list[Question]: ...
```

### `eval/metrics.py`

- `recall_at_k(retrieved: list[str], gold: list[str], k: int) -> float`: `|set(retrieved[:k]) ∩ set(gold)| / |set(gold)|`. Raises `ValueError` when `gold` is empty.
- `mrr(retrieved: list[str], gold: list[str]) -> float`: `1 / rank` of the first gold ID (1-based), or `0.0` if none.
- `evaluate_retrieval(questions, retrieve_fn: Callable[[Question], list[str]], k: int = 5) -> dict`: **skips unanswerable** questions. Returns `{"k": k, "n": int, "recall_at_k": mean, "mrr": mean, "per_question": [{"qid", "recall", "rr", "retrieved"}]}`.

### `eval/run_eval.py`

- `main(argv: list[str] | None = None) -> int` with flags:
  - `--split tune|heldout` (default `tune`)
  - `--stage retrieval|answer|e2e` (default `retrieval`)
  - `--retriever NAME`
  - `--k 5`
  - `--questions eval/questions.jsonl`
  - `--out eval/results`
  - `--allow-heldout`
- Held-out guard: `--split heldout` without `--allow-heldout` prints a message containing `--allow-heldout` to stderr and **returns 2** before loading anything else.
- `RETRIEVERS: dict[str, Callable[[], Callable[[Question], list[str]]]] = {}` is a registry that PR 7 and later fill. An unknown or missing retriever prints the available names and returns 3. Stages `answer` and `e2e` print "available from PR 9/10" and return 3.
- `write_results(result: dict, stage: str, split: str, out_dir: Path, run_date: str | None = None) -> Path` writes `{run_date or today}_{stage}_{split}.json` (ISO date). It adds `stage`, `split` and `created_at` to the JSON and returns the path.

### `eval/questions.jsonl`: how to write it

1. Real-contract questions (~30): choose CUAD contracts that are in the DB, covering the procurement categories in PRD §5.2 (renewal term, cap on liability, minimum commitment, termination for convenience, warranty duration and others). Write the question the way a procurement buyer would, naming the supplier. Look up the chunk(s) that answer it in SQLite and copy their `chunk_id`s. Include **at least 3 amendment questions** where the amended term is the answer; their gold must include the amendment chunk.
2. Exact-value questions (~20): one per fact from `data/raw/synthetic/ground_truth.jsonl` (unit price of a SKU, payment terms, certificate expiry date or number). The gold is the chunk containing the value.
3. Unanswerable questions (~15): a term that isn't in any document for that supplier, an unknown supplier, and a question outside the domain. Set `should_refuse: true` and use empty gold.
4. Split **stratified by group**: about 60% `tune` and 40% `heldout` in each group, assigned with `random.Random(42)`.
5. **Draft the questions, then stop and show me 10 of them.** I review and correct before you write the rest.

## Tests

### `tests/unit/test_eval_metrics.py`

```python
import pytest

from eval.metrics import evaluate_retrieval, mrr, recall_at_k
from eval.schema import Question


def test_recall_at_k():
    assert recall_at_k(["a", "b", "c"], ["b"], k=5) == 1.0
    assert recall_at_k(["a", "b", "c"], ["c"], k=2) == 0.0
    assert recall_at_k(["a", "b"], ["a", "z"], k=5) == 0.5
    with pytest.raises(ValueError):
        recall_at_k(["a"], [], k=5)


def test_mrr():
    assert mrr(["a", "b", "c"], ["a"]) == 1.0
    assert mrr(["a", "b", "c"], ["c"]) == pytest.approx(1 / 3)
    assert mrr(["a"], ["z"]) == 0.0


def _q(qid, gold, refuse=False):
    return Question(qid=qid, split="tune", group="unanswerable" if refuse else "real",
                    question="?", supplier_id="S-ACME", gold_chunk_ids=gold,
                    expected_answer="" if refuse else "x", should_refuse=refuse)


def test_evaluate_retrieval_skips_unanswerable():
    questions = [_q("Q1", ["a"]), _q("Q2", ["z"]), _q("Q3", [], refuse=True)]
    result = evaluate_retrieval(questions, lambda q: ["a", "b"], k=5)
    assert result["n"] == 2
    assert result["recall_at_k"] == 0.5
    assert result["mrr"] == 0.5
    assert {p["qid"] for p in result["per_question"]} == {"Q1", "Q2"}
```

### `tests/unit/test_eval_set.py`

```python
"""The committed question set is valid, balanced and split correctly."""
from collections import Counter
from pathlib import Path

import pytest

from eval.schema import load_questions

ROOT = Path(__file__).resolve().parents[2]
QUESTIONS = ROOT / "eval" / "questions.jsonl"


@pytest.fixture(scope="module")
def questions():
    return load_questions(QUESTIONS)


def test_size_and_groups(questions):
    assert 55 <= len(questions) <= 90
    groups = Counter(q.group for q in questions)
    assert groups["real"] >= 25 and groups["exact"] >= 15 and groups["unanswerable"] >= 12


def test_qids_unique(questions):
    assert len({q.qid for q in questions}) == len(questions)


def test_refusal_rules(questions):
    for q in questions:
        if q.group == "unanswerable":
            assert q.should_refuse and q.gold_chunk_ids == [] and q.expected_answer == "", q.qid
        else:
            assert not q.should_refuse and q.gold_chunk_ids and q.expected_answer, q.qid


def test_split_ratio_overall_and_per_group(questions):
    share = sum(q.split == "tune" for q in questions) / len(questions)
    assert 0.55 <= share <= 0.65
    for group in ["real", "exact", "unanswerable"]:
        splits = {q.split for q in questions if q.group == group}
        assert splits == {"tune", "heldout"}, f"{group} must appear in both splits"


def test_load_by_split(questions):
    tune = load_questions(QUESTIONS, split="tune")
    assert tune and all(q.split == "tune" for q in tune)


def test_gold_chunks_exist_in_db(questions):
    from clausecheck.core.config import Settings
    from clausecheck.store import sqlite as db

    path = Settings(_env_file=None).sqlite_path
    if not Path(path).exists():
        pytest.skip("index not built on this machine")
    conn = db.connect(path)
    missing = [(q.qid, cid) for q in questions for cid in q.gold_chunk_ids if db.get_chunk(conn, cid) is None]
    assert not missing, f"unknown gold chunk ids: {missing[:10]}"
```

### `tests/unit/test_run_eval.py`

```python
import json

from eval.run_eval import main, write_results


def test_heldout_blocked_without_flag(capsys):
    assert main(["--split", "heldout"]) == 2
    assert "--allow-heldout" in capsys.readouterr().err


def test_unknown_retriever_returns_3(capsys):
    assert main(["--split", "tune", "--stage", "retrieval", "--retriever", "nope"]) == 3


def test_write_results(tmp_path):
    path = write_results({"recall_at_k": 0.9}, "retrieval", "tune", tmp_path, run_date="2026-11-03")
    assert path.name == "2026-11-03_retrieval_tune.json"
    data = json.loads(path.read_text())
    assert data["recall_at_k"] == 0.9 and data["stage"] == "retrieval" and data["split"] == "tune"
```

## Manual checks

1. Run `pytest -q`. Every test should pass, and `test_gold_chunks_exist_in_db` should **run, not skip**, on your machine with the index built.
2. Run `python -m eval.run_eval --split heldout`. Expect a refusal that mentions `--allow-heldout`. Always run the runner as a module (`python -m eval.run_eval`) so `eval` imports resolve, and add `if __name__ == "__main__": raise SystemExit(main())` at the end of the file.
3. Run `python -c "from eval.schema import load_questions; from collections import Counter; q=load_questions('eval/questions.jsonl'); print(Counter((x.group,x.split) for x in q))"`. Paste the output into the PR description.
4. Give 5 random tuning questions to a teammate who didn't write them. Using only the contracts, they should reach the same gold chunk.
5. Read every unanswerable question and check that none is actually answerable from the corpus.

## Definition of done

The question set is committed, reviewed and split, the gold IDs exist, the held-out split is locked, and retrieval can be scored with one function.
