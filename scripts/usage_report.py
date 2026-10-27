#!/usr/bin/env python
"""Summarise the query log: volume, outcomes, latency and cache hits."""

import sqlite3
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from clausecheck.store import sqlite as db  # noqa: E402


def summarize(conn: sqlite3.Connection) -> dict:
    """Totals by outcome, median latency and time to first token, and the cache hit rate."""
    rows = conn.execute("SELECT outcome, latency_ms, ttft_ms, cached FROM query_log").fetchall()
    total = len(rows)

    def median(values):
        values = [v for v in values if v is not None]
        return statistics.median(values) if values else None

    return {
        "total": total,
        "by_outcome": dict(Counter(r["outcome"] for r in rows)),
        "median_latency_ms": median(r["latency_ms"] for r in rows),
        "median_ttft_ms": median(r["ttft_ms"] for r in rows),
        "cache_hit_rate": (sum(1 for r in rows if r["cached"]) / total) if total else 0.0,
    }


def main() -> int:
    """Print the summary for the configured database."""
    from clausecheck.core.config import get_settings

    summary = summarize(db.connect(get_settings().sqlite_path))
    for key, value in summary.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
