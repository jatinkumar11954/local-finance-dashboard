from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.entities import Transaction


class TransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    date: date
    description: str
    raw_description: str
    amount: float
    transaction_type: str
    account_source: str | None
    payment_mode: str
    merchant_name: str | None
    category: str
    subcategory: str | None
    tags: list[str]
    confidence_score: float
    currency: str
    running_balance: float | None
    is_recurring: bool
    is_personal_transfer: bool
    is_business_expense: bool
    is_excluded: bool
    notes: str | None
    source_document_id: int | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, transaction: Transaction) -> "TransactionRead":
        return cls(
            id=transaction.id,
            date=transaction.date,
            description=transaction.description,
            raw_description=transaction.raw_description,
            amount=float(transaction.amount),
            transaction_type=transaction.transaction_type,
            account_source=transaction.account_source,
            payment_mode=transaction.payment_mode,
            merchant_name=transaction.merchant_name,
            category=transaction.category,
            subcategory=transaction.subcategory,
            tags=list(transaction.tags or []),
            confidence_score=transaction.confidence_score,
            currency=transaction.currency,
            running_balance=float(transaction.running_balance) if transaction.running_balance is not None else None,
            is_recurring=transaction.is_recurring,
            is_personal_transfer=transaction.is_personal_transfer,
            is_business_expense=transaction.is_business_expense,
            is_excluded=transaction.is_excluded,
            notes=transaction.notes,
            source_document_id=transaction.source_document_id,
            created_at=transaction.created_at,
            updated_at=transaction.updated_at,
        )


class TransactionUpdate(BaseModel):
    category: str | None = None
    subcategory: str | None = None
    merchant_name: str | None = None
    notes: str | None = None
    is_recurring: bool | None = None
    is_personal_transfer: bool | None = None
    is_business_expense: bool | None = None
    is_excluded: bool | None = None
    tags: list[str] | None = Field(default=None)


class BulkTransactionUpdateItem(BaseModel):
    transaction_id: int
    updates: TransactionUpdate


class BulkTransactionUpdateRequest(BaseModel):
    items: list[BulkTransactionUpdateItem]


class BulkTransactionUpdateResponse(BaseModel):
    updated_count: int
