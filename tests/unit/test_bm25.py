from clausecheck.store.bm25_index import BM25Index, tokenize
from tests.helpers import make_chunk


def test_tokenize_keeps_exact_tokens():
    assert tokenize("Payment is due Net 45 days.") == ["payment", "is", "due", "net", "45", "days"]
    assert tokenize("$1,250.00 and 7.2% for A-114, total 1,250.") == [
        "$1,250.00", "and", "7.2%", "for", "a-114", "total", "1,250"]


def _index():
    return BM25Index([
        make_chunk(chunk_id="c1", text="Payment is due Net 45 days from invoice.", supplier_id="S-ACME"),
        make_chunk(chunk_id="c2", text="The initial term is two years.", supplier_id="S-ACME"),
        make_chunk(chunk_id="c3", text="Unit price for A-114 is $1,250.00.", supplier_id="S-ACME"),
        make_chunk(chunk_id="c4", text="Payment is due Net 30 days.", supplier_id="S-BETA"),
        make_chunk(chunk_id="c5", text="Liability is capped at fees paid.", supplier_id="S-BETA"),
    ])


def test_literal_match_ranks_first():
    hits = _index().search("net 45", k=3)
    assert hits[0].chunk_id == "c1" and hits[0].source == "bm25"


def test_exact_value_tokens():
    assert _index().search("A-114 price", k=1)[0].chunk_id == "c3"


def test_supplier_index_excludes_others():
    hits = _index().search("payment net days", k=5, supplier_id="S-BETA")
    assert {h.metadata["supplier_id"] for h in hits} == {"S-BETA"}
    assert _index().search("payment", supplier_id="S-NONE") == []


def test_chunks_without_query_tokens_dropped():
    assert _index().search("zebra", k=5) == []
