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

from app.services.analytics import analyze_upi_transactions, list_upi_sources
from common import default_period, format_inr, initialize_page, render_sidebar_status, session_scope


initialize_page("UPI Analysis")
render_sidebar_status()

st.title("UPI Analysis")
st.caption("Inspect local UPI spend patterns, merchants, transfers, and repeated payments.")

default_start, default_end = default_period()
filter_columns = st.columns(3)
selected_range = filter_columns[0].date_input("Date range", value=(default_start, default_end))
with session_scope() as session:
    upi_sources = list_upi_sources(session)
selected_source = filter_columns[1].selectbox("Account source", ["All sources"] + upi_sources)
filter_columns[2].caption("UPI detection uses the normalized local transaction table only.")

start_date = selected_range[0] if isinstance(selected_range, tuple) else default_start
end_date = selected_range[1] if isinstance(selected_range, tuple) and len(selected_range) > 1 else default_end

with session_scope() as session:
    analysis = analyze_upi_transactions(
        session=session,
        start_date=start_date,
        end_date=end_date,
        account_source=None if selected_source == "All sources" else selected_source,
    )

metric_columns = st.columns(5)
metric_columns[0].metric("Total UPI spend", format_inr(analysis.total_upi_spend))
metric_columns[1].metric("UPI transactions", f"{analysis.transaction_count:,}")
metric_columns[2].metric("Average UPI amount", format_inr(analysis.average_transaction_amount))
metric_columns[3].metric("Merchant spend", format_inr(analysis.merchant_spend))
metric_columns[4].metric("Personal transfers", format_inr(analysis.personal_transfer_spend))

if analysis.amount_quality_warning:
    st.warning(analysis.amount_quality_warning)

if not analysis.transactions:
    st.info("No UPI debit transactions matched the current filters.")
    st.stop()
    raise SystemExit

chart_columns = st.columns(2)
with chart_columns[0]:
    st.subheader("Daily UPI spend")
    daily_spend_df = pd.DataFrame(
        [{"date": item["date"], "amount": float(item["amount"])} for item in analysis.daily_spend]
    )
    st.line_chart(daily_spend_df.set_index("date"))

with chart_columns[1]:
    st.subheader("Top receivers / merchants")
    top_receivers_df = pd.DataFrame(
        [
            {
                "receiver_name": item["receiver_name"],
                "transaction_count": item["count"],
                "amount": float(item["amount"]),
            }
            for item in analysis.top_receivers
        ]
    )
    st.dataframe(top_receivers_df, use_container_width=True, hide_index=True)

st.subheader("Repeated UPI payments")
repeated_df = pd.DataFrame(
    [
        {
            "receiver_name": payment.receiver_name,
            "cadence": payment.cadence,
            "occurrences": payment.occurrences,
            "typical_amount": float(payment.typical_amount),
            "total_spend": float(payment.total_spend),
            "last_seen_date": payment.last_seen_date,
        }
        for payment in analysis.repeated_payments
    ]
)
if repeated_df.empty:
    st.caption("No repeated UPI payment patterns detected in the selected range.")
else:
    st.dataframe(repeated_df, use_container_width=True, hide_index=True)

st.subheader("Daily category-wise UPI spend")
daily_category_df = pd.DataFrame(
    [
        {
            "date": item["date"],
            "category": item["category"],
            "amount": float(item["amount"]),
        }
        for item in analysis.daily_category_spend
    ]
)
st.dataframe(daily_category_df, use_container_width=True, hide_index=True)

st.subheader("UPI transactions")
transactions_df = pd.DataFrame(
    [
        {
            "date": insight.date,
            "receiver_name": insight.receiver_name,
            "amount": float(insight.amount),
            "category": insight.category,
            "personal_transfer": insight.is_personal_transfer,
            "raw_description": insight.raw_description,
        }
        for insight in analysis.transactions
    ]
)
st.dataframe(transactions_df, use_container_width=True, hide_index=True)
