"""Write a document and its chunks to the stores."""

import sqlite3

from clausecheck.ingest.models import Chunk
from clausecheck.store import sqlite as db


def index(
    conn: sqlite3.Connection,
    doc_row: dict,
    chunks: list[Chunk],
    *,
    embedder=None,
    vector_store=None,
) -> int:
    """Upsert the document row and replace its chunks; return the number of chunks.

    `embedder` and `vector_store` are accepted for the embedding PR and ignored for now.
    """
    db.upsert_document(conn, doc_row)
    db.replace_chunks(conn, doc_row["doc_id"], chunks)
    return len(chunks)
