from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.entities import AssistantQuery, CreditCardStatement, Document, LoanPayment, Transaction
from app.schemas.assistant import (
    AssistantDocumentEvidence,
    AssistantResponse,
    AssistantTransactionEvidence,
)
from app.services.analytics import analyze_upi_transactions
from app.services.benchmarks import compare_to_benchmarks
from app.services.credit_cards import analyze_credit_card_transactions
from app.utils.amounts import MAX_REASONABLE_TRANSACTION_AMOUNT


STOPWORDS = {
    "how",
    "much",
    "did",
    "for",
    "the",
    "and",
    "with",
    "show",
    "all",
    "from",
    "this",
    "that",
    "are",
    "was",
    "what",
    "where",
    "when",
    "which",
    "last",
    "month",
    "year",
    "please",
    "my",
    "me",
    "in",
    "on",
    "of",
    "to",
    "by",
    "is",
    "it",
}
DISCRETIONARY_CATEGORIES = {
    "Food Delivery",
    "Restaurants",
    "Shopping",
    "Entertainment",
    "Travel",
    "Miscellaneous",
}
DATE_RANGE_FY_PATTERN = re.compile(r"\bfy\s*(\d{4})\s*[-/]\s*(\d{2,4})\b", re.IGNORECASE)


def answer_local_finance_query(
    session: Session,
    question: str,
    start_date: date | None = None,
    end_date: date | None = None,
    use_local_embeddings: bool = False,
    use_local_llm: bool = False,
) -> AssistantResponse:
    cleaned_question = " ".join(question.strip().split())
    normalized = cleaned_question.lower()
    range_start, range_end = _resolve_date_range(session, normalized, start_date, end_date)

    if any(keyword in normalized for keyword in {"hyderabad", "benchmark", "comfortable living", "basic living", "premium living"}):
        response = _handle_benchmark_comparison(session, cleaned_question, normalized, range_start, range_end)
    elif "credit card" in normalized and any(keyword in normalized for keyword in {"interest", "fee", "charge"}):
        response = _handle_credit_card_interest_and_fees(session, range_start, range_end)
    elif "emi" in normalized or ("loan" in normalized and any(word in normalized for word in {"paid", "payment", "interest"})):
        response = _handle_emi_and_loan_query(session, normalized, range_start, range_end)
    elif any(keyword in normalized for keyword in {"recurring", "repeated", "repeat"}):
        response = _handle_recurring_query(session, range_start, range_end)
    elif any(keyword in normalized for keyword in {"avoidable", "unnecessary", "discretionary"}):
        response = _handle_avoidable_expenses_query(session, range_start, range_end)
    elif any(keyword in normalized for keyword in {"food", "swiggy", "zomato", "restaurant", "grocery"}):
        response = _handle_food_spend_query(session, range_start, range_end)
    elif "spend" in normalized or "expense" in normalized:
        response = _handle_category_spend_query(session, normalized, range_start, range_end)
    else:
        response = _handle_keyword_search(
            session=session,
            question=cleaned_question,
            normalized_question=normalized,
            range_start=range_start,
            range_end=range_end,
            use_local_embeddings=use_local_embeddings,
        )

    if use_local_llm:
        response = _maybe_enhance_with_local_llm(cleaned_question, response)

    session.add(
        AssistantQuery(
            question=cleaned_question,
            answer=response.answer,
            date_range_start=response.date_range_start,
            date_range_end=response.date_range_end,
            confidence_score=response.confidence_score,
        )
    )
    session.commit()
    return response


