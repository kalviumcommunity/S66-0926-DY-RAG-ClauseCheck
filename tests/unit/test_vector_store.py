from clausecheck.store.vector_store import VectorStore, collection_name
from tests.helpers import make_chunk


def _store(tmp_path):
    return VectorStore(tmp_path / "chroma", "test_chunks")


def _chunks():
    return [
        make_chunk(chunk_id="a:p1:1", doc_id="a", supplier_id="S-ACME", clause_no="1"),
        make_chunk(chunk_id="a:p1:2", doc_id="a", supplier_id="S-ACME", clause_no="2"),
        make_chunk(chunk_id="b:p1:1", doc_id="b", supplier_id="S-BETA", clause_no="1"),
    ]


VECTORS = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]


def test_collection_name_is_safe():
    name = collection_name("v1", "sentence-transformers/all-MiniLM-L6-v2")
    assert name.startswith("chunks_v1_") and len(name) <= 63
    assert all(ch.isalnum() or ch in "_-" for ch in name)


def test_search_returns_nearest_first(tmp_path):
    store = _store(tmp_path)
    store.upsert(_chunks(), VECTORS)
    hits = store.search([0.9, 0.1, 0.0], k=2)
    assert [h.chunk_id for h in hits] == ["a:p1:1", "a:p1:2"]
    assert hits[0].score > hits[1].score
    assert hits[0].source == "vector" and hits[0].text


def test_supplier_filter(tmp_path):
    store = _store(tmp_path)
    store.upsert(_chunks(), VECTORS)
    hits = store.search([0.0, 0.0, 1.0], k=3, supplier_id="S-ACME")
    assert {h.metadata["supplier_id"] for h in hits} == {"S-ACME"}


def test_none_metadata_roundtrip(tmp_path):
    store = _store(tmp_path)
    store.upsert(_chunks(), VECTORS)
    hit = store.search([1.0, 0.0, 0.0], k=1)[0]
    assert hit.metadata["parent_doc_id"] is None
    assert hit.metadata["has_redaction"] is False


def test_upsert_is_idempotent_and_delete_doc(tmp_path):
    store = _store(tmp_path)
    store.upsert(_chunks(), VECTORS)
    store.upsert(_chunks(), VECTORS)
    assert store.count() == 3
    store.delete_doc("a")
    assert store.count() == 1
