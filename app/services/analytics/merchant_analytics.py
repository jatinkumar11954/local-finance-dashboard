from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.analytics.unified_transaction_analytics import AnalyticsFilters, build_analytics_response


def get_merchant_analytics(session: Session, filters: AnalyticsFilters) -> dict:
    response = build_analytics_response(session, filters)
    response["summary"] = {"merchant_count": len(response["tables"]["merchant_breakdown"])}
    return response

