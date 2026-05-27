from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import (
    AuditLog,
    Document,
    Loan,
    LoanManualOverride,
    LoanMonthlyLedger,
    LoanRateEvent,
    LoanTransaction,
    Transaction,
)
from app.services.loans.detection import classify_loan_transaction
from app.services.loans.calculator import analyze_home_loan
from app.services.loans.ledger import month_start, recalculate_loan_ledger
from app.services.parsers.models import ParsedTransactionRow


@dataclass(frozen=True)
class LoanImportSummary:
    loan_id: int | None
    transaction_count: int
    ledger_month_count: int
    total_emi_paid: Decimal
    total_prepayment_paid: Decimal
    total_interest_charged: Decimal
    latest_closing_outstanding: Decimal | None
    first_month: date | None
    latest_month: date | None


def list_loans(session: Session) -> list[Loan]:
    return session.scalars(select(Loan).order_by(Loan.created_at.desc(), Loan.id.desc())).all()


def list_loan_import_summaries(session: Session) -> dict[int | None, LoanImportSummary]:
    transaction_rows = session.execute(
        select(
            LoanTransaction.loan_id,
            func.count(LoanTransaction.id),
        ).group_by(LoanTransaction.loan_id)
    ).all()
    summaries: dict[int | None, LoanImportSummary] = {
        loan_id: LoanImportSummary(
            loan_id=loan_id,
            transaction_count=int(transaction_count or 0),
            ledger_month_count=0,
            total_emi_paid=Decimal("0.00"),
            total_prepayment_paid=Decimal("0.00"),
            total_interest_charged=Decimal("0.00"),
            latest_closing_outstanding=None,
            first_month=None,
            latest_month=None,
        )
        for loan_id, transaction_count in transaction_rows
    }

    for loan in list_loans(session):
        summaries.setdefault(
            loan.id,
            LoanImportSummary(
                loan_id=loan.id,
                transaction_count=0,
                ledger_month_count=0,
                total_emi_paid=Decimal("0.00"),
                total_prepayment_paid=Decimal("0.00"),
                total_interest_charged=Decimal("0.00"),
                latest_closing_outstanding=None,
                first_month=None,
                latest_month=None,
            ),
        )

    for loan_id in [loan_id for loan_id in summaries if loan_id is not None]:
        ledger = session.scalars(
            select(LoanMonthlyLedger)
            .where(LoanMonthlyLedger.loan_id == loan_id)
            .order_by(LoanMonthlyLedger.month.asc())
        ).all()
        base = summaries[loan_id]
        latest_closing = next((row.closing_outstanding for row in reversed(ledger) if row.closing_outstanding is not None), None)
        summaries[loan_id] = LoanImportSummary(
            loan_id=loan_id,
            transaction_count=base.transaction_count,
            ledger_month_count=len(ledger),
            total_emi_paid=sum((row.emi_paid for row in ledger), start=Decimal("0.00")),
            total_prepayment_paid=sum((row.prepayment_paid for row in ledger), start=Decimal("0.00")),
            total_interest_charged=sum((row.interest_charged or Decimal("0.00") for row in ledger), start=Decimal("0.00")),
            latest_closing_outstanding=latest_closing,
            first_month=ledger[0].month if ledger else None,
            latest_month=ledger[-1].month if ledger else None,
        )
    return summaries


def save_loan(
    session: Session,
    name: str,
    principal: float,
    interest_rate_annual: float,
    start_date: date,
    tenure_months: int,
    emi_amount: float,
    outstanding_balance: float | None = None,
    lender_name: str | None = None,
    bank_name: str | None = None,
    masked_loan_account_number: str | None = None,
    rate_type: str = "unknown",
    source_document_id: int | None = None,
    loan_type: str = "home_loan",
    loan_id: int | None = None,
    notes: str | None = None,
) -> Loan:
    loan = session.get(Loan, loan_id) if loan_id else None
    action = "loan_updated" if loan else "loan_created"
    if loan is None:
        loan = Loan(name=name)
        session.add(loan)

    loan.name = name
    loan.lender_name = lender_name
    loan.bank_name = bank_name
    loan.loan_type = loan_type
    loan.masked_loan_account_number = masked_loan_account_number
    loan.principal = Decimal(str(principal))
    loan.interest_rate_annual = Decimal(str(interest_rate_annual))
    loan.rate_type = rate_type
    loan.start_date = start_date
    loan.tenure_months = tenure_months
    loan.emi_amount = Decimal(str(emi_amount))
    loan.outstanding_balance = Decimal(str(outstanding_balance)) if outstanding_balance is not None else None
    loan.source_document_id = source_document_id
    loan.notes = notes

    session.flush()
    session.add(
        AuditLog(
            action=action,
            entity_type="loan",
            entity_id=str(loan.id),
            details={
                "name": loan.name,
                "loan_type": loan.loan_type,
                "emi_amount": float(loan.emi_amount or 0),
            },
        )
    )
    session.commit()
    if session.scalar(select(func.count(LoanTransaction.id)).where(LoanTransaction.loan_id == loan.id)):
        recalculate_loan_ledger(session, loan.id)
    session.refresh(loan)
    return loan


