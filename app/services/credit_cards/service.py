from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
import re

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.entities import (
    CreditCard,
    CreditCardEmiCharge,
    CreditCardEmiPlan,
    CreditCardStatement,
    CreditCardTransaction,
    Document,
    Transaction,
)
from app.services.categorization.rules import normalize_text
from app.services.credit_cards.analysis import (
    VALID_CHARGE_TYPES,
    classify_credit_card_transaction,
    detect_no_cost_emi,
    parse_emi_installment,
)


CARD_USAGE_TYPES = {"normal", "upi_only", "mixed", "emi_focused"}
STATEMENT_TAGS = {"normal", "emi_analysis", "upi_only", "mixed"}
EMI_PLAN_CHARGE_TYPES = {
    "emi_transaction",
    "emi_principal",
    "emi_interest",
    "interest_charge",
    "interest_reversal",
    "cashback_discount",
    "discount",
    "bank_offer_credit",
    "processing_fee",
    "emi_conversion",
    "gst_on_interest",
    "gst_on_processing_fee",
    "late_fee",
    "finance_charge",
    "other_charge",
    "other_credit",
}
CHARGE_TYPE_MAP = {
    "emi_transaction": "emi_debit",
    "emi_principal": "principal",
    "emi_interest": "interest",
    "interest_charge": "interest",
    "interest_reversal": "interest_reversal",
    "cashback_discount": "cashback",
    "discount": "discount",
    "bank_offer_credit": "bank_offer_credit",
    "processing_fee": "processing_fee",
    "emi_conversion": "processing_fee",
    "gst_on_interest": "gst_on_interest",
    "gst_on_processing_fee": "gst_on_processing_fee",
    "late_fee": "other_charge",
    "finance_charge": "other_charge",
    "other_charge": "other_charge",
    "other_credit": "other_credit",
}
MANUAL_EMI_CHARGE_TYPES = {
    "emi_debit",
    "principal",
    "interest",
    "interest_reversal",
    "gst_on_interest",
    "processing_fee",
    "gst_on_processing_fee",
    "cashback",
    "discount",
    "bank_offer_credit",
    "other_charge",
    "other_credit",
}
MANUAL_EMI_PLAN_ID_PATTERN = re.compile(r"\bcc_emi_plan_id\s*[:=]\s*(?P<plan_id>\d+)", re.IGNORECASE)
MANUAL_NOCOST_STATUS_PATTERN = re.compile(r"\bcc_no_cost_status\s*[:=]\s*(?P<status>[a-z_]+)", re.IGNORECASE)
NOCOST_STATUSES = {"truly_no_cost", "partial_no_cost", "not_no_cost", "unknown", "needs_review"}
NOCOST_TOLERANCE = Decimal("1.00")


def normalize_card_usage_type(value: str | None) -> str:
    normalized = normalize_text(value).replace(" ", "_").replace("-", "_")
    return normalized if normalized in CARD_USAGE_TYPES else "normal"


def normalize_statement_tag(value: str | None) -> str:
    normalized = normalize_text(value).replace(" ", "_").replace("-", "_")
    return normalized if normalized in STATEMENT_TAGS else "normal"


def normalize_last4(value: str | None) -> str | None:
    digits = re.sub(r"\D+", "", value or "")
    return digits[-4:] if len(digits) >= 4 else None


def masked_card_number(last4: str | None) -> str | None:
    return f"****{last4}" if last4 else None


def list_credit_cards(session: Session, active_only: bool = False) -> list[CreditCard]:
    statement = select(CreditCard).order_by(CreditCard.name.asc(), CreditCard.id.asc())
    if active_only:
        statement = statement.where(CreditCard.active.is_(True))
    return session.scalars(statement).all()


