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
