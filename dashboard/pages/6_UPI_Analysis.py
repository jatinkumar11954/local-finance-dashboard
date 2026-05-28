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

from app.services.analytics import AnalyticsFilters, get_upi_analytics
from common import default_period, format_inr, initialize_page, render_sidebar_status, session_scope


SOURCE_OPTIONS = {
    "All UPI sources": "all_sources",
    "Bank statement UPI": "bank_statement",
    "UPI exports": "upi_export",
    "Credit card UPI": "credit_card_statement",
}


initialize_page("UPI Analysis")
render_sidebar_status()

st.title("UPI Analysis")
st.caption("UPI analytics across bank statements, UPI exports, and UPI-only credit card statements.")

default_start, default_end = default_period()
filter_columns = st.columns(4)
selected_range = filter_columns[0].date_input("Date range", value=(default_start, default_end))
source_label = filter_columns[1].selectbox("UPI source", list(SOURCE_OPTIONS.keys()))
category = filter_columns[2].text_input("Category filter")
merchant = filter_columns[3].text_input("Receiver / merchant")

start_date = selected_range[0] if isinstance(selected_range, tuple) else default_start
end_date = selected_range[1] if isinstance(selected_range, tuple) and len(selected_range) > 1 else default_end

with session_scope() as session:
    response = get_upi_analytics(
        session,
        AnalyticsFilters(
            start_date=start_date,
            end_date=end_date,
            source_type=SOURCE_OPTIONS[source_label],
            category=category or None,
            merchant=merchant or None,
            transaction_channel="upi",
            include_internal_transfers=True,
        ),
    )

summary = response["summary"]
person_vs_merchant = {row["type"]: row["amount"] for row in response["charts"]["person_vs_merchant"]}
merchant_upi_spend = person_vs_merchant.get("merchant_payment", summary["upi_spend"])
person_transfer_movement = person_vs_merchant.get("person_transfer", 0)
total_upi_movement = merchant_upi_spend + person_transfer_movement
metric_columns = st.columns(5)
metric_columns[0].metric("Merchant UPI spend", format_inr(merchant_upi_spend))
metric_columns[1].metric("UPI transactions", f"{summary['transaction_count']:,}")
metric_columns[2].metric("Average UPI debit", format_inr(total_upi_movement / summary["transaction_count"] if summary["transaction_count"] else 0))
metric_columns[3].metric("UPI movement", format_inr(total_upi_movement))
metric_columns[4].metric("Person transfers", format_inr(person_transfer_movement))

if summary["transaction_count"] == 0:
    st.info("No UPI transactions matched the current filters.")
    st.stop()

chart_columns = st.columns(2)
with chart_columns[0]:
    st.subheader("Daily UPI spend")
    daily_df = pd.DataFrame(response["charts"]["daily_spend"])
    if daily_df.empty:
        st.caption("No daily UPI data.")
    else:
        st.line_chart(daily_df.set_index("date")[["amount"]])

with chart_columns[1]:
    st.subheader("UPI spend by source")
    source_df = pd.DataFrame(response["charts"]["source_comparison"])
    if source_df.empty:
        st.caption("No source data.")
    else:
        st.bar_chart(source_df.set_index("source_type")[["true_expense"]])

detail_columns = st.columns(2)
with detail_columns[0]:
    st.subheader("Top UPI receivers")
    receiver_df = pd.DataFrame(response["charts"]["upi_receivers"])
    if receiver_df.empty:
        st.caption("No receiver data.")
    else:
        st.dataframe(receiver_df, use_container_width=True, hide_index=True)

with detail_columns[1]:
    st.subheader("Weekday vs weekend UPI spend")
    weekday_df = pd.DataFrame(response["charts"]["weekday_weekend_spend"])
    st.bar_chart(weekday_df.set_index("day_type")[["amount"]])

st.subheader("Repeated UPI payments")
repeated_df = pd.DataFrame(response["tables"]["repeated_payments"])
if repeated_df.empty:
    st.caption("No repeated UPI payment patterns detected.")
else:
    st.dataframe(repeated_df, use_container_width=True, hide_index=True)

st.subheader("Small frequent UPI payments")
small_df = pd.DataFrame(response["tables"]["small_frequent_payments"])
if small_df.empty:
    st.caption("No small frequent UPI pattern detected.")
else:
    st.dataframe(small_df, use_container_width=True, hide_index=True)

st.subheader("Person vs merchant")
person_df = pd.DataFrame(response["charts"]["person_vs_merchant"])
st.bar_chart(person_df.set_index("type")[["amount"]])

st.subheader("UPI transactions")
transactions_df = pd.DataFrame(response["tables"]["transactions"])
st.dataframe(transactions_df, use_container_width=True, hide_index=True)
