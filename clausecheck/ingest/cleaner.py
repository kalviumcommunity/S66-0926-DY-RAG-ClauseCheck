"""Clean loaded text: remove footers and noise, fix wrapping, and flag redactions."""

import re

from clausecheck.ingest.models import CleanDocument, CleanPage, RawDocument, Table

# One pattern per redaction form in data-validation-report.md DV-5: [*****], [***], [*], ***,
# [**] and the phrase "confidential treatment". The last two patterns also cover the
# "[REDACTED]" and "[CONFIDENTIAL ... OMITTED]" forms that EDGAR filers use.
REDACTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"\[\s*\*{1,5}\s*\]"),
    re.compile(r"(?<![\w*])\*{3,}(?![\w*])"),
    re.compile(r"confidential\s+treatment", re.I),
    re.compile(r"\[\s*redacted\s*\]", re.I),
    re.compile(r"\[\s*confidential[^\]]*\]", re.I),
]

FOOTER_PATTERNS: list[re.Pattern] = [
    re.compile(r"^\s*Source:\s+.+,\s+[\w./-]+,\s+\d{1,2}/\d{1,2}/\d{2,4}\s*$", re.I),
    re.compile(r"^\s*\d{1,4}\s*$"),
    re.compile(r"^\s*[-–—]\s*\d{1,4}\s*[-–—]\s*$"),
    re.compile(r"^\s*page\s+\d{1,4}(\s+of\s+\d{1,4})?\s*$", re.I),
]

HEADING = re.compile(
    r"^\s*(?:\d+(?:\.\d+)+\.?|\d+\.)(?=\s|$)|^\s*(?:Section\s+\d+|ARTICLE\s+[IVXLC\d]+)\b",
)
HEADING_ONLY_MAX = 80


def detect_redaction(text: str) -> bool:
    """Return True if the text contains any redaction marker."""
    return any(p.search(text) for p in REDACTION_PATTERNS)


def strip_footers(text: str) -> str:
    """Remove EDGAR `Source:` footers and lines that are only a page number."""
    kept = [line for line in text.split("\n") if not any(p.match(line) for p in FOOTER_PATTERNS)]
    return "\n".join(kept)


def _join_hyphenated(text: str) -> str:
    """`provi-\\nsions` becomes `provisions`; hyphens next to digits or capitals are kept."""

    def repl(m: re.Match) -> str:
        left, right = m.group(1), m.group(2)
        if left.isalpha() and right.islower():
            return left + right
        return f"{left}-{right}"

    return re.sub(r"(\w)-[ \t]*\n[ \t]*(\w)", repl, text)


def _is_heading_only(line: str) -> bool:
    stripped = line.strip()
    return bool(
        HEADING.match(stripped)
        and len(stripped) <= HEADING_ONLY_MAX
        and not stripped.endswith((".", ";", ","))
    )


def _unwrap(text: str) -> str:
    """Turn single newlines inside a sentence into spaces; keep headings and blank lines."""
    out: list[str] = []
    prev: str | None = None
    for line in text.split("\n"):
        if prev is None or not line.strip() or not prev.strip():
            out.append(line)
        elif HEADING.match(line) or _is_heading_only(prev):
            out.append(line)
        else:
            out[-1] = out[-1].rstrip() + " " + line.lstrip()
        prev = line
    return "\n".join(out)


def clean_text(text: str) -> str:
    """Clean one page of text (footers, hyphenation, line wrapping, whitespace)."""
    text = strip_footers(text)
    text = _join_hyphenated(text)
    text = _unwrap(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def clean(raw: RawDocument) -> CleanDocument:
    """Clean every page, flag redactions per page and for the document, strip table cells."""
    pages = []
    for page in raw.pages:
        text = clean_text(page.text)
        pages.append(CleanPage(number=page.number, text=text, has_redaction=detect_redaction(text)))
    tables = [
        Table(
            page=t.page,
            header=[c.strip() for c in t.header],
            rows=[[c.strip() for c in row] for row in t.rows],
        )
        for t in raw.tables
    ]
    return CleanDocument(
        doc_id=raw.doc_id,
        pages=pages,
        tables=tables,
        has_redaction=any(p.has_redaction for p in pages),
        metadata=raw.metadata,
    )
