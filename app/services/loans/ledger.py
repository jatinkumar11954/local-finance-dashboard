from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.entities import Loan, LoanManualOverride, LoanMonthlyLedger, LoanRateEvent, LoanTransaction
from app.services.loans.detection import LOAN_CHARGE_TYPES


TWOPLACES = Decimal("0.01")


def month_start(value: date) -> date:
    return date(value.year, value.month, 1)


def money(value: Decimal | float | int | str | None) -> Decimal:
    if value is None:
        return Decimal("0.00")
    return Decimal(str(value)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class LedgerInput:
    month: date
    opening_outstanding: Decimal | None
    emi_paid: Decimal
    prepayment_paid: Decimal
    explicit_interest: Decimal | None
    explicit_principal: Decimal | None
    charges_paid: Decimal
    explicit_closing: Decimal | None
    provided_annual_rate: Decimal | None
    rate_source: str


def list_loan_ledger(session: Session, loan_id: int) -> list[LoanMonthlyLedger]:
    return session.scalars(
        select(LoanMonthlyLedger)
        .where(LoanMonthlyLedger.loan_id == loan_id)
        .order_by(LoanMonthlyLedger.month.asc())
    ).all()


def recalculate_loan_ledger(session: Session, loan_id: int) -> list[LoanMonthlyLedger]:
    loan = session.get(Loan, loan_id)
    if loan is None:
        raise ValueError(f"Loan {loan_id} was not found.")

    transactions = session.scalars(
        select(LoanTransaction)
        .where(
            LoanTransaction.loan_id == loan_id,
            LoanTransaction.review_status != "ignored",
        )
        .order_by(LoanTransaction.transaction_date.asc(), LoanTransaction.id.asc())
    ).all()
    overrides = {
        override.month: override
        for override in session.scalars(
            select(LoanManualOverride).where(
                LoanManualOverride.loan_id == loan_id,
                LoanManualOverride.is_active.is_(True),
            )
        ).all()
    }
    rate_events = session.scalars(
        select(LoanRateEvent)
        .where(
            (LoanRateEvent.loan_id == loan_id) | (LoanRateEvent.loan_id.is_(None)),
        )
        .order_by(LoanRateEvent.effective_date.asc(), LoanRateEvent.id.asc())
    ).all()
    months = sorted({month_start(item.transaction_date) for item in transactions} | set(overrides.keys()))

    session.execute(delete(LoanMonthlyLedger).where(LoanMonthlyLedger.loan_id == loan_id))
    ledgers: list[LoanMonthlyLedger] = []
    previous_closing: Decimal | None = None

    for ledger_month in months:
        month_transactions = [item for item in transactions if month_start(item.transaction_date) == ledger_month]
        ledger_input = _build_month_input(loan, month_transactions, ledger_month)
        ledger_row, previous_closing = _calculate_month_ledger(
            loan=loan,
            ledger_input=ledger_input,
            previous_closing=previous_closing,
            override=overrides.get(ledger_month),
            rate_event=_latest_rate_event(rate_events, ledger_month),
        )
        session.add(ledger_row)
        ledgers.append(ledger_row)

    session.commit()
    return list_loan_ledger(session, loan_id)


def _build_month_input(
    loan: Loan,
    transactions: list[LoanTransaction],
    ledger_month: date,
) -> LedgerInput:
    opening_values = [item.opening_outstanding for item in transactions if item.opening_outstanding is not None]
    closing_values = [item.closing_outstanding for item in transactions if item.closing_outstanding is not None]
    provided_rates = [item.provided_annual_rate for item in transactions if item.provided_annual_rate is not None]

    emi_paid = sum((item.amount for item in transactions if item.loan_transaction_type == "emi"), start=Decimal("0.00"))
    prepayment_paid = sum((item.amount for item in transactions if item.loan_transaction_type == "prepayment"), start=Decimal("0.00"))
    explicit_interest = _sum_or_none(
        [
            item.interest_component if item.interest_component is not None else item.amount
            for item in transactions
            if item.loan_transaction_type == "interest" or item.interest_component is not None
        ]
    )
    explicit_principal = _sum_or_none(
        [
            item.principal_component if item.principal_component is not None else item.amount
            for item in transactions
            if item.loan_transaction_type == "principal_adjustment" or item.principal_component is not None
        ]
    )
    charges_paid = sum(
        (
            item.charges_component if item.charges_component is not None else item.amount
            for item in transactions
            if item.loan_transaction_type in LOAN_CHARGE_TYPES or item.charges_component is not None
        ),
        start=Decimal("0.00"),
    )

    return LedgerInput(
        month=ledger_month,
        opening_outstanding=opening_values[0] if opening_values else None,
        emi_paid=money(emi_paid),
        prepayment_paid=money(prepayment_paid),
        explicit_interest=money(explicit_interest) if explicit_interest is not None else None,
        explicit_principal=money(explicit_principal) if explicit_principal is not None else None,
        charges_paid=money(charges_paid),
        explicit_closing=closing_values[-1] if closing_values else None,
        provided_annual_rate=provided_rates[-1] if provided_rates else loan.interest_rate_annual,
        rate_source="bank_statement" if provided_rates else ("manual" if loan.interest_rate_annual is not None else "unknown"),
    )


def _sum_or_none(values: list[Decimal | None]) -> Decimal | None:
    clean_values = [value for value in values if value is not None]
    if not clean_values:
        return None
    return sum(clean_values, start=Decimal("0.00"))


def _calculate_month_ledger(
    loan: Loan,
    ledger_input: LedgerInput,
    previous_closing: Decimal | None,
    override: LoanManualOverride | None,
    rate_event: LoanRateEvent | None,
) -> tuple[LoanMonthlyLedger, Decimal | None]:
    notes: list[str] = []
    confidence = Decimal("0.25")

    opening = ledger_input.opening_outstanding
    if opening is None and previous_closing is not None:
        opening = previous_closing
        notes.append("Opening outstanding carried from previous month closing.")
        confidence += Decimal("0.20")
    elif opening is not None:
        notes.append("Opening outstanding read from statement/transaction metadata.")
        confidence += Decimal("0.25")
    elif loan.outstanding_balance is not None:
        opening = loan.outstanding_balance
        notes.append("Opening outstanding initialized from loan profile; review first month.")
        confidence += Decimal("0.10")
    else:
        notes.append("Missing opening outstanding. Enter first month opening outstanding for reliable calculation.")

    interest = ledger_input.explicit_interest
    principal = ledger_input.explicit_principal
    closing = ledger_input.explicit_closing
    provided_rate = ledger_input.provided_annual_rate
    rate_source = ledger_input.rate_source

    if rate_event is not None and provided_rate is None and not (override and override.annual_rate is not None):
        provided_rate = rate_event.rate_percent
        rate_source = "bank_statement" if rate_event.document_id else "manual"

    if override:
        notes.append("Manual override applied before calculated values.")
        opening = override.opening_outstanding if override.opening_outstanding is not None else opening
        closing = override.closing_outstanding if override.closing_outstanding is not None else closing
        interest = override.interest_charged if override.interest_charged is not None else interest
        principal = override.principal_paid if override.principal_paid is not None else principal
        charges_paid = override.charges_paid if override.charges_paid is not None else ledger_input.charges_paid
        provided_rate = override.annual_rate if override.annual_rate is not None else provided_rate
        rate_source = "manual" if override.annual_rate is not None else rate_source
        confidence = max(confidence, Decimal("0.85"))
    else:
        charges_paid = ledger_input.charges_paid

    if interest is not None and opening is not None and principal is not None and closing is not None:
        notes.append("Used direct statement values for opening, interest, principal, and closing.")
        confidence = max(confidence, Decimal("0.92"))
    elif interest is not None and opening is not None and closing is not None and principal is None:
        principal = money(opening - closing - ledger_input.prepayment_paid)
        notes.append("Inferred principal from opening - closing - prepayment.")
        confidence = max(confidence, Decimal("0.82"))
    elif opening is not None and closing is not None and interest is None:
        interest = money(closing - opening + ledger_input.emi_paid + ledger_input.prepayment_paid - charges_paid)
        principal = money(ledger_input.emi_paid - interest - charges_paid) if principal is None else principal
        notes.append("Inferred interest as closing - opening + EMI + prepayment - charges.")
        confidence = max(confidence, Decimal("0.75"))
    elif opening is not None and interest is None and provided_rate is not None:
        monthly_rate = Decimal(str(provided_rate)) / Decimal("1200")
        interest = money(opening * monthly_rate)
        principal = money(ledger_input.emi_paid - interest) if principal is None else principal
        closing = money(opening - principal - ledger_input.prepayment_paid) if closing is None else closing
        notes.append("Calculated monthly interest from opening outstanding and provided annual rate.")
        confidence = max(confidence, Decimal("0.68"))
    elif opening is not None and interest is not None and closing is None:
        principal = money(ledger_input.emi_paid - interest - charges_paid) if principal is None else principal
        closing = money(opening - principal - ledger_input.prepayment_paid)
        notes.append("Calculated closing outstanding from opening, principal, and prepayment.")
        confidence = max(confidence, Decimal("0.72"))
    else:
        notes.append("Insufficient data to calculate interest/principal/outstanding confidently.")

    inferred_monthly_rate = None
    inferred_annual_rate = None
    if interest is not None and opening is not None and opening > 0:
        inferred_monthly_rate = (interest / opening).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
        inferred_annual_rate = (inferred_monthly_rate * Decimal("12") * Decimal("100")).quantize(
            Decimal("0.000001"),
            rounding=ROUND_HALF_UP,
        )
        notes.append("Inferred simple monthly and annual rates from interest / opening outstanding.")
        if rate_source == "unknown":
            rate_source = "inferred"

    ledger = LoanMonthlyLedger(
        loan_id=loan.id,
        month=ledger_input.month,
        opening_outstanding=money(opening) if opening is not None else None,
        emi_paid=ledger_input.emi_paid,
        prepayment_paid=ledger_input.prepayment_paid,
        interest_charged=money(interest) if interest is not None else None,
        principal_paid=money(principal) if principal is not None else None,
        charges_paid=money(charges_paid),
        closing_outstanding=money(closing) if closing is not None else None,
        inferred_monthly_rate=inferred_monthly_rate,
        inferred_annual_rate=inferred_annual_rate,
        provided_annual_rate=provided_rate,
        rate_source=rate_source,
        confidence_score=float(min(confidence, Decimal("0.98"))),
        calculation_notes=" ".join(notes),
    )
    return ledger, ledger.closing_outstanding


def _latest_rate_event(rate_events: list[LoanRateEvent], ledger_month: date) -> LoanRateEvent | None:
    applicable = [event for event in rate_events if event.effective_date <= ledger_month]
    return applicable[-1] if applicable else None
