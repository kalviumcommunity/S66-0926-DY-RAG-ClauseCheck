"""Shared fixtures. Every test runs with fake, recognisable keys."""
import pytest

from tests.constants import SENTINEL


@pytest.fixture(autouse=True)
def sentinel_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", SENTINEL)
    monkeypatch.setenv("GROQ_API_KEY", SENTINEL + "-groq")
    from clausecheck.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
