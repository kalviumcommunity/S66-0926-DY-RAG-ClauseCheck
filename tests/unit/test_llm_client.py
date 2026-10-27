import pytest

from clausecheck.llm.client import LLMClient, LLMError, ProviderError
from tests.constants import SENTINEL


class FakeProvider:
    def __init__(self, name, fail_times=0, always_fail=False):
        self.name = name
        self.fail_times = fail_times
        self.always_fail = always_fail
        self.calls = 0

    def _maybe_fail(self):
        self.calls += 1
        if self.always_fail or self.calls <= self.fail_times:
            raise ProviderError(f"401 bad key {SENTINEL}")

    def complete(self, prompt, **kw):
        self._maybe_fail()
        return f"{self.name}:ok"

    def stream(self, prompt, **kw):
        self._maybe_fail()
        yield from ["a", "b", "c"]

    def embed(self, texts):
        self._maybe_fail()
        return [[0.1, 0.2] for _ in texts]


def make(primary, fallback=None):
    return LLMClient(primary=primary, fallback=fallback, max_retries=3, wait_seconds=0)


def test_primary_success_no_fallback_call():
    p, f = FakeProvider("gemini"), FakeProvider("groq")
    assert make(p, f).complete("hi") == "gemini:ok"
    assert (p.calls, f.calls) == (1, 0)


def test_retries_primary_before_fallback():
    p, f = FakeProvider("gemini", fail_times=2), FakeProvider("groq")
    assert make(p, f).complete("hi") == "gemini:ok"
    assert (p.calls, f.calls) == (3, 0)


def test_falls_back_after_max_retries():
    p, f = FakeProvider("gemini", always_fail=True), FakeProvider("groq")
    assert make(p, f).complete("hi") == "groq:ok"
    assert p.calls == 3


def test_both_fail_raises_clean_llm_error():
    p, f = FakeProvider("gemini", always_fail=True), FakeProvider("groq", always_fail=True)
    with pytest.raises(LLMError) as err:
        make(p, f).complete("hi")
    assert str(err.value) == "All LLM providers failed: gemini, groq"
    assert SENTINEL not in str(err.value)


def test_no_fallback_raises():
    with pytest.raises(LLMError):
        make(FakeProvider("gemini", always_fail=True)).complete("hi")


def test_stream_falls_back_before_first_token():
    p, f = FakeProvider("gemini", always_fail=True), FakeProvider("groq")
    assert list(make(p, f).stream("hi")) == ["a", "b", "c"]


def test_embed_returns_one_vector_per_text():
    vectors = make(FakeProvider("gemini")).embed(["x", "y"])
    assert len(vectors) == 2


def test_failures_logged_without_secret(caplog):
    p, f = FakeProvider("gemini", fail_times=1), FakeProvider("groq")
    make(p, f).complete("hi")
    assert SENTINEL not in caplog.text
