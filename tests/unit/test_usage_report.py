import importlib.util
from pathlib import Path

from clausecheck.store import sqlite as db
from clausecheck.store.query_log import QueryLog

ROOT = Path(__file__).resolve().parents[2]


def test_summarize(tmp_path):
    spec = importlib.util.spec_from_file_location("usage_report", ROOT / "scripts/usage_report.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    conn = db.connect(tmp_path / "u.db")
    log = QueryLog(conn)
    for i, (outcome, ms, cached) in enumerate([("answered", 1000, False), ("refused", 3000, False),
                                               ("answered", 2000, True)]):
        log.log({"query_id": f"q{i}", "created_at": f"2026-11-2{i}T10:00:00", "question": "q",
                 "outcome": outcome, "latency_ms": ms, "ttft_ms": ms / 2, "cached": cached})
    s = mod.summarize(conn)
    assert s["total"] == 3 and s["by_outcome"] == {"answered": 2, "refused": 1}
    assert s["median_latency_ms"] == 2000 and s["cache_hit_rate"] == 1 / 3
