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
