"""Command line: `python -m clausecheck.ingest` ingests the manifest into SQLite."""

import argparse
from collections import Counter
from pathlib import Path

from clausecheck.services.ingestion_service import run_manifest
from clausecheck.store import sqlite as db


def _default_db() -> Path:
    try:
        from clausecheck.core.config import get_settings

        return get_settings().sqlite_path
    except Exception:  # keys may be missing; the path has a fixed default
        return Path("index/clausecheck.db")


def main(argv: list[str] | None = None) -> int:
    """Ingest the manifest, print a summary, and return 1 only if every document failed."""
    parser = argparse.ArgumentParser(prog="python -m clausecheck.ingest", description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("data/manifest.csv"))
    parser.add_argument("--suppliers", type=Path, default=Path("data/suppliers.csv"))
    parser.add_argument("--db", type=Path, default=None, help="default: SQLITE_PATH setting")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument(
        "--no-embed", action="store_true", help="skip embeddings and the vector store"
    )
    parser.add_argument("--only-supplier", metavar="ID")
    args = parser.parse_args(argv)

    db_path = args.db or _default_db()
    # A dry run must not create the database file.
    conn = db.connect(":memory:" if args.dry_run and not db_path.exists() else db_path)
    db.init_db(conn)
    suppliers = args.suppliers if args.suppliers.exists() else None

    embedder = store = None
    if not (args.no_embed or args.dry_run):
        from clausecheck.core.config import get_settings
        from clausecheck.ingest.embedder import Embedder
        from clausecheck.store.vector_store import VectorStore

        settings = get_settings()
        embedder = Embedder.from_settings(settings, conn)
        store = VectorStore.from_settings(settings)
        if args.rebuild:
            store.reset()

    results = run_manifest(
        args.manifest,
        conn,
        suppliers_path=suppliers,
        root=args.root,
        rebuild=args.rebuild,
        only_supplier=args.only_supplier,
        dry_run=args.dry_run,
        embedder=embedder,
        vector_store=store,
    )

    by_status = Counter(r.status for r in results)
    print(f"{'status':<12}{'documents':>10}")
    for status, n in sorted(by_status.items()):
        print(f"{status:<12}{n:>10}")
    print(f"total chunks: {sum(r.n_chunks for r in results)}")
    if not args.dry_run:
        from clausecheck.store.bm25_index import BM25Index

        # built only to check it works; the keyword index stays in memory at query time
        print(f"bm25 index: {BM25Index.from_conn(conn).size()} chunks")
    if store is not None:
        print(f"vectors in {store.collection_name}: {store.count()}")
    failures = [r for r in results if r.status == "failed"]
    if failures:
        print("failures:")
        for r in failures:
            print(f"  {r.doc_id}: {r.error}")
    return 1 if results and len(failures) == len(results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
