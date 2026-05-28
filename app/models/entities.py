from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, utcnow


class Account(TimestampMixin, Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    institution_name: Mapped[str | None] = mapped_column(String(120))
    account_type: Mapped[str | None] = mapped_column(String(50))
    masked_account_number: Mapped[str | None] = mapped_column(String(20))
    currency: Mapped[str] = mapped_column(String(10), default="INR", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    documents: Mapped[list["Document"]] = relationship(back_populates="account")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="account")


class Document(TimestampMixin, Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(500), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(120))
    document_type: Mapped[str] = mapped_column(String(50), default="unknown", nullable=False)
    detected_source_name: Mapped[str | None] = mapped_column(String(120))
    parsing_status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    parsing_confidence: Mapped[float] = mapped_column(default=0.0, nullable=False)
    record_count: Mapped[int] = mapped_column(default=0, nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))

    account: Mapped["Account | None"] = relationship(back_populates="documents")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="source_document")


class Transaction(TimestampMixin, Base):
    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_transactions_date", "date"),
        Index("ix_transactions_category", "category"),
        Index("ix_transactions_payment_mode", "payment_mode"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    raw_description: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(20), nullable=False)
    account_source: Mapped[str | None] = mapped_column(String(120))
    payment_mode: Mapped[str] = mapped_column(String(40), default="unknown", nullable=False)
    merchant_name: Mapped[str | None] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(100), default="Miscellaneous", nullable=False)
    subcategory: Mapped[str | None] = mapped_column(String(100))
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    confidence_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="INR", nullable=False)
    running_balance: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_personal_transfer: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_business_expense: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_excluded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    source_document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))

    source_document: Mapped["Document | None"] = relationship(back_populates="transactions")
    account: Mapped["Account | None"] = relationship(back_populates="transactions")


class Category(TimestampMixin, Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    parent_name: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class CategoryRule(TimestampMixin, Base):
    __tablename__ = "category_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    pattern: Mapped[str] = mapped_column(String(255), nullable=False)
    field_name: Mapped[str] = mapped_column(String(50), default="description", nullable=False)
    target_category: Mapped[str] = mapped_column(String(100), nullable=False)
    target_subcategory: Mapped[str | None] = mapped_column(String(100))
    priority: Mapped[int] = mapped_column(default=50, nullable=False)
    is_regex: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    case_sensitive: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Merchant(TimestampMixin, Base):
    __tablename__ = "merchants"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    category: Mapped[str | None] = mapped_column(String(100))
    subcategory: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)


class Loan(TimestampMixin, Base):
    __tablename__ = "loans"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    lender_name: Mapped[str | None] = mapped_column(String(120))
    bank_name: Mapped[str | None] = mapped_column(String(120))
    loan_type: Mapped[str] = mapped_column(String(50), default="home_loan", nullable=False)
    masked_loan_account_number: Mapped[str | None] = mapped_column(String(32))
    principal: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    interest_rate_annual: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    rate_type: Mapped[str] = mapped_column(String(20), default="unknown", nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date)
    tenure_months: Mapped[int | None] = mapped_column()
    emi_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    outstanding_balance: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    summary_total_paid: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    summary_interest_paid: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    summary_principal_paid: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    summary_prepayment_paid: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    source_document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))
    notes: Mapped[str | None] = mapped_column(Text)


class LoanPayment(TimestampMixin, Base):
    __tablename__ = "loan_payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    loan_id: Mapped[int] = mapped_column(ForeignKey("loans.id"), nullable=False)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    principal_component: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    interest_component: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    extra_principal: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    source_document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))
    notes: Mapped[str | None] = mapped_column(Text)


class LoanTransaction(TimestampMixin, Base):
    __tablename__ = "loan_transactions"
    __table_args__ = (
        UniqueConstraint("transaction_id", name="uq_loan_transactions_transaction_id"),
        Index("ix_loan_transactions_loan_month", "loan_id", "transaction_date"),
        Index("ix_loan_transactions_type", "loan_transaction_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    loan_id: Mapped[int | None] = mapped_column(ForeignKey("loans.id"))
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"))
    source_document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    raw_description: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), default="debit", nullable=False)
    loan_transaction_type: Mapped[str] = mapped_column(String(40), default="unknown", nullable=False)
    loan_match_reason: Mapped[str | None] = mapped_column(Text)
    confidence_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    review_status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    opening_outstanding: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    closing_outstanding: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    interest_component: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    principal_component: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    charges_component: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    provided_annual_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    notes: Mapped[str | None] = mapped_column(Text)


