import importlib.util
from pathlib import Path

from clausecheck.core.config import Settings
from clausecheck.store import sqlite as db
from tests.helpers import make_chunk

ROOT = Path(__file__).resolve().parents[2]


def _mod():
    spec = importlib.util.spec_from_file_location("bootstrap", ROOT / "scripts/bootstrap.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_builds_when_missing_and_skips_when_present(tmp_path):
    boot = _mod()
    s = Settings(_env_file=None, index_dir=tmp_path / "idx", sqlite_path=tmp_path / "idx" / "c.db")
    built = []

    def build():
        conn = db.connect(s.sqlite_path)
        db.init_db(conn)
        db.upsert_document(conn, {"doc_id": "doc-a", "supplier_id": "S-ACME", "doc_type": "contract"})
        db.replace_chunks(conn, "doc-a", [make_chunk()])
        built.append(True)

    assert boot.ensure_index(s, build_fn=build) == "built"
    assert boot.ensure_index(s, build_fn=build) == "present"
    assert built == [True]


def test_restores_from_archive_url(tmp_path):
    boot = _mod()
    s = Settings(_env_file=None, index_dir=tmp_path / "idx", sqlite_path=tmp_path / "idx" / "c.db",
                 index_archive_url="https://example.com/index.tar.gz")
    calls = []
    assert boot.ensure_index(s, build_fn=lambda: None, download_fn=lambda url, d: calls.append(url)) == "restored"
    assert calls == ["https://example.com/index.tar.gz"]


def test_pack_creates_archive(tmp_path):
    boot = _mod()
    (tmp_path / "idx").mkdir()
    (tmp_path / "idx" / "c.db").write_bytes(b"x")
    out = boot.pack(tmp_path / "idx", tmp_path / "index.tar.gz")
    assert out.exists() and out.stat().st_size > 0
