# PR 9 · Versioned answer prompt, prompt loader and generator

**Branch:** `b-answer-prompt-generator` · **Owner:** Teammate (Generation, Application & Delivery) · **Week:** 4 · **Depends on:** PR 8

## Context

Retrieval finds the clauses, and the language model only **phrases** an answer from them and cites them. **A refusal is a correct outcome; an invented term is the worst outcome.**

This is the first of three PRs that build grounded generation. This PR adds only:
- the versioned answer prompt and the loader that reads it
- the generator (blocking and streamed) that fills the prompt and calls the LLM client
- the single `REFUSAL_TEXT` constant that every later layer (gate, validator, API, frontend) compares against

Context building and the relevance gate come in PR 10; the citation validator, answer metrics and threshold sweep come in PR 11. Nothing in this PR touches retrieval.

Read before starting:
- `docs/architecture/rag-architecture-design.md`: query pipeline steps 6–9 and the design principles
- `docs/requirements/PRD.md`: the answer contract (cite every factual claim, flag conflicts, latest term wins visibly, no outside knowledge)
- `docs/ux/mock-ux.md`: the **copy deck**, for the exact refusal sentence and the redaction wording

## Scope (only these files)

| Path | Action |
|---|---|
| `clausecheck/prompts/answer.txt` | add (remove `.gitkeep`) |
| `clausecheck/prompts/__init__.py`, `clausecheck/prompts/loader.py` | add |
| `clausecheck/rag/generator.py` | add |
| `clausecheck/core/config.py`, `.env.example` | modify: `gen_temperature: float = 0.0` |
| `pyproject.toml` | modify: include `clausecheck/prompts/*.txt` as package data |
| `tests/unit/test_prompts.py`, `tests/unit/test_generator.py` | add |

## Specification

### `clausecheck/prompts/answer.txt`

- The first line is exactly `# v1`. Each later change bumps the version (`# v2` and so on).
- The body contains the placeholders `{{context}}` and `{{question}}` (double braces, replaced with `str.replace`, because contract text can contain `{}`).
- Rules it must state, in plain sentences:
  1. Answer **only** from the numbered clauses in the context. Never use outside knowledge.
  2. Put a citation marker such as `[C2]` **before the full stop** of every sentence that states a term, number, date or obligation. Cite only markers that appear in the context.
  3. If the clauses don't answer the question, reply with exactly the refusal sentence and nothing else.
  4. When an amendment changes a term, give the **amended** term, say what it replaced, and cite both.
  5. If two clauses conflict and neither is an amendment of the other, say they conflict and cite both.
  6. Never present a redaction marker as a value. Say the value is redacted, using the copy-deck wording.
  7. Be brief: at most 4 sentences, unless the question asks for a list.
- It must contain `REFUSAL_TEXT` verbatim.

### `clausecheck/prompts/loader.py`

`Prompt` dataclass (`name`, `version`, `text`), and `load_prompt(name: str, prompts_dir: Path | None = None) -> Prompt`:
- reads `<prompts_dir or this package's dir>/<name>.txt`
- parses `# v<N>` from the first line into `version="v<N>"`
- returns `text` without the header line
- raises `ValueError` if the header is missing

### `clausecheck/rag/generator.py`

- `REFUSAL_TEXT: str`: copy the exact refusal sentence from the `mock-ux.md` copy deck. If there isn't one, use `"I couldn't find this in the contracts I have for this supplier."`
- `class Generator`:
  - `__init__(self, client, prompt: Prompt, temperature: float = 0.0)`
  - `build_prompt(question, context_text) -> str`
  - `generate(question, context_text) -> str`: `client.complete(prompt, temperature=...)`, stripped
  - `stream(question, context_text) -> Iterator[str]`: `client.stream(...)`
  - `@classmethod from_settings(cls, settings)`

## Tests

### `tests/unit/test_prompts.py`

```python
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
```

### `tests/unit/test_generator.py`

```python
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
```

## Manual checks

1. Run `pytest -q`. Every test should pass.
2. Run `pip install -e .`, then from a **different directory** run:
   ```bash
   python -c "from clausecheck.prompts.loader import load_prompt; p = load_prompt('answer'); print(p.version, len(p.text))"
   ```
   It should print `v1` and a length. This proves the `.txt` file ships as package data.
3. Open the `mock-ux.md` copy deck and confirm `REFUSAL_TEXT` is identical to its refusal sentence. If the deck has none, say so in the PR description and keep the fallback sentence.
4. Smoke-test the generator with the real client and a hand-written context:
   ```python
   from clausecheck.core.config import get_settings
   from clausecheck.rag.generator import Generator
   g = Generator.from_settings(get_settings())
   ctx = "[C1] Acme MSA | page 2 | section 2. Payment | clause 2.1\n2.1 Payment is due Net 45 days."
   print(g.generate("What are the payment terms?", ctx))
   print(g.generate("What is the liability cap?", ctx))
   ```
   The first answer should state Net 45 with `[C1]` **before the full stop**. The second should be exactly `REFUSAL_TEXT` and nothing else.
5. Repeat step 4 with a context whose value is a redaction marker (use the marker form from the corpus). The answer should say the value is redacted, using the copy-deck wording, and must not present the marker as a value.

## Definition of done

The answer prompt is versioned and ships with the package, the generator fills it safely (contract text containing `{}` is fine), `REFUSAL_TEXT` matches the copy deck, and every test passes.