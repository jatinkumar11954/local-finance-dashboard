from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import AuditLog, Benchmark, Transaction
from app.utils.amounts import MAX_REASONABLE_TRANSACTION_AMOUNT


BENCHMARK_CATEGORY_MAP = {
    "Rent": "Rent / Housing",
    "Home Loan EMI": "Debt repayment",
    "Other Loan EMI": "Debt repayment",
    "Groceries": "Groceries",
    "Food Delivery": "Food outside",
    "Restaurants": "Food outside",
    "Utilities": "Utilities",
    "Electricity": "Utilities",
    "Water": "Utilities",
    "Internet": "Internet / Mobile",
    "Mobile Recharge": "Internet / Mobile",
    "Fuel": "Transport",
    "Transport": "Transport",
    "Cab / Auto": "Transport",
    "Healthcare": "Healthcare",
    "Insurance": "Insurance",
    "Shopping": "Lifestyle / Shopping",
    "Entertainment": "Entertainment",
    "Investments": "Savings / Investments",
    "Mutual Funds / SIP": "Savings / Investments",
    "Credit Card Payment": "Debt repayment",
    "Loan Interest": "Debt repayment",
    "Loan Prepayment": "Debt repayment",
    "Loan Charges": "Debt repayment",
    "Credit Card Interest / Fees": "Debt repayment",
}


def map_transaction_category_to_benchmark(category: str) -> str | None:
    return BENCHMARK_CATEGORY_MAP.get(category)


def load_benchmark_seed_data(file_path: Path) -> list[dict[str, str | float]]:
    with file_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    rows: list[dict[str, str | float]] = []
    city = payload["city"]
    for profile_name, categories in payload["profiles"].items():
        for category_name, limits in categories.items():
            rows.append(
                {
                    "city": city,
                    "profile": profile_name,
                    "category": category_name,
                    "min_amount": limits["min"],
                    "max_amount": limits["max"],
                }
            )
    return rows


def seed_benchmarks(session: Session, benchmark_rows: list[dict[str, str | float]]) -> None:
    for row in benchmark_rows:
        session.add(
            Benchmark(
                city=str(row["city"]),
                profile=str(row["profile"]),
                category=str(row["category"]),
                min_amount=Decimal(str(row["min_amount"])),
                max_amount=Decimal(str(row["max_amount"])),
            )
        )


def list_benchmarks(session: Session, city: str = "Hyderabad", profile: str | None = None) -> list[Benchmark]:
    statement = select(Benchmark).where(Benchmark.city == city).order_by(Benchmark.profile, Benchmark.category)
    if profile:
        statement = statement.where(Benchmark.profile == profile)
    return session.scalars(statement).all()


def list_benchmark_profiles(session: Session, city: str = "Hyderabad") -> list[str]:
    rows = session.scalars(
        select(Benchmark.profile).where(Benchmark.city == city).distinct().order_by(Benchmark.profile)
    ).all()
    return list(rows)


def update_benchmark(
    session: Session,
    benchmark_id: int,
    min_amount: float | None = None,
    max_amount: float | None = None,
    is_active: bool | None = None,
) -> Benchmark:
    benchmark = session.get(Benchmark, benchmark_id)
    if benchmark is None:
        raise ValueError(f"Benchmark {benchmark_id} was not found.")

    changes: dict[str, float | bool] = {}
    if min_amount is not None:
        benchmark.min_amount = Decimal(str(min_amount))
        changes["min_amount"] = min_amount
    if max_amount is not None:
        benchmark.max_amount = Decimal(str(max_amount))
        changes["max_amount"] = max_amount
    if is_active is not None:
        benchmark.is_active = is_active
        changes["is_active"] = is_active

    session.add(
        AuditLog(
            action="benchmark_updated",
            entity_type="benchmark",
            entity_id=str(benchmark.id),
            details=changes,
        )
    )
    session.commit()
    session.refresh(benchmark)
    return benchmark


def compare_to_benchmarks(
    session: Session,
    start_date: date,
    end_date: date,
    city: str,
    profile: str,
) -> list[dict[str, float | str]]:
    benchmarks = session.scalars(
        select(Benchmark).where(
            Benchmark.city == city,
            Benchmark.profile == profile,
            Benchmark.is_active.is_(True),
        )
    ).all()
    if not benchmarks:
        return []

    spend_by_benchmark: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    transactions = session.scalars(
        select(Transaction).where(
            Transaction.date >= start_date,
            Transaction.date <= end_date,
            Transaction.transaction_type == "debit",
            Transaction.amount <= MAX_REASONABLE_TRANSACTION_AMOUNT,
            Transaction.is_excluded.is_(False),
        )
    ).all()

    for transaction in transactions:
        benchmark_category = map_transaction_category_to_benchmark(transaction.category)
        if benchmark_category:
            spend_by_benchmark[benchmark_category] += transaction.amount

    results: list[dict[str, float | str]] = []
    for benchmark in benchmarks:
        actual = spend_by_benchmark.get(benchmark.category, Decimal("0.00"))
        if actual < benchmark.min_amount:
            status = "below_range"
        elif actual > benchmark.max_amount:
            status = "above_range"
        else:
            status = "within_range"

        results.append(
            {
                "category": benchmark.category,
                "actual": float(actual),
                "benchmark_min": float(benchmark.min_amount),
                "benchmark_max": float(benchmark.max_amount),
                "status": status,
            }
        )
    return results
