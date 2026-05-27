from __future__ import annotations

from pathlib import Path
import sys

DASHBOARD_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = DASHBOARD_DIR.parent
for path in (PROJECT_ROOT, DASHBOARD_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import streamlit as st

from common import initialize_page, render_sidebar_status


initialize_page("Local Finance Intelligence Dashboard")
render_sidebar_status()

st.title("Local Finance Intelligence Dashboard")
st.caption("Offline-first personal finance intelligence for local statement parsing and analysis.")

st.markdown(
    """
    Phase 5 is ready for:

    - CSV, XLSX, and digital PDF uploads stored only on local disk
    - Transaction normalization into a local SQLite database
    - Rule-based categorization with editable local rules
    - Bulk transaction correction and rule re-application
    - Core dashboard metrics, trends, and Hyderabad benchmark comparison
    - Home loan amortization, outstanding balance, and prepayment scenarios
    - Credit card fee, interest, and risk-pattern analysis
    - UPI daily spend, receiver, and repeated-payment analysis
    - Local finance assistant with deterministic local-query handlers and keyword search
    """
)

st.info(
    "Use Upload first, then review Transactions, Dashboard, Loans, Credit Cards, UPI Analysis, and Rules and Benchmarks as needed."
)
