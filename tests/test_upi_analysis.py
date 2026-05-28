from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from app.models.entities import Transaction
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
    assert analysis.transaction_count == 7
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


def test_upi_analysis_detects_upi_from_card_statement_description(db_session):
    transaction = Transaction(
        date=date(2026, 5, 10),
        description="RUPAY UPI/COFFEE SHOP/QR",
        raw_description="RUPAY UPI/COFFEE SHOP/QR",
        amount=Decimal("150.00"),
        transaction_type="debit",
        account_source="UPI Card",
        payment_mode="CARD",
        merchant_name="RUPAY UPI",
        category="UPI Transfers",
        confidence_score=0.8,
    )
    db_session.add(transaction)
    db_session.flush()

    analysis = analyze_upi_transactions(
        session=db_session,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 31),
        account_source="UPI Card",
    )

    assert analysis.total_upi_spend == Decimal("150.00")
    assert analysis.transaction_count == 1
    assert analysis.transactions[0].receiver_name == "Coffee Shop"
    assert "UPI Card" in list_upi_sources(db_session)


def test_upi_analysis_warns_when_amounts_look_like_counts(db_session):
    for index in range(25):
        db_session.add(
            Transaction(
                date=date(2026, 5, 1),
                description=f"UPI/SMALL MERCHANT {index}/QR",
                raw_description=f"UPI/SMALL MERCHANT {index}/QR",
                amount=Decimal("1.00"),
                transaction_type="debit",
                account_source="Parsed PDF",
                payment_mode="UPI",
                merchant_name=f"Small Merchant {index}",
                category="UPI Transfers",
                confidence_score=0.7,
            )
        )
    db_session.flush()

    analysis = analyze_upi_transactions(
        session=db_session,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 31),
        account_source="Parsed PDF",
    )

    assert analysis.total_upi_spend == Decimal("25.00")
    assert analysis.transaction_count == 25
    assert analysis.amount_quality_warning is not None
