from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.analytics.unified_transaction_analytics import AnalyticsFilters, build_analytics_response


def get_budget_analytics(session: Session, filters: AnalyticsFilters) -> dict:
    response = build_analytics_response(session, filters)
    over_budget = [item for item in response["tables"]["budget_comparison"] if item["status"] == "over_benchmark"]
    response["summary"] = {"over_benchmark_count": len(over_budget)}
    return response

