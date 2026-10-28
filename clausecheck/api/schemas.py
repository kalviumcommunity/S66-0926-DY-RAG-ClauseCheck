from typing import Any

from pydantic import BaseModel, Field


class CitationOut(BaseModel):
    marker: str
    chunk_id: str
    doc_id: str | None = None
    page: int | None = None
    section: str | None = None
    clause_no: str | None = None


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    session_id: str | None = None
    supplier_id: str | None = None
    # True: the conversation is about this one contract; a question naming another is refused
    strict_scope: bool = False
    # True: the stream also carries `step` events and a `checks` event (the new app uses them)
    detail: bool = False


class ChatResponse(BaseModel):
    query_id: str
    answer: str
    outcome: str
    refusal_reason: str | None = None
    supplier_id: str | None = None
    cached: bool = False
    unsupported: bool = False
    timings: dict[str, Any] = {}
    citations: list[CitationOut] = []
