from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from app.models.entities import CreditCard, CreditCardTransaction, Document, Loan, LoanMonthlyLedger, Transaction
from app.services.analytics import AnalyticsFilters, build_analytics_response, calculate_overview, get_upi_analytics
from app.services.documents import ingest_document_bytes


def test_overview_metrics_are_generated(db_session):
    sample_file = Path(__file__).resolve().parents[1] / "sample_data" / "dummy_bank_statement.csv"
    ingest_document_bytes(
        session=db_session,
        filename=sample_file.name,
        content=sample_file.read_bytes(),
        mime_type="text/csv",
        account_name="Primary Account",
        source_type_override="auto",
    )

    overview = calculate_overview(
        session=db_session,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 31),
        benchmark_profile="Comfortable living",
    )

    assert overview.total_income == 125000.0
    assert overview.total_expenses > 0
    assert overview.transaction_count == 10
    assert any(item.label == "Rent" for item in overview.top_categories)


def _document(db_session, filename: str, document_type: str) -> Document:
    document = Document(
        filename=filename,
        stored_path=f"/tmp/{filename}",
        content_hash=f"{filename}-{document_type}",
        mime_type="text/csv",
        document_type=document_type,
        parsing_status="parsed",
        parsing_confidence=0.95,
    )
    db_session.add(document)
    db_session.flush()
    return document


def _transaction(
    db_session,
    document: Document,
    transaction_date: date,
    description: str,
    amount: str,
    transaction_type: str = "debit",
    category: str = "Miscellaneous",
    payment_mode: str = "unknown",
    merchant_name: str | None = None,
    is_personal_transfer: bool = False,
) -> Transaction:
    transaction = Transaction(
        date=transaction_date,
        description=description[:255],
        raw_description=description,
        amount=Decimal(amount),
        transaction_type=transaction_type,
        account_source="Synthetic Account",
        payment_mode=payment_mode,
        merchant_name=merchant_name,
        category=category,
        tags=[],
        confidence_score=0.9,
        is_personal_transfer=is_personal_transfer,
        source_document_id=document.id,
    )
    db_session.add(transaction)
    db_session.flush()
    return transaction


def _credit_card_transaction(
    db_session,
    card: CreditCard,
    transaction: Transaction,
    parsed_type: str,
) -> CreditCardTransaction:
    card_transaction = CreditCardTransaction(
        card_id=card.id,
        transaction_id=transaction.id,
        transaction_date=transaction.date,
        description=transaction.raw_description,
        amount=transaction.amount,
        transaction_type=transaction.transaction_type,
        parsed_type=parsed_type,
        merchant_name=transaction.merchant_name,
        category=transaction.category,
        source_document_id=transaction.source_document_id,
        confidence_score=0.9,
    )
    db_session.add(card_transaction)
    db_session.flush()
    return card_transaction


def test_source_separation_and_credit_card_payment_deduplication(db_session):
    bank_document = _document(db_session, "bank.csv", "bank_statement")
    card_document = _document(db_session, "card.csv", "credit_card_statement")

    _transaction(
        db_session,
        bank_document,
        date(2026, 4, 1),
        "UPI-GROCERY STORE",
        "2000.00",
        category="Groceries",
        payment_mode="UPI",
        merchant_name="Grocery Store",
    )
    _transaction(
        db_session,
        bank_document,
        date(2026, 4, 3),
        "CREDIT CARD PAYMENT HDFC",
        "5000.00",
        category="Credit Card Payment",
        payment_mode="NETBANKING",
        merchant_name="HDFC Card",
    )
    card_purchase = _transaction(
        db_session,
        card_document,
        date(2026, 4, 2),
        "POS-ELECTRONICS SHOP",
        "3000.00",
        category="Shopping",
        payment_mode="CARD",
        merchant_name="Electronics Shop",
    )
    card = CreditCard(name="Synthetic Card", bank_name="Test Bank", last4="1234", usage_type="normal")
    db_session.add(card)
    db_session.flush()
    _credit_card_transaction(db_session, card, card_purchase, "purchase")

    bank_response = build_analytics_response(
        db_session,
        AnalyticsFilters(source_type="bank_statement", include_credit_card_bill_payments=True),
    )
    card_response = build_analytics_response(db_session, AnalyticsFilters(source_type="credit_card_statement"))
    unified_response = build_analytics_response(db_session, AnalyticsFilters())
    unified_with_liabilities = build_analytics_response(
        db_session,
        AnalyticsFilters(include_credit_card_bill_payments=True),
    )

    assert {row["source_type"] for row in bank_response["tables"]["transactions"]} == {"bank_statement"}
    assert {row["source_type"] for row in card_response["tables"]["transactions"]} == {"credit_card_statement"}
    assert unified_response["summary"]["true_expense"] == 5000.0
    assert unified_with_liabilities["summary"]["true_expense"] == 5000.0
    assert unified_with_liabilities["summary"]["liability_payment"] == 5000.0


