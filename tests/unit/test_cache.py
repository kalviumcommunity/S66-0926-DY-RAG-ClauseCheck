from clausecheck.store import sqlite as db
from clausecheck.store.cache import AnswerCache, make_key, normalise


def test_normalise_and_key():
    assert normalise("  What are the TERMS?  ") == "what are the terms"
    k = make_key("Terms?", "S-ACME", "v1", "v1")
    assert k == make_key("terms", "S-ACME", "v1", "v1")
    assert k != make_key("terms", "S-ACME", "v2", "v1")
    assert k != make_key("terms", "S-ACME", "v1", "v2")
    assert k != make_key("terms", "S-BETA", "v1", "v1")


def test_get_set_and_expiry(tmp_path):
    conn = db.connect(tmp_path / "c.db")
    now = [1000.0]
    cache = AnswerCache(conn, ttl_seconds=60, clock=lambda: now[0])
    assert cache.get("k") is None
    cache.set("k", {"answer": "Net 45 [C1]."})
    assert cache.get("k") == {"answer": "Net 45 [C1]."}
    now[0] += 61
    assert cache.get("k") is None
