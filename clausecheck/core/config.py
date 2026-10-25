"""Application settings, loaded from environment variables and an optional `.env` file."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration for ClauseCheck. Each field maps to an uppercase env var."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    # LLM providers
    gemini_api_key: SecretStr
    groq_api_key: SecretStr
    gemini_model: str = "gemini-2.0-flash"
    groq_model: str = "llama-3.3-70b-versatile"

    # LLM client behaviour
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 3
    llm_retry_wait_seconds: float = 1.0

    # Logging
    log_level: str = "INFO"

    # Corpus sourcing
    edgar_user_agent: str = ""
    raw_data_dir: Path = Path("data/raw")

    # Storage
    data_dir: Path = Path("data")
    index_dir: Path = Path("index")
    sqlite_path: Path = Path("index/clausecheck.db")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings object, built once."""
    return Settings()
