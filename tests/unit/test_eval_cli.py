"""Run `python -m eval.run_eval` as a real command.

`main()` used to be called from an `if __name__ == "__main__"` block placed above the functions it
dispatches to, so every stage except plain retrieval crashed with NameError when run from the
command line. Importing the module (as the other tests do) never showed it.
"""

import csv
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HEADER = ["qid", "question", "expected", "answer", "judge_label", "human_label"]


def run_eval(*args):
    return subprocess.run(
        [sys.executable, "-m", "eval.run_eval", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


def write_sample(path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(HEADER)
        writer.writerows(rows)


def test_agreement_stage_runs_from_the_command_line(tmp_path):
    sample = tmp_path / "sample.csv"
    write_sample(
        sample,
        [
            ["Q1", "q", "a", "a", "correct", "correct"],
            ["Q2", "q", "a", "a", "incorrect", "correct"],
            ["Q3", "q", "a", "a", "correct", ""],  # not hand-graded yet: left out
        ],
    )
    result = run_eval("--agreement", str(sample))
    assert result.returncode == 0, result.stderr
    assert "over 2 rows" in result.stdout and "NameError" not in result.stderr


def test_agreement_stage_says_so_when_nothing_is_hand_graded(tmp_path):
    sample = tmp_path / "sample.csv"
    write_sample(sample, [["Q1", "q", "a", "a", "correct", ""]])
    result = run_eval("--agreement", str(sample))
    assert result.returncode == 1 and "no hand-graded rows" in result.stderr


def test_the_held_out_split_is_blocked_without_the_flag():
    result = run_eval("--split", "heldout", "--stage", "e2e")
    assert result.returncode == 2 and "held-out" in result.stderr.lower()


def test_every_stage_function_exists_before_the_script_runs():
    # the module-level guard must come last, after every `_run_*` function
    source = (ROOT / "eval" / "run_eval.py").read_text()
    guard = source.index('if __name__ == "__main__":')
    for name in ("_run_answer", "_run_sweep", "_run_e2e", "_run_agreement", "_run_ablation"):
        assert source.index(f"def {name}(") < guard, name


def test_the_smoke_run_option_used_by_ci_exists():
    result = run_eval("--help")
    assert "--limit" in result.stdout
