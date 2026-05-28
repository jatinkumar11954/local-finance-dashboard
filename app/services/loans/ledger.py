from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.entities import Loan, LoanManualOverride, LoanMonthlyLedger, LoanRateEvent, LoanTransaction
from app.services.loans.calculator import generate_amortization_schedule
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
    emi_count: int
    prepayment_count: int
    minimum_confidence: float | None
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
    emi_rows = [item for item in transactions if item.loan_transaction_type == "emi"]
    prepayment_rows = [item for item in transactions if item.loan_transaction_type == "prepayment"]
    confidences = [Decimal(str(item.confidence_score)) for item in transactions if item.confidence_score is not None]
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
            if item.loan_transaction_type == "principal_adjustment"
            or (item.loan_transaction_type == "emi" and item.principal_component is not None)
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
        emi_count=len(emi_rows),
        prepayment_count=len(prepayment_rows),
        minimum_confidence=float(min(confidences)) if confidences else None,
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
    review_flags: list[str] = []
    confidence = Decimal("0.25")

    opening = ledger_input.opening_outstanding
    if opening is None and previous_closing is not None:
        opening = previous_closing
        notes.append("Opening outstanding carried from previous month closing.")
        confidence += Decimal("0.20")
    elif opening is not None:
        notes.append("Opening outstanding read from statement/transaction metadata.")
        confidence += Decimal("0.25")
    else:
        profile_opening = _scheduled_opening_from_profile(loan, ledger_input.month)
        if profile_opening is not None:
            opening = profile_opening
            notes.append("Opening outstanding estimated from loan profile schedule for the first imported month.")
            confidence += Decimal("0.18")

    if opening is None and loan.outstanding_balance is not None:
        opening = loan.outstanding_balance
        notes.append("Opening outstanding initialized from loan profile; review first month.")
        confidence += Decimal("0.10")
    elif opening is None:
        notes.append("Missing opening outstanding. Enter first month opening outstanding for reliable calculation.")
        review_flags.append("missing_opening")

    interest = ledger_input.explicit_interest
    principal_from_emi = ledger_input.explicit_principal
    closing = ledger_input.explicit_closing
    provided_rate = ledger_input.provided_annual_rate
    rate_source = ledger_input.rate_source
    base_annual_rate = loan.interest_rate_annual
    calculation_method = "unknown"
    manual_override_used = override is not None
    prepayment_principal = money(ledger_input.prepayment_paid)

    if rate_event is not None and provided_rate is None and not (override and override.annual_rate is not None):
        provided_rate = rate_event.rate_percent
        rate_source = "bank_statement" if rate_event.document_id else "manual"

    if override:
        notes.append("Manual override applied before calculated values.")
        opening = override.opening_outstanding if override.opening_outstanding is not None else opening
        closing = override.closing_outstanding if override.closing_outstanding is not None else closing
        interest = override.interest_charged if override.interest_charged is not None else interest
        principal_from_emi = override.principal_paid if override.principal_paid is not None else principal_from_emi
        emi_paid = money(override.emi_paid) if override.emi_paid is not None else ledger_input.emi_paid
        prepayment_paid = money(override.prepayment_paid) if override.prepayment_paid is not None else ledger_input.prepayment_paid
        prepayment_principal = prepayment_paid
        charges_paid = override.charges_paid if override.charges_paid is not None else ledger_input.charges_paid
        provided_rate = override.annual_rate if override.annual_rate is not None else provided_rate
        rate_source = "manual" if override.annual_rate is not None else rate_source
        confidence = max(confidence, Decimal("0.85"))
    else:
        emi_paid = ledger_input.emi_paid
        prepayment_paid = ledger_input.prepayment_paid
        charges_paid = ledger_input.charges_paid

    if ledger_input.minimum_confidence is not None and ledger_input.minimum_confidence < 0.7:
        review_flags.append("low_transaction_confidence")
        confidence = min(confidence, Decimal("0.60"))
    if ledger_input.emi_count == 0 and emi_paid == 0:
        review_flags.append("emi_not_found")
    if ledger_input.emi_count > 1:
        review_flags.append("duplicate_emi")

    if interest is not None and opening is not None:
        if principal_from_emi is None:
            principal_from_emi = money(emi_paid - interest - charges_paid)
        if closing is None:
            closing = money(opening - principal_from_emi - prepayment_paid)
        notes.append("Used explicit statement/manual interest and opening outstanding.")
        calculation_method = "explicit_interest"
        confidence = max(confidence, Decimal("0.92"))
    elif opening is not None and closing is not None and interest is None:
        # Include prepayment only to reconcile balance movement, then split it back out of EMI principal.
        interest = money(closing - opening + emi_paid + prepayment_paid - charges_paid)
        total_reduction = money(opening - closing)
        principal_from_emi = money(total_reduction - prepayment_paid) if principal_from_emi is None else principal_from_emi
        notes.append("Inferred interest as closing - opening + EMI + prepayment - charges.")
        notes.append("MBK/prepayment is excluded from EMI principal and tracked as separate principal reduction.")
        calculation_method = "actual_from_opening_closing"
        confidence = max(confidence, Decimal("0.75"))
    elif opening is not None and interest is None and (provided_rate is not None or base_annual_rate is not None):
        rate_for_estimate = provided_rate if provided_rate is not None else base_annual_rate
        monthly_rate = Decimal(str(rate_for_estimate)) / Decimal("1200")
        interest = money(opening * monthly_rate)
        principal_from_emi = money(emi_paid - interest - charges_paid) if principal_from_emi is None else principal_from_emi
        closing = money(opening - principal_from_emi - prepayment_paid) if closing is None else closing
        notes.append("Estimated monthly interest from opening outstanding and base/provided annual rate.")
        calculation_method = "estimated_using_base_rate"
        confidence = max(confidence, Decimal("0.68"))
    else:
        notes.append("Insufficient data to calculate interest/principal/outstanding confidently.")
        calculation_method = "needs_review"
        review_flags.append("insufficient_data")

    total_principal_reduced = None
    if opening is not None and closing is not None:
        total_principal_reduced = money(opening - closing)
    elif principal_from_emi is not None:
        total_principal_reduced = money(principal_from_emi + prepayment_principal)

    if principal_from_emi is not None and principal_from_emi < 0:
        review_flags.append("negative_principal_from_emi")
        notes.append("Principal from EMI is negative; review opening/closing/interest inputs.")
        confidence = min(confidence, Decimal("0.45"))
    if interest is not None and interest < 0:
        review_flags.append("negative_interest")
        confidence = min(confidence, Decimal("0.45"))

    inferred_monthly_rate = None
    inferred_annual_rate = None
    if (
        interest is not None
        and opening is not None
        and opening > 0
        and calculation_method != "estimated_using_base_rate"
    ):
        inferred_monthly_rate = (interest / opening).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
        inferred_annual_rate = (inferred_monthly_rate * Decimal("12") * Decimal("100")).quantize(
            Decimal("0.000001"),
            rounding=ROUND_HALF_UP,
        )
        notes.append("Inferred simple monthly and annual rates from interest / opening outstanding.")
        if rate_source == "unknown":
            rate_source = "inferred"
        if inferred_annual_rate < 0 or inferred_annual_rate > Decimal("30"):
            review_flags.append("abnormal_inferred_rate")
            notes.append("Inferred annual rate is outside normal review bounds.")
            confidence = min(confidence, Decimal("0.55"))

    rate_variance = None
    rate_variance_percent = None
    if inferred_annual_rate is not None and base_annual_rate is not None:
        rate_variance = (inferred_annual_rate - Decimal(str(base_annual_rate))).quantize(
            Decimal("0.000001"),
            rounding=ROUND_HALF_UP,
        )
        rate_variance_percent = rate_variance
        tolerance = Decimal("0.05")
        if rate_variance > tolerance:
            notes.append("Inferred rate is higher than base estimate.")
        elif rate_variance < -tolerance:
            notes.append("Inferred rate is lower than base estimate.")
        else:
            notes.append("Inferred rate is near the base estimate.")

    ledger = LoanMonthlyLedger(
        loan_id=loan.id,
        month=ledger_input.month,
        opening_outstanding=money(opening) if opening is not None else None,
        emi_paid=emi_paid,
        prepayment_paid=prepayment_paid,
        interest_charged=money(interest) if interest is not None else None,
        principal_paid=money(principal_from_emi) if principal_from_emi is not None else None,
        principal_from_emi=money(principal_from_emi) if principal_from_emi is not None else None,
        principal_from_prepayment=money(prepayment_principal),
        total_principal_reduced=money(total_principal_reduced) if total_principal_reduced is not None else None,
        charges_paid=money(charges_paid),
        closing_outstanding=money(closing) if closing is not None else None,
        inferred_monthly_rate=inferred_monthly_rate,
        inferred_annual_rate=inferred_annual_rate,
        base_annual_rate=base_annual_rate,
        rate_variance=rate_variance,
        rate_variance_percent=rate_variance_percent,
        provided_annual_rate=provided_rate,
        rate_source=rate_source,
        calculation_method=calculation_method,
        confidence_score=float(min(confidence, Decimal("0.98"))),
        manual_override_used=manual_override_used,
        review_status="needs_review" if review_flags else "ok",
        calculation_notes=" ".join(notes + ([f"Review flags: {', '.join(sorted(set(review_flags)))}."] if review_flags else [])),
    )
    return ledger, ledger.closing_outstanding


def _latest_rate_event(rate_events: list[LoanRateEvent], ledger_month: date) -> LoanRateEvent | None:
    applicable = [event for event in rate_events if event.effective_date <= ledger_month]
    return applicable[-1] if applicable else None


def _scheduled_opening_from_profile(loan: Loan, ledger_month: date) -> Decimal | None:
    if (
        loan.principal is None
        or loan.interest_rate_annual is None
        or loan.start_date is None
        or loan.tenure_months is None
        or loan.emi_amount is None
    ):
        return None
    if ledger_month < month_start(loan.start_date):
        return None

    try:
        schedule = generate_amortization_schedule(
            principal=loan.principal,
            annual_interest_rate=loan.interest_rate_annual,
            start_date=loan.start_date,
            tenure_months=loan.tenure_months,
            emi_amount=loan.emi_amount,
        )
    except ValueError:
        return None

    for row in schedule:
        if month_start(row.due_date) == ledger_month:
            return row.opening_balance
    return None
