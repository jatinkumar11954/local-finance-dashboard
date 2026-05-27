from __future__ import annotations

from pathlib import Path
import sys

import streamlit as st

DASHBOARD_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = DASHBOARD_DIR.parent
for path in (PROJECT_ROOT, DASHBOARD_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from common import initialize_page, render_sidebar_status, session_scope
from app.services.credit_cards import CARD_USAGE_TYPES, list_credit_cards
from app.services.documents import DOCUMENT_TYPES, delete_document, ingest_document_bytes, list_documents, update_document_type


initialize_page("Upload Statements")
render_sidebar_status()

st.title("Upload Statements")
st.caption("Supported in Phase 2: CSV, XLSX, and digital PDFs. Files are stored only in the local project data directory.")

account_name = st.text_input("Account or source label", placeholder="HDFC Savings Account")
source_type_labels = {
    "Auto detect": "auto",
    "Bank statement": "bank_statement",
    "Credit card statement": "credit_card_statement",
    "Loan statement": "loan_statement",
    "UPI export": "upi_statement",
    "Unknown": "unknown",
}
source_type = source_type_labels[st.selectbox("Statement type", list(source_type_labels.keys()))]

credit_card_upload_tag = None
credit_card_usage_type = None
credit_card_name = None
credit_card_bank_name = None
credit_card_last4 = None
if source_type == "credit_card_statement":
    st.subheader("Credit card statement tags")
    with session_scope() as session:
        existing_cards = list_credit_cards(session, active_only=True)
    card_options = ["Create or enter card"] + [
        f"{card.id} | {card.name} | {card.last4 or 'last4 unknown'} | {card.usage_type}"
        for card in existing_cards
    ]
    selected_card_label = st.selectbox("Credit card profile", card_options)
    selected_card = None
    if selected_card_label != "Create or enter card":
        selected_id = int(selected_card_label.split("|", 1)[0].strip())
        selected_card = next((card for card in existing_cards if card.id == selected_id), None)

    tag_labels = {
        "Normal credit card analysis": "normal",
        "EMI analysis": "emi_analysis",
        "UPI-only credit card analysis": "upi_only",
        "Mixed credit card statement": "mixed",
    }
    card_usage_labels = {
        "normal": "normal",
        "upi_only": "upi_only",
        "mixed": "mixed",
        "emi_focused": "emi_focused",
    }
    tag_columns = st.columns(2)
    credit_card_upload_tag = tag_labels[
        tag_columns[0].selectbox("Credit card upload tag", list(tag_labels.keys()))
    ]
    default_usage = selected_card.usage_type if selected_card else "normal"
    usage_options = sorted(CARD_USAGE_TYPES)
    credit_card_usage_type = card_usage_labels[
        tag_columns[1].selectbox(
            "Card usage type",
            usage_options,
            index=usage_options.index(default_usage) if default_usage in usage_options else usage_options.index("normal"),
        )
    ]

    profile_columns = st.columns(3)
    credit_card_name = profile_columns[0].text_input(
        "Credit card name",
        value=selected_card.name if selected_card else "",
        placeholder="HDFC Millennia",
    )
    credit_card_bank_name = profile_columns[1].text_input(
        "Bank name",
        value=(selected_card.bank_name or selected_card.issuer_name or "") if selected_card else "",
        placeholder="HDFC Bank",
    )
    credit_card_last4 = profile_columns[2].text_input(
        "Last 4 digits",
        value=selected_card.last4 if selected_card and selected_card.last4 else "",
        max_chars=4,
        placeholder="1234",
    )

uploaded_files = st.file_uploader(
    "Select statement files",
    type=["csv", "xlsx", "xls", "pdf"],
    accept_multiple_files=True,
)

if st.button("Import selected files", use_container_width=True, type="primary"):
    if not uploaded_files:
        st.warning("Choose at least one CSV, XLSX, or PDF file.")
    else:
        with session_scope() as session:
            for uploaded_file in uploaded_files:
                try:
                    response = ingest_document_bytes(
                        session=session,
                        filename=uploaded_file.name,
                        content=uploaded_file.getvalue(),
                        mime_type=uploaded_file.type,
                        account_name=account_name or None,
                        source_type_override=source_type,
                        credit_card_name=credit_card_name or None,
                        credit_card_bank_name=credit_card_bank_name or None,
                        credit_card_last4=credit_card_last4 or None,
                        credit_card_usage_type=credit_card_usage_type,
                        credit_card_uploaded_tag=credit_card_upload_tag,
                    )
                    st.success(response.message)
                    st.caption(
                        f"Detected `{response.document.document_type}` with confidence `{response.document.parsing_confidence}`."
                    )
                except ValueError as exc:
                    session.rollback()
                    st.error(f"{uploaded_file.name}: {exc}")

st.subheader("Imported documents")
with session_scope() as session:
    documents = list_documents(session)

if not documents:
    st.info("No statements imported yet.")
else:
    table = [
        {
            "ID": document.id,
            "Filename": document.filename,
            "Type": document.document_type,
            "Status": document.parsing_status,
            "Confidence": document.parsing_confidence,
            "Rows": document.record_count,
            "Uploaded at": document.uploaded_at,
        }
        for document in documents
    ]
    st.dataframe(table, use_container_width=True, hide_index=True)

    st.subheader("Manage imported document")
    document_options = {
        f"{document.id} | {document.filename} | {document.document_type}": document
        for document in documents
    }
    selected_document_label = st.selectbox("Document", list(document_options.keys()))
    selected_document = document_options[selected_document_label]

    action_columns = st.columns(3)
    new_document_type = action_columns[0].selectbox(
        "Document type",
        DOCUMENT_TYPES,
        index=DOCUMENT_TYPES.index(selected_document.document_type)
        if selected_document.document_type in DOCUMENT_TYPES
        else DOCUMENT_TYPES.index("unknown"),
    )
    if action_columns[1].button("Update type", use_container_width=True):
        with session_scope() as session:
            try:
                update_document_type(session, selected_document.id, new_document_type)
                st.success(f"Updated {selected_document.filename} to {new_document_type}.")
                st.rerun()
            except ValueError as exc:
                session.rollback()
                st.error(str(exc))

    delete_file = action_columns[2].checkbox("Delete stored file", value=True)
    confirm_delete = st.checkbox(
        f"Confirm delete `{selected_document.filename}` and its parsed transactions",
        value=False,
    )
    if st.button("Delete selected upload", type="primary", disabled=not confirm_delete, use_container_width=True):
        with session_scope() as session:
            try:
                delete_document(session, selected_document.id, delete_file=delete_file)
                st.success(f"Deleted {selected_document.filename}.")
                st.rerun()
            except ValueError as exc:
                session.rollback()
                st.error(str(exc))
