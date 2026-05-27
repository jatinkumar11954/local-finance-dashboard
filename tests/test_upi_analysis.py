from __future__ import annotations

from datetime import date
from pathlib import Path

from app.services.analytics import analyze_upi_transactions, list_upi_sources
from app.services.analytics.upi import UNLABELED_UPI_SOURCE
from app.services.documents import ingest_document_bytes


def test_upi_analysis_detects_daily_spend_and_repeated_payments(db_session):
    sample_file = Path(__file__).resolve().parents[1] / "sample_data" / "dummy_upi_export.csv"
    ingest_document_bytes(
        session=db_session,
        filename=sample_file.name,
        content=sample_file.read_bytes(),
        mime_type="text/csv",
        account_name="Primary UPI",
        source_type_override="upi_statement",
    )

    analysis = analyze_upi_transactions(
        session=db_session,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 7, 31),
        account_source="Primary UPI",
    )

    assert analysis.total_upi_spend == 8067
    assert analysis.merchant_spend == 3067
    assert analysis.personal_transfer_spend == 5000
    assert any(item["date"] == date(2026, 5, 3) and item["amount"] == 560 for item in analysis.daily_spend)
    assert any(payment.receiver_name == "Netflix Subscription" and payment.cadence == "monthly" for payment in analysis.repeated_payments)


def test_upi_source_dropdown_can_filter_unlabeled_sources(db_session):
    sample_file = Path(__file__).resolve().parents[1] / "sample_data" / "dummy_upi_export.csv"
    ingest_document_bytes(
        session=db_session,
        filename=sample_file.name,
        content=sample_file.read_bytes(),
        mime_type="text/csv",
        account_name=None,
        source_type_override="upi_statement",
    )

    assert UNLABELED_UPI_SOURCE in list_upi_sources(db_session)

    analysis = analyze_upi_transactions(
        session=db_session,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 7, 31),
        account_source=UNLABELED_UPI_SOURCE,
    )

    assert analysis.total_upi_spend == 8067
