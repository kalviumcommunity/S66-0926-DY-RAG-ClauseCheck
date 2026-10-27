"""One LLM client with retries on the primary provider and a fallback provider."""

import logging
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Protocol, TypeVar

from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_fixed

if TYPE_CHECKING:
    from clausecheck.core.config import Settings

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ProviderError(Exception):
    """Raised by a provider adapter when a call fails."""


def describe_error(exc: Exception) -> str:
    """The exception type and HTTP status code, such as `RateLimitError 429`.

    Never the message: provider messages can echo request data, including keys.
    """
    code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    name = type(exc).__name__
    return f"{name} {code}" if isinstance(code, int) else name


def provider_error(provider: str, exc: Exception) -> ProviderError:
    """A `ProviderError` for an adapter to raise; logs why, using only `describe_error`."""
    reason = describe_error(exc)
    logger.warning("%s call failed: %s", provider, reason)
    return ProviderError(reason)


class LLMError(Exception):
    """Raised by the client when every provider has failed. Never carries provider text."""


class LLMProvider(Protocol):
    """What the client needs from a provider adapter."""

    name: str

    def complete(self, prompt: str, **kw) -> str:
        """Return the full completion for `prompt`."""
        ...

    def stream(self, prompt: str, **kw) -> Iterator[str]:
        """Yield the completion for `prompt` piece by piece."""
        ...

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per text."""
        ...


class LLMClient:
    """Calls the primary provider with retries, then the fallback, then raises `LLMError`."""

    def __init__(
        self,
        primary: LLMProvider,
        fallback: LLMProvider | None = None,
        max_retries: int = 3,
        wait_seconds: float = 1.0,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.max_retries = max_retries
        self.wait_seconds = wait_seconds

    @classmethod
    def from_settings(cls, settings: "Settings") -> "LLMClient":
        """Build a client from `LLM_PRIMARY`; the other provider is the fallback.

        Groq is optional: without its key, Gemini is the primary and failures are final.
        """
        from clausecheck.llm.gemini import GeminiProvider
        from clausecheck.llm.groq import GroqProvider

        gemini = GeminiProvider(
            settings.gemini_api_key, settings.gemini_model, settings.llm_timeout_seconds
        )
        groq = (
            GroqProvider(settings.groq_api_key, settings.groq_model, settings.llm_timeout_seconds)
            if settings.groq_api_key.get_secret_value()
            else None
        )
        if settings.llm_primary == "groq" and groq is not None:
            primary, fallback = groq, gemini
        else:
            primary, fallback = gemini, groq
        return cls(
            primary=primary,
            fallback=fallback,
            max_retries=settings.llm_max_retries,
            wait_seconds=settings.llm_retry_wait_seconds,
        )

    @property
    def _providers(self) -> list[LLMProvider]:
        return [p for p in (self.primary, self.fallback) if p is not None]

    def _attempt(self, provider: LLMProvider, call: Callable[[], T]) -> T:
        """Run `call` up to `max_retries` times, retrying only on `ProviderError`."""
        retrying = Retrying(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_fixed(self.wait_seconds),
            retry=retry_if_exception_type(ProviderError),
            reraise=True,
        )
        for attempt in retrying:
            with attempt:
                try:
                    return call()
                except ProviderError:
                    logger.warning(
                        "LLM provider %s failed (attempt %d)",
                        provider.name,
                        attempt.retry_state.attempt_number,
                    )
                    raise
        raise AssertionError("unreachable")  # pragma: no cover

    def _run(self, make_call: Callable[[LLMProvider], Callable[[], T]]) -> T:
        for provider in self._providers:
            try:
                return self._attempt(provider, make_call(provider))
            except ProviderError:
                continue
        raise self._failure()

    def _failure(self) -> LLMError:
        return LLMError("All LLM providers failed: " + ", ".join(p.name for p in self._providers))

    def complete(self, prompt: str, **kw) -> str:
        """Return a completion, falling back to the second provider if needed."""
        return self._run(lambda p: lambda: p.complete(prompt, **kw))

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding per text, falling back to the second provider if needed."""
        return self._run(lambda p: lambda: p.embed(texts))

    def stream(self, prompt: str, **kw) -> Iterator[str]:
        """Yield a completion piece by piece.

        Retry and fallback apply only until the first piece arrives; a later failure
        raises `LLMError`.
        """
        _end = object()

        def start(provider: LLMProvider) -> Callable[[], tuple[object, Iterator[str]]]:
            def call() -> tuple[object, Iterator[str]]:
                it = iter(provider.stream(prompt, **kw))
                return next(it, _end), it

            return call

        first, it = self._run(start)
        if first is _end:
            return
        yield first  # type: ignore[misc]
        try:
            yield from it
        except ProviderError:
            raise self._failure() from None
