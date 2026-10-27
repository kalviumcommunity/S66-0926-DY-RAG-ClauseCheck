from clausecheck.store import sqlite as db
from clausecheck.store.query_log import QueryLog


def test_log_and_recent(tmp_path):
    log = QueryLog(db.connect(tmp_path / "q.db"))
    log.log({"query_id": "q1", "created_at": "2026-11-01T10:00:00", "question": "a", "outcome": "answered",
             "chunk_ids": ["c1", "c2"], "scores": [0.9, 0.4], "cached": False})
    log.log({"query_id": "q2", "created_at": "2026-11-01T10:01:00", "question": "b", "outcome": "refused"})
    rows = log.recent(10)
    assert [r["query_id"] for r in rows] == ["q2", "q1"]
    assert rows[1]["chunk_ids"] == ["c1", "c2"] and rows[0]["chunk_ids"] is None
