# PR 4 · Loaders and cleaner

**Branch:** `a-loaders-cleaner` · **Owner:** Diya (Data, Retrieval & Platform Foundations) · **Week:** 2 · **Depends on:** PR 3

## Context

The ingestion pipeline is load → clean → chunk → embed → index. This PR builds the first two steps:
- The **loader** turns any manifest row (PDF, HTML, DOCX, TXT) into a `RawDocument` with numbered pages and extracted tables.
- The **cleaner** removes EDGAR footers and noise, fixes hyphenation and whitespace, and **flags redactions** so the model never reads a redaction marker as a value.

Read before starting:
- `docs/architecture/ingestion-pipeline.md`
- `docs/data/data-validation-report.md`: DV-2 (CUAD text fallback), DV-5 (the **six redaction forms**), DV-6 (footer cleaning)
- `docs/architecture/tdd.md` §4.2 (`ingest/loaders`, `ingest/cleaner`)

## Scope (only these files)

| Path | Action |
|---|---|
| `clausecheck/ingest/models.py` | add |
| `clausecheck/ingest/loaders.py` | add |
| `clausecheck/ingest/cleaner.py` | add |
| `tests/fixtures/__init__.py`, `tests/fixtures/make_fixtures.py` | add (test below, verbatim) |
| `tests/conftest.py` | modify: append the `fixtures_dir` fixture below; leave the existing fixture alone |
| `tests/unit/test_loaders.py`, `tests/unit/test_cleaner.py` | add |
| `requirements.txt` | modify: add `pymupdf`, `pdfplumber`, `beautifulsoup4`, `lxml` |
| `docs/architecture/ingestion-pipeline.md` | modify: loader and cleaner behaviour as built |

## Specification

### `clausecheck/ingest/models.py`

```python
@dataclass
class Page:
    number: int          # 1-based
    text: str

@dataclass
class Table:
    page: int
    header: list[str]
    rows: list[list[str]]

@dataclass
class RawDocument:
    doc_id: str
    path: Path
    format: str          # pdf | html | docx | txt
    pages: list[Page]
    tables: list[Table] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)   # the manifest row

@dataclass
class CleanPage:
    number: int
    text: str
    has_redaction: bool

@dataclass
class CleanDocument:
    doc_id: str
    pages: list[CleanPage]
    tables: list[Table]
    has_redaction: bool
    metadata: dict
```

### `clausecheck/ingest/loaders.py`

- `class UnsupportedFormatError(ValueError)`, `class EmptyDocumentError(ValueError)`
- `load(path: Path, manifest_row: dict) -> RawDocument`. The format comes from `manifest_row["format"]` if present, otherwise from the file suffix.
  - **PDF**: PyMuPDF text per page. pdfplumber `extract_tables()` gives tables, with the first row as the header. Skip a table when it has fewer than 2 rows.
  - If every page is empty after `strip()` and `manifest_row.get("fallback_text")` is set, return one page with that text (DV-2). If there is no fallback text either, raise `EmptyDocumentError`.
  - **HTML**: BeautifulSoup with `lxml`. Remove `script`, `style`, `nav`, `header` and `footer`, then take `get_text("\n")`. Split on form feeds or `<hr>` page breaks if present, otherwise use one page. Extract `<table>` elements as tables, using the first `<tr>` as the header.
  - **DOCX**: paragraphs joined with `\n` as one page. Every table becomes a `Table(page=1, header=first row, rows=rest)`.
  - **TXT**: UTF-8 with `errors="replace"`. Split on `\f`, otherwise use one page.
  - Any other format raises `UnsupportedFormatError`.

### `clausecheck/ingest/cleaner.py`

- `REDACTION_PATTERNS: list[re.Pattern]`: one pattern per redaction form in DV-5. The test samples below are the usual EDGAR forms. If DV-5 lists different forms, **add** them, and tell me which.
- `detect_redaction(text: str) -> bool`
- `strip_footers(text: str) -> str`: removes lines matching DV-6's footer, such as `Source: <FILER>, <FORM>, <M/D/YYYY>`. Also removes lines that are only a page number (`7`, `- 7 -`, `Page 7`, `Page 7 of 12`).
- `clean_text(text: str) -> str`:
  1. strip footers
  2. join hyphenated line breaks (`provi-\nsions` → `provisions`)
  3. turn single newlines inside a sentence into spaces, but keep newlines before a numbered heading (`\n2.`, `\n2.1`, `\nSection 4`, `\nARTICLE IV`) and keep blank lines. Also keep the newline **after a heading-only line**: a line that starts with a heading pattern, is at most 80 characters, and does not end with `.`, `;` or `,` (so `1. Payment` stays on its own line)
  4. collapse runs of spaces and tabs into one space
  5. strip each line
