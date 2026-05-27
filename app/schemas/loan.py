from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class LoanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    lender_name: str | None
    bank_name: str | None
    loan_type: str
    masked_loan_account_number: str | None
    principal: float | None
    interest_rate_annual: float | None
    rate_type: str
    start_date: date | None
    tenure_months: int | None
    emi_amount: float | None
    outstanding_balance: float | None
    source_document_id: int | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class LoanCreate(BaseModel):
    name: str
    principal: float = 0.0
    interest_rate_annual: float = 0.0
    start_date: date
    tenure_months: int
    emi_amount: float = 0.0
    outstanding_balance: float | None = None
    lender_name: str | None = None
    bank_name: str | None = None
    masked_loan_account_number: str | None = None
    rate_type: str = "unknown"
    loan_type: str = "home_loan"
    source_document_id: int | None = None
    notes: str | None = None


class LoanUpdate(LoanCreate):
    pass


class LoanTransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    loan_id: int | None
    transaction_id: int | None
    source_document_id: int | None
    transaction_date: date
    raw_description: str
    amount: float
    direction: str
    loan_transaction_type: str
    loan_match_reason: str | None
    confidence_score: float
    review_status: str
    opening_outstanding: float | None
    closing_outstanding: float | None
    interest_component: float | None
    principal_component: float | None
    charges_component: float | None
    provided_annual_rate: float | None
    notes: str | None


class LoanTransactionUpdate(BaseModel):
    loan_id: int | None = None
    loan_transaction_type: str | None = None
    review_status: str | None = None
    notes: str | None = None


class LoanMonthlyLedgerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    loan_id: int
    month: date
    opening_outstanding: float | None
    emi_paid: float
    prepayment_paid: float
    interest_charged: float | None
    principal_paid: float | None
    charges_paid: float
    closing_outstanding: float | None
    inferred_monthly_rate: float | None
    inferred_annual_rate: float | None
    provided_annual_rate: float | None
    rate_source: str
    confidence_score: float
    calculation_notes: str | None


class LoanRateEventCreate(BaseModel):
    effective_date: date
    rate_name: str
    rate_percent: float
    source_note: str | None = None
    document_id: int | None = None