def get_or_create_credit_card(
    session: Session,
    card_name: str | None,
    bank_name: str | None = None,
    last4: str | None = None,
    usage_type: str | None = None,
) -> CreditCard:
    usage_type = normalize_card_usage_type(usage_type)
    last4 = normalize_last4(last4)
    name = (card_name or bank_name or "Credit Card").strip() or "Credit Card"

    existing = None
    if last4:
        existing = session.scalar(select(CreditCard).where(CreditCard.last4 == last4))
    if existing is None:
        existing = session.scalar(select(CreditCard).where(CreditCard.name == name))
    if existing:
        if bank_name and not existing.bank_name:
            existing.bank_name = bank_name
        if bank_name and not existing.issuer_name:
            existing.issuer_name = bank_name
        if last4 and not existing.last4:
            existing.last4 = last4
            existing.masked_card_number = masked_card_number(last4)
        if usage_type:
            existing.usage_type = usage_type
        session.add(existing)
        session.flush()
        return existing

    card = CreditCard(
        name=name,
        issuer_name=bank_name,
        bank_name=bank_name,
        last4=last4,
        masked_card_number=masked_card_number(last4),
        usage_type=usage_type,
        active=True,
    )
    session.add(card)
    session.flush()
    return card


def update_credit_card_profile(
    session: Session,
    card_id: int,
    card_name: str | None = None,
    bank_name: str | None = None,
    last4: str | None = None,
    usage_type: str | None = None,
    active: bool | None = None,
) -> CreditCard:
    card = session.get(CreditCard, card_id)
    if card is None:
        raise ValueError(f"Credit card {card_id} was not found.")
    if card_name:
        card.name = card_name.strip()
    if bank_name is not None:
        card.bank_name = bank_name.strip() or None
        card.issuer_name = card.bank_name
    if last4 is not None:
        card.last4 = normalize_last4(last4)
        card.masked_card_number = masked_card_number(card.last4)
    if usage_type is not None:
        card.usage_type = normalize_card_usage_type(usage_type)
    if active is not None:
        card.active = active
    session.add(card)
    session.commit()
    session.refresh(card)
    return card


def sync_credit_card_document(
    session: Session,
    document: Document,
    transactions: list[Transaction],
    card_name: str | None = None,
    bank_name: str | None = None,
    last4: str | None = None,
    usage_type: str | None = None,
    uploaded_tag: str | None = None,
) -> int:
    if document.document_type != "credit_card_statement" or not transactions:
        return 0

    inferred_source = next((transaction.account_source for transaction in transactions if transaction.account_source), None)
    card = get_or_create_credit_card(
        session=session,
        card_name=card_name or inferred_source or document.filename,
        bank_name=bank_name,
        last4=last4,
        usage_type=usage_type or uploaded_tag,
    )
    statement = _get_or_create_statement(session, card, document, transactions, uploaded_tag)
    transaction_ids = [transaction.id for transaction in transactions if transaction.id is not None]
    _delete_synced_credit_card_rows(session, transaction_ids)

    created = 0
    for transaction in transactions:
        charge_type, risk_flags = classify_credit_card_transaction(
            transaction.raw_description,
            transaction.transaction_type,
            transaction.category,
            transaction.payment_mode,
        )
        manual_override = _manual_charge_type_override(transaction)
        if manual_override:
            charge_type = manual_override
        row = CreditCardTransaction(
            card_id=card.id,
            statement_id=statement.id,
            transaction_id=transaction.id,
            transaction_date=transaction.date,
            posting_date=transaction.date,
            description=transaction.raw_description,
            amount=transaction.amount,
            transaction_type=transaction.transaction_type,
            parsed_type=charge_type,
            merchant_name=transaction.merchant_name,
            category=transaction.category,
            source_document_id=document.id,
            confidence_score=0.95 if not risk_flags else 0.75,
            manual_override=manual_override is not None,
            match_reason="Manual override" if manual_override else f"Auto classified as {charge_type}",
        )
        session.add(row)
        created += 1
    session.flush()
    recalculate_credit_card_emi_plans(session, card.id)
    return created


