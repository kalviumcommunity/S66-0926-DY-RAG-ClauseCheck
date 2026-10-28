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


@router.get("/insights/report")
def report(
    days: str = Query("7"), contract_id: str | None = None, container=Depends(get_container)
):
    """The service report. `days` is a number of days, or `all`."""
    window = None if days == "all" else max(1, int(days)) if days.isdigit() else 7
    return InsightsService(container.conn).report(days=window, contract_id=contract_id)
