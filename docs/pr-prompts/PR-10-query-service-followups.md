# PR 10 · Query service, follow-ups, cache, query log and the judge

**Branch:** `b-query-service-followups` · **Owner:** Teammate (Generation, Application & Delivery) · **Week:** 4 · **Depends on:** PR 9

## Context

This PR wires the whole query pipeline into one service the API will call:

**rewrite follow-up → resolve supplier → hybrid retrieve + expand → re-rank → gate → build context → generate → validate**

It adds conversation memory (the last few turns plus the last supplier), an answer cache, and a query log that records **everything needed to trace an answer**: chunk IDs, scores, prompt version, index version and threshold. It also adds an LLM judge from a different model family (Groq), with a 10% sample checked by hand.

Read before starting:
- `docs/architecture/rag-architecture-design.md`: query pipeline step 1 and the traceability principle
- `docs/architecture/tdd.md` §6–8 (query flow, caching, logging) and §16 (judge)
- `docs/ux/user-flows.md`: the follow-up flow
- `docs/ux/ui-states.md`: outcomes, and the unsupported-value warning

## Scope (only these files)

| Path | Action |
|---|---|
| `clausecheck/prompts/rewrite.txt`, `clausecheck/prompts/judge.txt` | add |
| `clausecheck/rag/rewriter.py` | add |
| `clausecheck/services/sessions.py` | add |
| `clausecheck/services/query_service.py` | add |
| `clausecheck/store/cache.py` | add |
| `clausecheck/store/query_log.py` | add |
| `eval/judge.py` | add |
| `eval/run_eval.py` | modify: `--stage e2e` |
| `clausecheck/core/config.py`, `.env.example` | modify: `history_turns: int = 3`, `cache_ttl_seconds: int = 86400`, `judge_model: str = "llama-3.3-70b-versatile"` |
| `tests/unit/test_rewriter.py`, `test_sessions.py`, `test_cache.py`, `test_query_log.py`, `test_judge.py`, `tests/integration/test_query_service.py` | add |

## Specification

### Prompts

- `rewrite.txt` (`# v1`, placeholders `{{history}}` and `{{question}}`): turn the latest question into **one stand-alone question** that names the supplier and the subject from the history. Output only the question.
- `judge.txt` (`# v1`, placeholders `{{question}}`, `{{expected}}` and `{{answer}}`): reply with JSON only, `{"label": "correct" | "partial" | "wrong", "reason": "<one sentence>"}`. Grade by meaning. A missing citation doesn't change the label.

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

### `clausecheck/services/query_service.py`

```python
@dataclass
class QueryResult:
    query_id: str
    question: str
    rewritten_question: str
    supplier_id: str | None
    answer: str
    citations: list[Citation]
    outcome: str                 # "answered" | "refused" | "error"
    refusal_reason: str | None   # gate reason, "no_citations", or None
    unsupported: bool
    cached: bool
    timings: dict                # ms: retrieve, rerank, generate, total
    prompt_version: str
    index_version: str
    chunk_ids: list[str]         # chunks given to the model, in marker order

@dataclass
class StreamEvent:
    type: str                    # meta | sources | token | citations | done | error
    data: dict

class QueryService:
    def __init__(self, *, rewriter, supplier_detector, retriever, reranker, generator, sessions,
                 cache, query_log, threshold: float, context_budget: int, index_version: str,
                 candidates: int = 20, top_n: int = 5): ...
    def answer(self, question: str, session_id: str | None = None,
               supplier_filter: str | None = None) -> QueryResult: ...
    def stream(self, question: str, session_id: str | None = None,
               supplier_filter: str | None = None) -> Iterator[StreamEvent]: ...
    @classmethod
    def from_settings(cls, settings, conn) -> "QueryService": ...
```

