import pytest

from clausecheck.ingest.embedder import Embedder
from clausecheck.store import sqlite as db


class FakeEmbed:
    def __init__(self, dim=4):
        self.dim = dim
        self.batches = []

    def __call__(self, texts):
        self.batches.append(list(texts))
        return [[float(len(t))] + [0.0] * (self.dim - 1) for t in texts]


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "e.db")
    db.init_db(c)
    return c


def test_batches_by_size(conn):
    fn = FakeEmbed()
    vectors = Embedder(fn, conn, "m1", batch_size=10).embed_texts([f"t{i}" for i in range(25)])
    assert len(vectors) == 25
    assert [len(b) for b in fn.batches] == [10, 10, 5]


def test_cache_hit_skips_api(conn):
    fn = FakeEmbed()
    e = Embedder(fn, conn, "m1", batch_size=10)
    first = e.embed_texts(["a", "bb"])
    calls = len(fn.batches)
    assert e.embed_texts(["a", "bb"]) == first
    assert len(fn.batches) == calls


def test_only_misses_are_sent_and_order_kept(conn):
    fn = FakeEmbed()
    e = Embedder(fn, conn, "m1")
    e.embed_texts(["a"])
    out = e.embed_texts(["ccc", "a", "bb"])
    assert fn.batches[-1] == ["ccc", "bb"]
    assert [v[0] for v in out] == [3.0, 1.0, 2.0]


def test_model_is_part_of_cache_key(conn):
    fn = FakeEmbed()
    Embedder(fn, conn, "m1").embed_texts(["a"])
    Embedder(fn, conn, "m2").embed_texts(["a"])
    assert len(fn.batches) == 2


def test_empty_input_no_call(conn):
    fn = FakeEmbed()
    assert Embedder(fn, conn, "m1").embed_texts([]) == []
    assert fn.batches == []


def test_embed_query(conn):
    assert len(Embedder(FakeEmbed(dim=6), conn, "m1").embed_query("hello")) == 6
