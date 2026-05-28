from __future__ import annotations

from dataclasses import replace

from sqlalchemy.orm import Session

from app.services.analytics.unified_transaction_analytics import AnalyticsFilters, build_analytics_response


def get_bank_analytics(session: Session, filters: AnalyticsFilters) -> dict:
    bank_filters = replace(filters, source_type="bank_statement")
    response = build_analytics_response(session, bank_filters)
    rows = response["tables"]["transactions"]
    response["summary"].update(
        {
            "bank_upi_spend": sum(row["true_expense"] for row in rows if row["transaction_channel"] == "upi"),
            "credit_card_bill_payments": sum(row["amount"] for row in rows if row["is_credit_card_payment"]),
            "loan_payments": sum(row["amount"] for row in rows if row["is_loan_emi"] or row["is_loan_prepayment"]),
            "internal_transfers": sum(row["amount"] for row in rows if row["is_internal_transfer"]),
        }
    )
    response["tables"]["credit_card_payments"] = [row for row in rows if row["is_credit_card_payment"]]
    response["tables"]["loan_payments"] = [row for row in rows if row["is_loan_emi"] or row["is_loan_prepayment"]]
    response["tables"]["internal_transfers"] = [row for row in rows if row["is_internal_transfer"]]
    return response
