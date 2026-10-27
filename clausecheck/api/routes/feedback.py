from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from clausecheck.api.deps import get_container

router = APIRouter()


class FeedbackRequest(BaseModel):
    query_id: str
    rating: str = Field(pattern="^(up|down)$")
    comment: str | None = None


@router.post("/feedback", status_code=204)
def feedback(req: FeedbackRequest, container=Depends(get_container)):
    if not container.query_log.exists(req.query_id):
        raise HTTPException(status_code=404, detail="query not found")
    container.query_log.add_feedback(req.query_id, req.rating, req.comment)
    return None
