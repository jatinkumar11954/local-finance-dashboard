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
from app.services.category_rules import reapply_category_rules
from app.services.transactions import bulk_update_transactions, query_transactions
from common import (
    category_options,
    default_period,
    document_options,
    initialize_page,
    render_sidebar_status,
    session_scope,
)


initialize_page("Transactions")
render_sidebar_status()

st.title("Transactions")
st.caption("Review parsed transactions, reapply rules, and correct data in bulk.")

default_start, default_end = default_period()
categories = category_options()
documents = document_options()

filter_columns = st.columns(4)
selected_range = filter_columns[0].date_input("Date range", value=(default_start, default_end))
merchant_query = filter_columns[1].text_input("Merchant search")
payment_mode = filter_columns[2].selectbox(
    "Payment mode",
    ["", "UPI", "CARD", "IMPS", "NEFT", "RTGS", "NETBANKING", "AUTOPAY", "EMI", "CHEQUE", "CASH", "unknown"],
)
category = filter_columns[3].selectbox("Category", [""] + categories)

extra_filter_columns = st.columns(4)
document_label = extra_filter_columns[0].selectbox("Statement file", [""] + [label for label, _ in documents])
transaction_type = extra_filter_columns[1].selectbox("Transaction type", ["", "debit", "credit"])
show_low_confidence_only = extra_filter_columns[2].checkbox("Only confidence <= 0.75")
include_excluded = extra_filter_columns[3].checkbox("Include excluded rows", value=True)

document_lookup = {label: document_id for label, document_id in documents}
start_date = selected_range[0] if isinstance(selected_range, tuple) else default_start
end_date = selected_range[1] if isinstance(selected_range, tuple) and len(selected_range) > 1 else default_end

with session_scope() as session:
    transactions = query_transactions(
        session=session,
        start_date=start_date,
        end_date=end_date,
        category=category or None,
        payment_mode=payment_mode or None,
        merchant_query=merchant_query or None,
        transaction_type=transaction_type or None,
        document_id=document_lookup.get(document_label),
        max_confidence=0.75 if show_low_confidence_only else None,
        include_excluded=include_excluded,
    )

if not transactions:
    st.info("No transactions matched the current filters.")
    st.stop()
    raise SystemExit

summary_columns = st.columns(4)
summary_columns[0].metric("Rows", len(transactions))
summary_columns[1].metric("Low confidence", sum(1 for tx in transactions if tx.confidence_score <= 0.75))
summary_columns[2].metric("Excluded", sum(1 for tx in transactions if tx.is_excluded))
summary_columns[3].metric("Recurring", sum(1 for tx in transactions if tx.is_recurring))

action_columns = st.columns(2)
if action_columns[0].button("Reapply category rules to filtered rows", use_container_width=True):
    with session_scope() as session:
        updated_count = reapply_category_rules(
            session=session,
            transaction_ids=[transaction.id for transaction in transactions],
        )
    st.success(f"Reapplied rules to {updated_count} transactions.")
    st.rerun()

if action_columns[1].button("Reapply rules only to low-confidence filtered rows", use_container_width=True):
    with session_scope() as session:
        updated_count = reapply_category_rules(
            session=session,
            transaction_ids=[transaction.id for transaction in transactions],
            only_low_confidence=True,
        )
    st.success(f"Reapplied rules to {updated_count} low-confidence transactions.")
    st.rerun()

original_df = pd.DataFrame(
    [
        {
            "transaction_id": transaction.id,
            "date": transaction.date,
            "amount": float(transaction.amount),
            "transaction_type": transaction.transaction_type,
            "payment_mode": transaction.payment_mode,
            "confidence_score": transaction.confidence_score,
            "merchant_name": transaction.merchant_name or "",
            "category": transaction.category,
            "subcategory": transaction.subcategory or "",
            "is_recurring": transaction.is_recurring,
            "is_personal_transfer": transaction.is_personal_transfer,
            "is_business_expense": transaction.is_business_expense,
            "is_excluded": transaction.is_excluded,
            "notes": transaction.notes or "",
            "raw_description": transaction.raw_description,
        }
        for transaction in transactions
    ]
).set_index("transaction_id")

st.subheader("Bulk correction grid")
edited_df = st.data_editor(
    original_df,
    use_container_width=True,
    hide_index=False,
    disabled=["date", "amount", "transaction_type", "payment_mode", "confidence_score", "raw_description"],
    column_config={
        "category": st.column_config.SelectboxColumn("Category", options=categories, required=True),
        "subcategory": st.column_config.TextColumn("Subcategory"),
        "merchant_name": st.column_config.TextColumn("Merchant"),
        "notes": st.column_config.TextColumn("Notes", width="large"),
        "is_recurring": st.column_config.CheckboxColumn("Recurring"),
        "is_personal_transfer": st.column_config.CheckboxColumn("Personal transfer"),
        "is_business_expense": st.column_config.CheckboxColumn("Business expense"),
        "is_excluded": st.column_config.CheckboxColumn("Excluded"),
        "confidence_score": st.column_config.NumberColumn("Confidence", format="%.2f"),
        "raw_description": st.column_config.TextColumn("Raw description", width="large"),
    },
)

if st.button("Save edited transactions", type="primary", use_container_width=True):
    updates: list[dict[str, object]] = []
    for transaction_id, edited_row in edited_df.iterrows():
        original_row = original_df.loc[transaction_id]
        payload_data: dict[str, object] = {}
        for field_name in [
            "category",
            "subcategory",
            "merchant_name",
            "notes",
            "is_recurring",
            "is_personal_transfer",
            "is_business_expense",
            "is_excluded",
        ]:
            original_value = original_row[field_name]
            edited_value = edited_row[field_name]
            if pd.isna(edited_value):
                edited_value = ""
            if pd.isna(original_value):
                original_value = ""

            normalized_original = None if original_value == "" else original_value
            normalized_edited = None if edited_value == "" else edited_value
            if normalized_original != normalized_edited:
                payload_data[field_name] = normalized_edited

        if payload_data:
            updates.append({"transaction_id": int(transaction_id), "updates": TransactionUpdate(**payload_data)})

    if not updates:
        st.info("No transaction changes detected.")
    else:
        with session_scope() as session:
            updated_count = bulk_update_transactions(session, updates)
        st.success(f"Saved updates for {updated_count} transactions.")
        st.rerun()
