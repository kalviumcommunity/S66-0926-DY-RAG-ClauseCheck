"""Smoke tests: the package installs and every subpackage imports."""
import importlib
import re


def test_package_has_semver_version():
    import clausecheck

    assert re.fullmatch(r"\d+\.\d+\.\d+", clausecheck.__version__)


def test_all_subpackages_import():
    for name in ["core", "ingest", "rag", "store", "llm", "services", "api"]:
        importlib.import_module(f"clausecheck.{name}")
