from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from clausecheck.api.deps import get_container

router = APIRouter()


@router.get("/health")
def health(container=Depends(get_container)):
    settings = container.settings
    checks = {"sqlite": True, "vector_store": True, "llm_configured": True}
    documents = 0
    chunks = 0
    suppliers = 0
    try:
        row = container.conn.execute("SELECT COUNT(*) FROM documents").fetchone()
        documents = row[0] if row else 0
        chunks = container.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        suppliers = container.conn.execute("SELECT COUNT(*) FROM suppliers").fetchone()[0]
    except Exception:
        checks["sqlite"] = False
    try:
        if container.vector_count is not None:
            container.vector_count()
    except Exception:
        checks["vector_store"] = False
    try:
        if (
            not settings.gemini_api_key.get_secret_value()
            or not settings.groq_api_key.get_secret_value()
        ):
            checks["llm_configured"] = False
    except Exception:
        checks["llm_configured"] = False

    if not checks["sqlite"]:
        status = "down"
        code = 503
    elif chunks == 0 or not checks["vector_store"]:
        status = "degraded"
        code = 200
    else:
        status = "ok"
        code = 200

    body = {
        "status": status,
        "documents": documents,
        "chunks": chunks,
        "suppliers": suppliers,
        "index_version": settings.index_version,
        "checks": checks,
    }
    return JSONResponse(status_code=code, content=body)
