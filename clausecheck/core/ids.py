"""Stable identifiers for documents, chunks and queries."""

import hashlib
import uuid


def doc_id(source: str, name: str) -> str:
    """Return a deterministic document ID like `cuad-1a2b3c4d5e6f`."""
    return f"{source}-{hashlib.sha1(name.encode()).hexdigest()[:12]}".lower()


def chunk_id(doc_id: str, page: int, part: str | int) -> str:
    """Return a chunk ID; `part` is a clause number (dots become `_`) or a window like `w0`."""
    return f"{doc_id}:p{page}:{str(part).replace('.', '_')}"


def query_id() -> str:
    """Return a new random query ID (32 hex characters)."""
    return uuid.uuid4().hex