Flow (`answer`):
1. Look up the session and rewrite the question using its history.
2. `supplier = supplier_filter or supplier_detector.detect(rewritten, previous=session.supplier_id)`
3. Cache key from `(rewritten, supplier, index_version, generator.prompt.version)`. On a **hit**, return the stored result with `cached=True` and a new `query_id`. Log it and append it to the session.
4. `retriever.retrieve(rewritten, supplier, k=candidates)`, then `reranker.rerank(rewritten, hits, top_n)`.
5. `relevance_gate.check(...)` against `threshold`. On failure: `outcome="refused"`, `answer=REFUSAL_TEXT`, and **the generator is not called**.
6. `build_context`, then `generator.generate(rewritten, ctx.text)`, then `validate(...)`.
7. If the answer isn't the refusal sentence and has **zero valid citations**: replace it with `REFUSAL_TEXT`, with `outcome="refused"` and `refusal_reason="no_citations"`. If it equals `REFUSAL_TEXT`, the outcome is `refused` with reason `"model_refused"`. Otherwise `answered`, with `unsupported` taken from validation.
8. Any `LLMError` gives `outcome="error"` with a generic copy-deck error message; the exception text is never included. Error results are **not cached**.
9. Cache answered and refused results. Log every query, including errors and cache hits. Append answered and refused results to the session. Record timings.

`stream` follows the same flow and yields events **in this order**:

| Event | Data |
|---|---|
| `meta` | `query_id`, `supplier_id`, `rewritten_question` |
| `sources` | list of `{marker, chunk_id, doc_id, page, section, clause_no}` for the context (empty when refused) |
| `token` | `text` (one or more) |
| `citations` | `citations`, `unsupported` |
| `done` | `outcome`, `refusal_reason`, `cached`, `timings` with `ttft` |

- Refusals stream `REFUSAL_TEXT` as one token.
- A cache hit streams the cached answer as one token.
- On an error, yield `error {"message": <generic>}` and then `done {"outcome": "error"}`.
- **No-citation rule while streaming:** tokens are already sent, so `citations` comes with `unsupported=True`, and `done` carries `outcome="refused"`, `refusal_reason="no_citations"`. The UI uses that to replace the message (see `ui-states.md`).

### `eval/judge.py`

- `Grade(label: str, reason: str)`
- `grade(client, prompt: Prompt, question, expected, answer) -> Grade`: parses the first `{…}` JSON object in the reply. A label outside `correct`, `partial` or `wrong`, or unparseable output, becomes `Grade("error", <short note>)`.
- `sample_for_review(rows: list[dict], frac: float = 0.1, seed: int = 42) -> list[dict]`: returns `max(1, round(len * frac))` rows chosen with `random.Random(seed)`, or `[]` for empty input.
- `agreement(judge: list[str], human: list[str]) -> float`: the share of equal labels.
- `build_judge_client(settings)`: an `LLMClient` with **Groq** as primary (`judge_model`) and no fallback, so the judge is always a different family from the answering model.

### `eval/run_eval.py` (`--stage e2e`)

Runs every question in the split through `QueryService.from_settings`.
- Grades: `exact` uses `contains_expected`, `real` uses the judge, and `unanswerable` is correct if `outcome == "refused"`.
- Writes per-question rows, the metrics from PR 9, median latency, and `eval/results/{date}_judge_sample_{split}.csv` (the 10% sample with an empty `human_label` column for hand grading).
- `--agreement path.csv` reads a hand-graded sample and prints the agreement.

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

### `tests/unit/test_judge.py`

```python
from eval.judge import agreement, grade, sample_for_review
from clausecheck.prompts.loader import Prompt

PROMPT = Prompt("judge", "v1", "Q {{question}} E {{expected}} A {{answer}}")


class Client:
    def __init__(self, reply):
        self.reply = reply

    def complete(self, prompt, **kw):
        return self.reply


def test_parses_json_inside_text():
    g = grade(Client('Sure: {"label": "correct", "reason": "same term"}'), PROMPT, "q", "Net 45", "Net 45 [C1].")
    assert (g.label, g.reason) == ("correct", "same term")


def test_bad_output_is_error():
    assert grade(Client("no json"), PROMPT, "q", "e", "a").label == "error"
    assert grade(Client('{"label": "great"}'), PROMPT, "q", "e", "a").label == "error"


def test_sample_and_agreement():
    rows = [{"qid": f"Q{i}"} for i in range(30)]
    s1, s2 = sample_for_review(rows), sample_for_review(rows)
    assert len(s1) == 3 and s1 == s2
    assert sample_for_review([]) == []
    assert agreement(["correct", "wrong"], ["correct", "partial"]) == 0.5
```