- `clean(raw: RawDocument) -> CleanDocument`: cleans every page and sets `has_redaction` per page (detected on the **cleaned** text) and on the document. It copies tables unchanged, with cells stripped.

## Tests

### `tests/fixtures/make_fixtures.py`

```python
"""Builds small, deterministic sample documents for tests (no binary files committed)."""
from pathlib import Path

import docx
import fitz  # PyMuPDF

PDF_PAGE_1 = (
    "SUPPLY AGREEMENT\n"
    "1. General provisions\n"
    "1.1 The Supplier shall deliver the Products described in Schedule A.\n"
    "1.2 This Agreement is governed by the laws of Delaware.\n"
    "Source: ACME CORP, 10-K, 1/15/2019"
)
PDF_PAGE_2 = (
    "2. Payment\n"
    "2.1 Payment is due Net 45 days from the invoice date.\n"
    "2.2 The rebate shall be [***] percent of annual spend.\n"
    "3. Term\n"
    "3.1 The initial term is two (2) years and renews automatically.\n"
    "Source: ACME CORP, 10-K, 1/15/2019"
)

HTML = """<html><head><style>p{}</style><script>var x=1;</script></head><body>
<p>AMENDMENT NO. 1 TO SUPPLY AGREEMENT</p>
<p>1. Section 2.1 of the Agreement is amended to read: Payment is due Net 30 days.</p>
<p>2. All other terms remain in effect.</p>
<table><tr><th>Item</th><th>Old</th><th>New</th></tr>
<tr><td>Payment terms</td><td>Net 45</td><td>Net 30</td></tr></table>
<p>Source: ACME CORP, 8-K, 3/1/2020</p>
</body></html>"""

TXT = (
    "CERTIFICATE OF REGISTRATION\n"
    "ISO 27001:2022\n"
    "Supplier: Acme Corp\n"
    "Certificate number: A-114\n"
    "Valid from 2025-04-01\n"
    "Valid until 2027-03-31\n"
)

DOCX_HEADER = ["SKU", "Description", "Unit price", "Currency", "Payment terms"]
DOCX_ROWS = [
    ["SKU-001", "Steel bracket", "1,250.00", "USD", "Net 45"],
    ["SKU-002", "Copper wire 10m", "88.10", "USD", "Net 45"],
    ["SKU-003", "Fastener kit", "7.20", "USD", "Net 45"],
]


def build_all(out: Path) -> dict[str, Path]:
    out.mkdir(parents=True, exist_ok=True)
    paths = {}

    pdf = fitz.open()
    for text in (PDF_PAGE_1, PDF_PAGE_2):
        page = pdf.new_page()
        page.insert_text((50, 72), text, fontsize=10)
    paths["pdf"] = out / "acme_supply.pdf"
    pdf.save(paths["pdf"])

    blank = fitz.open()
    blank.new_page()
    paths["blank_pdf"] = out / "no_text_layer.pdf"
    blank.save(paths["blank_pdf"])

    paths["html"] = out / "acme_amendment.html"
    paths["html"].write_text(HTML, encoding="utf-8")

    d = docx.Document()
    d.add_paragraph("PRICE SCHEDULE - ACME CORP")
    d.add_paragraph("Effective date: 2025-01-01")
    table = d.add_table(rows=1 + len(DOCX_ROWS), cols=len(DOCX_HEADER))
    for i, h in enumerate(DOCX_HEADER):
        table.rows[0].cells[i].text = h
    for r, row in enumerate(DOCX_ROWS, start=1):
        for c, value in enumerate(row):
            table.rows[r].cells[c].text = value
    paths["docx"] = out / "acme_prices.docx"
    d.save(paths["docx"])

    paths["txt"] = out / "acme_iso27001.txt"
    paths["txt"].write_text(TXT, encoding="utf-8")
    return paths


MANIFEST_ROWS = {
    "pdf": {"doc_id": "cuad-acme01", "supplier_id": "S-ACME", "source": "cuad",
            "doc_type": "contract", "format": "pdf", "title": "Acme Supply Agreement",
            "effective_date": "2019-01-15", "parent_doc_id": "", "is_synthetic": "false"},
    "html": {"doc_id": "edgar-acme02", "supplier_id": "S-ACME", "source": "edgar",
             "doc_type": "amendment", "format": "html", "title": "Amendment No. 1",
             "effective_date": "2020-03-01", "parent_doc_id": "cuad-acme01", "is_synthetic": "false"},
    "docx": {"doc_id": "synthetic-acme03", "supplier_id": "S-ACME", "source": "synthetic",
             "doc_type": "price_schedule", "format": "docx", "title": "Acme price schedule",
             "effective_date": "2025-01-01", "parent_doc_id": "", "is_synthetic": "true"},
    "txt": {"doc_id": "synthetic-acme04", "supplier_id": "S-ACME", "source": "synthetic",
            "doc_type": "certificate", "format": "txt", "title": "Acme ISO 27001",
            "effective_date": "2025-04-01", "parent_doc_id": "", "is_synthetic": "true"},
}
```

