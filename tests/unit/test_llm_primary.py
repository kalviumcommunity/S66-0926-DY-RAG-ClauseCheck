from clausecheck.core.config import Settings
from clausecheck.llm.client import LLMClient


def _client(**overrides):
    return LLMClient.from_settings(Settings(_env_file=None, **overrides))


def test_groq_is_primary_by_default_and_gemini_the_fallback():
    client = _client()
    assert client.primary.name == "groq" and client.fallback.name == "gemini"


def test_gemini_can_be_made_primary():
    client = _client(llm_primary="gemini")
    assert client.primary.name == "gemini" and client.fallback.name == "groq"


def test_without_a_groq_key_gemini_answers_and_there_is_no_fallback():
    client = _client(groq_api_key="")
    assert client.primary.name == "gemini" and client.fallback is None
