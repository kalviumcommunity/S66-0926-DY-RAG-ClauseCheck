from fastapi import APIRouter, Depends, Query

from clausecheck.api.deps import get_container
from clausecheck.services import contracts_service

router = APIRouter()


@router.get("/contracts")
def contracts(container=Depends(get_container)):
    """The register: each contract with its documents, latest effective date and last check."""
    return contracts_service.list_contracts(container.conn)


@router.get("/checks/recent")
def recent_checks(
    limit: int = Query(5, ge=1, le=50),
    contract_id: str | None = None,
    container=Depends(get_container),
):
    return contracts_service.recent_checks(container.conn, limit, contract_id)


@router.get("/contracts/{contract_id}/common-questions")
def common_questions(
    contract_id: str, limit: int = Query(5, ge=1, le=20), container=Depends(get_container)
):
    return contracts_service.common_questions(container.conn, contract_id, limit)