def _resolve_date_range(
    session: Session,
    normalized_question: str,
    start_date: date | None,
    end_date: date | None,
) -> tuple[date | None, date | None]:
    if start_date and end_date:
        return start_date, end_date

    today = date.today()
    if "last month" in normalized_question:
        first_of_current_month = today.replace(day=1)
        last_day_previous_month = first_of_current_month - timedelta(days=1)
        return last_day_previous_month.replace(day=1), last_day_previous_month
    if "this month" in normalized_question:
        return today.replace(day=1), today
    if "today" in normalized_question:
        return today, today
    if "yesterday" in normalized_question:
        yesterday = today - timedelta(days=1)
        return yesterday, yesterday

    fy_match = DATE_RANGE_FY_PATTERN.search(normalized_question)
    if fy_match:
        fy_start = int(fy_match.group(1))
        fy_end_fragment = fy_match.group(2)
        fy_end = int(fy_end_fragment) if len(fy_end_fragment) == 4 else (fy_start // 100) * 100 + int(fy_end_fragment)
        if fy_end < fy_start:
            fy_end += 100
        return date(fy_start, 4, 1), date(fy_end, 3, 31)

    min_date, max_date = session.execute(
        select(func.min(Transaction.date), func.max(Transaction.date)).where(Transaction.is_excluded.is_(False))
    ).one()
    return min_date, max_date


def _transaction_evidence_rows(transactions: list[Transaction]) -> list[AssistantTransactionEvidence]:
    return [
        AssistantTransactionEvidence(
            transaction_id=transaction.id,
            date=transaction.date,
            amount=float(transaction.amount),
            transaction_type=transaction.transaction_type,
            category=transaction.category,
            merchant_name=transaction.merchant_name,
            payment_mode=transaction.payment_mode,
            description=transaction.raw_description,
            source_document_id=transaction.source_document_id,
        )
        for transaction in transactions
    ]


def _document_evidence_rows(
    session: Session,
    document_ids: set[int],
    query_terms: list[str] | None = None,
) -> list[AssistantDocumentEvidence]:
    if not document_ids:
        return []

    documents = session.scalars(select(Document).where(Document.id.in_(document_ids)).order_by(Document.id.desc())).all()
    evidence: list[AssistantDocumentEvidence] = []
    for document in documents:
        snippet = _extract_snippet(document.raw_text, query_terms) if document.raw_text else None
        evidence.append(
            AssistantDocumentEvidence(
                document_id=document.id,
                filename=document.filename,
                document_type=document.document_type,
                snippet=snippet,
            )
        )
    return evidence


def _extract_snippet(raw_text: str, query_terms: list[str] | None = None) -> str | None:
    if not raw_text:
        return None

    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if not lines:
        return None

    if query_terms:
        lowered_terms = [term.lower() for term in query_terms]
        for line in lines:
            lowered_line = line.lower()
            if any(term in lowered_line for term in lowered_terms):
                return line[:180]
    return lines[0][:180]


def _response(
    *,
    answer: str,
    range_start: date | None,
    range_end: date | None,
    transactions: list[Transaction],
    documents: list[AssistantDocumentEvidence],
    method: str,
    confidence_score: float,
    data_available: bool,
    handler: str,
    used_local_embeddings: bool = False,
    used_local_llm: bool = False,
    local_llm_model: str | None = None,
) -> AssistantResponse:
    score = max(0.0, min(confidence_score, 1.0))
    if score >= 0.85:
        confidence_level = "high"
    elif score >= 0.55:
        confidence_level = "medium"
    else:
        confidence_level = "low"

    return AssistantResponse(
        answer=answer,
        date_range_start=range_start,
        date_range_end=range_end,
        supporting_transactions=_transaction_evidence_rows(transactions),
        supporting_documents=documents,
        calculation_method=method,
        confidence_level=confidence_level,
        confidence_score=round(score, 2),
        data_available=data_available,
        handler=handler,
        used_local_embeddings=used_local_embeddings,
        used_local_llm=used_local_llm,
        local_llm_model=local_llm_model,
    )


def _filter_transactions(
    session: Session,
    range_start: date | None,
    range_end: date | None,
    extra_filters: list | None = None,
    limit: int = 200,
) -> list[Transaction]:
    statement = select(Transaction).where(
        Transaction.is_excluded.is_(False),
        Transaction.amount <= MAX_REASONABLE_TRANSACTION_AMOUNT,
    )
    if range_start:
        statement = statement.where(Transaction.date >= range_start)
    if range_end:
        statement = statement.where(Transaction.date <= range_end)
    if extra_filters:
        statement = statement.where(and_(*extra_filters))
    statement = statement.order_by(Transaction.date.desc(), Transaction.id.desc()).limit(limit)
    return session.scalars(statement).all()


def _handle_food_spend_query(
    session: Session,
    range_start: date | None,
    range_end: date | None,
) -> AssistantResponse:
    categories = ["Food Delivery", "Restaurants", "Groceries"]
    transactions = _filter_transactions(
        session=session,
        range_start=range_start,
        range_end=range_end,
        extra_filters=[Transaction.transaction_type == "debit", Transaction.category.in_(categories)],
    )
    if not transactions:
        return _response(
            answer="Food spending data is not available for the selected date range.",
            range_start=range_start,
            range_end=range_end,
            transactions=[],
            documents=[],
            method="Filtered debit transactions where category is Food Delivery, Restaurants, or Groceries.",
            confidence_score=0.25,
            data_available=False,
            handler="food_spend",
        )

    total = sum((transaction.amount for transaction in transactions), start=Decimal("0.00"))
    document_ids = {transaction.source_document_id for transaction in transactions if transaction.source_document_id}
    documents = _document_evidence_rows(session, document_ids)
    answer = f"Total food spend is ₹{total:,.2f} across {len(transactions)} matched transactions."
    return _response(
        answer=answer,
        range_start=range_start,
        range_end=range_end,
        transactions=transactions[:15],
        documents=documents[:8],
        method="Summed debit transaction amounts for categories Food Delivery, Restaurants, and Groceries.",
        confidence_score=0.9,
        data_available=True,
        handler="food_spend",
    )


def _category_targets_from_question(normalized_question: str) -> list[str]:
    mapping = {
        "rent": ["Rent"],
        "emi": ["Home Loan EMI", "Other Loan EMI"],
        "grocery": ["Groceries"],
        "food": ["Food Delivery", "Restaurants", "Groceries"],
        "utility": ["Utilities", "Electricity", "Water", "Internet", "Mobile Recharge"],
        "fuel": ["Fuel"],
        "transport": ["Transport", "Cab / Auto"],
        "shopping": ["Shopping"],
        "health": ["Healthcare"],
        "insurance": ["Insurance"],
        "entertainment": ["Entertainment"],
        "travel": ["Travel"],
        "subscription": ["Subscriptions"],
        "investment": ["Investments", "Mutual Funds / SIP"],
    }
    for keyword, categories in mapping.items():
        if keyword in normalized_question:
            return categories
    return []


def _handle_category_spend_query(
    session: Session,
    normalized_question: str,
    range_start: date | None,
    range_end: date | None,
) -> AssistantResponse:
    categories = _category_targets_from_question(normalized_question)
    if not categories:
        return _handle_keyword_search(
            session=session,
            question=normalized_question,
            normalized_question=normalized_question,
            range_start=range_start,
            range_end=range_end,
            use_local_embeddings=False,
        )

    transactions = _filter_transactions(
        session=session,
        range_start=range_start,
        range_end=range_end,
        extra_filters=[Transaction.transaction_type == "debit", Transaction.category.in_(categories)],
    )
    if not transactions:
        return _response(
            answer=f"Spending data is not available for categories: {', '.join(categories)} in the selected date range.",
            range_start=range_start,
            range_end=range_end,
            transactions=[],
            documents=[],
            method=f"Filtered debit transactions for categories: {', '.join(categories)}.",
            confidence_score=0.3,
            data_available=False,
            handler="category_spend",
        )

    total = sum((transaction.amount for transaction in transactions), start=Decimal("0.00"))
    by_category: dict[str, Decimal] = {}
    for transaction in transactions:
        by_category[transaction.category] = by_category.get(transaction.category, Decimal("0.00")) + transaction.amount
    category_breakdown = ", ".join(f"{name}: ₹{value:,.2f}" for name, value in sorted(by_category.items()))
    document_ids = {transaction.source_document_id for transaction in transactions if transaction.source_document_id}
    documents = _document_evidence_rows(session, document_ids)
    return _response(
        answer=f"Total spend is ₹{total:,.2f}. Category breakdown: {category_breakdown}.",
        range_start=range_start,
        range_end=range_end,
        transactions=transactions[:15],
        documents=documents[:8],
        method=f"Summed debit amounts for categories mapped from query keywords: {', '.join(categories)}.",
        confidence_score=0.82,
        data_available=True,
        handler="category_spend",
    )


def _handle_emi_and_loan_query(
    session: Session,
    normalized_question: str,
    range_start: date | None,
    range_end: date | None,
) -> AssistantResponse:
    emi_transactions = _filter_transactions(
        session=session,
        range_start=range_start,
        range_end=range_end,
        extra_filters=[
            Transaction.transaction_type == "debit",
            Transaction.category.in_(["Home Loan EMI", "Other Loan EMI", "Loan Interest"]),
        ],
        limit=500,
    )

    loan_statement = select(LoanPayment)
    if range_start:
        loan_statement = loan_statement.where(LoanPayment.payment_date >= range_start)
    if range_end:
        loan_statement = loan_statement.where(LoanPayment.payment_date <= range_end)
    loan_payments = session.scalars(loan_statement).all()

    if not emi_transactions and not loan_payments:
        return _response(
            answer="Loan or EMI payment data is not available for the selected date range.",
            range_start=range_start,
            range_end=range_end,
            transactions=[],
            documents=[],
            method="Checked loan_payments table and debit transactions in EMI/Loan categories.",
            confidence_score=0.25,
            data_available=False,
            handler="emi_loan",
        )

    emi_total = sum((transaction.amount for transaction in emi_transactions), start=Decimal("0.00"))
    principal_total = sum((payment.principal_component or Decimal("0.00")) for payment in loan_payments)
    interest_total = sum((payment.interest_component or Decimal("0.00")) for payment in loan_payments)
    payments_total = sum((payment.amount for payment in loan_payments), start=Decimal("0.00"))

    wants_interest = "interest" in normalized_question
    if wants_interest:
        answer = (
            f"Loan interest tracked in loan_payments is ₹{interest_total:,.2f}. "
            f"Loan payments total ₹{payments_total:,.2f} and principal tracked is ₹{principal_total:,.2f}."
        )
    else:
        answer = (
            f"EMI/loan-related debit transactions total ₹{emi_total:,.2f}. "
            f"Loan payments table total is ₹{payments_total:,.2f}."
        )

    loan_document_ids = {payment.source_document_id for payment in loan_payments if payment.source_document_id}
    transaction_document_ids = {transaction.source_document_id for transaction in emi_transactions if transaction.source_document_id}
    documents = _document_evidence_rows(session, loan_document_ids | transaction_document_ids)
    return _response(
        answer=answer,
        range_start=range_start,
        range_end=range_end,
        transactions=emi_transactions[:15],
        documents=documents[:10],
        method="Aggregated amounts from loan_payments plus debit transactions in Home Loan EMI, Other Loan EMI, and Loan Interest categories.",
        confidence_score=0.86,
        data_available=True,
        handler="emi_loan",
    )


def _handle_credit_card_interest_and_fees(
    session: Session,
    range_start: date | None,
    range_end: date | None,
) -> AssistantResponse:
    card_analysis = analyze_credit_card_transactions(
        session=session,
        start_date=range_start,
        end_date=range_end,
        include_card_like=True,
    )

    statement_query = select(CreditCardStatement)
    if range_start:
        statement_query = statement_query.where(CreditCardStatement.statement_date >= range_start)
    if range_end:
        statement_query = statement_query.where(CreditCardStatement.statement_date <= range_end)
    statements = session.scalars(statement_query).all()

    total_statement_interest = sum((statement.interest_charged or Decimal("0.00")) for statement in statements)
    total_statement_fees = sum((statement.fees_charged or Decimal("0.00")) for statement in statements)

    flagged = [
        insight
        for insight in card_analysis.classified_transactions
        if insight.charge_type in {"interest_charge", "late_fee", "gst_on_fee", "cash_withdrawal_charge", "over_limit_fee", "fee"}
    ]
    tx_by_id = {transaction.id: transaction for transaction in _filter_transactions(session, range_start, range_end, limit=800)}
    matched_transactions = [tx_by_id[item.transaction_id] for item in flagged if item.transaction_id in tx_by_id]

    if not flagged and total_statement_interest == 0 and total_statement_fees == 0:
        return _response(
            answer="Credit card interest or fee data is not available for the selected range.",
            range_start=range_start,
            range_end=range_end,
            transactions=[],
            documents=[],
            method="Checked classified credit-card transactions and credit_card_statements summary fields.",
            confidence_score=0.3,
            data_available=False,
            handler="credit_card_interest_fees",
        )

    answer = (
        f"Credit card interest charges total ₹{card_analysis.total_interest:,.2f} and extra charges total "
        f"₹{card_analysis.total_extra_charges:,.2f}. Statement summaries show interest ₹{total_statement_interest:,.2f} "
        f"and fees ₹{total_statement_fees:,.2f}."
    )
    document_ids = {transaction.source_document_id for transaction in matched_transactions if transaction.source_document_id}
    statement_document_ids = {statement.source_document_id for statement in statements if statement.source_document_id}
    documents = _document_evidence_rows(session, document_ids | statement_document_ids)
    return _response(
        answer=answer,
        range_start=range_start,
        range_end=range_end,
        transactions=matched_transactions[:20],
        documents=documents[:10],
        method="Used credit-card classifier for interest/fee charge types and summed statement-level interest_charged/fees_charged fields.",
        confidence_score=0.84,
        data_available=True,
        handler="credit_card_interest_fees",
    )


def _handle_recurring_query(
    session: Session,
    range_start: date | None,
    range_end: date | None,
) -> AssistantResponse:
    upi = analyze_upi_transactions(session=session, start_date=range_start, end_date=range_end)
    recurring_transactions = _filter_transactions(
        session=session,
        range_start=range_start,
        range_end=range_end,
        extra_filters=[Transaction.is_recurring.is_(True), Transaction.transaction_type == "debit"],
        limit=300,
    )

    repeated_details = [
        f"{payment.receiver_name} ({payment.cadence}, ₹{payment.typical_amount:,.2f}, {payment.occurrences}x)"
        for payment in upi.repeated_payments[:8]
    ]
    recurring_total = sum((transaction.amount for transaction in recurring_transactions), start=Decimal("0.00"))
    if not repeated_details and not recurring_transactions:
        return _response(
            answer="No recurring payment patterns were detected in the selected date range.",
            range_start=range_start,
            range_end=range_end,
            transactions=[],
            documents=[],
            method="Analyzed UPI repeated-payment patterns and transactions explicitly marked as recurring.",
            confidence_score=0.35,
            data_available=False,
            handler="recurring",
        )

    answer = (
        f"Detected {len(upi.repeated_payments)} repeated UPI receivers and {len(recurring_transactions)} transactions marked recurring. "
        f"Recurring-marked spend total is ₹{recurring_total:,.2f}."
    )
    if repeated_details:
        answer = f"{answer} Examples: " + "; ".join(repeated_details)
    document_ids = {transaction.source_document_id for transaction in recurring_transactions if transaction.source_document_id}
    documents = _document_evidence_rows(session, document_ids)
    return _response(
        answer=answer,
        range_start=range_start,
        range_end=range_end,
        transactions=recurring_transactions[:15],
        documents=documents[:8],
        method="Used deterministic recurring detection from UPI cadence analysis plus explicit recurring flags in transactions table.",
        confidence_score=0.88,
        data_available=True,
        handler="recurring",
    )


def _handle_avoidable_expenses_query(
    session: Session,
    range_start: date | None,
    range_end: date | None,
) -> AssistantResponse:
    transactions = _filter_transactions(
        session=session,
        range_start=range_start,
        range_end=range_end,
        extra_filters=[Transaction.transaction_type == "debit", Transaction.category.in_(sorted(DISCRETIONARY_CATEGORIES))],
        limit=500,
    )
    if not transactions:
        return _response(
            answer="Avoidable expense data is not available for the selected period.",
            range_start=range_start,
            range_end=range_end,
            transactions=[],
            documents=[],
            method="Filtered debit transactions under discretionary categories: Food Delivery, Restaurants, Shopping, Entertainment, Travel, Miscellaneous.",
            confidence_score=0.3,
            data_available=False,
            handler="avoidable_expenses",
        )

    total = sum((transaction.amount for transaction in transactions), start=Decimal("0.00"))
    by_merchant: dict[str, Decimal] = {}
    for transaction in transactions:
        merchant = transaction.merchant_name or "Unknown"
        by_merchant[merchant] = by_merchant.get(merchant, Decimal("0.00")) + transaction.amount
    top_merchants = sorted(by_merchant.items(), key=lambda item: item[1], reverse=True)[:5]
    merchant_summary = ", ".join(f"{merchant}: ₹{amount:,.2f}" for merchant, amount in top_merchants)

    document_ids = {transaction.source_document_id for transaction in transactions if transaction.source_document_id}
    documents = _document_evidence_rows(session, document_ids)
    answer = f"Potentially avoidable discretionary spend is ₹{total:,.2f}. Top merchants: {merchant_summary}."
    return _response(
        answer=answer,
        range_start=range_start,
        range_end=range_end,
        transactions=transactions[:20],
        documents=documents[:10],
        method="Summed debit transactions in discretionary categories and ranked merchants by spend.",
        confidence_score=0.76,
        data_available=True,
        handler="avoidable_expenses",
    )


def _select_benchmark_profile(normalized_question: str) -> str:
    if "basic" in normalized_question:
        return "Basic living"
    if "premium" in normalized_question:
        return "Premium living"
    return "Comfortable living"


def _handle_benchmark_comparison(
    session: Session,
    question: str,
    normalized_question: str,
    range_start: date | None,
    range_end: date | None,
) -> AssistantResponse:
    if range_start is None or range_end is None:
        return _response(
            answer="Benchmark comparison needs transaction date data, but no transactions are available yet.",
            range_start=range_start,
            range_end=range_end,
            transactions=[],
            documents=[],
            method="Attempted to resolve date range and compare transactions to benchmark ranges.",
            confidence_score=0.2,
            data_available=False,
            handler="benchmark_comparison",
        )

    profile = _select_benchmark_profile(normalized_question)
    comparisons = compare_to_benchmarks(
        session=session,
        start_date=range_start,
        end_date=range_end,
        city="Hyderabad",
        profile=profile,
    )
    if not comparisons:
        return _response(
            answer=f"Benchmark data is not available for Hyderabad profile '{profile}'.",
            range_start=range_start,
            range_end=range_end,
            transactions=[],
            documents=[],
            method="Loaded benchmark rows and compared mapped transaction spend category-wise.",
            confidence_score=0.3,
            data_available=False,
            handler="benchmark_comparison",
        )

    above = [item for item in comparisons if item["status"] == "above_range"]
    within = [item for item in comparisons if item["status"] == "within_range"]
    below = [item for item in comparisons if item["status"] == "below_range"]
    answer = (
        f"Compared spending against Hyderabad '{profile}'. "
        f"{len(above)} categories are above range, {len(within)} within range, and {len(below)} below range."
    )
    if above:
        top_above = sorted(above, key=lambda item: item["actual"] - item["benchmark_max"], reverse=True)[:3]
        answer += " Biggest above-range categories: " + "; ".join(
            f"{item['category']} (actual ₹{item['actual']:,.2f}, max ₹{item['benchmark_max']:,.2f})"
            for item in top_above
        )

    transactions = _filter_transactions(
        session=session,
        range_start=range_start,
        range_end=range_end,
        extra_filters=[Transaction.transaction_type == "debit"],
        limit=25,
    )
    document_ids = {transaction.source_document_id for transaction in transactions if transaction.source_document_id}
    documents = _document_evidence_rows(session, document_ids, query_terms=question.split())
    return _response(
        answer=answer,
        range_start=range_start,
        range_end=range_end,
        transactions=transactions,
        documents=documents[:10],
        method="Mapped debit transaction categories to benchmark categories and compared actual spend with benchmark min/max ranges.",
        confidence_score=0.83,
        data_available=True,
        handler="benchmark_comparison",
    )


def _keyword_tokens(question: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z0-9]{3,}", question.lower())
    return [token for token in tokens if token not in STOPWORDS]


def _handle_keyword_search(
    session: Session,
    question: str,
    normalized_question: str,
    range_start: date | None,
    range_end: date | None,
    use_local_embeddings: bool,
) -> AssistantResponse:
    tokens = _keyword_tokens(normalized_question)
    if not tokens:
        return _response(
            answer="Not enough signal in the question to run a local search. Please include keywords like category, merchant, payment mode, or period.",
            range_start=range_start,
            range_end=range_end,
            transactions=[],
            documents=[],
            method="Question tokenization and keyword matching.",
            confidence_score=0.15,
            data_available=False,
            handler="keyword_search",
        )

    tx_conditions = []
    doc_conditions = []
    for token in tokens:
        like = f"%{token}%"
        tx_conditions.append(
            or_(
                Transaction.raw_description.ilike(like),
                Transaction.description.ilike(like),
                Transaction.merchant_name.ilike(like),
                Transaction.category.ilike(like),
                Transaction.payment_mode.ilike(like),
                Transaction.account_source.ilike(like),
            )
        )
        doc_conditions.append(
            or_(
                Document.raw_text.ilike(like),
                Document.filename.ilike(like),
                Document.document_type.ilike(like),
            )
        )

    tx_statement = select(Transaction).where(Transaction.is_excluded.is_(False), or_(*tx_conditions))
    if range_start:
        tx_statement = tx_statement.where(Transaction.date >= range_start)
    if range_end:
        tx_statement = tx_statement.where(Transaction.date <= range_end)
    transactions = session.scalars(tx_statement.order_by(Transaction.date.desc(), Transaction.id.desc()).limit(40)).all()

    doc_statement = select(Document).where(or_(*doc_conditions)).order_by(Document.uploaded_at.desc(), Document.id.desc()).limit(20)
    documents = session.scalars(doc_statement).all()

    used_local_embeddings = False
    if use_local_embeddings and (transactions or documents):
        transactions, documents, used_local_embeddings = _rerank_with_local_embeddings(
            question=question,
            transactions=transactions,
            documents=documents,
        )

    if not transactions and not documents:
        return _response(
            answer="No matching local transactions or documents were found for this question.",
            range_start=range_start,
            range_end=range_end,
            transactions=[],
            documents=[],
            method=f"Keyword search across transaction text fields and document text using tokens: {', '.join(tokens)}.",
            confidence_score=0.2,
            data_available=False,
            handler="keyword_search",
            used_local_embeddings=used_local_embeddings,
        )

    total_spend = sum(
        (transaction.amount for transaction in transactions if transaction.transaction_type == "debit"),
        start=Decimal("0.00"),
    )
    answer = (
        f"Found {len(transactions)} matching transactions and {len(documents)} matching documents in local storage. "
        f"Debit spend across matched transactions is ₹{total_spend:,.2f}."
    )
    document_evidence = _document_evidence_rows(session, {document.id for document in documents}, query_terms=tokens)
    return _response(
        answer=answer,
        range_start=range_start,
        range_end=range_end,
        transactions=transactions[:20],
        documents=document_evidence[:12],
        method=f"Keyword match on local SQLite tables (transactions + documents). Tokens: {', '.join(tokens)}.",
        confidence_score=0.62,
        data_available=True,
        handler="keyword_search",
        used_local_embeddings=used_local_embeddings,
    )


def _rerank_with_local_embeddings(
    question: str,
    transactions: list[Transaction],
    documents: list[Document],
) -> tuple[list[Transaction], list[Document], bool]:
    model = _load_local_embedding_model()
    if model is None:
        return transactions, documents, False

    corpus: list[str] = []
    pointers: list[tuple[str, int]] = []
    for index, transaction in enumerate(transactions):
        corpus.append(
            " | ".join(
                part
                for part in [
                    transaction.raw_description,
                    transaction.category,
                    transaction.merchant_name or "",
                    transaction.payment_mode,
                ]
                if part
            )
        )
        pointers.append(("transaction", index))
    for index, document in enumerate(documents):
        corpus.append(" | ".join(part for part in [document.filename, document.document_type, document.raw_text or ""] if part))
        pointers.append(("document", index))

    if not corpus:
        return transactions, documents, False

    try:
        embeddings = model.encode(corpus, convert_to_numpy=True, normalize_embeddings=True)
        query_vector = model.encode([question], convert_to_numpy=True, normalize_embeddings=True)[0]
    except Exception:
        return transactions, documents, False

    scored = []
    for idx, pointer in enumerate(pointers):
        similarity = float((embeddings[idx] * query_vector).sum())
        scored.append((similarity, pointer))
    scored.sort(key=lambda item: item[0], reverse=True)

    ranked_transactions: list[Transaction] = []
    ranked_documents: list[Document] = []
    for _, (kind, index) in scored:
        if kind == "transaction":
            ranked_transactions.append(transactions[index])
        else:
            ranked_documents.append(documents[index])
    return ranked_transactions, ranked_documents, True


def _maybe_enhance_with_local_llm(question: str, response: AssistantResponse) -> AssistantResponse:
    settings = get_settings()
    if settings.local_llm_provider != "ollama":
        return response
    if not _is_local_url(settings.ollama_base_url):
        return response

    prompt = _build_local_llm_prompt(question, response)
    generated_answer = _call_ollama_generate(settings.ollama_base_url, settings.ollama_model, prompt)
    if not generated_answer:
        return response

    return response.model_copy(
        update={
            "answer": generated_answer.strip(),
            "used_local_llm": True,
            "local_llm_model": settings.ollama_model,
        }
    )


def _is_local_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and parsed.hostname in {"127.0.0.1", "localhost", "::1"}


def _build_local_llm_prompt(question: str, response: AssistantResponse) -> str:
    transaction_lines = [
        (
            f"- {item.date} | {item.transaction_type} | Rs {item.amount:,.2f} | "
            f"{item.category} | {item.merchant_name or 'Unknown'} | {item.description[:160]}"
        )
        for item in response.supporting_transactions[:12]
    ]
    document_lines = [
        f"- {item.filename} ({item.document_type}): {(item.snippet or '')[:220]}"
        for item in response.supporting_documents[:8]
    ]
    return (
        "You are a local-only personal finance assistant. Use only the deterministic answer and evidence below. "
        "Do not invent missing data. If evidence is missing, say so. Keep the answer concise and include the method and confidence.\n\n"
        f"Question: {question}\n"
        f"Deterministic answer: {response.answer}\n"
        f"Date range: {response.date_range_start or 'N/A'} to {response.date_range_end or 'N/A'}\n"
        f"Calculation method: {response.calculation_method}\n"
        f"Confidence: {response.confidence_level} ({response.confidence_score:.2f})\n"
        "Supporting transactions:\n"
        + ("\n".join(transaction_lines) if transaction_lines else "- None")
        + "\nSupporting documents:\n"
        + ("\n".join(document_lines) if document_lines else "- None")
        + "\n\nFinal answer:"
    )


def _call_ollama_generate(base_url: str, model: str, prompt: str) -> str | None:
    try:
        import httpx
    except Exception:
        return None

    try:
        response = httpx.post(
            f"{base_url}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "num_predict": 450,
                },
            },
            timeout=30,
        )
        response.raise_for_status()
    except Exception:
        return None

    payload = response.json()
    answer = payload.get("response")
    return str(answer).strip() if answer else None


def _load_local_embedding_model():
    settings = get_settings()
    model_path = settings.local_embedding_model_path
    if model_path is None:
        return None
    if not Path(model_path).exists():
        return None

    try:
        from sentence_transformers import SentenceTransformer
    except Exception:
        return None

    try:
        return SentenceTransformer(str(model_path), local_files_only=True)
    except Exception:
        return None
