from __future__ import annotations

from datetime import date
from pathlib import Path
import sys

import pandas as pd
import streamlit as st

DASHBOARD_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = DASHBOARD_DIR.parent
for path in (PROJECT_ROOT, DASHBOARD_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.services.loans import (
    DEFAULT_BASE_ANNUAL_RATE,
    LoanPrepayment,
    analyze_home_loan,
    build_loan_projection,
    list_loan_ledger,
    list_loan_import_summaries,
    list_loan_transactions,
    list_loans,
    recalculate_loan_ledger,
    relink_loan_transactions,
    revert_loan_transaction_to_source,
    save_loan,
    save_loan_manual_override,
    save_loan_rate_event,
    update_loan_transaction,
)
from common import format_inr, initialize_page, render_sidebar_status, session_scope


LOAN_TRANSACTION_TYPES = [
    "emi",
    "prepayment",
    "interest",
    "principal_adjustment",
    "processing_fee",
    "insurance",
    "penal_interest",
    "bounce_charge",
    "charge",
    "unknown",
]
REVIEW_STATUSES = ["pending", "confirmed", "ignored"]


def parse_optional_float(value: str) -> float | None:
    stripped = value.strip()
    if not stripped:
        return None
    return float(stripped.replace(",", ""))


def parse_editor_float(value) -> float | None:
    if is_blank_editor_value(value):
        return None
    return float(str(value).replace(",", ""))


def parse_editor_date(value) -> date | None:
    if is_blank_editor_value(value):
        return None
    if hasattr(value, "date") and not isinstance(value, date):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def is_blank_editor_value(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def editor_values_differ(left, right) -> bool:
    left_value = normalize_editor_value(left)
    right_value = normalize_editor_value(right)
    if isinstance(left_value, float) and isinstance(right_value, float):
        return abs(left_value - right_value) > 0.000001
    return left_value != right_value


def normalize_editor_value(value):
    if is_blank_editor_value(value):
        return None
    if hasattr(value, "date") and not isinstance(value, date):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, int | float):
        return float(value)
    return str(value)


initialize_page("Loans")
render_sidebar_status()

st.title("Home Loan Analysis")
st.caption("Model EMI schedules, outstanding balance, and prepayment impact locally.")

with session_scope() as session:
    saved_loans = list_loans(session)
    import_summaries = list_loan_import_summaries(session)


def loan_option_label(loan) -> str:
    summary = import_summaries.get(loan.id)
    tx_count = summary.transaction_count if summary else 0
    ledger_count = summary.ledger_month_count if summary else 0
    return f"{loan.id} | {loan.name} | {tx_count} tx | {ledger_count} ledger months"


loan_lookup = {loan_option_label(loan): loan for loan in saved_loans}
loan_options = ["Create new loan"] + sorted(loan_lookup.keys(), key=str.lower)
if st.session_state.get("selected_loan_profile") not in loan_options:
    st.session_state["selected_loan_profile"] = "Create new loan"


def reset_loan_selection() -> None:
    st.session_state["selected_loan_profile"] = "Create new loan"


selected_loan_key = st.selectbox("Saved loan profile", loan_options, key="selected_loan_profile")
selected_loan = loan_lookup.get(selected_loan_key)
loan_widget_suffix = selected_loan.id if selected_loan else "new"

form_columns = st.columns(2)
with form_columns[0]:
    loan_name = st.text_input(
        "Loan name",
        value=selected_loan.name if selected_loan else "Home Loan",
        key=f"loan_name_{loan_widget_suffix}",
    )
    lender_name = st.text_input(
        "Lender",
        value=selected_loan.lender_name or "" if selected_loan else "",
        key=f"lender_name_{loan_widget_suffix}",
    )
    bank_name = st.text_input(
        "Bank name",
        value=selected_loan.bank_name or "" if selected_loan else "",
        key=f"bank_name_{loan_widget_suffix}",
    )
    masked_loan_account_number = st.text_input(
        "Loan account masked number",
        value=selected_loan.masked_loan_account_number or "" if selected_loan else "",
        key=f"loan_account_{loan_widget_suffix}",
        placeholder="****1234",
    )
    principal = st.number_input(
        "Original principal",
        min_value=0.0,
        value=float(selected_loan.principal) if selected_loan and selected_loan.principal is not None else 5_000_000.0,
        step=10000.0,
        key=f"principal_{loan_widget_suffix}",
    )
    interest_rate = st.number_input(
        "Base annual interest rate (%)",
        min_value=0.0,
        value=float(selected_loan.interest_rate_annual)
        if selected_loan and selected_loan.interest_rate_annual is not None
        else DEFAULT_BASE_ANNUAL_RATE,
        step=0.05,
        key=f"interest_rate_{loan_widget_suffix}",
    )
    rate_type = st.selectbox(
        "Rate type",
        ["unknown", "floating", "fixed"],
        index=["unknown", "floating", "fixed"].index(selected_loan.rate_type)
        if selected_loan and selected_loan.rate_type in {"unknown", "floating", "fixed"}
        else 0,
        key=f"rate_type_{loan_widget_suffix}",
    )
with form_columns[1]:
    loan_start_date = st.date_input(
        "Loan start date",
        value=selected_loan.start_date if selected_loan and selected_loan.start_date else date(2024, 1, 1),
        key=f"loan_start_date_{loan_widget_suffix}",
    )
    tenure_months = st.number_input(
        "Tenure (months)",
        min_value=1,
        value=selected_loan.tenure_months if selected_loan and selected_loan.tenure_months else 240,
        step=1,
        key=f"tenure_months_{loan_widget_suffix}",
    )
    emi_amount = st.number_input(
        "EMI amount",
        min_value=0.0,
        value=float(selected_loan.emi_amount) if selected_loan and selected_loan.emi_amount is not None else 43391.0,
        step=100.0,
        key=f"emi_amount_{loan_widget_suffix}",
    )
    outstanding_balance = st.number_input(
        "Current outstanding balance",
        min_value=0.0,
        value=float(selected_loan.outstanding_balance) if selected_loan and selected_loan.outstanding_balance is not None else principal,
        step=10000.0,
        key=f"outstanding_balance_{loan_widget_suffix}",
    )
    st.caption("Optional summary totals from bank/app records. Leave blank as 0 if unknown.")
    summary_total_paid = st.number_input(
        "Total amount paid till date",
        min_value=0.0,
        value=float(selected_loan.summary_total_paid) if selected_loan and selected_loan.summary_total_paid is not None else 0.0,
        step=1000.0,
        key=f"summary_total_paid_{loan_widget_suffix}",
    )
    summary_interest_paid = st.number_input(
        "Total interest paid till date",
        min_value=0.0,
        value=float(selected_loan.summary_interest_paid) if selected_loan and selected_loan.summary_interest_paid is not None else 0.0,
        step=1000.0,
        key=f"summary_interest_paid_{loan_widget_suffix}",
    )
    summary_principal_paid = st.number_input(
        "Total principal paid till date",
        min_value=0.0,
        value=float(selected_loan.summary_principal_paid) if selected_loan and selected_loan.summary_principal_paid is not None else 0.0,
        step=1000.0,
        key=f"summary_principal_paid_{loan_widget_suffix}",
    )
    summary_prepayment_paid = st.number_input(
        "Total prepayment paid till date",
        min_value=0.0,
        value=float(selected_loan.summary_prepayment_paid) if selected_loan and selected_loan.summary_prepayment_paid is not None else 0.0,
        step=1000.0,
        key=f"summary_prepayment_paid_{loan_widget_suffix}",
    )

notes = st.text_area(
    "Notes",
    value=selected_loan.notes or "" if selected_loan else "",
    key=f"loan_notes_{loan_widget_suffix}",
)
save_columns = st.columns(2)
if save_columns[0].button("Save loan profile", use_container_width=True, type="primary"):
    with session_scope() as session:
        saved = save_loan(
            session=session,
            loan_id=selected_loan.id if selected_loan else None,
            name=loan_name,
            lender_name=lender_name or None,
            bank_name=bank_name or None,
            masked_loan_account_number=masked_loan_account_number or None,
            rate_type=rate_type,
            principal=principal,
            interest_rate_annual=interest_rate,
            start_date=loan_start_date,
            tenure_months=int(tenure_months),
            emi_amount=emi_amount,
            outstanding_balance=outstanding_balance or None,
            summary_total_paid=summary_total_paid or None,
            summary_interest_paid=summary_interest_paid or None,
            summary_principal_paid=summary_principal_paid or None,
            summary_prepayment_paid=summary_prepayment_paid or None,
            notes=notes or None,
        )
    st.success(f"Loan profile saved: {saved.name}")
    st.rerun()

save_columns[1].button("Reset form to new loan", use_container_width=True, on_click=reset_loan_selection)

st.subheader("Imported statement values")
summary_rows = []
loan_name_by_id = {loan.id: loan.name for loan in saved_loans}
for loan_id, summary in sorted(import_summaries.items(), key=lambda item: (item[0] is None, item[0] or 0)):
    summary_rows.append(
        {
            "loan": "Unlinked" if loan_id is None else f"{loan_id} | {loan_name_by_id.get(loan_id, 'Unknown loan')}",
            "transactions": summary.transaction_count,
            "ledger_months": summary.ledger_month_count,
            "first_month": summary.first_month,
            "latest_month": summary.latest_month,
            "total_emi_paid": float(summary.total_emi_paid),
            "mbk_prepayment_paid": float(summary.total_prepayment_paid),
            "interest_charged": float(summary.total_interest_charged),
            "latest_closing_outstanding": float(summary.latest_closing_outstanding)
            if summary.latest_closing_outstanding is not None
            else None,
        }
    )
summary_rows = sorted(summary_rows, key=lambda row: str(row["loan"]).lower())
if summary_rows:
    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)
