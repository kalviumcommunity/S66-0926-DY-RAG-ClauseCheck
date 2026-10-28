"""Find the supplier a question is about by fuzzy-matching names and aliases."""

import re
import sqlite3

from rapidfuzz import fuzz

from clausecheck.store import sqlite as db

MIN_NAME_LENGTH = 3
# Shorter names must appear as whole words: fuzzy matching finds "mmi" inside "commitment"
MIN_FUZZY_LENGTH = 6


def _score(name: str, text: str) -> float:
    if len(name) < MIN_FUZZY_LENGTH:
        return 100.0 if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text) else 0.0
    return fuzz.partial_ratio(name, text)


class SupplierDetector:
    """Matches a question against supplier display names and aliases."""

    def __init__(self, suppliers: list[dict], min_score: int = 85):
        self.min_score = min_score
        self._names: list[tuple[str, str]] = []  # (lowercase name, supplier_id)
        self._display: dict[str, str] = {}
        for s in suppliers:
            self._display[s["supplier_id"]] = s["display_name"]
            for name in [s["display_name"], *s.get("aliases", [])]:
                if len(name.strip()) >= MIN_NAME_LENGTH:
                    self._names.append((name.strip().lower(), s["supplier_id"]))

    def display_name(self, supplier_id: str) -> str:
        """The name to show for a supplier; the ID itself if it is unknown."""
        return self._display.get(supplier_id, supplier_id)

    def other_supplier(self, question: str, scope_id: str) -> str | None:
        """A supplier other than `scope_id` that the question names, or None.

        Used inside a conversation that is about one contract: a question that names another
        contract must not be answered from this one.
        """
        text = question.lower()
        best: tuple[float, int, str] | None = None
        for name, supplier_id in self._names:
            if supplier_id == scope_id:
                continue
            candidate = (_score(name, text), len(name), supplier_id)
            if candidate[0] >= self.min_score and (best is None or candidate[:2] > best[:2]):
                best = candidate
        return best[2] if best else None

    @classmethod
    def from_conn(cls, conn: sqlite3.Connection, min_score: int = 85) -> "SupplierDetector":
        """Build from the suppliers table."""
        return cls(db.list_suppliers(conn), min_score)

    def strip_names(self, question: str, supplier_id: str | None) -> str:
        """`question` with the supplier's name replaced by "the Supplier", for the re-ranker.

        Inside a supplier-filtered search the name tells the re-ranker nothing, and it pulls in
        every title and preamble chunk, which repeat the party names. Replacing it, not deleting
        it, keeps the sentence whole ("What insurance must the Supplier carry?"), which scores far
        better than "What insurance must carry?", and matches how contracts name the party.
        """
        if not supplier_id:
            return question
        out = question
        names = sorted((n for n, sid in self._names if sid == supplier_id), key=len, reverse=True)

        def replace(match: re.Match) -> str:
            return "the Supplier's" if match.group("poss") else "the Supplier"

        for name in names:
            # The stored name may be shorter than the one in the question ("Sapphire" against
            # "Sapphire Facility Services Pvt. Ltd."), so take the capitalised words after it too.
            out = re.sub(
                rf"(?:\b(?i:the|our|their|its)\s+)?(?i:{re.escape(name)})"
                rf"(?:\s+[A-Z][\w&.\-]*){{0,4}}(?P<poss>['’]s?)?",
                replace,
                out,
            )
        return out

    def detect(self, question: str, previous: str | None = None) -> str | None:
        """The best-matching supplier, else `previous`. A clear new match replaces `previous`."""
        text = question.lower()
        best: tuple[float, int, str] | None = None
        for name, supplier_id in self._names:
            candidate = (_score(name, text), len(name), supplier_id)
            if candidate[0] >= self.min_score and (best is None or candidate[:2] > best[:2]):
                best = candidate
        return best[2] if best else previous
