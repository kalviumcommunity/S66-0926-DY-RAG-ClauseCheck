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
