"""Gemini adapter (google-genai SDK)."""

from collections.abc import Iterator

from google import genai
from google.genai import types
from pydantic import SecretStr

from clausecheck.llm.client import ProviderError


class GeminiProvider:
    """Completions, streaming and embeddings through the Gemini API."""

    name = "gemini"

    def __init__(
        self,
        api_key: SecretStr,
        model: str,
        timeout: float,
        embed_model: str = "text-embedding-004",
    ) -> None:
        self.model = model
        self.embed_model = embed_model
        self._client = genai.Client(
            api_key=api_key.get_secret_value(),
            http_options=types.HttpOptions(timeout=int(timeout * 1000)),
        )

    def complete(self, prompt: str, **kw) -> str:
        """Return the full completion for `prompt`."""
        try:
            response = self._client.models.generate_content(model=self.model, contents=prompt, **kw)
            return response.text or ""
        except Exception as exc:
            raise ProviderError(type(exc).__name__) from None

    def stream(self, prompt: str, **kw) -> Iterator[str]:
        """Yield the completion for `prompt` piece by piece."""
        try:
            for chunk in self._client.models.generate_content_stream(
                model=self.model, contents=prompt, **kw
            ):
                if chunk.text:
                    yield chunk.text
        except Exception as exc:
            raise ProviderError(type(exc).__name__) from None

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per text."""
        try:
            response = self._client.models.embed_content(model=self.embed_model, contents=texts)
            return [list(e.values) for e in response.embeddings]
        except Exception as exc:
            raise ProviderError(type(exc).__name__) from None
