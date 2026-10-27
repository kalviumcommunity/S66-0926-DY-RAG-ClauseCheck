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
