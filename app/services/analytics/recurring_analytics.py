from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.analytics.unified_transaction_analytics import AnalyticsFilters, build_analytics_response


def get_recurring_analytics(session: Session, filters: AnalyticsFilters) -> dict:
    response = build_analytics_response(session, filters)
    response["summary"] = {"recurring_count": len(response["tables"]["recurring"])}
    return response

