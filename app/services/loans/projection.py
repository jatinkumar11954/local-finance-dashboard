from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from app.models.entities import Loan, LoanMonthlyLedger
from app.services.loans.calculator import add_months, generate_amortization_schedule
from app.services.loans.ledger import month_start, money


TWOPLACES = Decimal("0.01")


@dataclass(frozen=True)
class LoanActualProjectedRow:
    month: date
    projected_interest: Decimal | None
    actual_interest: Decimal | None
    interest_difference: Decimal | None
    projected_principal: Decimal | None
    actual_principal: Decimal | None
    principal_difference: Decimal | None
    projected_closing: Decimal | None
    actual_closing: Decimal | None
    prepayment_impact: Decimal | None


@dataclass(frozen=True)
class LoanProjectionSummary:
    estimated_remaining_tenure_months: int | None
    estimated_total_future_interest: Decimal | None
    estimated_closure_date: date | None
    estimated_interest_saved_by_prepayment: Decimal
    estimated_tenure_reduced_months: int


@dataclass(frozen=True)
class LoanProjectionResult:
    summary: LoanProjectionSummary
    actual_vs_projected: list[LoanActualProjectedRow]


def build_loan_projection(
    loan: Loan,
    ledger_rows: list[LoanMonthlyLedger],
    future_monthly_extra_prepayment: Decimal | float | int | str = Decimal("0.00"),
) -> LoanProjectionResult:
    base_rate = loan.interest_rate_annual
    actual_vs_projected = build_actual_vs_projected_rows(ledger_rows, base_rate)
    summary = build_projection_summary(
        loan=loan,
        ledger_rows=ledger_rows,
        future_monthly_extra_prepayment=money(future_monthly_extra_prepayment),
    )
    return LoanProjectionResult(summary=summary, actual_vs_projected=actual_vs_projected)


def build_actual_vs_projected_rows(
    ledger_rows: list[LoanMonthlyLedger],
    base_annual_rate: Decimal | None,
) -> list[LoanActualProjectedRow]:
    rows: list[LoanActualProjectedRow] = []
    for ledger in ledger_rows:
        projected_interest = None
        projected_principal = None
        projected_closing = None
        if ledger.opening_outstanding is not None and base_annual_rate is not None:
            projected_interest = money(ledger.opening_outstanding * Decimal(str(base_annual_rate)) / Decimal("1200"))
            projected_principal = money(ledger.emi_paid - projected_interest - ledger.charges_paid)
            projected_closing = money(ledger.opening_outstanding - projected_principal)

        actual_principal = ledger.total_principal_reduced
        if actual_principal is None and ledger.principal_from_emi is not None:
            actual_principal = money(ledger.principal_from_emi + ledger.principal_from_prepayment)

        interest_difference = (
            money(ledger.interest_charged - projected_interest)
            if ledger.interest_charged is not None and projected_interest is not None
            else None
        )
        principal_difference = (
            money(actual_principal - projected_principal)
            if actual_principal is not None and projected_principal is not None
            else None
        )
        prepayment_impact = (
            money(projected_closing - ledger.closing_outstanding)
            if projected_closing is not None and ledger.closing_outstanding is not None
            else ledger.principal_from_prepayment
        )

        rows.append(
            LoanActualProjectedRow(
                month=ledger.month,
                projected_interest=projected_interest,
                actual_interest=ledger.interest_charged,
                interest_difference=interest_difference,
                projected_principal=projected_principal,
                actual_principal=actual_principal,
                principal_difference=principal_difference,
                projected_closing=projected_closing,
                actual_closing=ledger.closing_outstanding,
                prepayment_impact=prepayment_impact,
            )
        )
    return rows


def build_projection_summary(
    loan: Loan,
    ledger_rows: list[LoanMonthlyLedger],
    future_monthly_extra_prepayment: Decimal = Decimal("0.00"),
) -> LoanProjectionSummary:
    if loan.interest_rate_annual is None or loan.emi_amount is None:
        return LoanProjectionSummary(
            estimated_remaining_tenure_months=None,
            estimated_total_future_interest=None,
            estimated_closure_date=None,
            estimated_interest_saved_by_prepayment=Decimal("0.00"),
            estimated_tenure_reduced_months=0,
        )

    latest_closing = next((row.closing_outstanding for row in reversed(ledger_rows) if row.closing_outstanding is not None), None)
    opening = latest_closing or loan.outstanding_balance or loan.principal
    if opening is None or opening <= 0:
        return LoanProjectionSummary(
            estimated_remaining_tenure_months=0,
            estimated_total_future_interest=Decimal("0.00"),
            estimated_closure_date=None,
            estimated_interest_saved_by_prepayment=Decimal("0.00"),
            estimated_tenure_reduced_months=0,
        )

    start_month = _projection_start_month(loan, ledger_rows)
    remaining_tenure = _remaining_tenure_guess(loan, start_month)
    try:
        projected_schedule = generate_amortization_schedule(
            principal=opening,
            annual_interest_rate=loan.interest_rate_annual,
            start_date=start_month,
            tenure_months=remaining_tenure,
            emi_amount=loan.emi_amount,
            recurring_extra_payment=future_monthly_extra_prepayment,
        )
    except ValueError:
        return LoanProjectionSummary(
            estimated_remaining_tenure_months=None,
            estimated_total_future_interest=None,
            estimated_closure_date=None,
            estimated_interest_saved_by_prepayment=Decimal("0.00"),
            estimated_tenure_reduced_months=0,
        )

    total_future_interest = money(sum((row.interest_component for row in projected_schedule), start=Decimal("0.00")))
    total_uploaded_prepayment = money(sum((row.principal_from_prepayment for row in ledger_rows), start=Decimal("0.00")))
    interest_saved = Decimal("0.00")
    tenure_reduced = 0
    if total_uploaded_prepayment > 0:
        try:
            counterfactual_schedule = generate_amortization_schedule(
                principal=opening + total_uploaded_prepayment,
                annual_interest_rate=loan.interest_rate_annual,
                start_date=start_month,
                tenure_months=remaining_tenure,
                emi_amount=loan.emi_amount,
                recurring_extra_payment=future_monthly_extra_prepayment,
            )
            counterfactual_interest = money(sum((row.interest_component for row in counterfactual_schedule), start=Decimal("0.00")))
            interest_saved = max(Decimal("0.00"), money(counterfactual_interest - total_future_interest))
            tenure_reduced = max(0, len(counterfactual_schedule) - len(projected_schedule))
        except ValueError:
            interest_saved = Decimal("0.00")
            tenure_reduced = 0

    return LoanProjectionSummary(
        estimated_remaining_tenure_months=len(projected_schedule),
        estimated_total_future_interest=total_future_interest,
        estimated_closure_date=projected_schedule[-1].due_date if projected_schedule else None,
        estimated_interest_saved_by_prepayment=interest_saved.quantize(TWOPLACES, rounding=ROUND_HALF_UP),
        estimated_tenure_reduced_months=tenure_reduced,
    )


def _projection_start_month(loan: Loan, ledger_rows: list[LoanMonthlyLedger]) -> date:
    if ledger_rows:
        return add_months(ledger_rows[-1].month, 1)
    if loan.start_date:
        return month_start(loan.start_date)
    return month_start(date.today())


def _remaining_tenure_guess(loan: Loan, start_month: date) -> int:
    if loan.start_date and loan.tenure_months:
        elapsed = max(0, (start_month.year - loan.start_date.year) * 12 + (start_month.month - loan.start_date.month))
        return max(1, int(loan.tenure_months) - elapsed)
    return 360
