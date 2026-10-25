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
