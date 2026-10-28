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
    parser.add_argument("--sweep", metavar="RANGE", help="threshold sweep range start:stop:step")
    parser.add_argument(
        "--agreement", metavar="PATH", help="hand-graded sample CSV for judge agreement"
    )
    parser.add_argument("--allow-heldout", action="store_true")
    parser.add_argument("--limit", type=int, help="only the first N questions (quick smoke run)")
    args = parser.parse_args(argv)

    if args.agreement:
        return _run_agreement(args)
    if args.split == "heldout" and not args.allow_heldout:
        print(
            "The held-out split is not run before W5 D4. Pass --allow-heldout to run it anyway.",
            file=sys.stderr,
        )
        return 2
    if args.stage == "e2e":
        return _run_e2e(args)
    if args.stage == "answer":
        if args.sweep:
            return _run_sweep(args)
        return _run_answer(args)
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


def _run_answer_for_threshold(settings, questions, retriever, reranker, generator, threshold):
    from clausecheck.rag.citation_validator import validate
    from clausecheck.rag.context_builder import build_context
    from clausecheck.rag.generator import REFUSAL_TEXT
    from clausecheck.rag.relevance_gate import check
    from eval.metrics import (
        answer_correctness,
        citation_accuracy,
        contains_expected,
        false_refusal_rate,
        refusal_accuracy,
    )

    records = []
    refused_flags = []
    should_refuse_flags = []
    cited_ids = []
    gold_ids = []
    grades = []

    for q in questions:
        supplier = _supplier(q, True)
        hits = retriever.retrieve(q.question, supplier, k=settings.rerank_candidates)
        gate = check(hits, threshold, supplier_required=False, supplier_id=supplier)

        if gate.passed:
            ctx = build_context(hits, settings.context_token_budget)
            answer = generator.generate(q.question, ctx.text)
            vr = validate(answer, ctx.marker_map)
            answer = vr.answer
            citations = [c.chunk_id for c in vr.citations]
            outcome = "refused" if answer.strip() == REFUSAL_TEXT else "answered"
            unsupported = vr.unsupported
        else:
            answer = REFUSAL_TEXT
            citations = []
            outcome = "refused"
            unsupported = False

        refused = outcome == "refused"
        refused_flags.append(refused)
        should_refuse_flags.append(q.should_refuse)

        if q.should_refuse:
            grade = "correct" if refused else "wrong"
        else:
            if refused:
                grade = "wrong"
            else:
                grade = "correct" if contains_expected(answer, q.expected_answer) else "wrong"

        needs_judge = q.group == "real" and not q.should_refuse
        records.append(
            {
                "qid": q.qid,
                "group": q.group,
                "question": q.question,
                "outcome": outcome,
                "answer": answer,
                "citations": citations,
                "unsupported": unsupported,
                "grade": grade,
                "needs_judge": needs_judge,
            }
        )
        cited_ids.append(citations)
        gold_ids.append(q.gold_chunk_ids)
        grades.append(grade)

    metrics = {
        "answer_correctness": answer_correctness(grades) if grades else 0.0,
        "citation_accuracy": (
            citation_accuracy(cited_ids, gold_ids)
            if any(c and g for c, g in zip(cited_ids, gold_ids, strict=False))
            else 0.0
        ),
        "refusal_accuracy": refusal_accuracy(refused_flags, should_refuse_flags),
        "false_refusal_rate": false_refusal_rate(refused_flags, should_refuse_flags),
    }
    return records, metrics


def _run_answer(args) -> int:
    from clausecheck.rag.generator import Generator
    from clausecheck.rag.reranker import Reranker

    settings, retriever = _hybrid_retriever()
    reranker = Reranker(model_name=settings.rerank_model)
    generator = Generator.from_settings(settings)
    questions = load_questions(args.questions, split=args.split)

    class _Wrapped:
        def retrieve(self, q, supplier=None, k=None):
            hits = retriever.retrieve(q, supplier, k=k or settings.rerank_candidates)
            return reranker.rerank(q, hits, settings.rerank_top_n)

    wrapped = _Wrapped()
    records, metrics = _run_answer_for_threshold(
        settings, questions, wrapped, reranker, generator, settings.relevance_threshold
    )

    result = {
        "retriever": "hybrid_rerank",
        "threshold": settings.relevance_threshold,
        "metrics": metrics,
        "per_question": records,
    }
    path = write_results(result, "answer", args.split, args.out)
    print(json.dumps(metrics, indent=2))
    print(f"-> {path}")