def delete_credit_card_document_data(session: Session, document_id: int) -> None:
    rows = session.scalars(
        select(CreditCardTransaction).where(CreditCardTransaction.source_document_id == document_id)
    ).all()
    transaction_ids = [row.transaction_id for row in rows if row.transaction_id is not None]
    if transaction_ids:
        session.execute(delete(CreditCardEmiCharge).where(CreditCardEmiCharge.transaction_id.in_(transaction_ids)))
    statement_ids = [row.statement_id for row in rows if row.statement_id is not None]
    session.execute(delete(CreditCardTransaction).where(CreditCardTransaction.source_document_id == document_id))
    if statement_ids:
        session.execute(delete(CreditCardStatement).where(CreditCardStatement.id.in_(statement_ids)))


def recalculate_credit_card_emi_plans(session: Session, card_id: int) -> list[CreditCardEmiPlan]:
    card_transactions = session.scalars(
        select(CreditCardTransaction)
        .where(CreditCardTransaction.card_id == card_id)
        .order_by(CreditCardTransaction.transaction_date.asc(), CreditCardTransaction.id.asc())
    ).all()
    existing_plans = {
        _plan_auto_key(plan): plan
        for plan in session.scalars(select(CreditCardEmiPlan).where(CreditCardEmiPlan.card_id == card_id)).all()
    }

    plans_by_key: dict[str, CreditCardEmiPlan] = {}
    plan_seed_types = {"emi_transaction", "emi_principal", "emi_interest"}
    for row in [item for item in card_transactions if item.parsed_type in plan_seed_types]:
        plan = _resolve_emi_plan(session, row, existing_plans, plans_by_key, allow_create=True)
        if plan:
            _apply_transaction_to_plan(plan, row)
    session.flush()

    for row in card_transactions:
        if row.parsed_type not in EMI_PLAN_CHARGE_TYPES:
            continue
        plan = _resolve_emi_plan(session, row, existing_plans, plans_by_key, allow_create=row.parsed_type in plan_seed_types)
        if plan is None:
            continue
        _apply_transaction_to_plan(plan, row)
        charge_type = CHARGE_TYPE_MAP.get(row.parsed_type)
        if charge_type:
            _upsert_emi_charge(session, plan, row, charge_type)

    session.flush()
    for plan in set(plans_by_key.values()):
        _refresh_plan_rollup(session, plan)
    session.flush()
    return sorted(plans_by_key.values(), key=lambda item: item.id)


def update_credit_card_transaction_override(
    session: Session,
    transaction_id: int,
    parsed_type: str,
    emi_plan_id: int | None = None,
    notes: str | None = None,
) -> Transaction:
    if parsed_type not in VALID_CHARGE_TYPES:
        raise ValueError(f"Unsupported credit-card parsed type: {parsed_type}")
    transaction = session.get(Transaction, transaction_id)
    if transaction is None:
        raise ValueError(f"Transaction {transaction_id} was not found.")

    override_note = f"cc_charge_type={parsed_type}"
    if emi_plan_id is not None:
        override_note = f"{override_note}; cc_emi_plan_id={emi_plan_id}"
    if notes:
        override_note = f"{override_note}; {notes}"
    transaction.notes = _replace_note_directive(transaction.notes, "cc_charge_type", override_note)

    linked = session.scalar(select(CreditCardTransaction).where(CreditCardTransaction.transaction_id == transaction_id))
    if linked:
        linked.parsed_type = parsed_type
        linked.manual_override = True
        linked.match_reason = "Manual override"
        session.add(linked)
        recalculate_credit_card_emi_plans(session, linked.card_id)
    session.add(transaction)
    session.commit()
    session.refresh(transaction)
    return transaction


