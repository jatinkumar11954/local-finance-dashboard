from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from sqlalchemy.orm import Session

from app.services.analytics.unified_transaction_analytics import AnalyticsFilters, build_analytics_response, money_float


def get_upi_analytics(session: Session, filters: AnalyticsFilters) -> dict:
    upi_filters = replace(filters, transaction_channel="upi")
    response = build_analytics_response(session, upi_filters)
    rows = response["tables"]["transactions"]
    receivers: dict[str, dict[str, Decimal | int | str]] = {}
    small_frequent: dict[str, dict[str, Decimal | int | str]] = {}
    for row in rows:
        receiver = row["counterparty_name"] or "Unknown"
        item = receivers.setdefault(receiver, {"receiver": receiver, "amount": Decimal("0.00"), "count": 0})
        item["amount"] = item["amount"] + Decimal(str(row["true_expense"]))
        item["count"] = int(item["count"]) + 1
        if row["true_expense"] <= 300 and row["true_expense"] > 0:
            small = small_frequent.setdefault(receiver, {"receiver": receiver, "amount": Decimal("0.00"), "count": 0})
            small["amount"] = small["amount"] + Decimal(str(row["true_expense"]))
            small["count"] = int(small["count"]) + 1
    response["charts"]["upi_receivers"] = [
        {"receiver": key, "amount": money_float(item["amount"]), "count": item["count"]}
        for key, item in sorted(receivers.items(), key=lambda item: item[1]["amount"], reverse=True)[:20]
    ]
    person_transfer_amount = sum(
        row["amount"]
        for row in rows
        if row["is_internal_transfer"] and row["transaction_type"] == "debit"
    )
    merchant_payment_amount = sum(row["true_expense"] for row in rows if not row["is_internal_transfer"])
    response["charts"]["person_vs_merchant"] = [
        {"type": "person_transfer", "amount": person_transfer_amount},
        {"type": "merchant_payment", "amount": merchant_payment_amount},
    ]
    response["tables"]["small_frequent_payments"] = [
        {"receiver": key, "amount": money_float(item["amount"]), "count": item["count"]}
        for key, item in sorted(small_frequent.items(), key=lambda item: (item[1]["count"], item[1]["amount"]), reverse=True)
        if int(item["count"]) >= 3
    ]
    response["tables"]["repeated_payments"] = response["tables"]["recurring"]
    return response
