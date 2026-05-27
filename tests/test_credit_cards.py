from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from app.models.entities import CreditCard, CreditCardEmiCharge, CreditCardEmiPlan, CreditCardStatement, CreditCardTransaction, Document, Transaction
from app.services.credit_cards import (
    analyze_credit_card_transactions,
    add_manual_emi_charge,
    classify_credit_card_transaction,
    detect_credit_card_transaction_type,
    detect_gst_parent_charge,
    detect_no_cost_emi,
    detect_processing_fee,
    detect_upi_credit_card_transaction,
    extract_upi_receiver,
    normalize_statement_tag,
    parse_emi_installment,
    sync_credit_card_document,
    update_credit_card_transaction_override,
    update_emi_plan_review,
)
from app.services.credit_cards.analysis import list_credit_card_sources
from app.services.documents import ingest_document_bytes


def test_credit_card_charge_classifier_detects_fee_types():
    assert classify_credit_card_transaction("LATE FEE", "debit")[0] == "late_fee"
    assert classify_credit_card_transaction("GST ON LATE FEE", "debit")[0] == "gst_on_late_fee"
    assert classify_credit_card_transaction("FINANCE CHARGE", "debit")[0] == "interest_charge"
    assert classify_credit_card_transaction("CASH WITHDRAWAL FEE", "debit")[0] == "cash_withdrawal_charge"
    assert classify_credit_card_transaction("MERCHANT EMI CONVERSION FEE", "debit")[0] == "emi_conversion"
    assert classify_credit_card_transaction("NO COST EMI 1/6 AMAZON PHONE", "debit")[0] == "emi_transaction"
    assert classify_credit_card_transaction("LOAN ON CARD EMI 2/6", "debit")[0] == "emi_transaction"
    assert classify_credit_card_transaction("SMART EMI 3/12 STORE", "debit")[0] == "emi_transaction"
    assert classify_credit_card_transaction("EMI PROCESSING FEE", "debit")[0] == "processing_fee"
    assert classify_credit_card_transaction("GST ON INTEREST EMI", "debit")[0] == "gst_on_interest"
    assert classify_credit_card_transaction("GST ON EMI PROCESSING FEE", "debit")[0] == "gst_on_processing_fee"
    assert classify_credit_card_transaction("GST ON FINANCE CHARGE", "debit")[0] == "gst_on_finance_charge"
    assert classify_credit_card_transaction("INTEREST REVERSAL NO COST EMI", "credit")[0] == "interest_reversal"
    assert classify_credit_card_transaction("NO COST EMI CASHBACK", "credit")[0] == "cashback_discount"
    assert classify_credit_card_transaction("MERCHANT DISCOUNT NO COST EMI", "credit")[0] == "discount"
    assert classify_credit_card_transaction("BANK OFFER CREDIT", "credit")[0] == "bank_offer_credit"
    assert classify_credit_card_transaction("PAYMENT RECEIVED", "credit")[0] == "payment"
    assert parse_emi_installment("NO COST EMI 3/12 AMAZON PHONE") == (3, 12)
    assert parse_emi_installment("INSTALMENT 2 of 6 STORE") == (2, 6)
    parsed = detect_credit_card_transaction_type("NO COST EMI 1/6 AMAZON PHONE", 5000, "debit")
    assert parsed.parsed_type == "emi_transaction"
    assert parsed.extracted_fields["no_cost_claimed"] is True
    assert detect_no_cost_emi("NOCOST EMI STORE") is True
    assert detect_processing_fee("PROC FEE EMI") is True
    assert detect_gst_parent_charge("IGST ON PROCESSING FEE") == "processing_fee"
    assert detect_upi_credit_card_transaction("RUPAY UPI/COFFEE/@ybl", "CARD") is True
    assert extract_upi_receiver("UPI/COFFEE SHOP/ORDER") == "Coffee Shop"


def test_all_credit_card_statement_tags_are_supported():
    assert normalize_statement_tag("normal") == "normal"
    assert normalize_statement_tag("EMI analysis") == "emi_analysis"
    assert normalize_statement_tag("UPI-only") == "upi_only"
    assert normalize_statement_tag("Mixed") == "mixed"


