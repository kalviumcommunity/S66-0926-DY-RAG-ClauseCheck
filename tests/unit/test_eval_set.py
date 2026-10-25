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
