import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from clausecheck.api.deps import get_container
from clausecheck.api.schemas import ChatRequest, ChatResponse, CitationOut

router = APIRouter()

WRONG_CONTRACT = "This conversation belongs to another contract. Start a new conversation."


def _check_scope(container, req: ChatRequest) -> None:
    """A conversation stays on the contract of its first answer: 409 if the request moves it."""
    bound = container.sessions.scope_of(req.session_id)
    if bound is not None and req.supplier_id is not None and req.supplier_id != bound:
        raise HTTPException(status_code=409, detail=WRONG_CONTRACT)


def _scope_kwargs(req: ChatRequest) -> dict:
    """`strict_scope` is only passed when set, so a query service without it keeps working."""
    return {"strict_scope": True} if req.strict_scope else {}


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, container=Depends(get_container)):
    _check_scope(container, req)
    r = container.query_service.answer(
        req.question,
        session_id=req.session_id,
        supplier_filter=req.supplier_id,
        **_scope_kwargs(req),
    )
    citations = [
        CitationOut(
            marker=c.marker,
            chunk_id=c.chunk_id,
            doc_id=c.doc_id,
            page=c.page,
            section=c.section,
            clause_no=c.clause_no,
        )
        for c in r.citations
    ]
    return ChatResponse(
        query_id=r.query_id,
        answer=r.answer,
        outcome=r.outcome,
        refusal_reason=r.refusal_reason,
        supplier_id=r.supplier_id,
        cached=r.cached,
        unsupported=r.unsupported,
        timings=r.timings,
        citations=citations,
    )


@router.post("/chat/stream")
def chat_stream(req: ChatRequest, container=Depends(get_container)):
    _check_scope(container, req)  # before streaming starts, while a status code can still be sent

    def gen():
        try:
            for ev in container.query_service.stream(
                req.question,
                session_id=req.session_id,
                supplier_filter=req.supplier_id,
                **_scope_kwargs(req),
            ):
                yield f"event: {ev.type}\ndata: {json.dumps(ev.data)}\n\n"
        except Exception:
            yield f"event: error\ndata: {json.dumps({'message': 'Something went wrong. Please try again.'})}\n\n"
            yield f"event: done\ndata: {json.dumps({'outcome': 'error'})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
