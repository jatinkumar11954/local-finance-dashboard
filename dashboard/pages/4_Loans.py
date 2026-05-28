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
    LoanPrepayment,
    analyze_home_loan,
    list_loan_ledger,
    list_loan_import_summaries,
    list_loan_transactions,
    list_loans,
    recalculate_loan_ledger,
    relink_loan_transactions,
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
        "Annual interest rate (%)",
        min_value=0.0,
        value=float(selected_loan.interest_rate_annual) if selected_loan and selected_loan.interest_rate_annual is not None else 8.5,
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
    total_prepayment_paid = sum(row.prepayment_paid for row in ledger_rows)
    total_interest_paid = sum((row.interest_charged or 0) for row in ledger_rows)
    total_principal_paid = sum((row.principal_paid or 0) for row in ledger_rows)
    total_charges_paid = sum(row.charges_paid for row in ledger_rows)
    latest_closing = next((row.closing_outstanding for row in reversed(ledger_rows) if row.closing_outstanding is not None), None)
    inferred_rates = [row.inferred_annual_rate for row in ledger_rows if row.inferred_annual_rate is not None]
    average_inferred_rate = sum(inferred_rates) / len(inferred_rates) if inferred_rates else None
    latest_inferred_rate = inferred_rates[-1] if inferred_rates else None

    summary_top = st.columns(5)
    summary_bottom = st.columns(5)
    summary_top[0].metric("Current outstanding", format_inr(latest_closing or selected_loan.outstanding_balance or 0))
    summary_top[1].metric("Total EMI paid", format_inr(total_emi_paid))
    summary_top[2].metric("Total prepayment paid", format_inr(total_prepayment_paid))
    summary_top[3].metric("Total interest paid", format_inr(total_interest_paid))
    summary_top[4].metric("Total principal paid", format_inr(total_principal_paid))
    summary_bottom[0].metric("Total charges paid", format_inr(total_charges_paid))
    summary_bottom[1].metric("Avg inferred annual rate", f"{average_inferred_rate:.2f}%" if average_inferred_rate is not None else "N/A")
    summary_bottom[2].metric("Latest inferred annual rate", f"{latest_inferred_rate:.2f}%" if latest_inferred_rate is not None else "N/A")
    summary_bottom[3].metric("Estimated remaining tenure", f"{analysis.remaining_tenure_months} months")
    summary_bottom[4].metric("Interest saved", format_inr(analysis.interest_saved))

    st.subheader("Detected loan transactions")
    loan_label_by_id = {loan.id: f"{loan.id} | {loan.name}" for loan in all_loans}
    loan_id_by_label = {label: loan_id for loan_id, label in loan_label_by_id.items()}
    loan_link_options = ["Unlinked"] + list(loan_id_by_label.keys())
    transactions_df = pd.DataFrame(
        [
            {
                "id": item.id,
                "loan_link": loan_label_by_id.get(item.loan_id, "Unlinked"),
                "date": item.transaction_date,
                "amount": float(item.amount),
                "type": item.loan_transaction_type,
                "review_status": item.review_status,
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
            disabled=["date", "amount", "confidence", "reason", "description"],
            column_config={
                "loan_link": st.column_config.SelectboxColumn("Loan", options=loan_link_options),
                "type": st.column_config.SelectboxColumn("Type", options=LOAN_TRANSACTION_TYPES),
                "review_status": st.column_config.SelectboxColumn("Review", options=REVIEW_STATUSES),
                "notes": st.column_config.TextColumn("Notes", width="large"),
                "description": st.column_config.TextColumn("Description", width="large"),
            },
        )
        if st.button("Save loan transaction review", use_container_width=True):
            with session_scope() as session:
                for transaction_id, edited_row in edited_transactions_df.iterrows():
                    original_row = transactions_df.set_index("id").loc[transaction_id]
                    if edited_row.equals(original_row):
                        continue
                    selected_link = edited_row["loan_link"]
                    update_loan_transaction(
                        session=session,
                        loan_transaction_id=int(transaction_id),
                        loan_id=loan_id_by_label.get(selected_link, 0),
                        loan_transaction_type=str(edited_row["type"]),
                        review_status=str(edited_row["review_status"]),
                        notes=str(edited_row["notes"] or ""),
                    )
            st.success("Loan transaction review saved.")
            st.rerun()

    st.subheader("Monthly loan ledger")
    ledger_df = pd.DataFrame(
        [
            {
                "month": row.month,
                "opening_outstanding": float(row.opening_outstanding) if row.opening_outstanding is not None else None,
                "emi_paid": float(row.emi_paid),
                "prepayment_paid": float(row.prepayment_paid),
                "interest_charged": float(row.interest_charged) if row.interest_charged is not None else None,
                "principal_paid": float(row.principal_paid) if row.principal_paid is not None else None,
                "charges_paid": float(row.charges_paid),
                "closing_outstanding": float(row.closing_outstanding) if row.closing_outstanding is not None else None,
                "inferred_annual_rate": float(row.inferred_annual_rate) if row.inferred_annual_rate is not None else None,
                "provided_annual_rate": float(row.provided_annual_rate) if row.provided_annual_rate is not None else None,
                "rate_source": row.rate_source,
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
            st.bar_chart(ledger_df.set_index("month")[["interest_charged", "principal_paid"]])
        with chart_columns[1]:
            st.subheader("EMI vs prepayment")
            st.bar_chart(ledger_df.set_index("month")[["emi_paid", "prepayment_paid"]])

        trend_columns = st.columns(2)
        with trend_columns[0]:
            st.subheader("Outstanding trend")
            st.line_chart(ledger_df.set_index("month")[["closing_outstanding"]])
        with trend_columns[1]:
            st.subheader("Inferred annual rate trend")
            rate_df = ledger_df.dropna(subset=["inferred_annual_rate"])
            if rate_df.empty:
                st.caption("No inferred rate data yet.")
            else:
                st.line_chart(rate_df.set_index("month")[["inferred_annual_rate"]])

        st.dataframe(ledger_df, use_container_width=True, hide_index=True)
        low_confidence_df = ledger_df[ledger_df["confidence"] < 0.65]
        st.subheader("Low-confidence months requiring review")
        if low_confidence_df.empty:
            st.caption("No low-confidence ledger months.")
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
        rate_percent = rate_columns[2].number_input("Rate %", min_value=0.0, value=float(selected_loan.interest_rate_annual or 0), step=0.05)
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
