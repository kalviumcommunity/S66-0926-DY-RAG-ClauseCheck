import json
import sqlite3

_COLUMNS = [
    "query_id",
    "created_at",
    "session_id",
    "question",
    "rewritten_question",
    "supplier_id",
    "outcome",
    "refusal_reason",
    "chunk_ids",
    "scores",
    "citations",
    "unsupported",
    "prompt_version",
    "index_version",
    "threshold",
    "latency_ms",
    "ttft_ms",
    "cached",
    "error",
]


class QueryLog:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        conn.execute("""CREATE TABLE IF NOT EXISTS query_log (
                query_id TEXT PRIMARY KEY,
                created_at TEXT,
                session_id TEXT,
                question TEXT,
                rewritten_question TEXT,
                supplier_id TEXT,
                outcome TEXT,
                refusal_reason TEXT,
                chunk_ids TEXT,
                scores TEXT,
                citations TEXT,
                unsupported INTEGER,
                prompt_version TEXT,
                index_version TEXT,
                threshold REAL,
                latency_ms REAL,
                ttft_ms REAL,
                cached INTEGER,
                error TEXT
            )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS feedback (
                query_id TEXT,
                rating TEXT,
                comment TEXT,
                created_at TEXT
            )""")
        conn.commit()

    def exists(self, query_id: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM query_log WHERE query_id=?", (query_id,)).fetchone()
        return row is not None

    def add_feedback(self, query_id: str, rating: str, comment: str | None = None) -> None:
        import datetime

        self.conn.execute(
            "INSERT INTO feedback (query_id, rating, comment, created_at) VALUES (?, ?, ?, ?)",
            (
                query_id,
                rating,
                comment,
                datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            ),
        )
        self.conn.commit()

    def log(self, record: dict) -> None:
        values = []
        for col in _COLUMNS:
            val = record.get(col, None)
            if isinstance(val, (list, dict)):
                val = json.dumps(val)
            if isinstance(val, bool):
                val = int(val)
            values.append(val)
        placeholders = ", ".join("?" for _ in _COLUMNS)
        columns = ", ".join(_COLUMNS)
        self.conn.execute(
            f"INSERT OR REPLACE INTO query_log ({columns}) VALUES ({placeholders})",
            values,
        )
        self.conn.commit()

    def recent(self, n: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT " + ", ".join(_COLUMNS) + " FROM query_log "
            "ORDER BY created_at DESC, query_id DESC LIMIT ?",
            (n,),
        ).fetchall()
        out = []
        for row in rows:
            d = {}
            for col in _COLUMNS:
                val = row[col]
                if isinstance(val, str):
                    try:
                        val = json.loads(val)
                    except (json.JSONDecodeError, ValueError):
                        pass
                if col in ("unsupported", "cached") and val is not None:
                    val = bool(val)
                d[col] = val
            out.append(d)
        return out
