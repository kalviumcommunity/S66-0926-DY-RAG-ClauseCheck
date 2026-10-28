"""Recognise an uploaded amendment and link it to the agreement it amends."""

import datetime as dt
import re
import sqlite3

AMENDMENT_RE = re.compile(r"\bamendment\s+(?:no\.?|number)\s*\d+|\bamendment\s+to\b", re.I)
AGREEMENT_NO_RE = re.compile(r"\bAgreement\s+No\.?\s*([A-Z0-9][A-Z0-9/\-_.]*[A-Z0-9])", re.I)
EFFECTIVE_RE = re.compile(
    r"\beffective\s+(?:from|as\s+of|on)\s+"
    r"(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4}|[A-Za-z]+\s+\d{1,2},?\s+\d{4})",
    re.I,
)
DATE_FORMATS = ("%d %B %Y", "%B %d %Y", "%d %b %Y", "%b %d %Y")
HEAD_CHARS = 2000  # the title, parties and effective date are all at the top


def is_amendment(text: str) -> bool:
    """True if the first part of the text presents itself as an amendment."""
    return bool(AMENDMENT_RE.search(text[:HEAD_CHARS]))


def agreement_number(text: str) -> str | None:
    """The agreement number the document refers to, such as `KML/ORN/2023/004`."""
    match = AGREEMENT_NO_RE.search(text[:HEAD_CHARS])
    return match.group(1).rstrip(".") if match else None


def effective_date(text: str) -> str:
    """The first "effective from <date>" in ISO form, or an empty string."""
    for match in EFFECTIVE_RE.finditer(text[:HEAD_CHARS]):
        raw = re.sub(r"(?<=\d)(st|nd|rd|th)", "", match.group(1)).replace(",", "")
        for fmt in DATE_FORMATS:
            try:
                return dt.datetime.strptime(raw, fmt).date().isoformat()
            except ValueError:
                continue
    return ""


def find_parent(
    conn: sqlite3.Connection, supplier_id: str, number: str | None, exclude_doc_id: str
) -> str | None:
    """The supplier's agreement that the amendment is for.

    Prefers the document whose text contains the agreement number; otherwise the supplier's only
    other non-amendment document. Returns None when it is ambiguous, so a wrong link is never made.
    """
    candidates = [
        r[0]
        for r in conn.execute(
            "SELECT doc_id FROM documents WHERE supplier_id=? AND doc_id<>? "
            "AND COALESCE(doc_type,'')<>'amendment' ORDER BY doc_id",
            (supplier_id, exclude_doc_id),
        )
    ]
    if number:
        matching = [
            doc_id
            for doc_id in candidates
            if conn.execute(
                "SELECT 1 FROM chunks WHERE doc_id=? AND instr(lower(text), lower(?)) > 0 LIMIT 1",
                (doc_id, number),
            ).fetchone()
        ]
        if len(matching) == 1:
            return matching[0]
    return candidates[0] if len(candidates) == 1 else None


def describe(conn: sqlite3.Connection, row: dict, text: str) -> dict:
    """`row` with `doc_type`, `parent_doc_id` and `effective_date` filled in from the text."""
    out = dict(row)
    if not out.get("effective_date"):
        out["effective_date"] = effective_date(text)
    if is_amendment(text):
        out["doc_type"] = "amendment"
        if not out.get("parent_doc_id"):
            parent = find_parent(conn, out["supplier_id"], agreement_number(text), out["doc_id"])
            out["parent_doc_id"] = parent or ""
    return out
