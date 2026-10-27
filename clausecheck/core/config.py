"""Application settings, loaded from environment variables and an optional `.env` file."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

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
    judge_model: str = "llama-3.3-70b-versatile"

    # LLM client behaviour
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 3
    llm_retry_wait_seconds: float = 1.0
    gen_temperature: float = 0.0

    # Context building and relevance gate (PR 10)
    context_token_budget: int = 3000
    relevance_threshold: float = 0.0

    # Sessions, cache and query log (PR 12)
    history_turns: int = 3
    cache_ttl_seconds: int = 86400

    # Logging
    log_level: str = "INFO"

    # Embeddings and vector search
    embed_provider: Literal["gemini", "local"] = "gemini"
    embed_model: str = "text-embedding-004"
    local_embed_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embed_batch: int = 32
    index_version: str = "v1"
    top_k: int = 5

    # Retrieval: hybrid search, re-ranking and supplier detection
    rrf_k: int = 60
    vector_k: int = 20
    bm25_k: int = 20
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    rerank_candidates: int = 20
    rerank_top_n: int = 5
    supplier_match_min: int = 85

    # Chunking
    chunk_max_tokens: int = 512
    chunk_window: int = 400
    chunk_overlap: int = 60

    # Corpus sourcing
    edgar_user_agent: str = ""
    raw_data_dir: Path = Path("data/raw")

    # Storage
    data_dir: Path = Path("data")
    index_dir: Path = Path("index")
    sqlite_path: Path = Path("index/clausecheck.db")

    # API (PR 15)
    frontend_origin: str = "http://localhost:8501"
    port: int = 7860

    # Uploads (PR 16)
    max_upload_mb: int = 20
    allowed_types: str = "pdf,html,htm,docx,txt"
    uploads_dir: Path = Path("data/uploads")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings object, built once."""
    return Settings()