def test_upi_analytics_combines_bank_upi_and_upi_only_credit_card(db_session):
    bank_document = _document(db_session, "bank-upi.csv", "bank_statement")
    card_document = _document(db_session, "rupay-upi-card.csv", "credit_card_statement")

    _transaction(
        db_session,
        bank_document,
        date(2026, 4, 4),
        "UPI/123/GROCERY STORE@ybl",
        "120.00",
        category="Groceries",
        payment_mode="UPI",
        merchant_name="Grocery Store",
    )
    _transaction(
        db_session,
        bank_document,
        date(2026, 4, 5),
        "UPI/124/SELF TRANSFER@okaxis",
        "80.00",
        category="UPI Transfers",
        payment_mode="UPI",
        is_personal_transfer=True,
    )
    card = CreditCard(name="UPI Card", bank_name="Test Bank", last4="9999", usage_type="upi_only")
    db_session.add(card)
    db_session.flush()
    card_upi = _transaction(
        db_session,
        card_document,
        date(2026, 4, 6),
        "RUPAY UPI-456-BHARATPE MERCHANT@paytm",
        "220.00",
        category="Food Delivery",
        payment_mode="UPI",
        merchant_name="BharatPe Merchant",
    )
    _credit_card_transaction(db_session, card, card_upi, "upi_card_spend")

    response = get_upi_analytics(db_session, AnalyticsFilters(include_internal_transfers=True))
    sources = {row["source_type"] for row in response["tables"]["transactions"]}
    person_vs_merchant = {row["type"]: row["amount"] for row in response["charts"]["person_vs_merchant"]}

    assert {"bank_statement", "credit_card_statement"}.issubset(sources)
    assert response["summary"]["upi_spend"] == 340.0
    assert person_vs_merchant["person_transfer"] == 80.0
    assert person_vs_merchant["merchant_payment"] == 340.0
    assert any(row["source_card_usage_type"] == "upi_only" for row in response["tables"]["transactions"])


def test_loan_ledger_impact_does_not_double_count_emi_rows(db_session):
    bank_document = _document(db_session, "loan-bank.csv", "bank_statement")
    _transaction(
        db_session,
        bank_document,
        date(2026, 4, 10),
        "LOAN RECOVERY FOR80740600007603",
        "10000.00",
        category="Home Loan EMI",
        payment_mode="AUTOPAY",
    )
    loan = Loan(name="Synthetic Home Loan")
    db_session.add(loan)
    db_session.flush()
    db_session.add(
        LoanMonthlyLedger(
            loan_id=loan.id,
            month=date(2026, 4, 1),
            opening_outstanding=Decimal("500000.00"),
            emi_paid=Decimal("10000.00"),
            prepayment_paid=Decimal("0.00"),
            interest_charged=Decimal("3000.00"),
            principal_from_emi=Decimal("7000.00"),
            principal_from_prepayment=Decimal("0.00"),
            total_principal_reduced=Decimal("7000.00"),
            charges_paid=Decimal("0.00"),
            closing_outstanding=Decimal("493000.00"),
            calculation_method="actual_from_opening_closing",
            confidence_score=0.9,
        )
    )
    db_session.flush()

    response = build_analytics_response(db_session, AnalyticsFilters(include_credit_card_bill_payments=True))
    card_response = build_analytics_response(db_session, AnalyticsFilters(source_type="credit_card_statement"))

    assert response["summary"]["true_expense"] == 0.0
    assert response["summary"]["total_emi_burden"] == 10000.0
    assert response["summary"]["debt_interest"] == 3000.0
    assert response["summary"]["debt_principal"] == 7000.0
    assert card_response["summary"]["total_emi_burden"] == 0.0
    assert card_response["summary"]["debt_interest"] == 0.0


