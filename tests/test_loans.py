from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from app.models.entities import Document, Loan, LoanTransaction
from app.services.documents import ingest_document_bytes
from app.services.loans import (
    LoanPrepayment,
    analyze_home_loan,
    calculate_emi,
    classify_loan_transaction,
    generate_amortization_schedule,
    list_loan_ledger,
    list_loan_import_summaries,
    recalculate_loan_ledger,
    relink_loan_transactions,
    save_loan_manual_override,
    update_loan_transaction,
)


def test_emi_and_schedule_breakdown_are_correct():
    emi = calculate_emi(principal=120000, annual_interest_rate=12, tenure_months=12)
    schedule = generate_amortization_schedule(
        principal=120000,
        annual_interest_rate=12,
        start_date=date(2026, 1, 1),
        tenure_months=12,
        emi_amount=emi,
    )

    assert emi == Decimal("10661.85")
    assert len(schedule) == 12
    assert schedule[0].interest_component == Decimal("1200.00")
    assert schedule[0].principal_component == Decimal("9461.85")
    assert schedule[0].closing_balance == Decimal("110538.15")
    assert schedule[-1].closing_balance == Decimal("0.00")


def test_home_loan_analysis_shows_prepayment_benefit():
    analysis = analyze_home_loan(
        principal=120000,
        annual_interest_rate=12,
        start_date=date(2026, 1, 1),
        tenure_months=12,
        emi_amount=10661.85,
        current_outstanding_balance=120000,
        recurring_extra_payment=1000,
        one_time_prepayments=[LoanPrepayment(payment_date=date(2026, 3, 15), amount=5000)],
        as_of_date=date(2026, 1, 1),
    )

    assert analysis.interest_saved > Decimal("0.00")
    assert analysis.projected_closure_date < analysis.baseline_closure_date
    assert analysis.months_saved > 0
    assert len(analysis.projected_schedule) < len(analysis.baseline_schedule)
    assert analysis.one_time_prepayment_total == Decimal("5000.00")


def test_loan_transaction_classification_patterns():
    mbk = classify_loan_transaction("MBK HOME LOAN PREPAYMENT LAN4455", 100000, "debit", "bank_statement")
    mbk_credit = classify_loan_transaction("MBK HOME LOAN PREPAYMENT LAN4455", 100000, "credit", "bank_statement")
    recovery = classify_loan_transaction("LOAN RECOVERY HOME LOAN EMI", 50000, "debit", "bank_statement")
    loan_account_payment = classify_loan_transaction("Loan Account Payments For :80740600007603", 40000, "debit", "bank_statement")
    non_loan = classify_loan_transaction("UPI/SWIGGY/food order", 850, "debit", "bank_statement")

    assert mbk is not None
    assert mbk.loan_transaction_type == "prepayment"
    assert mbk_credit is None
    assert recovery is not None
    assert recovery.loan_transaction_type == "emi"
    assert loan_account_payment is not None
    assert loan_account_payment.loan_transaction_type == "prepayment"
    assert non_loan is None


def test_monthly_ledger_emi_only_with_known_rate(db_session):
    loan = _create_test_loan(db_session)
    db_session.add(_loan_transaction(loan, "emi", 50000, date(2026, 5, 5), "LOAN RECOVERY EMI"))
    db_session.commit()

    ledger = recalculate_loan_ledger(db_session, loan.id)

    assert len(ledger) == 1
    assert ledger[0].opening_outstanding == Decimal("1000000.00")
    assert ledger[0].interest_charged == Decimal("10000.00")
    assert ledger[0].principal_paid == Decimal("40000.00")
    assert ledger[0].closing_outstanding == Decimal("960000.00")
    assert ledger[0].inferred_annual_rate == Decimal("12.000000")
    assert ledger[0].rate_source == "manual"


def test_monthly_ledger_emi_and_mbk_prepayment_same_month(db_session):
    loan = _create_test_loan(db_session)
    db_session.add(_loan_transaction(loan, "emi", 50000, date(2026, 5, 5), "LOAN RECOVERY EMI"))
    db_session.add(_loan_transaction(loan, "prepayment", 100000, date(2026, 5, 10), "MBK LOAN PREPAYMENT"))
    db_session.commit()

    ledger = recalculate_loan_ledger(db_session, loan.id)

    assert ledger[0].emi_paid == Decimal("50000.00")
    assert ledger[0].prepayment_paid == Decimal("100000.00")
    assert ledger[0].interest_charged == Decimal("10000.00")
    assert ledger[0].principal_paid == Decimal("40000.00")
    assert ledger[0].closing_outstanding == Decimal("860000.00")


def test_monthly_ledger_first_import_month_uses_profile_schedule_opening(db_session):
    loan = _create_test_loan(db_session, start_date_value=date(2026, 1, 1))
    db_session.add(_loan_transaction(loan, "emi", 50000, date(2026, 5, 5), "LOAN RECOVERY EMI"))
    db_session.add(_loan_transaction(loan, "prepayment", 100000, date(2026, 5, 10), "MBK LOAN PREPAYMENT"))
    db_session.commit()

    ledger = recalculate_loan_ledger(db_session, loan.id)

    assert ledger[0].opening_outstanding == Decimal("837583.96")
    assert ledger[0].interest_charged == Decimal("8375.84")
    assert ledger[0].principal_paid == Decimal("41624.16")
    assert ledger[0].closing_outstanding == Decimal("695959.80")
    assert "profile schedule" in ledger[0].calculation_notes