class LoanMonthlyLedger(TimestampMixin, Base):
    __tablename__ = "loan_monthly_ledger"
    __table_args__ = (
        UniqueConstraint("loan_id", "month", name="uq_loan_monthly_ledger_loan_month"),
        Index("ix_loan_monthly_ledger_loan_month", "loan_id", "month"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    loan_id: Mapped[int] = mapped_column(ForeignKey("loans.id"), nullable=False)
    month: Mapped[date] = mapped_column(Date, nullable=False)
    opening_outstanding: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    emi_paid: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"), nullable=False)
    prepayment_paid: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"), nullable=False)
    interest_charged: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    principal_paid: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    principal_from_emi: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    principal_from_prepayment: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"), nullable=False)
    total_principal_reduced: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    charges_paid: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"), nullable=False)
    closing_outstanding: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    inferred_monthly_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 8))
    inferred_annual_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    base_annual_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    rate_variance: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    rate_variance_percent: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    provided_annual_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    rate_source: Mapped[str] = mapped_column(String(40), default="unknown", nullable=False)
    calculation_method: Mapped[str] = mapped_column(String(60), default="unknown", nullable=False)
    confidence_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    manual_override_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    review_status: Mapped[str] = mapped_column(String(40), default="ok", nullable=False)
    calculation_notes: Mapped[str | None] = mapped_column(Text)


class LoanRateEvent(TimestampMixin, Base):
    __tablename__ = "loan_rate_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    loan_id: Mapped[int | None] = mapped_column(ForeignKey("loans.id"))
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    rate_name: Mapped[str] = mapped_column(String(120), nullable=False)
    rate_percent: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    source_note: Mapped[str | None] = mapped_column(Text)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))


