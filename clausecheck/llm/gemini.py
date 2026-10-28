"""Gemini adapter (google-genai SDK)."""

from collections.abc import Iterator

from google import genai
from google.genai import types
from pydantic import SecretStr

from clausecheck.llm.client import provider_error


class GeminiProvider:
    """Completions, streaming and embeddings through the Gemini API."""

    name = "gemini"

    def __init__(
        self,
        api_key: SecretStr,
        model: str,
        timeout: float,
        embed_model: str = "gemini-embedding-001",
    ) -> None:
        self.model = model
        self.embed_model = embed_model
        self._api_key = api_key
        self._timeout = timeout
        self._client_obj: genai.Client | None = None

    @property
    def _client(self) -> genai.Client:
        """Built on first use, so a missing key fails the call, not the app start-up."""
        if self._client_obj is None:
            self._client_obj = genai.Client(
                api_key=self._api_key.get_secret_value(),
                http_options=types.HttpOptions(timeout=int(self._timeout * 1000)),
            )
        return self._client_obj

    @staticmethod
    def _options(kw: dict) -> dict:
        """The SDK takes sampling options inside `config`, not as keyword arguments."""
        options = dict(kw)
        temperature = options.pop("temperature", None)
        if temperature is not None:
            options["config"] = types.GenerateContentConfig(temperature=temperature)
        return options

    def complete(self, prompt: str, **kw) -> str:
        """Return the full completion for `prompt`."""
        try:
            response = self._client.models.generate_content(
                model=self.model, contents=prompt, **self._options(kw)
            )
            return response.text or ""
        except Exception as exc:
            raise provider_error(self.name, exc) from None

    def stream(self, prompt: str, **kw) -> Iterator[str]:
        """Yield the completion for `prompt` piece by piece."""
        try:
            for chunk in self._client.models.generate_content_stream(
                model=self.model, contents=prompt, **self._options(kw)
            ):
                if chunk.text:
                    yield chunk.text
        except Exception as exc:
            raise provider_error(self.name, exc) from None

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per text."""
        try:
            response = self._client.models.embed_content(
                model=self.embed_model,
                contents=list(texts),  # type: ignore[arg-type]  # SDK stubs reject list[str]
            )
            return [list(e.values or []) for e in response.embeddings or []]
        except Exception as exc:
            raise provider_error(self.name, exc) from None