def test_monthly_ledger_uses_explicit_interest_and_infers_rate(db_session):
    loan = _create_test_loan(db_session, outstanding=900000, annual_rate=0)
    db_session.add(
        _loan_transaction(
            loan,
            "emi",
            50000,
            date(2026, 5, 5),
            "LOAN RECOVERY EMI",
            opening_outstanding=Decimal("900000"),
            closing_outstanding=Decimal("859000"),
            interest_component=Decimal("9000"),
        )
    )
    db_session.commit()

    ledger = recalculate_loan_ledger(db_session, loan.id)

    assert ledger[0].interest_charged == Decimal("9000.00")
    assert ledger[0].principal_paid == Decimal("41000.00")
    assert ledger[0].inferred_monthly_rate == Decimal("0.01000000")
    assert ledger[0].inferred_annual_rate == Decimal("12.000000")


def test_monthly_ledger_marks_missing_opening_balance_low_confidence(db_session):
    loan = Loan(
        name="Incomplete loan",
        loan_type="home_loan",
        rate_type="unknown",
        start_date=date(2026, 1, 1),
        tenure_months=240,
        emi_amount=Decimal("50000"),
    )
    db_session.add(loan)
    db_session.commit()
    db_session.add(_loan_transaction(loan, "emi", 50000, date(2026, 5, 5), "LOAN RECOVERY EMI"))
    db_session.commit()

    ledger = recalculate_loan_ledger(db_session, loan.id)

    assert ledger[0].opening_outstanding is None
    assert ledger[0].interest_charged is None
    assert ledger[0].confidence_score < 0.5
    assert "Missing opening outstanding" in ledger[0].calculation_notes


def test_manual_override_takes_precedence(db_session):
    loan = _create_test_loan(db_session)
    db_session.add(_loan_transaction(loan, "emi", 50000, date(2026, 5, 5), "LOAN RECOVERY EMI"))
    db_session.commit()

    save_loan_manual_override(
        db_session,
        loan_id=loan.id,
        month=date(2026, 5, 1),
        opening_outstanding=990000,
        closing_outstanding=949000,
        interest_charged=9000,
        principal_paid=41000,
        annual_rate=10.9,
        notes="Statement correction",
    )

    ledger = list_loan_ledger(db_session, loan.id)
    assert ledger[0].opening_outstanding == Decimal("990000.00")
    assert ledger[0].interest_charged == Decimal("9000.00")
    assert ledger[0].principal_paid == Decimal("41000.00")
    assert ledger[0].closing_outstanding == Decimal("949000.00")
    assert ledger[0].provided_annual_rate == Decimal("10.9000")
    assert ledger[0].rate_source == "manual"
    assert ledger[0].confidence_score >= 0.85


def test_updating_loan_transaction_recalculates_ledger(db_session):
    loan = _create_test_loan(db_session)
    db_session.add(_loan_transaction(loan, "emi", 50000, date(2026, 5, 5), "LOAN RECOVERY EMI"))
    prepayment = _loan_transaction(loan, "prepayment", 100000, date(2026, 5, 10), "MBK LOAN PREPAYMENT")
    db_session.add(prepayment)
    db_session.commit()
    recalculate_loan_ledger(db_session, loan.id)
    assert list_loan_ledger(db_session, loan.id)[0].closing_outstanding == Decimal("860000.00")

    update_loan_transaction(db_session, prepayment.id, review_status="ignored")

    assert list_loan_ledger(db_session, loan.id)[0].closing_outstanding == Decimal("960000.00")


def test_manual_transaction_reclassification_takes_precedence(db_session):
    loan = _create_test_loan(db_session)
    db_session.add(_loan_transaction(loan, "emi", 50000, date(2026, 5, 5), "LOAN RECOVERY EMI"))
    prepayment = _loan_transaction(loan, "prepayment", 100000, date(2026, 5, 10), "MBK LOAN PREPAYMENT")
    db_session.add(prepayment)
    db_session.commit()
    recalculate_loan_ledger(db_session, loan.id)
    assert list_loan_ledger(db_session, loan.id)[0].prepayment_paid == Decimal("100000.00")

    update_loan_transaction(db_session, prepayment.id, loan_transaction_type="charge", review_status="confirmed")

    ledger = list_loan_ledger(db_session, loan.id)
    db_session.refresh(prepayment)
    assert prepayment.loan_transaction_type == "charge"
    assert prepayment.review_status == "confirmed"
    assert ledger[0].prepayment_paid == Decimal("0.00")
    assert ledger[0].charges_paid == Decimal("100000.00")


