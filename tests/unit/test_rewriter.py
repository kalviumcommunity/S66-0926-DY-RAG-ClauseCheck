from clausecheck.prompts.loader import Prompt
from clausecheck.rag.rewriter import Rewriter
from clausecheck.services.sessions import Turn

PROMPT = Prompt("rewrite", "v1", "History:\n{{history}}\nQuestion: {{question}}")


class FakeClient:
    def __init__(self, reply="What is the notice period with Acme Corp?"):
        self.reply = reply
        self.calls = []

    def complete(self, prompt, **kw):
        self.calls.append(prompt)
        return self.reply


def test_no_history_no_call():
    client = FakeClient()
    assert Rewriter(client, PROMPT).rewrite("And their notice period?", []) == "And their notice period?"
    assert client.calls == []


def test_with_history_rewrites():
    client = FakeClient()
    history = [Turn("What are the payment terms with Acme Corp?", "Net 45 [C1].")]
    out = Rewriter(client, PROMPT).rewrite("And their notice period?", history)
    assert out == "What is the notice period with Acme Corp?"
    assert "User: What are the payment terms with Acme Corp?" in client.calls[0]


def test_empty_reply_falls_back():
    out = Rewriter(FakeClient(reply="   "), PROMPT).rewrite("And the term?", [Turn("q", "a")])
    assert out == "And the term?"
