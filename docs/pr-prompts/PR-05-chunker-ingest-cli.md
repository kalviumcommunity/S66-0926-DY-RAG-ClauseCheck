# PR 5 · Clause chunker, SQLite store and the ingest CLI

**Branch:** `a-chunker-ingest-cli` · **Owner:** Diya (Data, Retrieval & Platform Foundations) · **Week:** 2 · **Depends on:** PR 4

## Context

Clauses are ClauseCheck's unit of meaning: it chunks, retrieves, cites and displays at clause level. This PR turns a `CleanDocument` into clause-level `Chunk`s with full metadata, stores documents and chunks in SQLite, and adds `python -m clausecheck.ingest`. The CLI ingests the whole manifest, skips unchanged files and links amendments to their parents.

Read before starting:
- `docs/architecture/rag-architecture-design.md`: the chunking decision (heading regex, 512-token cap, 400/60 windows, page fallback)
- `docs/architecture/ingestion-pipeline.md`
- `docs/architecture/tdd.md` §4–5 (components, storage schema)
- `docs/data/data-validation-report.md` DV-10 (amendment chains)

## Scope (only these files)

| Path | Action |
|---|---|
| `clausecheck/ingest/models.py` | modify: add `Chunk` |
| `clausecheck/ingest/chunker.py` | add |
| `clausecheck/store/sqlite.py` | add |
| `clausecheck/ingest/indexer.py` | add |
| `clausecheck/services/ingestion_service.py` | add |
| `clausecheck/ingest/__main__.py` | add |
| `clausecheck/core/config.py`, `.env.example` | modify: `chunk_max_tokens: int = 512`, `chunk_window: int = 400`, `chunk_overlap: int = 60` |
| `tests/helpers.py` | add (below, verbatim) |
| `tests/unit/test_chunker.py`, `tests/unit/test_sqlite.py`, `tests/integration/test_ingest.py` | add |
| `docs/architecture/ingestion-pipeline.md` | modify: schema and CLI as built |

## Specification

### `Chunk` (in `ingest/models.py`)

```python
@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    supplier_id: str
    text: str
    page: int                 # page where the chunk starts (1-based)
    section: str | None       # e.g. "2. Payment"
    clause_no: str | None     # e.g. "2.1"; None for page-fallback and table chunks
    doc_type: str
    effective_date: str | None
    parent_doc_id: str | None
    has_redaction: bool
    is_synthetic: bool
    is_table: bool
    token_count: int
    token_start: int | None = None   # set only for windowed chunks (offsets in the clause's tokens)
    token_end: int | None = None
```

### `clausecheck/ingest/chunker.py`

`chunk(doc: CleanDocument, max_tokens: int = 512, window: int = 400, overlap: int = 60) -> list[Chunk]`

1. **Heading regex** (`HEADING_RE`, multiline) matches lines that start with `\d+\.` (as in `2.`), `\d+(\.\d+)+` (as in `2.1`, `2.1.3`), `Section \d+(\.\d+)*`, or `ARTICLE [IVXLC\d]+`.
2. Walk the pages in order and keep the page number where each clause starts. A clause can continue onto the next page.
3. **Heading-only line** (a top-level pattern such as `2.`, `Section 4` or `ARTICLE IV`, at most 80 characters, not ending with `.`, `;` or `,`): this becomes the current `section`. Sub-numbered lines (`2.1`, `2.1.3`) are **always** clause lines, even without a full stop.
   - If body lines follow before the next heading, they form one chunk. Its `clause_no` is the heading's number (`"2"`), and its text is `heading + "\n" + body`.