def update_emi_plan_review(
    session: Session,
    plan_id: int,
    no_cost_verification_status: str | None = None,
    processing_fee_status: str | None = None,
    lifecycle_status: str | None = None,
    notes: str | None = None,
    total_emi_count: int | None = None,
    pending_emi_count: int | None = None,
    monthly_emi_amount: Decimal | None = None,
    merchant_name: str | None = None,
) -> CreditCardEmiPlan:
    plan = session.get(CreditCardEmiPlan, plan_id)
    if plan is None:
        raise ValueError(f"EMI plan {plan_id} was not found.")
    if no_cost_verification_status in NOCOST_STATUSES:
        plan.no_cost_verification_status = no_cost_verification_status
    if processing_fee_status:
        plan.processing_fee_status = processing_fee_status
    if lifecycle_status:
        plan.lifecycle_status = lifecycle_status
    if notes is not None:
        plan.notes = notes
    if total_emi_count is not None:
        plan.total_emi_count = total_emi_count
    if pending_emi_count is not None:
        plan.pending_emi_count = pending_emi_count
    if monthly_emi_amount is not None:
        plan.monthly_emi_amount = monthly_emi_amount
    if merchant_name is not None:
        plan.merchant_name = merchant_name or None
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return plan


def add_manual_emi_charge(
    session: Session,
    plan_id: int,
    charge_type: str,
    amount: Decimal,
    charge_month: date,
    notes: str | None = None,
) -> CreditCardEmiCharge:
    if charge_type not in MANUAL_EMI_CHARGE_TYPES:
        raise ValueError(f"Unsupported EMI charge type: {charge_type}")
    plan = session.get(CreditCardEmiPlan, plan_id)
    if plan is None:
        raise ValueError(f"EMI plan {plan_id} was not found.")
    month = date(charge_month.year, charge_month.month, 1)
    charge = CreditCardEmiCharge(
        emi_plan_id=plan.id,
        transaction_id=None,
        charge_month=month,
        charge_type=charge_type,
        amount=amount,
        confidence_score=1.0,
        manual_override=True,
        notes=notes or "Manual EMI charge entry",
    )
    session.add(charge)
    session.flush()
    _refresh_plan_rollup(session, plan)
    session.commit()
    session.refresh(charge)
    return charge


def _get_or_create_statement(
    session: Session,
    card: CreditCard,
    document: Document,
    transactions: list[Transaction],
    uploaded_tag: str | None,
) -> CreditCardStatement:
    latest_date = max(transaction.date for transaction in transactions)
    statement_month = date(latest_date.year, latest_date.month, 1)
    existing = session.scalar(
        select(CreditCardStatement).where(
            CreditCardStatement.credit_card_id == card.id,
            CreditCardStatement.source_document_id == document.id,
        )
    )
    if existing:
        existing.uploaded_tag = normalize_statement_tag(uploaded_tag)
        existing.statement_date = latest_date
        existing.statement_month = statement_month
        session.add(existing)
        session.flush()
        return existing

    statement = CreditCardStatement(
        credit_card_id=card.id,
        statement_date=latest_date,
        statement_month=statement_month,
        uploaded_tag=normalize_statement_tag(uploaded_tag),
        source_document_id=document.id,
    )
    session.add(statement)
    session.flush()
    return statement


def _delete_synced_credit_card_rows(session: Session, transaction_ids: list[int]) -> None:
    if not transaction_ids:
        return
    session.execute(delete(CreditCardEmiCharge).where(CreditCardEmiCharge.transaction_id.in_(transaction_ids)))
    session.execute(delete(CreditCardTransaction).where(CreditCardTransaction.transaction_id.in_(transaction_ids)))


def _manual_charge_type_override(transaction: Transaction) -> str | None:
    if not transaction.notes:
        return None
    match = re.search(r"\bcc_charge_type\s*[:=]\s*(?P<charge_type>[a-z_]+)", transaction.notes, re.IGNORECASE)
    if not match:
        return None
    charge_type = match.group("charge_type").lower()
    return charge_type if charge_type in VALID_CHARGE_TYPES else None


def _replace_note_directive(existing_notes: str | None, directive: str, replacement: str) -> str:
    notes = existing_notes or ""
    pattern = re.compile(rf"\b{re.escape(directive)}\s*[:=]\s*[a-z_]+(?:;\s*cc_emi_plan_id\s*[:=]\s*\d+)?", re.IGNORECASE)
    cleaned = pattern.sub("", notes).strip(" ;\n")
    return f"{cleaned}; {replacement}" if cleaned else replacement


