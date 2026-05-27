from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import CreditCardEmiCharge, CreditCardEmiPlan, CreditCardTransaction, Document, Transaction
from app.services.categorization.rules import normalize_text
from app.utils.amounts import MAX_REASONABLE_TRANSACTION_AMOUNT


TWOPLACES = Decimal("0.01")
ANALYSIS_MODES = {"normal", "emi_analysis", "upi_only", "mixed"}
UPI_SEPARATE_MODES = {"upi_only", "mixed"}
EXTRA_CHARGE_TYPES = {
    "gst_on_fee",
    "gst_on_interest",
    "gst_on_processing_fee",
    "gst_on_late_fee",
    "gst_on_finance_charge",
    "gst_unknown",
    "interest_charge",
    "emi_interest",
    "late_fee",
    "cash_withdrawal_charge",
    "emi_conversion",
    "processing_fee",
    "annual_fee",
    "over_limit_fee",
    "fee",
    "finance_charge",
    "other_charge",
}
VALID_CHARGE_TYPES = EXTRA_CHARGE_TYPES | {
    "purchase",
    "payment",
    "payment_or_credit",
    "refund",
    "emi_principal",
    "interest_reversal",
    "cashback_discount",
    "discount",
    "bank_offer_credit",
    "emi_transaction",
    "cash_withdrawal",
    "upi_card_spend",
    "other_credit",
}
DISCRETIONARY_CATEGORIES = {
    "Shopping",
    "Entertainment",
    "Restaurants",
    "Food Delivery",
    "Travel",
    "Miscellaneous",
}
UPI_TOKENS = {
    "upi",
    "bhim",
    "gpay",
    "google pay",
    "phonepe",
    "paytm",
    "amazon pay",
    "bharatpe",
    "cred upi",
    "rupay upi",
    "qr",
    "vpa",
    "@ybl",
    "@okaxis",
    "@oksbi",
    "@okhdfcbank",
    "@paytm",
    "@ibl",
    "@axl",
}
MANUAL_CHARGE_TYPE_PATTERN = re.compile(r"\bcc_charge_type\s*[:=]\s*(?P<charge_type>[a-z_]+)", re.IGNORECASE)
MANUAL_NOCOST_STATUS_PATTERN = re.compile(
    r"\bcc_no_cost_status\s*[:=]\s*(?P<status>[a-z_]+)",
    re.IGNORECASE,
)
INSTALLMENT_PATTERNS = [
    re.compile(r"\b(?:emi|instalment|installment)\s*(?:no\.?\s*)?(?P<current>\d{1,2})\s*/\s*(?P<total>\d{1,2})\b", re.IGNORECASE),
    re.compile(r"\b(?P<current>\d{1,2})\s*/\s*(?P<total>\d{1,2})\b.*\b(?:emi|instalment|installment)\b", re.IGNORECASE),
    re.compile(r"\b(?:emi|instalment|installment)\s*(?P<current>\d{1,2})\s*(?:of|out of)\s*(?P<total>\d{1,2})\b", re.IGNORECASE),
]
AMOUNT_PATTERN = re.compile(r"(?:INR|Rs\.?|₹)?\s*[\d,]+(?:\.\d{1,2})?", re.IGNORECASE)
RATE_PATTERN = re.compile(r"(?P<rate>\d{1,2}(?:\.\d{1,4})?)\s*%")
REFERENCE_PATTERN = re.compile(r"\b(?:ref|reference|loan|emi)\s*(?:no|number|id)?\s*[:#-]?\s*(?P<ref>[A-Z0-9-]{4,})\b", re.IGNORECASE)
NOCOST_STATUSES = {"truly_no_cost", "partial_no_cost", "not_no_cost", "unknown", "needs_review"}
NOCOST_TOLERANCE = Decimal("1.00")


@dataclass(frozen=True)
class CreditCardParseResult:
    parsed_type: str
    extracted_fields: dict[str, str | int | Decimal | bool | None]
    confidence_score: float
    match_reason: str
    risk_flags: list[str]


@dataclass(frozen=True)
class CreditCardInsight:
    transaction_id: int
    date: date
    description: str
    merchant_name: str | None
    amount: Decimal
    transaction_type: str
    charge_type: str
    extra_charge_amount: Decimal
    risk_flags: list[str]
    account_source: str | None
    statement_file: str | None
    category: str
    emi_current_installment: int | None = None
    emi_total_installments: int | None = None
    manual_override_applied: bool = False


@dataclass(frozen=True)
class CreditCardUpiInsight:
    transaction_id: int
    date: date
    receiver_name: str
    receiver_type: str
    amount: Decimal
    category: str
    description: str
    statement_file: str | None


@dataclass(frozen=True)
class CreditCardEmiInsight:
    transaction_id: int
    date: date
    description: str
    merchant_name: str | None
    amount: Decimal
    current_installment: int | None
    total_installments: int | None
    pending_installments: int | None
    statement_file: str | None


@dataclass(frozen=True)
class CreditCardEmiScheduleEntry:
    description: str
    amount: Decimal | None
    original_transaction_date: date | None
    emi_start_date: date | None
    current_installment: int | None
    total_installments: int | None
    pending_installments: int | None
    merchant_name: str | None
    no_cost_claimed: bool
    interest_rate: Decimal | None
    principal_outstanding: Decimal | None
    processing_fee: Decimal | None
    emi_reference: str | None
    source_document_id: int
    statement_file: str


@dataclass(frozen=True)
class CreditCardEmiPlanInsight:
    plan_id: int
    card_id: int
    merchant_name: str | None
    original_transaction_amount: Decimal | None
    monthly_emi_amount: Decimal | None
    completed_emi_count: int | None
    total_emi_count: int | None
    pending_emi_count: int | None
    no_cost_claimed: bool
    no_cost_verification_status: str
    processing_fee_status: str
    lifecycle_status: str
    total_interest_charged: Decimal
    total_interest_reversed: Decimal
    total_gst_on_interest: Decimal
    total_processing_fee: Decimal
    total_gst_on_processing_fee: Decimal
    total_extra_cost: Decimal
    effective_extra_cost_percent: Decimal | None
    confidence_score: float
    notes: str | None