def test_credit_card_analysis_summarizes_spend_and_extra_charges(db_session):
    sample_file = Path(__file__).resolve().parents[1] / "sample_data" / "dummy_credit_card_statement.csv"
    ingest_document_bytes(
        session=db_session,
        filename=sample_file.name,
        content=sample_file.read_bytes(),
        mime_type="text/csv",
        account_name="HDFC Credit Card",
        source_type_override="credit_card_statement",
    )

    analysis = analyze_credit_card_transactions(
        session=db_session,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 31),
        account_source="HDFC Credit Card",
    )

    assert analysis.total_purchase_spend == Decimal("4475.00")
    assert analysis.total_extra_charges == Decimal("2457.82")
    assert analysis.total_interest == Decimal("1080.00")
    assert analysis.total_fees == Decimal("1677.82")
    assert analysis.total_payments_received == 5000
    assert any(item["period"] == "2026-05" and item["spend"] == Decimal("4475.00") for item in analysis.monthly_spend)
    assert any("Late fee" in risk for risk in analysis.risky_patterns)
    assert len(analysis.flagged_transactions) >= 4


def test_credit_card_source_dropdown_can_filter_by_statement_filename(db_session):
    sample_file = Path(__file__).resolve().parents[1] / "sample_data" / "dummy_credit_card_statement.csv"
    ingest_document_bytes(
        session=db_session,
        filename=sample_file.name,
        content=sample_file.read_bytes(),
        mime_type="text/csv",
        account_name=None,
        source_type_override="credit_card_statement",
    )

    sources = list_credit_card_sources(db_session)
    assert sample_file.name in sources

    analysis = analyze_credit_card_transactions(
        session=db_session,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 31),
        account_source=sample_file.name,
    )

    assert analysis.total_purchase_spend == Decimal("4475.00")


def test_no_cost_emi_components_and_net_extra_cost(db_session):
    document = _add_card_document(
        db_session,
        raw_text="EMI Schedule\nAMAZON PHONE NO COST EMI 1/6 5000.00\nAMAZON PHONE NO COST EMI 2/6 5000.00",
    )
    _add_card_transaction(db_session, document, "NO COST EMI 1/6 AMAZON PHONE", 5000, "debit")
    _add_card_transaction(db_session, document, "INTEREST CHARGED NO COST EMI", 300, "debit")
    _add_card_transaction(db_session, document, "INTEREST REVERSAL NO COST EMI", 300, "credit")
    _add_card_transaction(db_session, document, "EMI PROCESSING FEE", 199, "debit")
    _add_card_transaction(db_session, document, "GST ON EMI PROCESSING FEE", Decimal("35.82"), "debit")
    _add_card_transaction(db_session, document, "GST ON INTEREST EMI", 54, "debit")
    _add_card_transaction(db_session, document, "NO COST EMI CASHBACK", 100, "credit")
    db_session.commit()

    analysis = analyze_credit_card_transactions(
        session=db_session,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 31),
        account_source="No Cost Card",
        analysis_mode="emi_analysis",
    )

    assert analysis.emi_summary.detected_emi_count == 1
    assert analysis.emi_summary.pending_emi_count == 5
    assert analysis.emi_summary.schedule_detected is True
    assert analysis.no_cost_emi_summary.interest_charged == Decimal("300.00")
    assert analysis.no_cost_emi_summary.interest_reversal == Decimal("300.00")
    assert analysis.no_cost_emi_summary.cashback_discount == Decimal("100.00")
    assert analysis.no_cost_emi_summary.processing_fee == Decimal("199.00")
    assert analysis.no_cost_emi_summary.gst_on_processing_fee == Decimal("35.82")
    assert analysis.no_cost_emi_summary.gst_on_interest == Decimal("54.00")
    assert analysis.no_cost_emi_summary.net_extra_cost == Decimal("188.82")
    assert analysis.no_cost_emi_summary.verification_status == "partial_no_cost"


def test_no_cost_emi_missing_processing_fee_needs_review(db_session):
    document = _add_card_document(db_session)
    _add_card_transaction(db_session, document, "NO COST EMI 1/6 STORE", 3000, "debit")
    _add_card_transaction(db_session, document, "INTEREST CHARGED NO COST EMI", 200, "debit")
    db_session.commit()

    analysis = analyze_credit_card_transactions(
        session=db_session,
        account_source="No Cost Card",
        analysis_mode="emi_analysis",
    )

    assert analysis.no_cost_emi_summary.processing_fee == Decimal("0.00")
    assert analysis.no_cost_emi_summary.processing_fee_found is False
    assert analysis.no_cost_emi_summary.needs_review is True
    assert any("Processing fee not found" in warning for warning in analysis.review_warnings)


