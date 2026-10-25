# PR 1 · Repo scaffold, tooling and CI

**Branch:** `a-repo-scaffold` · **Owner:** Diya (Data, Retrieval & Platform Foundations) · **Week:** 1 · **Depends on:** nothing

## Context

ClauseCheck is a RAG assistant that answers questions about negotiated supplier contract terms and cites the exact clause. Repo: `FirstName_ClauseCheck_Kalvium-Community`. Right now it contains only `README.md` and `docs/` with subfolders `architecture/`, `data/`, `planning/`, `requirements/` and `ux/`.

Read before starting: `docs/requirements/tdd.md` §17 (repository layout) and `docs/requirements/non-functional-requirements.md` NFR-2 (secrets).

## Goal

Turn the repo into an installable Python package with clean docs, pre-commit hooks and CI. After this PR, `pip install -e .` and `pytest` work on a fresh clone, and every PR runs lint, a secrets scan and the tests.

## Scope (only these files)

| Path | Action | What to do |
|---|---|---|
| `docs/requirements/PRD (1).md` → `docs/requirements/PRD.md` | rename | `git mv` |
| `docs/planning/development-plan (1).md` → `docs/planning/development-plan.md` | rename | `git mv` |
| `docs/requirements/tdd.md` → `docs/architecture/tdd.md` | move | `git mv`, then update §17 to the layout below |
| `.DS_Store`, `docs/.DS_Store` | delete | `git rm --cached`, delete from disk |
| `docs/data/data-validation-report.md` | add | **I will paste it in.** Create it only if I've provided it, otherwise stop and ask |
| `docs/ux/ui-states.md` | add | Same as above |
| `docs/team-charter.md` | add | Template: members, workstream owners A–D and reviewers (blank cells), working rules from `development-plan.md` §4 |
| `docs/**/*.md` | modify | Turn cross-references into relative Markdown links that resolve, e.g. `[PRD](../requirements/PRD.md)` |
| `docs/planning/development-plan.md` | modify | Remove the daily journal requirement (§4.1, §4.3 item 3, §15 "journal entries"); eval numbers go in the PR description instead |
| `.gitignore` | add | See spec |
| `pyproject.toml` | add | See spec |
| `requirements.txt` | add | See spec |
| `.pre-commit-config.yaml` | add | ruff, black, detect-secrets, nbstripout, end-of-file-fixer, trailing-whitespace |
| `.secrets.baseline` | add | `detect-secrets scan > .secrets.baseline` |
| `NOTICE` | add | CUAD attribution: "Contract Understanding Atticus Dataset (CUAD) v1 by The Atticus Project, licensed under CC BY 4.0", with link |
| `.github/workflows/ci.yml` | add | See spec |
| `clausecheck/__init__.py` | add | `__version__ = "0.1.0"` |
| `clausecheck/{core,ingest,rag,store,llm,services,api}/__init__.py` | add | empty |
| `clausecheck/prompts/.gitkeep`, `frontend/.gitkeep`, `scripts/.gitkeep`, `notebooks/.gitkeep`, `eval/results/.gitkeep`, `data/raw/.gitkeep`, `data/uploads/.gitkeep` | add | empty |
| `tests/__init__.py`, `tests/unit/__init__.py`, `tests/integration/__init__.py`, `tests/api/__init__.py` | add | empty |
| `tests/unit/test_smoke.py`, `tests/unit/test_repo_layout.py` | add | Tests below, verbatim |
| `README.md` | modify | One-paragraph summary, setup steps (venv, `pip install -e . -r requirements.txt`, `pre-commit install`), folder map |

## Specification

**`.gitignore`** must contain these exact lines (others are fine too): `.env`, `.DS_Store`, `__pycache__/`, `.venv/`, `index/`, `data/raw/*`, `!data/raw/.gitkeep`, `data/uploads/*`, `!data/uploads/.gitkeep`, `.pytest_cache/`, `.ruff_cache/`, `*.egg-info/`, `frontend/.streamlit/secrets.toml`.

**`pyproject.toml`**
- `[project]` name `clausecheck`, `requires-python = ">=3.11"`, dynamic version from `clausecheck.__version__`, setuptools packages = `clausecheck*` only.
- `[tool.ruff]` `line-length = 100`, `target-version = "py311"`, `select = ["E","F","I","B","UP"]`.
- `[tool.black]` `line-length = 100`.
- `[tool.pytest.ini_options]` `testpaths = ["tests"]`, `pythonpath = ["."]`, `addopts = "-ra"`, markers: `e2e: needs a running deployment (skipped unless CLAUSECHECK_E2E=1)`, `targets: corpus size targets`, `slow: downloads models`.

**`requirements.txt`**: pinned with `==`. Runtime: `pydantic`, `pydantic-settings`, `python-dotenv`. Dev: `pytest`, `pytest-cov`, `ruff`, `black`, `pre-commit`, `detect-secrets`, `nbstripout`. Later PRs append to this file.

**`.github/workflows/ci.yml`**: on `pull_request` and `push` to `main`, Python 3.11, cache pip. Jobs: `lint` (`ruff check .`, `black --check .`), `secrets` (`detect-secrets scan --baseline .secrets.baseline` followed by a check that fails on new findings), `test` (`pip install -e . -r requirements.txt`, `pytest -q`).

**`docs/architecture/tdd.md` §17**: replace the tree with the final layout. It is the current tree plus `NOTICE`, `pyproject.toml`, `.pre-commit-config.yaml`, `.secrets.baseline`, `data/fetch_log.csv`, `scripts/validate_cuad.py`, `notebooks/`, `docs/` subfolders, `docs/evaluation/`, and these modules: `ingest/models.py`, `rag/types.py`, `rag/vector_retriever.py`, `rag/context_builder.py`, `prompts/loader.py`, `services/sessions.py`, `frontend/components/insights.py`.

