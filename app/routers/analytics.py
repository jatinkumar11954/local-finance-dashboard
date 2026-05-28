from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.analytics import AnalyticsOverview
from app.services.analytics import (
    AnalyticsFilters,
    calculate_overview,
    get_anomaly_analytics,
    get_bank_analytics,
    get_budget_analytics,
    get_cashflow_analytics,
    get_category_analytics,
    get_credit_card_analytics,
    get_merchant_analytics,
    get_overview_analytics,
    get_recurring_analytics,
    get_upi_analytics,
)
from app.services.analytics.unified_transaction_analytics import build_analytics_response


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


def _filters(
    start_date: date | None = None,
    end_date: date | None = None,
    source_type: str | None = None,
    account_id: int | None = None,
    card_id: int | None = None,
    category: str | None = None,
    merchant: str | None = None,
    transaction_channel: str | None = None,
    include_internal_transfers: bool = False,
    include_credit_card_bill_payments: bool = False,
    include_excluded: bool = False,
    month: int | None = None,
    year: int | None = None,
    benchmark_profile: str | None = None,
) -> AnalyticsFilters:
    return AnalyticsFilters(
        start_date=start_date,
        end_date=end_date,
        source_type=source_type,
        account_id=account_id,
        card_id=card_id,
        category=category,
        merchant=merchant,
        transaction_channel=transaction_channel,
        include_internal_transfers=include_internal_transfers,
        include_credit_card_bill_payments=include_credit_card_bill_payments,
        include_excluded=include_excluded,
        month=month,
        year=year,
        benchmark_profile=benchmark_profile,
    )


def _query_filters(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    source_type: str | None = Query(default="all_sources"),
    account_id: int | None = Query(default=None),
    card_id: int | None = Query(default=None),
    category: str | None = Query(default=None),
    merchant: str | None = Query(default=None),
    transaction_channel: str | None = Query(default=None),
    include_internal_transfers: bool = Query(default=False),
    include_credit_card_bill_payments: bool = Query(default=False),
    include_excluded: bool = Query(default=False),
    month: int | None = Query(default=None),
    year: int | None = Query(default=None),
    benchmark_profile: str | None = Query(default=None),
) -> AnalyticsFilters:
    return _filters(
        start_date=start_date,
        end_date=end_date,
        source_type=source_type,
        account_id=account_id,
        card_id=card_id,
        category=category,
        merchant=merchant,
        transaction_channel=transaction_channel,
        include_internal_transfers=include_internal_transfers,
        include_credit_card_bill_payments=include_credit_card_bill_payments,
        include_excluded=include_excluded,
        month=month,
        year=year,
        benchmark_profile=benchmark_profile,
    )


@router.get("/summary")
def get_summary(filters: AnalyticsFilters = Depends(_query_filters), session: Session = Depends(get_db)) -> dict:
    return get_overview_analytics(session, filters)


@router.get("/monthly-trend")
def get_monthly_trend(filters: AnalyticsFilters = Depends(_query_filters), session: Session = Depends(get_db)) -> dict:
    return get_overview_analytics(session, filters)


@router.get("/category-breakdown")
def get_category_breakdown(filters: AnalyticsFilters = Depends(_query_filters), session: Session = Depends(get_db)) -> dict:
    return get_category_analytics(session, filters)


@router.get("/merchant-breakdown")
def get_merchant_breakdown(filters: AnalyticsFilters = Depends(_query_filters), session: Session = Depends(get_db)) -> dict:
    return get_merchant_analytics(session, filters)


@router.get("/daily-spend")
def get_daily_spend(filters: AnalyticsFilters = Depends(_query_filters), session: Session = Depends(get_db)) -> dict:
    return get_overview_analytics(session, filters)


@router.get("/cashflow")
def get_cashflow(filters: AnalyticsFilters = Depends(_query_filters), session: Session = Depends(get_db)) -> dict:
    return get_cashflow_analytics(session, filters)


@router.get("/recurring")
def get_recurring(filters: AnalyticsFilters = Depends(_query_filters), session: Session = Depends(get_db)) -> dict:
    return get_recurring_analytics(session, filters)