def test_upi_only_card_keeps_upi_separate_from_card_shopping(db_session):
    document = _add_card_document(db_session, account_source="UPI Card")
    _add_card_transaction(
        db_session,
        document,
        "UPI/COFFEE SHOP/ORDER",
        150,
        "debit",
        payment_mode="UPI",
        merchant_name="Coffee Shop",
        category="UPI Transfers",
        account_source="UPI Card",
    )
    _add_card_transaction(
        db_session,
        document,
        "POS MALL STORE",
        1000,
        "debit",
        payment_mode="CARD",
        merchant_name="Mall Store",
        category="Shopping",
        account_source="UPI Card",
    )
    db_session.commit()

    upi_only = analyze_credit_card_transactions(
        session=db_session,
        account_source="UPI Card",
        analysis_mode="upi_only",
    )
    mixed = analyze_credit_card_transactions(
        session=db_session,
        account_source="UPI Card",
        analysis_mode="mixed",
    )

    assert upi_only.total_upi_spend == Decimal("150.00")
    assert upi_only.daily_upi_spend == [{"date": date(2026, 5, 1), "amount": Decimal("150.00")}]
    assert upi_only.upi_transactions[0].receiver_name == "Coffee Shop"
    assert upi_only.upi_transactions[0].receiver_type == "merchant_spend"
    assert upi_only.total_purchase_spend == Decimal("0.00")
    assert mixed.total_upi_spend == Decimal("150.00")
    assert mixed.total_purchase_spend == Decimal("1000.00")


def test_credit_card_upload_metadata_creates_card_statement_and_emi_plan(db_session):
    sample_file = Path(__file__).resolve().parents[1] / "sample_data" / "dummy_credit_card_statement.csv"
    response = ingest_document_bytes(
        session=db_session,
        filename=sample_file.name,
        content=sample_file.read_bytes(),
        mime_type="text/csv",
        account_name="HDFC UPI Card",
        source_type_override="credit_card_statement",
        credit_card_name="HDFC Rupay UPI",
        credit_card_bank_name="HDFC Bank",
        credit_card_last4="1234",
        credit_card_usage_type="upi_only",
        credit_card_uploaded_tag="upi_only",
    )

    card = db_session.scalar(select(CreditCard).where(CreditCard.last4 == "1234"))
    assert card is not None
    assert card.usage_type == "upi_only"
    statement = db_session.scalar(select(CreditCardStatement).where(CreditCardStatement.source_document_id == response.document.id))
    assert statement is not None
    assert statement.uploaded_tag == "upi_only"
    assert db_session.scalar(select(CreditCardTransaction).where(CreditCardTransaction.card_id == card.id).limit(1)) is not None
    assert db_session.scalar(select(CreditCardEmiPlan).where(CreditCardEmiPlan.card_id == card.id).limit(1)) is not None


def test_credit_card_emi_schedule_parses_details_from_statement_text(db_session):
    document = _add_card_document(
        db_session,
        raw_text=(
            "EMI Schedule\n"
            "AMAZON PHONE txn date 01/05/2026 start date 05/06/2026 NO COST EMI 2/6 INR 5000 rate 14.5% principal outstanding 20000 "
            "processing fee 199 ref EMIABC1234"
        ),
    )
    _add_card_transaction(db_session, document, "NO COST EMI 2/6 AMAZON PHONE", 5000, "debit")
    db_session.commit()

    analysis = analyze_credit_card_transactions(db_session, account_source="No Cost Card", analysis_mode="emi_analysis")

    assert analysis.emi_schedule[0].merchant_name is not None
    assert analysis.emi_schedule[0].no_cost_claimed is True
    assert analysis.emi_schedule[0].original_transaction_date == date(2026, 5, 1)
    assert analysis.emi_schedule[0].emi_start_date == date(2026, 6, 5)
    assert analysis.emi_schedule[0].interest_rate == Decimal("14.5")
    assert analysis.emi_schedule[0].processing_fee == Decimal("199.00")
    assert analysis.emi_schedule[0].emi_reference == "EMIABC1234"


