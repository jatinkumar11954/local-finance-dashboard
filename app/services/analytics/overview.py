from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.entities import Transaction
from app.schemas.analytics import (
    AnalyticsOverview,
    BenchmarkComparisonItem,
    BreakdownItem,
    DailySpendPoint,
    TrendPoint,
)
from app.services.benchmarks import compare_to_benchmarks
from app.utils.amounts import MAX_REASONABLE_TRANSACTION_AMOUNT


def _to_dataframe(transactions: list[Transaction]) -> pd.DataFrame:
    if not transactions:
        return pd.DataFrame(
            columns=[
                "date",
                "amount",
                "transaction_type",
                "payment_mode",
                "category",
                "merchant_name",
                "is_excluded",
            ]
        )

    return pd.DataFrame.from_records(
        [
            {
                "date": transaction.date,
                "amount": float(transaction.amount),
                "transaction_type": transaction.transaction_type,
                "payment_mode": transaction.payment_mode,
                "category": transaction.category,
                "merchant_name": transaction.merchant_name or "Unknown",
                "is_excluded": transaction.is_excluded,
            }
            for transaction in transactions
        ]
    )


def calculate_overview(
    session: Session,
    start_date: date,
    end_date: date,
    benchmark_profile: str | None = None,
) -> AnalyticsOverview:
    transactions = session.scalars(
        select(Transaction).where(
            Transaction.date >= start_date,
            Transaction.date <= end_date,
            Transaction.amount <= MAX_REASONABLE_TRANSACTION_AMOUNT,
        )
    ).all()
    dataframe = _to_dataframe(transactions)
    if dataframe.empty:
        return AnalyticsOverview(
            total_income=0.0,
            total_expenses=0.0,
            net_savings=0.0,
            savings_rate=0.0,
            upi_spend=0.0,
            credit_card_spend=0.0,
            transaction_count=0,
            top_categories=[],
            top_merchants=[],
            monthly_trend=[],
            daily_spend=[],
            benchmark_comparison=[],
        )

    dataframe["date"] = pd.to_datetime(dataframe["date"])
    dataframe = dataframe[dataframe["is_excluded"] == False]  # noqa: E712

    income = dataframe.loc[dataframe["transaction_type"] == "credit", "amount"].sum()
    expenses = dataframe.loc[dataframe["transaction_type"] == "debit", "amount"].sum()
    upi_spend = dataframe.loc[
        (dataframe["transaction_type"] == "debit") & (dataframe["payment_mode"] == "UPI"),
        "amount",
    ].sum()
    credit_card_spend = dataframe.loc[
        (dataframe["transaction_type"] == "debit") & (dataframe["payment_mode"] == "CARD"),
        "amount",
    ].sum()

    top_category_series = (
        dataframe.loc[dataframe["transaction_type"] == "debit"]
        .groupby("category")["amount"]
        .sum()
        .sort_values(ascending=False)
        .head(5)
    )
    top_merchant_series = (
        dataframe.loc[dataframe["transaction_type"] == "debit"]
        .groupby("merchant_name")["amount"]
        .sum()
        .sort_values(ascending=False)
        .head(5)
    )

    monthly_group = dataframe.assign(period=dataframe["date"].dt.to_period("M").astype(str)).groupby(
        ["period", "transaction_type"]
    )["amount"].sum()
    monthly_lookup = {}
    for (period, transaction_type), amount in monthly_group.items():
        monthly_lookup.setdefault(period, {"period": period, "income": 0.0, "expenses": 0.0})
        if transaction_type == "credit":
            monthly_lookup[period]["income"] = float(amount)
        else:
            monthly_lookup[period]["expenses"] = float(amount)

    daily_spend_series = (
        dataframe.loc[dataframe["transaction_type"] == "debit"]
        .groupby(dataframe["date"].dt.date)["amount"]
        .sum()
    )

    settings = get_settings()
    benchmark_comparison = compare_to_benchmarks(
        session=session,
        start_date=start_date,
        end_date=end_date,
        city=settings.default_benchmark_city,
        profile=benchmark_profile or settings.default_benchmark_profile,
    )

    return AnalyticsOverview(
        total_income=round(float(income), 2),
        total_expenses=round(float(expenses), 2),
        net_savings=round(float(income - expenses), 2),
        savings_rate=round(float(((income - expenses) / income) * 100), 2) if income else 0.0,
        upi_spend=round(float(upi_spend), 2),
        credit_card_spend=round(float(credit_card_spend), 2),
        transaction_count=int(len(dataframe)),
        top_categories=[
            BreakdownItem(label=label, amount=round(float(amount), 2))
            for label, amount in top_category_series.items()
        ],
        top_merchants=[
            BreakdownItem(label=label, amount=round(float(amount), 2))
            for label, amount in top_merchant_series.items()
        ],
        monthly_trend=[
            TrendPoint(**monthly_lookup[key]) for key in sorted(monthly_lookup.keys())
        ],
        daily_spend=[
            DailySpendPoint(date=day, amount=round(float(amount), 2))
            for day, amount in daily_spend_series.items()
        ],
        benchmark_comparison=[
            BenchmarkComparisonItem(**item) for item in benchmark_comparison
        ],
    )
