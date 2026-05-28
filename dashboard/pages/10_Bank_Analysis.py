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

from app.services.analytics import AnalyticsFilters, get_bank_analytics
from common import default_period, format_inr, initialize_page, render_sidebar_status, session_scope


initialize_page("Bank Analysis")
render_sidebar_status()

st.title("Bank Statement Analysis")
st.caption("Bank-only analytics. Credit card bill payments and loan payments are separated from normal spending.")

default_start, default_end = default_period()
filter_columns = st.columns(4)
selected_range = filter_columns[0].date_input("Date range", value=(default_start, default_end))
category = filter_columns[1].text_input("Category filter")
merchant = filter_columns[2].text_input("Merchant filter")
include_internal = filter_columns[3].checkbox("Include internal transfers", value=True)

start_date = selected_range[0] if isinstance(selected_range, tuple) else default_start
end_date = selected_range[1] if isinstance(selected_range, tuple) and len(selected_range) > 1 else default_end

with session_scope() as session:
    response = get_bank_analytics(
        session,
        AnalyticsFilters(
            start_date=start_date,
            end_date=end_date,
            source_type="bank_statement",
            category=category or None,
            merchant=merchant or None,
            include_internal_transfers=include_internal,
            include_credit_card_bill_payments=True,
        ),
    )

summary = response["summary"]
metric_columns = st.columns(5)
metric_columns[0].metric("Bank income", format_inr(summary["total_income"]))
metric_columns[1].metric("Bank true spend", format_inr(summary["true_expense"]))
metric_columns[2].metric("Credit card payments", format_inr(summary["credit_card_bill_payments"]))
metric_columns[3].metric("Loan payments", format_inr(summary["loan_payments"]))
metric_columns[4].metric("Internal transfers", format_inr(summary["internal_transfers"]))

if summary["transaction_count"] == 0:
    st.info("No bank statement transactions matched the filters.")
    st.stop()

chart_columns = st.columns(2)
with chart_columns[0]:
    st.subheader("Monthly income vs true expense")
    monthly_df = pd.DataFrame(response["charts"]["monthly_trend"])
    if monthly_df.empty:
        st.caption("No monthly data.")
    else:
        st.bar_chart(monthly_df.set_index("period")[["income", "true_expense", "liability_payment"]])

with chart_columns[1]:
    st.subheader("Bank debits by category")
    category_df = pd.DataFrame(response["charts"]["category_breakdown"])
    if category_df.empty:
        st.caption("No bank category spend.")
    else:
        st.bar_chart(category_df.set_index("category")[["amount"]])

st.subheader("Credit card bill payments")
cc_payment_df = pd.DataFrame(response["tables"]["credit_card_payments"])
if cc_payment_df.empty:
    st.caption("No credit card bill payments detected.")
else:
    st.dataframe(cc_payment_df, use_container_width=True, hide_index=True)

st.subheader("Loan EMI / MBK prepayments")
loan_payment_df = pd.DataFrame(response["tables"]["loan_payments"])
if loan_payment_df.empty:
    st.caption("No loan payments detected in bank statements.")
else:
    st.dataframe(loan_payment_df, use_container_width=True, hide_index=True)

st.subheader("Large debits and credits")
transactions_df = pd.DataFrame(response["tables"]["transactions"])
if transactions_df.empty:
    st.caption("No transactions.")
else:
    large_df = transactions_df.sort_values("amount", ascending=False).head(25)
    st.dataframe(large_df, use_container_width=True, hide_index=True)
