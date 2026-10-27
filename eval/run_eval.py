"""Run the evaluation set. Always run as a module: `python -m eval.run_eval`."""

import argparse
import datetime as dt
import json
import sys
from collections.abc import Callable
from pathlib import Path

from eval.metrics import evaluate_retrieval
from eval.schema import Question, load_questions

# Retriever factories, filled in by later PRs: name -> function that builds a retrieve function.
RETRIEVERS: dict[str, Callable[[], Callable[[Question], list[str]]]] = {}


def _vector_retriever() -> Callable[[Question], list[str]]:
    """Semantic search over the Chroma collection for the configured embedding model."""
    from clausecheck.core.config import get_settings
    from clausecheck.ingest.embedder import Embedder
    from clausecheck.rag.vector_retriever import VectorRetriever
    from clausecheck.store import sqlite as db
    from clausecheck.store.vector_store import VectorStore

    settings = get_settings()
    conn = db.connect(settings.sqlite_path)
    db.init_db(conn)
    retriever = VectorRetriever(
        Embedder.from_settings(settings, conn), VectorStore.from_settings(settings)
    )
    return lambda q: [h.chunk_id for h in retriever.retrieve(q.question, q.supplier_id, k=20)]


RETRIEVERS["vector"] = _vector_retriever


def write_results(
    result: dict, stage: str, split: str, out_dir: Path, run_date: str | None = None
) -> Path:
    """Write `{date}_{stage}_{split}.json` with the stage, split and creation time added."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.UTC)
    path = out_dir / f"{run_date or now.date().isoformat()}_{stage}_{split}.json"
    payload = {
        **result,
        "stage": stage,
        "split": split,
        "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    """Run one evaluation stage and write its results; return a non-zero code if blocked."""
    parser = argparse.ArgumentParser(prog="python -m eval.run_eval", description=__doc__)
    parser.add_argument("--split", choices=["tune", "heldout"], default="tune")
    parser.add_argument("--stage", choices=["retrieval", "answer", "e2e"], default="retrieval")
    parser.add_argument("--retriever", help="name of a registered retriever")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--questions", type=Path, default=Path("eval/questions.jsonl"))
    parser.add_argument("--out", type=Path, default=Path("eval/results"))
    parser.add_argument("--allow-heldout", action="store_true")
    args = parser.parse_args(argv)

    if args.split == "heldout" and not args.allow_heldout:
        print(
            "The held-out split is not run before W5 D4. Pass --allow-heldout to run it anyway.",
            file=sys.stderr,
        )
        return 2
    if args.stage != "retrieval":
        print(f"stage '{args.stage}' is available from PR 9/10", file=sys.stderr)
        return 3
    if args.retriever not in RETRIEVERS:
        names = ", ".join(sorted(RETRIEVERS)) or "(none registered yet)"
        print(f"unknown or missing --retriever; available: {names}", file=sys.stderr)
        return 3

    questions = load_questions(args.questions, split=args.split)
    result = evaluate_retrieval(questions, RETRIEVERS[args.retriever](), k=args.k)
    result["retriever"] = args.retriever
    path = write_results(result, args.stage, args.split, args.out)
    print(
        f"{args.retriever} on {args.split}: n={result['n']} "
        f"recall@{args.k}={result['recall_at_k']:.3f} mrr={result['mrr']:.3f} -> {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