else:
    st.caption("No imported loan transactions have been detected yet.")

if selected_loan:
    selected_summary = import_summaries.get(selected_loan.id)
    imported_metric_columns = st.columns(5)
    imported_metric_columns[0].metric(
        "Imported current outstanding",
        format_inr(
            selected_summary.latest_closing_outstanding
            if selected_summary and selected_summary.latest_closing_outstanding is not None
            else selected_loan.outstanding_balance
            or 0
        ),
    )
    imported_metric_columns[1].metric("Imported EMI paid", format_inr(selected_summary.total_emi_paid if selected_summary else 0))
    imported_metric_columns[2].metric("MBK / prepayment", format_inr(selected_summary.total_prepayment_paid if selected_summary else 0))
    imported_metric_columns[3].metric("Imported interest", format_inr(selected_summary.total_interest_charged if selected_summary else 0))
    imported_metric_columns[4].metric("Ledger months", str(selected_summary.ledger_month_count if selected_summary else 0))

    relink_options = {
        (
            "Unlinked"
            if source_loan_id is None
            else f"{source_loan_id} | {loan_name_by_id.get(source_loan_id, 'Unknown loan')}"
        ): source_loan_id
        for source_loan_id, summary in import_summaries.items()
        if summary.transaction_count > 0 and source_loan_id != selected_loan.id
    }
    if relink_options:
        with st.expander("Move imported transactions to the selected loan", expanded=False):
            st.caption(
                "Use this when uploaded loan statements were auto-linked to a placeholder profile, "
                "but your real profile is selected above."
            )
            relink_label = st.selectbox("Source loan transaction group", list(relink_options.keys()))
            if st.button("Move and recalculate selected loan ledger", use_container_width=True):
                with session_scope() as session:
                    moved_count = relink_loan_transactions(
                        session=session,
                        target_loan_id=selected_loan.id,
                        source_loan_id=relink_options[relink_label],
                    )
                st.success(f"Moved {moved_count} loan transactions to {selected_loan.name}.")
                st.rerun()
