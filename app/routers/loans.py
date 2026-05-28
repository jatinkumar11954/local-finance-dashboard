from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.loan import (
    LoanActualProjectedRowRead,
    LoanCreate,
    LoanManualOverrideCreate,
    LoanMonthlyLedgerRead,
    LoanProjectionRead,
    LoanProjectionSummaryRead,
    LoanRateEventCreate,
    LoanRead,
    LoanTransactionRead,
    LoanTransactionUpdate,
    LoanUpdate,
)
from app.services.loans import (
    build_loan_projection,
    list_loan_ledger,
    list_loan_transactions,
    list_loans,
    recalculate_loan_ledger,
    revert_loan_transaction_to_source,
    save_loan,
    save_loan_manual_override,
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


@router.get("/{loan_id}/monthly-ledger", response_model=list[LoanMonthlyLedgerRead])
def get_loan_monthly_ledger(loan_id: int, session: Session = Depends(get_db)) -> list[LoanMonthlyLedgerRead]:
    return [LoanMonthlyLedgerRead.model_validate(row) for row in list_loan_ledger(session, loan_id)]


@router.post("/{loan_id}/recalculate", response_model=list[LoanMonthlyLedgerRead])
def post_recalculate_loan(loan_id: int, session: Session = Depends(get_db)) -> list[LoanMonthlyLedgerRead]:
    try:
        return [LoanMonthlyLedgerRead.model_validate(row) for row in recalculate_loan_ledger(session, loan_id)]
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{loan_id}/recalculate-ledger", response_model=list[LoanMonthlyLedgerRead])
def post_recalculate_loan_ledger(loan_id: int, session: Session = Depends(get_db)) -> list[LoanMonthlyLedgerRead]:
    return post_recalculate_loan(loan_id=loan_id, session=session)


@router.get("/{loan_id}/projection", response_model=LoanProjectionRead)
def get_loan_projection(
    loan_id: int,
    future_monthly_extra_prepayment: float = 0.0,
    session: Session = Depends(get_db),
) -> LoanProjectionRead:
    loan = next((item for item in list_loans(session) if item.id == loan_id), None)
    if loan is None:
        raise HTTPException(status_code=404, detail=f"Loan {loan_id} was not found.")
    result = build_loan_projection(
        loan=loan,
        ledger_rows=list_loan_ledger(session, loan_id),
        future_monthly_extra_prepayment=future_monthly_extra_prepayment,
    )
    return _projection_to_schema(result)


@router.post("/{loan_id}/projection", response_model=LoanProjectionRead)
def post_loan_projection(
    loan_id: int,
    future_monthly_extra_prepayment: float = 0.0,
    session: Session = Depends(get_db),
) -> LoanProjectionRead:
    return get_loan_projection(
        loan_id=loan_id,
        future_monthly_extra_prepayment=future_monthly_extra_prepayment,
        session=session,
    )


@router.post("/{loan_id}/manual-override")
def post_loan_manual_override(
    loan_id: int,
    payload: LoanManualOverrideCreate,
    session: Session = Depends(get_db),
) -> dict[str, int]:
    override = save_loan_manual_override(session=session, loan_id=loan_id, **payload.model_dump())
    return {"id": override.id}


@router.patch("/{loan_id}/monthly-ledger/{month}")
def patch_loan_monthly_ledger(
    loan_id: int,
    month,
    payload: LoanManualOverrideCreate,
    session: Session = Depends(get_db),
) -> dict[str, int]:
    override = save_loan_manual_override(session=session, loan_id=loan_id, month=payload.month or month, **payload.model_dump(exclude={"month"}))
    return {"id": override.id}


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
        transaction = update_loan_transaction(
            session,
            loan_transaction_id=loan_transaction_id,
            **payload.model_dump(exclude_unset=True),
        )
        return LoanTransactionRead.model_validate(transaction)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@loan_transactions_router.post("/{loan_transaction_id}/revert", response_model=LoanTransactionRead)
def post_revert_loan_transaction(
    loan_transaction_id: int,
    session: Session = Depends(get_db),
) -> LoanTransactionRead:
    try:
        transaction = revert_loan_transaction_to_source(session, loan_transaction_id=loan_transaction_id)
        return LoanTransactionRead.model_validate(transaction)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _projection_to_schema(result) -> LoanProjectionRead:
    return LoanProjectionRead(
        summary=LoanProjectionSummaryRead(
            estimated_remaining_tenure_months=result.summary.estimated_remaining_tenure_months,
            estimated_total_future_interest=float(result.summary.estimated_total_future_interest)
            if result.summary.estimated_total_future_interest is not None
            else None,
            estimated_closure_date=result.summary.estimated_closure_date,
            estimated_interest_saved_by_prepayment=float(result.summary.estimated_interest_saved_by_prepayment),
            estimated_tenure_reduced_months=result.summary.estimated_tenure_reduced_months,
        ),
        actual_vs_projected=[
            LoanActualProjectedRowRead(
                month=row.month,
                projected_interest=float(row.projected_interest) if row.projected_interest is not None else None,
                actual_interest=float(row.actual_interest) if row.actual_interest is not None else None,
                interest_difference=float(row.interest_difference) if row.interest_difference is not None else None,
                projected_principal=float(row.projected_principal) if row.projected_principal is not None else None,
                actual_principal=float(row.actual_principal) if row.actual_principal is not None else None,
                principal_difference=float(row.principal_difference) if row.principal_difference is not None else None,
                projected_closing=float(row.projected_closing) if row.projected_closing is not None else None,
                actual_closing=float(row.actual_closing) if row.actual_closing is not None else None,
                prepayment_impact=float(row.prepayment_impact) if row.prepayment_impact is not None else None,
            )
            for row in result.actual_vs_projected
        ],
    )
