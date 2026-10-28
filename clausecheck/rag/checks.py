"""Checks run on a finished answer, and the table of terms shown beside it.

Everything here is computed from the answer text and from the clauses the answer cites. Nothing is
taken from what the model says about its own answer, so the "Checked" seal in the app can be trusted
to describe what the backend actually verified.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from clausecheck.rag.citation_validator import MARKER_RE, _sentences
from clausecheck.rag.hybrid_retriever import CLAUSE_REF_RE

NUMBER_RE = re.compile(r"(?<![\w.])\$?\d[\d,]*(?:\.\d+)?%?")
UNIT = (
    r"(?:%|(?:calendar |business |working )?(?:days?|weeks?|months?|years?|hours?|minutes?)\b"
    r"|per [A-Za-z]+|units?\b|MT\b)"
)
FIGURE_RE = re.compile(rf"\$?\d[\d,]*(?:\.\d+)?\)?(?:\s?{UNIT})?", re.I)
YEAR_RE = re.compile(r"(?:19|20)\d\d")
HEADING_RE = re.compile(r"^\s*\d+(?:\.\d+)*\.?\s+([A-Z][A-Za-z0-9 &/\-']{2,60}?)[.:]\s")
NAMED_REF_RE = re.compile(r"Section\s+\d+(?:\.\d+)*\s*\(([A-Z][A-Za-z &/\-']{2,60})\)")
QUOTED_HEADING_RE = re.compile(
    r"[\"\u201c]\s*\d+(?:\.\d+)*\.?\s+([A-Z][A-Za-z0-9 &/\-']{2,60}?)[.:]\s"
)
LEADING_NUMBER_RE = re.compile(r"^\s*\d+(?:\.\d+)*\.?\s+")
WORDS = (
    "zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen"
    "|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety"
    "|hundred|thousand|million"
)
WORD_PREFIX_RE = re.compile(rf"(?:\b(?:{WORDS})(?:[- ](?:{WORDS}))*\s+)?\(?$", re.I)
UNIT_SUFFIX_RE = re.compile(
    r"(?:\s+(?:per\s+[A-Za-z]+|(?:calendar\s+|business\s+)?"
    r"(?:days?|weeks?|months?|years?|hours?|minutes?)\b))?",
    re.I,
)

DocInfo = Callable[[str], dict | None]
AmendedClauses = Callable[[str], dict[str, str]]


def normalise(number: str) -> str:
    """`$40,000` and `40000` and `40,000.00` all become `40000`; `99.95%` becomes `99.95`."""
    n = number.replace("$", "").replace("%", "").replace(",", "")
    whole, _, fraction = n.partition(".")
    whole = whole.lstrip("0") or "0"
    fraction = fraction.rstrip("0")
    return f"{whole}.{fraction}" if fraction else whole


def numbers_in(text: str) -> list[tuple[str, str]]:
    """(as written, normalised) for each figure in `text`, ignoring citation markers."""
    return [(m, normalise(m)) for m in NUMBER_RE.findall(MARKER_RE.sub("", text))]


def _clause_figures(hit) -> set[str]:
    """Every figure in a clause, plus its date, clause number and section, as normalised strings."""
    meta = hit.metadata or {}
    extra = " ".join(str(meta.get(k) or "") for k in ("effective_date", "clause_no", "section"))
    return {n for _, n in numbers_in(hit.text or "")} | {n for _, n in numbers_in(extra)}


def _marker_ids(sentence: str, marker_map: dict) -> list[str]:
    seen: list[str] = []
    for m in MARKER_RE.finditer(sentence):
        marker = f"C{m.group(1)}"
        if marker in marker_map and marker not in seen:
            seen.append(marker)
    return seen


@dataclass
class Checks:
    """What was verified about one answer."""

    citations_found: int = 0
    citations_total: int = 0
    numbers_total: int = 0
    unverified: list[dict] = field(default_factory=list)  # {"value", "marker"}
    uncited_sentences: int = 0
    amendments: list[dict] = field(default_factory=list)
    matched_by_marker: dict[str, list[str]] = field(default_factory=dict)

    @property
    def status(self) -> str:
        """`checked` when every citation exists and every figure is in its clause, else `verify`."""
        clean = (
            self.citations_found > 0
            and self.citations_found == self.citations_total
            and not self.unverified
            and not self.uncited_sentences
        )
        return "checked" if clean else "verify"

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "citations": {"found": self.citations_found, "total": self.citations_total},
            "numbers": {
                "matched": self.numbers_total - len(self.unverified),
                "total": self.numbers_total,
                "unverified": self.unverified,
            },
            "uncited_sentences": self.uncited_sentences,
            "amendments": self.amendments,
        }


def check_answer(
    answer: str, marker_map: dict, doc_info: DocInfo | None = None, dropped: int = 0
) -> Checks:
    """Verify the citations and figures of `answer` against the clauses in `marker_map`."""
    doc_info = doc_info or (lambda _doc_id: None)
    checks = Checks()
    used: list[str] = []
    figures = {marker: _clause_figures(hit) for marker, hit in marker_map.items()}
    sentences = [s.strip() for s in _sentences(answer) if s.strip()]
    for text in sentences:
        for marker in _marker_ids(text, marker_map):
            if marker not in used:
                used.append(marker)
    # A figure counts as verified if it is in any clause the answer cites. A sentence such as
    # "replacing Net 30 [C1]" cites the new clause but names the old figure, which is in the
    # original clause cited elsewhere. A figure that is in no cited clause is still flagged.
    allowed_everywhere = set().union(*(figures[m] for m in used)) if used else set()
    for text in sentences:
        markers = _marker_ids(text, marker_map)
        found = numbers_in(text)
        checks.numbers_total += len(found)
        if not markers:
            if not text.endswith((":", "?")):
                checks.uncited_sentences += 1
                checks.unverified += [{"value": raw, "marker": None} for raw, _ in found]
            continue
        for raw, norm in found:
            if norm in allowed_everywhere:
                for marker in used:
                    if norm in figures[marker]:
                        checks.matched_by_marker.setdefault(marker, []).append(norm)
            else:
                checks.unverified.append({"value": raw, "marker": markers[0]})
    checks.citations_found = len(used)
    checks.citations_total = len(used) + dropped
    seen_amendments: set[tuple] = set()
    for marker in used:
        meta = marker_map[marker].metadata or {}
        if meta.get("doc_type") != "amendment":
            continue
        info = doc_info(meta.get("doc_id") or "") or {}
        refs = CLAUSE_REF_RE.findall(marker_map[marker].text or "")
        key = (meta.get("doc_id"), refs[0] if refs else meta.get("clause_no"))
        if key in seen_amendments:
            continue
        seen_amendments.add(key)
        checks.amendments.append(
            {
                "marker": marker,
                "title": info.get("title") or meta.get("doc_id"),
                "effective_date": meta.get("effective_date") or info.get("effective_date"),
                "clause_no": meta.get("clause_no"),
                "replaces_clause": refs[0] if refs else None,
            }
        )
    return checks


def highlight_spans(text: str, normalised_numbers: list[str]) -> list[list[int]]:
    """Character ranges of `text` holding the figures the answer relies on, with their words.

    `forty-five (45) days` is one range, so the reader sees the whole phrase.
    """
    wanted = set(normalised_numbers)
    spans: list[list[int]] = []
    for m in NUMBER_RE.finditer(text):
        if normalise(m.group(0)) not in wanted:
            continue
        start, end = m.start(), m.end()
        opened = text[start - 1 : start] == "("
        prefix = WORD_PREFIX_RE.search(text[:start])
        if prefix and prefix.start() < start:
            start = prefix.start()
        if opened and text[end : end + 1] == ")":
            end += 1
        end += UNIT_SUFFIX_RE.match(text[end:]).end()
        spans.append([start, end])
    spans.sort()
    merged: list[list[int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def key_figures(text: str, limit: int = 3) -> list[str]:
    """The figures in a clause as short phrases (`45 days`, `2%`), without clause numbers."""
    body = CLAUSE_REF_RE.sub("", LEADING_NUMBER_RE.sub("", text or "", count=1))
    out: list[str] = []
    seen: set[str] = set()
    for m in FIGURE_RE.finditer(body):
        raw = " ".join(m.group(0).replace(")", "").split())
        number = NUMBER_RE.match(raw)
        if number is None:
            continue
        digits = normalise(number.group(0))
        has_unit = len(raw) > len(number.group(0))
        # A figure worth listing has a unit or a currency sign. A bare number is usually a clause
        # number ("5.1"), a count or a year, so it is listed only when it is large.
        worth_listing = (
            has_unit or "$" in raw or (len(digits) >= 4 and not YEAR_RE.fullmatch(digits))
        )
        if digits in seen or not worth_listing:
            continue
        seen.add(digits)
        out.append(raw)
        if len(out) == limit:
            break
    return out


def term_name(hit) -> str:
    """A clause's heading (`Payment Period`), else its section name, else `Clause 4.1`."""
    text = hit.text or ""
    for pattern in (HEADING_RE.match, NAMED_REF_RE.search, QUOTED_HEADING_RE.search):
        match = pattern(text)
        if match:
            return _sentence_case(match.group(1).strip())
    meta = hit.metadata or {}
    section = re.sub(r"^[\d.\s-]+", "", str(meta.get("section") or "")).strip()
    return _sentence_case(section) or f"Clause {meta.get('clause_no') or '-'}"


