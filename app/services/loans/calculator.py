from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP


TWOPLACES = Decimal("0.01")


def to_decimal(value: Decimal | float | int | str | None) -> Decimal:
    if value is None:
        return Decimal("0.00")
    return Decimal(str(value))


def quantize_money(value: Decimal) -> Decimal:
    return value.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def add_months(source_date: date, months: int) -> date:
    month_index = source_date.month - 1 + months
    year = source_date.year + month_index // 12
    month = month_index % 12 + 1
    day = min(source_date.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def months_between(start_date: date, end_date: date) -> int:
    months = (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month)
    if end_date.day < start_date.day:
        months -= 1
    return max(months, 0)


@dataclass(frozen=True)
class LoanPrepayment:
    payment_date: date
    amount: Decimal


@dataclass(frozen=True)
class AmortizationRow:
    installment_number: int
    due_date: date
    opening_balance: Decimal
    emi_amount: Decimal
    interest_component: Decimal
    principal_component: Decimal
    extra_principal: Decimal
    total_payment: Decimal
    closing_balance: Decimal


@dataclass(frozen=True)
class LoanAnalysis:
    opening_balance: Decimal
    remaining_tenure_months: int
    scheduled_emi: Decimal
    outstanding_balance: Decimal
    total_interest: Decimal
    total_principal: Decimal
    projected_interest: Decimal
    projected_principal: Decimal
    interest_saved: Decimal
    baseline_closure_date: date
    projected_closure_date: date
    months_saved: int
    recurring_extra_payment: Decimal
    one_time_prepayment_total: Decimal
    baseline_schedule: list[AmortizationRow]
    projected_schedule: list[AmortizationRow]


def calculate_emi(principal: Decimal | float | int | str, annual_interest_rate: Decimal | float | int | str, tenure_months: int) -> Decimal:
    principal_amount = to_decimal(principal)
    annual_rate = to_decimal(annual_interest_rate)
    if tenure_months <= 0:
        raise ValueError("Tenure months must be greater than zero.")
    if principal_amount <= 0:
        raise ValueError("Principal must be greater than zero.")

    if annual_rate <= 0:
        return quantize_money(principal_amount / Decimal(tenure_months))

    monthly_rate = annual_rate / Decimal("1200")
    factor = (Decimal("1.00") + monthly_rate) ** tenure_months
    emi = principal_amount * monthly_rate * factor / (factor - Decimal("1.00"))
    return quantize_money(emi)


def generate_amortization_schedule(
    principal: Decimal | float | int | str,
    annual_interest_rate: Decimal | float | int | str,
    start_date: date,
    tenure_months: int,
    emi_amount: Decimal | float | int | str | None = None,
    recurring_extra_payment: Decimal | float | int | str = 0,
    one_time_prepayments: list[LoanPrepayment] | None = None,
) -> list[AmortizationRow]:
    balance = quantize_money(to_decimal(principal))
    annual_rate = to_decimal(annual_interest_rate)
    recurring_extra = quantize_money(to_decimal(recurring_extra_payment))
    scheduled_emi = quantize_money(to_decimal(emi_amount)) if emi_amount is not None else calculate_emi(balance, annual_rate, tenure_months)
    prepayment_lookup: dict[tuple[int, int], Decimal] = {}
    for prepayment in one_time_prepayments or []:
        prepayment_amount = quantize_money(to_decimal(prepayment.amount))
        if prepayment_amount <= 0:
            continue
        key = (prepayment.payment_date.year, prepayment.payment_date.month)
        prepayment_lookup[key] = prepayment_lookup.get(key, Decimal("0.00")) + prepayment_amount

    if scheduled_emi <= 0:
        raise ValueError("EMI amount must be greater than zero.")

    monthly_rate = annual_rate / Decimal("1200")
    schedule: list[AmortizationRow] = []
    installment_number = 1
    due_date = start_date
    safety_limit = tenure_months + 600

    while balance > 0 and installment_number <= safety_limit:
        opening_balance = balance
        interest_component = quantize_money(opening_balance * monthly_rate) if monthly_rate > 0 else Decimal("0.00")
        if scheduled_emi <= interest_component and opening_balance > 0:
            raise ValueError("EMI is too low to cover monthly interest. Increase EMI or reduce outstanding balance.")

        emi_for_period = scheduled_emi
        principal_component = quantize_money(emi_for_period - interest_component)
        extra_principal = recurring_extra + prepayment_lookup.get((due_date.year, due_date.month), Decimal("0.00"))

        if principal_component > opening_balance:
            principal_component = opening_balance
            emi_for_period = quantize_money(interest_component + principal_component)

        if installment_number == tenure_months and principal_component + extra_principal < opening_balance:
            principal_component = quantize_money(opening_balance - extra_principal)
            emi_for_period = quantize_money(interest_component + principal_component)

        if principal_component + extra_principal > opening_balance:
            extra_principal = max(Decimal("0.00"), quantize_money(opening_balance - principal_component))

        total_payment = quantize_money(emi_for_period + extra_principal)
        closing_balance = quantize_money(opening_balance - principal_component - extra_principal)
        if closing_balance < 0:
            closing_balance = Decimal("0.00")

        schedule.append(
            AmortizationRow(
                installment_number=installment_number,
                due_date=due_date,
                opening_balance=opening_balance,
                emi_amount=emi_for_period,
                interest_component=interest_component,
                principal_component=principal_component,
                extra_principal=extra_principal,
                total_payment=total_payment,
                closing_balance=closing_balance,
            )
        )

        balance = closing_balance
        installment_number += 1
        due_date = add_months(start_date, installment_number - 1)

    return schedule


def summarize_schedule(schedule: list[AmortizationRow]) -> tuple[Decimal, Decimal, date]:
    if not schedule:
        raise ValueError("Schedule cannot be empty.")
    total_interest = quantize_money(sum((row.interest_component for row in schedule), start=Decimal("0.00")))
    total_principal = quantize_money(
        sum((row.principal_component + row.extra_principal for row in schedule), start=Decimal("0.00"))
    )
    closure_date = schedule[-1].due_date
    return total_interest, total_principal, closure_date


def analyze_home_loan(
    principal: Decimal | float | int | str,
    annual_interest_rate: Decimal | float | int | str,
    start_date: date,
    tenure_months: int,
    emi_amount: Decimal | float | int | str | None = None,
    current_outstanding_balance: Decimal | float | int | str | None = None,
    recurring_extra_payment: Decimal | float | int | str = 0,
    one_time_prepayments: list[LoanPrepayment] | None = None,
    as_of_date: date | None = None,
) -> LoanAnalysis:
    original_principal = quantize_money(to_decimal(principal))
    outstanding_balance = quantize_money(to_decimal(current_outstanding_balance)) if current_outstanding_balance else original_principal
    scenario_date = as_of_date or start_date
    elapsed_months = months_between(start_date, scenario_date) if current_outstanding_balance else 0
    remaining_tenure_months = max(1, tenure_months - elapsed_months)
    schedule_start_date = add_months(start_date, elapsed_months) if current_outstanding_balance else start_date

    scheduled_emi = quantize_money(to_decimal(emi_amount)) if emi_amount is not None else calculate_emi(original_principal, annual_interest_rate, tenure_months)
    baseline_schedule = generate_amortization_schedule(
        principal=outstanding_balance,
        annual_interest_rate=annual_interest_rate,
        start_date=schedule_start_date,
        tenure_months=remaining_tenure_months,
        emi_amount=scheduled_emi,
    )
    projected_schedule = generate_amortization_schedule(
        principal=outstanding_balance,
        annual_interest_rate=annual_interest_rate,
        start_date=schedule_start_date,
        tenure_months=remaining_tenure_months,
        emi_amount=scheduled_emi,
        recurring_extra_payment=recurring_extra_payment,
        one_time_prepayments=one_time_prepayments,
    )

    baseline_interest, baseline_principal, baseline_closure_date = summarize_schedule(baseline_schedule)
    projected_interest, projected_principal, projected_closure_date = summarize_schedule(projected_schedule)
    interest_saved = quantize_money(baseline_interest - projected_interest)
    months_saved = max(0, len(baseline_schedule) - len(projected_schedule))
    total_one_time_prepayment = quantize_money(
        sum((prepayment.amount for prepayment in (one_time_prepayments or [])), start=Decimal("0.00"))
    )

    return LoanAnalysis(
        opening_balance=outstanding_balance,
        remaining_tenure_months=remaining_tenure_months,
        scheduled_emi=scheduled_emi,
        outstanding_balance=outstanding_balance,
        total_interest=baseline_interest,
        total_principal=baseline_principal,
        projected_interest=projected_interest,
        projected_principal=projected_principal,
        interest_saved=interest_saved,
        baseline_closure_date=baseline_closure_date,
        projected_closure_date=projected_closure_date,
        months_saved=months_saved,
        recurring_extra_payment=quantize_money(to_decimal(recurring_extra_payment)),
        one_time_prepayment_total=total_one_time_prepayment,
        baseline_schedule=baseline_schedule,
        projected_schedule=projected_schedule,
    )
