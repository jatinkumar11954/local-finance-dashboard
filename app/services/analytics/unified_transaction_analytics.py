from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.entities import (
    Benchmark,
    CreditCard,
    CreditCardTransaction,
    Document,
    LoanMonthlyLedger,
    LoanTransaction,
    Transaction,
)
from app.services.categorization.rules import UPI_PROVIDER_TOKENS, normalize_text
from app.utils.amounts import MAX_REASONABLE_TRANSACTION_AMOUNT


TWOPLACES = Decimal("0.01")
SOURCE_TYPE_ALIASES = {
    "upi_statement": "upi_export",
    "upi_export": "upi_export",
    "bank_statement": "bank_statement",
    "credit_card_statement": "credit_card_statement",
    "loan_statement": "loan_statement",
    "manual": "manual",
    "unknown": "manual",
    "all_sources": "all_sources",
    "": "all_sources",
}
UPI_TOKENS = {
    "upi",
    "bhim",
    "gpay",
    "google pay",
    "phonepe",
    "paytm",
    "cred upi",
    "rupay upi",
    "qr",
    "vpa",
    "@ybl",
    "@okaxis",
    "@oksbi",
    "@okhdfcbank",
    "@paytm",
    "@ibl",
    "@axl",
}
CARD_PAYMENT_TOKENS = {"credit card payment", "cc payment", "card payment", "autopay card", "card autopay"}
INTERNAL_TRANSFER_CATEGORIES = {"UPI Transfers", "Family / Personal Transfers"}
LOAN_EMI_CATEGORIES = {"Home Loan EMI", "Other Loan EMI", "Loan EMI"}
LOAN_PREPAYMENT_CATEGORIES = {"Loan Prepayment"}
REFUND_TOKENS = {"refund", "reversal", "reversed"}
CASHBACK_TOKENS = {"cashback", "reward", "cash back"}
FEE_TOKENS = {"charge", "fee", "interest", "penal", "late", "gst", "finance"}


@dataclass(frozen=True)
class AnalyticsFilters:
    start_date: date | None = None
    end_date: date | None = None
    source_type: str | None = None
    account_id: int | None = None
    card_id: int | None = None
    category: str | None = None
    merchant: str | None = None
    transaction_channel: str | None = None
    include_internal_transfers: bool = False
    include_credit_card_bill_payments: bool = False
    include_excluded: bool = False
    month: int | None = None
    year: int | None = None
    benchmark_profile: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "source_type": normalize_source_type(self.source_type),
            "account_id": self.account_id,
            "card_id": self.card_id,
            "category": self.category,
            "merchant": self.merchant,
            "transaction_channel": self.transaction_channel,
            "include_internal_transfers": self.include_internal_transfers,
            "include_credit_card_bill_payments": self.include_credit_card_bill_payments,
            "include_excluded": self.include_excluded,
            "month": self.month,
            "year": self.year,
            "benchmark_profile": self.benchmark_profile,
        }


def normalize_source_type(value: str | None) -> str:
    normalized = normalize_text(value).replace(" ", "_").replace("-", "_")
    return SOURCE_TYPE_ALIASES.get(normalized, normalized or "all_sources")


