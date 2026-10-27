import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from clausecheck.core.config import Settings
from clausecheck.store import sqlite as db


@dataclass
class AppContainer:
    settings: Settings
    conn: sqlite3.Connection
    query_service: Any
    sessions: Any
    query_log: Any
    upload_service: Any = None
    vector_count: Callable[[], int] | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> "AppContainer":
        conn = db.connect(settings.sqlite_path)
        db.init_db(conn)

        from clausecheck.rag.supplier_detector import SupplierDetector
        from clausecheck.services.ingestion_service import UploadService
        from clausecheck.services.query_service import QueryService
        from clausecheck.store.bm25_index import BM25Index

        query_service = QueryService.from_settings(settings, conn)
        sessions = query_service.sessions
        query_log = query_service.query_log

        retriever = query_service.retriever if hasattr(query_service, "retriever") else None
        # QueryService exposes retriever as an attribute.

        def on_indexed():
            if retriever is not None and getattr(retriever, "conn", None) is not None:
                retriever.bm25 = BM25Index.from_conn(retriever.conn)
            # an uploaded document may belong to a supplier the detector has not seen
            query_service.supplier_detector = SupplierDetector.from_conn(
                conn, settings.supplier_match_min
            )

        embedder = None
        vector_store = None
        vector = getattr(retriever, "vector_retriever", None)
        if vector is not None:
            embedder = vector.embedder
            vector_store = vector.store

        upload_service = UploadService(
            lambda: db.connect(settings.sqlite_path),
            settings,
            embedder=embedder,
            vector_store=vector_store,
            on_indexed=on_indexed,
        )

        def vector_count() -> int:
            if vector_store is None:
                return 0
            return vector_store.count()

        return cls(
            settings=settings,
            conn=conn,
            query_service=query_service,
            sessions=sessions,
            query_log=query_log,
            upload_service=upload_service,
            vector_count=vector_count,
        )