elif summary_rows:
    st.info("Select a saved loan profile above to see imported EMI, MBK/prepayment, interest, and outstanding values.")

st.subheader("Prepayment scenario")
scenario_columns = st.columns(4)
as_of_date = scenario_columns[0].date_input("Analysis date", value=date.today())
recurring_extra_payment = scenario_columns[1].number_input("Monthly extra principal", min_value=0.0, value=0.0, step=1000.0)
one_time_prepayment_amount = scenario_columns[2].number_input("One-time prepayment", min_value=0.0, value=0.0, step=10000.0)
one_time_prepayment_date = scenario_columns[3].date_input("Prepayment date", value=as_of_date)

prepayments = []
if one_time_prepayment_amount > 0:
    prepayments.append(
        LoanPrepayment(
            payment_date=one_time_prepayment_date,
            amount=one_time_prepayment_amount,
        )
    )

try:
    analysis = analyze_home_loan(
        principal=principal,
        annual_interest_rate=interest_rate,
        start_date=loan_start_date,
        tenure_months=int(tenure_months),
        emi_amount=emi_amount,
        current_outstanding_balance=outstanding_balance or principal,
        recurring_extra_payment=recurring_extra_payment,
        one_time_prepayments=prepayments,
        as_of_date=as_of_date,
    )