def test_processing_fee_in_earlier_statement_links_to_later_emi_plan(db_session):
    first_document = _add_card_document(db_session, account_source="Linked EMI Card")
    fee = _add_card_transaction(
        db_session,
        first_document,
        "EMI PROCESSING FEE AMAZON PHONE",
        199,
        "debit",
        account_source="Linked EMI Card",
    )
    fee.date = date(2026, 4, 28)
    db_session.flush()
    sync_credit_card_document(
        db_session,
        first_document,
        [fee],
        card_name="Linked EMI Card",
        usage_type="emi_focused",
        uploaded_tag="emi_analysis",
    )

    second_document = _add_card_document(db_session, account_source="Linked EMI Card")
    emi = _add_card_transaction(
        db_session,
        second_document,
        "NO COST EMI 1/6 AMAZON PHONE",
        5000,
        "debit",
        account_source="Linked EMI Card",
    )
    db_session.flush()
    sync_credit_card_document(
        db_session,
        second_document,
        [emi],
        card_name="Linked EMI Card",
        usage_type="emi_focused",
        uploaded_tag="emi_analysis",
    )
    db_session.commit()

    plan = db_session.scalar(select(CreditCardEmiPlan))
    assert plan is not None
    assert plan.processing_fee_status == "processing_fee_found"
    assert db_session.scalar(
        select(CreditCardEmiCharge).where(
            CreditCardEmiCharge.emi_plan_id == plan.id,
            CreditCardEmiCharge.charge_type == "processing_fee",
        )
    ) is not None


def test_upi_only_synced_card_routes_upi_without_normal_card_spend(db_session):
    document = _add_card_document(db_session, account_source="Synced UPI Card")
    first = _add_card_transaction(
        db_session,
        document,
        "RUPAY UPI/COFFEE SHOP/QR",
        150,
        "debit",
        payment_mode="UPI",
        account_source="Synced UPI Card",
    )
    second = _add_card_transaction(
        db_session,
        document,
        "RUPAY UPI/COFFEE SHOP/QR",
        125,
        "debit",
        payment_mode="UPI",
        account_source="Synced UPI Card",
    )
    third = _add_card_transaction(
        db_session,
        document,
        "POS MALL STORE",
        1000,
        "debit",
        payment_mode="CARD",
        account_source="Synced UPI Card",
    )
    db_session.flush()
    sync_credit_card_document(
        db_session,
        document,
        [first, second, third],
        card_name="Synced UPI Card",
        usage_type="upi_only",
        uploaded_tag="upi_only",
    )
    card = db_session.scalar(select(CreditCard).where(CreditCard.name == "Synced UPI Card"))

    analysis = analyze_credit_card_transactions(db_session, card_id=card.id, analysis_mode="upi_only")

    assert analysis.total_upi_spend == Decimal("275.00")
    assert analysis.total_purchase_spend == Decimal("0.00")
    assert analysis.repeated_upi_payments[0]["receiver"] == "Coffee Shop"
    assert analysis.small_frequent_upi_payments[0]["count"] == 2


def test_manual_override_reclassifies_transaction_and_recalculates_emi_plan(db_session):
    document = _add_card_document(db_session, account_source="Manual EMI Card")
    emi = _add_card_transaction(
        db_session,
        document,
        "NO COST EMI 1/3 STORE",
        1000,
        "debit",
        account_source="Manual EMI Card",
    )
    adjustment = _add_card_transaction(
        db_session,
        document,
        "STORE ADJUSTMENT",
        99,
        "debit",
        account_source="Manual EMI Card",
    )
    db_session.flush()
    sync_credit_card_document(
        db_session,
        document,
        [emi, adjustment],
        card_name="Manual EMI Card",
        usage_type="emi_focused",
        uploaded_tag="emi_analysis",
    )
    update_credit_card_transaction_override(db_session, adjustment.id, "processing_fee")

    card = db_session.scalar(select(CreditCard).where(CreditCard.name == "Manual EMI Card"))
    analysis = analyze_credit_card_transactions(db_session, card_id=card.id, analysis_mode="emi_analysis")

    assert analysis.no_cost_emi_summary.processing_fee == Decimal("99.00")
    assert analysis.no_cost_emi_summary.processing_fee_found is True
    assert db_session.scalar(select(CreditCardTransaction).where(CreditCardTransaction.transaction_id == adjustment.id)).manual_override is True


