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


@pytest.fixture(scope="session")
def fixtures_dir(tmp_path_factory):
    """Sample PDF, HTML, DOCX and TXT files built fresh for the test session."""
    from tests.fixtures.make_fixtures import build_all

    out = tmp_path_factory.mktemp("fixtures")
    build_all(out)
    return out


@pytest.fixture(scope="session")
def fixture_paths(fixtures_dir):
    return {
        "pdf": fixtures_dir / "acme_supply.pdf",
        "blank_pdf": fixtures_dir / "no_text_layer.pdf",
        "html": fixtures_dir / "acme_amendment.html",
        "docx": fixtures_dir / "acme_prices.docx",
        "txt": fixtures_dir / "acme_iso27001.txt",
    }
