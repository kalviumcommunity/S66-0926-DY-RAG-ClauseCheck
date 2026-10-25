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

    With both an `embedder` and a `vector_store`, the document's vectors are replaced too.
    """
    db.upsert_document(conn, doc_row)
    db.replace_chunks(conn, doc_row["doc_id"], chunks)
    if embedder is not None and vector_store is not None:
        vector_store.delete_doc(doc_row["doc_id"])
        vector_store.upsert(chunks, embedder.embed_texts([c.text for c in chunks]))
    return len(chunks)