@dataclass(frozen=True)
class CreditCardEmiSummary:
    detected_emi_count: int
    total_emi_paid: Decimal
    pending_emi_count: int
    pending_emi_amount: Decimal
    total_emi_obligation: Decimal
    schedule_detected: bool
    schedule_entries_count: int


@dataclass(frozen=True)
class NoCostEmiSummary:
    interest_charged: Decimal
    interest_reversal: Decimal
    cashback_discount: Decimal
    gst_on_interest: Decimal
    processing_fee: Decimal
    gst_on_processing_fee: Decimal
    other_charges: Decimal
    other_credits: Decimal
    net_interest_paid: Decimal
    total_gst_paid: Decimal
    net_extra_cost: Decimal
    effective_extra_cost_percent: Decimal | None
    verification_status: str
    processing_fee_found: bool
    gst_on_processing_fee_found: bool
    needs_review: bool
    awaiting_more_statements: bool
    missing_data_flags: list[str]


@dataclass(frozen=True)
class CreditCardAnalysisResult:
    analysis_mode: str
    total_purchase_spend: Decimal
    total_extra_charges: Decimal
    total_interest: Decimal
    total_fees: Decimal
    total_payments_received: Decimal
    total_upi_spend: Decimal
    daily_upi_spend: list[dict[str, Decimal | date]]
    top_upi_receivers: list[dict[str, Decimal | int | str]]
    repeated_upi_payments: list[dict[str, Decimal | int | str]]
    upi_transfer_breakdown: list[dict[str, Decimal | str]]
    small_frequent_upi_payments: list[dict[str, Decimal | int | str]]
    monthly_spend: list[dict[str, Decimal | str]]
    extra_charge_breakdown: list[dict[str, Decimal | str]]
    risky_patterns: list[str]
    review_warnings: list[str]
    classified_transactions: list[CreditCardInsight]
    flagged_transactions: list[CreditCardInsight]
    upi_transactions: list[CreditCardUpiInsight]
    emi_transactions: list[CreditCardEmiInsight]
    emi_schedule: list[CreditCardEmiScheduleEntry]
    emi_plans: list[CreditCardEmiPlanInsight]
    emi_summary: CreditCardEmiSummary
    no_cost_emi_summary: NoCostEmiSummary


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def _contains_any(text: str, patterns: list[str]) -> bool:
    return any(pattern in text for pattern in patterns)


def normalize_analysis_mode(value: str | None) -> str:
    normalized = normalize_text(value).replace(" ", "_").replace("-", "_")
    return normalized if normalized in ANALYSIS_MODES else "normal"


def _is_upi_like(description: str, payment_mode: str | None = None) -> bool:
    normalized = normalize_text(description)
    return payment_mode == "UPI" or any(token in normalized for token in UPI_TOKENS)


def _is_emi_like(description: str) -> bool:
    normalized = normalize_text(description)
    return bool(
        re.search(r"\bemi\b|\binstalment\b|\binstallment\b", normalized)
        or _contains_any(
            normalized,
            [
                "loan on card",
                "smart emi",
                "merchant emi",
                "no cost",
                "nocost",
                "balance conversion",
                "converted to emi",
                "transaction converted",
            ],
        )
    )


def parse_emi_installment(description: str) -> tuple[int | None, int | None]:
    if not _is_emi_like(description):
        return None, None
    for pattern in INSTALLMENT_PATTERNS:
        match = pattern.search(description)
        if not match:
            continue
        current = int(match.group("current"))
        total = int(match.group("total"))
        if 1 <= current <= total <= 120:
            return current, total
    return None, None


def extract_emi_sequence(description: str) -> tuple[int | None, int | None]:
    return parse_emi_installment(description)


def detect_no_cost_emi(description: str) -> bool:
    normalized = normalize_text(description)
    return _contains_any(normalized, ["no cost emi", "no-cost emi", "nocost emi", "no cost", "nocost"])


def detect_processing_fee(description: str) -> bool:
    normalized = normalize_text(description)
    return _contains_any(normalized, ["processing fee", "processing charge", "proc fee", "emi processing"])


def detect_interest_reversal(description: str) -> bool:
    normalized = normalize_text(description)
    return _contains_any(
        normalized,
        ["interest reversal", "finance charge reversal", "interest refund", "interest credit"],
    )


def detect_gst_parent_charge(description: str) -> str | None:
    normalized = normalize_text(description)
    if not _contains_any(normalized, ["gst", "igst", "cgst", "sgst"]):
        return None
    if _contains_any(normalized, ["processing", "proc fee", "conversion fee"]):
        return "processing_fee"
    if _contains_any(normalized, ["finance charge"]):
        return "finance_charge"
    if _contains_any(normalized, ["interest", "finance"]):
        return "interest"
    if _contains_any(normalized, ["late"]):
        return "late_fee"
    if _contains_any(normalized, ["fee", "charge", "membership", "annual"]):
        return "fee"
    return "unknown"


def detect_upi_credit_card_transaction(description: str, payment_mode: str | None = None) -> bool:
    return _is_upi_like(description, payment_mode)


def extract_upi_receiver(description: str, merchant_name: str | None = None) -> str:
    if merchant_name:
        return merchant_name
    tokens = [
        token.strip(" -/")
        for token in re.split(r"[/|:-]+", description)
        if token.strip(" -/")
    ]
    stopwords = {
        "upi",
        "rupay upi",
        "rupay",
        "bhim",
        "gpay",
        "google pay",
        "phonepe",
        "paytm",
        "payment",
        "p2m",
        "p2a",
        "collect",
        "ref",
        "utr",
        "rrn",
        "txn",
        "debit",
        "credit",
        "vpa",
        "qr",
    }
    for token in tokens:
        normalized = normalize_text(token)
        if normalized and normalized not in stopwords and not normalized.isdigit() and "@" not in normalized:
            return token.title()
    handle_match = re.search(r"[\w.-]+@[\w.-]+", description)
    if handle_match:
        return handle_match.group(0)
    return normalize_text(description)[:60] or "Unknown"


