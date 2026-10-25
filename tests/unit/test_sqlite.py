from clausecheck.store import sqlite as db
from tests.helpers import make_chunk


def _conn(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.init_db(conn)
    return conn


def test_tables_created(tmp_path):
    conn = _conn(tmp_path)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"documents", "chunks", "suppliers", "aliases", "jobs"} <= names


def test_document_upsert_is_idempotent(tmp_path):
    conn = _conn(tmp_path)
    row = {"doc_id": "doc-a", "supplier_id": "S-ACME", "doc_type": "contract", "sha256": "1" * 64}
    db.upsert_document(conn, row)
    db.upsert_document(conn, dict(row, sha256="2" * 64))
    assert db.counts(conn)["documents"] == 1
    assert db.get_document(conn, "doc-a")["sha256"] == "2" * 64


def test_replace_chunks_roundtrip(tmp_path):
    conn = _conn(tmp_path)
    db.upsert_document(conn, {"doc_id": "doc-a", "supplier_id": "S-ACME", "doc_type": "contract"})
    chunks = [make_chunk(), make_chunk(chunk_id="doc-a:p1:2_2", clause_no="2.2", has_redaction=True)]
    db.replace_chunks(conn, "doc-a", chunks)
    db.replace_chunks(conn, "doc-a", chunks)
    got = db.get_chunks(conn, doc_id="doc-a")
    assert len(got) == 2
    assert db.get_chunk(conn, "doc-a:p1:2_2").has_redaction is True
    assert db.get_chunk(conn, "missing") is None
    assert db.get_chunks(conn, supplier_id="S-OTHER") == []


def test_suppliers_and_aliases(tmp_path):
    conn = _conn(tmp_path)
    db.upsert_supplier(conn, "S-ACME", "Acme Corp", ["Acme", "ACME Corporation"])
    db.upsert_supplier(conn, "S-ACME", "Acme Corp", ["Acme"])
    suppliers = db.list_suppliers(conn)
    assert suppliers == [{"supplier_id": "S-ACME", "display_name": "Acme Corp", "aliases": ["Acme"]}]
