from fastapi import APIRouter, Depends

from clausecheck.api.deps import get_container

router = APIRouter()


@router.post("/sessions", status_code=201)
def create_session(container=Depends(get_container)):
    sid = container.sessions.new()
    return {"session_id": sid}
