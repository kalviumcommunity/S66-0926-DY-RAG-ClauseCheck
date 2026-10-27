# PR 12 · Follow-up rewriting, sessions, answer cache and query log

**Branch:** `b-sessions-cache-querylog` · **Owner:** Teammate (Generation, Application & Delivery) · **Week:** 4 · **Depends on:** PR 11

## Context

PR 13 wires the whole query pipeline into one service. This PR builds the four pieces that service needs, each testable on its own:
- a **rewriter** that turns a follow-up ("and their notice period?") into one stand-alone question
- an in-memory **session store** (last few turns plus the last supplier)
- an **answer cache** with a TTL, keyed on question, supplier, index version and prompt version
- a **query log** that records everything needed to trace an answer: chunk IDs, scores, prompt version, index version and threshold

Read before starting:
- `docs/architecture/rag-architecture-design.md`: query pipeline step 1 and the traceability principle
- `docs/architecture/tdd.md` §6–8 (query flow, caching, logging)
- `docs/ux/user-flows.md`: the follow-up flow

## Scope (only these files)

| Path | Action |
|---|---|
| `clausecheck/prompts/rewrite.txt` | add |
| `clausecheck/rag/rewriter.py` | add |
| `clausecheck/services/sessions.py` | add |
| `clausecheck/store/cache.py` | add |
| `clausecheck/store/query_log.py` | add |
| `clausecheck/core/config.py`, `.env.example` | modify: `history_turns: int = 3`, `cache_ttl_seconds: int = 86400` |
| `tests/unit/test_rewriter.py`, `test_sessions.py`, `test_cache.py`, `test_query_log.py` | add |

## Specification

### `clausecheck/prompts/rewrite.txt`

`rewrite.txt` (`# v1`, placeholders `{{history}}` and `{{question}}`): turn the latest question into **one stand-alone question** that names the supplier and the subject from the history. Output only the question.

### `clausecheck/services/sessions.py`

```python
@dataclass
class Turn: question: str; answer: str
@dataclass
class Session: session_id: str; turns: list[Turn]; supplier_id: str | None

class SessionStore:                       # in memory, thread-safe (threading.Lock)
    def __init__(self, history_turns: int = 3): ...
    def new(self) -> str: ...             # uuid4 hex
    def get_or_create(self, session_id: str | None) -> Session: ...   # unknown id -> new session with that id
    def append(self, session_id: str, question: str, answer: str, supplier_id: str | None) -> None: ...
```

`append` keeps only the last `history_turns` turns and updates `supplier_id` whenever it isn't `None`.

### `clausecheck/rag/rewriter.py`

`Rewriter(client, prompt)` with `rewrite(question: str, history: list[Turn]) -> str`:
- **Empty history**: return `question` unchanged, with **no LLM call**.
- Otherwise fill the prompt (history formatted as `User: …\nAssistant: …` lines) and call `client.complete(prompt, temperature=0.0)`.
- Return the stripped result, or `question` if the result is empty.

Also `@classmethod from_settings(cls, settings)`.

### `clausecheck/store/cache.py`

- `normalise(question) -> str`: lowercase, collapse whitespace, strip trailing `?`, `.` and `!`
- `make_key(question, supplier_id, index_version, prompt_version) -> str`: sha256 of the normalised parts joined by `\x00`
- `class AnswerCache`:
  - `__init__(self, conn, ttl_seconds: int, clock: Callable[[], float] = time.time)` creates the table `answer_cache(key PK, value TEXT, created_at REAL)`
  - `get(key) -> dict | None` returns `None` once expired
  - `set(key, value: dict) -> None` stores the value as JSON

### `clausecheck/store/query_log.py`

`class QueryLog(conn)` creates `query_log` with columns `query_id PK, created_at, session_id, question, rewritten_question, supplier_id, outcome, refusal_reason, chunk_ids, scores, citations, unsupported, prompt_version, index_version, threshold, latency_ms, ttft_ms, cached, error`. JSON lists are stored as TEXT.
- `log(record: dict) -> None`: missing keys become NULL; lists and dicts are JSON-encoded.
- `recent(n: int = 20) -> list[dict]`: newest first, with JSON fields decoded.

## Tests

### `tests/unit/test_sessions.py`

```python
from clausecheck.services.sessions import SessionStore


def test_new_and_get_or_create():
    store = SessionStore(history_turns=2)
    sid = store.new()
    assert store.get_or_create(sid).session_id == sid
    assert store.get_or_create(None).session_id != sid
    assert store.get_or_create("custom").session_id == "custom"


def test_history_trimmed_and_supplier_kept():
    store = SessionStore(history_turns=2)
    sid = store.new()
    store.append(sid, "q1", "a1", "S-ACME")
    store.append(sid, "q2", "a2", None)
    store.append(sid, "q3", "a3", None)
    s = store.get_or_create(sid)
    assert [t.question for t in s.turns] == ["q2", "q3"]
    assert s.supplier_id == "S-ACME"
```