def list_loan_transactions(session: Session, loan_id: int | None = None, include_unlinked: bool = False) -> list[LoanTransaction]:
    statement = select(LoanTransaction).order_by(LoanTransaction.transaction_date.desc(), LoanTransaction.id.desc())
    if loan_id is not None:
        if include_unlinked:
            statement = statement.where((LoanTransaction.loan_id == loan_id) | (LoanTransaction.loan_id.is_(None)))
        else:
            statement = statement.where(LoanTransaction.loan_id == loan_id)
    elif not include_unlinked:
        statement = statement.where(LoanTransaction.loan_id.is_not(None))
    return session.scalars(statement).all()


def relink_loan_transactions(
    session: Session,
    target_loan_id: int,
    source_loan_id: int | None,
) -> int:
    target_loan = session.get(Loan, target_loan_id)
    if target_loan is None:
        raise ValueError(f"Target loan {target_loan_id} was not found.")

    if source_loan_id is not None and source_loan_id == target_loan_id:
        return 0
    if source_loan_id is not None and session.get(Loan, source_loan_id) is None:
        raise ValueError(f"Source loan {source_loan_id} was not found.")

    statement = select(LoanTransaction)
    if source_loan_id is None:
        statement = statement.where(LoanTransaction.loan_id.is_(None))
    else:
        statement = statement.where(LoanTransaction.loan_id == source_loan_id)
    transactions = session.scalars(statement).all()
    for transaction in transactions:
        transaction.loan_id = target_loan_id
        transaction.review_status = "pending" if transaction.review_status == "ignored" else transaction.review_status
        session.add(transaction)
    session.add(
        AuditLog(
            action="loan_transactions_relinked",
            entity_type="loan",
            entity_id=str(target_loan_id),
            details={
                "target_loan_id": target_loan_id,
                "source_loan_id": source_loan_id,
                "transaction_count": len(transactions),
            },
        )
    )
    session.commit()

    affected_loan_ids = {target_loan_id}
    if source_loan_id is not None:
        affected_loan_ids.add(source_loan_id)
    for loan_id in affected_loan_ids:
        recalculate_loan_ledger(session, loan_id)
    return len(transactions)


def detect_and_store_loan_transactions(
    session: Session,
    document: Document,
    transactions: list[Transaction],
    parsed_rows: list[ParsedTransactionRow] | None = None,
) -> int:
    row_lookup = {index: row for index, row in enumerate(parsed_rows or [])}
    loan = _loan_for_auto_mapping(session, document)
    created_count = 0

    for index, transaction in enumerate(transactions):
        row = row_lookup.get(index)
        classification = classify_loan_transaction(
            description=transaction.raw_description,
            amount=transaction.amount,
            transaction_type=transaction.transaction_type,
            document_type=document.document_type,
        )
        if classification is None:
            continue
        if session.scalar(select(LoanTransaction.id).where(LoanTransaction.transaction_id == transaction.id)):
            continue

        extra = row.extra if row else {}
        loan_transaction = LoanTransaction(
            loan_id=loan.id if loan else None,
            transaction_id=transaction.id,
            source_document_id=document.id,
            transaction_date=transaction.date,
            raw_description=transaction.raw_description,
            amount=transaction.amount,
            direction=transaction.transaction_type,
            loan_transaction_type=classification.loan_transaction_type,
            loan_match_reason=classification.loan_match_reason,
            confidence_score=classification.confidence_score,
            review_status="pending",
            opening_outstanding=extra.get("opening_outstanding"),
            closing_outstanding=extra.get("closing_outstanding"),
            interest_component=extra.get("interest_charged"),
            principal_component=extra.get("principal_paid"),
            charges_component=extra.get("charges_paid"),
            provided_annual_rate=extra.get("annual_rate"),
        )
        session.add(loan_transaction)
        created_count += 1

    if created_count:
        session.flush()
        if loan:
            recalculate_loan_ledger(session, loan.id)
        else:
            session.commit()
    return created_count


def _loan_for_auto_mapping(session: Session, document: Document) -> Loan | None:
    loans = list_loans(session)
    if len(loans) == 1:
        return loans[0]
    if loans:
        return None
    if document.document_type != "loan_statement":
        return None

    loan = Loan(
        name=f"Loan from {document.filename}",
        lender_name=document.detected_source_name,
        bank_name=document.detected_source_name,
        loan_type="home_loan",
        rate_type="unknown",
        source_document_id=document.id,
        notes="Auto-created placeholder from loan statement upload. Review and complete loan profile.",
    )
    session.add(loan)
    session.flush()
    return loan