### Append to `tests/conftest.py`

```python
@pytest.fixture(scope="session")
def fixtures_dir(tmp_path_factory):
    """Sample PDF, HTML, DOCX and TXT files built fresh for the test session."""
    from tests.fixtures.make_fixtures import build_all

    out = tmp_path_factory.mktemp("fixtures")
    build_all(out)
    return out


@pytest.fixture(scope="session")
def fixture_paths(fixtures_dir):
    return {
        "pdf": fixtures_dir / "acme_supply.pdf",
        "blank_pdf": fixtures_dir / "no_text_layer.pdf",
        "html": fixtures_dir / "acme_amendment.html",
        "docx": fixtures_dir / "acme_prices.docx",
        "txt": fixtures_dir / "acme_iso27001.txt",
    }
```

### `tests/unit/test_loaders.py`

```python
import pytest

from clausecheck.ingest.loaders import EmptyDocumentError, UnsupportedFormatError, load
from tests.fixtures.make_fixtures import DOCX_HEADER, DOCX_ROWS, MANIFEST_ROWS


def test_pdf_pages_numbered_and_text_present(fixture_paths):
    raw = load(fixture_paths["pdf"], MANIFEST_ROWS["pdf"])
    assert raw.format == "pdf"
    assert [p.number for p in raw.pages] == [1, 2]
    assert "General provisions" in raw.pages[0].text
    assert "Net 45" in raw.pages[1].text
    assert raw.doc_id == "cuad-acme01"
    assert raw.metadata["supplier_id"] == "S-ACME"


def test_pdf_without_text_uses_fallback(fixture_paths):
    row = dict(MANIFEST_ROWS["pdf"], fallback_text="1. Payment\nNet 60 days.")
    raw = load(fixture_paths["blank_pdf"], row)
    assert len(raw.pages) == 1
    assert "Net 60" in raw.pages[0].text


def test_pdf_without_text_and_no_fallback_raises(fixture_paths):
    with pytest.raises(EmptyDocumentError):
        load(fixture_paths["blank_pdf"], MANIFEST_ROWS["pdf"])


def test_html_text_without_markup_or_scripts(fixture_paths):
    raw = load(fixture_paths["html"], MANIFEST_ROWS["html"])
    text = "\n".join(p.text for p in raw.pages)
    assert "AMENDMENT NO. 1" in text
    assert "Net 30" in text
    assert "<p>" not in text and "var x" not in text


def test_html_table_extracted(fixture_paths):
    raw = load(fixture_paths["html"], MANIFEST_ROWS["html"])
    assert len(raw.tables) == 1
    assert raw.tables[0].header == ["Item", "Old", "New"]
    assert raw.tables[0].rows == [["Payment terms", "Net 45", "Net 30"]]


def test_docx_table_extracted(fixture_paths):
    raw = load(fixture_paths["docx"], MANIFEST_ROWS["docx"])
    assert "PRICE SCHEDULE" in raw.pages[0].text
    assert len(raw.tables) == 1
    assert raw.tables[0].header == DOCX_HEADER
    assert raw.tables[0].rows == DOCX_ROWS


def test_txt_single_page(fixture_paths):
    raw = load(fixture_paths["txt"], MANIFEST_ROWS["txt"])
    assert len(raw.pages) == 1
    assert "A-114" in raw.pages[0].text


def test_unsupported_format(tmp_path):
    p = tmp_path / "x.xyz"
    p.write_text("hello")
    with pytest.raises(UnsupportedFormatError):
        load(p, {"doc_id": "x", "format": "xyz"})
```

