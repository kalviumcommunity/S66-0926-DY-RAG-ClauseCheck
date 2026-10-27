import pytest
from fastapi.testclient import TestClient

from clausecheck.api.container import AppContainer
from clausecheck.api.main import create_app
from clausecheck.core.config import Settings
from clausecheck.rag.citation_validator import Citation
from clausecheck.services.query_service import QueryResult, StreamEvent
from clausecheck.services.sessions import SessionStore
from clausecheck.store import sqlite as db
from clausecheck.store.query_log import QueryLog
from tests.helpers import make_chunk

CITATION = Citation("C1", "doc-a:p2:2_1", "doc-a", 2, "2. Payment", "2.1")


def result(outcome="answered", answer="Payment is due Net 45 days [C1].", query_id="q-1"):
    return QueryResult(
        query_id=query_id,
        question="q",
        rewritten_question="q",
        supplier_id="S-ACME",
        answer=answer,
        citations=[CITATION] if outcome == "answered" else [],
        outcome=outcome,
        refusal_reason=None if outcome == "answered" else "low_score",
        unsupported=False,
        cached=False,
        timings={"total": 120.0},
        prompt_version="v1",
        index_version="v1",
        chunk_ids=["doc-a:p2:2_1"] if outcome == "answered" else [],
    )


class FakeQueryService:
    def __init__(self, query_log):
        self.query_log = query_log
        self.fail_with = None

    def answer(self, question, session_id=None, supplier_filter=None):
        if self.fail_with:
            raise self.fail_with
        r = result("refused", "I couldn't find this.") if "refuse" in question else result()
        self.query_log.log(
            {
                "query_id": r.query_id,
                "created_at": "2026-11-20T10:00:00",
                "question": question,
                "outcome": r.outcome,
                "latency_ms": 120.0,
                "ttft_ms": 800.0,
            }
        )
        return r

    def stream(self, question, session_id=None, supplier_filter=None):
        if self.fail_with:
            raise self.fail_with
        yield StreamEvent(
            "meta", {"query_id": "q-2", "supplier_id": "S-ACME", "rewritten_question": question}
        )
        yield StreamEvent("sources", {"sources": [{"marker": "C1", "chunk_id": "doc-a:p2:2_1"}]})
        yield StreamEvent("token", {"text": "Payment is due "})
        yield StreamEvent("token", {"text": "Net 45 days [C1]."})
        yield StreamEvent(
            "citations",
            {"citations": [{"marker": "C1", "chunk_id": "doc-a:p2:2_1"}], "unsupported": False},
        )
        yield StreamEvent(
            "done",
            {
                "outcome": "answered",
                "refusal_reason": None,
                "cached": False,
                "timings": {"ttft": 400.0},
            },
        )


@pytest.fixture
def container(tmp_path):
    settings = Settings(_env_file=None, sqlite_path=tmp_path / "api.db")
    conn = db.connect(settings.sqlite_path)
    db.init_db(conn)
    db.upsert_supplier(conn, "S-ACME", "Acme Corp", ["Acme"])
    db.upsert_document(
        conn,
        {
            "doc_id": "doc-a",
            "supplier_id": "S-ACME",
            "source": "cuad",
            "doc_type": "contract",
            "format": "pdf",
            "path": "data/raw/a.pdf",
            "title": "A",
        },
    )
    db.replace_chunks(conn, "doc-a", [make_chunk(chunk_id="doc-a:p2:2_1", doc_id="doc-a", page=2)])
    query_log = QueryLog(conn)
    return AppContainer(
        settings=settings,
        conn=conn,
        query_service=FakeQueryService(query_log),
        sessions=SessionStore(3),
        query_log=query_log,
        vector_count=lambda: 1,
    )


@pytest.fixture
def client(container):
    return TestClient(create_app(container), raise_server_exceptions=False)


def parse_sse(text: str) -> list[tuple[str, dict]]:
    import json

    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        events.append((lines["event"], json.loads(lines["data"])))
    return events