def classify_upi_receiver(description: str, receiver_name: str, category: str | None = None) -> str:
    normalized = normalize_text(f"{description} {receiver_name} {category or ''}")
    person_hints = {"family", "personal", "friend", "mom", "dad", "wife", "husband", "brother", "sister", "rent"}
    merchant_hints = {"p2m", "merchant", "store", "shop", "restaurant", "food", "grocery", "fuel", "bill", "subscription", "order", "qr"}
    if any(token in normalized for token in person_hints):
        return "person_transfer"
    if any(token in normalized for token in merchant_hints):
        return "merchant_spend"
    return "unknown"


def detect_emi_transaction(description: str, amount: Decimal | int | float | str | None = None) -> CreditCardParseResult:
    normalized = normalize_text(description)
    current, total = parse_emi_installment(description)
    no_cost = detect_no_cost_emi(description)
    if not _is_emi_like(description):
        return CreditCardParseResult("unknown", {}, 0.0, "No EMI pattern detected.", [])

    parsed_type = "emi_transaction"
    match_reason = "EMI keyword detected."
    if "principal" in normalized:
        parsed_type = "emi_principal"
        match_reason = "EMI principal component detected."
    elif _contains_any(normalized, ["interest", "finance"]) and not detect_interest_reversal(description):
        parsed_type = "emi_interest"
        match_reason = "EMI interest component detected."

    risk_flags = []
    if current is not None and total is not None:
        risk_flags.append(f"EMI installment detected ({current}/{total}).")
    else:
        risk_flags.append("EMI transaction detected; installment count needs review.")

    return CreditCardParseResult(
        parsed_type=parsed_type,
        extracted_fields={
            "current_installment": current,
            "total_installments": total,
            "pending_installments": max(total - current, 0) if current is not None and total is not None else None,
            "no_cost_claimed": no_cost,
        },
        confidence_score=0.9 if current and total else 0.7,
        match_reason=match_reason,
        risk_flags=risk_flags,
    )


def detect_credit_card_transaction_type(
    description: str,
    amount: Decimal | int | float | str | None = None,
    transaction_type: str = "debit",
    category: str | None = None,
    payment_mode: str | None = None,
) -> CreditCardParseResult:
    parsed_type, risk_flags = classify_credit_card_transaction(
        description=description,
        transaction_type=transaction_type,
        category=category,
        payment_mode=payment_mode,
    )
    current, total = parse_emi_installment(description)
    return CreditCardParseResult(
        parsed_type=parsed_type,
        extracted_fields={
            "current_installment": current,
            "total_installments": total,
            "pending_installments": max(total - current, 0) if current is not None and total is not None else None,
            "no_cost_claimed": detect_no_cost_emi(description),
            "upi_receiver": extract_upi_receiver(description) if detect_upi_credit_card_transaction(description, payment_mode) else None,
            "gst_parent_charge": detect_gst_parent_charge(description),
        },
        confidence_score=0.85 if parsed_type != "purchase" else 0.6,
        match_reason=f"Classified as {parsed_type}.",
        risk_flags=risk_flags,
    )


def is_credit_card_transaction(transaction: Transaction, document_type: str | None, include_card_like: bool = False) -> bool:
    normalized_description = normalize_text(transaction.raw_description)
    normalized_source = normalize_text(transaction.account_source)
    if document_type == "credit_card_statement":
        return True
    if "credit card" in normalized_description or "credit card" in normalized_source:
        return True
    if include_card_like and transaction.payment_mode == "CARD" and transaction.category != "Credit Card Payment":
        return True
    return False


def classify_credit_card_transaction(
    description: str,
    transaction_type: str,
    category: str | None = None,
    payment_mode: str | None = None,
) -> tuple[str, list[str]]:
    normalized = normalize_text(description)
    risk_flags: list[str] = []

    if detect_interest_reversal(description):
        return "interest_reversal", risk_flags
    if _contains_any(normalized, ["cashback", "cash back"]) and (
        "emi" in normalized or transaction_type == "credit"
    ):
        return "cashback_discount", risk_flags
    if _contains_any(normalized, ["merchant discount", "instant discount", "no cost emi discount", "no-cost emi discount"]):
        return "discount", risk_flags
    if _contains_any(normalized, ["bank offer credit", "offer credit"]) and transaction_type == "credit":
        return "bank_offer_credit", risk_flags
    if _contains_any(normalized, ["refund", "reversal", "chargeback"]):
        return "refund", risk_flags
    if _contains_any(normalized, ["payment received", "payment credit", "credit card payment", "autopay received"]):
        return "payment", risk_flags

    gst_parent = detect_gst_parent_charge(description)
    if gst_parent == "processing_fee":
        return "gst_on_processing_fee", risk_flags
    if gst_parent == "interest":
        return "gst_on_interest", risk_flags
    if gst_parent == "finance_charge":
        return "gst_on_finance_charge", risk_flags
    if gst_parent == "late_fee":
        return "gst_on_late_fee", risk_flags
    if gst_parent == "fee":
        return "gst_on_fee", risk_flags
    if gst_parent == "unknown":
        risk_flags.append("GST row detected but parent charge is unknown.")
        return "gst_unknown", risk_flags

    if _contains_any(normalized, ["late fee", "late payment fee"]):
        risk_flags.append("Late payment fee detected.")
        return "late_fee", risk_flags
    if _contains_any(normalized, ["interest"]) and _is_emi_like(description) and transaction_type == "debit":
        risk_flags.append("EMI interest component detected.")
        return "emi_interest", risk_flags
    if _contains_any(normalized, ["finance charge", "interest charged", "revolving interest", "interest charge"]):
        risk_flags.append("Interest charge detected.")
        return "interest_charge", risk_flags
    if _contains_any(normalized, ["cash advance fee", "cash withdrawal fee", "cash withdrawal charge"]):
        risk_flags.append("Cash withdrawal charge detected.")
        return "cash_withdrawal_charge", risk_flags
    if _contains_any(normalized, ["cash advance", "cash withdrawal"]) and transaction_type == "debit":
        risk_flags.append("Cash withdrawal detected on credit card.")
        return "cash_withdrawal", risk_flags
    if _contains_any(normalized, ["over limit fee", "overlimit fee"]):
        risk_flags.append("Over-limit fee detected.")
        return "over_limit_fee", risk_flags
    if "principal" in normalized and _is_emi_like(description) and transaction_type == "debit":
        return "emi_principal", risk_flags
    if _contains_any(normalized, ["emi conversion", "convert to emi", "merchant emi"]):
        risk_flags.append("EMI conversion detected.")
        return "emi_conversion", risk_flags
    if detect_processing_fee(description):
        return "processing_fee", risk_flags
    if _is_emi_like(normalized) and transaction_type == "debit":
        current, total = parse_emi_installment(description)
        if current is None or total is None:
            risk_flags.append("EMI transaction detected; installment count needs review.")
        return "emi_transaction", risk_flags
    if _contains_any(normalized, ["annual fee", "membership fee", "joining fee", "renewal fee"]):
        return "annual_fee", risk_flags
    if category == "Credit Card Payment":
        return "payment", risk_flags
    if re.search(r"\b(?:fee|charge)\b", normalized) and transaction_type == "debit":
        return "fee", risk_flags
    if transaction_type == "credit":
        return "payment_or_credit", risk_flags
    return "purchase", risk_flags


