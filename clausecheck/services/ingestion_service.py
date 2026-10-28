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
    progress=None,
) -> IngestResult:
    """Ingest one manifest row. Failures are returned, not raised.

    `progress(step, detail)` is called as the document moves through the pipeline, so an upload
    can show real counts: `extracted` (pages), `split` (clauses), `embedding`, `ready`.
    """
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
        if progress:
            texts = sum(1 for page in doc.pages if page.text.strip())
            progress("extracted", {"pages": len(doc.pages), "text_pages": texts})
        max_tokens, window, overlap = _chunk_params(settings)
        chunks = chunk(doc, max_tokens, window, overlap)
        if progress:
            progress("split", {"clauses": len(chunks)})
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
        if progress:
            progress("embedding", {"clauses": len(chunks)})
        index(conn, doc_row, chunks, embedder=embedder, vector_store=vector_store)
        if progress:
            progress("ready", {"clauses": len(chunks)})
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


class DuplicateDocumentError(Exception):
    def __init__(self, doc_id: str):
        super().__init__(doc_id)
        self.doc_id = doc_id


class UploadService:
    def __init__(
        self,
        conn_factory,
        settings,
        *,
        embedder=None,
        vector_store=None,
        on_indexed=None,
        executor=None,
    ):
        from concurrent.futures import ThreadPoolExecutor

        self.conn_factory = conn_factory
        self.settings = settings
        self.embedder = embedder
        self.vector_store = vector_store
        self.on_indexed = on_indexed
        self.executor = executor or ThreadPoolExecutor(max_workers=1)

    def _sha256(self, content: bytes) -> str:
        import hashlib

        return hashlib.sha256(content).hexdigest()

    def _safe_name(self, filename: str) -> str:
        return "".join(c if c.isalnum() or c in "._-" else "_" for c in filename)

    def submit(
        self,
        filename: str,
        content: bytes,
        supplier_id: str,
        doc_type: str = "contract",
        display_name: str | None = None,
        effective_date: str | None = None,
        amends: str | None = None,
    ) -> str:
        sha = self._sha256(content)
        # duplicate check
        conn = self.conn_factory()
        try:
            row = conn.execute("SELECT doc_id FROM documents WHERE sha256=?", (sha,)).fetchone()
        finally:
            conn.close()
        if row is not None:
            raise DuplicateDocumentError(row["doc_id"] if hasattr(row, "keys") else row[0])

        uploads_dir = self.settings.uploads_dir
        if not isinstance(uploads_dir, __import__("pathlib").Path):
            uploads_dir = __import__("pathlib").Path(uploads_dir)
        uploads_dir.mkdir(parents=True, exist_ok=True)
        dest = uploads_dir / f"{sha[:12]}_{self._safe_name(filename)}"

        import uuid

        job_id = uuid.uuid4().hex
        conn = self.conn_factory()
        try:
            conn.execute(
                "INSERT INTO jobs (job_id, kind, status, filename, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (job_id, "upload", "queued", filename, _now(), _now()),
            )
            conn.commit()
            self._record_step(
                conn,
                job_id,
                "checked",
                {"bytes": len(content), "type": Path(filename).suffix.lstrip(".").upper()},
            )
        finally:
            conn.close()

        dest.write_bytes(content)

        self.executor.submit(
            self._run,
            job_id,
            filename,
            content,
            supplier_id,
            doc_type,
            sha,
            dest,
            display_name,
            effective_date,
            amends,
        )
        return job_id

    @staticmethod
    def _record_step(conn, job_id: str, step: str, detail: dict | None = None) -> None:
        """Append one line to the job's filing log (what happened, when, with which counts)."""
        import json

        conn.execute(
            "CREATE TABLE IF NOT EXISTS job_steps " "(job_id TEXT, at TEXT, step TEXT, detail TEXT)"
        )
        conn.execute(
            "INSERT INTO job_steps (job_id, at, step, detail) VALUES (?, ?, ?, ?)",
            (job_id, _now(), step, json.dumps(detail or {})),
        )
        conn.commit()

    def _run(
        self,
        job_id,
        filename,
        content,
        supplier_id,
        doc_type,
        sha,
        dest,
        display_name=None,
        effective_date=None,
        amends=None,
    ):
        from pathlib import Path

        from clausecheck.core import ids

        conn = self.conn_factory()
        try:
            conn.execute(
                "UPDATE jobs SET status=?, updated_at=? WHERE job_id=?",
                ("running", _now(), job_id),
            )
            conn.commit()

            ext = Path(filename).suffix.lstrip(".").lower()
            if ext == "htm":
                ext = "html"
            if ext not in {"pdf", "html", "docx", "txt"}:
                ext = "txt"

            row = {
                "doc_id": ids.doc_id("upload", sha),
                "supplier_id": supplier_id,
                "source": "upload",
                "doc_type": doc_type,
                "format": ext,
                "path": str(dest),
                "title": filename,
                "effective_date": "",
                "parent_doc_id": "",
                "licence": "user upload",
                "url": "",
                "sha256": sha,
                "is_synthetic": "false",
            }

            # Create the supplier if it is new. An existing supplier keeps its display name and
            # aliases: upsert_supplier would replace both.
            try:
                if not conn.execute(
                    "SELECT 1 FROM suppliers WHERE supplier_id=?", (supplier_id,)
                ).fetchone():
                    name = (
                        display_name
                        or " ".join(supplier_id.replace("-", " ").replace("_", " ").split()).title()
                    )
                    db.upsert_supplier(conn, supplier_id, name, [supplier_id])
            except Exception:
                pass

            # An amendment must be linked to its agreement, or its clauses are just more
            # contract text. Failures here are left for ingest_document to report.
            try:
                from clausecheck.services import amendments

                head = "\n".join(p.text for p in clean(load(Path(dest), row)).pages[:2])
                row = amendments.describe(conn, row, head)
            except Exception:
                pass
            # what the user typed wins over what was read from the document
            if effective_date:
                row["effective_date"] = effective_date
            if amends:
                row["parent_doc_id"] = amends
                row["doc_type"] = "amendment"

            from clausecheck.services.ingestion_service import ingest_document

            settings = self.settings
            result = ingest_document(
                conn,
                row,
                root=Path("."),
                settings=settings,
                embedder=self.embedder,
                vector_store=self.vector_store,
                progress=lambda step, detail: self._record_step(conn, job_id, step, detail),
            )
            if result.status == "failed":
                raise RuntimeError(result.error or "ingest failed")

            conn.execute(
                "UPDATE jobs SET status=?, doc_id=?, updated_at=? WHERE job_id=?",
                ("done", result.doc_id, _now(), job_id),
            )
            conn.commit()
            if self.on_indexed is not None:
                try:
                    self.on_indexed()
                except Exception:
                    pass
        except Exception as exc:
            try:
                conn.execute(
                    "UPDATE jobs SET status=?, error=?, updated_at=? WHERE job_id=?",
                    ("failed", f"{type(exc).__name__}: {exc}", _now(), job_id),
                )
                conn.commit()
                self._record_step(conn, job_id, "failed", {"error": type(exc).__name__})
            except Exception:
                pass
        finally:
            conn.close()

    @staticmethod
    def _steps(conn, job_id: str) -> list[dict]:
        """The filing log as lines of `{"at", "id", "label", "detail"}`."""
        import json

        try:
            rows = conn.execute(
                "SELECT at, step, detail FROM job_steps WHERE job_id=? ORDER BY rowid", (job_id,)
            ).fetchall()
        except Exception:  # no step has been recorded yet, so the table may not exist
            return []
        return [
            {"at": r["at"], "id": r["step"], **describe_step(r["step"], json.loads(r["detail"]))}
            for r in rows
        ]

    def get_job(self, job_id: str):
        conn = self.conn_factory()
        try:
            row = conn.execute(
                "SELECT job_id, status, doc_id, error FROM jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None:
                return None
            return {
                "job_id": row["job_id"],
                "status": row["status"],
                "doc_id": row["doc_id"],
                "error": row["error"],
                "steps": self._steps(conn, job_id),
            }
        finally:
            conn.close()


def describe_step(step: str, detail: dict) -> dict:
    """The label and detail line for one step of the filing log."""
    n = detail.get("clauses", 0)
    if step == "checked":
        size = f"{detail.get('bytes', 0) / (1024 * 1024):.1f} MB {detail.get('type') or ''}".strip()
        return {"label": "File checked", "detail": f"{size} · not a duplicate"}
    if step == "extracted":
        pages, text = detail.get("pages", 0), detail.get("text_pages", 0)
        word = "page" if pages == 1 else "pages"
        suffix = "all with a text layer" if text == pages else f"{text} with a text layer"
        return {"label": "Text extracted", "detail": f"{pages} {word}, {suffix}"}
    if step == "split":
        return {"label": "Split into clauses", "detail": f"{n} clauses"}
    if step == "embedding":
        return {"label": "Embedding clauses", "detail": f"{n} clauses"}
    if step == "ready":
        return {"label": "Ready to check", "detail": f"{n} clauses indexed"}
    if step == "failed":
        return {"label": "Could not be filed", "detail": detail.get("error", "")}
    return {"label": step, "detail": ""}


def _now() -> str:
    import datetime

    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