except ValueError as exc:
    st.error(str(exc))
    st.stop()

metric_top_row = st.columns(3)
metric_bottom_row = st.columns(3)
metric_top_row[0].metric("Opening balance", format_inr(analysis.opening_balance))
metric_top_row[1].metric("Scheduled EMI", format_inr(analysis.scheduled_emi))
metric_top_row[2].metric("Projected interest", format_inr(analysis.projected_interest))
metric_bottom_row[0].metric("Interest saved", format_inr(analysis.interest_saved))
metric_bottom_row[1].metric("Baseline closure", analysis.baseline_closure_date.isoformat())
metric_bottom_row[2].metric("Projected closure", analysis.projected_closure_date.isoformat(), delta=f"{analysis.months_saved} months faster")

st.caption(
    f"Remaining tenure used for projection: {analysis.remaining_tenure_months} months. "
    f"One-time prepayment: {format_inr(analysis.one_time_prepayment_total)}. "
    f"Recurring extra principal: {format_inr(analysis.recurring_extra_payment)}."
)

baseline_df = pd.DataFrame(
    [
        {
            "due_date": row.due_date,
            "opening_balance": float(row.opening_balance),
            "interest": float(row.interest_component),
            "principal": float(row.principal_component),
            "extra_principal": float(row.extra_principal),
            "closing_balance": float(row.closing_balance),
        }
        for row in analysis.baseline_schedule
    ]
)
projected_df = pd.DataFrame(
    [
        {
            "due_date": row.due_date,
            "opening_balance": float(row.opening_balance),
            "interest": float(row.interest_component),
            "principal": float(row.principal_component),
            "extra_principal": float(row.extra_principal),
            "closing_balance": float(row.closing_balance),
            "total_payment": float(row.total_payment),
        }
        for row in analysis.projected_schedule
    ]
)

chart_columns = st.columns(2)
with chart_columns[0]:
    st.subheader("Projected interest vs principal")
    interest_principal_df = projected_df.set_index("due_date")[["interest", "principal", "extra_principal"]]
    st.bar_chart(interest_principal_df)

with chart_columns[1]:
    st.subheader("Outstanding balance trajectory")
    balance_df = baseline_df[["due_date", "closing_balance"]].rename(columns={"closing_balance": "baseline_balance"})
    balance_df = balance_df.merge(
        projected_df[["due_date", "closing_balance"]].rename(columns={"closing_balance": "projected_balance"}),
        on="due_date",
        how="outer",
    ).ffill()
    balance_df = balance_df.set_index("due_date")
    st.line_chart(balance_df)

st.subheader("Projected amortization schedule")
st.dataframe(projected_df, use_container_width=True, hide_index=True)

st.divider()
st.header("Imported Loan Ledger")

if not selected_loan:
    st.info("Save or select a loan profile to link detected loan transactions and calculate the monthly ledger.")
