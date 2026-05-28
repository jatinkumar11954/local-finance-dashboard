from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from sqlalchemy.orm import Session

from app.services.analytics.unified_transaction_analytics import AnalyticsFilters, build_analytics_response, money_float


EXTRA_CHARGE_TYPES = {
    "gst_on_fee",
    "gst_on_interest",
    "gst_on_processing_fee",
    "gst_on_late_fee",
    "gst_on_finance_charge",
    "gst_unknown",
    "interest_charge",
    "emi_interest",
    "late_fee",
    "cash_withdrawal_charge",
    "processing_fee",
    "annual_fee",
    "over_limit_fee",
    "fee",
    "finance_charge",
    "other_charge",
}


def get_credit_card_analytics(session: Session, filters: AnalyticsFilters) -> dict:
    card_filters = replace(filters, source_type="credit_card_statement")
    response = build_analytics_response(session, card_filters)
    rows = response["tables"]["transactions"]
    by_card: dict[str, Decimal] = {}
    extra_charges = Decimal("0.00")
    card_payments = Decimal("0.00")
    for row in rows:
        card = str(row["source_card_id"] or "unknown_card")
        by_card[card] = by_card.get(card, Decimal("0.00")) + Decimal(str(row["true_expense"]))
        if row.get("credit_card_parsed_type") in EXTRA_CHARGE_TYPES:
            extra_charges += Decimal(str(row["amount"]))
        if row["transaction_type"] == "credit" and row.get("credit_card_parsed_type") in {"payment", "payment_or_credit"}:
            card_payments += Decimal(str(row["amount"]))
    response["summary"].update(
        {
            "card_payments_received": money_float(card_payments),
            "extra_charges": money_float(extra_charges),
            "upi_only_card_spend": sum(row["true_expense"] for row in rows if row.get("source_card_usage_type") == "upi_only"),
        }
    )
    response["charts"]["card_wise_spend"] = [
        {"card_id": card_id, "amount": money_float(amount)}
        for card_id, amount in sorted(by_card.items(), key=lambda item: item[1], reverse=True)
    ]
    response["tables"]["fees_interest_gst"] = [row for row in rows if row.get("credit_card_parsed_type") in EXTRA_CHARGE_TYPES]
    response["tables"]["upi_only"] = [row for row in rows if row.get("source_card_usage_type") == "upi_only" or row["transaction_channel"] == "upi"]
    response["tables"]["emi"] = [row for row in rows if row["is_credit_card_emi"]]
    return response