def _manual_charge_type_override(transaction: Transaction) -> str | None:
    if not transaction.notes:
        return None
    match = MANUAL_CHARGE_TYPE_PATTERN.search(transaction.notes)
    if not match:
        return None
    charge_type = match.group("charge_type").lower()
    return charge_type if charge_type in VALID_CHARGE_TYPES else None


def _receiver_from_upi(transaction: Transaction) -> str:
    return extract_upi_receiver(transaction.raw_description, transaction.merchant_name)


def _amount_from_text(value: str) -> Decimal | None:
    matches = AMOUNT_PATTERN.findall(value)
    if not matches:
        return None
    candidate = matches[-1]
    cleaned = re.sub(r"[^0-9.]", "", candidate)
    try:
        return _quantize(Decimal(cleaned))
    except (InvalidOperation, ValueError):
        return None


def _first_amount_from_text(value: str) -> Decimal | None:
    matches = AMOUNT_PATTERN.findall(value)
    if not matches:
        return None
    cleaned = re.sub(r"[^0-9.]", "", matches[0])
    try:
        return _quantize(Decimal(cleaned))
    except (InvalidOperation, ValueError):
        return None


def _amount_after_keyword(value: str, keywords: list[str]) -> Decimal | None:
    normalized_value = value.lower()
    for keyword in keywords:
        index = normalized_value.find(keyword)
        if index < 0:
            continue
        amount = _first_amount_from_text(value[index + len(keyword) :])
        if amount is not None:
            return amount
    return None


def _interest_rate_from_text(value: str) -> Decimal | None:
    match = RATE_PATTERN.search(value)
    if not match:
        return None
    try:
        return Decimal(match.group("rate"))
    except InvalidOperation:
        return None


def _reference_from_text(value: str) -> str | None:
    match = REFERENCE_PATTERN.search(value)
    return match.group("ref") if match else None


def _date_after_keyword(value: str, keywords: list[str]) -> date | None:
    for keyword in keywords:
        match = re.search(
            rf"{re.escape(keyword)}\s*[:#-]?\s*(?P<date>\d{{1,2}}[/-]\d{{1,2}}[/-]\d{{2,4}}|\d{{4}}[/-]\d{{1,2}}[/-]\d{{1,2}})",
            value,
            flags=re.IGNORECASE,
        )
        if not match:
            continue
        raw = match.group("date")
        for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y", "%Y-%m-%d", "%Y/%m/%d"):
            try:
                return datetime.strptime(raw, fmt).date()
            except ValueError:
                continue
    return None


def _schedule_merchant_from_text(value: str) -> str | None:
    cleaned = re.sub(r"\b(?:emi|instalment|installment)\s*\d{1,2}\s*/\s*\d{1,2}\b", "", value, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:no cost|no-cost|nocost|schedule|summary|pending|completed)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(?:INR|Rs\.?|₹)?\s*[\d,]+(?:\.\d{1,2})?", "", cleaned, flags=re.IGNORECASE)
    merchant = re.sub(r"[^A-Za-z0-9 &.-]+", " ", cleaned).strip()
    return merchant[:120].title() if merchant else None


def parse_emi_schedule_from_text(raw_text: str | None, source_document_id: int, statement_file: str) -> list[CreditCardEmiScheduleEntry]:
    if not raw_text:
        return []
    entries: list[CreditCardEmiScheduleEntry] = []
    for line in raw_text.splitlines():
        cleaned = re.sub(r"\s+", " ", line).strip()
        if not cleaned or not _is_emi_like(cleaned):
            continue
        current, total = parse_emi_installment(cleaned)
        if current is None and total is None:
            continue
        pending = max(total - current, 0) if current is not None and total is not None else None
        entries.append(
            CreditCardEmiScheduleEntry(
                description=cleaned[:240],
                amount=_amount_from_text(cleaned),
                original_transaction_date=_date_after_keyword(cleaned, ["original transaction date", "transaction date", "txn date"]),
                emi_start_date=_date_after_keyword(cleaned, ["emi start date", "start date", "start month"]),
                current_installment=current,
                total_installments=total,
                pending_installments=pending,
                merchant_name=_schedule_merchant_from_text(cleaned),
                no_cost_claimed=detect_no_cost_emi(cleaned),
                interest_rate=_interest_rate_from_text(cleaned),
                principal_outstanding=_amount_after_keyword(cleaned, ["principal outstanding", "outstanding principal", "outstanding"]),
                processing_fee=_amount_after_keyword(cleaned, ["processing fee", "proc fee", "processing charge"]),
                emi_reference=_reference_from_text(cleaned),
                source_document_id=source_document_id,
                statement_file=statement_file,
            )
        )
    return entries