else:
    if st.button("Recalculate monthly loan ledger", use_container_width=True):
        with session_scope() as session:
            recalculate_loan_ledger(session, selected_loan.id)
        st.success("Loan ledger recalculated.")
        st.rerun()

    with session_scope() as session:
        loan_transactions = list_loan_transactions(session, loan_id=selected_loan.id, include_unlinked=True)
        ledger_rows = list_loan_ledger(session, selected_loan.id)
        all_loans = list_loans(session)

    total_emi_paid = sum(row.emi_paid for row in ledger_rows)
    total_prepayment_paid = selected_loan.summary_prepayment_paid or sum(row.prepayment_paid for row in ledger_rows)
    total_interest_paid = selected_loan.summary_interest_paid or sum((row.interest_charged or 0) for row in ledger_rows)
    total_principal_paid = selected_loan.summary_principal_paid or sum(
        (row.total_principal_reduced or (row.principal_from_emi or 0) + row.principal_from_prepayment)
        for row in ledger_rows
    )
    total_charges_paid = sum(row.charges_paid for row in ledger_rows)
    latest_closing = next((row.closing_outstanding for row in reversed(ledger_rows) if row.closing_outstanding is not None), None)
    inferred_rates = [row.inferred_annual_rate for row in ledger_rows if row.inferred_annual_rate is not None]
    average_inferred_rate = sum(inferred_rates) / len(inferred_rates) if inferred_rates else None
    latest_inferred_rate = inferred_rates[-1] if inferred_rates else None
    projection = build_loan_projection(selected_loan, ledger_rows, future_monthly_extra_prepayment=recurring_extra_payment)
    latest_rate_variance = next((row.rate_variance for row in reversed(ledger_rows) if row.rate_variance is not None), None)

    summary_top = st.columns(4)
    summary_middle = st.columns(4)
    summary_bottom = st.columns(4)
    summary_top[0].metric("Current outstanding", format_inr(latest_closing or selected_loan.outstanding_balance or 0))
    summary_top[1].metric("Total EMI paid", format_inr(total_emi_paid))
    summary_top[2].metric("MBK / prepayment paid", format_inr(total_prepayment_paid))
    summary_top[3].metric("Total interest paid", format_inr(total_interest_paid))
    summary_middle[0].metric("Total principal paid", format_inr(total_principal_paid))
    summary_middle[1].metric("Avg inferred annual rate", f"{average_inferred_rate:.2f}%" if average_inferred_rate is not None else "N/A")
    summary_middle[2].metric("Latest inferred annual rate", f"{latest_inferred_rate:.2f}%" if latest_inferred_rate is not None else "N/A")
    summary_middle[3].metric("Base annual rate", f"{float(selected_loan.interest_rate_annual or 0):.2f}%")
    summary_bottom[0].metric("Latest rate variance", f"{latest_rate_variance:.2f}%" if latest_rate_variance is not None else "N/A")
    summary_bottom[1].metric(
        "Estimated remaining tenure",
        f"{projection.summary.estimated_remaining_tenure_months} months"
        if projection.summary.estimated_remaining_tenure_months is not None
        else "N/A",
    )
    summary_bottom[2].metric("Future interest estimate", format_inr(projection.summary.estimated_total_future_interest or 0))
    summary_bottom[3].metric("Prepayment interest saved", format_inr(projection.summary.estimated_interest_saved_by_prepayment))

    st.subheader("Detected loan transactions")
    loan_label_by_id = {loan.id: f"{loan.id} | {loan.name}" for loan in all_loans}
    loan_id_by_label = {label: loan_id for loan_id, label in loan_label_by_id.items()}
    loan_link_options = ["Unlinked"] + list(loan_id_by_label.keys())
    transactions_df = pd.DataFrame(
        [
            {
                "id": item.id,
                "source_transaction_id": item.transaction_id,
                "rollback_to_parsed": False,
                "exclude_from_ledger": item.review_status == "ignored",
                "loan_link": loan_label_by_id.get(item.loan_id, "Unlinked"),
                "date": item.transaction_date,
                "amount": float(item.amount),
                "direction": item.direction,
                "type": item.loan_transaction_type,
                "review_status": item.review_status,
                "opening_outstanding": float(item.opening_outstanding) if item.opening_outstanding is not None else None,
                "closing_outstanding": float(item.closing_outstanding) if item.closing_outstanding is not None else None,
                "interest_component": float(item.interest_component) if item.interest_component is not None else None,
                "principal_component": float(item.principal_component) if item.principal_component is not None else None,
                "charges_component": float(item.charges_component) if item.charges_component is not None else None,
                "provided_annual_rate": float(item.provided_annual_rate) if item.provided_annual_rate is not None else None,
                "confidence": item.confidence_score,
                "reason": item.loan_match_reason or "",
                "description": item.raw_description,
                "notes": item.notes or "",
            }
            for item in loan_transactions
        ]
    )
    if transactions_df.empty:
        st.caption("No loan transactions detected yet. Upload a loan statement or a bank statement with loan patterns like MBK or LOAN RECOVERY.")
    else:
        edited_transactions_df = st.data_editor(
            transactions_df.set_index("id"),
            use_container_width=True,
            disabled=["source_transaction_id", "confidence", "reason"],
            column_config={
                "source_transaction_id": st.column_config.NumberColumn("Source tx", help="Parsed source transaction id, if available."),
                "rollback_to_parsed": st.column_config.CheckboxColumn(
                    "Rollback",
                    help="Restore date, amount, description, direction, and auto loan type from the parsed source transaction.",
                ),
                "exclude_from_ledger": st.column_config.CheckboxColumn(
                    "Exclude",
                    help="Soft-remove this row from ledger/projection. Uncheck to restore it.",
                ),
                "loan_link": st.column_config.SelectboxColumn("Loan", options=loan_link_options),
                "date": st.column_config.DateColumn("Date"),
                "amount": st.column_config.NumberColumn("Amount", format="%.2f"),
                "direction": st.column_config.SelectboxColumn("Direction", options=["debit", "credit"]),
                "type": st.column_config.SelectboxColumn("Type", options=LOAN_TRANSACTION_TYPES),
                "review_status": st.column_config.SelectboxColumn("Review", options=REVIEW_STATUSES),
                "opening_outstanding": st.column_config.NumberColumn("Opening outstanding", format="%.2f"),
                "closing_outstanding": st.column_config.NumberColumn("Closing outstanding", format="%.2f"),
                "interest_component": st.column_config.NumberColumn("Interest", format="%.2f"),
                "principal_component": st.column_config.NumberColumn("Principal", format="%.2f"),
                "charges_component": st.column_config.NumberColumn("Charges", format="%.2f"),
                "provided_annual_rate": st.column_config.NumberColumn("Annual rate %", format="%.4f"),
                "notes": st.column_config.TextColumn("Notes", width="large"),
                "description": st.column_config.TextColumn("Description", width="large"),
            },
        )
        st.caption(
            "Use Exclude as a reversible remove from calculations. Use Rollback only when the row is linked "
            "to a parsed source transaction and you want to undo manual edits."
        )
        if st.button("Save loan transaction edits", use_container_width=True):
            changed_count = 0
            warning_messages: list[str] = []
            original_transactions_df = transactions_df.set_index("id")
            tracked_fields = [
                "loan_link",
                "date",
                "amount",
                "direction",
                "type",
                "review_status",
                "exclude_from_ledger",
                "opening_outstanding",
                "closing_outstanding",
                "interest_component",
                "principal_component",
                "charges_component",
                "provided_annual_rate",
                "description",
                "notes",
            ]
            with session_scope() as session:
                for transaction_id, edited_row in edited_transactions_df.iterrows():
                    original_row = original_transactions_df.loc[transaction_id]
                    if bool(edited_row.get("rollback_to_parsed")):
                        if is_blank_editor_value(edited_row.get("source_transaction_id")):
                            warning_messages.append(f"Transaction {transaction_id} has no parsed source transaction to roll back to.")
                            continue
                        revert_loan_transaction_to_source(session=session, loan_transaction_id=int(transaction_id))
                        changed_count += 1
                        continue
                    if not any(editor_values_differ(edited_row.get(field), original_row.get(field)) for field in tracked_fields):
                        continue

                    selected_link = edited_row["loan_link"]
                    edited_review_status = str(edited_row.get("review_status") or "pending")
                    review_status = "ignored" if bool(edited_row.get("exclude_from_ledger")) else edited_review_status
                    if review_status == "ignored" and not bool(edited_row.get("exclude_from_ledger")):
                        review_status = "pending"
                    update_loan_transaction(
                        session=session,
                        loan_transaction_id=int(transaction_id),
                        loan_id=loan_id_by_label.get(selected_link, 0),
                        transaction_date=parse_editor_date(edited_row["date"]),
                        raw_description=str(edited_row["description"] or ""),
                        amount=parse_editor_float(edited_row["amount"]),
                        direction=str(edited_row["direction"] or "debit"),
                        loan_transaction_type=str(edited_row["type"]),
                        review_status=review_status,
                        opening_outstanding=parse_editor_float(edited_row.get("opening_outstanding")),
                        closing_outstanding=parse_editor_float(edited_row.get("closing_outstanding")),
                        interest_component=parse_editor_float(edited_row.get("interest_component")),
                        principal_component=parse_editor_float(edited_row.get("principal_component")),
                        charges_component=parse_editor_float(edited_row.get("charges_component")),
                        provided_annual_rate=parse_editor_float(edited_row.get("provided_annual_rate")),
                        notes=None if is_blank_editor_value(edited_row.get("notes")) else str(edited_row["notes"]),
                    )
                    changed_count += 1
            for message in warning_messages:
                st.warning(message)
            st.success(f"Saved {changed_count} loan transaction change(s).")
            st.rerun()

    st.subheader("Monthly loan ledger")
    ledger_df = pd.DataFrame(
        [
            {
                "month": row.month,
                "opening_outstanding": float(row.opening_outstanding) if row.opening_outstanding is not None else None,
                "emi_paid": float(row.emi_paid),
                "mbk_prepayment": float(row.prepayment_paid),
                "interest_charged": float(row.interest_charged) if row.interest_charged is not None else None,
                "principal_from_emi": float(row.principal_from_emi) if row.principal_from_emi is not None else None,
                "principal_from_prepayment": float(row.principal_from_prepayment),
                "total_principal_reduced": float(row.total_principal_reduced) if row.total_principal_reduced is not None else None,
                "charges_paid": float(row.charges_paid),
                "closing_outstanding": float(row.closing_outstanding) if row.closing_outstanding is not None else None,
                "inferred_annual_rate": float(row.inferred_annual_rate) if row.inferred_annual_rate is not None else None,
                "base_annual_rate": float(row.base_annual_rate) if row.base_annual_rate is not None else None,
                "rate_variance": float(row.rate_variance) if row.rate_variance is not None else None,
                "provided_annual_rate": float(row.provided_annual_rate) if row.provided_annual_rate is not None else None,
                "rate_source": row.rate_source,
                "calculation_method": row.calculation_method,
                "review_status": row.review_status,
                "manual_override": row.manual_override_used,
                "confidence": row.confidence_score,
                "notes": row.calculation_notes,
            }
            for row in ledger_rows
        ]
    )
    if ledger_df.empty:
        st.caption("No ledger rows yet. Confirm or link detected loan transactions, then recalculate.")
    else:
        chart_columns = st.columns(2)
        with chart_columns[0]:
            st.subheader("Interest and principal by month")
            st.bar_chart(ledger_df.set_index("month")[["interest_charged", "principal_from_emi", "principal_from_prepayment"]])
        with chart_columns[1]:
            st.subheader("EMI vs prepayment")
            st.bar_chart(ledger_df.set_index("month")[["emi_paid", "mbk_prepayment"]])

        trend_columns = st.columns(2)
        with trend_columns[0]:
            st.subheader("Outstanding trend")
            st.line_chart(ledger_df.set_index("month")[["opening_outstanding", "closing_outstanding"]])
        with trend_columns[1]:
            st.subheader("Actual rate vs base rate")
            rate_df = ledger_df.dropna(subset=["inferred_annual_rate"])
            if rate_df.empty:
                st.caption("No inferred rate data yet.")
            else:
                st.line_chart(rate_df.set_index("month")[["inferred_annual_rate", "base_annual_rate"]])

        st.dataframe(ledger_df, use_container_width=True, hide_index=True)
        actual_projected_df = pd.DataFrame(
            [
                {
                    "month": row.month,
                    "projected_interest": float(row.projected_interest) if row.projected_interest is not None else None,
                    "actual_interest": float(row.actual_interest) if row.actual_interest is not None else None,
                    "interest_difference": float(row.interest_difference) if row.interest_difference is not None else None,
                    "projected_principal": float(row.projected_principal) if row.projected_principal is not None else None,
                    "actual_principal": float(row.actual_principal) if row.actual_principal is not None else None,
                    "principal_difference": float(row.principal_difference) if row.principal_difference is not None else None,
                    "projected_closing": float(row.projected_closing) if row.projected_closing is not None else None,
                    "actual_closing": float(row.actual_closing) if row.actual_closing is not None else None,
                    "impact_of_prepayment": float(row.prepayment_impact) if row.prepayment_impact is not None else None,
                }
                for row in projection.actual_vs_projected
            ]
        )
        st.subheader("Actual vs projected")
        if actual_projected_df.empty:
            st.caption("No actual/projected rows yet.")
        else:
            trend_df = actual_projected_df.set_index("month")[["projected_closing", "actual_closing"]]
            st.line_chart(trend_df)
            st.dataframe(actual_projected_df, use_container_width=True, hide_index=True)

        low_confidence_df = ledger_df[(ledger_df["confidence"] < 0.65) | (ledger_df["review_status"] != "ok")]
        st.subheader("Review table")
        if low_confidence_df.empty:
            st.caption("No low-confidence or review-needed ledger months.")
        else:
            st.dataframe(low_confidence_df, use_container_width=True, hide_index=True)

    st.subheader("Manual monthly override")
    with st.form("loan-ledger-override"):
        override_month = st.date_input("Ledger month", value=date.today().replace(day=1))
        override_columns = st.columns(3)
        override_opening = override_columns[0].text_input("Opening outstanding", placeholder="optional")
        override_closing = override_columns[1].text_input("Closing outstanding", placeholder="optional")
        override_interest = override_columns[2].text_input("Interest charged", placeholder="optional")
        override_columns_2 = st.columns(3)
        override_principal = override_columns_2[0].text_input("Principal paid", placeholder="optional")
        override_charges = override_columns_2[1].text_input("Charges paid", placeholder="optional")
        override_rate = override_columns_2[2].text_input("Annual rate %", placeholder="optional")
        override_columns_3 = st.columns(2)
        override_emi = override_columns_3[0].text_input("EMI paid", placeholder="optional")
        override_prepayment = override_columns_3[1].text_input("MBK/prepayment paid", placeholder="optional")
        override_notes = st.text_area("Override notes")
        override_submitted = st.form_submit_button("Save override and recalculate", use_container_width=True)

    if override_submitted:
        try:
            with session_scope() as session:
                save_loan_manual_override(
                    session=session,
                    loan_id=selected_loan.id,
                    month=override_month,
                    opening_outstanding=parse_optional_float(override_opening),
                    closing_outstanding=parse_optional_float(override_closing),
                    interest_charged=parse_optional_float(override_interest),
                    principal_paid=parse_optional_float(override_principal),
                    emi_paid=parse_optional_float(override_emi),
                    prepayment_paid=parse_optional_float(override_prepayment),
                    charges_paid=parse_optional_float(override_charges),
                    annual_rate=parse_optional_float(override_rate),
                    notes=override_notes or None,
                )
            st.success("Manual override saved.")
            st.rerun()
        except ValueError as exc:
            st.error(f"Could not save override: {exc}")

    st.subheader("Manual rate event")
    with st.form("loan-rate-event"):
        rate_columns = st.columns(3)
        rate_effective_date = rate_columns[0].date_input("Effective date", value=date.today())
        rate_name = rate_columns[1].text_input("Rate name", value="Bank-provided loan rate")
        rate_percent = rate_columns[2].number_input(
            "Rate %",
            min_value=0.0,
            value=float(selected_loan.interest_rate_annual)
            if selected_loan.interest_rate_annual is not None
            else DEFAULT_BASE_ANNUAL_RATE,
            step=0.05,
        )
        source_note = st.text_area("Source note")
        rate_submitted = st.form_submit_button("Add rate event", use_container_width=True)

    if rate_submitted:
        with session_scope() as session:
            save_loan_rate_event(
                session=session,
                loan_id=selected_loan.id,
                effective_date=rate_effective_date,
                rate_name=rate_name,
                rate_percent=rate_percent,
                source_note=source_note or None,
            )
        st.success("Rate event added.")
        st.rerun()
