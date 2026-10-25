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
