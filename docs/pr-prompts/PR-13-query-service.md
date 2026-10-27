# PR 13 · Query service: end-to-end pipeline, streaming and tracing

**Branch:** `b-query-service` · **Owner:** Teammate (Generation, Application & Delivery) · **Week:** 4 · **Depends on:** PR 12

## Context

This PR wires the whole query pipeline into the one service the API will call:

**rewrite follow-up → resolve supplier → hybrid retrieve + expand → re-rank → gate → build context → generate → validate**

Every piece already exists (PR 9 to 12). This PR only orchestrates them, adds the blocking `answer()` and the streamed `stream()` paths, applies the "an answer with no valid citation becomes a refusal" rule, and makes sure every query (including errors and cache hits) is logged.

Read before starting:
- `docs/architecture/rag-architecture-design.md`: the full query pipeline and the traceability principle
- `docs/architecture/tdd.md` §6–8 (query flow, caching, logging)
- `docs/ux/ui-states.md`: outcomes, stream events and the unsupported-value warning

## Scope (only these files)

| Path | Action |
|---|---|
| `clausecheck/services/query_service.py` | add |
| `tests/integration/test_query_service.py` | add |

No config changes are needed: every setting used here was added in PR 9 to PR 12.

## Specification

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

## Tests

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
5. Check streaming:
   ```python
   for e in svc.stream("What are the payment terms with <real supplier>?"):
       print(e.type, e.data)
   ```
   Events should arrive in the order `meta`, `sources`, `token`…, `citations`, `done`.
6. Break the LLM key on purpose (for example set a bad `GEMINI_API_KEY` and `GROQ_API_KEY` for one run). The result should be `outcome="error"` with a generic message, no key or provider text anywhere in it, and a second identical question must **not** come back as `cached`.

## Definition of done

One service answers end to end with follow-ups, caching, streaming and full logging, errors are generic and never cached, and every test passes.