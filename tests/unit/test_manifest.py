"""The committed manifest is internally consistent."""
import csv
import hashlib
import re
from pathlib import Path

import pytest

from clausecheck.core import schema

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "data" / "manifest.csv"
SUPPLIERS = ROOT / "data" / "suppliers.csv"


def _read(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def rows():
    assert MANIFEST.exists(), "data/manifest.csv must be committed"
    return _read(MANIFEST)


@pytest.fixture(scope="module")
def suppliers():
    assert SUPPLIERS.exists(), "data/suppliers.csv must be committed"
    return _read(SUPPLIERS)


def test_columns(rows):
    with MANIFEST.open(encoding="utf-8") as f:
        header = f.readline().strip().split(",")
    assert header == schema.MANIFEST_COLUMNS


def test_not_empty(rows):
    assert len(rows) > 0


def test_doc_ids_unique(rows):
    ids = [r["doc_id"] for r in rows]
    assert len(ids) == len(set(ids))


def test_allowed_values(rows):
    for r in rows:
        assert r["source"] in schema.SOURCES, r
        assert r["doc_type"] in schema.DOC_TYPES, r
        assert r["format"] in schema.FORMATS, r
        assert r["is_synthetic"] in {"true", "false"}, r
        assert (r["source"] == "synthetic") == (r["is_synthetic"] == "true"), r


def test_every_row_has_licence_and_checksum(rows):
    for r in rows:
        assert r["licence"].strip(), f"no licence: {r['doc_id']}"
        assert re.fullmatch(r"[0-9a-f]{64}", r["sha256"]), r["doc_id"]


def test_dates_are_iso_or_empty(rows):
    for r in rows:
        assert r["effective_date"] == "" or re.fullmatch(r"\d{4}-\d{2}-\d{2}", r["effective_date"]), r


def test_suppliers_known(rows, suppliers):
    known = {s["supplier_id"] for s in suppliers}
    unknown = {r["supplier_id"] for r in rows} - known
    assert not unknown, f"suppliers missing from suppliers.csv: {unknown}"


def test_parents_exist_and_match_supplier(rows):
    by_id = {r["doc_id"]: r for r in rows}
    for r in rows:
        if r["doc_type"] in schema.AMENDMENT_TYPES:
            assert r["parent_doc_id"], f"amendment without parent: {r['doc_id']}"
        if r["parent_doc_id"]:
            parent = by_id.get(r["parent_doc_id"])
            assert parent is not None, f"unknown parent for {r['doc_id']}"
            assert parent["supplier_id"] == r["supplier_id"], r["doc_id"]


def test_supplier_ids_and_aliases_unique(suppliers):
    ids = [s["supplier_id"] for s in suppliers]
    assert len(ids) == len(set(ids))
    seen = {}
    for s in suppliers:
        names = [s["display_name"]] + [a for a in s["aliases"].split("|") if a]
        for name in names:
            key = name.strip().lower()
            assert key not in seen or seen[key] == s["supplier_id"], f"alias '{name}' used twice"
            seen[key] = s["supplier_id"]


def test_files_exist_and_checksums_match(rows):
    if not (ROOT / "data" / "raw").exists() or not any((ROOT / "data" / "raw").iterdir()):
        pytest.skip("raw corpus not fetched on this machine")
    missing, wrong = [], []
    for r in rows:
        p = ROOT / r["path"]
        if not p.exists():
            missing.append(r["path"])
            continue
        if hashlib.sha256(p.read_bytes()).hexdigest() != r["sha256"]:
            wrong.append(r["path"])
    assert not missing, f"missing files: {missing[:10]}"
    assert not wrong, f"checksum mismatch: {wrong[:10]}"


@pytest.mark.targets
def test_corpus_targets(rows, suppliers):
    """May fail only if the shortfall is recorded in docs/data/data-sourcing.md."""
    count = lambda types: sum(r["doc_type"] in types for r in rows)
    actual = {
        "contract": count({"contract"}),
        "amendment": count({"amendment"}),
        "price_schedule": count({"price_schedule"}),
        "compliance": count({"dpa", "sla", "certificate"}),
        "suppliers": len({r["supplier_id"] for r in rows}),
    }
    for key, (lo, hi) in schema.TARGETS.items():
        assert lo <= actual[key] <= hi, f"{key}: {actual[key]} not in [{lo}, {hi}]"
    assert {r["format"] for r in rows} >= {"pdf", "html", "docx", "txt"}
