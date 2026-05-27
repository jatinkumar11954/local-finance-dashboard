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

from app.services.rag import answer_local_finance_query
from common import default_period, initialize_page, render_sidebar_status, session_scope


initialize_page("Assistant")
render_sidebar_status()

st.title("Local Finance Assistant")
st.caption("Answers are generated only from local database tables and uploaded local document text.")

with st.expander("Example questions", expanded=True):
    st.markdown(
        """
        - How much did I spend on food last month?
        - How much EMI did I pay in FY 2025-26?
        - Which UPI payments are recurring?
        - How much credit card interest did I pay?
        - Show all credit card charges that look like interest or late fees.
        - How does my monthly spend compare with Hyderabad comfortable living standards?
        - What are my top avoidable expenses?
        """
    )

default_start, default_end = default_period()
query_columns = st.columns(3)
apply_date_filter = query_columns[0].checkbox("Apply date range filter", value=False)
selected_range = query_columns[0].date_input(
    "Date range (optional)",
    value=(default_start, default_end),
    disabled=not apply_date_filter,
)
use_local_embeddings = query_columns[1].checkbox(
    "Use local embeddings if configured",
    value=False,
    help="Only works when a local sentence-transformer model path is configured via LFI_LOCAL_EMBEDDING_MODEL_PATH.",
)
use_local_llm = query_columns[2].checkbox(
    "Use local Ollama reasoning",
    value=False,
    help="Uses only a local Ollama server configured with LFI_LOCAL_LLM_PROVIDER=ollama.",
)
question = st.text_area(
    "Ask a question",
    placeholder="How much did I spend on food delivery last month?",
    height=120,
)

if apply_date_filter:
    start_date = selected_range[0] if isinstance(selected_range, tuple) else None
    end_date = selected_range[1] if isinstance(selected_range, tuple) and len(selected_range) > 1 else start_date
else:
    start_date = None
    end_date = None

if st.button("Run local assistant query", type="primary", use_container_width=True):
    if not question.strip():
        st.warning("Enter a question to continue.")
    else:
        with session_scope() as session:
            response = answer_local_finance_query(
                session=session,
                question=question,
                start_date=start_date,
                end_date=end_date,
                use_local_embeddings=use_local_embeddings,
                use_local_llm=use_local_llm,
            )

        st.subheader("Answer")
        st.write(response.answer)

        metadata_columns = st.columns(4)
        metadata_columns[0].metric(
            "Date range used",
            f"{response.date_range_start or 'N/A'} to {response.date_range_end or 'N/A'}",
        )
        metadata_columns[1].metric("Confidence", f"{response.confidence_level} ({response.confidence_score:.2f})")
        metadata_columns[2].metric("Handler", response.handler)
        metadata_columns[3].metric(
            "Local AI",
            response.local_llm_model if response.used_local_llm else ("Embeddings" if response.used_local_embeddings else "No"),
        )

        st.subheader("Calculation method")
        st.write(response.calculation_method)

        st.subheader("Supporting transactions")
        if response.supporting_transactions:
            transaction_df = pd.DataFrame([item.model_dump() for item in response.supporting_transactions])
            st.dataframe(transaction_df, use_container_width=True, hide_index=True)
        else:
            st.caption("No supporting transactions found for this answer.")

        st.subheader("Supporting documents")
        if response.supporting_documents:
            document_df = pd.DataFrame([item.model_dump() for item in response.supporting_documents])
            st.dataframe(document_df, use_container_width=True, hide_index=True)
        else:
            st.caption("No supporting documents found for this answer.")
