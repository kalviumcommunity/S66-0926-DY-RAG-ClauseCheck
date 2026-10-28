"""The contract register and the recent-checks feed, read from the database and the query log."""

import json
import sqlite3
from collections import Counter

from clausecheck.store.query_log import QueryLog

KIND_LABELS = {
    "contract": "Contract",
    "amendment": "Amendment",
    "price_schedule": "Price schedule",
    "certificate": "Certificate",
    "dpa": "DPA",
    "sla": "SLA",
}


def _ensure_log(conn: sqlite3.Connection) -> None:
    """A database that has never answered a question has no log table yet; make it, empty."""
    QueryLog(conn)


def list_contracts(conn: sqlite3.Connection) -> list[dict]:
    """Every contract that has at least one document, most recently checked first.

    `kinds` counts documents by type, `latest_effective` is the newest effective date among them,
    and `last_checked` is the time of the last question asked about the contract.
    """
    _ensure_log(conn)
    docs: dict[str, list] = {}
    for row in conn.execute("SELECT supplier_id, doc_type, effective_date FROM documents"):
        docs.setdefault(row["supplier_id"], []).append(row)
    last_checked = {
        row["supplier_id"]: row["last"]
        for row in conn.execute(
            "SELECT supplier_id, MAX(created_at) AS last FROM query_log GROUP BY supplier_id"
        )
    }
    contracts = []
    for row in conn.execute("SELECT supplier_id, display_name FROM suppliers"):
        mine = docs.get(row["supplier_id"])
        if not mine:
            continue
        dates = [d["effective_date"] for d in mine if d["effective_date"]]
        contracts.append(
            {
                "id": row["supplier_id"],
                "name": row["display_name"] or row["supplier_id"],
                "documents": len(mine),
                "kinds": dict(Counter(d["doc_type"] or "document" for d in mine)),
                "latest_effective": max(dates) if dates else None,
                "last_checked": last_checked.get(row["supplier_id"]),
            }
        )
    contracts.sort(
        key=lambda c: (c["last_checked"] is None, _neg(c["last_checked"]), c["name"].lower())
    )
    return contracts


def _neg(timestamp: str | None) -> tuple:
    """Sort key that puts the newest timestamp first among strings."""
    return tuple(-ord(ch) for ch in (timestamp or ""))


def outcome_label(outcome: str, citations: int, unsupported: bool) -> tuple[str, str]:
    """(words, kind) for a logged check: how it ended, in the app's own vocabulary."""
    if outcome == "error":
        return "System failure", "failed"
    if outcome == "refused":
        return "No term found", "none"
    if unsupported:
        return "Verify before use", "verify"
    noun = "citation" if citations == 1 else "citations"
    return f"{citations} {noun} checked", "checked"


def recent_checks(
    conn: sqlite3.Connection, limit: int = 5, contract_id: str | None = None
) -> list[dict]:
    """The latest questions, newest first, each with the contract and how it ended."""
    _ensure_log(conn)
    names = {r["supplier_id"]: r["display_name"] for r in conn.execute("SELECT * FROM suppliers")}
    sql = (
        "SELECT query_id, created_at, supplier_id, question, outcome, citations, unsupported "
        "FROM query_log WHERE supplier_id IS NOT NULL AND supplier_id <> ''"
    )
    args: list = []
    if contract_id:
        sql += " AND supplier_id = ?"
        args.append(contract_id)
    sql += " ORDER BY created_at DESC, query_id DESC LIMIT ?"
    args.append(limit)
    rows = []
    for r in conn.execute(sql, args):
        try:
            cited = len(json.loads(r["citations"] or "[]"))
        except ValueError:
            cited = 0
        label, kind = outcome_label(r["outcome"], cited, bool(r["unsupported"]))
        rows.append(
            {
                "query_id": r["query_id"],
                "at": r["created_at"],
                "contract_id": r["supplier_id"],
                "contract": names.get(r["supplier_id"]) or r["supplier_id"],
                "question": " ".join((r["question"] or "").split()),
                "outcome": label,
                "kind": kind,
            }
        )
    return rows


def common_questions(conn: sqlite3.Connection, contract_id: str, limit: int = 5) -> list[str]:
    """The questions most often answered for this contract, most asked first."""
    _ensure_log(conn)
    rows = conn.execute(
        "SELECT question, COUNT(*) AS n, MAX(created_at) AS last FROM query_log "
        "WHERE supplier_id = ? AND outcome = 'answered' GROUP BY lower(trim(question)) "
        "ORDER BY n DESC, last DESC LIMIT ?",
        (contract_id, limit),
    ).fetchall()
    return [" ".join((r["question"] or "").split()) for r in rows]