def update_loan_transaction(
    session: Session,
    loan_transaction_id: int,
    loan_id: int | None = None,
    loan_transaction_type: str | None = None,
    review_status: str | None = None,
    notes: str | None = None,
) -> LoanTransaction:
    loan_transaction = session.get(LoanTransaction, loan_transaction_id)
    if loan_transaction is None:
        raise ValueError(f"Loan transaction {loan_transaction_id} was not found.")

    old_loan_id = loan_transaction.loan_id
    if loan_id is not None:
        loan_transaction.loan_id = loan_id if loan_id > 0 else None
    if loan_transaction_type:
        loan_transaction.loan_transaction_type = loan_transaction_type
    if review_status:
        loan_transaction.review_status = review_status
    if notes is not None:
        loan_transaction.notes = notes

    session.add(
        AuditLog(
            action="loan_transaction_updated",
            entity_type="loan_transaction",
            entity_id=str(loan_transaction.id),
            details={
                "loan_id": loan_transaction.loan_id,
                "loan_transaction_type": loan_transaction.loan_transaction_type,
                "review_status": loan_transaction.review_status,
            },
        )
    )
    session.commit()

    affected_loan_ids = {loan_id for loan_id in [old_loan_id, loan_transaction.loan_id] if loan_id}
    for affected_loan_id in affected_loan_ids:
        recalculate_loan_ledger(session, affected_loan_id)
    session.refresh(loan_transaction)
    return loan_transaction


def save_loan_manual_override(
    session: Session,
    loan_id: int,
    month: date,
    opening_outstanding: float | None = None,
    closing_outstanding: float | None = None,
    interest_charged: float | None = None,
    principal_paid: float | None = None,
    charges_paid: float | None = None,
    annual_rate: float | None = None,
    notes: str | None = None,
) -> LoanManualOverride:
    ledger_month = month_start(month)
    override = session.scalar(
        select(LoanManualOverride).where(
            LoanManualOverride.loan_id == loan_id,
            LoanManualOverride.month == ledger_month,
        )
    )
    if override is None:
        override = LoanManualOverride(loan_id=loan_id, month=ledger_month)
        session.add(override)

    override.opening_outstanding = Decimal(str(opening_outstanding)) if opening_outstanding is not None else None
    override.closing_outstanding = Decimal(str(closing_outstanding)) if closing_outstanding is not None else None
    override.interest_charged = Decimal(str(interest_charged)) if interest_charged is not None else None
    override.principal_paid = Decimal(str(principal_paid)) if principal_paid is not None else None
    override.charges_paid = Decimal(str(charges_paid)) if charges_paid is not None else None
    override.annual_rate = Decimal(str(annual_rate)) if annual_rate is not None else None
    override.notes = notes
    override.is_active = True
    session.commit()
    recalculate_loan_ledger(session, loan_id)
    session.refresh(override)
    return override


def save_loan_rate_event(
    session: Session,
    effective_date: date,
    rate_name: str,
    rate_percent: float,
    loan_id: int | None = None,
    source_note: str | None = None,
    document_id: int | None = None,
) -> LoanRateEvent:
    event = LoanRateEvent(
        loan_id=loan_id,
        effective_date=effective_date,
        rate_name=rate_name,
        rate_percent=Decimal(str(rate_percent)),
        source_note=source_note,
        document_id=document_id,
    )
    session.add(event)
    session.commit()
    if loan_id:
        recalculate_loan_ledger(session, loan_id)
    session.refresh(event)
    return event


def analyze_saved_loan(
    session: Session,
    loan_id: int,
    recurring_extra_payment: float = 0.0,
    one_time_prepayment_amount: float = 0.0,
    one_time_prepayment_date: date | None = None,
    as_of_date: date | None = None,
):
    loan = session.get(Loan, loan_id)
    if loan is None:
        raise ValueError(f"Loan {loan_id} was not found.")
    if loan.principal is None or loan.interest_rate_annual is None or loan.start_date is None or loan.tenure_months is None:
        raise ValueError("Loan profile is incomplete.")

    prepayments = []
    if one_time_prepayment_amount > 0 and one_time_prepayment_date:
        from app.services.loans.calculator import LoanPrepayment

        prepayments.append(
            LoanPrepayment(
                payment_date=one_time_prepayment_date,
                amount=Decimal(str(one_time_prepayment_amount)),
            )
        )

    return analyze_home_loan(
        principal=loan.principal,
        annual_interest_rate=loan.interest_rate_annual,
        start_date=loan.start_date,
        tenure_months=loan.tenure_months,
        emi_amount=loan.emi_amount,
        current_outstanding_balance=loan.outstanding_balance or loan.principal,
        recurring_extra_payment=Decimal(str(recurring_extra_payment)),
        one_time_prepayments=prepayments,
        as_of_date=as_of_date or loan.start_date,
    )
