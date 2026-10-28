import re
from dataclasses import dataclass

from clausecheck.rag.generator import REFUSAL_TEXT

MARKER_RE = re.compile(r"\[C(\d+)\]")
# A full stop after these does not end a sentence ("Verdant Polymers Pvt. Ltd. (the Supplier)")
ABBREVIATIONS = (
    "ltd.", "inc.", "corp.", "co.", "pvt.", "llc.", "plc.", "no.", "vs.", "etc.",
    "e.g.", "i.e.", "st.", "mr.", "ms.", "dr.", "b.v.", "n.v.", "s.a.", "gmbh.", "ag.",
)  # fmt: skip


LOOKALIKE_MARKER_RE = re.compile(r"[\[【［(]\s*C\s*(\d+)\s*[\]】］)]")
SPACE_VARIANTS = str.maketrans({" ": " ", " ": " ", " ": " ", "​": ""})


def normalise_markers(text: str) -> str:
    """Turn look-alike citation markers into `[C1]`.

    Some models write 【C1】, ［C1］, [ C1 ] or put a narrow no-break space before the marker;
    without this a correct, cited answer is counted as uncited and refused.
    """
    return LOOKALIKE_MARKER_RE.sub(r"[C\1]", text.translate(SPACE_VARIANTS))


def _sentences(text: str) -> list[str]:
    """Split on sentence-ending punctuation, but not after a common abbreviation."""
    merged: list[str] = []
    for part in re.split(r"(?<=[.!?])\s+", text):
        if merged and merged[-1].lower().endswith(ABBREVIATIONS):
            merged[-1] += " " + part
        else:
            merged.append(part)
    return merged


@dataclass
class Citation:
    """A validated citation marker pointing at a retrieved chunk."""

    marker: str
    chunk_id: str
    doc_id: str | None
    page: int | None
    section: str | None
    clause_no: str | None


@dataclass
class ValidationResult:
    """Outcome of validating an answer's citations."""

    answer: str
    citations: list[Citation]
    dropped: list[str]
    unsupported: bool


def validate(answer: str, marker_map: dict) -> ValidationResult:
    """Validate citation markers against the context's marker map."""
    answer = normalise_markers(answer)
    stripped = answer.strip()
    if stripped == REFUSAL_TEXT:
        return ValidationResult(answer=stripped, citations=[], dropped=[], unsupported=False)

    # Remove invalid markers.
    dropped: list[str] = []

    def _repl(match: re.Match) -> str:
        marker = f"C{match.group(1)}"
        if marker in marker_map:
            return match.group(0)
        dropped.append(marker)
        return ""

    cleaned = MARKER_RE.sub(_repl, answer)
    # Tidy spaces before punctuation and collapse double spaces.
    cleaned = re.sub(r"\s+([.,;:!?])", r"\1", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()

    # Unique valid citations in order of first use.
    citations: list[Citation] = []
    seen: set[str] = set()
    for match in MARKER_RE.finditer(answer):
        marker = f"C{match.group(1)}"
        if marker in marker_map and marker not in seen:
            seen.add(marker)
            hit = marker_map[marker]
            meta = getattr(hit, "metadata", {}) or {}
            citations.append(
                Citation(
                    marker=marker,
                    chunk_id=hit.chunk_id,
                    doc_id=meta.get("doc_id"),
                    page=meta.get("page"),
                    section=meta.get("section"),
                    clause_no=meta.get("clause_no"),
                )
            )

    # Determine unsupported factual sentences.
    unsupported = False
    for sentence in _sentences(answer):
        s = sentence.strip()
        if not s:
            continue
        if s.endswith(":") or s.endswith("?"):
            continue
        if s == REFUSAL_TEXT:
            continue
        valid_in_sentence = any(f"C{m.group(1)}" in marker_map for m in MARKER_RE.finditer(s))
        if not valid_in_sentence:
            unsupported = True
            break

    # Deduplicate dropped while preserving order.
    unique_dropped: list[str] = []
    for d in dropped:
        if d not in unique_dropped:
            unique_dropped.append(d)

    return ValidationResult(
        answer=cleaned, citations=citations, dropped=unique_dropped, unsupported=unsupported
    )
