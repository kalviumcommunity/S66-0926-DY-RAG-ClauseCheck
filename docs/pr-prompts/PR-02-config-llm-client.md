# PR 2 · Settings, safe logging, IDs and the LLM client

**Branch:** `a-config-llm-client` · **Owner:** Diya (Data, Retrieval & Platform Foundations) · **Week:** 1 · **Depends on:** PR 1

## Context

ClauseCheck uses Gemini as its main LLM and Groq as the fallback, through the free tiers. Every module reads configuration from one settings object, and no key may ever reach a log, an error or an HTTP response.

Read before starting: `docs/requirements/non-functional-requirements.md` NFR-2 (AC-N2.1 to AC-N2.7), `docs/architecture/tdd.md` §4 (module dependencies, `llm/client`).

## Goal

Create the foundations every other workstream imports:
- `core/config.py` for settings
- `core/logging.py` for logging with redaction
- `core/ids.py` for stable IDs
- `llm/` for one client with retries and fallback

## Scope (only these files)

| Path | Action |
|---|---|
| `clausecheck/core/config.py` | add |
| `clausecheck/core/logging.py` | add |
| `clausecheck/core/ids.py` | add |
| `clausecheck/llm/client.py` | add |
| `clausecheck/llm/gemini.py` | add |
| `clausecheck/llm/groq.py` | add |
| `clausecheck/llm/tokens.py` | add |
| `.env.example` | add |
| `requirements.txt` | modify: add `google-genai`, `groq`, `tenacity`, `tiktoken` (pinned) |
| `tests/constants.py`, `tests/conftest.py` | add |
| `tests/unit/test_config.py`, `test_env_example.py`, `test_logging_redaction.py`, `test_ids.py`, `test_llm_client.py`, `test_tokens.py` | add |
| `README.md` | modify: "Configuration" section |

## Specification

### `clausecheck/core/config.py`

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)
    gemini_api_key: SecretStr            # required
    groq_api_key: SecretStr              # required
    gemini_model: str = "gemini-2.0-flash"       # confirm the current free-tier name
    groq_model: str = "llama-3.3-70b-versatile"  # confirm the current name
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 3
    llm_retry_wait_seconds: float = 1.0
    log_level: str = "INFO"
    data_dir: Path = Path("data")
    index_dir: Path = Path("index")
    sqlite_path: Path = Path("index/clausecheck.db")

