from fastapi import APIRouter, Depends, Query

from clausecheck.api.deps import get_container
from clausecheck.services.insights_service import InsightsService

router = APIRouter()


@router.get("/insights/kpis")
def kpis(container=Depends(get_container)):
    return InsightsService(container.conn).kpis()


@router.get("/insights/charts")
def charts(days: int = Query(14), container=Depends(get_container)):
    return InsightsService(container.conn).charts(days=days)


@router.get("/insights/tables")
def tables(container=Depends(get_container)):
    return InsightsService(container.conn).tables()