def _run_sweep(args) -> int:
    from clausecheck.rag.generator import Generator
    from clausecheck.rag.reranker import Reranker

    settings, retriever = _hybrid_retriever()
    reranker = Reranker(model_name=settings.rerank_model)
    generator = Generator.from_settings(settings)
    questions = load_questions(args.questions, split=args.split)

    class _Wrapped:
        def retrieve(self, q, supplier=None, k=None):
            hits = retriever.retrieve(q, supplier, k=k or settings.rerank_candidates)
            return reranker.rerank(q, hits, settings.rerank_top_n)

    wrapped = _Wrapped()

    start, stop, step = (float(x) for x in args.sweep.split(":"))
    thresholds = []
    t = start
    while t <= stop + 1e-9:
        thresholds.append(round(t, 6))
        t += step

    import csv

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    sweep_path = out_dir / f"{dt.datetime.now(dt.UTC).date().isoformat()}_sweep_{args.split}.csv"
    rows = []
    for thr in thresholds:
        _, metrics = _run_answer_for_threshold(
            settings, questions, wrapped, reranker, generator, thr
        )
        row = {
            "threshold": thr,
            "refusal_accuracy": metrics["refusal_accuracy"],
            "false_refusal_rate": metrics["false_refusal_rate"],
            "answer_correctness": metrics["answer_correctness"],
        }
        rows.append(row)
        print(row)

    with sweep_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"-> {sweep_path}")
    return 0


def _run_e2e(args) -> int:
    import csv
    import statistics

    from clausecheck.core.config import get_settings
    from clausecheck.services.query_service import QueryService
    from clausecheck.store import sqlite as db
    from eval.judge import build_judge_client, grade, sample_for_review
    from eval.metrics import (
        answer_correctness,
        citation_accuracy,
        contains_expected,
        false_refusal_rate,
        refusal_accuracy,
    )

    settings = get_settings()
    conn = db.connect(settings.sqlite_path)
    db.init_db(conn)
    svc = QueryService.from_settings(settings, conn)
    judge_client = build_judge_client(settings)
    from clausecheck.prompts.loader import load_prompt

    judge_prompt = load_prompt("judge")

    questions = load_questions(args.questions, split=args.split)[: args.limit]
    records = []
    grades = []
    cited_ids = []
    gold_ids = []
    refused_flags = []
    should_refuse_flags = []
    latencies = []

    for q in questions:
        r = svc.answer(q.question, supplier_filter=q.supplier_id)
        outcome = r.outcome
        answer = r.answer
        citations = [c.chunk_id for c in r.citations]
        if q.should_refuse:
            g = "correct" if outcome == "refused" else "wrong"
        else:
            if q.group == "exact":
                g = "correct" if contains_expected(answer, q.expected_answer) else "wrong"
            else:
                gr = grade(judge_client, judge_prompt, q.question, q.expected_answer, answer)
                g = gr.label
        needs_judge = q.group == "real" and not q.should_refuse
        records.append(
            {
                "qid": q.qid,
                "group": q.group,
                "question": q.question,
                "expected": q.expected_answer,
                "answer": answer,
                "citations": citations,
                "outcome": outcome,
                "grade": g,
                "needs_judge": needs_judge,
                "latency_ms": r.timings.get("total", 0.0),
            }
        )
        grades.append(g)
        cited_ids.append(citations)
        gold_ids.append(q.gold_chunk_ids)
        refused_flags.append(outcome == "refused")
        should_refuse_flags.append(q.should_refuse)
        latencies.append(r.timings.get("total", 0.0))

    metrics = {
        "answer_correctness": answer_correctness(grades) if grades else 0.0,
        "citation_accuracy": (
            citation_accuracy(cited_ids, gold_ids)
            if any(c and g for c, g in zip(cited_ids, gold_ids, strict=False))
            else 0.0
        ),
        "refusal_accuracy": refusal_accuracy(refused_flags, should_refuse_flags),
        "false_refusal_rate": false_refusal_rate(refused_flags, should_refuse_flags),
        "median_latency_ms": statistics.median(latencies) if latencies else 0.0,
    }

    # judge sample csv
    sample = sample_for_review(records, frac=0.1, seed=42)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    date = dt.datetime.now(dt.UTC).date().isoformat()
    sample_path = out_dir / f"{date}_judge_sample_{args.split}.csv"
    with sample_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["qid", "question", "expected", "answer", "judge_label", "human_label"]
        )
        writer.writeheader()
        for row in sample:
            gr = None
            if row.get("group") == "real" and not row.get("should_refuse", False):
                pass
            # find grade label
            judge_label = row.get("grade", "")
            writer.writerow(
                {
                    "qid": row["qid"],
                    "question": row["question"],
                    "expected": row["expected"],
                    "answer": row["answer"],
                    "judge_label": judge_label,
                    "human_label": "",
                }
            )

    result = {"metrics": metrics, "per_question": records}
    path = write_results(result, "e2e", args.split, args.out)
    print(json.dumps(metrics, indent=2))
    print(f"-> {path}")
    print(f"-> {sample_path}")
    return 0


def _run_agreement(args) -> int:
    import csv

    from eval.judge import agreement as compute_agreement

    path = Path(args.agreement)
    judge_labels = []
    human_labels = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            hl = (row.get("human_label") or "").strip()
            if not hl:
                continue
            judge_labels.append(row.get("judge_label", ""))
            human_labels.append(hl)
    if not judge_labels:
        print("no hand-graded rows found", file=sys.stderr)
        return 1
    print(
        "agreement: "
        f"{compute_agreement(judge_labels, human_labels):.3f} "
        f"over {len(judge_labels)} rows"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
