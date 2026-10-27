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
