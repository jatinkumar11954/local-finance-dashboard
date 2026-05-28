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

from app.services.analytics import AnalyticsFilters, get_overview_analytics
from common import benchmark_profile_options, default_period, format_inr, format_percentage, initialize_page, render_sidebar_status, session_scope


SOURCE_OPTIONS = {
    "All sources": "all_sources",
    "Bank statements": "bank_statement",
    "Credit card statements": "credit_card_statement",
    "UPI exports": "upi_export",
    "Loan statements": "loan_statement",
}


initialize_page("Dashboard")
render_sidebar_status()

st.title("Overview Dashboard")
st.caption("Combined local financial health across bank, credit card, UPI, and loan sources.")

default_start, default_end = default_period()
filter_columns = st.columns(4)
selected_range = filter_columns[0].date_input("Date range", value=(default_start, default_end))
source_label = filter_columns[1].selectbox("Source", list(SOURCE_OPTIONS.keys()))
profiles = benchmark_profile_options()
benchmark_profile = filter_columns[2].selectbox(
    "Hyderabad profile",
    profiles,
    index=profiles.index("Comfortable living") if "Comfortable living" in profiles else 0,
)
include_internal = filter_columns[3].checkbox("Include transfers", value=False)

start_date = selected_range[0] if isinstance(selected_range, tuple) else default_start
end_date = selected_range[1] if isinstance(selected_range, tuple) and len(selected_range) > 1 else default_end

with session_scope() as session:
    response = get_overview_analytics(
        session,
        AnalyticsFilters(
            start_date=start_date,
            end_date=end_date,
            source_type=SOURCE_OPTIONS[source_label],
            include_internal_transfers=include_internal,
            benchmark_profile=benchmark_profile,
        ),
    )

summary = response["summary"]
metric_top = st.columns(4)
metric_mid = st.columns(4)
metric_bottom = st.columns(4)
metric_top[0].metric("Income", format_inr(summary["total_income"]))
metric_top[1].metric("True expense", format_inr(summary["true_expense"]))
metric_top[2].metric("Net savings", format_inr(summary["net_savings"]))
metric_top[3].metric("Savings rate", format_percentage(summary["savings_rate"]))
metric_mid[0].metric("Gross debit", format_inr(summary["gross_debit"]))
metric_mid[1].metric("Liability payments", format_inr(summary["liability_payment"]))
metric_mid[2].metric("EMI burden", format_inr(summary["total_emi_burden"]))
metric_mid[3].metric("EMI / income", format_percentage(summary["emi_to_income_ratio"]))
metric_bottom[0].metric("Credit card spend", format_inr(summary["credit_card_spend"]))
metric_bottom[1].metric("UPI spend", format_inr(summary["upi_spend"]))
metric_bottom[2].metric("Bank spend", format_inr(summary["bank_account_spend"]))
metric_bottom[3].metric("Debt interest", format_inr(summary["debt_interest"]))

score = summary["spend_quality_score"]
st.info(f"Spend quality score: {score['score']}/100. {score['explanation']}")

if summary["transaction_count"] == 0:
    st.info("No transactions matched the current filters.")
    st.stop()

chart_columns = st.columns(2)
with chart_columns[0]:
    st.subheader("Monthly income, true expense, and gross debit")
    monthly_df = pd.DataFrame(response["charts"]["monthly_trend"])
    if monthly_df.empty:
        st.caption("No monthly trend available.")
    else:
        st.bar_chart(monthly_df.set_index("period")[["income", "true_expense", "gross_debit"]])

with chart_columns[1]:
    st.subheader("True expense vs gross debit")
    true_vs_gross_df = pd.DataFrame(response["charts"]["true_expense_vs_gross_debit"])
    st.bar_chart(true_vs_gross_df.set_index("label")[["amount"]])

trend_columns = st.columns(2)
with trend_columns[0]:
    st.subheader("Category spend")
    category_df = pd.DataFrame(response["charts"]["category_breakdown"])
    if category_df.empty:
        st.caption("No category spend.")
    else:
        st.bar_chart(category_df.set_index("category")[["amount"]])

with trend_columns[1]:
    st.subheader("Source-wise spend")
    source_df = pd.DataFrame(response["charts"]["source_comparison"])
    if source_df.empty:
        st.caption("No source comparison.")
    else:
        st.bar_chart(source_df.set_index("source_type")[["true_expense", "liability_payment"]])

detail_columns = st.columns(2)
with detail_columns[0]:
    st.subheader("Daily spend")
    daily_df = pd.DataFrame(response["charts"]["daily_spend"])
    if daily_df.empty:
        st.caption("No daily spend.")
    else:
        st.line_chart(daily_df.set_index("date")[["amount"]])

with detail_columns[1]:
    st.subheader("Top merchants")
    merchant_df = pd.DataFrame(response["charts"]["merchant_breakdown"])
    if merchant_df.empty:
        st.caption("No merchant data.")
    else:
        st.bar_chart(merchant_df.set_index("merchant")[["amount"]])

st.subheader("Recurring commitments")
recurring_df = pd.DataFrame(response["tables"]["recurring"])
if recurring_df.empty:
    st.caption("No recurring patterns detected.")
else:
    st.dataframe(recurring_df, use_container_width=True, hide_index=True)

st.subheader("Anomalies requiring review")
anomaly_df = pd.DataFrame(response["tables"]["anomalies"])
if anomaly_df.empty:
    st.caption("No anomalies detected.")
else:
    st.dataframe(anomaly_df, use_container_width=True, hide_index=True)

st.subheader("Hyderabad benchmark / budget comparison")
budget_df = pd.DataFrame(response["tables"]["budget_comparison"])
if budget_df.empty:
    st.caption("No benchmark data available.")
else:
    st.dataframe(budget_df, use_container_width=True, hide_index=True)
