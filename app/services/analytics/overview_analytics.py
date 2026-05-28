from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.analytics.unified_transaction_analytics import AnalyticsFilters, build_analytics_response


def get_overview_analytics(session: Session, filters: AnalyticsFilters) -> dict:
    return build_analytics_response(session, filters)

