import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from clausecheck.llm.client import LLMError
from clausecheck.rag.checks import check_answer, clause_pages, terms_found
from clausecheck.rag.citation_validator import validate
from clausecheck.rag.context_builder import build_context
from clausecheck.rag.generator import REFUSAL_TEXT
from clausecheck.rag.hybrid_retriever import CLAUSE_REF_RE
from clausecheck.rag.relevance_gate import check as gate_check
from clausecheck.services.sessions import SessionStore
from clausecheck.store import sqlite as db
from clausecheck.store.cache import AnswerCache, make_key
from clausecheck.store.query_log import QueryLog

OTHER_CONTRACT = "other_contract"  # refusal reason: the question names a different contract

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
    conn: Any = None  # for document titles and amendment links in the checks

    def _new_id(self) -> str:
        return uuid.uuid4().hex

    def _doc_info(self, doc_id: str) -> dict | None:
        if self.conn is None or not doc_id:
            return None
        doc = db.get_document(self.conn, doc_id)
        return dict(doc) if doc else None

    def _amended_clauses(self, doc_id: str) -> dict[str, str]:
        """`{clause number: amendment title}` for the clauses that amendments of `doc_id` name."""
        if self.conn is None:
            return {}
        out: dict[str, str] = {}
        children = self.conn.execute(
            "SELECT doc_id, title FROM documents WHERE parent_doc_id=?", (doc_id,)
        ).fetchall()
        for child in children:
            for row in self.conn.execute(
                "SELECT text FROM chunks WHERE doc_id=?", (child["doc_id"],)
            ).fetchall():
                for ref in set(CLAUSE_REF_RE.findall(row["text"] or "")):
                    out.setdefault(ref, child["title"] or child["doc_id"])
        return out

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
        self,
        result: QueryResult,
        cached: bool,
        chunk_ids: list[str],
        scores: list,
        sources: list,
        error: str | None = None,
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
            # the cause (`groq: RateLimitError 429; gemini: ClientError 404`), else the generic text
            record["error"] = error or result.answer
        self.query_log.log(record)

    def _other_contract_reply(self, scope_id: str, rewritten: str) -> str | None:
        """The refusal text if `rewritten` names a contract other than `scope_id`, else None.

        A conversation fixed to one contract must not answer about another one: the search would
        be limited to this contract and the answer would be presented as if it were about the
        contract the user named.
        """
        other = self.supplier_detector.other_supplier(rewritten, scope_id)
        if other is None:
            return None
        return (
            f"This conversation is about {self.supplier_detector.display_name(scope_id)}. "
            f"To ask about {self.supplier_detector.display_name(other)}, open that contract "
            "and ask there."
        )

    def _other_contract_result(
        self, query_id: str, question: str, rewritten: str, scope_id: str, message: str, t0: float
    ) -> QueryResult:
        total_ms = round((time.perf_counter() - t0) * 1000, 2)
        result = QueryResult(
            query_id=query_id,
            question=question,
            rewritten_question=rewritten,
            supplier_id=scope_id,
            answer=message,
            citations=[],
            outcome="refused",
            refusal_reason=OTHER_CONTRACT,
            unsupported=False,
            cached=False,
            timings={"total": total_ms},
            prompt_version=self.generator.prompt.version,
            index_version=self.index_version,
            chunk_ids=[],
        )
        self._log(result, False, [], [], [])  # logged, but never cached or added to the history
        return result

    def answer(
        self,
        question: str,
        session_id: str | None = None,
        supplier_filter: str | None = None,
        strict_scope: bool = False,
    ) -> QueryResult:
        query_id = self._new_id()
        t0 = time.perf_counter()
        session = self.sessions.get_or_create(session_id)
        rewritten = self.rewriter.rewrite(question, session.turns)
        if strict_scope and supplier_filter is not None:
            message = self._other_contract_reply(supplier_filter, rewritten)
            if message is not None:
                return self._other_contract_result(
                    query_id, question, rewritten, supplier_filter, message, t0
                )
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
            hits = self.reranker.rerank(
                self.supplier_detector.strip_names(rewritten, supplier), hits, self.top_n
            )
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
        error_reason: str | None = None

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
            except LLMError as exc:
                error_reason = "; ".join(exc.reasons) or None
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

        self._log(result, False, chunk_ids, scores, [], error=error_reason)
        if outcome in ("answered", "refused"):
            self.sessions.append(session_id if session_id else query_id, question, answer, supplier)

        return result

    def stream(
        self,
        question: str,
        session_id: str | None = None,
        supplier_filter: str | None = None,
        strict_scope: bool = False,
        detail: bool = False,
    ) -> Iterator[StreamEvent]:
        """Stream the answer as events. With `detail`, also stream `step` events (what the
        pipeline is doing) and a `checks` event (what was verified); the plain order is unchanged.
        """
        query_id = self._new_id()
        t0 = time.perf_counter()
        session = self.sessions.get_or_create(session_id)
        rewritten = self.rewriter.rewrite(question, session.turns)
        if strict_scope and supplier_filter is not None:
            message = self._other_contract_reply(supplier_filter, rewritten)
            if message is not None:
                result = self._other_contract_result(
                    query_id, question, rewritten, supplier_filter, message, t0
                )
                yield StreamEvent(
                    "meta",
                    {
                        "query_id": query_id,
                        "supplier_id": supplier_filter,
                        "rewritten_question": rewritten,
                    },
                )
                yield StreamEvent("sources", {"sources": []})
                yield StreamEvent("token", {"text": message})
                yield StreamEvent("citations", {"citations": [], "unsupported": False})
                total_ms = result.timings["total"]
                yield StreamEvent(
                    "done",
                    {
                        "outcome": "refused",
                        "refusal_reason": OTHER_CONTRACT,
                        "cached": False,
                        "timings": {"ttft": total_ms, "total": total_ms},
                    },
                )
                return
        supplier = (
            supplier_filter
            if supplier_filter is not None
            else self.supplier_detector.detect(rewritten, previous=session.supplier_id)
        )

        key = make_key(rewritten, supplier, self.index_version, self.generator.prompt.version)
        cached_val = self.cache.get(key)
        if (
            cached_val is not None
            and detail
            and cached_val.get("outcome", "answered") == "answered"
            and "checks" not in cached_val
        ):
            cached_val = None  # cached by a client that did not ask for checks: answer it again
        if cached_val is not None:
            yield StreamEvent(
                "meta",
                {"query_id": query_id, "supplier_id": supplier, "rewritten_question": rewritten},
            )
            if detail:
                cached_sources = cached_val.get("sources", [])
                yield StreamEvent(
                    "step",
                    {
                        "id": "found",
                        "state": "done",
                        "clauses": len(cached_sources),
                        "documents": len({c.get("doc_id") for c in cached_sources}),
                        "ms": 0.0,
                        "cached": True,
                    },
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
            if detail and cached_val.get("checks"):
                yield StreamEvent("checks", cached_val["checks"])
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
            hits = self.reranker.rerank(
                self.supplier_detector.strip_names(rewritten, supplier), hits, self.top_n
            )
        except Exception:
            pass
        rerank_ms = (time.perf_counter() - t_rerank) * 1000

        gate = gate_check(hits, self.threshold, supplier_required=False, supplier_id=supplier)

        yield StreamEvent(
            "meta", {"query_id": query_id, "supplier_id": supplier, "rewritten_question": rewritten}
        )
        if detail:
            yield StreamEvent(
                "step",
                {
                    "id": "found",
                    "state": "done",
                    "clauses": len(hits),
                    "documents": len({(h.metadata or {}).get("doc_id") for h in hits}),
                    "ms": round(retrieve_ms + rerank_ms, 1),
                },
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
        if detail:
            yield StreamEvent("step", {"id": "write", "state": "active"})

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
        except LLMError as exc:
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
            self._log(result, False, result.chunk_ids, [], [], error="; ".join(exc.reasons) or None)
            return

        if detail:
            yield StreamEvent("step", {"id": "write", "state": "done", "ms": round(generate_ms, 1)})
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

        checks_payload = None
        if detail and outcome == "answered":
            yield StreamEvent("step", {"id": "check", "state": "active"})
            checks = check_answer(answer, ctx.marker_map, self._doc_info, dropped=len(vr.dropped))
            cited = [(c.marker, ctx.marker_map[c.marker]) for c in citations]
            checks_payload = {
                **checks.to_dict(),
                "answer": answer,  # the validated text, with citation markers normalised
                "terms": terms_found(cited, self._doc_info, self._amended_clauses),
                "clauses": clause_pages(cited, checks, self._doc_info),
            }
            yield StreamEvent("checks", checks_payload)
            yield StreamEvent("step", {"id": "check", "state": "done"})
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
            payload = self._to_cache(result)
            if checks_payload is not None:
                payload["checks"] = checks_payload  # so a cached answer can show its seal too
            self.cache.set(key, payload)
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
            conn=conn,
        )
