from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.analytics import AnalyticsOverview
from app.services.analytics import calculate_overview


router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/overview", response_model=AnalyticsOverview)
def get_analytics_overview(
    start_date: date = Query(...),
    end_date: date = Query(...),
    benchmark_profile: str | None = Query(default=None),
    session: Session = Depends(get_db),
) -> AnalyticsOverview:
    return calculate_overview(
        session=session,
        start_date=start_date,
        end_date=end_date,
        benchmark_profile=benchmark_profile,
    )
