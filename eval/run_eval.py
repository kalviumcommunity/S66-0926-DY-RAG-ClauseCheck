"""Run the evaluation set. Always run as a module: `python -m eval.run_eval`."""

import argparse
import datetime as dt
import json
import sys
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

from eval.metrics import evaluate_retrieval
from eval.schema import Question, load_questions

RetrieveFn = Callable[[Question], list[str]]
# Retriever factories: name -> function(supplier_filter) that builds a retrieve function.
RETRIEVERS: dict[str, Callable[[bool], RetrieveFn]] = {}
ABLATION_RETRIEVERS = ["vector", "bm25", "hybrid", "hybrid_rerank"]


@lru_cache(maxsize=1)
def _core():
    """Settings, SQLite connection and BM25 index, built once per run (no API key needed)."""
    from clausecheck.core.config import get_settings
    from clausecheck.store import sqlite as db
    from clausecheck.store.bm25_index import BM25Index

    settings = get_settings()
    conn = db.connect(settings.sqlite_path)
    db.init_db(conn)
    return settings, conn, BM25Index.from_conn(conn)


@lru_cache(maxsize=1)
def _vector_parts():
    """Embedder and vector store, built once per run (needs the embedding provider's key)."""
    from clausecheck.ingest.embedder import Embedder
    from clausecheck.store.vector_store import VectorStore

    settings, conn, _ = _core()
    return Embedder.from_settings(settings, conn), VectorStore.from_settings(settings)


def _supplier(q: Question, supplier_filter: bool) -> str | None:
    return q.supplier_id if supplier_filter else None


def _vector(supplier_filter: bool = True) -> RetrieveFn:
    """Semantic search over the Chroma collection for the configured embedding model."""
    from clausecheck.rag.vector_retriever import VectorRetriever

    retriever = VectorRetriever(*_vector_parts())
    return lambda q: [
        h.chunk_id for h in retriever.retrieve(q.question, _supplier(q, supplier_filter), k=20)
    ]


def _bm25(supplier_filter: bool = True) -> RetrieveFn:
    """Keyword search only."""
    settings, _, bm25 = _core()
    return lambda q: [
        h.chunk_id for h in bm25.search(q.question, settings.bm25_k, _supplier(q, supplier_filter))
    ]


def _hybrid_retriever():
    from clausecheck.rag.hybrid_retriever import HybridRetriever
    from clausecheck.rag.vector_retriever import VectorRetriever

    settings, conn, bm25 = _core()
    return settings, HybridRetriever(
        VectorRetriever(*_vector_parts()),
        bm25,
        conn,
        vector_k=settings.vector_k,
        bm25_k=settings.bm25_k,
        rrf_k=settings.rrf_k,
    )


def _hybrid(supplier_filter: bool = True) -> RetrieveFn:
    """Vector and BM25 fused with RRF, with amendment expansion."""
    settings, retriever = _hybrid_retriever()
    return lambda q: [
        h.chunk_id
        for h in retriever.retrieve(
            q.question, _supplier(q, supplier_filter), k=settings.rerank_candidates
        )
    ]


def _hybrid_rerank(supplier_filter: bool = True) -> RetrieveFn:
    """Hybrid candidates re-ranked by the cross-encoder."""
    from clausecheck.rag.reranker import Reranker

    settings, retriever = _hybrid_retriever()
    reranker = Reranker(model_name=settings.rerank_model)

    def retrieve(q: Question) -> list[str]:
        hits = retriever.retrieve(
            q.question, _supplier(q, supplier_filter), k=settings.rerank_candidates
        )
        return [h.chunk_id for h in reranker.rerank(q.question, hits, settings.rerank_top_n)]

    return retrieve


RETRIEVERS.update(vector=_vector, bm25=_bm25, hybrid=_hybrid, hybrid_rerank=_hybrid_rerank)


def ablation_table(results: dict[tuple[str, bool], dict]) -> str:
    """Markdown table of retriever x supplier filter, best recall@5 first."""
    rows = sorted(results.items(), key=lambda item: -item[1]["recall_at_k"])
    lines = [
        "| retriever | supplier filter | recall@5 | MRR |",
        "|---|---|---|---|",
    ]
    for (name, filter_on), r in rows:
        lines.append(
            f"| {name} | {'on' if filter_on else 'off'} | {r['recall_at_k']:.3f} | {r['mrr']:.3f} |"
        )
    return "\n".join(lines)


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


def _run_ablation(args) -> int:
    questions = load_questions(args.questions, split=args.split)
    results: dict[tuple[str, bool], dict] = {}
    for name in ABLATION_RETRIEVERS:
        for filter_on in (True, False):
            print(
                f"running {name}, supplier filter {'on' if filter_on else 'off'}", file=sys.stderr
            )
            results[(name, filter_on)] = evaluate_retrieval(
                questions, RETRIEVERS[name](filter_on), k=args.k
            )
    table = ablation_table(results)
    payload = {
        "k": args.k,
        "n": next(iter(results.values()))["n"],
        "rows": {f"{n}|{'on' if f else 'off'}": r for (n, f), r in results.items()},
    }
    path = write_results(payload, "ablation", args.split, args.out)
    path.with_suffix(".md").write_text(table + "\n", encoding="utf-8")
    print(table)
    print(f"-> {path} and {path.with_suffix('.md')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run one evaluation stage and write its results; return a non-zero code if blocked."""
    parser = argparse.ArgumentParser(prog="python -m eval.run_eval", description=__doc__)
    parser.add_argument("--split", choices=["tune", "heldout"], default="tune")
    parser.add_argument("--stage", choices=["retrieval", "answer", "e2e"], default="retrieval")
    parser.add_argument("--retriever", help="name of a registered retriever")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--questions", type=Path, default=Path("eval/questions.jsonl"))
    parser.add_argument("--out", type=Path, default=Path("eval/results"))
    parser.add_argument("--supplier-filter", choices=["on", "off"], default="on")
    parser.add_argument("--ablation", action="store_true", help="4 retrievers x filter on/off")
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
    if args.ablation:
        return _run_ablation(args)
    if args.retriever not in RETRIEVERS:
        names = ", ".join(sorted(RETRIEVERS)) or "(none registered yet)"
        print(f"unknown or missing --retriever; available: {names}", file=sys.stderr)
        return 3

    questions = load_questions(args.questions, split=args.split)
    filter_on = args.supplier_filter == "on"
    result = evaluate_retrieval(questions, RETRIEVERS[args.retriever](filter_on), k=args.k)
    result["retriever"] = args.retriever
    result["supplier_filter"] = filter_on
    path = write_results(result, args.stage, args.split, args.out)
    print(
        f"{args.retriever} on {args.split}: n={result['n']} "
        f"recall@{args.k}={result['recall_at_k']:.3f} mrr={result['mrr']:.3f} -> {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
