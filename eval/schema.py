"""The labelled evaluation question format."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel


class Question(BaseModel):
    """One evaluation question with its gold chunks."""

    qid: str  # "Q001".. unique
    split: Literal["tune", "heldout"]
    group: Literal["real", "exact", "unanswerable"]
    question: str
    supplier_id: str | None  # None only when the question names no supplier on purpose
    gold_chunk_ids: list[str]  # empty only for unanswerable
    expected_answer: str  # "" for unanswerable
    should_refuse: bool  # True exactly for unanswerable
    notes: str = ""


def load_questions(path: Path, split: str | None = None) -> list[Question]:
    """Read a JSONL question file, optionally keeping only one split."""
    questions = [
        Question.model_validate_json(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return [q for q in questions if split is None or q.split == split]
