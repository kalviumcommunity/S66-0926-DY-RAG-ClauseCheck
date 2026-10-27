from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException

from clausecheck.api.deps import get_container
from clausecheck.store import sqlite as db

router = APIRouter()


@router.get("/suppliers")
def suppliers(container=Depends(get_container)):
    return db.list_suppliers(container.conn)


@router.get("/chunks/{chunk_id}")
def get_chunk(chunk_id: str, container=Depends(get_container)):
    chunk = db.get_chunk(container.conn, chunk_id)
    if chunk is None:
        raise HTTPException(status_code=404, detail="chunk not found")
    return asdict(chunk)
