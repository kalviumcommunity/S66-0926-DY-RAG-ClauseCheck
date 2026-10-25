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