def _iter_credit_card_rows(
    session: Session,
    start_date: date | None = None,
    end_date: date | None = None,
    account_source: str | None = None,
    include_card_like: bool = False,
    card_id: int | None = None,
) -> list[tuple[Transaction, str | None, str | None]]:
    statement = (
        select(Transaction, Document.document_type, Document.filename)
        .join(Document, Transaction.source_document_id == Document.id, isouter=True)
        .where(Transaction.amount <= MAX_REASONABLE_TRANSACTION_AMOUNT)
        .order_by(Transaction.date.asc(), Transaction.id.asc())
    )
    if start_date:
        statement = statement.where(Transaction.date >= start_date)
    if end_date:
        statement = statement.where(Transaction.date <= end_date)
    if account_source:
        statement = statement.where(
            (Transaction.account_source == account_source)
            | (Document.filename == account_source)
        )
    if card_id is not None:
        statement = statement.join(CreditCardTransaction, CreditCardTransaction.transaction_id == Transaction.id).where(
            CreditCardTransaction.card_id == card_id
        )

    rows = session.execute(statement).all()
    return [
        (transaction, document_type, filename)
        for transaction, document_type, filename in rows
        if is_credit_card_transaction(transaction, document_type, include_card_like=include_card_like)
        and not transaction.is_excluded
    ]


def list_credit_card_sources(session: Session, include_card_like: bool = False) -> list[str]:
    sources = {
        transaction.account_source or filename or f"Document {transaction.source_document_id}"
        for transaction, document_type, filename in _iter_credit_card_rows(
            session=session,
            include_card_like=include_card_like,
        )
    }
    return sorted(source for source in sources if source)