def test_import_summary_and_relink_moves_transactions_between_profiles(db_session):
    source_loan = _create_test_loan(db_session)
    target_loan = _create_test_loan(db_session, outstanding=2000000, annual_rate=7.35)
    target_loan.name = "User profile loan"
    db_session.add(_loan_transaction(source_loan, "emi", 37602, date(2025, 5, 5), "LOAN RECOVERY EMI"))
    db_session.add(_loan_transaction(source_loan, "prepayment", 10000, date(2025, 5, 10), "MBK PREPAYMENT"))
    db_session.commit()
    recalculate_loan_ledger(db_session, source_loan.id)

    summaries = list_loan_import_summaries(db_session)
    assert summaries[source_loan.id].transaction_count == 2
    assert summaries[source_loan.id].ledger_month_count == 1
    assert summaries[target_loan.id].transaction_count == 0

    moved = relink_loan_transactions(db_session, target_loan.id, source_loan.id)

    assert moved == 2
    summaries = list_loan_import_summaries(db_session)
    assert summaries[source_loan.id].transaction_count == 0
    assert summaries[target_loan.id].transaction_count == 2
    target_ledger = list_loan_ledger(db_session, target_loan.id)
    assert target_ledger[0].emi_paid == Decimal("37602.00")
    assert target_ledger[0].prepayment_paid == Decimal("10000.00")


def test_bank_statement_ingestion_detects_and_links_loan_transactions(db_session):
    loan = _create_test_loan(db_session)
    sample_file = Path(__file__).resolve().parents[1] / "sample_data" / "dummy_bank_statement_with_loan.csv"

    response = ingest_document_bytes(
        session=db_session,
        filename=sample_file.name,
        content=sample_file.read_bytes(),
        mime_type="text/csv",
        account_name="Primary Account",
        source_type_override="bank_statement",
    )

    document = db_session.get(Document, response.document.id)
    loan_transactions = db_session.scalars(select(LoanTransaction).order_by(LoanTransaction.id.asc())).all()
    assert document.document_type == "bank_statement"
    assert {item.loan_transaction_type for item in loan_transactions} == {"emi", "prepayment"}
    assert {item.loan_id for item in loan_transactions} == {loan.id}
    assert list_loan_ledger(db_session, loan.id)


def test_loan_statement_upload_creates_placeholder_loan_and_ledger(db_session):
    sample_file = Path(__file__).resolve().parents[1] / "sample_data" / "dummy_loan_statement.csv"

    response = ingest_document_bytes(
        session=db_session,
        filename=sample_file.name,
        content=sample_file.read_bytes(),
        mime_type="text/csv",
        account_name="Home Loan Account",
        source_type_override="loan",
    )

    document = db_session.get(Document, response.document.id)
    loan = db_session.scalar(select(Loan))
    loan_transactions = db_session.scalars(select(LoanTransaction).order_by(LoanTransaction.id.asc())).all()
    ledger = list_loan_ledger(db_session, loan.id)

    assert document.document_type == "loan_statement"
    assert loan.name.startswith("Loan from")
    assert {item.loan_transaction_type for item in loan_transactions} >= {"emi", "prepayment", "processing_fee"}
    assert len(ledger) == 2
    assert ledger[0].rate_source == "bank_statement"


def test_loan_statement_can_be_auto_detected_from_content(db_session):
    sample_file = Path(__file__).resolve().parents[1] / "sample_data" / "dummy_loan_statement.csv"

    response = ingest_document_bytes(
        session=db_session,
        filename="generic_statement.csv",
        content=sample_file.read_bytes(),
        mime_type="text/csv",
        account_name="Home Loan Account",
    )

    document = db_session.get(Document, response.document.id)
    assert document.document_type == "loan_statement"
    assert db_session.scalar(select(Loan)) is not None


def _create_test_loan(
    db_session,
    outstanding: int | float | Decimal | None = 1000000,
    annual_rate: int | float | Decimal | None = 12,
    start_date_value: date = date(2026, 5, 1),
) -> Loan:
    loan = Loan(
        name="Home Loan",
        lender_name="Example Bank",
        bank_name="Example Bank",
        loan_type="home_loan",
        masked_loan_account_number="****4455",
        principal=Decimal("1000000"),
        interest_rate_annual=Decimal(str(annual_rate)) if annual_rate is not None else None,
        rate_type="floating",
        start_date=start_date_value,
        tenure_months=240,
        emi_amount=Decimal("50000"),
        outstanding_balance=Decimal(str(outstanding)) if outstanding is not None else None,
    )
    db_session.add(loan)
    db_session.commit()
    return loan


def _loan_transaction(
    loan: Loan,
    transaction_type: str,
    amount: int | float | Decimal,
    transaction_date: date,
    description: str,
    **extra,
) -> LoanTransaction:
    return LoanTransaction(
        loan_id=loan.id,
        transaction_date=transaction_date,
        raw_description=description,
        amount=Decimal(str(amount)),
        direction="debit",
        loan_transaction_type=transaction_type,
        loan_match_reason="test fixture",
        confidence_score=0.9,
        review_status="pending",
        **extra,
    )
