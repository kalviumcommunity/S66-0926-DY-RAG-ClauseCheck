from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[2] / "frontend" / "app.py"


def test_app_renders_without_backend():
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.secrets["API_BASE_URL"] = "http://127.0.0.1:9"
    at.run()
    assert not at.exception
    assert len(at.error) >= 1
    assert len(at.tabs) == 2
