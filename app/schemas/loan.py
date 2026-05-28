from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.services.loans.constants import DEFAULT_BASE_ANNUAL_RATE


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
    summary_total_paid: float | None
    summary_interest_paid: float | None
    summary_principal_paid: float | None
    summary_prepayment_paid: float | None
    source_document_id: int | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class LoanCreate(BaseModel):
    name: str
    principal: float = 0.0
    interest_rate_annual: float = DEFAULT_BASE_ANNUAL_RATE
    start_date: date
    tenure_months: int
    emi_amount: float = 0.0
    outstanding_balance: float | None = None
    summary_total_paid: float | None = None
    summary_interest_paid: float | None = None
    summary_principal_paid: float | None = None
    summary_prepayment_paid: float | None = None
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
    transaction_date: date | None = None
    raw_description: str | None = None
    amount: float | None = None
    direction: str | None = None
    loan_transaction_type: str | None = None
    review_status: str | None = None
    opening_outstanding: float | None = None
    closing_outstanding: float | None = None
    interest_component: float | None = None
    principal_component: float | None = None
    charges_component: float | None = None
    provided_annual_rate: float | None = None
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
    principal_from_emi: float | None
    principal_from_prepayment: float
    total_principal_reduced: float | None
    charges_paid: float
    closing_outstanding: float | None
    inferred_monthly_rate: float | None
    inferred_annual_rate: float | None
    base_annual_rate: float | None
    rate_variance: float | None
    rate_variance_percent: float | None
    provided_annual_rate: float | None
    rate_source: str
    calculation_method: str
    confidence_score: float
    manual_override_used: bool
    review_status: str
    calculation_notes: str | None


class LoanRateEventCreate(BaseModel):
    effective_date: date
    rate_name: str
    rate_percent: float
    source_note: str | None = None
    document_id: int | None = None


class LoanManualOverrideCreate(BaseModel):
    month: date
    opening_outstanding: float | None = None
    closing_outstanding: float | None = None
    interest_charged: float | None = None
    principal_paid: float | None = None
    emi_paid: float | None = None
    prepayment_paid: float | None = None
    charges_paid: float | None = None
    annual_rate: float | None = None
    notes: str | None = None


class LoanActualProjectedRowRead(BaseModel):
    month: date
    projected_interest: float | None
    actual_interest: float | None
    interest_difference: float | None
    projected_principal: float | None
    actual_principal: float | None
    principal_difference: float | None
    projected_closing: float | None
    actual_closing: float | None
    prepayment_impact: float | None


class LoanProjectionSummaryRead(BaseModel):
    estimated_remaining_tenure_months: int | None
    estimated_total_future_interest: float | None
    estimated_closure_date: date | None
    estimated_interest_saved_by_prepayment: float
    estimated_tenure_reduced_months: int


class LoanProjectionRead(BaseModel):
    summary: LoanProjectionSummaryRead
    actual_vs_projected: list[LoanActualProjectedRowRead]
