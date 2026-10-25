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
