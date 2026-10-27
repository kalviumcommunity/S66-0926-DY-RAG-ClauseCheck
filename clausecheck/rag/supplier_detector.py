"""Find the supplier a question is about by fuzzy-matching names and aliases."""

import sqlite3

from rapidfuzz import fuzz

from clausecheck.store import sqlite as db

MIN_NAME_LENGTH = 3


class SupplierDetector:
    """Matches a question against supplier display names and aliases."""

    def __init__(self, suppliers: list[dict], min_score: int = 85):
        self.min_score = min_score
        self._names: list[tuple[str, str]] = []  # (lowercase name, supplier_id)
        for s in suppliers:
            for name in [s["display_name"], *s.get("aliases", [])]:
                if len(name.strip()) >= MIN_NAME_LENGTH:
                    self._names.append((name.strip().lower(), s["supplier_id"]))

    @classmethod
    def from_conn(cls, conn: sqlite3.Connection, min_score: int = 85) -> "SupplierDetector":
        """Build from the suppliers table."""
        return cls(db.list_suppliers(conn), min_score)

    def detect(self, question: str, previous: str | None = None) -> str | None:
        """The best-matching supplier, else `previous`. A clear new match replaces `previous`."""
        text = question.lower()
        best: tuple[float, int, str] | None = None
        for name, supplier_id in self._names:
            candidate = (fuzz.partial_ratio(name, text), len(name), supplier_id)
            if candidate[0] >= self.min_score and (best is None or candidate[:2] > best[:2]):
                best = candidate
        return best[2] if best else previous