## Tests

### `tests/unit/test_smoke.py`

```python
"""Smoke tests: the package installs and every subpackage imports."""
import importlib
import re


def test_package_has_semver_version():
    import clausecheck

    assert re.fullmatch(r"\d+\.\d+\.\d+", clausecheck.__version__)


def test_all_subpackages_import():
    for name in ["core", "ingest", "rag", "store", "llm", "services", "api"]:
        importlib.import_module(f"clausecheck.{name}")
```

### `tests/unit/test_repo_layout.py`

```python
"""Repository hygiene: required files exist, no junk is tracked, docs links resolve."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

REQUIRED_FILES = [
    ".gitignore",
    "pyproject.toml",
    "requirements.txt",
    ".pre-commit-config.yaml",
    ".secrets.baseline",
    "NOTICE",
    "README.md",
    ".github/workflows/ci.yml",
    "docs/01-project-overview.md",
    "docs/02-project-description.md",
    "docs/team-charter.md",
    "docs/requirements/PRD.md",
    "docs/requirements/functional-requirements.md",
    "docs/requirements/non-functional-requirements.md",
    "docs/planning/development-plan.md",
    "docs/planning/roadmap.md",
    "docs/architecture/tdd.md",
    "docs/architecture/rag-architecture-design.md",
    "docs/architecture/api-design.md",
    "docs/architecture/data-flow.md",
    "docs/architecture/ingestion-pipeline.md",
    "docs/data/data-sourcing.md",
    "docs/data/data-validation-report.md",
    "docs/ux/mock-ux.md",
    "docs/ux/user-flows.md",
    "docs/ux/ui-states.md",
]

REQUIRED_DIRS = [
    "clausecheck/core",
    "clausecheck/ingest",
    "clausecheck/rag",
    "clausecheck/store",
    "clausecheck/llm",
    "clausecheck/services",
    "clausecheck/api",
    "clausecheck/prompts",
    "frontend",
    "scripts",
    "notebooks",
    "eval/results",
    "data/raw",
    "data/uploads",
    "tests/unit",
    "tests/integration",
    "tests/api",
]


def _tracked_files() -> list[str]:
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [line for line in out.splitlines() if line]


def test_required_files_exist():
    missing = [p for p in REQUIRED_FILES if not (ROOT / p).is_file()]
    assert not missing, f"missing files: {missing}"


def test_required_dirs_exist():
    missing = [d for d in REQUIRED_DIRS if not (ROOT / d).is_dir()]
    assert not missing, f"missing dirs: {missing}"


def test_old_paths_are_gone():
    assert not (ROOT / "docs/requirements/PRD (1).md").exists()
    assert not (ROOT / "docs/planning/development-plan (1).md").exists()
    assert not (ROOT / "docs/requirements/tdd.md").exists()


def test_no_junk_or_bad_names_tracked():
    bad = [
        f
        for f in _tracked_files()
        if f.endswith(".DS_Store") or "(1)" in f or (f.startswith("docs/") and " " in f)
    ]
    assert not bad, f"rename or remove: {bad}"


def test_no_env_file_tracked():
    tracked = _tracked_files()
    bad = [f for f in tracked if Path(f).name == ".env" or (f.endswith(".env") and not f.endswith(".env.example"))]
    assert not bad


def test_gitignore_has_required_entries():
    lines = {l.strip() for l in (ROOT / ".gitignore").read_text().splitlines()}
    for entry in [".env", ".DS_Store", "__pycache__/", "index/", "data/raw/*", "data/uploads/*"]:
        assert entry in lines, f".gitignore missing {entry}"


def test_precommit_has_required_hooks():
    text = (ROOT / ".pre-commit-config.yaml").read_text()
    for hook in ["ruff", "black", "detect-secrets", "nbstripout"]:
        assert hook in text, f"pre-commit missing {hook}"


def test_ci_runs_lint_secrets_and_tests():
    text = (ROOT / ".github/workflows/ci.yml").read_text()
    for word in ["ruff", "black", "detect-secrets", "pytest", "pull_request"]:
        assert word in text, f"ci.yml missing {word}"


def test_notice_attributes_cuad():
    text = (ROOT / "NOTICE").read_text()
    assert "CUAD" in text and "CC BY 4.0" in text


def test_tdd_layout_lists_new_modules():
    text = (ROOT / "docs/architecture/tdd.md").read_text()
    for name in ["context_builder.py", "vector_retriever.py", "models.py", "sessions.py", "notebooks/"]:
        assert name in text, f"tdd.md §17 missing {name}"


LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def test_relative_doc_links_resolve():
    broken = []
    for md in (ROOT / "docs").rglob("*.md"):
        for target in LINK.findall(md.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            path = target.split("#", 1)[0]
            if path and not (md.parent / path).resolve().exists():
                broken.append(f"{md.relative_to(ROOT)} -> {target}")
    assert not broken, "broken links:\n" + "\n".join(broken)
```

## Manual checks

1. Clone the branch into a fresh folder, then run `python -m venv .venv && source .venv/bin/activate && pip install -e . -r requirements.txt`. Expect no errors.
2. Run `pytest -q`. Every test should pass (the git tests skip only outside a git checkout).
3. Run `pre-commit install && pre-commit run --all-files`. Every hook should pass.
4. Push the branch and open the PR. CI should show `lint`, `secrets` and `test`, all green.
5. Make a throwaway commit with an unused import and push it. CI `lint` should fail. Revert the commit.
6. In GitHub, go to Settings → Branches and protect `main`, requiring the 3 checks and 1 review.

## Definition of done

All tests pass, CI is green, `main` is protected, and the docs are renamed, moved and cross-linked.
