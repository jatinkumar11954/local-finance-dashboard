from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.config import reload_settings
from app.models.entities import Document, Loan, LoanPayment, Transaction
from app.services.rag import answer_local_finance_query


def _create_document(
    db_session,
    *,
    filename: str,
    document_type: str = "bank_statement",
    raw_text: str | None = None,
) -> Document:
    document = Document(
        filename=filename,
        stored_path=f"/tmp/{filename}",
        content_hash=uuid4().hex,
        mime_type="text/plain",
        document_type=document_type,
        parsing_status="parsed",
        parsing_confidence=0.95,
        record_count=0,
        raw_text=raw_text,
    )
    db_session.add(document)
    db_session.flush()
    return document


def _create_transaction(
    db_session,
    *,
    tx_date: date,
    amount: Decimal,
    transaction_type: str,
    category: str,
    payment_mode: str,
    raw_description: str,
    source_document_id: int | None,
    merchant_name: str | None = None,
) -> Transaction:
    transaction = Transaction(
        date=tx_date,
        description=merchant_name or raw_description[:120],
        raw_description=raw_description,
        amount=amount,
        transaction_type=transaction_type,
        payment_mode=payment_mode,
        category=category,
        confidence_score=0.9,
        merchant_name=merchant_name,
        source_document_id=source_document_id,
    )
    db_session.add(transaction)
    db_session.flush()
    return transaction


def test_assistant_food_query_returns_total_and_evidence(db_session):
    document = _create_document(db_session, filename="bank_food.csv")
    _create_transaction(
        db_session,
        tx_date=date(2026, 5, 3),
        amount=Decimal("640.00"),
        transaction_type="debit",
        category="Food Delivery",
        payment_mode="UPI",
        raw_description="UPI/SWIGGY/food order",
        merchant_name="Swiggy",
        source_document_id=document.id,
    )
    _create_transaction(
        db_session,
        tx_date=date(2026, 5, 12),
        amount=Decimal("820.00"),
        transaction_type="debit",
        category="Food Delivery",
        payment_mode="UPI",
        raw_description="UPI/ZOMATO/dinner order",
        merchant_name="Zomato",
        source_document_id=document.id,
    )
    _create_transaction(
        db_session,
        tx_date=date(2026, 5, 2),
        amount=Decimal("28000.00"),
        transaction_type="debit",
        category="Rent",
        payment_mode="NEFT",
        raw_description="NEFT HOUSE RENT",
        source_document_id=document.id,
    )
    db_session.commit()

    response = answer_local_finance_query(
        session=db_session,
        question="How much did I spend on food last month?",
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 31),
    )

    assert response.handler == "food_spend"
    assert response.data_available is True
    assert "₹1,460.00" in response.answer
    assert len(response.supporting_transactions) == 2
    assert len(response.supporting_documents) >= 1


def test_assistant_benchmark_query_uses_local_benchmark_table(db_session):
    document = _create_document(db_session, filename="bank_benchmark.csv")
    _create_transaction(
        db_session,
        tx_date=date(2026, 5, 2),
        amount=Decimal("28000.00"),
        transaction_type="debit",
        category="Rent",
        payment_mode="NEFT",
        raw_description="NEFT HOUSE RENT TO LANDLORD",
        source_document_id=document.id,
    )
    _create_transaction(
        db_session,
        tx_date=date(2026, 5, 4),
        amount=Decimal("7200.00"),
        transaction_type="debit",
        category="Groceries",
        payment_mode="CARD",
        raw_description="POS GROCERY",
        source_document_id=document.id,
    )
    db_session.commit()

    response = answer_local_finance_query(
        session=db_session,
        question="How does my monthly spend compare with Hyderabad comfortable living standards?",
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 31),
    )

    assert response.handler == "benchmark_comparison"
    assert response.data_available is True
    assert "Hyderabad 'Comfortable living'" in response.answer
    assert response.confidence_score >= 0.8


def test_assistant_emi_query_uses_loan_payment_table(db_session):
    document = _create_document(db_session, filename="loan_statement.pdf", document_type="loan_statement")
    loan = Loan(name="Home Loan", loan_type="home_loan")
    db_session.add(loan)
    db_session.flush()
    db_session.add(
        LoanPayment(
            loan_id=loan.id,
            payment_date=date(2026, 5, 7),
            amount=Decimal("40000.00"),
            principal_component=Decimal("15000.00"),
            interest_component=Decimal("25000.00"),
            source_document_id=document.id,
        )
    )
    db_session.commit()

    response = answer_local_finance_query(
        session=db_session,
        question="How much EMI did I pay this month?",
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 31),
    )

    assert response.handler == "emi_loan"
    assert response.data_available is True
    assert "₹40,000.00" in response.answer
    assert len(response.supporting_documents) >= 1


def test_assistant_keyword_search_uses_document_text(db_session):
    _create_document(
        db_session,
        filename="loan_notes.txt",
        document_type="loan_statement",
        raw_text="Home loan amortization schedule updated with outstanding principal details.",
    )
    db_session.commit()

    response = answer_local_finance_query(
        session=db_session,
        question="show amortization outstanding principal details",
    )

    assert response.handler == "keyword_search"
    assert response.data_available is True
    assert len(response.supporting_documents) >= 1


def test_assistant_returns_clear_missing_data_message(db_session):
    response = answer_local_finance_query(
        session=db_session,
        question="How much did I spend on food last month?",
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 31),
    )

    assert response.handler == "food_spend"
    assert response.data_available is False
    assert "not available" in response.answer.lower()


def test_assistant_can_use_configured_local_ollama_response(db_session, monkeypatch):
    document = _create_document(db_session, filename="bank_food.csv")
    _create_transaction(
        db_session,
        tx_date=date(2026, 5, 3),
        amount=Decimal("640.00"),
        transaction_type="debit",
        category="Food Delivery",
        payment_mode="UPI",
        raw_description="UPI/SWIGGY/food order",
        merchant_name="Swiggy",
        source_document_id=document.id,
    )
    db_session.commit()

    monkeypatch.setenv("LFI_LOCAL_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LFI_OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("LFI_OLLAMA_MODEL", "qwen2.5:7b-instruct")
    reload_settings()
    monkeypatch.setattr(
        "app.services.rag.assistant._call_ollama_generate",
        lambda base_url, model, prompt: "Local model answer using the supplied transaction evidence.",
    )

    response = answer_local_finance_query(
        session=db_session,
        question="How much did I spend on food?",
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 31),
        use_local_llm=True,
    )

    assert response.used_local_llm is True
    assert response.local_llm_model == "qwen2.5:7b-instruct"
    assert response.answer == "Local model answer using the supplied transaction evidence."


def test_assistant_refuses_non_local_llm_url(db_session, monkeypatch):
    monkeypatch.setenv("LFI_LOCAL_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LFI_OLLAMA_BASE_URL", "https://example.com")
    reload_settings()
    monkeypatch.setattr(
        "app.services.rag.assistant._call_ollama_generate",
        lambda base_url, model, prompt: "should not be used",
    )

    response = answer_local_finance_query(
        session=db_session,
        question="How much did I spend on food?",
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 31),
        use_local_llm=True,
    )

    assert response.used_local_llm is False
    assert response.answer != "should not be used"
