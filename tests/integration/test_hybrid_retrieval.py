from clausecheck.rag.hybrid_retriever import HybridRetriever, expand_amendments
from clausecheck.rag.types import SearchHit
from clausecheck.store import sqlite as db
from clausecheck.store.bm25_index import BM25Index
from tests.helpers import make_chunk

ORIG = make_chunk(chunk_id="orig:p1:2_1", doc_id="orig", clause_no="2.1",
                  text="2.1 Payment is due Net 45 days from the invoice date.")
TERM = make_chunk(chunk_id="orig:p1:3_1", doc_id="orig", clause_no="3.1", text="3.1 The term is two years.")
AMEND = make_chunk(chunk_id="amd:p1:1", doc_id="amd", clause_no="1", doc_type="amendment", parent_doc_id="orig",
                   text="1. Section 2.1 of the Agreement is amended to read: Payment is due Net 30 days.")


def _conn(tmp_path):
    conn = db.connect(tmp_path / "h.db")
    db.init_db(conn)
    db.upsert_document(conn, {"doc_id": "orig", "supplier_id": "S-ACME", "doc_type": "contract"})
    db.upsert_document(conn, {"doc_id": "amd", "supplier_id": "S-ACME", "doc_type": "amendment",
                              "parent_doc_id": "orig"})
    db.replace_chunks(conn, "orig", [ORIG, TERM])
    db.replace_chunks(conn, "amd", [AMEND])
    return conn


def _hit(c):
    return SearchHit(c.chunk_id, 1.0, c.text, {"doc_id": c.doc_id, "clause_no": c.clause_no,
                                                "supplier_id": c.supplier_id})


def test_amendment_hit_pulls_in_original_clause(tmp_path):
    out = expand_amendments([_hit(AMEND)], _conn(tmp_path))
    assert [h.chunk_id for h in out] == ["amd:p1:1", "orig:p1:2_1"]
    assert out[1].expanded and out[1].source == "expansion"


def test_original_hit_pulls_in_amendment(tmp_path):
    out = expand_amendments([_hit(ORIG)], _conn(tmp_path))
    assert "amd:p1:1" in [h.chunk_id for h in out]
    assert "orig:p1:3_1" not in [h.chunk_id for h in out]


class FakeVector:
    def __init__(self, ids):
        self.ids = ids

    def retrieve(self, query, supplier_id=None, k=20):
        return [_hit(c) for c in [ORIG, TERM, AMEND] if c.chunk_id in self.ids][:k]


def test_hybrid_fuses_both_lists(tmp_path):
    conn = _conn(tmp_path)
    retriever = HybridRetriever(FakeVector(["orig:p1:3_1"]), BM25Index.from_conn(conn), conn, expand=False)
    ids = [h.chunk_id for h in retriever.retrieve("net 45 payment", supplier_id="S-ACME", k=3)]
    assert "orig:p1:2_1" in ids and "orig:p1:3_1" in ids
    assert all(h.source == "hybrid" for h in retriever.retrieve("net 45", k=3))


def test_hybrid_with_expansion_returns_amendment_with_original(tmp_path):
    conn = _conn(tmp_path)
    retriever = HybridRetriever(FakeVector([]), BM25Index.from_conn(conn), conn, expand=True)
    ids = [h.chunk_id for h in retriever.retrieve("Net 30 amended", k=1)]
    assert ids[0] == "amd:p1:1" and "orig:p1:2_1" in ids