def test_manual_emi_plan_review_overrides_no_cost_status(db_session):
    document = _add_card_document(db_session, account_source="Review EMI Card")
    emi = _add_card_transaction(
        db_session,
        document,
        "NO COST EMI 1/2 STORE",
        1000,
        "debit",
        account_source="Review EMI Card",
    )
    db_session.flush()
    sync_credit_card_document(
        db_session,
        document,
        [emi],
        card_name="Review EMI Card",
        usage_type="emi_focused",
        uploaded_tag="emi_analysis",
    )
    plan = db_session.scalar(select(CreditCardEmiPlan))
    update_emi_plan_review(
        db_session,
        plan.id,
        no_cost_verification_status="not_no_cost",
        processing_fee_status="manual_entry",
        lifecycle_status="needs_review",
        notes="Manual review says fee exists in invoice.",
    )

    card = db_session.scalar(select(CreditCard).where(CreditCard.name == "Review EMI Card"))
    analysis = analyze_credit_card_transactions(db_session, card_id=card.id, analysis_mode="emi_analysis")

    assert analysis.emi_plans[0].no_cost_verification_status == "not_no_cost"
    assert analysis.emi_plans[0].processing_fee_status == "manual_entry"


def test_manual_processing_fee_entry_updates_emi_plan_cost(db_session):
    document = _add_card_document(db_session, account_source="Manual Fee Card")
    emi = _add_card_transaction(
        db_session,
        document,
        "NO COST EMI 1/2 STORE",
        1000,
        "debit",
        account_source="Manual Fee Card",
    )
    db_session.flush()
    sync_credit_card_document(
        db_session,
        document,
        [emi],
        card_name="Manual Fee Card",
        usage_type="emi_focused",
        uploaded_tag="emi_analysis",
    )
    plan = db_session.scalar(select(CreditCardEmiPlan))
    add_manual_emi_charge(
        db_session,
        plan.id,
        "processing_fee",
        Decimal("99.00"),
        date(2026, 5, 1),
        notes="Synthetic manual processing fee",
    )

    card = db_session.scalar(select(CreditCard).where(CreditCard.name == "Manual Fee Card"))
    analysis = analyze_credit_card_transactions(db_session, card_id=card.id, analysis_mode="emi_analysis")

    assert analysis.emi_plans[0].total_processing_fee == Decimal("99.00")
    assert analysis.emi_plans[0].total_extra_cost == Decimal("99.00")


def test_manual_credit_card_charge_type_override_wins(db_session):
    document = _add_card_document(db_session)
    _add_card_transaction(
        db_session,
        document,
        "FINANCE CHARGE",
        780,
        "debit",
        notes="cc_charge_type=purchase",
    )
    db_session.commit()

    analysis = analyze_credit_card_transactions(session=db_session, account_source="No Cost Card")

    assert analysis.total_interest == Decimal("0.00")
    assert analysis.total_purchase_spend == Decimal("780.00")
    assert analysis.classified_transactions[0].charge_type == "purchase"
    assert analysis.classified_transactions[0].manual_override_applied is True


def _add_card_document(db_session, raw_text: str | None = None, account_source: str = "No Cost Card") -> Document:
    document = Document(
        filename=f"{account_source.lower().replace(' ', '_')}.csv",
        stored_path="/tmp/synthetic_credit_card.csv",
        content_hash=f"{account_source.lower().replace(' ', '_')}-{uuid4().hex}",
        mime_type="text/csv",
        document_type="credit_card_statement",
        parsing_status="parsed",
        parsing_confidence=0.99,
        record_count=0,
        raw_text=raw_text,
    )
    db_session.add(document)
    db_session.flush()
    return document


def _add_card_transaction(
    db_session,
    document: Document,
    description: str,
    amount: int | float | Decimal,
    transaction_type: str,
    payment_mode: str = "CARD",
    merchant_name: str | None = None,
    category: str = "Shopping",
    account_source: str = "No Cost Card",
    notes: str | None = None,
) -> Transaction:
    transaction = Transaction(
        date=date(2026, 5, 1),
        description=merchant_name or description[:120],
        raw_description=description,
        amount=Decimal(str(amount)),
        transaction_type=transaction_type,
        payment_mode=payment_mode,
        merchant_name=merchant_name,
        category=category,
        confidence_score=0.9,
        account_source=account_source,
        source_document_id=document.id,
        notes=notes,
    )
    db_session.add(transaction)
    return transaction
