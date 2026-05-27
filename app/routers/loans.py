from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.loan import (
    LoanCreate,
    LoanMonthlyLedgerRead,
    LoanRateEventCreate,
    LoanRead,
    LoanTransactionRead,
    LoanTransactionUpdate,
    LoanUpdate,
)
from app.services.loans import (
    list_loan_ledger,
    list_loan_transactions,
    list_loans,
    recalculate_loan_ledger,
    save_loan,
    save_loan_rate_event,
    update_loan_transaction,
)


router = APIRouter(prefix="/api/loans", tags=["loans"])
loan_transactions_router = APIRouter(prefix="/api/loan-transactions", tags=["loan-transactions"])


@router.get("", response_model=list[LoanRead])
def get_loans(session: Session = Depends(get_db)) -> list[LoanRead]:
    return [LoanRead.model_validate(loan) for loan in list_loans(session)]


@router.post("", response_model=LoanRead)
def post_loan(payload: LoanCreate, session: Session = Depends(get_db)) -> LoanRead:
    loan = save_loan(session=session, **payload.model_dump())
    return LoanRead.model_validate(loan)


@router.patch("/{loan_id}", response_model=LoanRead)
def patch_loan(loan_id: int, payload: LoanUpdate, session: Session = Depends(get_db)) -> LoanRead:
    try:
        loan = save_loan(session=session, loan_id=loan_id, **payload.model_dump())
        return LoanRead.model_validate(loan)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{loan_id}/transactions", response_model=list[LoanTransactionRead])
def get_loan_transactions(loan_id: int, session: Session = Depends(get_db)) -> list[LoanTransactionRead]:
    return [
        LoanTransactionRead.model_validate(transaction)
        for transaction in list_loan_transactions(session, loan_id=loan_id, include_unlinked=True)
    ]


@router.get("/{loan_id}/ledger", response_model=list[LoanMonthlyLedgerRead])
def get_loan_ledger(loan_id: int, session: Session = Depends(get_db)) -> list[LoanMonthlyLedgerRead]:
    return [LoanMonthlyLedgerRead.model_validate(row) for row in list_loan_ledger(session, loan_id)]


@router.post("/{loan_id}/recalculate", response_model=list[LoanMonthlyLedgerRead])
def post_recalculate_loan(loan_id: int, session: Session = Depends(get_db)) -> list[LoanMonthlyLedgerRead]:
    try:
        return [LoanMonthlyLedgerRead.model_validate(row) for row in recalculate_loan_ledger(session, loan_id)]
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{loan_id}/rate-events")
def post_loan_rate_event(loan_id: int, payload: LoanRateEventCreate, session: Session = Depends(get_db)) -> dict[str, int]:
    event = save_loan_rate_event(session=session, loan_id=loan_id, **payload.model_dump())
    return {"id": event.id}


@loan_transactions_router.patch("/{loan_transaction_id}", response_model=LoanTransactionRead)
def patch_loan_transaction(
    loan_transaction_id: int,
    payload: LoanTransactionUpdate,
    session: Session = Depends(get_db),
) -> LoanTransactionRead:
    try:
        transaction = update_loan_transaction(session, loan_transaction_id=loan_transaction_id, **payload.model_dump())
        return LoanTransactionRead.model_validate(transaction)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