### `tests/integration/test_query_service.py`

```python
import pytest

from clausecheck.llm.client import LLMError
from clausecheck.prompts.loader import Prompt
from clausecheck.rag.generator import REFUSAL_TEXT
from clausecheck.rag.supplier_detector import SupplierDetector
from clausecheck.rag.types import SearchHit
from clausecheck.services.query_service import QueryService
from clausecheck.services.sessions import SessionStore
from clausecheck.store import sqlite as db
from clausecheck.store.cache import AnswerCache
from clausecheck.store.query_log import QueryLog

SUPPLIERS = [{"supplier_id": "S-ACME", "display_name": "Acme Corp", "aliases": ["Acme"]},
             {"supplier_id": "S-BETA", "display_name": "Beta Industries", "aliases": ["Beta"]}]


class FakeRewriter:
    def __init__(self):
        self.calls = []

    def rewrite(self, question, history):
        self.calls.append((question, list(history)))
        return question


class FakeRetriever:
    def __init__(self):
        self.calls = []

    def retrieve(self, query, supplier_id=None, k=20):
        self.calls.append((query, supplier_id))
        meta = {"doc_id": "doc-a", "page": 2, "section": "2. Payment", "clause_no": "2.1",
                "supplier_id": supplier_id or "S-ACME", "doc_type": "contract", "has_redaction": False}
        return [SearchHit("doc-a:p2:2_1", 0.03, "2.1 Payment is due Net 45 days.", dict(meta))]


class FakeReranker:
    def __init__(self, score):
        self.score = score

    def rerank(self, query, hits, top_n=5):
        for h in hits:
            h.rerank_score = self.score
        return hits[:top_n]


class FakeGenerator:
    prompt = Prompt("answer", "v1", "")

    def __init__(self, reply="Payment is due Net 45 days [C1].", fail=False):
        self.reply, self.fail, self.calls = reply, fail, 0

    def generate(self, question, context_text):
        self.calls += 1
        if self.fail:
            raise LLMError("All LLM providers failed: gemini, groq")
        return self.reply

    def stream(self, question, context_text):
        self.calls += 1
        if self.fail:
            raise LLMError("All LLM providers failed: gemini, groq")
        yield from ["Payment is due ", "Net 45 days [C1]."]


@pytest.fixture
def build(tmp_path):
    def _build(score=5.0, generator=None):
        conn = db.connect(tmp_path / "qs.db")
        parts = dict(rewriter=FakeRewriter(), retriever=FakeRetriever(), generator=generator or FakeGenerator())
        svc = QueryService(
            rewriter=parts["rewriter"], supplier_detector=SupplierDetector(SUPPLIERS),
            retriever=parts["retriever"], reranker=FakeReranker(score), generator=parts["generator"],
            sessions=SessionStore(3), cache=AnswerCache(conn, 3600), query_log=QueryLog(conn),
            threshold=0.0, context_budget=3000, index_version="test-v1",
        )
        return svc, parts, conn
    return _build


def test_answered_with_citation_and_logged(build):
    svc, parts, conn = build()
    r = svc.answer("What are the payment terms with Acme Corp?")
    assert r.outcome == "answered" and r.supplier_id == "S-ACME"
    assert [c.chunk_id for c in r.citations] == ["doc-a:p2:2_1"]
    assert r.chunk_ids == ["doc-a:p2:2_1"] and r.prompt_version == "v1" and r.index_version == "test-v1"
    row = QueryLog(conn).recent(1)[0]
    assert row["outcome"] == "answered" and row["chunk_ids"] == ["doc-a:p2:2_1"]


def test_low_score_refuses_without_calling_generator(build):
    svc, parts, _ = build(score=-3.0)
    r = svc.answer("What is Acme's liability cap?")
    assert (r.outcome, r.answer, r.refusal_reason) == ("refused", REFUSAL_TEXT, "low_score")
    assert parts["generator"].calls == 0


def test_answer_without_citation_becomes_refusal(build):
    svc, _, _ = build(generator=FakeGenerator(reply="Payment is due Net 45 days."))
    r = svc.answer("Payment terms with Acme?")
    assert (r.outcome, r.refusal_reason, r.answer) == ("refused", "no_citations", REFUSAL_TEXT)


def test_follow_up_keeps_supplier_and_passes_history(build):
    svc, parts, _ = build()
    sid = "s1"
    svc.answer("What are the payment terms with Acme Corp?", session_id=sid)
    svc.answer("And their notice period?", session_id=sid)
    assert parts["retriever"].calls[-1][1] == "S-ACME"
    question, history = parts["rewriter"].calls[-1]
    assert question == "And their notice period?" and len(history) == 1


def test_supplier_filter_overrides_detection(build):
    svc, parts, _ = build()
    svc.answer("What are the payment terms with Acme Corp?", supplier_filter="S-BETA")
    assert parts["retriever"].calls[-1][1] == "S-BETA"


def test_repeat_question_served_from_cache(build):
    svc, parts, conn = build()
    first = svc.answer("What are the payment terms with Acme Corp?")
    second = svc.answer("what are the payment terms with acme corp")
    assert second.cached and second.answer == first.answer and second.query_id != first.query_id
    assert parts["generator"].calls == 1
    assert len(QueryLog(conn).recent(10)) == 2


def test_llm_error_is_generic_and_not_cached(build):
    svc, parts, _ = build(generator=FakeGenerator(fail=True))
    r = svc.answer("Payment terms with Acme?")
    assert r.outcome == "error" and "gemini" not in r.answer
    r2 = svc.answer("Payment terms with Acme?")
    assert not r2.cached


def test_stream_event_order(build):
    svc, _, _ = build()
    events = list(svc.stream("What are the payment terms with Acme Corp?"))
    types = [e.type for e in events]
    assert types[0] == "meta" and types[1] == "sources"
    assert types[-2:] == ["citations", "done"]
    assert set(types[2:-2]) == {"token"}
    assert "".join(e.data["text"] for e in events if e.type == "token") == "Payment is due Net 45 days [C1]."
    assert events[-1].data["outcome"] == "answered" and "ttft" in events[-1].data["timings"]


def test_stream_refusal_and_error(build):
    svc, _, _ = build(score=-3.0)
    events = list(svc.stream("Liability cap for Acme?"))
    assert [e.data["text"] for e in events if e.type == "token"] == [REFUSAL_TEXT]
    assert events[-1].data["outcome"] == "refused"

    svc, _, _ = build(generator=FakeGenerator(fail=True))
    types = [e.type for e in svc.stream("Payment terms with Acme?")]
    assert types[-2:] == ["error", "done"]
```

