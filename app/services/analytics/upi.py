from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.entities import Transaction
from app.services.categorization.rules import is_probable_personal_transfer, normalize_text
from app.utils.amounts import MAX_REASONABLE_TRANSACTION_AMOUNT


TWOPLACES = Decimal("0.01")
UNLABELED_UPI_SOURCE = "Unlabeled source"


@dataclass(frozen=True)
class UpiTransactionInsight:
    transaction_id: int
    date: date
    receiver_name: str
    amount: Decimal
    category: str
    is_personal_transfer: bool
    raw_description: str


@dataclass(frozen=True)
class UpiRecurringPayment:
    receiver_name: str
    cadence: str
    occurrences: int
    typical_amount: Decimal
    total_spend: Decimal
    last_seen_date: date


@dataclass(frozen=True)
class UpiAnalysisResult:
    total_upi_spend: Decimal
    merchant_spend: Decimal
    personal_transfer_spend: Decimal
    daily_spend: list[dict[str, Decimal | date]]
    daily_category_spend: list[dict[str, Decimal | date | str]]
    top_receivers: list[dict[str, Decimal | str]]
    repeated_payments: list[UpiRecurringPayment]
    transactions: list[UpiTransactionInsight]


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def _receiver_name(transaction: Transaction) -> str:
    if transaction.merchant_name:
        return transaction.merchant_name
    normalized = normalize_text(transaction.raw_description)
    return normalized[:60] or "Unknown"


def _detect_cadence(day_gaps: list[int]) -> str:
    if not day_gaps:
        return "single"
    median_gap = sorted(day_gaps)[len(day_gaps) // 2]
    if 1 <= median_gap <= 2:
        return "daily"
    if 6 <= median_gap <= 8:
        return "weekly"
    if 12 <= median_gap <= 17:
        return "fortnightly"
    if 25 <= median_gap <= 35:
        return "monthly"
    return "irregular"


def list_upi_sources(session: Session) -> list[str]:
    rows = session.scalars(
        select(Transaction.account_source)
        .where(Transaction.payment_mode == "UPI")
        .distinct()
        .order_by(Transaction.account_source)
    ).all()
    sources = [row for row in rows if row]
    if any(not row for row in rows):
        sources.append(UNLABELED_UPI_SOURCE)
    return sources


def analyze_upi_transactions(
    session: Session,
    start_date: date | None = None,
    end_date: date | None = None,
    account_source: str | None = None,
) -> UpiAnalysisResult:
    statement = select(Transaction).where(
        Transaction.payment_mode == "UPI",
        Transaction.is_excluded.is_(False),
        Transaction.amount <= MAX_REASONABLE_TRANSACTION_AMOUNT,
    )
    if start_date:
        statement = statement.where(Transaction.date >= start_date)
    if end_date:
        statement = statement.where(Transaction.date <= end_date)
    if account_source:
        if account_source == UNLABELED_UPI_SOURCE:
            statement = statement.where(or_(Transaction.account_source.is_(None), Transaction.account_source == ""))
        else:
            statement = statement.where(Transaction.account_source == account_source)

    transactions = session.scalars(statement.order_by(Transaction.date.asc(), Transaction.id.asc())).all()
    debit_transactions = [transaction for transaction in transactions if transaction.transaction_type == "debit"]

    insights = [
        UpiTransactionInsight(
            transaction_id=transaction.id,
            date=transaction.date,
            receiver_name=_receiver_name(transaction),
            amount=_quantize(transaction.amount),
            category=transaction.category,
            is_personal_transfer=bool(
                transaction.is_personal_transfer or transaction.category == "Family / Personal Transfers"
                or (
                    transaction.category in {"UPI Transfers", "Miscellaneous"}
                    and is_probable_personal_transfer(
                        description=transaction.raw_description,
                        merchant_name=_receiver_name(transaction),
                        payment_mode="UPI",
                    )
                )
            ),
            raw_description=transaction.raw_description,
        )
        for transaction in debit_transactions
    ]

    total_upi_spend = _quantize(sum((insight.amount for insight in insights), start=Decimal("0.00")))
    merchant_spend = _quantize(
        sum((insight.amount for insight in insights if not insight.is_personal_transfer), start=Decimal("0.00"))
    )
    personal_transfer_spend = _quantize(
        sum((insight.amount for insight in insights if insight.is_personal_transfer), start=Decimal("0.00"))
    )

    daily_spend_totals: dict[date, Decimal] = {}
    daily_category_totals: dict[tuple[date, str], Decimal] = {}
    receiver_totals: dict[str, Decimal] = {}
    receiver_transactions: dict[str, list[UpiTransactionInsight]] = {}

    for insight in insights:
        daily_spend_totals[insight.date] = daily_spend_totals.get(insight.date, Decimal("0.00")) + insight.amount
        key = (insight.date, insight.category)
        daily_category_totals[key] = daily_category_totals.get(key, Decimal("0.00")) + insight.amount
        receiver_totals[insight.receiver_name] = receiver_totals.get(insight.receiver_name, Decimal("0.00")) + insight.amount
        receiver_transactions.setdefault(insight.receiver_name, []).append(insight)

    repeated_payments: list[UpiRecurringPayment] = []
    for receiver_name, receiver_group in receiver_transactions.items():
        if len(receiver_group) < 2:
            continue
        sorted_group = sorted(receiver_group, key=lambda item: item.date)
        day_gaps = [
            (sorted_group[index].date - sorted_group[index - 1].date).days
            for index in range(1, len(sorted_group))
        ]
        cadence = _detect_cadence(day_gaps)
        if cadence == "irregular":
            continue

        amounts = [item.amount for item in sorted_group]
        average_amount = _quantize(sum(amounts, start=Decimal("0.00")) / Decimal(len(amounts)))
        min_amount = min(amounts)
        max_amount = max(amounts)
        variation_ratio = (max_amount - min_amount) / average_amount if average_amount else Decimal("0.00")
        if variation_ratio > Decimal("0.20"):
            continue

        repeated_payments.append(
            UpiRecurringPayment(
                receiver_name=receiver_name,
                cadence=cadence,
                occurrences=len(sorted_group),
                typical_amount=average_amount,
                total_spend=_quantize(sum(amounts, start=Decimal("0.00"))),
                last_seen_date=sorted_group[-1].date,
            )
        )

    repeated_payments = sorted(
        repeated_payments,
        key=lambda payment: (-payment.occurrences, payment.receiver_name.lower()),
    )

    return UpiAnalysisResult(
        total_upi_spend=total_upi_spend,
        merchant_spend=merchant_spend,
        personal_transfer_spend=personal_transfer_spend,
        daily_spend=[
            {"date": spend_date, "amount": _quantize(amount)}
            for spend_date, amount in sorted(daily_spend_totals.items())
        ],
        daily_category_spend=[
            {"date": spend_date, "category": category, "amount": _quantize(amount)}
            for (spend_date, category), amount in sorted(daily_category_totals.items())
        ],
        top_receivers=[
            {"receiver_name": receiver_name, "amount": _quantize(amount)}
            for receiver_name, amount in sorted(receiver_totals.items(), key=lambda item: item[1], reverse=True)[:10]
        ],
        repeated_payments=repeated_payments,
        transactions=insights,
    )
