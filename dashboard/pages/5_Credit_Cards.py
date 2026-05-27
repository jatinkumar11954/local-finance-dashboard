from __future__ import annotations

from pathlib import Path
import sys
from decimal import Decimal

import pandas as pd
import streamlit as st

DASHBOARD_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = DASHBOARD_DIR.parent
for path in (PROJECT_ROOT, DASHBOARD_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.services.credit_cards import (
    CARD_USAGE_TYPES,
    MANUAL_EMI_CHARGE_TYPES,
    add_manual_emi_charge,
    analyze_credit_card_transactions,
    list_credit_card_sources,
    list_credit_cards,
    update_credit_card_profile,
    update_credit_card_transaction_override,
    update_emi_plan_review,
)
from common import default_period, format_inr, initialize_page, render_sidebar_status, session_scope


ANALYSIS_MODE_LABELS = {
    "Normal": "normal",
    "EMI analysis": "emi_analysis",
    "UPI-only": "upi_only",
    "Mixed": "mixed",
}

initialize_page("Credit Cards")
render_sidebar_status()

st.title("Credit Card Analysis")
st.caption("Analyze locally parsed credit card statements for purchases, charges, and risky patterns.")

default_start, default_end = default_period()
with session_scope() as session:
    credit_cards = list_credit_cards(session)
card_options = {"All cards": None} | {
    f"{card.id} | {card.name} | {card.last4 or 'last4 unknown'} | {card.usage_type}": card for card in credit_cards
}
selected_card_label = st.selectbox("Credit card profile", list(card_options.keys()))
selected_card = card_options[selected_card_label]

if selected_card:
    with st.expander("Card profile settings", expanded=False):
        profile_columns = st.columns(4)
        updated_name = profile_columns[0].text_input("Card name", value=selected_card.name)
        updated_bank = profile_columns[1].text_input("Bank name", value=selected_card.bank_name or selected_card.issuer_name or "")
        updated_last4 = profile_columns[2].text_input("Last 4", value=selected_card.last4 or "", max_chars=4)
        usage_options = sorted(CARD_USAGE_TYPES)
        updated_usage = profile_columns[3].selectbox(
            "Usage type",
            usage_options,
            index=usage_options.index(selected_card.usage_type) if selected_card.usage_type in usage_options else usage_options.index("normal"),
        )
        if st.button("Save card profile", use_container_width=True):
            with session_scope() as session:
                update_credit_card_profile(
                    session,
                    selected_card.id,
                    card_name=updated_name,
                    bank_name=updated_bank,
                    last4=updated_last4,
                    usage_type=updated_usage,
                )
            st.success("Card profile updated.")
            st.rerun()

filter_columns = st.columns(5)
selected_range = filter_columns[0].date_input("Date range", value=(default_start, default_end))
include_card_like = filter_columns[1].checkbox("Include card-like bank rows", value=False)
with session_scope() as session:
    sources = list_credit_card_sources(session, include_card_like=include_card_like)
selected_source = filter_columns[2].selectbox("Card source", ["All sources"] + sources)
default_mode = "Normal"
if selected_card and selected_card.usage_type == "upi_only":
    default_mode = "UPI-only"
elif selected_card and selected_card.usage_type == "mixed":
    default_mode = "Mixed"
elif selected_card and selected_card.usage_type == "emi_focused":
    default_mode = "EMI analysis"
analysis_mode_label = filter_columns[3].selectbox(
    "Statement tag",
    list(ANALYSIS_MODE_LABELS.keys()),
    index=list(ANALYSIS_MODE_LABELS.keys()).index(default_mode),
)
filter_columns[4].caption("Use UPI-only or Mixed to keep UPI spends separate from card shopping.")

start_date = selected_range[0] if isinstance(selected_range, tuple) else default_start
end_date = selected_range[1] if isinstance(selected_range, tuple) and len(selected_range) > 1 else default_end

with session_scope() as session:
    analysis = analyze_credit_card_transactions(
        session=session,
        start_date=start_date,
        end_date=end_date,
        account_source=None if selected_source == "All sources" or selected_card else selected_source,
        include_card_like=include_card_like,
        analysis_mode=ANALYSIS_MODE_LABELS[analysis_mode_label],
        card_id=selected_card.id if selected_card else None,
    )

metric_columns = st.columns(5)
metric_columns[0].metric("Monthly card spend", format_inr(analysis.total_purchase_spend))
metric_columns[1].metric("Extra charges", format_inr(analysis.total_extra_charges))
metric_columns[2].metric("Interest charged", format_inr(analysis.total_interest))
metric_columns[3].metric("Fees + GST", format_inr(analysis.total_fees))
metric_columns[4].metric("Payments / credits", format_inr(analysis.total_payments_received))

emi_metric_columns = st.columns(4)
emi_metric_columns[0].metric("UPI card spend", format_inr(analysis.total_upi_spend))
emi_metric_columns[1].metric("EMI paid", format_inr(analysis.emi_summary.total_emi_paid))
emi_metric_columns[2].metric("Pending EMI", format_inr(analysis.emi_summary.pending_emi_amount))
emi_metric_columns[3].metric(
    "No-cost EMI net extra",
    format_inr(analysis.no_cost_emi_summary.net_extra_cost),
    help=f"Status: {analysis.no_cost_emi_summary.verification_status}",
)

plan_metric_columns = st.columns(4)
plan_metric_columns[0].metric("Active EMI plans", len([plan for plan in analysis.emi_plans if plan.lifecycle_status == "active"]))
plan_metric_columns[1].metric("No-cost EMI plans", len([plan for plan in analysis.emi_plans if plan.no_cost_claimed]))
plan_metric_columns[2].metric(
    "Truly no-cost plans",
    len([plan for plan in analysis.emi_plans if plan.no_cost_verification_status == "truly_no_cost"]),
)
plan_metric_columns[3].metric(
    "Plans needing review",
    len([plan for plan in analysis.emi_plans if plan.lifecycle_status == "needs_review" or plan.no_cost_verification_status in {"unknown", "needs_review"}]),
)

if not analysis.classified_transactions:
    st.info("No credit card transactions matched the current filters. Upload a credit card statement or broaden the filters.")
    st.stop()

chart_columns = st.columns(2)
with chart_columns[0]:
    st.subheader("Monthly purchase spend")
    monthly_spend_df = pd.DataFrame(
        [
            {"period": item["period"], "spend": float(item["spend"])}
            for item in analysis.monthly_spend
        ]
    )
    if not monthly_spend_df.empty:
        st.bar_chart(monthly_spend_df.set_index("period"))
    else:
        st.caption("No purchase spend found.")

with chart_columns[1]:
    st.subheader("Extra charge breakdown")
    charge_df = pd.DataFrame(
        [
            {"charge_type": item["charge_type"], "amount": float(item["amount"])}
            for item in analysis.extra_charge_breakdown
        ]
    )
    if not charge_df.empty:
        st.dataframe(charge_df, use_container_width=True, hide_index=True)
    else:
        st.caption("No extra charges detected.")

st.subheader("Risk flags")
if analysis.risky_patterns:
    for risk in analysis.risky_patterns:
        st.warning(risk)
else:
    st.success("No credit-card risk patterns were flagged for the selected data.")

if analysis.review_warnings:
    st.subheader("Needs review / awaiting more statements")
    for warning in analysis.review_warnings:
        st.warning(warning)

upi_df = pd.DataFrame(
    [
        {
            "date": item.date,
            "receiver": item.receiver_name,
            "amount": float(item.amount),
            "category": item.category,
            "statement_file": item.statement_file or "",
            "description": item.description,
        }
        for item in analysis.upi_transactions
    ]
)
if analysis.analysis_mode in {"upi_only", "mixed"}:
    st.subheader("UPI-only / mixed card UPI analysis")
    daily_upi_df = pd.DataFrame(
        [{"date": item["date"], "amount": float(item["amount"])} for item in analysis.daily_upi_spend]
    )
    if daily_upi_df.empty:
        st.caption("No UPI transactions detected for this card source.")
    else:
        st.line_chart(daily_upi_df.set_index("date"))
        st.dataframe(upi_df, use_container_width=True, hide_index=True)
        upi_columns = st.columns(2)
        with upi_columns[0]:
            st.caption("Top UPI receivers")
            st.dataframe(pd.DataFrame(analysis.top_upi_receivers), use_container_width=True, hide_index=True)
        with upi_columns[1]:
            st.caption("Repeated UPI payments")
            st.dataframe(pd.DataFrame(analysis.repeated_upi_payments), use_container_width=True, hide_index=True)
        breakdown_columns = st.columns(2)
        with breakdown_columns[0]:
            st.caption("Person transfer vs merchant spend")
            st.dataframe(pd.DataFrame(analysis.upi_transfer_breakdown), use_container_width=True, hide_index=True)
        with breakdown_columns[1]:
            st.caption("Small frequent UPI payments")
            st.dataframe(pd.DataFrame(analysis.small_frequent_upi_payments), use_container_width=True, hide_index=True)

st.subheader("Credit card EMI analysis")
emi_plan_df = pd.DataFrame(
    [
        {
            "plan_id": plan.plan_id,
            "merchant": plan.merchant_name or "",
            "monthly_emi": float(plan.monthly_emi_amount) if plan.monthly_emi_amount is not None else None,
            "completed_total": f"{plan.completed_emi_count if plan.completed_emi_count is not None else '?'} / {plan.total_emi_count if plan.total_emi_count is not None else '?'}",
            "pending_emi": plan.pending_emi_count,
            "no_cost_claimed": plan.no_cost_claimed,
            "no_cost_status": plan.no_cost_verification_status,
            "interest_charged": float(plan.total_interest_charged),
            "interest_reversed": float(plan.total_interest_reversed),
            "gst_on_interest": float(plan.total_gst_on_interest),
            "processing_fee": float(plan.total_processing_fee),
            "gst_on_processing_fee": float(plan.total_gst_on_processing_fee),
            "net_extra_cost": float(plan.total_extra_cost),
            "effective_extra_cost_percent": float(plan.effective_extra_cost_percent) if plan.effective_extra_cost_percent is not None else None,
            "confidence": plan.confidence_score,
            "status": plan.lifecycle_status,
        }
        for plan in analysis.emi_plans
    ]
)
if not emi_plan_df.empty:
    st.caption("EMI lifecycle plans from credit-card statement ingestion.")
    st.dataframe(emi_plan_df, use_container_width=True, hide_index=True)

emi_summary_df = pd.DataFrame(
    [
        {
            "detected_emi_count": analysis.emi_summary.detected_emi_count,
            "total_emi_paid": float(analysis.emi_summary.total_emi_paid),
            "pending_emi_count": analysis.emi_summary.pending_emi_count,
            "pending_emi_amount": float(analysis.emi_summary.pending_emi_amount),
            "total_emi_obligation": float(analysis.emi_summary.total_emi_obligation),
            "schedule_detected": analysis.emi_summary.schedule_detected,
            "schedule_entries_count": analysis.emi_summary.schedule_entries_count,
        }
    ]
)
st.dataframe(emi_summary_df, use_container_width=True, hide_index=True)

emi_df = pd.DataFrame(
    [
        {
            "date": item.date,
            "amount": float(item.amount),
            "installment": f"{item.current_installment or '?'} / {item.total_installments or '?'}",
            "pending_installments": item.pending_installments,
            "merchant": item.merchant_name or "",
            "statement_file": item.statement_file or "",
            "description": item.description,
        }
        for item in analysis.emi_transactions
    ]
)
if emi_df.empty:
    st.caption("No monthly EMI transactions detected.")
else:
    st.dataframe(emi_df, use_container_width=True, hide_index=True)

schedule_df = pd.DataFrame(
    [
        {
            "statement_file": item.statement_file,
            "amount": float(item.amount) if item.amount is not None else None,
            "original_transaction_date": item.original_transaction_date,
            "emi_start_date": item.emi_start_date,
            "installment": f"{item.current_installment or '?'} / {item.total_installments or '?'}",
            "pending_installments": item.pending_installments,
            "description": item.description,
        }
        for item in analysis.emi_schedule
    ]
)
if not schedule_df.empty:
    st.caption("EMI schedule rows parsed from statement text.")
    st.dataframe(schedule_df, use_container_width=True, hide_index=True)

st.subheader("No-cost EMI cost verification")
no_cost = analysis.no_cost_emi_summary
no_cost_df = pd.DataFrame(
    [
        {
            "interest_charged": float(no_cost.interest_charged),
            "interest_reversal": float(no_cost.interest_reversal),
            "cashback_discount": float(no_cost.cashback_discount),
            "gst_on_interest": float(no_cost.gst_on_interest),
            "processing_fee": float(no_cost.processing_fee),
            "gst_on_processing_fee": float(no_cost.gst_on_processing_fee),
            "other_charges": float(no_cost.other_charges),
            "other_credits": float(no_cost.other_credits),
            "net_interest_paid": float(no_cost.net_interest_paid),
            "total_gst_paid": float(no_cost.total_gst_paid),
            "net_extra_cost": float(no_cost.net_extra_cost),
            "effective_extra_cost_percent": float(no_cost.effective_extra_cost_percent) if no_cost.effective_extra_cost_percent is not None else None,
            "verification_status": no_cost.verification_status,
            "needs_review": no_cost.needs_review,
            "awaiting_more_statements": no_cost.awaiting_more_statements,
        }
    ]
)
st.dataframe(no_cost_df, use_container_width=True, hide_index=True)

st.subheader("Manual review and correction")
review_columns = st.columns(2)
with review_columns[0]:
    if analysis.classified_transactions:
        transaction_options = {
            f"{item.transaction_id} | {item.date} | {item.charge_type} | {item.description[:60]}": item
            for item in analysis.classified_transactions
        }
        selected_transaction_label = st.selectbox("Transaction to correct", list(transaction_options.keys()))
        selected_transaction = transaction_options[selected_transaction_label]
        parsed_type_options = [
            "purchase",
            "payment",
            "emi_transaction",
            "emi_principal",
            "emi_interest",
            "interest_reversal",
            "cashback_discount",
            "discount",
            "processing_fee",
            "gst_on_interest",
            "gst_on_processing_fee",
            "late_fee",
            "finance_charge",
            "upi_card_spend",
            "other_charge",
            "other_credit",
        ]
        selected_parsed_type = st.selectbox(
            "Parsed type override",
            parsed_type_options,
            index=parsed_type_options.index(selected_transaction.charge_type)
            if selected_transaction.charge_type in parsed_type_options
            else parsed_type_options.index("purchase"),
        )
        plan_id_override = st.number_input("Link to EMI plan id (optional)", min_value=0, step=1, value=0)
        correction_notes = st.text_input("Correction notes", placeholder="Optional note")
        if st.button("Apply transaction correction", use_container_width=True):
            with session_scope() as session:
                update_credit_card_transaction_override(
                    session=session,
                    transaction_id=selected_transaction.transaction_id,
                    parsed_type=selected_parsed_type,
                    emi_plan_id=int(plan_id_override) if plan_id_override else None,
                    notes=correction_notes or None,
                )
            st.success("Transaction correction saved.")
            st.rerun()

with review_columns[1]:
    if analysis.emi_plans:
        plan_options = {f"{plan.plan_id} | {plan.merchant_name or 'Unknown'} | {plan.no_cost_verification_status}": plan for plan in analysis.emi_plans}
        selected_plan_label = st.selectbox("EMI plan to review", list(plan_options.keys()))
        selected_plan = plan_options[selected_plan_label]
        status_options = ["unknown", "truly_no_cost", "partial_no_cost", "not_no_cost", "needs_review"]
        lifecycle_options = ["active", "completed", "closed_early", "unknown", "needs_review"]
        fee_status_options = ["processing_fee_unknown", "processing_fee_found", "manual_entry", "not_applicable"]
        reviewed_status = st.selectbox(
            "No-cost verification status",
            status_options,
            index=status_options.index(selected_plan.no_cost_verification_status)
            if selected_plan.no_cost_verification_status in status_options
            else 0,
        )
        reviewed_fee_status = st.selectbox(
            "Processing fee status",
            fee_status_options,
            index=fee_status_options.index(selected_plan.processing_fee_status)
            if selected_plan.processing_fee_status in fee_status_options
            else 0,
        )
        reviewed_lifecycle = st.selectbox(
            "Lifecycle status",
            lifecycle_options,
            index=lifecycle_options.index(selected_plan.lifecycle_status) if selected_plan.lifecycle_status in lifecycle_options else 3,
        )
        reviewed_notes = st.text_area("Plan notes", value=selected_plan.notes or "", height=80)
        if st.button("Save EMI plan review", use_container_width=True):
            with session_scope() as session:
                update_emi_plan_review(
                    session=session,
                    plan_id=selected_plan.plan_id,
                    no_cost_verification_status=reviewed_status,
                    processing_fee_status=reviewed_fee_status,
                    lifecycle_status=reviewed_lifecycle,
                    notes=reviewed_notes,
                )
            st.success("EMI plan review saved.")
            st.rerun()

        st.caption("Add missing EMI fee, GST, cashback, discount, or reversal manually when the statement row is absent.")
        manual_charge_columns = st.columns(3)
        manual_charge_type = manual_charge_columns[0].selectbox("Manual charge type", sorted(MANUAL_EMI_CHARGE_TYPES))
        manual_charge_amount = manual_charge_columns[1].number_input("Amount", min_value=0.0, step=1.0, value=0.0)
        manual_charge_month = manual_charge_columns[2].date_input("Charge month", value=start_date)
        manual_charge_notes = st.text_input("Manual charge notes", placeholder="Example: fee shown on invoice, not statement")
        if st.button("Add manual EMI charge/credit", use_container_width=True, disabled=manual_charge_amount <= 0):
            with session_scope() as session:
                add_manual_emi_charge(
                    session=session,
                    plan_id=selected_plan.plan_id,
                    charge_type=manual_charge_type,
                    amount=Decimal(str(manual_charge_amount)),
                    charge_month=manual_charge_month,
                    notes=manual_charge_notes or None,
                )
            st.success("Manual EMI charge added.")
            st.rerun()

st.subheader("Flagged transactions")
flagged_df = pd.DataFrame(
    [
        {
            "date": insight.date,
            "amount": float(insight.amount),
            "charge_type": insight.charge_type,
            "merchant": insight.merchant_name or "",
            "description": insight.description,
            "risk_flags": "; ".join(insight.risk_flags),
        }
        for insight in analysis.flagged_transactions
    ]
)
if flagged_df.empty:
    st.caption("No flagged transactions in the current filter window.")
else:
    st.dataframe(flagged_df, use_container_width=True, hide_index=True)

st.subheader("Classified credit card transactions")
classified_df = pd.DataFrame(
    [
        {
            "date": insight.date,
            "amount": float(insight.amount),
            "transaction_type": insight.transaction_type,
            "charge_type": insight.charge_type,
            "merchant": insight.merchant_name or "",
            "category": insight.category,
            "extra_charge": float(insight.extra_charge_amount),
            "statement_file": insight.statement_file or "",
            "description": insight.description,
        }
        for insight in analysis.classified_transactions
    ]
)
st.dataframe(classified_df, use_container_width=True, hide_index=True)
