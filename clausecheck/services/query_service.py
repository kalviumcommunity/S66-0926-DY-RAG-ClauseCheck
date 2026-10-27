import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from clausecheck.llm.client import LLMError
from clausecheck.rag.citation_validator import validate
from clausecheck.rag.context_builder import build_context
from clausecheck.rag.generator import REFUSAL_TEXT
from clausecheck.rag.relevance_gate import check as gate_check
from clausecheck.services.sessions import SessionStore
from clausecheck.store.cache import AnswerCache, make_key
from clausecheck.store.query_log import QueryLog

GENERIC_ERROR = (
    'ClauseCheck couldn\'t generate an answer right now. This is a system error, not a "not found".'
)


@dataclass
class QueryResult:
    query_id: str
    question: str
    rewritten_question: str
    supplier_id: str | None
    answer: str
    citations: list[Any]
    outcome: str
    refusal_reason: str | None
    unsupported: bool
    cached: bool
    timings: dict
    prompt_version: str
    index_version: str
    chunk_ids: list[str]


@dataclass
class StreamEvent:
    type: str
    data: dict


@dataclass
class QueryService:
    rewriter: Any
    supplier_detector: Any
    retriever: Any
    reranker: Any
    generator: Any
    sessions: SessionStore
    cache: AnswerCache
    query_log: QueryLog
    threshold: float
    context_budget: int
    index_version: str
    candidates: int = 20
    top_n: int = 5

    def _new_id(self) -> str:
        return uuid.uuid4().hex

    def _to_cache(self, result: QueryResult) -> dict:
        return {
            "question": result.question,
            "rewritten_question": result.rewritten_question,
            "supplier_id": result.supplier_id,
            "answer": result.answer,
            "citations": [
                {
                    "marker": c.marker,
                    "chunk_id": c.chunk_id,
                    "doc_id": c.doc_id,
                    "page": c.page,
                    "section": c.section,
                    "clause_no": c.clause_no,
                }
                for c in result.citations
            ],
            "outcome": result.outcome,
            "refusal_reason": result.refusal_reason,
            "unsupported": result.unsupported,
            "timings": result.timings,
            "prompt_version": result.prompt_version,
            "index_version": result.index_version,
            "chunk_ids": result.chunk_ids,
        }

    def _from_cache(self, query_id: str, question: str, cached: dict) -> QueryResult:
        from clausecheck.rag.citation_validator import Citation

        citations = [
            Citation(
                marker=c["marker"],
                chunk_id=c["chunk_id"],
                doc_id=c.get("doc_id"),
                page=c.get("page"),
                section=c.get("section"),
                clause_no=c.get("clause_no"),
            )
            for c in cached.get("citations", [])
        ]
        return QueryResult(
            query_id=query_id,
            question=question,
            rewritten_question=cached.get("rewritten_question", question),
            supplier_id=cached.get("supplier_id"),
            answer=cached.get("answer", ""),
            citations=citations,
            outcome=cached.get("outcome", "answered"),
            refusal_reason=cached.get("refusal_reason"),
            unsupported=cached.get("unsupported", False),
            cached=True,
            timings=cached.get("timings", {}),
            prompt_version=cached.get("prompt_version", self.generator.prompt.version),
            index_version=cached.get("index_version", self.index_version),
            chunk_ids=cached.get("chunk_ids", []),
        )

    def _log(
        self, result: QueryResult, cached: bool, chunk_ids: list[str], scores: list, sources: list
    ) -> None:
        import datetime

        record = {
            "query_id": result.query_id,
            "created_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "session_id": None,
            "question": result.question,
            "rewritten_question": result.rewritten_question,
            "supplier_id": result.supplier_id,
            "outcome": result.outcome,
            "refusal_reason": result.refusal_reason,
            "chunk_ids": chunk_ids,
            "scores": scores,
            "citations": [c.chunk_id for c in result.citations],
            "unsupported": result.unsupported,
            "prompt_version": result.prompt_version,
            "index_version": result.index_version,
            "threshold": self.threshold,
            "latency_ms": result.timings.get("total", 0.0),
            "ttft_ms": result.timings.get("ttft", result.timings.get("total", 0.0)),
            "cached": cached,
            "error": None,
        }
        if result.outcome == "error":
            record["error"] = result.answer
        self.query_log.log(record)

    def answer(
        self, question: str, session_id: str | None = None, supplier_filter: str | None = None
    ) -> QueryResult:
        query_id = self._new_id()
        t0 = time.perf_counter()
        session = self.sessions.get_or_create(session_id)
        rewritten = self.rewriter.rewrite(question, session.turns)
        supplier = (
            supplier_filter
            if supplier_filter is not None
            else self.supplier_detector.detect(rewritten, previous=session.supplier_id)
        )

        key = make_key(rewritten, supplier, self.index_version, self.generator.prompt.version)
        cached_val = self.cache.get(key)
        if cached_val is not None:
            result = self._from_cache(query_id, question, cached_val)
            result.question = question
            result.rewritten_question = rewritten
            result.supplier_id = supplier
            result.cached = True
            timings = dict(cached_val.get("timings", {}))
            timings["total"] = round((time.perf_counter() - t0) * 1000, 2)
            result.timings = timings
            self._log(result, True, result.chunk_ids, [], [])
            if result.outcome in ("answered", "refused"):
                self.sessions.append(
                    session_id if session_id else query_id, question, result.answer, supplier
                )
            return result

        # retrieve
        t_ret = time.perf_counter()
        try:
            hits = self.retriever.retrieve(rewritten, supplier, k=self.candidates)
        except Exception:
            hits = []
        retrieve_ms = (time.perf_counter() - t_ret) * 1000

        t_rerank = time.perf_counter()
        try:
            hits = self.reranker.rerank(rewritten, hits, self.top_n)
        except Exception:
            pass
        rerank_ms = (time.perf_counter() - t_rerank) * 1000

        gate = gate_check(hits, self.threshold, supplier_required=False, supplier_id=supplier)

        chunk_ids: list[str] = []
        citations = []
        unsupported = False
        answer = REFUSAL_TEXT
        outcome = "refused"
        refusal_reason = gate.reason
        generate_ms = 0.0

        if gate.passed:
            ctx = build_context(hits, self.context_budget)
            chunk_ids = [h.chunk_id for h in ctx.used]
            t_gen = time.perf_counter()
            try:
                raw = self.generator.generate(rewritten, ctx.text)
                generate_ms = (time.perf_counter() - t_gen) * 1000
                vr = validate(raw, ctx.marker_map)
                answer = vr.answer
                citations = vr.citations
                unsupported = vr.unsupported
                if answer.strip() != REFUSAL_TEXT and not citations:
                    answer = REFUSAL_TEXT
                    outcome = "refused"
                    refusal_reason = "no_citations"
                    citations = []
                elif answer.strip() == REFUSAL_TEXT:
                    outcome = "refused"
                    refusal_reason = "model_refused"
                else:
                    outcome = "answered"
                    refusal_reason = None
            except LLMError:
                generate_ms = (time.perf_counter() - t_gen) * 1000
                outcome = "error"
                answer = GENERIC_ERROR
                refusal_reason = None
                citations = []
                unsupported = False
        else:
            chunk_ids = []

        scores = []
        if gate.passed:
            try:
                scores = [h.rerank_score if h.rerank_score is not None else h.score for h in hits]
            except Exception:
                scores = []

        total_ms = (time.perf_counter() - t0) * 1000
        timings = {
            "retrieve": round(retrieve_ms, 2),
            "rerank": round(rerank_ms, 2),
            "generate": round(generate_ms, 2),
            "total": round(total_ms, 2),
        }

        result = QueryResult(
            query_id=query_id,
            question=question,
            rewritten_question=rewritten,
            supplier_id=supplier,
            answer=answer,
            citations=citations,
            outcome=outcome,
            refusal_reason=refusal_reason,
            unsupported=unsupported,
            cached=False,
            timings=timings,
            prompt_version=self.generator.prompt.version,
            index_version=self.index_version,
            chunk_ids=chunk_ids,
        )

        if outcome in ("answered", "refused"):
            cache_payload = self._to_cache(result)
            self.cache.set(key, cache_payload)

        self._log(result, False, chunk_ids, scores, [])
        if outcome in ("answered", "refused"):
            self.sessions.append(session_id if session_id else query_id, question, answer, supplier)

        return result

    def stream(
        self, question: str, session_id: str | None = None, supplier_filter: str | None = None
    ) -> Iterator[StreamEvent]:
        query_id = self._new_id()
        t0 = time.perf_counter()
        session = self.sessions.get_or_create(session_id)
        rewritten = self.rewriter.rewrite(question, session.turns)
        supplier = (
            supplier_filter
            if supplier_filter is not None
            else self.supplier_detector.detect(rewritten, previous=session.supplier_id)
        )

        key = make_key(rewritten, supplier, self.index_version, self.generator.prompt.version)
        cached_val = self.cache.get(key)
        if cached_val is not None:
            yield StreamEvent(
                "meta",
                {"query_id": query_id, "supplier_id": supplier, "rewritten_question": rewritten},
            )
            yield StreamEvent("sources", {"sources": cached_val.get("sources", [])})
            yield StreamEvent("token", {"text": cached_val.get("answer", "")})
            from clausecheck.rag.citation_validator import Citation

            citations = [
                Citation(
                    marker=c["marker"],
                    chunk_id=c["chunk_id"],
                    doc_id=c.get("doc_id"),
                    page=c.get("page"),
                    section=c.get("section"),
                    clause_no=c.get("clause_no"),
                )
                for c in cached_val.get("citations", [])
            ]
            yield StreamEvent(
                "citations",
                {
                    "citations": [c.chunk_id for c in citations],
                    "unsupported": cached_val.get("unsupported", False),
                },
            )
            total_ms = round((time.perf_counter() - t0) * 1000, 2)
            yield StreamEvent(
                "done",
                {
                    "outcome": cached_val.get("outcome", "answered"),
                    "refusal_reason": cached_val.get("refusal_reason"),
                    "cached": True,
                    "timings": {"ttft": total_ms, "total": total_ms},
                },
            )
            result = self._from_cache(query_id, question, cached_val)
            result.question = question
            result.rewritten_question = rewritten
            result.supplier_id = supplier
            result.cached = True
            self._log(result, True, result.chunk_ids, [], [])
            if result.outcome in ("answered", "refused"):
                self.sessions.append(
                    session_id if session_id else query_id, question, result.answer, supplier
                )
            return

        # retrieve
        t_ret = time.perf_counter()
        try:
            hits = self.retriever.retrieve(rewritten, supplier, k=self.candidates)
        except Exception:
            hits = []
        retrieve_ms = (time.perf_counter() - t_ret) * 1000
        t_rerank = time.perf_counter()
        try:
            hits = self.reranker.rerank(rewritten, hits, self.top_n)
        except Exception:
            pass
        rerank_ms = (time.perf_counter() - t_rerank) * 1000

        gate = gate_check(hits, self.threshold, supplier_required=False, supplier_id=supplier)

        yield StreamEvent(
            "meta", {"query_id": query_id, "supplier_id": supplier, "rewritten_question": rewritten}
        )

        if not gate.passed:
            yield StreamEvent("sources", {"sources": []})
            yield StreamEvent("token", {"text": REFUSAL_TEXT})
            yield StreamEvent("citations", {"citations": [], "unsupported": False})
            total_ms = round((time.perf_counter() - t0) * 1000, 2)
            yield StreamEvent(
                "done",
                {
                    "outcome": "refused",
                    "refusal_reason": gate.reason,
                    "cached": False,
                    "timings": {"ttft": total_ms, "total": total_ms},
                },
            )
            result = QueryResult(
                query_id=query_id,
                question=question,
                rewritten_question=rewritten,
                supplier_id=supplier,
                answer=REFUSAL_TEXT,
                citations=[],
                outcome="refused",
                refusal_reason=gate.reason,
                unsupported=False,
                cached=False,
                timings={
                    "retrieve": round(retrieve_ms, 2),
                    "rerank": round(rerank_ms, 2),
                    "generate": 0.0,
                    "total": total_ms,
                },
                prompt_version=self.generator.prompt.version,
                index_version=self.index_version,
                chunk_ids=[],
            )
            self.cache.set(key, self._to_cache(result))
            self._log(result, False, [], [], [])
            self.sessions.append(
                session_id if session_id else query_id, question, REFUSAL_TEXT, supplier
            )
            return

        ctx = build_context(hits, self.context_budget)
        sources = [
            {
                "marker": m,
                "chunk_id": h.chunk_id,
                "doc_id": (h.metadata or {}).get("doc_id"),
                "page": (h.metadata or {}).get("page"),
                "section": (h.metadata or {}).get("section"),
                "clause_no": (h.metadata or {}).get("clause_no"),
            }
            for m, h in ctx.marker_map.items()
        ]
        yield StreamEvent("sources", {"sources": sources})

        t_gen = time.perf_counter()
        accumulated = ""
        ttft = None
        try:
            for tok in self.generator.stream(rewritten, ctx.text):
                if ttft is None:
                    ttft = (time.perf_counter() - t_gen) * 1000
                accumulated += tok
                yield StreamEvent("token", {"text": tok})
            generate_ms = (time.perf_counter() - t_gen) * 1000
        except LLMError:
            generate_ms = (time.perf_counter() - t_gen) * 1000
            yield StreamEvent("error", {"message": GENERIC_ERROR})
            total_ms = round((time.perf_counter() - t0) * 1000, 2)
            yield StreamEvent(
                "done",
                {
                    "outcome": "error",
                    "refusal_reason": None,
                    "cached": False,
                    "timings": {"ttft": total_ms, "total": total_ms},
                },
            )
            result = QueryResult(
                query_id=query_id,
                question=question,
                rewritten_question=rewritten,
                supplier_id=supplier,
                answer=GENERIC_ERROR,
                citations=[],
                outcome="error",
                refusal_reason=None,
                unsupported=False,
                cached=False,
                timings={
                    "retrieve": round(retrieve_ms, 2),
                    "rerank": round(rerank_ms, 2),
                    "generate": round(generate_ms, 2),
                    "total": total_ms,
                },
                prompt_version=self.generator.prompt.version,
                index_version=self.index_version,
                chunk_ids=[h.chunk_id for h in ctx.used],
            )
            self._log(result, False, result.chunk_ids, [], [])
            return

        vr = validate(accumulated, ctx.marker_map)
        answer = vr.answer
        citations = vr.citations
        unsupported = vr.unsupported
        if answer.strip() != REFUSAL_TEXT and not citations:
            outcome = "refused"
            refusal_reason = "no_citations"
            answer = REFUSAL_TEXT
            citations = []
        elif answer.strip() == REFUSAL_TEXT:
            outcome = "refused"
            refusal_reason = "model_refused"
        else:
            outcome = "answered"
            refusal_reason = None

        total_ms = round((time.perf_counter() - t0) * 1000, 2)
        if ttft is None:
            ttft = total_ms
        timings = {
            "retrieve": round(retrieve_ms, 2),
            "rerank": round(rerank_ms, 2),
            "generate": round(generate_ms, 2),
            "total": total_ms,
            "ttft": round(ttft, 2),
        }

        yield StreamEvent(
            "citations", {"citations": [c.chunk_id for c in citations], "unsupported": unsupported}
        )
        yield StreamEvent(
            "done",
            {
                "outcome": outcome,
                "refusal_reason": refusal_reason,
                "cached": False,
                "timings": {"ttft": timings["ttft"], "total": total_ms},
            },
        )

        result = QueryResult(
            query_id=query_id,
            question=question,
            rewritten_question=rewritten,
            supplier_id=supplier,
            answer=answer,
            citations=citations,
            outcome=outcome,
            refusal_reason=refusal_reason,
            unsupported=unsupported,
            cached=False,
            timings=timings,
            prompt_version=self.generator.prompt.version,
            index_version=self.index_version,
            chunk_ids=[h.chunk_id for h in ctx.used],
        )
        if outcome in ("answered", "refused"):
            self.cache.set(key, self._to_cache(result))
        self._log(
            result,
            False,
            result.chunk_ids,
            [h.rerank_score if h.rerank_score is not None else h.score for h in ctx.used],
            [],
        )
        if outcome in ("answered", "refused"):
            self.sessions.append(session_id if session_id else query_id, question, answer, supplier)

    @classmethod
    def from_settings(cls, settings, conn) -> "QueryService":
        from clausecheck.rag.generator import Generator
        from clausecheck.rag.hybrid_retriever import HybridRetriever
        from clausecheck.rag.reranker import Reranker
        from clausecheck.rag.rewriter import Rewriter
        from clausecheck.rag.supplier_detector import SupplierDetector
        from clausecheck.services.sessions import SessionStore
        from clausecheck.store.cache import AnswerCache
        from clausecheck.store.query_log import QueryLog

        retriever = HybridRetriever.from_settings(settings, conn)
        reranker = Reranker(model_name=settings.rerank_model)
        generator = Generator.from_settings(settings)
        rewriter = Rewriter.from_settings(settings)
        supplier_detector = SupplierDetector.from_conn(conn, settings.supplier_match_min)
        sessions = SessionStore(settings.history_turns)
        cache = AnswerCache(conn, settings.cache_ttl_seconds)
        query_log = QueryLog(conn)
        return cls(
            rewriter=rewriter,
            supplier_detector=supplier_detector,
            retriever=retriever,
            reranker=reranker,
            generator=generator,
            sessions=sessions,
            cache=cache,
            query_log=query_log,
            threshold=settings.relevance_threshold,
            context_budget=settings.context_token_budget,
            index_version=settings.index_version,
            candidates=settings.rerank_candidates,
            top_n=settings.rerank_top_n,
        )
