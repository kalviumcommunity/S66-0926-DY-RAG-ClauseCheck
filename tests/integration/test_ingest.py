from clausecheck.ingest.__main__ import main
from clausecheck.services.ingestion_service import run_manifest
from clausecheck.store import sqlite as db
from tests.fixtures.make_fixtures import MANIFEST_ROWS
from tests.helpers import write_manifest


def _setup(tmp_path, fixture_paths):
    manifest, suppliers = write_manifest(tmp_path, fixture_paths, MANIFEST_ROWS)
    conn = db.connect(tmp_path / "ingest.db")
    db.init_db(conn)
    return manifest, suppliers, conn


def test_first_run_ingests_everything(tmp_path, fixture_paths):
    manifest, suppliers, conn = _setup(tmp_path, fixture_paths)
    results = run_manifest(manifest, conn, suppliers_path=suppliers)
    assert {r.status for r in results} == {"ingested"}, [(r.doc_id, r.error) for r in results]
    counts = db.counts(conn)
    assert counts["documents"] == 4 and counts["chunks"] > 4 and counts["suppliers"] == 1
    bad = conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE supplier_id IS NULL OR page IS NULL OR doc_type IS NULL"
    ).fetchone()[0]
    assert bad == 0


def test_amendment_linked_to_parent(tmp_path, fixture_paths):
    manifest, suppliers, conn = _setup(tmp_path, fixture_paths)
    run_manifest(manifest, conn, suppliers_path=suppliers)
    assert db.get_document(conn, "edgar-acme02")["parent_doc_id"] == "cuad-acme01"
    assert all(c.parent_doc_id == "cuad-acme01" for c in db.get_chunks(conn, doc_id="edgar-acme02"))


def test_second_run_skips_unchanged_and_rebuild_reingests(tmp_path, fixture_paths):
    manifest, suppliers, conn = _setup(tmp_path, fixture_paths)
    run_manifest(manifest, conn, suppliers_path=suppliers)
    assert {r.status for r in run_manifest(manifest, conn)} == {"unchanged"}
    assert {r.status for r in run_manifest(manifest, conn, rebuild=True)} == {"ingested"}


def test_dry_run_writes_nothing(tmp_path, fixture_paths):
    manifest, suppliers, conn = _setup(tmp_path, fixture_paths)
    results = run_manifest(manifest, conn, suppliers_path=suppliers, dry_run=True)
    assert {r.status for r in results} == {"dry-run"} and all(r.n_chunks > 0 for r in results)
    assert db.counts(conn) == {"documents": 0, "chunks": 0, "suppliers": 0}


def test_missing_file_fails_without_stopping_run(tmp_path, fixture_paths):
    paths = dict(fixture_paths, txt=tmp_path / "does_not_exist.txt")
    manifest, suppliers = write_manifest(tmp_path, paths, MANIFEST_ROWS)
    conn = db.connect(tmp_path / "f.db")
    db.init_db(conn)
    results = {r.doc_id: r for r in run_manifest(manifest, conn, suppliers_path=suppliers)}
    assert results["synthetic-acme04"].status == "failed" and results["synthetic-acme04"].error
    assert results["cuad-acme01"].status == "ingested"


def test_only_supplier_filter(tmp_path, fixture_paths):
    manifest, suppliers, conn = _setup(tmp_path, fixture_paths)
    assert run_manifest(manifest, conn, only_supplier="S-NOBODY") == []


def test_cli_returns_zero_and_prints_summary(tmp_path, fixture_paths, capsys):
    manifest, suppliers, _ = _setup(tmp_path, fixture_paths)
    code = main(["--manifest", str(manifest), "--suppliers", str(suppliers), "--db", str(tmp_path / "cli.db")])
    assert code == 0
    assert "ingested" in capsys.readouterr().out
