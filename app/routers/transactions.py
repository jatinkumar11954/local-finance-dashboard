from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.transaction import (
    BulkTransactionUpdateRequest,
    BulkTransactionUpdateResponse,
    TransactionRead,
    TransactionUpdate,
)
from app.services.transactions import bulk_update_transactions, query_transactions, update_transaction


router = APIRouter(prefix="/api/transactions", tags=["transactions"])


@router.get("", response_model=list[TransactionRead])
def get_transactions(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    category: str | None = Query(default=None),
    payment_mode: str | None = Query(default=None),
    merchant_query: str | None = Query(default=None),
    transaction_type: str | None = Query(default=None),
    document_id: int | None = Query(default=None),
    max_confidence: float | None = Query(default=None),
    include_excluded: bool = Query(default=True),
    session: Session = Depends(get_db),
) -> list[TransactionRead]:
    transactions = query_transactions(
        session=session,
        start_date=start_date,
        end_date=end_date,
        category=category,
        payment_mode=payment_mode,
        merchant_query=merchant_query,
        transaction_type=transaction_type,
        document_id=document_id,
        max_confidence=max_confidence,
        include_excluded=include_excluded,
    )
    return [TransactionRead.from_model(transaction) for transaction in transactions]


@router.patch("/{transaction_id}", response_model=TransactionRead)
def patch_transaction(
    transaction_id: int,
    payload: TransactionUpdate,
    session: Session = Depends(get_db),
) -> TransactionRead:
    try:
        transaction = update_transaction(session, transaction_id, payload)
        return TransactionRead.from_model(transaction)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/bulk-update", response_model=BulkTransactionUpdateResponse)
def post_bulk_update_transactions(
    payload: BulkTransactionUpdateRequest,
    session: Session = Depends(get_db),
) -> BulkTransactionUpdateResponse:
    updated_count = bulk_update_transactions(session, payload.items)
    return BulkTransactionUpdateResponse(updated_count=updated_count)
