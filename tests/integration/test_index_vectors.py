import hashlib

from clausecheck.ingest.embedder import Embedder
from clausecheck.services.ingestion_service import run_manifest
from clausecheck.store import sqlite as db
from clausecheck.store.vector_store import VectorStore
from tests.fixtures.make_fixtures import MANIFEST_ROWS
from tests.helpers import write_manifest


class HashEmbed:
    calls = 0

    def __call__(self, texts):
        HashEmbed.calls += 1
        return [[b / 255 for b in hashlib.sha256(t.encode()).digest()[:8]] for t in texts]


def test_index_writes_one_vector_per_chunk_and_reuses_cache(tmp_path, fixture_paths):
    manifest, suppliers = write_manifest(tmp_path, fixture_paths, MANIFEST_ROWS)
    conn = db.connect(tmp_path / "v.db")
    db.init_db(conn)
    embedder = Embedder(HashEmbed(), conn, "hash-8", batch_size=16)
    store = VectorStore(tmp_path / "chroma", "it")

    run_manifest(manifest, conn, suppliers_path=suppliers, embedder=embedder, vector_store=store)
    assert store.count() == db.counts(conn)["chunks"] > 0

    calls = HashEmbed.calls
    run_manifest(manifest, conn, rebuild=True, embedder=embedder, vector_store=store)
    assert store.count() == db.counts(conn)["chunks"]
    assert HashEmbed.calls == calls  # every text served from the cache