### `tests/unit/test_cleaner.py`

```python
import pytest

from clausecheck.ingest.cleaner import clean, clean_text, detect_redaction, strip_footers
from clausecheck.ingest.loaders import load
from tests.fixtures.make_fixtures import MANIFEST_ROWS

REDACTION_SAMPLES = [
    "The rebate is [***] percent.",
    "The rebate is *** percent.",
    "Price: [REDACTED]",
    "Price: [*]",
    "[Confidential Treatment Requested] per unit",
    "The fee is [CONFIDENTIAL PORTION OMITTED] dollars.",
]
CLEAN_SAMPLES = [
    "Payment is due Net 45 days.",
    "See Section 4.2(a) and Schedule B.",
    "Price is 3 x 4 units at $1,250.00.",
]


@pytest.mark.parametrize("text", REDACTION_SAMPLES)
def test_detects_redaction_forms(text):
    assert detect_redaction(text)


@pytest.mark.parametrize("text", CLEAN_SAMPLES)
def test_no_false_redaction(text):
    assert not detect_redaction(text)


def test_strip_footers_and_page_numbers():
    text = "1. Term\nTwo years.\nSource: ACME CORP, 10-K, 1/15/2019\n- 7 -\nPage 3 of 12\n"
    out = strip_footers(text)
    assert "Source: ACME" not in out
    assert "- 7 -" not in out and "Page 3 of 12" not in out
    assert "Two years." in out


def test_clean_text_hyphenation_and_spaces():
    assert clean_text("The provi-\nsions   apply") == "The provisions apply"


def test_clean_text_keeps_heading_breaks():
    out = clean_text("1. Payment\nInvoices are paid\nwithin 45 days.\n2. Term\nTwo years.")
    lines = out.splitlines()
    assert lines[0] == "1. Payment"
    assert "Invoices are paid within 45 days." in out
    assert any(line.startswith("2. Term") for line in lines)


def test_clean_document_flags_redaction_per_page(fixture_paths):
    doc = clean(load(fixture_paths["pdf"], MANIFEST_ROWS["pdf"]))
    assert [p.has_redaction for p in doc.pages] == [False, True]
    assert doc.has_redaction is True
    assert all("Source: ACME" not in p.text for p in doc.pages)
    assert doc.metadata["doc_type"] == "contract"


def test_clean_document_keeps_tables(fixture_paths):
    doc = clean(load(fixture_paths["docx"], MANIFEST_ROWS["docx"]))
    assert len(doc.tables) == 1
    assert doc.tables[0].header[0] == "SKU"
```

## Manual checks

1. Run `pytest -q`. Every test should pass, including all earlier ones.
2. Load and clean one real file per source from `data/raw/`, then print `doc.pages[0].text[:600]`:
   ```bash
   python -c "import csv; from pathlib import Path; from clausecheck.ingest.loaders import load; from clausecheck.ingest.cleaner import clean; rows=list(csv.DictReader(open('data/manifest.csv'))); r=[x for x in rows if x['source']=='edgar'][0]; d=clean(load(Path(r['path']), r)); print(d.pages[0].text[:600]); print('redaction:', d.has_redaction)"
   ```
   Repeat with `cuad`, `vendor` and `synthetic`. The text should be readable and have no footer lines.
3. Count how many real documents are flagged as redacted. The number should be plausible against the validation report.
4. Find one CUAD PDF with no text layer (if any), and check that the fallback text is used.

## Definition of done

Every format loads, footers are gone, all six redaction forms are flagged, tables survive with their headers, and every test passes.
