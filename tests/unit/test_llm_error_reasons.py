import pytest

from clausecheck.llm.client import LLMClient, LLMError, ProviderError, safe_reason
from tests.constants import SENTINEL


class Failing:
    def __init__(self, name, message):
        self.name, self.message = name, message

    def complete(self, prompt, **kw):
        raise ProviderError(self.message)

    def stream(self, prompt, **kw):
        raise ProviderError(self.message)
        yield  # pragma: no cover

    def embed(self, texts):
        raise ProviderError(self.message)


def client(*providers):
    return LLMClient(primary=providers[0], fallback=providers[1], max_retries=1, wait_seconds=0)


def test_the_error_says_why_each_provider_failed():
    with pytest.raises(LLMError) as caught:
        client(
            Failing("groq", "RateLimitError 429"), Failing("gemini", "ClientError 404")
        ).complete("x")
    assert caught.value.reasons == ["groq: RateLimitError 429", "gemini: ClientError 404"]


def test_a_provider_message_that_echoes_request_data_never_becomes_a_reason():
    with pytest.raises(LLMError) as caught:
        client(
            Failing("groq", f"401 invalid key {SENTINEL}"), Failing("gemini", "TimeoutError")
        ).complete("x")
    assert caught.value.reasons == ["groq: error", "gemini: TimeoutError"]
    assert SENTINEL not in str(caught.value) and SENTINEL not in " ".join(caught.value.reasons)


def test_safe_reason_keeps_only_a_class_name_and_a_status():
    assert safe_reason("groq", "RateLimitError 429") == "groq: RateLimitError 429"
    assert safe_reason("groq", "Rate limit: key=abc") == "groq: error"
    assert safe_reason("groq", "") == "groq: error"