### `tests/unit/test_rewriter.py`

```python
from clausecheck.prompts.loader import Prompt
from clausecheck.rag.rewriter import Rewriter
from clausecheck.services.sessions import Turn

PROMPT = Prompt("rewrite", "v1", "History:\n{{history}}\nQuestion: {{question}}")


class FakeClient:
    def __init__(self, reply="What is the notice period with Acme Corp?"):
        self.reply = reply
        self.calls = []

    def complete(self, prompt, **kw):
        self.calls.append(prompt)
        return self.reply


def test_no_history_no_call():
    client = FakeClient()
    assert Rewriter(client, PROMPT).rewrite("And their notice period?", []) == "And their notice period?"
    assert client.calls == []


def test_with_history_rewrites():
    client = FakeClient()
    history = [Turn("What are the payment terms with Acme Corp?", "Net 45 [C1].")]
    out = Rewriter(client, PROMPT).rewrite("And their notice period?", history)
    assert out == "What is the notice period with Acme Corp?"
    assert "User: What are the payment terms with Acme Corp?" in client.calls[0]


def test_empty_reply_falls_back():
    out = Rewriter(FakeClient(reply="   "), PROMPT).rewrite("And the term?", [Turn("q", "a")])
    assert out == "And the term?"
```

### `tests/unit/test_cache.py`

```python
from clausecheck.store import sqlite as db
from clausecheck.store.cache import AnswerCache, make_key, normalise


def test_normalise_and_key():
    assert normalise("  What are the TERMS?  ") == "what are the terms"
    k = make_key("Terms?", "S-ACME", "v1", "v1")
    assert k == make_key("terms", "S-ACME", "v1", "v1")
    assert k != make_key("terms", "S-ACME", "v2", "v1")
    assert k != make_key("terms", "S-ACME", "v1", "v2")
    assert k != make_key("terms", "S-BETA", "v1", "v1")


def test_get_set_and_expiry(tmp_path):
    conn = db.connect(tmp_path / "c.db")
    now = [1000.0]
    cache = AnswerCache(conn, ttl_seconds=60, clock=lambda: now[0])
    assert cache.get("k") is None
    cache.set("k", {"answer": "Net 45 [C1]."})
    assert cache.get("k") == {"answer": "Net 45 [C1]."}
    now[0] += 61
    assert cache.get("k") is None
```

### `tests/unit/test_query_log.py`

```python
from clausecheck.store import sqlite as db
from clausecheck.store.query_log import QueryLog


def test_log_and_recent(tmp_path):
    log = QueryLog(db.connect(tmp_path / "q.db"))
    log.log({"query_id": "q1", "created_at": "2026-11-01T10:00:00", "question": "a", "outcome": "answered",
             "chunk_ids": ["c1", "c2"], "scores": [0.9, 0.4], "cached": False})
    log.log({"query_id": "q2", "created_at": "2026-11-01T10:01:00", "question": "b", "outcome": "refused"})
    rows = log.recent(10)
    assert [r["query_id"] for r in rows] == ["q2", "q1"]
    assert rows[1]["chunk_ids"] == ["c1", "c2"] and rows[0]["chunk_ids"] is None
```

## Manual checks

1. Run `pytest -q`. Every test should pass.
2. Try the real rewriter:
   ```python
   from clausecheck.core.config import get_settings
   from clausecheck.rag.rewriter import Rewriter
   from clausecheck.services.sessions import Turn
   rw = Rewriter.from_settings(get_settings())
   print(rw.rewrite("And their notice period?", [Turn("What are the payment terms with Acme Corp?", "Net 45 [C1].")]))
   print(rw.rewrite("What are the payment terms with Acme Corp?", []))
   ```
   The first result should be one stand-alone question that names Acme Corp. The second should come back unchanged, and the provider log should show **no LLM call** for it.
3. Run `sqlite3 <your db> ".schema answer_cache"` and `".schema query_log"` after creating `AnswerCache` and `QueryLog` on a scratch DB. Every column named in the spec should exist.
4. Quick thread-safety check: start 20 threads that each call `SessionStore.append` on the same session. There should be no exception, and the session should never hold more than `history_turns` turns.

## Definition of done

Follow-ups can be rewritten into stand-alone questions, sessions keep a bounded history and the last supplier, the cache honours its TTL and versions, the query log round-trips every traceability field, and every test passes.