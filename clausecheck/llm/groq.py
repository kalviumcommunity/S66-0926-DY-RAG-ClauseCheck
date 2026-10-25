"""Groq adapter, used as the fallback provider."""

from collections.abc import Iterator

from groq import Groq
from pydantic import SecretStr

from clausecheck.llm.client import ProviderError


class GroqProvider:
    """Completions and streaming through the Groq API. Embeddings are not supported."""

    name = "groq"

    def __init__(self, api_key: SecretStr, model: str, timeout: float) -> None:
        self.model = model
        self._client = Groq(api_key=api_key.get_secret_value(), timeout=timeout)

    def complete(self, prompt: str, **kw) -> str:
        """Return the full completion for `prompt`."""
        try:
            response = self._client.chat.completions.create(
                model=self.model, messages=[{"role": "user", "content": prompt}], **kw
            )
            return response.choices[0].message.content or ""
        except Exception as exc:
            raise ProviderError(type(exc).__name__) from None

    def stream(self, prompt: str, **kw) -> Iterator[str]:
        """Yield the completion for `prompt` piece by piece."""
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                stream=True,
                **kw,
            )
            for chunk in response:
                text = chunk.choices[0].delta.content if chunk.choices else None
                if text:
                    yield text
        except Exception as exc:
            raise ProviderError(type(exc).__name__) from None

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Groq has no embeddings endpoint."""
        raise ProviderError("embeddings not supported")
