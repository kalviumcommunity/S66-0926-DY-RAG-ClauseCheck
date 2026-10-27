# PR 14 · LLM judge and end-to-end evaluation

**Branch:** `b-judge-e2e-eval` · **Owner:** Teammate (Generation, Application & Delivery) · **Week:** 5 · **Depends on:** PR 13

## Context

Exact string matching can't grade free-text answers, so this PR adds an **LLM judge from a different model family** (Groq, while answers come from Gemini), plus a 10% sample that a human grades by hand to show the judge can be trusted.

It also adds `--stage e2e`, which runs every question through the real `QueryService` and produces the numbers for the report: correctness, citation accuracy, refusals, median latency and judge agreement.

Read before starting:
- `docs/architecture/tdd.md` §16 (the judge)
- `docs/planning/development-plan.md`: evaluation targets

## Scope (only these files)

| Path | Action |
|---|---|
| `clausecheck/prompts/judge.txt` | add |
| `eval/judge.py` | add |
| `eval/run_eval.py` | modify: `--stage e2e`, `--agreement` |
| `clausecheck/core/config.py`, `.env.example` | modify: `judge_model: str = "llama-3.3-70b-versatile"` |
| `tests/unit/test_judge.py` | add |

## Specification

### `clausecheck/prompts/judge.txt`

`judge.txt` (`# v1`, placeholders `{{question}}`, `{{expected}}` and `{{answer}}`): reply with JSON only, `{"label": "correct" | "partial" | "wrong", "reason": "<one sentence>"}`. Grade by meaning. A missing citation doesn't change the label.

### `eval/judge.py`

- `Grade(label: str, reason: str)`
- `grade(client, prompt: Prompt, question, expected, answer) -> Grade`: parses the first `{…}` JSON object in the reply. A label outside `correct`, `partial` or `wrong`, or unparseable output, becomes `Grade("error", <short note>)`.
- `sample_for_review(rows: list[dict], frac: float = 0.1, seed: int = 42) -> list[dict]`: returns `max(1, round(len * frac))` rows chosen with `random.Random(seed)`, or `[]` for empty input.
- `agreement(judge: list[str], human: list[str]) -> float`: the share of equal labels.
- `build_judge_client(settings)`: an `LLMClient` with **Groq** as primary (`judge_model`) and no fallback, so the judge is always a different family from the answering model.

### `eval/run_eval.py` (`--stage e2e`)

Runs every question in the split through `QueryService.from_settings`.
- Grades: `exact` uses `contains_expected`, `real` uses the judge, and `unanswerable` is correct if `outcome == "refused"`.
- Writes per-question rows, the metrics from PR 11, median latency, and `eval/results/{date}_judge_sample_{split}.csv` (the 10% sample with an empty `human_label` column for hand grading).
- `--agreement path.csv` reads a hand-graded sample and prints the agreement.

## Tests

### `tests/unit/test_judge.py`

```python
from eval.judge import agreement, grade, sample_for_review
from clausecheck.prompts.loader import Prompt

PROMPT = Prompt("judge", "v1", "Q {{question}} E {{expected}} A {{answer}}")


class Client:
    def __init__(self, reply):
        self.reply = reply

    def complete(self, prompt, **kw):
        return self.reply


def test_parses_json_inside_text():
    g = grade(Client('Sure: {"label": "correct", "reason": "same term"}'), PROMPT, "q", "Net 45", "Net 45 [C1].")
    assert (g.label, g.reason) == ("correct", "same term")


def test_bad_output_is_error():
    assert grade(Client("no json"), PROMPT, "q", "e", "a").label == "error"
    assert grade(Client('{"label": "great"}'), PROMPT, "q", "e", "a").label == "error"


def test_sample_and_agreement():
    rows = [{"qid": f"Q{i}"} for i in range(30)]
    s1, s2 = sample_for_review(rows), sample_for_review(rows)
    assert len(s1) == 3 and s1 == s2
    assert sample_for_review([]) == []
    assert agreement(["correct", "wrong"], ["correct", "partial"]) == 0.5
```

## Manual checks

1. Run `pytest -q`. Every test should pass.
2. Confirm in the logs that the judge call goes to **Groq** and the answer call goes to **Gemini**, so the judge really is a different family.
3. Run `python -m eval.run_eval --split tune --stage e2e`.
4. Open `eval/results/<file>.csv` (the judge sample). Grade each row by hand in the empty `human_label` column.
5. Run `python -m eval.run_eval --agreement eval/results/<file>.csv`.
6. Record correctness, citation accuracy, refusals, median latency and judge agreement in the PR description. If agreement is low, say what the judge got wrong and whether `judge.txt` needs a `# v2`.

## Definition of done

The tuning split is measured end to end with spot-checked judge grades, the judge is a different model family from the answerer, and every test passes.