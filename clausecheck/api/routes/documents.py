import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from clausecheck.api.deps import get_container
from clausecheck.services.ingestion_service import DuplicateDocumentError

router = APIRouter()


@router.get("/documents")
def list_documents(
    supplier_id: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
    container=Depends(get_container),
):
    limit = min(max(limit, 1), 200)
    conn = container.conn
    sql = "SELECT * FROM documents WHERE 1=1"
    args: list[str | int] = []
    if supplier_id:
        sql += " AND supplier_id=?"
        args.append(supplier_id)
    if cursor:
        sql += " AND doc_id > ?"
        args.append(cursor)
    sql += " ORDER BY doc_id LIMIT ?"
    args.append(limit + 1)
    rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
    # remove path
    for r in rows:
        r.pop("path", None)
    next_cursor = None
    if len(rows) > limit:
        next_cursor = rows[limit - 1]["doc_id"]
        rows = rows[:limit]
    return {"items": rows, "next_cursor": next_cursor}


@router.post("/documents", status_code=202)
async def upload_document(
    file: UploadFile = File(...),
    supplier_id: str = Form(...),
    doc_type: str = Form("contract"),
    display_name: str = Form(""),
    effective_date: str = Form(""),
    amends: str = Form(""),
    container=Depends(get_container),
):
    settings = container.settings
    supplier_id = supplier_id.strip()
    if not supplier_id:
        # without a supplier the document cannot be searched on its own and is easily outranked
        return JSONResponse(status_code=422, content={"detail": "supplier_id is required"})
    effective_date = effective_date.strip()
    if effective_date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", effective_date):
        return JSONResponse(
            status_code=422, content={"detail": "effective_date must be written YYYY-MM-DD"}
        )
    content = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(content) > max_bytes:
        return JSONResponse(status_code=413, content={"detail": "file too large"})
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    allowed = [x.strip().lower() for x in settings.allowed_types.split(",")]
    if ext not in allowed:
        return JSONResponse(status_code=415, content={"detail": "unsupported file type"})
    service = container.upload_service
    if service is None:
        return JSONResponse(status_code=503, content={"detail": "upload service unavailable"})
    try:
        # only sent when given, so a service without display_name support keeps working
        extra = {"display_name": display_name.strip()} if display_name.strip() else {}
        if effective_date:
            extra["effective_date"] = effective_date
        if amends.strip():
            extra["amends"] = amends.strip()
        job_id = service.submit(file.filename or "upload", content, supplier_id, doc_type, **extra)
    except DuplicateDocumentError as exc:
        return JSONResponse(status_code=409, content={"detail": "duplicate", "doc_id": exc.doc_id})
    return {"job_id": job_id}


@router.get("/documents/jobs/{job_id}")
def job_status(job_id: str, container=Depends(get_container)):
    service = container.upload_service
    if service is None:
        raise HTTPException(status_code=404, detail="not found")
    job = service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="not found")
    return job
