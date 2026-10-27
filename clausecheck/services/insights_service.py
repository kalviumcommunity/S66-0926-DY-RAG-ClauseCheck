import sqlite3
from collections import Counter, defaultdict
from pathlib import Path


class InsightsService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def kpis(self) -> dict:
        rows = self.conn.execute("SELECT outcome, latency_ms, ttft_ms FROM query_log").fetchall()
        questions_asked = len(rows)
        answered = sum(1 for r in rows if r["outcome"] == "answered")
        refused = sum(1 for r in rows if r["outcome"] == "refused")
        denom = answered + refused
        answer_rate = answered / denom if denom else 0.0
        checked_times = [r["latency_ms"] for r in rows if r["latency_ms"] is not None]
        ttfts = [r["ttft_ms"] for r in rows if r["ttft_ms"] is not None]
        median_checked = _median(checked_times)
        median_ttft = _median(ttfts)
        # citation accuracy from newest e2e result file
        citation_accuracy = None
        try:
            files = sorted(Path("eval/results").glob("*_e2e_*.json"))
            if files:
                import json as _json

                data = _json.loads(files[-1].read_text())
                citation_accuracy = (data.get("metrics") or {}).get("citation_accuracy")
        except Exception:
            citation_accuracy = None
        return {
            "questions_asked": questions_asked,
            "answer_rate": answer_rate,
            "median_time_to_checked_answer_ms": median_checked,
            "median_ttft_ms": median_ttft,
            "citation_accuracy": citation_accuracy,
        }

    def charts(self, days: int = 14) -> dict:
        # outcomes by day
        rows = self.conn.execute("SELECT created_at, outcome FROM query_log").fetchall()
        outcomes_by_day: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        latency_by_day: dict[str, list[float]] = defaultdict(list)
        for r in rows:
            day = (r["created_at"] or "")[:10]
            outcomes_by_day[day][r["outcome"]] += 1
            # latency not per-day in query_log? use latency_ms
        # latency by day from query_log
        for r in self.conn.execute("SELECT created_at, latency_ms FROM query_log").fetchall():
            day = (r["created_at"] or "")[:10]
            if r["latency_ms"] is not None:
                latency_by_day[day].append(r["latency_ms"])

        outcomes_list = [{"day": d, "counts": dict(c)} for d, c in sorted(outcomes_by_day.items())]
        latency_list = [
            {"day": d, "median_ms": _median(v)} for d, v in sorted(latency_by_day.items())
        ]

        # questions by topic
        topic_map = {
            "payment": "payment",
            "term": "term/renewal",
            "renewal": "term/renewal",
            "liability": "liability",
            "termination": "termination",
            "price": "price",
            "certificate": "certificate",
        }
        topic_counts: Counter = Counter()
        for r in self.conn.execute("SELECT question FROM query_log").fetchall():
            q = (r["question"] or "").lower()
            topic = "other"
            for kw, t in topic_map.items():
                if kw in q:
                    topic = t
                    break
            topic_counts[topic] += 1
        questions_by_topic = [{"topic": t, "count": c} for t, c in topic_counts.items()]

        # documents by source
        src_counts = Counter(
            r["source"] for r in self.conn.execute("SELECT source FROM documents").fetchall()
        )
        documents_by_source = [{"source": s, "count": c} for s, c in src_counts.items()]

        return {
            "outcomes_by_day": outcomes_list,
            "latency_by_day": latency_list,
            "questions_by_topic": questions_by_topic,
            "documents_by_source": documents_by_source,
        }

    def tables(self) -> dict:
        # supplier activity
        activity = []
        for r in self.conn.execute(
            "SELECT supplier_id, COUNT(*) as qs FROM query_log GROUP BY supplier_id"
        ).fetchall():
            activity.append({"supplier_id": r["supplier_id"], "questions": r["qs"]})

        # unanswered: latest refused questions
        unanswered = []
        for r in self.conn.execute(
            "SELECT query_id, question FROM query_log "
            "WHERE outcome='refused' ORDER BY created_at DESC LIMIT 20"
        ).fetchall():
            unanswered.append(
                {"query_id": r["query_id"], "question": r["question"], "can_upload": True}
            )

        # evaluation
        evaluation = [
            {"metric": "answer_correctness", "target": 0.85, "value": None},
            {"metric": "citation_accuracy", "target": 0.90, "value": None},
            {"metric": "correct_refusal_rate", "target": 0.90, "value": None},
            {"metric": "false_refusal_rate", "target": 0.10, "value": None},
            {"metric": "ttft_p50_ms", "target": 3000, "value": None},
        ]

        # coverage
        coverage = []
        for r in self.conn.execute(
            "SELECT source, COUNT(*) as n FROM documents GROUP BY source"
        ).fetchall():
            coverage.append({"source": r["source"], "documents": r["n"]})

        return {
            "supplier_activity": activity,
            "unanswered": unanswered,
            "evaluation": evaluation,
            "coverage": coverage,
        }


def _median(values):
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2