def _resolve_emi_plan(
    session: Session,
    row: CreditCardTransaction,
    existing_plans: dict[str, CreditCardEmiPlan],
    plans_by_key: dict[str, CreditCardEmiPlan],
    allow_create: bool,
) -> CreditCardEmiPlan | None:
    explicit_plan_id = _manual_plan_id(row.transaction_id, session)
    if explicit_plan_id:
        plan = session.get(CreditCardEmiPlan, explicit_plan_id)
        if plan and plan.card_id == row.card_id:
            plans_by_key[_plan_auto_key(plan)] = plan
            return plan

    key = _emi_plan_key(row)
    plan = plans_by_key.get(key) or existing_plans.get(key)
    if plan is None and allow_create:
        plan = CreditCardEmiPlan(
            card_id=row.card_id,
            merchant_name=row.merchant_name or _merchant_from_description(row.description),
            emi_start_month=date(row.transaction_date.year, row.transaction_date.month, 1),
            no_cost_claimed=detect_no_cost_emi(row.description),
            processing_fee_status="processing_fee_unknown",
            lifecycle_status="unknown",
            confidence_score=0.65,
            notes=f"auto_key={key}",
        )
        session.add(plan)
        session.flush()
    if plan is None:
        plan = _single_active_plan_for_card(session, row.card_id)
    if plan:
        plans_by_key[key] = plan
    return plan


def _manual_plan_id(transaction_id: int | None, session: Session) -> int | None:
    if transaction_id is None:
        return None
    transaction = session.get(Transaction, transaction_id)
    if transaction is None or not transaction.notes:
        return None
    match = MANUAL_EMI_PLAN_ID_PATTERN.search(transaction.notes)
    return int(match.group("plan_id")) if match else None


def _single_active_plan_for_card(session: Session, card_id: int) -> CreditCardEmiPlan | None:
    plans = session.scalars(
        select(CreditCardEmiPlan).where(
            CreditCardEmiPlan.card_id == card_id,
            CreditCardEmiPlan.lifecycle_status.in_(["active", "unknown", "needs_review"]),
        )
    ).all()
    return plans[0] if len(plans) == 1 else None


def _plan_auto_key(plan: CreditCardEmiPlan) -> str:
    if plan.notes:
        match = re.search(r"\bauto_key\s*[:=]\s*(?P<key>[a-z0-9_-]+)", plan.notes)
        if match:
            return match.group("key")
    return normalize_text(plan.merchant_name or f"plan_{plan.id}").replace(" ", "_")[:80]


def _emi_plan_key(row: CreditCardTransaction) -> str:
    merchant = row.merchant_name or _merchant_from_description(row.description) or "unknown_emi"
    normalized = normalize_text(merchant)
    normalized = re.sub(r"\b(?:emi|instalment|installment|no|cost|nocost|processing|fee|interest|reversal|gst)\b", "", normalized)
    normalized = re.sub(r"\b\d{1,2}\s*/\s*\d{1,2}\b", "", normalized)
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
    return normalized[:80] or "unknown_emi"


