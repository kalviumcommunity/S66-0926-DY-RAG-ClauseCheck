"""SQLite storage: documents, chunks, suppliers and ingestion jobs."""

import sqlite3
from dataclasses import asdict, fields
from pathlib import Path

from clausecheck.core.schema import MANIFEST_COLUMNS
from clausecheck.ingest.models import Chunk

DOCUMENT_COLUMNS = [
    *MANIFEST_COLUMNS,
    "has_redaction",
    "status",
    "error",
    "n_chunks",
    "ingested_at",
]
CHUNK_FIELDS = [f.name for f in fields(Chunk)]
CHUNK_BOOLS = {"has_redaction", "is_synthetic", "is_table"}

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS documents (
    {", ".join(f"{c} INTEGER" if c in ("has_redaction", "n_chunks") else f"{c} TEXT"
               for c in DOCUMENT_COLUMNS)},
    PRIMARY KEY (doc_id)
);
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    supplier_id TEXT,
    text TEXT,
    page INTEGER,
    section TEXT,
    clause_no TEXT,
    doc_type TEXT,
    effective_date TEXT,
    parent_doc_id TEXT,
    has_redaction INTEGER,
    is_synthetic INTEGER,
    is_table INTEGER,
    token_count INTEGER,
    token_start INTEGER,
    token_end INTEGER
);
CREATE INDEX IF NOT EXISTS idx_chunks_supplier ON chunks(supplier_id);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);
CREATE TABLE IF NOT EXISTS suppliers (
    supplier_id TEXT PRIMARY KEY,
    display_name TEXT
);
CREATE TABLE IF NOT EXISTS aliases (
    supplier_id TEXT,
    alias TEXT,
    PRIMARY KEY (supplier_id, alias)
);
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    kind TEXT,
    status TEXT,
    filename TEXT,
    doc_id TEXT,
    error TEXT,
    created_at TEXT,
    updated_at TEXT
);
"""


def connect(path: Path | str) -> sqlite3.Connection:
    """Open a database, creating parent folders; rows come back as `sqlite3.Row`."""
    in_memory = str(path) == ":memory:"
    if not in_memory:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    if not in_memory:
        conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create the tables and indexes if they do not exist."""
    conn.executescript(_SCHEMA)
    conn.commit()


def upsert_document(conn: sqlite3.Connection, row: dict) -> None:
    """Insert a document, or update only the columns present in `row`."""
    data = {k: v for k, v in row.items() if k in DOCUMENT_COLUMNS}
    columns = ", ".join(data)
    marks = ", ".join("?" for _ in data)
    updates = ", ".join(f"{c}=excluded.{c}" for c in data if c != "doc_id")
    sql = f"INSERT INTO documents ({columns}) VALUES ({marks}) ON CONFLICT(doc_id) DO "
    sql += f"UPDATE SET {updates}" if updates else "NOTHING"
    with conn:
        conn.execute(sql, list(data.values()))


def get_document(conn: sqlite3.Connection, doc_id: str) -> dict | None:
    """Return a document row as a dict, or None."""
    row = conn.execute("SELECT * FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
    return dict(row) if row else None


def _chunk_values(chunk: Chunk) -> list:
    data = asdict(chunk)
    return [int(data[f]) if f in CHUNK_BOOLS else data[f] for f in CHUNK_FIELDS]


def _to_chunk(row: sqlite3.Row) -> Chunk:
    data = {f: row[f] for f in CHUNK_FIELDS}
    for name in CHUNK_BOOLS:
        data[name] = bool(data[name])
    return Chunk(**data)


def replace_chunks(conn: sqlite3.Connection, doc_id: str, chunks: list[Chunk]) -> None:
    """Delete a document's chunks and insert the new ones in one transaction."""
    marks = ", ".join("?" for _ in CHUNK_FIELDS)
    with conn:
        conn.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
        conn.executemany(
            f"INSERT INTO chunks ({', '.join(CHUNK_FIELDS)}) VALUES ({marks})",
            [_chunk_values(c) for c in chunks],
        )


def get_chunks(
    conn: sqlite3.Connection, doc_id: str | None = None, supplier_id: str | None = None
) -> list[Chunk]:
    """Return chunks, optionally filtered by document and/or supplier, in insertion order."""
    where, args = [], []
    if doc_id is not None:
        where.append("doc_id=?")
        args.append(doc_id)
    if supplier_id is not None:
        where.append("supplier_id=?")
        args.append(supplier_id)
    sql = "SELECT * FROM chunks" + (" WHERE " + " AND ".join(where) if where else "")
    return [_to_chunk(r) for r in conn.execute(sql + " ORDER BY rowid", args)]


def get_chunk(conn: sqlite3.Connection, chunk_id: str) -> Chunk | None:
    """Return one chunk by ID, or None."""
    row = conn.execute("SELECT * FROM chunks WHERE chunk_id=?", (chunk_id,)).fetchone()
    return _to_chunk(row) if row else None


def upsert_supplier(
    conn: sqlite3.Connection, supplier_id: str, display_name: str, aliases: list[str]
) -> None:
    """Insert or update a supplier and replace its alias list."""
    with conn:
        conn.execute(
            "INSERT INTO suppliers (supplier_id, display_name) VALUES (?, ?) "
            "ON CONFLICT(supplier_id) DO UPDATE SET display_name=excluded.display_name",
            (supplier_id, display_name),
        )
        conn.execute("DELETE FROM aliases WHERE supplier_id=?", (supplier_id,))
        conn.executemany(
            "INSERT OR IGNORE INTO aliases (supplier_id, alias) VALUES (?, ?)",
            [(supplier_id, a) for a in aliases if a],
        )


def list_suppliers(conn: sqlite3.Connection) -> list[dict]:
    """Return suppliers with their aliases, ordered by ID."""
    out = []
    for row in conn.execute("SELECT supplier_id, display_name FROM suppliers ORDER BY supplier_id"):
        aliases = conn.execute(
            "SELECT alias FROM aliases WHERE supplier_id=? ORDER BY alias", (row["supplier_id"],)
        )
        out.append(
            {
                "supplier_id": row["supplier_id"],
                "display_name": row["display_name"],
                "aliases": [a[0] for a in aliases],
            }
        )
    return out


def counts(conn: sqlite3.Connection) -> dict:
    """Return the number of documents, chunks and suppliers."""
    return {
        name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        for name in ("documents", "chunks", "suppliers")
    }
