import re

from clausecheck.core.ids import chunk_id, doc_id, query_id


def test_doc_id_is_deterministic_and_safe():
    a = doc_id("cuad", "LohaCompanyltd_20191209_F-1_EX-10.16 Supply Agreement")
    assert a == doc_id("cuad", "LohaCompanyltd_20191209_F-1_EX-10.16 Supply Agreement")
    assert a.startswith("cuad-")
    assert re.fullmatch(r"[a-z0-9-]+", a)
    assert a != doc_id("cuad", "Another contract")


def test_chunk_id_format():
    assert chunk_id("cuad-abc", 3, "4.2") == "cuad-abc:p3:4_2"
    assert chunk_id("cuad-abc", 1, "w0") == "cuad-abc:p1:w0"


def test_query_id_unique_hex():
    ids = {query_id() for _ in range(100)}
    assert len(ids) == 100
    assert all(re.fullmatch(r"[0-9a-f]{32}", i) for i in ids)
