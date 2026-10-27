from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_dockerfile():
    text = (ROOT / "Dockerfile").read_text()
    assert "EXPOSE 7860" in text and "bootstrap.py" in text and "--factory" in text
    assert ".env" not in text.replace(".env.example", "")


def test_dockerignore_excludes_secrets_and_data():
    lines = {l.strip() for l in (ROOT / ".dockerignore").read_text().splitlines()}
    assert {".env", "index/", "data/raw/"} <= lines


def test_frontend_secrets_example_only():
    import shutil
    import subprocess

    assert (ROOT / "frontend/.streamlit/secrets.toml.example").exists()
    if shutil.which("git") and (ROOT / ".git").exists():
        tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.splitlines()
        assert "frontend/.streamlit/secrets.toml" not in tracked


def test_ci_has_deploy_and_eval_smoke():
    text = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "HF_TOKEN" in text and "eval-smoke" in text and "deploy" in text
