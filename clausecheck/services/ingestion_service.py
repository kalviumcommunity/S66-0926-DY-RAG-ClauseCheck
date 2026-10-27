"""Ingest documents from the manifest: load, clean, chunk and index."""

import csv
import datetime as dt
import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from clausecheck.ingest.chunker import chunk
from clausecheck.ingest.cleaner import clean
from clausecheck.ingest.indexer import index
from clausecheck.ingest.loaders import load
from clausecheck.store import sqlite as db

DEFAULT_CHUNK_PARAMS = (512, 400, 60)


@dataclass
class IngestResult:
    """Outcome for one document."""

    doc_id: str
    status: str  # "ingested" | "unchanged" | "failed" | "dry-run"
    n_chunks: int = 0
    error: str | None = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _chunk_params(settings) -> tuple[int, int, int]:
    if settings is None:
        try:
            from clausecheck.core.config import get_settings

            settings = get_settings()
        except Exception:  # keys may be missing; chunking does not need them
            return DEFAULT_CHUNK_PARAMS
    return settings.chunk_max_tokens, settings.chunk_window, settings.chunk_overlap


def _fallback_text(path: Path, row: dict) -> str | None:
    """CUAD text saved next to the PDF by the fetch script, used if the PDF has no text layer."""
    sidecar = path.parent / "json_text" / f"{path.stem}.txt"
    if row.get("format") == "pdf" and sidecar.exists():
        return sidecar.read_text(encoding="utf-8")
    return None


def ingest_document(
    conn: sqlite3.Connection,
    row: dict,
    *,
    root: Path = Path("."),
    rebuild: bool = False,
    dry_run: bool = False,
    settings=None,
    embedder=None,
    vector_store=None,
) -> IngestResult:
    """Ingest one manifest row. Failures are returned, not raised."""
    doc_id = row["doc_id"]
    try:
        path = Path(root) / row["path"]
        sha = _sha256(path)
        stored = db.get_document(conn, doc_id)
        if stored and stored["sha256"] == sha and stored["status"] == "ingested" and not rebuild:
            return IngestResult(doc_id, "unchanged", stored["n_chunks"] or 0)

        load_row = dict(row)
        if "fallback_text" not in load_row and (fallback := _fallback_text(path, row)):
            load_row["fallback_text"] = fallback
        doc = clean(load(path, load_row))
        max_tokens, window, overlap = _chunk_params(settings)
        chunks = chunk(doc, max_tokens, window, overlap)
        if dry_run:
            return IngestResult(doc_id, "dry-run", len(chunks))

        doc_row = dict(
            row,
            sha256=sha,
            has_redaction=int(doc.has_redaction),
            status="ingested",
            error=None,
            n_chunks=len(chunks),
            ingested_at=dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        index(conn, doc_row, chunks, embedder=embedder, vector_store=vector_store)
        return IngestResult(doc_id, "ingested", len(chunks))
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        if not dry_run:
            db.upsert_document(conn, dict(row, status="failed", error=error))
        return IngestResult(doc_id, "failed", error=error)


def _parents_first(rows: list[dict]) -> list[dict]:
    """Order rows so that a document comes after the document it amends."""
    ids = {r["doc_id"] for r in rows}
    ordered: list[dict] = []
    done: set[str] = set()
    pending = list(rows)
    while pending:
        ready = [
            r
            for r in pending
            if not r.get("parent_doc_id")
            or r["parent_doc_id"] in done
            or r["parent_doc_id"] not in ids
        ]
        if not ready:  # a cycle: keep the manifest order
            ready = pending
        for r in ready:
            ordered.append(r)
            done.add(r["doc_id"])
        pending = [r for r in pending if r not in ready]
    return ordered


def _load_suppliers(conn: sqlite3.Connection, path: Path) -> None:
    with path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            aliases = [a for a in (r.get("aliases") or "").split("|") if a]
            db.upsert_supplier(conn, r["supplier_id"], r["display_name"], aliases)


def run_manifest(
    manifest_path: Path,
    conn: sqlite3.Connection,
    *,
    suppliers_path: Path | None = None,
    root: Path = Path("."),
    rebuild: bool = False,
    only_supplier: str | None = None,
    dry_run: bool = False,
    settings=None,
    embedder=None,
    vector_store=None,
) -> list[IngestResult]:
    """Ingest every manifest row, parents before children, and return one result per row."""
    if suppliers_path is not None and not dry_run:
        _load_suppliers(conn, suppliers_path)
    with Path(manifest_path).open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    results = []
    for row in _parents_first(rows):
        if only_supplier and row.get("supplier_id") != only_supplier:
            continue
        results.append(
            ingest_document(
                conn,
                row,
                root=root,
                rebuild=rebuild,
                dry_run=dry_run,
                settings=settings,
                embedder=embedder,
                vector_store=vector_store,
            )
        )
    return results