4. **Clause line** (`2.1 Payment is due…`): starts a new chunk with `clause_no="2.1"` and the current `section`. Its text runs until the next heading.
5. Text before the first heading on a page with other headings becomes one chunk with `clause_no=None` and part `"pre"`, unless it's empty.
6. **No headings in the whole document**: create one chunk per page, with `clause_no=None` and part `f"page{n}"`.
7. **Cap**: if a chunk is longer than `max_tokens`, split its tokens (`llm.tokens.encode`) into windows of `window` tokens, each starting `window - overlap` after the previous one. Set `token_start` and `token_end`, decode the text, use part `f"{clause_no or 'page' + str(page)}-w{i}"`, and keep the same `clause_no` and `section`.
8. **Tables**: one chunk per table with `is_table=True`, `clause_no=None`, `section="table"`. The text is the header joined with `" | "`, then one line per row. If it's over `max_tokens`, split the **rows** into groups, and **repeat the header line** in each group's text.
9. Metadata comes from `doc.metadata` (`supplier_id`, `doc_type`, `effective_date`, `parent_doc_id` with empty treated as `None`, and `is_synthetic` from `"true"`). `has_redaction` comes from the page the chunk starts on (or the table's page). `token_count = count_tokens(text)`.
10. `chunk_id = ids.chunk_id(doc_id, page, part)`, where `part` is the `clause_no`, `"pre"`, `"page{n}"`, a window part, or `f"t{table_index}-{group}"`. IDs must be **unique within a document and identical across runs**. If a clause number repeats in the same document, add `-2`, `-3` and so on in order.

### `clausecheck/store/sqlite.py`

- `connect(path: Path | str) -> sqlite3.Connection`: creates parent dirs, sets `row_factory = sqlite3.Row`, and turns on `PRAGMA foreign_keys=ON` and `journal_mode=WAL` (not for `:memory:`).
- `init_db(conn) -> None`: creates these tables if they don't exist (later PRs add their own tables in their own modules):
  - `documents`: every manifest column, plus `has_redaction INTEGER`, `status TEXT`, `error TEXT`, `n_chunks INTEGER`, `ingested_at TEXT`. Primary key `doc_id`.
  - `chunks`: every `Chunk` field. Booleans are stored as INTEGER. Primary key `chunk_id`, `doc_id` references `documents(doc_id) ON DELETE CASCADE`. Indexes on `supplier_id` and `doc_id`.
  - `suppliers(supplier_id PK, display_name)` and `aliases(supplier_id, alias, PRIMARY KEY(supplier_id, alias))`
  - `jobs(job_id PK, kind, status, filename, doc_id, error, created_at, updated_at)`
- Functions:
  - `upsert_document(conn, row: dict)`
  - `get_document(conn, doc_id) -> dict | None`
  - `replace_chunks(conn, doc_id, chunks: list[Chunk])`: deletes the old chunks, inserts the new ones, and runs in one transaction
  - `get_chunks(conn, doc_id=None, supplier_id=None) -> list[Chunk]`
  - `get_chunk(conn, chunk_id) -> Chunk | None`
  - `upsert_supplier(conn, supplier_id, display_name, aliases: list[str])`
  - `list_suppliers(conn) -> list[dict]`, where each dict holds `supplier_id`, `display_name` and `aliases`
  - `counts(conn) -> dict` with keys `documents`, `chunks`, `suppliers`

### `clausecheck/ingest/indexer.py`

`index(conn, doc_row: dict, chunks: list[Chunk], *, embedder=None, vector_store=None) -> int` upserts the document row and replaces its chunks. It returns the number of chunks. `embedder` and `vector_store` are accepted and ignored for now; PR 7 uses them.

### `clausecheck/services/ingestion_service.py`

```python
@dataclass
class IngestResult:
    doc_id: str
    status: str          # "ingested" | "unchanged" | "failed" | "dry-run"
    n_chunks: int = 0
    error: str | None = None

def ingest_document(conn, row: dict, *, root: Path = Path("."), rebuild=False, dry_run=False,
                    settings=None, embedder=None, vector_store=None) -> IngestResult: ...
def run_manifest(manifest_path: Path, conn, *, suppliers_path: Path | None = None, root: Path = Path("."),
                 rebuild=False, only_supplier: str | None = None, dry_run=False,
                 settings=None, embedder=None, vector_store=None) -> list[IngestResult]: ...
```

- `ingest_document` computes the file's sha256. If a stored document already has that sha256, status `ingested`, and `rebuild` is false, it returns `unchanged` without loading. Otherwise it runs load → clean → chunk → index and stores the sha256, `status="ingested"`, `n_chunks`, `has_redaction` and `ingested_at`.
- Any exception gives `status="failed"` with `error="<ExceptionType>: <message>"`. The document row is stored with `status="failed"`, and the run **continues**.
- `dry_run` loads, cleans and chunks, but **writes nothing**, and returns `status="dry-run"` with `n_chunks`.
- `run_manifest` loads suppliers first (when `suppliers_path` is given, and not in a dry run), then processes rows **parents before children**, so an amendment never arrives before the document it amends. It skips rows whose `supplier_id` doesn't match `only_supplier`.

### `clausecheck/ingest/__main__.py`

`main(argv: list[str] | None = None) -> int` with flags:
- `--manifest` (default `data/manifest.csv`)
- `--suppliers` (default `data/suppliers.csv`)
- `--db` (default `settings.sqlite_path`)
- `--root` (default `.`)
- `--dry-run`, `--rebuild`, `--only-supplier ID`

It prints a summary table: counts per status, total chunks, then each failure with its error. It returns `0`, or `1` only when every document failed. It finishes with `if __name__ == "__main__": raise SystemExit(main())`.

## Tests

### `tests/helpers.py`

```python
"""Small builders shared by tests from PR 5 onward."""
import csv
from pathlib import Path

from clausecheck.ingest.models import Chunk, CleanDocument, CleanPage
from clausecheck.llm.tokens import count_tokens


def make_chunk(**overrides) -> Chunk:
    text = overrides.pop("text", "2.1 Payment is due Net 45 days from the invoice date.")
    base = dict(
        chunk_id="doc-a:p1:2_1", doc_id="doc-a", supplier_id="S-ACME", text=text, page=1,
        section="2. Payment", clause_no="2.1", doc_type="contract", effective_date="2019-01-15",
        parent_doc_id=None, has_redaction=False, is_synthetic=False, is_table=False,
        token_count=count_tokens(text),
    )
    base.update(overrides)
    return Chunk(**base)


def make_doc(pages: list[str], doc_id: str = "doc-a", tables=None, **meta) -> CleanDocument:
    metadata = {"doc_id": doc_id, "supplier_id": "S-ACME", "doc_type": "contract",
                "effective_date": "2019-01-15", "parent_doc_id": "", "is_synthetic": "false"}
    metadata.update(meta)
    return CleanDocument(
        doc_id=doc_id,
        pages=[CleanPage(number=i + 1, text=t, has_redaction="[***]" in t) for i, t in enumerate(pages)],
        tables=tables or [],
        has_redaction=any("[***]" in t for t in pages),
        metadata=metadata,
    )


MANIFEST_EXTRA = {"licence": "CC BY 4.0", "url": "https://example.com", "sha256": "0" * 64}


def write_manifest(tmp_path: Path, fixture_paths: dict, manifest_rows: dict) -> tuple[Path, Path]:
    """Writes manifest.csv and suppliers.csv for the 4 fixture documents (absolute paths)."""
    from clausecheck.core.schema import MANIFEST_COLUMNS, SUPPLIER_COLUMNS

    manifest = tmp_path / "manifest.csv"
    with manifest.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_COLUMNS)
        w.writeheader()
        for key in ["html", "pdf", "docx", "txt"]:  # child listed before parent on purpose
            row = {c: "" for c in MANIFEST_COLUMNS}
            row.update(MANIFEST_EXTRA)
            row.update(manifest_rows[key])
            row["path"] = str(fixture_paths[key])
            w.writerow(row)
    suppliers = tmp_path / "suppliers.csv"
    with suppliers.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SUPPLIER_COLUMNS)
        w.writeheader()
        w.writerow({"supplier_id": "S-ACME", "display_name": "Acme Corp", "aliases": "Acme|ACME Corporation"})
    return manifest, suppliers
```

### `tests/unit/test_chunker.py`

```python
from clausecheck.ingest.chunker import chunk
from clausecheck.ingest.models import Table
from clausecheck.llm.tokens import count_tokens
from tests.helpers import make_doc


def test_heading_only_sections_become_clause_chunks():
    doc = make_doc(["1. Definitions\nA means B.\n2. Payment\nNet 45 days.\n3. Term\nTwo years."])
    chunks = chunk(doc)
    assert [c.clause_no for c in chunks] == ["1", "2", "3"]
    assert chunks[1].section == "2. Payment"
    assert chunks[1].text.startswith("2. Payment")
    assert "Net 45" in chunks[1].text


def test_subclauses_get_their_own_chunks_with_section():
    doc = make_doc(["2. Payment\n2.1 Net 45 days.\n2.2 Late fee 1.5% per month.\n3. Term\n3.1 Two years."])
    chunks = chunk(doc)
    assert [c.clause_no for c in chunks] == ["2.1", "2.2", "3.1"]
    assert chunks[0].section == "2. Payment" and chunks[2].section == "3. Term"


def test_clause_spanning_pages_starts_on_first_page():
    doc = make_doc(["1. Scope\n1.1 The Supplier shall deliver", "the goods by truck.\n1.2 Risk passes on delivery."])
    chunks = chunk(doc)
    first = next(c for c in chunks if c.clause_no == "1.1")
    assert first.page == 1 and "by truck" in first.text
    assert next(c for c in chunks if c.clause_no == "1.2").page == 2


def test_long_clause_is_windowed_with_overlap():
    body = " ".join(f"word{i}" for i in range(2000))
    doc = make_doc([f"5. Scope\n{body}"])
    chunks = chunk(doc, max_tokens=512, window=400, overlap=60)
    assert len(chunks) > 1
    assert all(c.token_count <= 512 for c in chunks)
    assert all(c.clause_no == "5" for c in chunks)
    for a, b in zip(chunks, chunks[1:]):
        assert b.token_start == a.token_end - 60
    assert len({c.chunk_id for c in chunks}) == len(chunks)


def test_page_fallback_when_no_headings():
    doc = make_doc(["This certificate confirms compliance.", "It is valid until 2027."])
    chunks = chunk(doc)
    assert [c.page for c in chunks] == [1, 2]
    assert all(c.clause_no is None for c in chunks)


def test_ids_are_stable_and_unique():
    doc = make_doc(["1. A\nx.\n1. A\ny.\n2. B\nz."])
    first, second = chunk(doc), chunk(doc)
    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]
    assert len({c.chunk_id for c in first}) == len(first)


def test_metadata_copied_and_redaction_flag():
    doc = make_doc(["2. Payment\n2.1 Rebate is [***] percent."], doc_type="amendment",
                   parent_doc_id="doc-parent", is_synthetic="true")
    c = chunk(doc)[0]
    assert (c.doc_type, c.parent_doc_id, c.is_synthetic, c.has_redaction) == ("amendment", "doc-parent", True, True)
    assert c.supplier_id == "S-ACME" and c.token_count == count_tokens(c.text)


def test_empty_parent_becomes_none():
    assert chunk(make_doc(["1. A\nx."]))[0].parent_doc_id is None


def test_table_chunk_keeps_header():
    t = Table(page=1, header=["SKU", "Unit price"], rows=[["A-1", "7.20"], ["A-2", "1,250.00"]])
    chunks = [c for c in chunk(make_doc(["Prices"], tables=[t])) if c.is_table]
    assert len(chunks) == 1
    assert chunks[0].text.splitlines()[0] == "SKU | Unit price"
    assert "1,250.00" in chunks[0].text


def test_big_table_splits_rows_and_repeats_header():
    t = Table(page=1, header=["SKU", "Description", "Unit price"],
              rows=[[f"SKU-{i:03d}", "Steel bracket heavy duty", f"{i}.00"] for i in range(200)])
    chunks = [c for c in chunk(make_doc(["Prices"], tables=[t]), max_tokens=120) if c.is_table]
    assert len(chunks) > 1
    assert all(c.text.splitlines()[0] == "SKU | Description | Unit price" for c in chunks)
    assert all(c.token_count <= 120 for c in chunks)
```

### `tests/unit/test_sqlite.py`

```python
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
```

### `tests/integration/test_ingest.py`

```python
from clausecheck.ingest.__main__ import main
from clausecheck.services.ingestion_service import run_manifest
from clausecheck.store import sqlite as db
from tests.fixtures.make_fixtures import MANIFEST_ROWS
from tests.helpers import write_manifest


def _setup(tmp_path, fixture_paths):
    manifest, suppliers = write_manifest(tmp_path, fixture_paths, MANIFEST_ROWS)
    conn = db.connect(tmp_path / "ingest.db")
    db.init_db(conn)
    return manifest, suppliers, conn


def test_first_run_ingests_everything(tmp_path, fixture_paths):
    manifest, suppliers, conn = _setup(tmp_path, fixture_paths)
    results = run_manifest(manifest, conn, suppliers_path=suppliers)
    assert {r.status for r in results} == {"ingested"}, [(r.doc_id, r.error) for r in results]
    counts = db.counts(conn)
    assert counts["documents"] == 4 and counts["chunks"] > 4 and counts["suppliers"] == 1
    bad = conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE supplier_id IS NULL OR page IS NULL OR doc_type IS NULL"
    ).fetchone()[0]
    assert bad == 0


def test_amendment_linked_to_parent(tmp_path, fixture_paths):
    manifest, suppliers, conn = _setup(tmp_path, fixture_paths)
    run_manifest(manifest, conn, suppliers_path=suppliers)
    assert db.get_document(conn, "edgar-acme02")["parent_doc_id"] == "cuad-acme01"
    assert all(c.parent_doc_id == "cuad-acme01" for c in db.get_chunks(conn, doc_id="edgar-acme02"))


def test_second_run_skips_unchanged_and_rebuild_reingests(tmp_path, fixture_paths):
    manifest, suppliers, conn = _setup(tmp_path, fixture_paths)
    run_manifest(manifest, conn, suppliers_path=suppliers)
    assert {r.status for r in run_manifest(manifest, conn)} == {"unchanged"}
    assert {r.status for r in run_manifest(manifest, conn, rebuild=True)} == {"ingested"}


def test_dry_run_writes_nothing(tmp_path, fixture_paths):
    manifest, suppliers, conn = _setup(tmp_path, fixture_paths)
    results = run_manifest(manifest, conn, suppliers_path=suppliers, dry_run=True)
    assert {r.status for r in results} == {"dry-run"} and all(r.n_chunks > 0 for r in results)
    assert db.counts(conn) == {"documents": 0, "chunks": 0, "suppliers": 0}


def test_missing_file_fails_without_stopping_run(tmp_path, fixture_paths):
    paths = dict(fixture_paths, txt=tmp_path / "does_not_exist.txt")
    manifest, suppliers = write_manifest(tmp_path, paths, MANIFEST_ROWS)
    conn = db.connect(tmp_path / "f.db")
    db.init_db(conn)
    results = {r.doc_id: r for r in run_manifest(manifest, conn, suppliers_path=suppliers)}
    assert results["synthetic-acme04"].status == "failed" and results["synthetic-acme04"].error
    assert results["cuad-acme01"].status == "ingested"


def test_only_supplier_filter(tmp_path, fixture_paths):
    manifest, suppliers, conn = _setup(tmp_path, fixture_paths)
    assert run_manifest(manifest, conn, only_supplier="S-NOBODY") == []


def test_cli_returns_zero_and_prints_summary(tmp_path, fixture_paths, capsys):
    manifest, suppliers, _ = _setup(tmp_path, fixture_paths)
    code = main(["--manifest", str(manifest), "--suppliers", str(suppliers), "--db", str(tmp_path / "cli.db")])
    assert code == 0
    assert "ingested" in capsys.readouterr().out
```

## Manual checks

1. Run `pytest -q`. Every test should pass.
2. Run `python -m clausecheck.ingest --dry-run` on the real corpus. Expect a summary in which every failure has a reason. Paste the summary into the PR description.
3. Run `python -m clausecheck.ingest`, then run it again. The second run should show every document as `unchanged`.
4. Run `sqlite3 index/clausecheck.db "SELECT COUNT(*) FROM chunks WHERE supplier_id IS NULL OR page IS NULL OR doc_type IS NULL;"`. Expect `0`.
5. Run `sqlite3 index/clausecheck.db "SELECT MAX(token_count), AVG(token_count) FROM chunks;"`. The max should be at most 512.
6. Run `sqlite3 index/clausecheck.db "SELECT clause_no, substr(text,1,80) FROM chunks WHERE doc_id=(SELECT doc_id FROM documents WHERE source='cuad' LIMIT 1) LIMIT 15;"`. Each row should hold one clause.
7. Pick one amendment and check that `parent_doc_id` points at the right contract (DV-10 chains included).

## Definition of done

The whole corpus becomes clause chunks with complete metadata, re-runs skip unchanged files, failures are reported without stopping the run, and every test passes. **Gate M3.**
