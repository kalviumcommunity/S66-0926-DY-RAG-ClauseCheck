import pytest
from pydantic import SecretStr, ValidationError

from clausecheck.core.config import Settings, get_settings
from tests.constants import SENTINEL


def test_secrets_are_secretstr():
    s = Settings(_env_file=None)
    assert isinstance(s.gemini_api_key, SecretStr)
    assert isinstance(s.groq_api_key, SecretStr)
    assert s.gemini_api_key.get_secret_value() == SENTINEL


def test_printing_settings_never_shows_secrets():
    s = Settings(_env_file=None)
    for text in (repr(s), str(s), s.model_dump_json()):
        assert SENTINEL not in text


def test_missing_secret_names_the_variable_but_no_values(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY")
    with pytest.raises(ValidationError) as err:
        Settings(_env_file=None)
    msg = str(err.value)
    assert "gemini_api_key" in msg.lower()
    assert SENTINEL not in msg


def test_defaults_are_sane():
    s = Settings(_env_file=None)
    assert s.llm_max_retries >= 1
    assert s.llm_timeout_seconds > 0
    assert s.gemini_model and s.groq_model


def test_get_settings_is_cached():
    assert get_settings() is get_settings()