class LoanManualOverride(TimestampMixin, Base):
    __tablename__ = "loan_manual_overrides"
    __table_args__ = (
        UniqueConstraint("loan_id", "month", name="uq_loan_manual_overrides_loan_month"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    loan_id: Mapped[int] = mapped_column(ForeignKey("loans.id"), nullable=False)
    month: Mapped[date] = mapped_column(Date, nullable=False)
    opening_outstanding: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    closing_outstanding: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    interest_charged: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    principal_paid: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    emi_paid: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    prepayment_paid: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    charges_paid: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    annual_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class LoanProjectionScenario(TimestampMixin, Base):
    __tablename__ = "loan_projection_scenarios"
    __table_args__ = (
        Index("ix_loan_projection_scenarios_loan", "loan_id", "scenario_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    loan_id: Mapped[int] = mapped_column(ForeignKey("loans.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    scenario_type: Mapped[str] = mapped_column(String(40), default="base", nullable=False)
    base_annual_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    start_month: Mapped[date | None] = mapped_column(Date)
    opening_outstanding: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    scheduled_emi: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    recurring_extra_payment: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"), nullable=False)
    one_time_prepayment: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"), nullable=False)
    projected_closure_date: Mapped[date | None] = mapped_column(Date)
    projected_total_interest: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    interest_saved: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    tenure_months_saved: Mapped[int | None] = mapped_column()
    notes: Mapped[str | None] = mapped_column(Text)


class LoanProjectionRow(Base):
    __tablename__ = "loan_projection_rows"
    __table_args__ = (
        Index("ix_loan_projection_rows_scenario_month", "scenario_id", "month"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("loan_projection_scenarios.id"), nullable=False)
    month: Mapped[date] = mapped_column(Date, nullable=False)
    opening_outstanding: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    projected_emi: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    projected_interest: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    projected_principal: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    projected_prepayment: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"), nullable=False)
    closing_outstanding: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow)


class CreditCard(TimestampMixin, Base):
    __tablename__ = "credit_cards"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    issuer_name: Mapped[str | None] = mapped_column(String(120))
    bank_name: Mapped[str | None] = mapped_column(String(120))
    last4: Mapped[str | None] = mapped_column(String(4))
    masked_card_number: Mapped[str | None] = mapped_column(String(20))
    usage_type: Mapped[str] = mapped_column(String(30), default="normal", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    statement_day: Mapped[int | None] = mapped_column()
    due_day: Mapped[int | None] = mapped_column()
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))


class CreditCardStatement(TimestampMixin, Base):
    __tablename__ = "credit_card_statements"
    __table_args__ = (
        UniqueConstraint("credit_card_id", "source_document_id", name="uq_credit_card_statement_document"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    credit_card_id: Mapped[int] = mapped_column(ForeignKey("credit_cards.id"), nullable=False)
    statement_date: Mapped[date] = mapped_column(Date, nullable=False)
    statement_month: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    total_due: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    minimum_due: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    total_amount_due: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    minimum_amount_due: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    payment_due_date: Mapped[date | None] = mapped_column(Date)
    uploaded_tag: Mapped[str] = mapped_column(String(40), default="normal", nullable=False)
    interest_charged: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    fees_charged: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    source_document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))


class CreditCardTransaction(TimestampMixin, Base):
    __tablename__ = "credit_card_transactions"
    __table_args__ = (
        UniqueConstraint("transaction_id", name="uq_credit_card_transactions_transaction"),
        Index("ix_credit_card_transactions_card_date", "card_id", "transaction_date"),
        Index("ix_credit_card_transactions_parsed_type", "parsed_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("credit_cards.id"), nullable=False)
    statement_id: Mapped[int | None] = mapped_column(ForeignKey("credit_card_statements.id"))
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"))
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    posting_date: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(20), nullable=False)
    parsed_type: Mapped[str] = mapped_column(String(50), default="unknown", nullable=False)
    merchant_name: Mapped[str | None] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(100))
    source_document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))
    confidence_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    manual_override: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    match_reason: Mapped[str | None] = mapped_column(Text)


class CreditCardEmiPlan(TimestampMixin, Base):
    __tablename__ = "credit_card_emi_plans"
    __table_args__ = (
        Index("ix_credit_card_emi_plans_card_status", "card_id", "lifecycle_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("credit_cards.id"), nullable=False)
    merchant_name: Mapped[str | None] = mapped_column(String(255))
    original_transaction_date: Mapped[date | None] = mapped_column(Date)
    original_transaction_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    emi_start_month: Mapped[date | None] = mapped_column(Date)
    emi_end_month: Mapped[date | None] = mapped_column(Date)
    monthly_emi_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    total_emi_count: Mapped[int | None] = mapped_column()
    pending_emi_count: Mapped[int | None] = mapped_column()
    completed_emi_count: Mapped[int | None] = mapped_column()
    no_cost_claimed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    no_cost_verification_status: Mapped[str] = mapped_column(String(40), default="unknown", nullable=False)
    processing_fee_status: Mapped[str] = mapped_column(String(40), default="processing_fee_unknown", nullable=False)
    lifecycle_status: Mapped[str] = mapped_column(String(40), default="unknown", nullable=False)
    confidence_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)


class CreditCardEmiCharge(Base):
    __tablename__ = "credit_card_emi_charges"
    __table_args__ = (
        UniqueConstraint("emi_plan_id", "transaction_id", "charge_type", name="uq_credit_card_emi_charge_txn_type"),
        Index("ix_credit_card_emi_charges_plan_month", "emi_plan_id", "charge_month"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    emi_plan_id: Mapped[int] = mapped_column(ForeignKey("credit_card_emi_plans.id"), nullable=False)
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"))
    charge_month: Mapped[date] = mapped_column(Date, nullable=False)
    charge_type: Mapped[str] = mapped_column(String(50), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    confidence_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    manual_override: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow)


class RecurringTransaction(TimestampMixin, Base):
    __tablename__ = "recurring_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(100))
    payment_mode: Mapped[str | None] = mapped_column(String(50))
    typical_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    cadence: Mapped[str | None] = mapped_column(String(50))
    last_seen_date: Mapped[date | None] = mapped_column(Date)
    confidence_score: Mapped[float] = mapped_column(default=0.0, nullable=False)


class Benchmark(TimestampMixin, Base):
    __tablename__ = "benchmarks"

    id: Mapped[int] = mapped_column(primary_key=True)
    city: Mapped[str] = mapped_column(String(120), nullable=False)
    profile: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(120), nullable=False)
    min_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    max_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="INR", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class AssistantQuery(Base):
    __tablename__ = "assistant_queries"

    id: Mapped[int] = mapped_column(primary_key=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text)
    date_range_start: Mapped[date | None] = mapped_column(Date)
    date_range_end: Mapped[date | None] = mapped_column(Date)
    confidence_score: Mapped[float | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow)


class AssistantMemory(TimestampMixin, Base):
    __tablename__ = "assistant_memory"
    __table_args__ = (
        UniqueConstraint("memory_type", "key", name="uq_assistant_memory_type_key"),
        Index("ix_assistant_memory_active_type", "active", "memory_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    memory_type: Mapped[str] = mapped_column(String(50), nullable=False)
    key: Mapped[str] = mapped_column(String(160), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str | None] = mapped_column(String(120))
    confidence_score: Mapped[float] = mapped_column(default=1.0, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(120), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(120))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow)
