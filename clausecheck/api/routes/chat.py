import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from clausecheck.api.deps import get_container
from clausecheck.api.schemas import ChatRequest, ChatResponse

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, container=Depends(get_container)):
    r = container.query_service.answer(
        req.question, session_id=req.session_id, supplier_filter=req.supplier_id
    )
    citations = [
        {
            "marker": c.marker,
            "chunk_id": c.chunk_id,
            "doc_id": c.doc_id,
            "page": c.page,
            "section": c.section,
            "clause_no": c.clause_no,
        }
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
    def gen():
        try:
            for ev in container.query_service.stream(
                req.question, session_id=req.session_id, supplier_filter=req.supplier_id
            ):
                yield f"event: {ev.type}\ndata: {json.dumps(ev.data)}\n\n"
        except Exception:
            yield f"event: error\ndata: {json.dumps({'message': 'Something went wrong. Please try again.'})}\n\n"
            yield f"event: done\ndata: {json.dumps({'outcome': 'error'})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
