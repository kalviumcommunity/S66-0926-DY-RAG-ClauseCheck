from clausecheck.ingest.cleaner import strip_running_lines
from clausecheck.services import amendments
from clausecheck.store import sqlite as db
from tests.helpers import make_chunk

AMENDMENT_TEXT = (
    "Orion Freight Lines Pvt. Ltd. - Amendment No. 1 to Transportation Services Agreement\n"
    "Agreement No. KML/ORN/2023/004\n"
    "This Amendment No. 1 is signed on 15 March 2024 and is effective from 1 April 2024."
)


def _conn_with_parent(tmp_path, text="Transportation Services Agreement No. KML/ORN/2023/004"):
    conn = db.connect(tmp_path / "a.db")
    db.init_db(conn)
    db.upsert_document(conn, {"doc_id": "orig", "supplier_id": "S-ORION", "doc_type": "contract"})
    db.replace_chunks(
        conn,
        "orig",
        [make_chunk(chunk_id="orig:p1:1", doc_id="orig", supplier_id="S-ORION", text=text)],
    )
    return conn


def test_detects_amendment_number_and_effective_date():
    assert amendments.is_amendment(AMENDMENT_TEXT)
    assert not amendments.is_amendment("Transportation Services Agreement between the Parties")
    assert amendments.agreement_number(AMENDMENT_TEXT) == "KML/ORN/2023/004"
    assert amendments.effective_date(AMENDMENT_TEXT) == "2024-04-01"


def test_links_amendment_to_its_agreement_and_fixes_doc_type(tmp_path):
    conn = _conn_with_parent(tmp_path)
    row = {"doc_id": "amd", "supplier_id": "S-ORION", "doc_type": "contract", "effective_date": ""}
    out = amendments.describe(conn, row, AMENDMENT_TEXT)
    assert (out["doc_type"], out["parent_doc_id"], out["effective_date"]) == (
        "amendment",
        "orig",
        "2024-04-01",
    )


def test_ambiguous_parent_is_left_unlinked(tmp_path):
    conn = _conn_with_parent(tmp_path, text="Some other agreement")
    db.upsert_document(conn, {"doc_id": "other", "supplier_id": "S-ORION", "doc_type": "contract"})
    row = {"doc_id": "amd", "supplier_id": "S-ORION", "doc_type": "contract", "effective_date": ""}
    assert amendments.describe(conn, row, AMENDMENT_TEXT)["parent_doc_id"] == ""


def test_running_headers_and_footers_are_removed():
    pages = [
        f"Acme Agreement No. 7\nClause {i} text here.\nPage {i} of 3\nConfidential draft"
        for i in (1, 2, 3)
    ]
    cleaned = strip_running_lines(pages)
    assert all("Confidential draft" not in p and "Acme Agreement" not in p for p in cleaned)
    assert all(f"Clause {i} text here." in cleaned[i - 1] for i in (1, 2, 3))


def test_single_page_documents_are_untouched():
    assert strip_running_lines(["Only page\nText"]) == ["Only page\nText"]
