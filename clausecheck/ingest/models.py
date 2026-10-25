"""Data passed between the ingestion stages."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Page:
    """One page of raw text."""

    number: int  # 1-based
    text: str


@dataclass
class Table:
    """A table with its header row, on a given page."""

    page: int
    header: list[str]
    rows: list[list[str]]


@dataclass
class RawDocument:
    """A loaded document before cleaning."""

    doc_id: str
    path: Path
    format: str  # pdf | html | docx | txt
    pages: list[Page]
    tables: list[Table] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)  # the manifest row


@dataclass
class CleanPage:
    """One page of cleaned text, with its redaction flag."""

    number: int
    text: str
    has_redaction: bool


@dataclass
class CleanDocument:
    """A cleaned document, ready for chunking."""

    doc_id: str
    pages: list[CleanPage]
    tables: list[Table]
    has_redaction: bool
    metadata: dict


@dataclass
class Chunk:
    """One clause-level (or table, or page) chunk with the metadata used for retrieval."""

    chunk_id: str
    doc_id: str
    supplier_id: str
    text: str
    page: int  # page where the chunk starts (1-based)
    section: str | None  # e.g. "2. Payment"
    clause_no: str | None  # e.g. "2.1"; None for page-fallback and table chunks
    doc_type: str
    effective_date: str | None
    parent_doc_id: str | None
    has_redaction: bool
    is_synthetic: bool
    is_table: bool
    token_count: int
    token_start: int | None = None  # set only for windowed chunks (offsets in the clause's tokens)
    token_end: int | None = None
