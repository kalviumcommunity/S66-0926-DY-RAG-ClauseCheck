#!/usr/bin/env python
"""Validate CUAD_v1.json and print the numbers quoted in docs/data/data-validation-report.md.

Usage: python scripts/validate_cuad.py [path/to/CUAD_v1.json]

With no argument it reads the file from the cached `CUAD_v1.zip` that `fetch_sources.py`
downloads. The JSON report goes to stdout; the exit code is 1 if any label offset does not
point to its labelled text (this runs in CI).
"""

import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

USED_CATEGORIES = [
    "Renewal Term",
    "Notice Period To Terminate Renewal",
    "Expiration Date",
    "Cap On Liability",
    "Uncapped Liability",
    "Termination For Convenience",
    "Warranty Duration",
    "Liquidated Damages",
    "Price Restrictions",
    "Most Favored Nation",
    "Minimum Commitment",
    "Volume Restriction",
    "Insurance",
    "Audit Rights",
    "Parties",
    "Effective Date",
    "Agreement Date",
    "Governing Law",
]
OLD_TITLE = re.compile(r"^.+_\d{2}_\d{2}_\d{4}-EX-")
NEW_TITLE = re.compile(r"^.+_\d{8}_[^_]+_EX-")
REDACTION = re.compile(r"\[\*+\]|\*\*\*|confidential treatment", re.I)


def load(path: Path | None) -> dict:
    """Read CUAD_v1.json from a path or from the cached zip."""
    if path is not None:
        return json.loads(path.read_text(encoding="utf-8"))
    cache = ROOT / "data" / "raw" / ".cache" / "CUAD_v1.zip"
    if not cache.exists():
        sys.exit("no path given and data/raw/.cache/CUAD_v1.zip is missing: run fetch_sources.py")
    with zipfile.ZipFile(cache) as z:
        return json.loads(z.read("CUAD_v1/CUAD_v1.json"))


def validate(data: dict) -> dict:
    """Return the validation numbers for a parsed CUAD_v1.json."""
    contracts = data["data"]
    categories: set[str] = set()
    spans = exact = redacted_spans = 0
    bad: list[str] = []
    for contract in contracts:
        paragraph = contract["paragraphs"][0]
        context = paragraph["context"]
        for qa in paragraph["qas"]:
            categories.add(qa["id"].split("__", 1)[1])
            for answer in qa["answers"]:
                spans += 1
                start, text = answer["answer_start"], answer["text"]
                if context[start : start + len(text)] == text:
                    exact += 1
                else:
                    bad.append(qa["id"])
                redacted_spans += bool(REDACTION.search(text))
    titles = [c["title"] for c in contracts]
    return {
        "contracts": len(contracts),
        "categories": len(categories),
        "spans": spans,
        "spans_exact": exact,
        "spans_with_redaction_marker": redacted_spans,
        "used_categories_present": sum(c in categories for c in USED_CATEGORIES),
        "used_categories_expected": len(USED_CATEGORIES),
        "categories_named_payment_invoice_net": sorted(
            c for c in categories if re.search(r"payment|invoice|\bnet\b", c, re.I)
        ),
        "titles_old_pattern": sum(bool(OLD_TITLE.match(t)) for t in titles),
        "titles_new_pattern": sum(bool(NEW_TITLE.match(t)) for t in titles),
        "mismatched_offsets": bad[:20],
    }


def main(argv: list[str] | None = None) -> int:
    """Command line entry point."""
    args = sys.argv[1:] if argv is None else argv
    report = validate(load(Path(args[0]) if args else None))
    print(json.dumps(report, indent=2))
    print(
        f"{report['contracts']} contracts, {report['categories']} categories, "
        f"{report['spans_exact']:,}/{report['spans']:,} spans exact, "
        f"{report['used_categories_present']}/{report['used_categories_expected']} "
        "categories present",
        file=sys.stderr,
    )
    return 0 if report["spans_exact"] == report["spans"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
