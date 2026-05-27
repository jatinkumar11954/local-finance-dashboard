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

from app.services.analytics import calculate_overview
from common import (
    benchmark_profile_options,
    default_period,
    format_inr,
    format_percentage,
    initialize_page,
    render_sidebar_status,
    session_scope,
)


initialize_page("Dashboard")
render_sidebar_status()

st.title("Dashboard")
st.caption("Local financial snapshot using the imported transactions only.")

default_start, default_end = default_period()
selected_range = st.date_input("Date range", value=(default_start, default_end))
start_date = selected_range[0] if isinstance(selected_range, tuple) else default_start
end_date = selected_range[1] if isinstance(selected_range, tuple) and len(selected_range) > 1 else default_end
profiles = benchmark_profile_options()
benchmark_profile = st.selectbox(
    "Hyderabad benchmark profile",
    profiles,
    index=profiles.index("Comfortable living") if "Comfortable living" in profiles else 0,
)

with session_scope() as session:
    overview = calculate_overview(
        session=session,
        start_date=start_date,
        end_date=end_date,
        benchmark_profile=benchmark_profile,
    )

metric_top_row = st.columns(3)
metric_bottom_row = st.columns(3)
metric_top_row[0].metric("Income", format_inr(overview.total_income), help=f"Exact: ₹{overview.total_income:,.2f}")
metric_top_row[1].metric("Expenses", format_inr(overview.total_expenses), help=f"Exact: ₹{overview.total_expenses:,.2f}")
metric_top_row[2].metric("Net savings", format_inr(overview.net_savings), help=f"Exact: ₹{overview.net_savings:,.2f}")
metric_bottom_row[0].metric("Savings rate", format_percentage(overview.savings_rate))
metric_bottom_row[1].metric("UPI spend", format_inr(overview.upi_spend), help=f"Exact: ₹{overview.upi_spend:,.2f}")
metric_bottom_row[2].metric("Card spend", format_inr(overview.credit_card_spend), help=f"Exact: ₹{overview.credit_card_spend:,.2f}")

if overview.transaction_count == 0:
    st.info("Upload statements to populate the dashboard.")
    st.stop()

chart_columns = st.columns(2)
with chart_columns[0]:
    st.subheader("Monthly income vs expenses")
    monthly_df = pd.DataFrame([item.model_dump() for item in overview.monthly_trend])
    if not monthly_df.empty:
        monthly_df = monthly_df.set_index("period")[["income", "expenses"]]
        st.bar_chart(monthly_df)
    else:
        st.caption("Not enough data for the selected period.")

with chart_columns[1]:
    st.subheader("Category spend")
    category_df = pd.DataFrame([item.model_dump() for item in overview.top_categories])
    if not category_df.empty:
        category_df = category_df.set_index("label")[["amount"]]
        st.bar_chart(category_df)
    else:
        st.caption("No spending categories available.")

trend_columns = st.columns(2)
with trend_columns[0]:
    st.subheader("Daily spend trend")
    daily_df = pd.DataFrame([item.model_dump() for item in overview.daily_spend])
    if not daily_df.empty:
        daily_df = daily_df.set_index("date")[["amount"]]
        st.line_chart(daily_df)
    else:
        st.caption("No daily spend data available.")

with trend_columns[1]:
    st.subheader("Top merchants")
    merchant_df = pd.DataFrame([item.model_dump() for item in overview.top_merchants])
    if not merchant_df.empty:
        merchant_df.columns = ["Merchant", "Spend"]
        st.dataframe(merchant_df, use_container_width=True, hide_index=True)
    else:
        st.caption("Merchant information is still sparse for this period.")

st.subheader("Hyderabad benchmark comparison")
benchmark_df = pd.DataFrame([item.model_dump() for item in overview.benchmark_comparison])
if benchmark_df.empty:
    st.caption("No benchmark data available.")
else:
    benchmark_df["range_midpoint"] = (benchmark_df["benchmark_min"] + benchmark_df["benchmark_max"]) / 2
    benchmark_df["variance_from_midpoint"] = benchmark_df["actual"] - benchmark_df["range_midpoint"]
    st.dataframe(benchmark_df, use_container_width=True, hide_index=True)