def test_manual_refund_tag_reduces_true_spend(db_session):
    bank_document = _document(db_session, "manual-refund-bank.csv", "bank_statement")
    _transaction(
        db_session,
        bank_document,
        date(2026, 4, 12),
        "SHOPPING PURCHASE",
        "1000.00",
        category="Shopping",
        payment_mode="UPI",
        merchant_name="Synthetic Shop",
    )
    refund = _transaction(
        db_session,
        bank_document,
        date(2026, 4, 13),
        "MERCHANT CREDIT",
        "200.00",
        transaction_type="credit",
        category="Shopping",
        payment_mode="UPI",
        merchant_name="Synthetic Shop",
    )
    refund.tags = ["refund"]
    db_session.flush()

    response = build_analytics_response(db_session, AnalyticsFilters())
    shopping = next(row for row in response["tables"]["category_breakdown"] if row["category"] == "Shopping")

    assert response["summary"]["true_expense"] == 800.0
    assert response["summary"]["refund_adjustment"] == 200.0
    assert shopping["amount"] == 800.0


def test_recurring_anomaly_and_budget_outputs(db_session):
    bank_document = _document(db_session, "analytics-bank.csv", "bank_statement")
    for month in (1, 2, 3):
        _transaction(
            db_session,
            bank_document,
            date(2026, month, 5),
            "NETFLIX SUBSCRIPTION",
            "649.00",
            category="Subscriptions",
            payment_mode="CARD",
            merchant_name="Netflix",
        )
    for day in (1, 2, 3, 4):
        _transaction(
            db_session,
            bank_document,
            date(2026, 4, day),
            f"SMALL ENTERTAINMENT {day}",
            "100.00",
            category="Entertainment",
            payment_mode="UPI",
            merchant_name="Small Cafe",
        )
    _transaction(
        db_session,
        bank_document,
        date(2026, 4, 8),
        "LARGE ENTERTAINMENT EVENT",
        "5000.00",
        category="Entertainment",
        payment_mode="UPI",
        merchant_name="Event Venue",
    )
    _transaction(
        db_session,
        bank_document,
        date(2026, 4, 9),
        "MONTHLY GROCERIES",
        "13000.00",
        category="Groceries",
        payment_mode="UPI",
        merchant_name="Grocery Store",
    )

    response = build_analytics_response(
        db_session,
        AnalyticsFilters(benchmark_profile="Comfortable living"),
    )

    assert any(row["name"] == "Netflix" for row in response["tables"]["recurring"])
    assert any(row["title"] == "High transaction" for row in response["tables"]["anomalies"])
    assert any(
        row["category"] == "Groceries" and row["status"] == "over_benchmark"
        for row in response["tables"]["budget_comparison"]
    )


def test_analytics_api_returns_consistent_response_shape(db_session):
    bank_document = _document(db_session, "api-bank.csv", "bank_statement")
    _transaction(
        db_session,
        bank_document,
        date(2026, 4, 10),
        "UPI-API TEST MERCHANT",
        "250.00",
        category="Restaurants",
        payment_mode="UPI",
        merchant_name="API Merchant",
    )
    db_session.commit()

    from app.database import get_db
    from app.main import app

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            response = client.get("/api/analytics/summary?source_type=all_sources")
            bank_response = client.get("/api/analytics/bank/summary")
            card_response = client.get("/api/analytics/credit-cards/summary")
            upi_response = client.get("/api/analytics/upi/summary")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert {"filters", "summary", "charts", "tables", "insights", "warnings", "generated_at"}.issubset(payload)
    assert payload["summary"]["true_expense"] == 250.0
    for endpoint_response in (bank_response, card_response, upi_response):
        assert endpoint_response.status_code == 200
        endpoint_payload = endpoint_response.json()
        assert {"filters", "summary", "charts", "tables", "insights", "warnings", "generated_at"}.issubset(endpoint_payload)