def _sentence_case(name: str) -> str:
    """`PAYMENT TERMS` as written in some documents becomes `Payment Terms`."""
    return name.title() if name.isupper() else name


def _first_sentence(text: str, width: int = 90) -> str:
    heading = HEADING_RE.match(text or "")
    body = (text or "")[heading.end() :] if heading else LEADING_NUMBER_RE.sub("", text or "", 1)
    first = re.split(r"(?<=[.;])\s", body, maxsplit=1)[0]
    return first if len(first) <= width else first[: width - 1].rstrip() + "…"


def terms_found(
    cited: list[tuple[str, object]],
    doc_info: DocInfo | None = None,
    amended_clauses: AmendedClauses | None = None,
) -> list[dict]:
    """One row per cited clause: term, value in the clause, source, and whether it is in force.

    `cited` is `[(marker, hit)]` in citation order. A clause of an original agreement that a cited
    amendment changes is `Replaced by C#`; one that an uncited amendment changes is `Amended by
    <title>`; an amendment clause is `In force since <date>`.
    """
    doc_info = doc_info or (lambda _doc_id: None)
    amended_clauses = amended_clauses or (lambda _doc_id: {})
    cited_amendments = {}
    for marker, hit in cited:
        meta = hit.metadata or {}
        if meta.get("doc_type") == "amendment" and meta.get("parent_doc_id"):
            for ref in set(CLAUSE_REF_RE.findall(hit.text or "")):
                cited_amendments.setdefault((meta["parent_doc_id"], ref), marker)
    rows = []
    for marker, hit in cited:
        meta = hit.metadata or {}
        doc_id = meta.get("doc_id") or ""
        info = doc_info(doc_id) or {}
        date = meta.get("effective_date") or info.get("effective_date")
        clause = meta.get("clause_no")
        if meta.get("doc_type") == "amendment":
            kind, status = "in_force", f"In force since {date}" if date else "In force"
        elif (doc_id, clause) in cited_amendments:
            kind, status = "replaced", f"Replaced by {cited_amendments[(doc_id, clause)]}"
        elif clause and clause in amended_clauses(doc_id):
            kind, status = "amended", f"Amended by {amended_clauses(doc_id)[clause]}"
        else:
            kind, status = "in_force", f"In force since {date}" if date else "In force"
        figures = key_figures(hit.text)
        if not figures and len((hit.text or "").strip()) < 60:
            continue  # a heading fragment such as "2.1 Section 5.1 Replaced" is not a term
        title = info.get("title") or doc_id
        page = meta.get("page")
        rows.append(
            {
                "marker": marker,
                "term": term_name(hit),
                "value": ", ".join(figures) if figures else _first_sentence(hit.text),
                "source": f"§{clause}, {title}" + (f", p.{page}" if page else ""),
                "status": status,
                "status_kind": kind,
            }
        )
    return rows


def clause_pages(
    cited: list[tuple[str, object]], checks: Checks, doc_info: DocInfo | None = None
) -> dict[str, dict]:
    """What the clause-page panel needs for each cited marker, with the words to highlight."""
    doc_info = doc_info or (lambda _doc_id: None)
    out = {}
    for marker, hit in cited:
        meta = hit.metadata or {}
        info = doc_info(meta.get("doc_id") or "") or {}
        out[marker] = {
            "chunk_id": hit.chunk_id,
            "doc_id": meta.get("doc_id"),
            "doc_title": info.get("title") or meta.get("doc_id"),
            "doc_type": meta.get("doc_type") or info.get("doc_type"),
            "effective_date": meta.get("effective_date") or info.get("effective_date"),
            "page": meta.get("page"),
            "section": meta.get("section"),
            "clause_no": meta.get("clause_no"),
            "text": hit.text,
            "highlights": highlight_spans(hit.text or "", checks.matched_by_marker.get(marker, [])),
        }
    return out