def money(value: Decimal | float | int | str | None) -> Decimal:
    if value is None:
        return Decimal("0.00")
    return Decimal(str(value)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def money_float(value: Decimal | float | int | str | None) -> float:
    return float(money(value))


def build_unified_rows(session: Session, filters: AnalyticsFilters | None = None) -> list[dict[str, Any]]:
    filters = filters or AnalyticsFilters()
    statement = select(Transaction, Document.document_type, Document.filename).outerjoin(
        Document,
        Transaction.source_document_id == Document.id,
    )
    if filters.start_date:
        statement = statement.where(Transaction.date >= filters.start_date)
    if filters.end_date:
        statement = statement.where(Transaction.date <= filters.end_date)
    if filters.year:
        statement = statement.where(Transaction.date >= date(filters.year, 1, 1), Transaction.date <= date(filters.year, 12, 31))
    if filters.month and filters.year:
        month_start = date(filters.year, filters.month, 1)
        month_end = date(filters.year + (filters.month // 12), (filters.month % 12) + 1, 1) - timedelta(days=1)
        statement = statement.where(Transaction.date >= month_start, Transaction.date <= month_end)
    if filters.account_id:
        statement = statement.where(Transaction.account_id == filters.account_id)
    if filters.category:
        statement = statement.where(Transaction.category == filters.category)
    if filters.merchant:
        like_value = f"%{filters.merchant}%"
        statement = statement.where(Transaction.merchant_name.ilike(like_value))
    if not filters.include_excluded:
        statement = statement.where(Transaction.is_excluded.is_(False))
    statement = statement.where(Transaction.amount <= MAX_REASONABLE_TRANSACTION_AMOUNT)
    rows = session.execute(statement.order_by(Transaction.date.asc(), Transaction.id.asc())).all()

    credit_card_map = _credit_card_lookup(session)
    loan_map = _loan_transaction_lookup(session)
    output_rows = [
        _build_unified_row(
            transaction=transaction,
            document_type=document_type,
            document_filename=document_filename,
            credit_card_info=credit_card_map.get(transaction.id),
            loan_info=loan_map.get(transaction.id),
        )
        for transaction, document_type, document_filename in rows
    ]

    source_type = normalize_source_type(filters.source_type)
    if source_type != "all_sources":
        output_rows = [row for row in output_rows if row["source_type"] == source_type]
    if filters.card_id:
        output_rows = [row for row in output_rows if row["source_card_id"] == filters.card_id]
    if filters.transaction_channel:
        output_rows = [row for row in output_rows if row["transaction_channel"] == filters.transaction_channel]
    if not filters.include_internal_transfers:
        output_rows = [row for row in output_rows if not row["is_internal_transfer"]]
    if not filters.include_credit_card_bill_payments:
        output_rows = [row for row in output_rows if not row["is_credit_card_payment"]]
    return output_rows


def build_analytics_response(session: Session, filters: AnalyticsFilters | None = None) -> dict[str, Any]:
    filters = filters or AnalyticsFilters()
    rows = build_unified_rows(session, filters)
    loan_impacts = _loan_impacts(session, filters)
    recurring = detect_recurring_patterns(rows)
    anomalies = detect_anomalies(rows)
    budget = build_budget_comparison(session, rows, filters)
    summary = build_summary(rows, loan_impacts)
    charts = {
        "monthly_trend": monthly_trend(rows, loan_impacts),
        "category_breakdown": category_breakdown(rows),
        "merchant_breakdown": merchant_breakdown(rows),
        "daily_spend": daily_spend(rows),
        "source_comparison": source_comparison(rows),
        "cashflow": cashflow(rows, loan_impacts),
        "true_expense_vs_gross_debit": true_expense_vs_gross_debit(rows),
        "weekday_weekend_spend": weekday_weekend_spend(rows),
        "category_month_movement": category_month_movement(rows),
    }
    tables = {
        "transactions": _table_rows(rows, limit=500),
        "top_transactions": sorted(_table_rows(rows), key=lambda item: item["true_expense"], reverse=True)[:20],
        "recurring": recurring,
        "anomalies": anomalies,
        "budget_comparison": budget,
        "merchant_breakdown": merchant_breakdown(rows, limit=50),
        "category_breakdown": category_breakdown(rows, limit=50),
    }
    return {
        "filters": filters.as_dict(),
        "summary": summary,
        "charts": charts,
        "tables": tables,
        "insights": build_insights(summary, anomalies, budget),
        "warnings": _warnings(rows),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def build_summary(rows: list[dict[str, Any]], loan_impacts: dict[str, Decimal] | None = None) -> dict[str, Any]:
    loan_impacts = loan_impacts or {}
    income = sum((row["amount_decimal"] for row in rows if row["transaction_type"] == "credit" and not row["is_refund"] and not row["is_cashback"]), Decimal("0.00"))
    gross_debit = sum((row["gross_debit_decimal"] for row in rows), Decimal("0.00"))
    true_expense = sum((row["true_expense_decimal"] for row in rows), Decimal("0.00"))
    refund_adjustment = sum((row["refund_adjustment_decimal"] for row in rows), Decimal("0.00"))
    cashback_adjustment = sum((row["cashback_adjustment_decimal"] for row in rows), Decimal("0.00"))
    net_true_expense = max(Decimal("0.00"), money(true_expense - refund_adjustment - cashback_adjustment))
    liability_payment = sum((row["liability_payment_decimal"] for row in rows), Decimal("0.00"))
    row_loan_principal = sum((row["debt_principal_decimal"] for row in rows if row["is_loan_prepayment"]), Decimal("0.00"))
    row_loan_interest = sum((row["debt_interest_decimal"] for row in rows if row["category"] == "Loan Interest" or row["loan_transaction_type"] == "interest"), Decimal("0.00"))
    row_card_interest = sum((row["debt_interest_decimal"] for row in rows if not (row["category"] == "Loan Interest" or row["loan_transaction_type"] == "interest")), Decimal("0.00"))
    debt_principal = max(row_loan_principal, loan_impacts.get("principal", Decimal("0.00")))
    debt_interest = row_card_interest + max(row_loan_interest, loan_impacts.get("interest", Decimal("0.00")))
    credit_card_spend = sum((row["true_expense_decimal"] for row in rows if row["source_type"] == "credit_card_statement"), Decimal("0.00"))
    upi_spend = sum((row["true_expense_decimal"] for row in rows if row["transaction_channel"] == "upi"), Decimal("0.00"))
    bank_spend = sum((row["true_expense_decimal"] for row in rows if row["source_type"] == "bank_statement"), Decimal("0.00"))
    loan_emi_from_rows = sum((row["amount_decimal"] for row in rows if row["is_loan_emi"]), Decimal("0.00"))
    credit_card_emi = sum((row["amount_decimal"] for row in rows if row["is_credit_card_emi"]), Decimal("0.00"))
    emi_burden = credit_card_emi + max(loan_emi_from_rows, loan_impacts.get("emi", Decimal("0.00")))
    savings = money(income - net_true_expense - debt_interest)
    return {
        "total_income": money_float(income),
        "gross_debit": money_float(gross_debit),
        "true_expense": money_float(net_true_expense),
        "liability_payment": money_float(liability_payment),
        "debt_principal": money_float(debt_principal),
        "debt_interest": money_float(debt_interest),
        "refund_adjustment": money_float(refund_adjustment),
        "cashback_adjustment": money_float(cashback_adjustment),
        "net_savings": money_float(savings),
        "savings_rate": _pct(savings, income),
        "expense_to_income_ratio": _pct(net_true_expense, income),
        "total_emi_burden": money_float(emi_burden),
        "emi_to_income_ratio": _pct(emi_burden, income),
        "credit_card_spend": money_float(credit_card_spend),
        "upi_spend": money_float(upi_spend),
        "bank_account_spend": money_float(bank_spend),
        "transaction_count": len(rows),
        "spend_quality_score": spend_quality_score(income, net_true_expense, emi_burden, debt_interest, rows),
    }


def monthly_trend(rows: list[dict[str, Any]], loan_impacts: dict[str, Decimal] | None = None) -> list[dict[str, Any]]:
    monthly: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for row in rows:
        period = row["transaction_date"][:7]
        monthly[period]["income"] += row["amount_decimal"] if row["transaction_type"] == "credit" and not row["is_refund"] and not row["is_cashback"] else Decimal("0.00")
        monthly[period]["gross_debit"] += row["gross_debit_decimal"]
        monthly[period]["true_expense"] += row["true_expense_decimal"]
        monthly[period]["liability_payment"] += row["liability_payment_decimal"]
        monthly[period]["credit_card_spend"] += row["true_expense_decimal"] if row["source_type"] == "credit_card_statement" else Decimal("0.00")
        monthly[period]["upi_spend"] += row["true_expense_decimal"] if row["transaction_channel"] == "upi" else Decimal("0.00")
        monthly[period]["bank_only_spend"] += row["true_expense_decimal"] if row["source_type"] == "bank_statement" else Decimal("0.00")
        monthly[period]["loan_emi_from_rows"] += row["amount_decimal"] if row["is_loan_emi"] else Decimal("0.00")
        monthly[period]["credit_card_emi"] += row["amount_decimal"] if row["is_credit_card_emi"] else Decimal("0.00")
        monthly[period]["row_loan_interest"] += row["debt_interest_decimal"] if row["category"] == "Loan Interest" or row["loan_transaction_type"] == "interest" else Decimal("0.00")
        monthly[period]["row_card_interest"] += row["debt_interest_decimal"] if not (row["category"] == "Loan Interest" or row["loan_transaction_type"] == "interest") else Decimal("0.00")
        monthly[period]["row_loan_principal"] += row["debt_principal_decimal"] if row["is_loan_prepayment"] else Decimal("0.00")
    for period, values in (loan_impacts or {}).get("monthly", {}).items():
        monthly[period]["loan_ledger_emi"] += values["emi"]
        monthly[period]["loan_ledger_interest"] += values["interest"]
        monthly[period]["loan_ledger_principal"] += values["principal"]
    output = []
    for period in sorted(monthly):
        values = monthly[period]
        emi_burden = values["credit_card_emi"] + max(values["loan_emi_from_rows"], values["loan_ledger_emi"])
        debt_interest = values["row_card_interest"] + max(values["row_loan_interest"], values["loan_ledger_interest"])
        debt_principal = max(values["row_loan_principal"], values["loan_ledger_principal"])
        savings = values["income"] - values["true_expense"] - debt_interest
        output.append(
            {
                "period": period,
                "income": money_float(values["income"]),
                "gross_debit": money_float(values["gross_debit"]),
                "true_expense": money_float(values["true_expense"]),
                "savings": money_float(savings),
                "savings_rate": _pct(savings, values["income"]),
                "emi_burden": money_float(emi_burden),
                "credit_card_spend": money_float(values["credit_card_spend"]),
                "upi_spend": money_float(values["upi_spend"]),
                "bank_only_spend": money_float(values["bank_only_spend"]),
                "debt_interest": money_float(debt_interest),
                "debt_principal": money_float(debt_principal),
            }
        )
    return output


def category_breakdown(rows: list[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    grouped: dict[str, Decimal] = defaultdict(Decimal)
    for row in rows:
        grouped[row["category"]] += row["net_category_spend_decimal"]
    return [
        {"category": category, "amount": money_float(amount)}
        for category, amount in sorted(grouped.items(), key=lambda item: item[1], reverse=True)
        if amount != 0
    ][:limit]


def merchant_breakdown(rows: list[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        merchant = row["merchant_name"] or row["counterparty_name"] or "Unknown"
        item = grouped.setdefault(
            merchant,
            {
                "merchant": merchant,
                "amount": Decimal("0.00"),
                "frequency": 0,
                "first_seen": row["transaction_date"],
                "last_seen": row["transaction_date"],
                "category": row["category"],
                "sources": set(),
            },
        )
        item["amount"] += row["net_category_spend_decimal"]
        item["frequency"] += 1 if row["true_expense_decimal"] > 0 else 0
        item["first_seen"] = min(item["first_seen"], row["transaction_date"])
        item["last_seen"] = max(item["last_seen"], row["transaction_date"])
        item["sources"].add(row["source_type"])
    output = []
    for item in sorted(grouped.values(), key=lambda row: row["amount"], reverse=True)[:limit]:
        output.append(
            {
                "merchant": item["merchant"],
                "amount": money_float(item["amount"]),
                "frequency": item["frequency"],
                "average_transaction_size": money_float(item["amount"] / item["frequency"]) if item["frequency"] else 0.0,
                "first_seen": item["first_seen"],
                "last_seen": item["last_seen"],
                "category": item["category"],
                "source_split": sorted(item["sources"]),
                "recurring_probability": min(0.95, item["frequency"] / 6) if item["frequency"] >= 2 else 0.0,
            }
        )
    return output


def daily_spend(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, Decimal] = defaultdict(Decimal)
    for row in rows:
        grouped[row["transaction_date"]] += row["true_expense_decimal"]
    return [{"date": day, "amount": money_float(amount)} for day, amount in sorted(grouped.items()) if amount > 0]


def source_comparison(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for row in rows:
        source = row["source_type"]
        grouped[source]["gross_debit"] += row["gross_debit_decimal"]
        grouped[source]["true_expense"] += row["true_expense_decimal"]
        grouped[source]["liability_payment"] += row["liability_payment_decimal"]
        grouped[source]["transaction_count"] += Decimal("1")
    return [
        {
            "source_type": source,
            "gross_debit": money_float(values["gross_debit"]),
            "true_expense": money_float(values["true_expense"]),
            "liability_payment": money_float(values["liability_payment"]),
            "transaction_count": int(values["transaction_count"]),
        }
        for source, values in sorted(grouped.items())
    ]


def cashflow(rows: list[dict[str, Any]], loan_impacts: dict[str, Decimal] | None = None) -> dict[str, Any]:
    summary = build_summary(rows, loan_impacts)
    fixed_commitments = sum((Decimal(str(item["monthly_commitment"])) for item in detect_recurring_patterns(rows)), Decimal("0.00"))
    variable_expenses = money(Decimal(str(summary["true_expense"])) - fixed_commitments)
    days = sorted({row["transaction_date"] for row in rows})
    elapsed_days = max(1, len(days))
    spend_velocity = money(Decimal(str(summary["true_expense"])) / Decimal(elapsed_days))
    projected_month_end = money(spend_velocity * Decimal("30"))
    return {
        "income_received": summary["total_income"],
        "fixed_commitments": money_float(fixed_commitments),
        "variable_expenses": money_float(max(Decimal("0.00"), variable_expenses)),
        "debt_payments": summary["total_emi_burden"],
        "debt_interest": summary["debt_interest"],
        "free_cashflow": money_float(Decimal(str(summary["total_income"])) - Decimal(str(summary["true_expense"])) - Decimal(str(summary["total_emi_burden"]))),
        "daily_spend_velocity": money_float(spend_velocity),
        "projected_month_end_expense": money_float(projected_month_end),
    }


def true_expense_vs_gross_debit(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"label": "Gross debit", "amount": money_float(sum((row["gross_debit_decimal"] for row in rows), Decimal("0.00")))},
        {"label": "True expense", "amount": money_float(sum((row["true_expense_decimal"] for row in rows), Decimal("0.00")))},
        {"label": "Liability/internal", "amount": money_float(sum((row["liability_payment_decimal"] for row in rows), Decimal("0.00")))},
    ]


def weekday_weekend_spend(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = {"weekday": Decimal("0.00"), "weekend": Decimal("0.00")}
    counts = {"weekday": 0, "weekend": 0}
    for row in rows:
        label = "weekend" if date.fromisoformat(row["transaction_date"]).weekday() >= 5 else "weekday"
        grouped[label] += row["true_expense_decimal"]
        counts[label] += 1 if row["true_expense_decimal"] > 0 else 0
    return [
        {"day_type": label, "amount": money_float(grouped[label]), "transaction_count": counts[label]}
        for label in ["weekday", "weekend"]
    ]


def category_month_movement(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    for row in rows:
        grouped[(row["category"], row["transaction_date"][:7])] += row["net_category_spend_decimal"]
    output = []
    months = sorted({month for _, month in grouped})
    if not months:
        return output
    current_month = months[-1]
    previous_month = months[-2] if len(months) > 1 else None
    categories = sorted({category for category, _ in grouped})
    for category in categories:
        current = grouped.get((category, current_month), Decimal("0.00"))
        previous = grouped.get((category, previous_month), Decimal("0.00")) if previous_month else Decimal("0.00")
        past_amounts = [grouped.get((category, month), Decimal("0.00")) for month in months[-4:-1]]
        average_3m = sum(past_amounts, Decimal("0.00")) / Decimal(len(past_amounts)) if past_amounts else Decimal("0.00")
        change = current - previous
        output.append(
            {
                "category": category,
                "current_month": current_month,
                "current_month_spend": money_float(current),
                "previous_month_spend": money_float(previous),
                "change_amount": money_float(change),
                "change_percent": _pct(change, previous) if previous else None,
                "three_month_average": money_float(average_3m),
            }
        )
    return sorted(output, key=lambda item: item["current_month_spend"], reverse=True)


def detect_recurring_patterns(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["true_expense_decimal"] <= 0 and not row["is_loan_emi"] and not row["is_credit_card_emi"]:
            continue
        key = (row["counterparty_name"] or row["merchant_name"] or "Unknown", row["category"])
        groups[key].append(row)
    output = []
    for (name, category), group in groups.items():
        if len(group) < 2:
            continue
        dates = sorted(date.fromisoformat(row["transaction_date"]) for row in group)
        gaps = [(dates[index] - dates[index - 1]).days for index in range(1, len(dates))]
        cadence = _cadence(gaps)
        amounts = [row["amount_decimal"] for row in group]
        typical_amount = money(Decimal(str(median(amounts))))
        variation = (max(amounts) - min(amounts)) / typical_amount if typical_amount else Decimal("1.00")
        recurring_hint = category in {"Subscriptions", "Rent", "Insurance", "Home Loan EMI", "Other Loan EMI", "Mutual Funds / SIP", "Utilities"}
        if len(group) >= 3 or variation <= Decimal("0.20") or recurring_hint:
            output.append(
                {
                    "name": name,
                    "category": category,
                    "frequency": cadence,
                    "occurrences": len(group),
                    "expected_amount": money_float(typical_amount),
                    "monthly_commitment": money_float(typical_amount if cadence in {"monthly", "irregular"} else typical_amount * Decimal("4")),
                    "next_expected_date": (dates[-1] + timedelta(days=_cadence_days(cadence))).isoformat(),
                    "last_seen": dates[-1].isoformat(),
                    "source": sorted({row["source_type"] for row in group}),
                    "confidence_score": min(0.95, 0.45 + (0.12 * len(group)) + (0.2 if variation <= Decimal("0.20") else 0)),
                }
            )
    return sorted(output, key=lambda item: item["monthly_commitment"], reverse=True)


def detect_anomalies(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    anomalies: list[dict[str, Any]] = []
    by_category: dict[str, list[Decimal]] = defaultdict(list)
    duplicate_key_seen: dict[tuple[str, str, Decimal], int] = {}
    for row in rows:
        if row["true_expense_decimal"] > 0:
            by_category[row["category"]].append(row["true_expense_decimal"])
    averages = {
        category: sum(amounts, Decimal("0.00")) / Decimal(len(amounts))
        for category, amounts in by_category.items()
        if amounts
    }
    for row in rows:
        if row["true_expense_decimal"] <= 0:
            continue
        category_average = averages.get(row["category"], Decimal("0.00"))
        if row["true_expense_decimal"] >= max(Decimal("5000.00"), category_average * Decimal("3")) and len(by_category[row["category"]]) >= 2:
            anomalies.append(_anomaly(row, "High transaction", "warning", f"Amount is at least 3x the category average ({money_float(category_average)}).", 0.78))
        if any(token in normalize_text(row["raw_description"]) for token in FEE_TOKENS) and row["source_type"] in {"bank_statement", "credit_card_statement"}:
            anomalies.append(_anomaly(row, "Possible fee or interest charge", "warning", "Description contains fee, charge, interest, GST, or late-payment wording.", 0.84))
        duplicate_key = (row["transaction_date"], row["counterparty_name"] or row["merchant_name"] or "", row["amount_decimal"])
        if duplicate_key in duplicate_key_seen:
            anomalies.append(_anomaly(row, "Duplicate-looking transaction", "info", f"Looks similar to transaction {duplicate_key_seen[duplicate_key]}.", 0.72))
        else:
            duplicate_key_seen[duplicate_key] = row["id"]
    anomalies.extend(_category_spike_anomalies(rows))
    return anomalies[:100]


def build_budget_comparison(session: Session, rows: list[dict[str, Any]], filters: AnalyticsFilters | None = None) -> list[dict[str, Any]]:
    filters = filters or AnalyticsFilters()
    settings = get_settings()
    profile = filters.benchmark_profile or settings.default_benchmark_profile
    benchmarks = session.scalars(
        select(Benchmark).where(
            Benchmark.city == settings.default_benchmark_city,
            Benchmark.profile == profile,
            Benchmark.is_active.is_(True),
        )
    ).all()
    spend_by_category = {item["category"]: Decimal(str(item["amount"])) for item in category_breakdown(rows, limit=1000)}
    output = []
    for benchmark in benchmarks:
        actual = spend_by_category.get(benchmark.category, Decimal("0.00"))
        status = "within_range"
        overspend = Decimal("0.00")
        if actual > benchmark.max_amount:
            status = "over_benchmark"
            overspend = actual - benchmark.max_amount
        elif actual < benchmark.min_amount:
            status = "under_benchmark"
        output.append(
            {
                "category": benchmark.category,
                "actual": money_float(actual),
                "benchmark_min": money_float(benchmark.min_amount),
                "benchmark_max": money_float(benchmark.max_amount),
                "overspend_amount": money_float(overspend),
                "status": status,
                "profile": profile,
            }
        )
    return output


def build_insights(summary: dict[str, Any], anomalies: list[dict[str, Any]], budget: list[dict[str, Any]]) -> list[dict[str, Any]]:
    insights: list[dict[str, Any]] = []
    if summary["savings_rate"] < 10 and summary["total_income"] > 0:
        insights.append(_insight("Low savings rate", "Savings rate is below 10% for the selected data.", "warning", [], "net_savings / income", 0.8))
    if summary["emi_to_income_ratio"] > 40:
        insights.append(_insight("High EMI burden", "EMI-to-income ratio is above 40% in uploaded data.", "warning", [], "emi_burden / income", 0.78))
    if summary["debt_interest"] > 0:
        insights.append(_insight("Debt cost detected", "Loan or card interest/fees were detected and separated from principal movement.", "info", [], "ledger and transaction classification", 0.82))
    for item in budget:
        if item["status"] == "over_benchmark" and item["overspend_amount"] > 0:
            insights.append(
                _insight(
                    f"{item['category']} above benchmark",
                    f"Actual spend is above the {item['profile']} benchmark range by {item['overspend_amount']:.2f}.",
                    "warning",
                    [],
                    "actual category spend vs local benchmark range",
                    0.74,
                )
            )
    if anomalies:
        insights.append(_insight("Transactions need review", f"{len(anomalies)} anomaly flags were detected.", "info", [item["transaction_id"] for item in anomalies[:10]], "deterministic anomaly rules", 0.76))
    return insights


def spend_quality_score(income: Decimal, true_expense: Decimal, emi_burden: Decimal, debt_interest: Decimal, rows: list[dict[str, Any]]) -> dict[str, Any]:
    if income <= 0:
        return {"score": 0, "explanation": "No income detected in selected data.", "breakdown": {}}
    savings_rate = (income - true_expense - debt_interest) / income * Decimal("100")
    emi_ratio = emi_burden / income * Decimal("100")
    discretionary = sum((row["true_expense_decimal"] for row in rows if row["category"] in {"Shopping", "Entertainment", "Restaurants", "Food Delivery", "Travel"}), Decimal("0.00"))
    discretionary_ratio = discretionary / income * Decimal("100")
    fee_count = sum(1 for row in rows if any(token in normalize_text(row["raw_description"]) for token in FEE_TOKENS))
    score = Decimal("70.00")
    score += min(Decimal("20.00"), savings_rate / Decimal("2"))
    score -= max(Decimal("0.00"), emi_ratio - Decimal("25.00")) * Decimal("0.6")
    score -= max(Decimal("0.00"), discretionary_ratio - Decimal("25.00")) * Decimal("0.4")
    score -= Decimal(fee_count) * Decimal("2.00")
    score = max(Decimal("0.00"), min(Decimal("100.00"), score))
    return {
        "score": int(score),
        "explanation": "Deterministic score based only on uploaded transaction data; not financial advice.",
        "breakdown": {
            "savings_rate": round(float(savings_rate), 2),
            "emi_to_income_ratio": round(float(emi_ratio), 2),
            "discretionary_spend_ratio": round(float(discretionary_ratio), 2),
            "fee_or_interest_flags": fee_count,
        },
    }


def _build_unified_row(
    transaction: Transaction,
    document_type: str | None,
    document_filename: str | None,
    credit_card_info: dict[str, Any] | None,
    loan_info: dict[str, Any] | None,
) -> dict[str, Any]:
    source_type = normalize_source_type(document_type or "manual")
    amount = money(transaction.amount)
    text = normalize_text(transaction.raw_description)
    tag_text = normalize_text(" ".join(transaction.tags or []))
    manual_text = f"{text} {tag_text}".strip()
    category = transaction.category or "Miscellaneous"
    cc_parsed_type = credit_card_info["parsed_type"] if credit_card_info else None
    loan_transaction_type = loan_info["loan_transaction_type"] if loan_info else None
    is_credit_card_payment = _is_credit_card_payment(transaction, source_type, manual_text)
    is_loan_emi = loan_transaction_type == "emi" or category in LOAN_EMI_CATEGORIES or "loan recovery" in manual_text or "loan rec" in manual_text or "loan_emi" in manual_text
    is_loan_prepayment = loan_transaction_type == "prepayment" or category in LOAN_PREPAYMENT_CATEGORIES or ("mbk" in manual_text and transaction.transaction_type == "debit") or "loan_prepayment" in manual_text
    is_internal_transfer = bool(
        transaction.is_personal_transfer
        or category in INTERNAL_TRANSFER_CATEGORIES
        or ("self" in manual_text and transaction.transaction_type == "debit")
        or "internal_transfer" in manual_text
    )
    is_refund = transaction.transaction_type == "credit" and any(token in manual_text for token in REFUND_TOKENS)
    is_cashback = transaction.transaction_type == "credit" and any(token in manual_text for token in CASHBACK_TOKENS)
    is_credit_card_emi = bool(cc_parsed_type and "emi" in cc_parsed_type)
    channel = _transaction_channel(transaction, source_type, text, is_loan_emi, is_loan_prepayment)
    counterparty = _counterparty_name(transaction, channel)
    gross_debit = amount if transaction.transaction_type == "debit" else Decimal("0.00")
    liability_payment = amount if transaction.transaction_type == "debit" and (is_credit_card_payment or is_loan_emi or is_loan_prepayment) else Decimal("0.00")
    debt_principal = amount if is_loan_prepayment else Decimal("0.00")
    debt_interest = amount if (loan_transaction_type == "interest" or category in {"Loan Interest", "Credit Card Interest / Fees"} or cc_parsed_type in {"interest_charge", "emi_interest", "finance_charge"}) else Decimal("0.00")
    refund_adjustment = amount if is_refund else Decimal("0.00")
    cashback_adjustment = amount if is_cashback else Decimal("0.00")
    true_expense = _true_expense(transaction, source_type, amount, is_internal_transfer, is_credit_card_payment, is_loan_emi, is_loan_prepayment, cc_parsed_type)
    net_category_spend = true_expense - refund_adjustment - cashback_adjustment
    return {
        "id": transaction.id,
        "transaction_date": transaction.date.isoformat(),
        "posting_date": transaction.date.isoformat(),
        "source_type": source_type,
        "source_document_id": transaction.source_document_id,
        "source_document_name": document_filename,
        "source_account_id": transaction.account_id,
        "source_card_id": credit_card_info["card_id"] if credit_card_info else None,
        "source_card_usage_type": credit_card_info["usage_type"] if credit_card_info else None,
        "source_loan_id": loan_info["loan_id"] if loan_info else None,
        "transaction_channel": channel,
        "transaction_type": transaction.transaction_type,
        "amount": money_float(amount),
        "amount_decimal": amount,
        "description": transaction.description,
        "raw_description": transaction.raw_description,
        "merchant_name": transaction.merchant_name,
        "counterparty_name": counterparty,
        "category": category,
        "subcategory": transaction.subcategory,
        "tags": list(transaction.tags or []),
        "is_internal_transfer": is_internal_transfer,
        "is_credit_card_payment": is_credit_card_payment,
        "is_loan_emi": is_loan_emi,
        "is_loan_prepayment": is_loan_prepayment,
        "is_credit_card_emi": is_credit_card_emi,
        "is_refund": is_refund,
        "is_cashback": is_cashback,
        "is_recurring": transaction.is_recurring,
        "is_excluded_from_analysis": transaction.is_excluded,
        "confidence_score": transaction.confidence_score,
        "manual_override": bool(transaction.notes and "manual" in normalize_text(transaction.notes)),
        "gross_debit": money_float(gross_debit),
        "gross_debit_decimal": gross_debit,
        "true_expense": money_float(true_expense),
        "true_expense_decimal": true_expense,
        "liability_payment": money_float(liability_payment),
        "liability_payment_decimal": liability_payment,
        "internal_transfer": money_float(amount if is_internal_transfer else Decimal("0.00")),
        "debt_principal": money_float(debt_principal),
        "debt_principal_decimal": debt_principal,
        "debt_interest": money_float(debt_interest),
        "debt_interest_decimal": debt_interest,
        "refund_adjustment": money_float(refund_adjustment),
        "refund_adjustment_decimal": refund_adjustment,
        "cashback_adjustment": money_float(cashback_adjustment),
        "cashback_adjustment_decimal": cashback_adjustment,
        "net_category_spend": money_float(net_category_spend),
        "net_category_spend_decimal": net_category_spend,
        "credit_card_parsed_type": cc_parsed_type,
        "loan_transaction_type": loan_transaction_type,
    }


def _credit_card_lookup(session: Session) -> dict[int, dict[str, Any]]:
    rows = session.execute(
        select(
            CreditCardTransaction.transaction_id,
            CreditCardTransaction.card_id,
            CreditCardTransaction.parsed_type,
            CreditCard.usage_type,
        ).join(CreditCard, CreditCard.id == CreditCardTransaction.card_id)
    ).all()
    return {
        transaction_id: {"card_id": card_id, "parsed_type": parsed_type, "usage_type": usage_type}
        for transaction_id, card_id, parsed_type, usage_type in rows
        if transaction_id is not None
    }


def _loan_transaction_lookup(session: Session) -> dict[int, dict[str, Any]]:
    rows = session.execute(
        select(LoanTransaction.transaction_id, LoanTransaction.loan_id, LoanTransaction.loan_transaction_type)
        .where(LoanTransaction.transaction_id.is_not(None))
    ).all()
    return {
        transaction_id: {"loan_id": loan_id, "loan_transaction_type": loan_transaction_type}
        for transaction_id, loan_id, loan_transaction_type in rows
        if transaction_id is not None
    }


def _loan_impacts(session: Session, filters: AnalyticsFilters) -> dict[str, Any]:
    source_type = normalize_source_type(filters.source_type)
    if source_type not in {"all_sources", "bank_statement", "loan_statement", "manual"}:
        return {"emi": Decimal("0.00"), "prepayment": Decimal("0.00"), "interest": Decimal("0.00"), "principal": Decimal("0.00"), "monthly": {}}
    statement = select(LoanMonthlyLedger)
    if filters.start_date:
        statement = statement.where(LoanMonthlyLedger.month >= date(filters.start_date.year, filters.start_date.month, 1))
    if filters.end_date:
        statement = statement.where(LoanMonthlyLedger.month <= date(filters.end_date.year, filters.end_date.month, 1))
    ledgers = session.scalars(statement.order_by(LoanMonthlyLedger.month.asc())).all()
    monthly: dict[str, dict[str, Decimal]] = defaultdict(lambda: {"emi": Decimal("0.00"), "prepayment": Decimal("0.00"), "interest": Decimal("0.00"), "principal": Decimal("0.00")})
    total = {"emi": Decimal("0.00"), "prepayment": Decimal("0.00"), "interest": Decimal("0.00"), "principal": Decimal("0.00")}
    for row in ledgers:
        period = row.month.strftime("%Y-%m")
        emi = money(row.emi_paid)
        prepayment = money(row.prepayment_paid)
        interest = money(row.interest_charged)
        principal = money(row.total_principal_reduced)
        monthly[period]["emi"] += emi
        monthly[period]["prepayment"] += prepayment
        monthly[period]["interest"] += interest
        monthly[period]["principal"] += principal
        total["emi"] += emi
        total["prepayment"] += prepayment
        total["interest"] += interest
        total["principal"] += principal
    total["monthly"] = monthly
    return total


def _true_expense(
    transaction: Transaction,
    source_type: str,
    amount: Decimal,
    is_internal_transfer: bool,
    is_credit_card_payment: bool,
    is_loan_emi: bool,
    is_loan_prepayment: bool,
    cc_parsed_type: str | None,
) -> Decimal:
    if transaction.transaction_type != "debit":
        return Decimal("0.00")
    if is_internal_transfer or is_credit_card_payment or is_loan_emi or is_loan_prepayment:
        return Decimal("0.00")
    if source_type == "credit_card_statement" and cc_parsed_type in {"payment", "payment_or_credit", "refund", "interest_reversal", "cashback_discount", "discount", "bank_offer_credit", "other_credit"}:
        return Decimal("0.00")
    return amount


def _transaction_channel(transaction: Transaction, source_type: str, text: str, is_loan_emi: bool, is_loan_prepayment: bool) -> str:
    payment_mode = normalize_text(transaction.payment_mode).upper()
    if is_loan_emi or is_loan_prepayment or source_type == "loan_statement":
        return "loan"
    if transaction.payment_mode == "UPI" or any(token in text for token in UPI_TOKENS | UPI_PROVIDER_TOKENS):
        return "upi"
    if payment_mode == "CARD" or source_type == "credit_card_statement":
        return "card"
    if "atm" in text or payment_mode == "CASH":
        return "cash"
    if payment_mode in {"IMPS", "NEFT", "RTGS", "NETBANKING", "AUTOPAY", "CHEQUE"}:
        return "bank_transfer"
    if "wallet" in text:
        return "wallet"
    if "emi" in text:
        return "emi"
    return "unknown"


def _is_credit_card_payment(transaction: Transaction, source_type: str, text: str) -> bool:
    if source_type == "credit_card_statement":
        return False
    return transaction.transaction_type == "debit" and (
        transaction.category == "Credit Card Payment"
        or any(token in text for token in CARD_PAYMENT_TOKENS)
        or ("credit card" in text and "payment" in text)
    )


def _counterparty_name(transaction: Transaction, channel: str) -> str:
    if transaction.merchant_name:
        return transaction.merchant_name
    if channel == "upi":
        tokens = [
            token.strip(" -/")
            for token in transaction.raw_description.replace("|", "/").replace(":", "/").replace("-", "/").split("/")
            if token.strip(" -/")
        ]
        stopwords = UPI_TOKENS | {"payment", "collect", "ref", "utr", "rrn", "txn", "debit", "credit", "p2m", "p2a"}
        for token in tokens:
            normalized = normalize_text(token)
            if normalized and normalized not in stopwords and not normalized.isdigit() and "@" not in normalized:
                return token.title()
    return transaction.account_source or "Unknown"


def _table_rows(rows: list[dict[str, Any]], limit: int | None = None) -> list[dict[str, Any]]:
    cleaned = []
    for row in rows[: limit or len(rows)]:
        cleaned.append({key: value for key, value in row.items() if not key.endswith("_decimal")})
    return cleaned


def _category_spike_anomalies(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    monthly: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    for row in rows:
        monthly[(row["category"], row["transaction_date"][:7])] += row["net_category_spend_decimal"]
    months = sorted({month for _, month in monthly})
    if len(months) < 2:
        return []
    latest = months[-1]
    anomalies = []
    for category in {category for category, _ in monthly}:
        current = monthly[(category, latest)]
        previous_values = [monthly.get((category, month), Decimal("0.00")) for month in months[:-1]]
        previous_average = sum(previous_values, Decimal("0.00")) / Decimal(len(previous_values))
        if previous_average > 0 and current > previous_average * Decimal("2.5") and current - previous_average > Decimal("2000.00"):
            anomalies.append(
                {
                    "title": "Category spike",
                    "severity": "warning",
                    "category": category,
                    "transaction_id": None,
                    "description": f"{category} spend is above 2.5x previous monthly average.",
                    "amount": money_float(current),
                    "calculation_method": "latest category month vs historical average",
                    "confidence_score": 0.74,
                }
            )
    return anomalies


def _anomaly(row: dict[str, Any], title: str, severity: str, description: str, confidence: float) -> dict[str, Any]:
    return {
        "title": title,
        "severity": severity,
        "transaction_id": row["id"],
        "date": row["transaction_date"],
        "amount": row["amount"],
        "merchant": row["merchant_name"] or row["counterparty_name"],
        "category": row["category"],
        "description": description,
        "calculation_method": "deterministic local rule",
        "confidence_score": confidence,
    }


def _insight(title: str, description: str, severity: str, related_transactions: list[int], method: str, confidence: float) -> dict[str, Any]:
    return {
        "title": title,
        "description": description,
        "severity": severity,
        "related_transactions": related_transactions,
        "calculation_method": method,
        "confidence_score": confidence,
    }


def _warnings(rows: list[dict[str, Any]]) -> list[str]:
    warnings = []
    if not rows:
        warnings.append("No transactions matched the current filters.")
    if any(row["confidence_score"] < 0.55 for row in rows):
        warnings.append("Some transactions have low parsing/classification confidence and should be reviewed.")
    return warnings


def _cadence(gaps: list[int]) -> str:
    if not gaps:
        return "single"
    gap = median(gaps)
    if 1 <= gap <= 2:
        return "daily"
    if 6 <= gap <= 8:
        return "weekly"
    if 12 <= gap <= 17:
        return "fortnightly"
    if 25 <= gap <= 35:
        return "monthly"
    return "irregular"


def _cadence_days(cadence: str) -> int:
    return {"daily": 1, "weekly": 7, "fortnightly": 14, "monthly": 30}.get(cadence, 30)


def _pct(numerator: Decimal, denominator: Decimal) -> float:
    if denominator == 0:
        return 0.0
    return round(float((numerator / denominator) * Decimal("100")), 2)
