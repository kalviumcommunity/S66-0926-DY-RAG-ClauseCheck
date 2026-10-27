import hashlib
import json
import re
import sqlite3
import time
from collections.abc import Callable


def normalise(question: str) -> str:
    text = re.sub(r"\s+", " ", question.strip().lower())
    return text.rstrip("?").rstrip(".").rstrip("!").strip()


def make_key(
    question: str,
    supplier_id: str | None,
    index_version: str,
    prompt_version: str,
) -> str:
    parts = [normalise(question), supplier_id or "", index_version, prompt_version]
    return hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()


class AnswerCache:
    def __init__(
        self,
        conn: sqlite3.Connection,
        ttl_seconds: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.conn = conn
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        conn.execute(
            "CREATE TABLE IF NOT EXISTS answer_cache "
            "(key TEXT PRIMARY KEY, value TEXT, created_at REAL)"
        )
        conn.commit()

    def get(self, key: str) -> dict | None:
        row = self.conn.execute(
            "SELECT value, created_at FROM answer_cache WHERE key=?", (key,)
        ).fetchone()
        if row is None:
            return None
        if self.clock() - row["created_at"] > self.ttl_seconds:
            return None
        return json.loads(row["value"])

    def set(self, key: str, value: dict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO answer_cache (key, value, created_at) VALUES (?, ?, ?)",
            (key, json.dumps(value), self.clock()),
        )
        self.conn.commit()
