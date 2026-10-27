"""Grounded answer generator: fills the versioned prompt and calls the LLM client."""

from collections.abc import Iterator

from clausecheck.prompts.loader import Prompt, load_prompt

REFUSAL_TEXT = "I couldn't find this in the contracts I have for this supplier."


class Generator:
    """Fill the answer prompt and call the LLM client (blocking or streamed)."""

    def __init__(self, client, prompt: Prompt, temperature: float = 0.0) -> None:
        self.client = client
        self.prompt = prompt
        self.temperature = temperature

    def build_prompt(self, question, context_text) -> str:
        """Fill placeholders safely (contract text may contain ``{}``)."""
        return self.prompt.text.replace("{{context}}", str(context_text)).replace(
            "{{question}}", str(question)
        )

    def generate(self, question, context_text) -> str:
        """Return the stripped completion."""
        filled = self.build_prompt(question, context_text)
        return self.client.complete(filled, temperature=self.temperature).strip()

    def stream(self, question, context_text) -> Iterator[str]:
        """Yield completion tokens as they arrive."""
        filled = self.build_prompt(question, context_text)
        yield from self.client.stream(filled, temperature=self.temperature)

    @classmethod
    def from_settings(cls, settings) -> "Generator":
        """Build a generator using the real LLM client and the shipped answer prompt."""
        from clausecheck.llm.client import LLMClient

        client = LLMClient.from_settings(settings)
        prompt = load_prompt("answer")
        return cls(client, prompt, temperature=getattr(settings, "gen_temperature", 0.0))
