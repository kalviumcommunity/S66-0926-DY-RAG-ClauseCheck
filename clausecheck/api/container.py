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

        from clausecheck.services.query_service import QueryService

        query_service = QueryService.from_settings(settings, conn)
        sessions = query_service.sessions
        query_log = query_service.query_log

        def vector_count() -> int:
            try:
                return conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            except Exception:
                return 0

        return cls(
            settings=settings,
            conn=conn,
            query_service=query_service,
            sessions=sessions,
            query_log=query_log,
            upload_service=None,
            vector_count=vector_count,
        )
