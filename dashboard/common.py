from __future__ import annotations

import sys
from contextlib import contextmanager
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import streamlit as st


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.bootstrap import bootstrap_application, reset_local_data
from app.config import get_settings
from app.database import get_session_factory
from app.services.benchmarks import list_benchmark_profiles
from app.services.documents import list_documents
from app.services.transactions import list_categories
from app.utils.security import verify_password


def initialize_page(title: str) -> None:
    bootstrap_application()
    st.set_page_config(page_title=title, layout="wide")
    inject_ui_css()
    ensure_password_gate()


def ensure_password_gate() -> None:
    settings = get_settings()
    if not settings.app_password_hash:
        return

    if st.session_state.get("authenticated"):
        return

    st.title(settings.project_name)
    st.caption("This dashboard stays local. Enter the local app password to continue.")
    candidate = st.text_input("App password", type="password")
    if st.button("Unlock", use_container_width=True):
        if verify_password(candidate, settings.app_password_hash):
            st.session_state["authenticated"] = True
            st.rerun()
        st.error("Password verification failed.")
    st.stop()


@contextmanager
def session_scope():
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def format_inr(value: float | int | Decimal) -> str:
    amount = _to_decimal(value)
    absolute = abs(amount)

    compact_scales = (
        (Decimal("10000000"), "Cr"),
        (Decimal("100000"), "L"),
    )
    for threshold, suffix in compact_scales:
        if absolute >= threshold:
            scaled = amount / threshold
            return f"₹{scaled:,.2f} {suffix}"
    return f"₹{amount:,.2f}"


def format_percentage(value: float | int | Decimal) -> str:
    number = _to_decimal(value)
    return f"{number:,.2f}%"


def default_period() -> tuple[date, date]:
    today = date.today()
    start = today.replace(day=1)
    return start, today


def category_options() -> list[str]:
    with session_scope() as session:
        return list_categories(session)


def benchmark_profile_options(city: str = "Hyderabad") -> list[str]:
    with session_scope() as session:
        return list_benchmark_profiles(session, city=city)


def document_options() -> list[tuple[str, int]]:
    with session_scope() as session:
        documents = list_documents(session)
    return [(f"{document.id} | {document.filename} | {document.document_type}", document.id) for document in documents]


def render_sidebar_status() -> None:
    settings = get_settings()
    st.sidebar.caption("Privacy mode: local-only")
    st.sidebar.caption(f"Database: `{settings.database_path}`")
    st.sidebar.caption(f"Uploads: `{settings.uploads_dir}`")


def render_reset_controls() -> None:
    st.subheader("Local data reset")
    confirm = st.checkbox("I understand this will delete imported files and reset the local database.")
    if st.button("Reset local data", type="primary", use_container_width=True, disabled=not confirm):
        reset_local_data()
        st.success("Local data reset completed.")


def _to_decimal(value: float | int | Decimal) -> Decimal:
    try:
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def inject_ui_css() -> None:
    st.markdown(
        """
        <style>
        div[data-testid="stMetric"] {
            min-width: 0;
        }
        div[data-testid="stMetricLabel"] {
            font-size: 0.95rem;
        }
        div[data-testid="stMetricValue"] > div {
            font-size: clamp(1.10rem, 2.3vw, 2.50rem);
            white-space: normal;
            overflow-wrap: anywhere;
            line-height: 1.1;
        }
        @media (max-width: 1024px) {
            div[data-testid="stMetricValue"] > div {
                font-size: 1.00rem;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
