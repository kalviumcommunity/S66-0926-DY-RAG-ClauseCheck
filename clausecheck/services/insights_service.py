import datetime as dt
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from clausecheck.services.contracts_service import outcome_label
from clausecheck.services.topics import NOT_CLASSIFIED, classify
from clausecheck.store.query_log import QueryLog

# the targets the report measures against (docs/requirements and mock-ux UX-9)
TARGETS = {
    "answered_rate": 0.80,
    "ttft_ms": 3000.0,
    "checked_ms": 30000.0,
    "citation_accuracy": 0.90,
}
WINDOWS = {7: "Last 7 days", 30: "Last 30 days", None: "All time"}
NUMBER_WORDS = {0: "None", 1: "One", 2: "Two", 3: "Three", 4: "Four"}


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

    def report(
        self,
        days: int | None = 7,
        contract_id: str | None = None,
        now: dt.datetime | None = None,
        results_dir: Path = Path("eval/results"),
    ) -> dict:
        """The service report: figures, targets and their status, for one window and contract.

        Unlike `kpis`, the answer rate counts system failures as not answered, so a day with
        outages cannot look better than it was.
        """
        now = now or dt.datetime.now(dt.UTC)
        QueryLog(self.conn)  # a database that has never answered a question has no log table yet
        sql = (
            "SELECT query_id, created_at, supplier_id, question, outcome, latency_ms, ttft_ms, "
            "error FROM query_log WHERE 1=1"
        )
        args: list = []
        if days:
            cutoff = (now - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
            sql += " AND created_at >= ?"
            args.append(cutoff)
        if contract_id:
            sql += " AND supplier_id = ?"
            args.append(contract_id)
        rows = self.conn.execute(sql + " ORDER BY created_at DESC", args).fetchall()
        names = {
            r["supplier_id"]: r["display_name"]
            for r in self.conn.execute("SELECT * FROM suppliers")
        }

        total = len(rows)
        outcomes = Counter(r["outcome"] for r in rows)
        answered = outcomes.get("answered", 0)
        ttft = _median([r["ttft_ms"] for r in rows if r["ttft_ms"] is not None])
        checked = _median(
            [
                r["latency_ms"]
                for r in rows
                if r["outcome"] == "answered" and r["latency_ms"] is not None
            ]
        )
        accuracy = self._heldout_citation_accuracy(results_dir)

        scorecard = [
            _score(
                "answered_rate",
                "Answered with sources",
                answered / total if total else None,
                TARGETS["answered_rate"],
                "min",
                f"{answered} of {total} questions, errors included",
            ),
            _score(
                "ttft_ms",
                "First words appear (median)",
                ttft if total else None,
                TARGETS["ttft_ms"],
                "max",
                f"Median of {total} questions",
            ),
            _score(
                "checked_ms",
                "Checked answer (median)",
                checked if answered else None,
                TARGETS["checked_ms"],
                "max",
                f"Median of {answered} answers",
            ),
            _score(
                "citation_accuracy",
                "Citation accuracy",
                accuracy["value"],
                TARGETS["citation_accuracy"],
                "min",
                (
                    f"Held-out set, {accuracy['date']}"
                    if accuracy["value"] is not None
                    else "Run eval.run_eval on the held-out set"
                ),
            ),
        ]
        topics = Counter(classify(r["question"]) for r in rows)
        unclassified = topics.get(NOT_CLASSIFIED, 0)
        failures = Counter(
            (
                r["error"]
                if r["error"] and not r["error"].startswith("ClauseCheck couldn't")
                else "Cause not recorded"
            )
            for r in rows
            if r["outcome"] == "error"
        )
        days_with_data = len({(r["created_at"] or "")[:10] for r in rows})
        daily: dict[str, Counter] = defaultdict(Counter)
        for r in rows:
            daily[(r["created_at"] or "")[:10]][r["outcome"]] += 1

        unanswered = []
        for r in rows:
            if r["outcome"] not in ("refused", "error"):
                continue
            label, kind = outcome_label(r["outcome"], 0, False)
            unanswered.append(
                {
                    "at": r["created_at"],
                    "contract": names.get(r["supplier_id"]) or r["supplier_id"] or "",
                    "question": " ".join((r["question"] or "").split()),
                    "outcome": label,
                    "kind": kind,
                }
            )
            if len(unanswered) == 10:
                break

        index = self.conn.execute(
            "SELECT COUNT(DISTINCT supplier_id) AS contracts, COUNT(*) AS documents, "
            "MAX(ingested_at) AS last FROM documents"
        ).fetchone()
        notes = []
        measured_rate = answered / (answered + outcomes.get("refused", 0)) if total else None
        if total and outcomes.get("error"):
            notes.append(
                "Answer rate counts system failures as unanswered; excluding them it would be "
                f"{round(measured_rate * 100)}%."
            )
        if total and unclassified / total > 0.2:
            notes.append(
                f"{round(unclassified / total * 100)}% of questions match no topic; the topic list "
                "needs new categories."
            )
        notes.append("Topics come from a keyword classifier; questions that match none are shown.")
        notes.append("The log does not tell evaluation and test questions apart from live use.")

        return {
            "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "window": {"days": days, "label": WINDOWS.get(days, f"Last {days} days")},
            "contract_id": contract_id,
            "contract": names.get(contract_id) if contract_id else None,
            "index": {
                "contracts": index["contracts"],
                "documents": index["documents"],
                "last_indexed": index["last"],
            },
            "questions": total,
            "outcomes": {k: outcomes.get(k, 0) for k in ("answered", "refused", "error")},
            "scorecard": scorecard,
            "headline": _headline(scorecard),
            "topics": [{"topic": t, "count": n} for t, n in topics.most_common()],
            "unclassified_share": unclassified / total if total else 0.0,
            "unanswered": unanswered,
            "failures": [{"cause": c, "count": n} for c, n in failures.most_common()],
            "days_with_data": days_with_data,
            "daily": [{"day": d, "counts": dict(c)} for d, c in sorted(daily.items())],
            "notes": notes,
        }

    @staticmethod
    def _heldout_citation_accuracy(results_dir: Path) -> dict:
        """Citation accuracy from the newest held-out end-to-end run, if there is one."""
        try:
            for path in sorted(Path(results_dir).glob("*_e2e_heldout.json"), reverse=True):
                value = (json.loads(path.read_text()).get("metrics") or {}).get("citation_accuracy")
                if value is not None:
                    return {"value": value, "date": path.name[:10]}
        except (OSError, ValueError):
            pass
        return {"value": None, "date": None}

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


def _score(key: str, label: str, value, target: float, direction: str, basis: str) -> dict:
    """One row of the scorecard. `direction` is `min` (value must reach target) or `max`."""
    if value is None:
        status = "not_measured"
    elif direction == "min":
        status = "met" if value >= target else "below"
    else:
        status = "met" if value <= target else "above"
    return {
        "key": key,
        "label": label,
        "value": value,
        "target": target,
        "direction": direction,
        "status": status,
        "basis": basis,
    }


def _headline(scorecard: list[dict]) -> str:
    """One sentence that states the result, for the top of the report."""
    measured = [r for r in scorecard if r["status"] != "not_measured"]
    if not measured:
        return "No target could be measured yet: there are no questions in this window."
    met = sum(1 for r in measured if r["status"] == "met")
    verb = "was" if met == 1 else "were"
    parts = [
        f"{NUMBER_WORDS.get(met, met)} of {NUMBER_WORDS.get(len(measured), len(measured)).lower()} "
        f"measured targets {verb} met."
    ]
    by_key = {r["key"]: r for r in scorecard}
    if by_key["answered_rate"]["status"] == "below":
        parts.append("Fewer questions were answered with sources than planned")
    if by_key["ttft_ms"]["status"] == "above":
        close = by_key["ttft_ms"]["value"] <= by_key["ttft_ms"]["target"] * 1.25
        parts.append(
            "first words arrived just over target"
            if close
            else "first words arrived well over target"
        )
    if by_key["citation_accuracy"]["status"] == "not_measured":
        parts.append("citation accuracy has not yet been measured")
    if len(parts) > 1:
        tail = ", ".join(parts[1:-1]) + (", and " if len(parts) > 2 else "") + parts[-1] + "."
        parts = [parts[0], tail[0].upper() + tail[1:]]
    return " ".join(parts)


def _median(values):
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2
