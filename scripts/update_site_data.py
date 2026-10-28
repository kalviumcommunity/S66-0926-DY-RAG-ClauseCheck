#!/usr/bin/env python
"""Write site/results.json from the query log and the held-out eval, for the landing page.

The landing page shows only what is in this file, so it can never show a figure that was not
measured. Run it after `python -m eval.run_eval` or whenever the log has grown:

    python scripts/update_site_data.py [--days 7]
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from clausecheck.core.config import get_settings  # noqa: E402
from clausecheck.services.insights_service import InsightsService  # noqa: E402
from clausecheck.store import sqlite as db  # noqa: E402

OUT = ROOT / "site" / "results.json"


def build(days: int | None, results_dir: Path = ROOT / "eval" / "results") -> dict:
    """The landing page's numbers: the service report's scorecard, with its date and basis."""
    conn = db.connect(get_settings().sqlite_path)
    report = InsightsService(conn).report(days=days, results_dir=results_dir)
    return {
        "generated_at": report["generated_at"],
        "window": report["window"]["label"],
        "questions": report["questions"],
        "index": report["index"],
        "headline": report["headline"],
        "scorecard": report["scorecard"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=7, help="window in days (default 7)")
    args = parser.parse_args()
    data = build(args.days)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(data, indent=2) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {data['questions']} questions, {data['window']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
