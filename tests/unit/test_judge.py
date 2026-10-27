from clausecheck.prompts.loader import Prompt
from eval.judge import agreement, grade, sample_for_review

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
