from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class BreakdownItem(BaseModel):
    label: str
    amount: float


class TrendPoint(BaseModel):
    period: str
    income: float = 0.0
    expenses: float = 0.0


class DailySpendPoint(BaseModel):
    date: date
    amount: float


class BenchmarkComparisonItem(BaseModel):
    category: str
    actual: float
    benchmark_min: float
    benchmark_max: float
    status: str


class AnalyticsOverview(BaseModel):
    total_income: float
    total_expenses: float
    net_savings: float
    savings_rate: float
    upi_spend: float
    credit_card_spend: float
    transaction_count: int
    top_categories: list[BreakdownItem]
    top_merchants: list[BreakdownItem]
    monthly_trend: list[TrendPoint]
    daily_spend: list[DailySpendPoint]
    benchmark_comparison: list[BenchmarkComparisonItem]
