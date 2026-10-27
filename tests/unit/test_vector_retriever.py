from clausecheck.rag.vector_retriever import VectorRetriever
from clausecheck.store.vector_store import VectorStore
from tests.helpers import make_chunk


class FakeEmbedder:
    def embed_query(self, text):
        return [1.0, 0.0] if "payment" in text.lower() else [0.0, 1.0]


def test_retrieve_uses_query_vector_and_filter(tmp_path):
    store = VectorStore(tmp_path / "chroma", "r")
    store.upsert(
        [make_chunk(chunk_id="pay", supplier_id="S-ACME"), make_chunk(chunk_id="term", supplier_id="S-ACME"),
         make_chunk(chunk_id="other", supplier_id="S-BETA")],
        [[1.0, 0.0], [0.0, 1.0], [1.0, 0.0]],
    )
    hits = VectorRetriever(FakeEmbedder(), store).retrieve("What are the payment terms?", "S-ACME", k=1)
    assert [h.chunk_id for h in hits] == ["pay"]
