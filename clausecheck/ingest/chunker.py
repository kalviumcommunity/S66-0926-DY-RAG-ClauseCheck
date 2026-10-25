"""Split a cleaned document into clause-level chunks."""

import re
from collections import Counter

from clausecheck.core.ids import chunk_id
from clausecheck.ingest.cleaner import detect_redaction
from clausecheck.ingest.models import Chunk, CleanDocument, Table
from clausecheck.llm.tokens import count_tokens, decode, encode

HEADING_RE = re.compile(
    r"^\s*(?:(?P<sub>\d+(?:\.\d+)+)\.?|(?P<top>\d+)\.|Section\s+(?P<sec>\d+(?:\.\d+)*)"
    r"|ARTICLE\s+(?P<art>[IVXLC\d]+))(?=\s|$)",
    re.MULTILINE,
)
HEADING_ONLY_MAX = 80


class _Open:
    """A chunk being built."""

    def __init__(self, page: int, clause_no: str | None, section: str | None, part: str | None):
        self.page = page
        self.clause_no = clause_no
        self.section = section
        self.part = part  # "pre" for text before the first heading
        self.lines: list[str] = []
        self.has_body = False


def _classify(line: str) -> tuple[str | None, bool]:
    """Return (clause number, is_section_heading) for a line; (None, False) for body text."""
    m = HEADING_RE.match(line)
    if not m:
        return None, False
    if m.group("sub"):
        return m.group("sub"), False
    number = m.group("top") or m.group("sec") or m.group("art")
    stripped = line.strip()
    heading_only = len(stripped) <= HEADING_ONLY_MAX and not stripped.endswith((".", ";", ","))
    return number, heading_only


def _has_headings(doc: CleanDocument) -> bool:
    return any(
        HEADING_RE.match(line) for page in doc.pages for line in page.text.splitlines() if line
    )


def chunk(
    doc: CleanDocument, max_tokens: int = 512, window: int = 400, overlap: int = 60
) -> list[Chunk]:
    """Chunk a document by clause; fall back to one chunk per page when it has no headings."""
    meta = doc.metadata
    page_redaction = {p.number: p.has_redaction for p in doc.pages}
    seen: Counter[str] = Counter()
    out: list[Chunk] = []

    def make(text, page, section, clause_no, part, *, is_table=False, start=None, end=None):
        return Chunk(
            chunk_id=chunk_id(doc.doc_id, page, part),
            doc_id=doc.doc_id,
            supplier_id=meta.get("supplier_id", ""),
            text=text,
            page=page,
            section=section,
            clause_no=clause_no,
            doc_type=meta.get("doc_type", ""),
            effective_date=meta.get("effective_date") or None,
            parent_doc_id=meta.get("parent_doc_id") or None,
            has_redaction=page_redaction.get(page, False) or detect_redaction(text),
            is_synthetic=str(meta.get("is_synthetic", "")).lower() == "true",
            is_table=is_table,
            token_count=count_tokens(text),
            token_start=start,
            token_end=end,
        )

    def unique(part: str) -> str:
        seen[part] += 1
        return part if seen[part] == 1 else f"{part}-{seen[part]}"

    def emit(text, page, section, clause_no, base_part):
        part = unique(base_part)
        if count_tokens(text) <= max_tokens:
            out.append(make(text, page, section, clause_no, part))
            return
        tokens = encode(text)
        step = max(window - overlap, 1)
        for i, start in enumerate(range(0, len(tokens), step)):
            end = min(start + window, len(tokens))
            out.append(
                make(
                    decode(tokens[start:end]),
                    page,
                    section,
                    clause_no,
                    f"{part}-w{i}",
                    start=start,
                    end=end,
                )
            )
            if end >= len(tokens):
                break

    def flush(open_chunk: _Open | None) -> None:
        if open_chunk is None or not open_chunk.has_body:
            return
        text = "\n".join(open_chunk.lines).strip()
        if not text:
            return
        part = open_chunk.part or open_chunk.clause_no or f"page{open_chunk.page}"
        emit(text, open_chunk.page, open_chunk.section, open_chunk.clause_no, part)

    if _has_headings(doc):
        section: str | None = None
        current: _Open | None = None
        for page in doc.pages:
            for raw in page.text.splitlines():
                line = raw.strip()
                if not line:
                    continue
                number, is_heading = _classify(line)
                if number is None:
                    if current is None:
                        current = _Open(page.number, None, None, "pre")
                    current.lines.append(line)
                    current.has_body = True
                    continue
                flush(current)
                if is_heading:
                    section = line
                    current = _Open(page.number, number, section, None)
                    current.lines.append(line)  # body lines make it a chunk
                else:
                    current = _Open(page.number, number, section, None)
                    current.lines.append(line)
                    current.has_body = True
        flush(current)
    else:
        for page in doc.pages:
            text = page.text.strip()
            if text:
                emit(text, page.number, None, None, f"page{page.number}")

    for index, table in enumerate(doc.tables):
        out.extend(_table_chunks(table, index, max_tokens, make))
    return out


def _table_texts(table: Table, max_tokens: int) -> list[str]:
    """Group rows so each text (header line plus rows) fits; window a single oversized row."""
    header = " | ".join(table.header)
    if count_tokens(header) > max_tokens // 2:
        # PDF "tables" that are really paragraphs: the header is too long to repeat.
        tokens = encode("\n".join([header, *(" | ".join(r) for r in table.rows)]))
        size = max(max_tokens - 4, 1)
        return [decode(tokens[i : i + size]) for i in range(0, len(tokens), size)]
    groups: list[list[str]] = [[]]
    for row in table.rows:
        line = " | ".join(row)
        if groups[-1] and count_tokens("\n".join([header, *groups[-1], line])) > max_tokens:
            groups.append([])
        groups[-1].append(line)
    texts = []
    for group in groups:
        text = "\n".join([header, *group])
        if count_tokens(text) <= max_tokens or len(group) != 1:
            texts.append(text)
            continue
        # One row is longer than the cap: split its tokens, repeating the header.
        tokens = encode(group[0])
        budget = max(max_tokens - count_tokens(header) - 4, 1)
        texts += [
            f"{header}\n{decode(tokens[i : i + budget])}" for i in range(0, len(tokens), budget)
        ]
    return texts


def _table_chunks(table: Table, index: int, max_tokens: int, make) -> list[Chunk]:
    """One chunk per table, or several (each starting with the header) when it is too long."""
    return [
        make(text, table.page, "table", None, f"t{index}-{n}", is_table=True)
        for n, text in enumerate(_table_texts(table, max_tokens))
    ]