def get_settings() -> Settings: ...   # functools.lru_cache(maxsize=1)
```

- Field names are lowercase snake_case **without aliases**, and the env var is the uppercase name. Later PRs add fields here and in `.env.example` together.
- `hide_input_in_errors=True` is required. Without it, pydantic prints other settings' values inside the "missing field" error (AC-N2.6).

### `clausecheck/core/logging.py`

- `REDACTED = "[REDACTED]"`
- `class RedactionFilter(logging.Filter)`: `__init__(self, secrets: Iterable[str])` ignores empty strings. `filter(record)` does three things and then returns `True`:
  1. Sets `record.msg = record.getMessage()` with every secret replaced, and sets `record.args = ()`.
  2. If `record.exc_info` is set, formats it with `logging.Formatter().formatException`, redacts the result into `record.exc_text`, and sets `record.exc_info = None`.
  3. Redacts an existing `record.exc_text`.
- `def setup_logging(settings: Settings, stream: IO[str] | None = None) -> logging.Handler`: configures the root logger at `settings.log_level` with one `StreamHandler(stream or sys.stderr)`, a JSON formatter (`ts`, `level`, `logger`, `msg`), and a `RedactionFilter` built from **every `SecretStr` field** in settings. **Attach the filter to the handler, not the root logger.** Logger filters don't run on records that propagate from child loggers. It removes any handler it added earlier and returns the handler.

### `clausecheck/core/ids.py`

- `doc_id(source: str, name: str) -> str`: `f"{source}-{sha1(name.encode()).hexdigest()[:12]}"`, lowercase, matches `^[a-z0-9-]+$`.
- `chunk_id(doc_id: str, page: int, part: str | int) -> str`: `f"{doc_id}:p{page}:{part}"`, where `part` is the clause number (dots become `_`) or `w{n}` for a window.
- `query_id() -> str`: `uuid4().hex`.

### `clausecheck/llm/`

- `client.py`:
  - `class ProviderError(Exception)`: raised by adapters.
  - `class LLMError(Exception)`: raised by the client. **Its message is exactly `"All LLM providers failed: <comma-separated provider names>"`**. It never contains the providers' error text, because that can hold keys.
  - `class LLMProvider(Protocol)`: `name: str`, `complete(prompt: str, **kw) -> str`, `stream(prompt: str, **kw) -> Iterator[str]`, `embed(texts: list[str]) -> list[list[float]]`.
  - `class LLMClient`: `__init__(self, primary, fallback=None, max_retries=3, wait_seconds=1.0)` and `@classmethod from_settings(cls, settings)`. It has the same three methods. Each method tries `primary` up to `max_retries` times (tenacity, fixed wait `wait_seconds`, retry only on `ProviderError`), then `fallback` up to `max_retries` times, then raises `LLMError`. Each failure is logged at WARNING with the provider name and attempt number only.
  - `stream`: retry and fallback apply **only until the first token arrives**. Pull the first item with `next()` inside the retry. A failure after the first token raises `LLMError`.
- `gemini.py` / `groq.py`: `GeminiProvider(api_key: SecretStr, model: str, timeout: float)` and `GroqProvider(...)`. They implement the protocol and wrap any SDK exception in `ProviderError(type(exc).__name__)`. Embeddings: Gemini uses `text-embedding-004` (make the model a constructor argument). Groq's `embed` raises `ProviderError("embeddings not supported")`.
- `tokens.py`: `count_tokens(text) -> int`, `encode(text) -> list[int]`, `decode(tokens) -> str`, all with `tiktoken.get_encoding("cl100k_base")`, cached.

### `.env.example`

Every `Settings` field in uppercase, `KEY=value` per line, with secrets left empty (`GEMINI_API_KEY=`). Add a one-line comment above each group.

## Tests

### `tests/constants.py`

```python
SENTINEL = "TEST-SENTINEL-7f3a"
```

### `tests/conftest.py`

```python
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
```

### `tests/unit/test_config.py`

```python
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
```

### `tests/unit/test_env_example.py`

```python
"""AC-N2.2: .env.example documents every setting, secrets empty."""
import shutil
import subprocess
from pathlib import Path

import pytest

from clausecheck.core.config import Settings

ROOT = Path(__file__).resolve().parents[2]


def _parse_env_example() -> dict[str, str]:
    keys = {}
    for line in (ROOT / ".env.example").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        keys[key.strip()] = value.strip()
    return keys


def test_env_example_matches_settings_exactly():
    keys = set(_parse_env_example())
    fields = {name.upper() for name in Settings.model_fields}
    assert keys == fields, f"missing in .env.example: {fields - keys}; extra: {keys - fields}"


def test_secret_values_are_empty():
    keys = _parse_env_example()
    for name, field in Settings.model_fields.items():
        if "SecretStr" in str(field.annotation):
            assert keys[name.upper()] == "", f"{name.upper()} must be empty in .env.example"


def test_no_dotenv_committed():
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    assert ".env" not in tracked
```

### `tests/unit/test_logging_redaction.py`

```python
import io
import json
import logging

from clausecheck.core.config import Settings
from clausecheck.core.logging import REDACTED, RedactionFilter, setup_logging
from tests.constants import SENTINEL