def _merchant_from_description(description: str) -> str | None:
    cleaned = re.sub(r"\b(?:emi|instalment|installment|no cost|nocost|processing fee|interest|reversal|gst)\b", "", description, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b\d{1,2}\s*/\s*\d{1,2}\b", "", cleaned)
    cleaned = re.sub(r"(?:INR|Rs\.?|₹)?\s*[\d,]+(?:\.\d{1,2})?", "", cleaned, flags=re.IGNORECASE)
    merchant = re.sub(r"[^A-Za-z0-9 &.-]+", " ", cleaned).strip()
    return merchant[:120].title() if merchant else None


def _apply_transaction_to_plan(plan: CreditCardEmiPlan, row: CreditCardTransaction) -> None:
    current, total = parse_emi_installment(row.description)
    if row.parsed_type in {"emi_transaction", "emi_principal"}:
        plan.monthly_emi_amount = row.amount
        plan.emi_start_month = plan.emi_start_month or date(row.transaction_date.year, row.transaction_date.month, 1)
        if current is not None:
            plan.completed_emi_count = max(plan.completed_emi_count or 0, current)
        if total is not None:
            plan.total_emi_count = total
            plan.pending_emi_count = max(total - (plan.completed_emi_count or current or 0), 0)
    if detect_no_cost_emi(row.description):
        plan.no_cost_claimed = True
    if not plan.merchant_name:
        plan.merchant_name = row.merchant_name or _merchant_from_description(row.description)
    plan.confidence_score = max(plan.confidence_score or 0.0, row.confidence_score)
def _upsert_emi_charge(session: Session, plan: CreditCardEmiPlan, row: CreditCardTransaction, charge_type: str) -> None:
    existing = session.scalar(
        select(CreditCardEmiCharge).where(
            CreditCardEmiCharge.emi_plan_id == plan.id,
            CreditCardEmiCharge.transaction_id == row.transaction_id,
            CreditCardEmiCharge.charge_type == charge_type,
        )
    )
    charge_month = date(row.transaction_date.year, row.transaction_date.month, 1)
    if existing:
        existing.amount = row.amount
        existing.charge_month = charge_month
        existing.confidence_score = row.confidence_score
        existing.manual_override = row.manual_override
        session.add(existing)
        return
    session.add(
        CreditCardEmiCharge(
            emi_plan_id=plan.id,
            transaction_id=row.transaction_id,
            charge_month=charge_month,
            charge_type=charge_type,
            amount=row.amount,
            confidence_score=row.confidence_score,
            manual_override=row.manual_override,
            notes=row.match_reason,
        )
    )


def _refresh_plan_rollup(session: Session, plan: CreditCardEmiPlan) -> None:
    charges = session.scalars(select(CreditCardEmiCharge).where(CreditCardEmiCharge.emi_plan_id == plan.id)).all()
    totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    for charge in charges:
        totals[charge.charge_type] += charge.amount

    processing_fee = totals["processing_fee"]
    gst_on_processing_fee = totals["gst_on_processing_fee"]
    interest = totals["interest"]
    interest_reversal = totals["interest_reversal"]
    gst_on_interest = totals["gst_on_interest"]
    credits = totals["cashback"] + totals["discount"] + totals["bank_offer_credit"] + totals["other_credit"]
    other_charges = totals["other_charge"]
    net_extra = interest + gst_on_interest + processing_fee + gst_on_processing_fee + other_charges - interest_reversal - credits

    plan.processing_fee_status = "processing_fee_found" if processing_fee > 0 else "processing_fee_unknown"
    if plan.no_cost_claimed:
        if plan.processing_fee_status == "processing_fee_unknown" or (interest > 0 and interest_reversal == 0 and credits == 0):
            plan.no_cost_verification_status = _manual_plan_status(plan) or "unknown"
        elif net_extra <= NOCOST_TOLERANCE:
            plan.no_cost_verification_status = _manual_plan_status(plan) or "truly_no_cost"
        elif interest_reversal > 0 or credits > 0:
            plan.no_cost_verification_status = _manual_plan_status(plan) or "partial_no_cost"
        else:
            plan.no_cost_verification_status = _manual_plan_status(plan) or "not_no_cost"

    if plan.pending_emi_count == 0 and plan.total_emi_count:
        plan.lifecycle_status = "completed"
    elif plan.total_emi_count and plan.monthly_emi_amount:
        plan.lifecycle_status = "active"
    elif plan.no_cost_verification_status == "unknown" or plan.processing_fee_status == "processing_fee_unknown":
        plan.lifecycle_status = "needs_review"
    else:
        plan.lifecycle_status = "unknown"
    session.add(plan)


def _manual_plan_status(plan: CreditCardEmiPlan) -> str | None:
    if not plan.notes:
        return None
    match = MANUAL_NOCOST_STATUS_PATTERN.search(plan.notes)
    if match and match.group("status").lower() in NOCOST_STATUSES:
        return match.group("status").lower()
    return None