## Manual checks

1. Run `pytest -q`. Every test should pass.
2. In a Python shell:
   ```python
   from clausecheck.core.config import get_settings
   from clausecheck.store import sqlite as db
   from clausecheck.services.query_service import QueryService
   s = get_settings(); svc = QueryService.from_settings(s, db.connect(s.sqlite_path))
   r = svc.answer("What are the payment terms with <real supplier>?", session_id="demo"); print(r.answer, r.citations)
   print(svc.answer("And their notice period?", session_id="demo").supplier_id)
   ```
   The follow-up should keep the same supplier.
3. Ask the first question again. It should return `cached=True` with a much smaller `timings["total"]`.
4. Run `sqlite3 index/clausecheck.db "SELECT outcome, prompt_version, index_version, threshold, latency_ms FROM query_log ORDER BY created_at DESC LIMIT 5;"`. Every column should be filled.
5. Run `python -m eval.run_eval --split tune --stage e2e`. Grade the generated judge sample by hand in the CSV, then run `python -m eval.run_eval --agreement eval/results/<file>.csv`. Record correctness, citation accuracy, refusals, median latency and judge agreement in the PR description.

## Definition of done

One service answers end to end with follow-ups, caching and full logging. The tuning split is measured end to end with spot-checked judge grades, and every test passes.