def _logger_with_filter(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.filters.clear()
    logger.addFilter(RedactionFilter([SENTINEL, ""]))
    return logger


def test_secret_in_message_is_redacted(caplog):
    logger = _logger_with_filter("test.redact.msg")
    with caplog.at_level(logging.INFO, logger="test.redact.msg"):
        logger.info("calling with key=%s", SENTINEL)
    assert SENTINEL not in caplog.text
    assert REDACTED in caplog.text


def test_secret_in_exception_is_redacted(caplog):
    logger = _logger_with_filter("test.redact.exc")
    with caplog.at_level(logging.INFO, logger="test.redact.exc"):
        try:
            raise RuntimeError(f"401 Unauthorized for key {SENTINEL}")
        except RuntimeError:
            logger.exception("provider failed")
    assert SENTINEL not in caplog.text
    assert "provider failed" in caplog.text


def test_setup_logging_writes_json_and_redacts_all_secret_fields():
    stream = io.StringIO()
    setup_logging(Settings(_env_file=None), stream=stream)
    logging.getLogger("clausecheck.test").warning("keys %s %s", SENTINEL, SENTINEL + "-groq")
    out = stream.getvalue().strip().splitlines()[-1]
    assert SENTINEL not in out
    record = json.loads(out)
    assert {"ts", "level", "logger", "msg"} <= record.keys()
    assert record["level"] == "WARNING"


def test_setup_logging_is_idempotent():
    stream = io.StringIO()
    s = Settings(_env_file=None)
    setup_logging(s, stream=stream)
    setup_logging(s, stream=stream)
    logging.getLogger("clausecheck.once").warning("hello")
    assert stream.getvalue().count("hello") == 1
```

### `tests/unit/test_ids.py`

```python
import re

from clausecheck.core.ids import chunk_id, doc_id, query_id


def test_doc_id_is_deterministic_and_safe():
    a = doc_id("cuad", "LohaCompanyltd_20191209_F-1_EX-10.16 Supply Agreement")
    assert a == doc_id("cuad", "LohaCompanyltd_20191209_F-1_EX-10.16 Supply Agreement")
    assert a.startswith("cuad-")
    assert re.fullmatch(r"[a-z0-9-]+", a)
    assert a != doc_id("cuad", "Another contract")


def test_chunk_id_format():
    assert chunk_id("cuad-abc", 3, "4.2") == "cuad-abc:p3:4_2"
    assert chunk_id("cuad-abc", 1, "w0") == "cuad-abc:p1:w0"


def test_query_id_unique_hex():
    ids = {query_id() for _ in range(100)}
    assert len(ids) == 100
    assert all(re.fullmatch(r"[0-9a-f]{32}", i) for i in ids)
```

### `tests/unit/test_llm_client.py`

```python
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
```

### `tests/unit/test_tokens.py`

```python
from clausecheck.llm.tokens import count_tokens, decode, encode


def test_count_tokens():
    assert count_tokens("") == 0
    assert count_tokens("Payment is due Net 45 days.") > 3


def test_encode_decode_roundtrip():
    text = "Section 4.2: Supplier shall invoice monthly."
    assert decode(encode(text)) == text
```

## Manual checks

1. Run `pytest -q`. Every test should pass.
2. Copy `.env.example` to `.env` and add your real keys. Then run `python -c "from clausecheck.core.config import get_settings; print(get_settings())"`. Both keys should print as `**********`.
3. Comment out `GEMINI_API_KEY` in `.env` and run the same command. It should fail, name `gemini_api_key`, and print no values.
4. Run `python -c "from clausecheck.core.config import get_settings; from clausecheck.llm.client import LLMClient; print(LLMClient.from_settings(get_settings()).complete('Reply with OK'))"`. Expect a short reply.
5. Put a wrong value in `GEMINI_API_KEY` and repeat step 4. You should see 3 WARNING lines for gemini, and the reply should still arrive from Groq.
6. Run `python -c "from clausecheck.core.config import get_settings; from clausecheck.llm.client import LLMClient; print(len(LLMClient.from_settings(get_settings()).embed(['hello'])[0]))"`. It should print the embedding size (for example 768).

## Definition of done

All tests pass. A real key never appears in any output, the Gemini-to-Groq fallback works with real keys.
