from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import streamlit as st

DASHBOARD_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = DASHBOARD_DIR.parent
for path in (PROJECT_ROOT, DASHBOARD_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.schemas.transaction import TransactionUpdate
from app.services.analytics import AnalyticsFilters, build_analytics_response
from app.services.transactions import bulk_update_transactions
from common import category_options, default_period, format_inr, initialize_page, render_sidebar_status, session_scope


SOURCE_OPTIONS = {
    "All sources": "all_sources",
    "Bank statements": "bank_statement",
    "Credit card statements": "credit_card_statement",
    "UPI exports": "upi_export",
    "Loan statements": "loan_statement",
    "Manual / unknown": "manual",
}
CHANNELS = ["", "upi", "card", "bank_transfer", "cash", "emi", "loan", "wallet", "unknown"]
CLASSIFICATION_OPTIONS = [
    "true_expense",
    "internal_transfer",
    "credit_card_payment",
    "loan_emi",
    "loan_prepayment",
    "refund",
    "cashback",
    "exclude",
    "review",
]
CLASSIFICATION_TAGS = {
    "internal_transfer",
    "credit_card_payment",
    "loan_emi",
    "loan_prepayment",
    "refund",
    "cashback",
    "needs_review",
}


def tags_to_text(tags) -> str:
    return ", ".join(tags or [])


def text_to_tags(value: str) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def classification_from_row(row: pd.Series) -> str:
    if row["is_excluded_from_analysis"]:
        return "exclude"
    if row["is_internal_transfer"]:
        return "internal_transfer"
    if row["is_credit_card_payment"]:
        return "credit_card_payment"
    if row["is_loan_emi"]:
        return "loan_emi"
    if row["is_loan_prepayment"]:
        return "loan_prepayment"
    if row["is_refund"]:
        return "refund"
    if row["is_cashback"]:
        return "cashback"
    if row["true_expense"] > 0:
        return "true_expense"
    return "review"


def apply_classification_payload(classification: str, edited_tags: list[str], payload: dict) -> list[str]:
    cleaned_tags = [tag for tag in edited_tags if tag not in CLASSIFICATION_TAGS]
    if classification == "true_expense":
        payload["is_personal_transfer"] = False
        payload["is_excluded"] = False
        return cleaned_tags
    if classification == "internal_transfer":
        payload["is_personal_transfer"] = True
        payload["category"] = "Family / Personal Transfers"
        return cleaned_tags + ["internal_transfer"]
    if classification == "credit_card_payment":
        payload["is_personal_transfer"] = False
        payload["category"] = "Credit Card Payment"
        return cleaned_tags + ["credit_card_payment"]
    if classification == "loan_emi":
        payload["is_personal_transfer"] = False
        payload["category"] = "Home Loan EMI"
        return cleaned_tags + ["loan_emi"]
    if classification == "loan_prepayment":
        payload["is_personal_transfer"] = False
        payload["category"] = "Loan Prepayment"
        return cleaned_tags + ["loan_prepayment"]
    if classification == "refund":
        payload["is_excluded"] = False
        return cleaned_tags + ["refund"]
    if classification == "cashback":
        payload["is_excluded"] = False
        return cleaned_tags + ["cashback"]
    if classification == "exclude":
        payload["is_excluded"] = True
        return cleaned_tags
    if classification == "review":
        return cleaned_tags + ["needs_review"]
    return edited_tags


initialize_page("All Transactions")
render_sidebar_status()

st.title("All Transactions / Unified Analysis")
st.caption("Unified transaction center with source filtering and true-spend deduplication.")

default_start, default_end = default_period()
categories = category_options()
filter_columns = st.columns(5)
selected_range = filter_columns[0].date_input("Date range", value=(default_start, default_end))
source_label = filter_columns[1].selectbox("Source", list(SOURCE_OPTIONS.keys()))
channel = filter_columns[2].selectbox("Channel", CHANNELS)
category = filter_columns[3].selectbox("Category", [""] + categories)
merchant = filter_columns[4].text_input("Merchant")

extra_columns = st.columns(3)
include_internal = extra_columns[0].checkbox("Include internal transfers", value=False)
include_card_payments = extra_columns[1].checkbox("Include credit card bill payments", value=False)
include_excluded = extra_columns[2].checkbox("Include excluded", value=True)

start_date = selected_range[0] if isinstance(selected_range, tuple) else default_start
end_date = selected_range[1] if isinstance(selected_range, tuple) and len(selected_range) > 1 else default_end

filters = AnalyticsFilters(
    start_date=start_date,
    end_date=end_date,
    source_type=SOURCE_OPTIONS[source_label],
    category=category or None,
    merchant=merchant or None,
    transaction_channel=channel or None,
    include_internal_transfers=include_internal,
    include_credit_card_bill_payments=include_card_payments,
    include_excluded=include_excluded,
)

with session_scope() as session:
    response = build_analytics_response(session, filters)

summary = response["summary"]
metric_columns = st.columns(5)
metric_columns[0].metric("True expense", format_inr(summary["true_expense"]))
metric_columns[1].metric("Gross debit", format_inr(summary["gross_debit"]))
metric_columns[2].metric("Liability payments", format_inr(summary["liability_payment"]))
metric_columns[3].metric("Refund/cashback", format_inr(summary["refund_adjustment"] + summary["cashback_adjustment"]))
metric_columns[4].metric("Rows", f"{summary['transaction_count']:,}")

chart_columns = st.columns(2)
with chart_columns[0]:
    st.subheader("Source-wise spend")
    source_df = pd.DataFrame(response["charts"]["source_comparison"])
    if source_df.empty:
        st.caption("No source data.")
    else:
        st.bar_chart(source_df.set_index("source_type")[["true_expense", "liability_payment"]])

with chart_columns[1]:
    st.subheader("Month-over-month category movement")
    movement_df = pd.DataFrame(response["charts"]["category_month_movement"])
    if movement_df.empty:
        st.caption("No category movement.")
    else:
        st.dataframe(movement_df.head(20), use_container_width=True, hide_index=True)

transactions_df = pd.DataFrame(response["tables"]["transactions"])
if transactions_df.empty:
    st.info("No transactions matched the current filters.")
    st.stop()

st.download_button(
    "Export filtered transactions CSV",
    data=transactions_df.to_csv(index=False).encode("utf-8"),
    file_name="local_finance_filtered_transactions.csv",
    mime="text/csv",
    use_container_width=True,
)

st.subheader("Unified correction grid")
editable_df = transactions_df[
    [
        "id",
        "transaction_date",
        "source_type",
        "transaction_channel",
        "amount",
        "transaction_type",
        "true_expense",
        "liability_payment",
        "merchant_name",
        "category",
        "is_internal_transfer",
        "is_credit_card_payment",
        "is_loan_emi",
        "is_loan_prepayment",
        "is_refund",
        "is_cashback",
        "is_excluded_from_analysis",
        "tags",
        "raw_description",
    ]
].copy()
editable_df["tags"] = editable_df["tags"].apply(tags_to_text)
editable_df["classification"] = editable_df.apply(classification_from_row, axis=1)
editable_df = editable_df.set_index("id")

edited_df = st.data_editor(
    editable_df,
    use_container_width=True,
    disabled=[
        "transaction_date",
        "source_type",
        "transaction_channel",
        "amount",
        "transaction_type",
        "true_expense",
        "liability_payment",
        "is_credit_card_payment",
        "is_loan_emi",
        "is_loan_prepayment",
        "is_refund",
        "is_cashback",
        "raw_description",
    ],
    column_config={
        "category": st.column_config.SelectboxColumn("Category", options=categories),
        "classification": st.column_config.SelectboxColumn("Classification", options=CLASSIFICATION_OPTIONS),
        "merchant_name": st.column_config.TextColumn("Merchant"),
        "is_internal_transfer": st.column_config.CheckboxColumn("Internal/person transfer"),
        "is_excluded_from_analysis": st.column_config.CheckboxColumn("Excluded"),
        "tags": st.column_config.TextColumn("Tags, comma-separated"),
        "raw_description": st.column_config.TextColumn("Raw description", width="large"),
    },
)

st.caption("To classify credit card payment, loan EMI/prepayment, refund, or cashback, set the category/tags accordingly and save. Analytics recalculates from local data.")
if st.button("Save unified transaction corrections", type="primary", use_container_width=True):
    updates = []
    for transaction_id, edited_row in edited_df.iterrows():
        original_row = editable_df.loc[transaction_id]
        payload = {}
        if edited_row["category"] != original_row["category"]:
            payload["category"] = edited_row["category"]
        if (edited_row["merchant_name"] or "") != (original_row["merchant_name"] or ""):
            payload["merchant_name"] = edited_row["merchant_name"] or None
        if bool(edited_row["is_internal_transfer"]) != bool(original_row["is_internal_transfer"]):
            payload["is_personal_transfer"] = bool(edited_row["is_internal_transfer"])
        if bool(edited_row["is_excluded_from_analysis"]) != bool(original_row["is_excluded_from_analysis"]):
            payload["is_excluded"] = bool(edited_row["is_excluded_from_analysis"])
        edited_tags = text_to_tags(edited_row["tags"])
        original_tags = text_to_tags(original_row["tags"])
        if edited_row["classification"] != original_row["classification"]:
            edited_tags = apply_classification_payload(edited_row["classification"], edited_tags, payload)
        if edited_tags != original_tags:
            payload["tags"] = edited_tags
        if payload:
            updates.append({"transaction_id": int(transaction_id), "updates": TransactionUpdate(**payload)})

    if not updates:
        st.info("No changes detected.")
    else:
        with session_scope() as session:
            updated = bulk_update_transactions(session, updates)
        st.success(f"Saved {updated} transaction update(s).")
        st.rerun()

st.subheader("Top 20 transactions")
st.dataframe(pd.DataFrame(response["tables"]["top_transactions"]), use_container_width=True, hide_index=True)