def analyze_credit_card_transactions(
    session: Session,
    start_date: date | None = None,
    end_date: date | None = None,
    account_source: str | None = None,
    include_card_like: bool = False,
    analysis_mode: str = "normal",
    card_id: int | None = None,
) -> CreditCardAnalysisResult:
    analysis_mode = normalize_analysis_mode(analysis_mode)
    insights: list[CreditCardInsight] = []
    upi_insights: list[CreditCardUpiInsight] = []
    emi_insights: list[CreditCardEmiInsight] = []
    monthly_spend_totals: dict[str, Decimal] = {}
    daily_upi_totals: dict[date, Decimal] = {}
    extra_charge_totals: dict[str, Decimal] = {}
    total_purchase_spend = Decimal("0.00")
    total_extra_charges = Decimal("0.00")
    total_interest = Decimal("0.00")
    total_fees = Decimal("0.00")
    total_payments_received = Decimal("0.00")
    total_upi_spend = Decimal("0.00")
    review_warnings: list[str] = []

    rows = _iter_credit_card_rows(
        session=session,
        start_date=start_date,
        end_date=end_date,
        account_source=account_source,
        include_card_like=include_card_like,
        card_id=card_id,
    )

    source_document_ids = {transaction.source_document_id for transaction, _, _ in rows if transaction.source_document_id}
    documents = {
        document.id: document
        for document in session.scalars(select(Document).where(Document.id.in_(source_document_ids))).all()
    } if source_document_ids else {}
    emi_schedule = [
        entry
        for document in documents.values()
        for entry in parse_emi_schedule_from_text(
            raw_text=document.raw_text,
            source_document_id=document.id,
            statement_file=document.filename,
        )
    ]

    for transaction, _, filename in rows:
        charge_type, risk_flags = classify_credit_card_transaction(
            description=transaction.raw_description,
            transaction_type=transaction.transaction_type,
            category=transaction.category,
            payment_mode=transaction.payment_mode,
        )
        manual_override = _manual_charge_type_override(transaction)
        if manual_override:
            charge_type = manual_override
            risk_flags = [*risk_flags, "Manual credit-card charge type override applied."]

        amount = _quantize(transaction.amount)
        current_installment, total_installments = parse_emi_installment(transaction.raw_description)
        is_upi_transaction = _is_upi_like(transaction.raw_description, transaction.payment_mode)
        separate_upi = analysis_mode in UPI_SEPARATE_MODES and is_upi_transaction
        if separate_upi and charge_type == "purchase":
            charge_type = "upi_card_spend"
        extra_charge_amount = amount if charge_type in EXTRA_CHARGE_TYPES else Decimal("0.00")

        insight = CreditCardInsight(
            transaction_id=transaction.id,
            date=transaction.date,
            description=transaction.raw_description,
            merchant_name=transaction.merchant_name,
            amount=amount,
            transaction_type=transaction.transaction_type,
            charge_type=charge_type,
            extra_charge_amount=extra_charge_amount,
            risk_flags=risk_flags,
            account_source=transaction.account_source,
            statement_file=filename,
            category=transaction.category,
            emi_current_installment=current_installment,
            emi_total_installments=total_installments,
            manual_override_applied=bool(manual_override),
        )
        insights.append(insight)

        if separate_upi and transaction.transaction_type == "debit":
            receiver_name = _receiver_from_upi(transaction)
            upi_insight = CreditCardUpiInsight(
                transaction_id=transaction.id,
                date=transaction.date,
                receiver_name=receiver_name,
                receiver_type=classify_upi_receiver(transaction.raw_description, receiver_name, transaction.category),
                amount=amount,
                category=transaction.category,
                description=transaction.raw_description,
                statement_file=filename,
            )
            upi_insights.append(upi_insight)
            daily_upi_totals[transaction.date] = daily_upi_totals.get(transaction.date, Decimal("0.00")) + amount
            total_upi_spend += amount

        if charge_type in {"emi_transaction", "emi_principal"}:
            pending_installments = (
                max(total_installments - current_installment, 0)
                if current_installment is not None and total_installments is not None
                else None
            )
            emi_insights.append(
                CreditCardEmiInsight(
                    transaction_id=transaction.id,
                    date=transaction.date,
                    description=transaction.raw_description,
                    merchant_name=transaction.merchant_name,
                    amount=amount,
                    current_installment=current_installment,
                    total_installments=total_installments,
                    pending_installments=pending_installments,
                    statement_file=filename,
                )
            )

        period = transaction.date.strftime("%Y-%m")
        if charge_type == "purchase" and transaction.transaction_type == "debit" and analysis_mode != "upi_only":
            monthly_spend_totals[period] = monthly_spend_totals.get(period, Decimal("0.00")) + amount
            total_purchase_spend += amount
        if charge_type in EXTRA_CHARGE_TYPES:
            extra_charge_totals[charge_type] = extra_charge_totals.get(charge_type, Decimal("0.00")) + amount
            total_extra_charges += amount
        if charge_type in {"interest_charge", "emi_interest"}:
            total_interest += amount
        if charge_type in {
            "late_fee",
            "cash_withdrawal_charge",
            "emi_conversion",
            "processing_fee",
            "annual_fee",
            "over_limit_fee",
            "fee",
            "gst_on_fee",
            "gst_on_interest",
            "gst_on_processing_fee",
            "gst_on_late_fee",
            "gst_on_finance_charge",
            "gst_unknown",
            "emi_interest",
        }:
            total_fees += amount
        if charge_type in {"payment", "payment_or_credit"} and transaction.transaction_type == "credit":
            total_payments_received += amount

    monthly_fee_months = {
        insight.date.strftime("%Y-%m")
        for insight in insights
        if insight.charge_type in {"late_fee", "interest_charge"}
    }
    risky_patterns: list[str] = []
    if any(insight.charge_type == "late_fee" for insight in insights):
        risky_patterns.append("Late fee detected on at least one statement.")
    if any(insight.charge_type == "interest_charge" for insight in insights):
        risky_patterns.append("Interest or finance charges detected.")
    if any(insight.charge_type in {"cash_withdrawal", "cash_withdrawal_charge"} for insight in insights):
        risky_patterns.append("Credit card cash withdrawal usage detected.")
    if any(insight.charge_type == "over_limit_fee" for insight in insights):
        risky_patterns.append("Over-limit fee detected.")
    if any(insight.charge_type == "emi_conversion" for insight in insights):
        risky_patterns.append("EMI conversion or conversion fee detected.")
    if emi_schedule:
        risky_patterns.append("Credit card EMI schedule rows were parsed from statement text.")
    if len(monthly_fee_months) >= 2:
        risky_patterns.append("Possible minimum-due or revolving balance behavior inferred from charges across multiple months.")

    discretionary_purchases = [
        insight
        for insight in insights
        if insight.charge_type == "purchase" and insight.category in DISCRETIONARY_CATEGORIES
    ]
    if discretionary_purchases:
        median_like_threshold = sorted(insight.amount for insight in discretionary_purchases)[len(discretionary_purchases) // 2]
        high_spend_threshold = max(Decimal("5000.00"), _quantize(median_like_threshold * Decimal("2.00")))
        high_discretionary_count = sum(1 for insight in discretionary_purchases if insight.amount >= high_spend_threshold)
        if high_discretionary_count >= 2:
            risky_patterns.append("Repeated high discretionary credit card spends detected.")

    flagged_transactions = [insight for insight in insights if insight.risk_flags]
    emi_summary = _build_emi_summary(emi_insights, emi_schedule)
    emi_plans = _load_emi_plan_insights(session, card_id=card_id)
    no_cost_emi_summary = _build_no_cost_emi_summary(insights, emi_summary, emi_plans)
    review_warnings.extend(no_cost_emi_summary.missing_data_flags)
    if analysis_mode == "upi_only" and not upi_insights:
        review_warnings.append("Statement is tagged UPI-only, but no UPI transactions were detected.")
    if emi_summary.pending_emi_count:
        review_warnings.append("Pending EMI installments remain; future statements may be needed for complete cost analysis.")

    return CreditCardAnalysisResult(
        analysis_mode=analysis_mode,
        total_purchase_spend=_quantize(total_purchase_spend),
        total_extra_charges=_quantize(total_extra_charges),
        total_interest=_quantize(total_interest),
        total_fees=_quantize(total_fees),
        total_payments_received=_quantize(total_payments_received),
        total_upi_spend=_quantize(total_upi_spend),
        daily_upi_spend=[
            {"date": spend_date, "amount": _quantize(amount)}
            for spend_date, amount in sorted(daily_upi_totals.items())
        ],
        top_upi_receivers=_build_top_upi_receivers(upi_insights),
        repeated_upi_payments=_build_repeated_upi_payments(upi_insights),
        upi_transfer_breakdown=_build_upi_transfer_breakdown(upi_insights),
        small_frequent_upi_payments=_build_small_frequent_upi_payments(upi_insights),
        monthly_spend=[
            {"period": period, "spend": _quantize(amount)}
            for period, amount in sorted(monthly_spend_totals.items())
        ],
        extra_charge_breakdown=[
            {"charge_type": charge_type, "amount": _quantize(amount)}
            for charge_type, amount in sorted(extra_charge_totals.items())
        ],
        risky_patterns=risky_patterns,
        review_warnings=review_warnings,
        classified_transactions=insights,
        flagged_transactions=flagged_transactions,
        upi_transactions=upi_insights,
        emi_transactions=emi_insights,
        emi_schedule=emi_schedule,
        emi_plans=emi_plans,
        emi_summary=emi_summary,
        no_cost_emi_summary=no_cost_emi_summary,
    )


def _build_emi_summary(
    emi_insights: list[CreditCardEmiInsight],
    emi_schedule: list[CreditCardEmiScheduleEntry],
) -> CreditCardEmiSummary:
    total_emi_paid = _quantize(sum((item.amount for item in emi_insights), start=Decimal("0.00")))
    pending_count = 0
    pending_amount = Decimal("0.00")

    latest_by_description: dict[str, CreditCardEmiInsight] = {}
    for insight in emi_insights:
        key = normalize_text(re.sub(r"\b\d{1,2}\s*/\s*\d{1,2}\b", "", insight.description))[:120]
        current_best = latest_by_description.get(key)
        if current_best is None or insight.date >= current_best.date:
            latest_by_description[key] = insight

    for insight in latest_by_description.values():
        if insight.pending_installments is None or insight.pending_installments <= 0:
            continue
        pending_count += insight.pending_installments
        pending_amount += insight.amount * Decimal(insight.pending_installments)

    if not pending_count and emi_schedule:
        for entry in emi_schedule:
            if entry.pending_installments is None or entry.pending_installments <= 0 or entry.amount is None:
                continue
            pending_count += entry.pending_installments
            pending_amount += entry.amount * Decimal(entry.pending_installments)

    pending_amount = _quantize(pending_amount)
    return CreditCardEmiSummary(
        detected_emi_count=len(emi_insights),
        total_emi_paid=total_emi_paid,
        pending_emi_count=pending_count,
        pending_emi_amount=pending_amount,
        total_emi_obligation=_quantize(total_emi_paid + pending_amount),
        schedule_detected=bool(emi_schedule),
        schedule_entries_count=len(emi_schedule),
    )


def _sum_charge(insights: list[CreditCardInsight], charge_types: set[str]) -> Decimal:
    return _quantize(
        sum((insight.amount for insight in insights if insight.charge_type in charge_types), start=Decimal("0.00"))
    )


def _manual_no_cost_status(insights: list[CreditCardInsight]) -> str | None:
    for insight in insights:
        transaction = insight.description
        match = MANUAL_NOCOST_STATUS_PATTERN.search(transaction)
        if match and match.group("status").lower() in NOCOST_STATUSES:
            return match.group("status").lower()
    return None


def _build_top_upi_receivers(upi_insights: list[CreditCardUpiInsight]) -> list[dict[str, Decimal | int | str]]:
    totals: dict[str, dict[str, Decimal | int | str]] = {}
    for insight in upi_insights:
        row = totals.setdefault(
            insight.receiver_name,
            {"receiver": insight.receiver_name, "receiver_type": insight.receiver_type, "amount": Decimal("0.00"), "count": 0},
        )
        row["amount"] = _quantize(row["amount"] + insight.amount)  # type: ignore[operator]
        row["count"] = int(row["count"]) + 1
    return sorted(totals.values(), key=lambda item: item["amount"], reverse=True)[:10]  # type: ignore[arg-type]


def _build_repeated_upi_payments(upi_insights: list[CreditCardUpiInsight]) -> list[dict[str, Decimal | int | str]]:
    repeated = []
    for row in _build_top_upi_receivers(upi_insights):
        if int(row["count"]) >= 2:
            repeated.append(row)
    return repeated


def _build_upi_transfer_breakdown(upi_insights: list[CreditCardUpiInsight]) -> list[dict[str, Decimal | str]]:
    totals: dict[str, Decimal] = {}
    for insight in upi_insights:
        totals[insight.receiver_type] = totals.get(insight.receiver_type, Decimal("0.00")) + insight.amount
    return [{"receiver_type": key, "amount": _quantize(value)} for key, value in sorted(totals.items())]


def _build_small_frequent_upi_payments(upi_insights: list[CreditCardUpiInsight]) -> list[dict[str, Decimal | int | str]]:
    grouped: dict[str, dict[str, Decimal | int | str]] = {}
    for insight in upi_insights:
        if insight.amount > Decimal("500.00"):
            continue
        row = grouped.setdefault(
            insight.receiver_name,
            {"receiver": insight.receiver_name, "amount": Decimal("0.00"), "count": 0},
        )
        row["amount"] = _quantize(row["amount"] + insight.amount)  # type: ignore[operator]
        row["count"] = int(row["count"]) + 1
    return sorted(
        [row for row in grouped.values() if int(row["count"]) >= 2],
        key=lambda item: (item["count"], item["amount"]),
        reverse=True,
    )


def _load_emi_plan_insights(session: Session, card_id: int | None = None) -> list[CreditCardEmiPlanInsight]:
    statement = select(CreditCardEmiPlan).order_by(CreditCardEmiPlan.updated_at.desc(), CreditCardEmiPlan.id.desc())
    if card_id is not None:
        statement = statement.where(CreditCardEmiPlan.card_id == card_id)
    plans = session.scalars(statement).all()
    insights: list[CreditCardEmiPlanInsight] = []
    for plan in plans:
        charges = session.scalars(
            select(CreditCardEmiCharge).where(CreditCardEmiCharge.emi_plan_id == plan.id)
        ).all()
        totals: dict[str, Decimal] = {}
        for charge in charges:
            totals[charge.charge_type] = totals.get(charge.charge_type, Decimal("0.00")) + charge.amount
        interest_charged = _quantize(totals.get("interest", Decimal("0.00")) + totals.get("emi_interest", Decimal("0.00")))
        interest_reversed = _quantize(totals.get("interest_reversal", Decimal("0.00")))
        gst_on_interest = _quantize(totals.get("gst_on_interest", Decimal("0.00")))
        processing_fee = _quantize(totals.get("processing_fee", Decimal("0.00")))
        gst_on_processing_fee = _quantize(totals.get("gst_on_processing_fee", Decimal("0.00")))
        other_charges = _quantize(totals.get("other_charge", Decimal("0.00")) + totals.get("late_fee", Decimal("0.00")) + totals.get("finance_charge", Decimal("0.00")))
        credits = _quantize(
            totals.get("cashback", Decimal("0.00"))
            + totals.get("cashback_discount", Decimal("0.00"))
            + totals.get("discount", Decimal("0.00"))
            + totals.get("bank_offer_credit", Decimal("0.00"))
            + totals.get("other_credit", Decimal("0.00"))
        )
        total_extra_cost = _quantize(
            interest_charged
            + gst_on_interest
            + processing_fee
            + gst_on_processing_fee
            + other_charges
            - interest_reversed
            - credits
        )
        effective_percent = None
        if plan.original_transaction_amount and plan.original_transaction_amount > 0:
            effective_percent = _quantize(total_extra_cost / plan.original_transaction_amount * Decimal("100"))
        insights.append(
            CreditCardEmiPlanInsight(
                plan_id=plan.id,
                card_id=plan.card_id,
                merchant_name=plan.merchant_name,
                original_transaction_amount=plan.original_transaction_amount,
                monthly_emi_amount=plan.monthly_emi_amount,
                completed_emi_count=plan.completed_emi_count,
                total_emi_count=plan.total_emi_count,
                pending_emi_count=plan.pending_emi_count,
                no_cost_claimed=plan.no_cost_claimed,
                no_cost_verification_status=plan.no_cost_verification_status,
                processing_fee_status=plan.processing_fee_status,
                lifecycle_status=plan.lifecycle_status,
                total_interest_charged=interest_charged,
                total_interest_reversed=interest_reversed,
                total_gst_on_interest=gst_on_interest,
                total_processing_fee=processing_fee,
                total_gst_on_processing_fee=gst_on_processing_fee,
                total_extra_cost=total_extra_cost,
                effective_extra_cost_percent=effective_percent,
                confidence_score=plan.confidence_score,
                notes=plan.notes,
            )
        )
    return insights


def _build_no_cost_emi_summary(
    insights: list[CreditCardInsight],
    emi_summary: CreditCardEmiSummary,
    emi_plans: list[CreditCardEmiPlanInsight] | None = None,
) -> NoCostEmiSummary:
    has_emi_context = bool(emi_summary.detected_emi_count or emi_summary.schedule_detected or emi_plans)
    has_no_cost_hint = any("no cost" in normalize_text(insight.description) or "no-cost" in normalize_text(insight.description) for insight in insights)
    emi_plans = emi_plans or []
    has_no_cost_hint = has_no_cost_hint or any(plan.no_cost_claimed for plan in emi_plans)

    interest_charged = _sum_charge(insights, {"interest_charge", "emi_interest"})
    interest_reversal = _sum_charge(insights, {"interest_reversal"})
    cashback_discount = _sum_charge(insights, {"cashback_discount", "discount", "bank_offer_credit"})
    gst_on_interest = _sum_charge(insights, {"gst_on_interest"})
    processing_fee = _sum_charge(insights, {"processing_fee", "emi_conversion"})
    gst_on_processing_fee = _sum_charge(insights, {"gst_on_processing_fee"})
    other_charges = _sum_charge(insights, {"late_fee", "finance_charge", "other_charge"})
    other_credits = _sum_charge(insights, {"other_credit"})

    processing_fee_found = any(insight.charge_type in {"processing_fee", "emi_conversion"} for insight in insights)
    gst_on_processing_fee_found = any(insight.charge_type == "gst_on_processing_fee" for insight in insights)
    if emi_plans:
        interest_charged = max(interest_charged, _quantize(sum((plan.total_interest_charged for plan in emi_plans), start=Decimal("0.00"))))
        interest_reversal = max(interest_reversal, _quantize(sum((plan.total_interest_reversed for plan in emi_plans), start=Decimal("0.00"))))
        gst_on_interest = max(gst_on_interest, _quantize(sum((plan.total_gst_on_interest for plan in emi_plans), start=Decimal("0.00"))))
        processing_fee = max(processing_fee, _quantize(sum((plan.total_processing_fee for plan in emi_plans), start=Decimal("0.00"))))
        gst_on_processing_fee = max(
            gst_on_processing_fee,
            _quantize(sum((plan.total_gst_on_processing_fee for plan in emi_plans), start=Decimal("0.00"))),
        )
        processing_fee_found = processing_fee_found or any(plan.processing_fee_status == "processing_fee_found" for plan in emi_plans)
        gst_on_processing_fee_found = gst_on_processing_fee_found or gst_on_processing_fee > Decimal("0.00")
    missing_data_flags: list[str] = []

    if has_emi_context or has_no_cost_hint:
        if not processing_fee_found:
            missing_data_flags.append("Processing fee not found yet. Upload first EMI statement or previous statement to complete analysis.")
        if not gst_on_processing_fee_found:
            missing_data_flags.append("GST on processing fee not found; needs statement review.")
        if has_no_cost_hint and interest_charged == Decimal("0.00"):
            missing_data_flags.append("Interest charge row not found for no-cost EMI verification.")
        if has_no_cost_hint and interest_charged > 0 and (interest_reversal + cashback_discount) == Decimal("0.00"):
            missing_data_flags.append("Interest reversal, cashback, or discount row not found for no-cost EMI verification.")

    net_interest_paid = _quantize(interest_charged - interest_reversal)
    total_gst_paid = _quantize(gst_on_interest + gst_on_processing_fee)
    net_extra_cost = _quantize(
        interest_charged
        + processing_fee
        + gst_on_interest
        + gst_on_processing_fee
        + other_charges
        - interest_reversal
        - cashback_discount
        - other_credits
    )
    needs_review = bool(missing_data_flags)
    effective_percent = None
    original_amounts = [plan.original_transaction_amount for plan in emi_plans if plan.original_transaction_amount and plan.original_transaction_amount > 0]
    if original_amounts:
        effective_percent = _quantize(net_extra_cost / sum(original_amounts, start=Decimal("0.00")) * Decimal("100"))

    verification_status = "unknown"
    if needs_review:
        verification_status = "unknown"
    elif net_extra_cost <= NOCOST_TOLERANCE and has_no_cost_hint:
        verification_status = "truly_no_cost"
    elif (interest_reversal > Decimal("0.00") or cashback_discount > Decimal("0.00")) and net_extra_cost > NOCOST_TOLERANCE:
        verification_status = "partial_no_cost"
    elif has_no_cost_hint and net_extra_cost > NOCOST_TOLERANCE:
        verification_status = "not_no_cost"

    manual_status = _manual_no_cost_status(insights)
    if manual_status:
        verification_status = manual_status
        needs_review = False

    return NoCostEmiSummary(
        interest_charged=interest_charged,
        interest_reversal=interest_reversal,
        cashback_discount=cashback_discount,
        gst_on_interest=gst_on_interest,
        processing_fee=processing_fee,
        gst_on_processing_fee=gst_on_processing_fee,
        other_charges=other_charges,
        other_credits=other_credits,
        net_interest_paid=net_interest_paid,
        total_gst_paid=total_gst_paid,
        net_extra_cost=net_extra_cost,
        effective_extra_cost_percent=effective_percent,
        verification_status=verification_status,
        processing_fee_found=processing_fee_found,
        gst_on_processing_fee_found=gst_on_processing_fee_found,
        needs_review=needs_review,
        awaiting_more_statements=needs_review or emi_summary.pending_emi_count > 0,
        missing_data_flags=missing_data_flags,
    )