@router.get("/anomalies")
def get_anomalies(filters: AnalyticsFilters = Depends(_query_filters), session: Session = Depends(get_db)) -> dict:
    return get_anomaly_analytics(session, filters)


@router.get("/budget-comparison")
def get_budget_comparison(filters: AnalyticsFilters = Depends(_query_filters), session: Session = Depends(get_db)) -> dict:
    return get_budget_analytics(session, filters)


@router.get("/source-comparison")
def get_source_comparison(filters: AnalyticsFilters = Depends(_query_filters), session: Session = Depends(get_db)) -> dict:
    return build_analytics_response(session, filters)


def _bank_query_filters(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    source_type: str | None = Query(default="bank_statement"),
    account_id: int | None = Query(default=None),
    card_id: int | None = Query(default=None),
    category: str | None = Query(default=None),
    merchant: str | None = Query(default=None),
    transaction_channel: str | None = Query(default=None),
    include_internal_transfers: bool = Query(default=True),
    include_credit_card_bill_payments: bool = Query(default=True),
    include_excluded: bool = Query(default=False),
    month: int | None = Query(default=None),
    year: int | None = Query(default=None),
    benchmark_profile: str | None = Query(default=None),
) -> AnalyticsFilters:
    return _filters(
        start_date=start_date,
        end_date=end_date,
        source_type=source_type,
        account_id=account_id,
        card_id=card_id,
        category=category,
        merchant=merchant,
        transaction_channel=transaction_channel,
        include_internal_transfers=include_internal_transfers,
        include_credit_card_bill_payments=include_credit_card_bill_payments,
        include_excluded=include_excluded,
        month=month,
        year=year,
        benchmark_profile=benchmark_profile,
    )


@router.get("/bank/summary")
@router.get("/bank/monthly")
@router.get("/bank/income-expense")
@router.get("/bank/upi")
@router.get("/bank/internal-transfers")
@router.get("/bank/credit-card-payments")
@router.get("/bank/loan-payments")
def get_bank_specific(filters: AnalyticsFilters = Depends(_bank_query_filters), session: Session = Depends(get_db)) -> dict:
    return get_bank_analytics(session, filters)


@router.get("/credit-cards/summary")
@router.get("/credit-cards/monthly")
@router.get("/credit-cards/card-wise")
@router.get("/credit-cards/emi")
@router.get("/credit-cards/fees-interest-gst")
@router.get("/credit-cards/upi-only")
@router.get("/credit-cards/payments-vs-spend")
def get_credit_card_specific(filters: AnalyticsFilters = Depends(_query_filters), session: Session = Depends(get_db)) -> dict:
    return get_credit_card_analytics(session, filters)


def _upi_query_filters(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    source_type: str | None = Query(default="all_sources"),
    account_id: int | None = Query(default=None),
    card_id: int | None = Query(default=None),
    category: str | None = Query(default=None),
    merchant: str | None = Query(default=None),
    include_internal_transfers: bool = Query(default=True),
    include_credit_card_bill_payments: bool = Query(default=False),
    include_excluded: bool = Query(default=False),
    month: int | None = Query(default=None),
    year: int | None = Query(default=None),
    benchmark_profile: str | None = Query(default=None),
) -> AnalyticsFilters:
    return _filters(
        start_date=start_date,
        end_date=end_date,
        source_type=source_type,
        account_id=account_id,
        card_id=card_id,
        category=category,
        merchant=merchant,
        transaction_channel="upi",
        include_internal_transfers=include_internal_transfers,
        include_credit_card_bill_payments=include_credit_card_bill_payments,
        include_excluded=include_excluded,
        month=month,
        year=year,
        benchmark_profile=benchmark_profile,
    )


@router.get("/upi/summary")
@router.get("/upi/daily")
@router.get("/upi/monthly")
@router.get("/upi/receivers")
@router.get("/upi/categories")
@router.get("/upi/repeated-payments")
@router.get("/upi/small-frequent-payments")
@router.get("/upi/person-vs-merchant")
def get_upi_specific(filters: AnalyticsFilters = Depends(_upi_query_filters), session: Session = Depends(get_db)) -> dict:
    return get_upi_analytics(session, filters)
