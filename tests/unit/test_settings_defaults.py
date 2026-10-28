"""The settings the project was tuned on, and `.env.example` agreeing with the code."""

from pathlib import Path

from clausecheck.core.config import Settings

ROOT = Path(__file__).resolve().parents[2]
SECRETS = {"GEMINI_API_KEY", "GROQ_API_KEY"}


def example_values() -> dict[str, str]:
    values = {}
    for line in (ROOT / ".env.example").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def test_tuned_settings_keep_their_values():
    s = Settings(_env_file=None)
    assert s.relevance_threshold == -8.0  # debugging.md 2.32: a tighter gate refused real answers
    assert s.llm_primary == "groq"  # debugging.md 2.33: flash-lite refused answerable questions
    assert s.embed_provider == "gemini"  # the README tells people to set EMBED_PROVIDER=local


def test_env_example_matches_the_defaults_in_the_code():
    # a value in .env.example that differs from the code default is a documentation bug
    example = {k: v for k, v in example_values().items() if v != "" and k not in SECRETS}
    defaults = Settings(_env_file=None)
    from_example = Settings(_env_file=None, **{k.lower(): v for k, v in example.items()})
    differing = {
        field: (getattr(defaults, field), getattr(from_example, field))
        for field in Settings.model_fields
        if getattr(defaults, field) != getattr(from_example, field)
    }
    assert not differing, differing


def test_the_example_leaves_the_secrets_empty():
    values = example_values()
    assert all(values[key] == "" for key in SECRETS)
