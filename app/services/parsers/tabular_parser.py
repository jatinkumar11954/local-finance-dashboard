from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from app.services.categorization.rules import categorize_transaction, extract_merchant_name, infer_payment_mode
from app.services.parsers.models import ParsedDocument, ParsedTransactionRow
from app.utils.amounts import is_reasonable_transaction_amount


HEADER_ALIASES = {
    "date": [
        "date",
        "txn date",
        "transaction date",
        "value date",
        "posting date",
        "post date",
    ],
    "description": [
        "description",
        "narration",
        "particulars",
        "particular",
        "details",
        "remarks",
        "transaction remarks",
        "transaction details",
        "txn particulars",
    ],
    "amount": [
        "amount",
        "txn amount",
        "transaction amount",
        "billing amount",
        "amount inr",
        "amount in",
        "amount in rs",
        "amount in rupees",
        "withdrawal/deposit amount",
    ],
    "debit": [
        "debit",
        "withdrawal",
        "withdrawal amount",
        "debit amount",
        "dr",
        "dr amount",
        "paid out",
    ],
    "credit": [
        "credit",
        "deposit",
        "credit amount",
        "cr",
        "cr amount",
        "paid in",
    ],
    "type": [
        "type",
        "transaction type",
        "dr/cr",
        "debit/credit",
        "cr/dr",
    ],
    "balance": [
        "balance",
        "running balance",
        "closing balance",
        "available balance",
        "balance amount",
    ],
    "account_source": [
        "account",
        "account source",
        "source",
        "bank account",
        "account name",
    ],
    "opening_outstanding": [
        "opening outstanding",
        "opening balance",
        "opening principal",
        "opening loan balance",
    ],
    "closing_outstanding": [
        "closing outstanding",
        "closing balance",
        "closing principal",
        "closing loan balance",
        "outstanding balance",
    ],
    "interest_charged": [
        "interest charged",
        "interest",
        "monthly interest",
        "interest component",
    ],
    "principal_paid": [
        "principal paid",
        "principal",
        "principal component",
        "principal adjustment",
    ],
    "charges_paid": [
        "charges paid",
        "charges",
        "fees",
        "loan charges",
    ],
    "annual_rate": [
        "annual rate",
        "interest rate",
        "rate percent",
        "rate pa",
        "rate p a",
    ],
}


def _normalize_header(value: object) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", str(value).strip().lower())
    return re.sub(r"\s+", " ", normalized).strip()


def _find_column(columns: list[str], aliases: list[str]) -> str | None:
    alias_set = {_normalize_header(alias) for alias in aliases}
    for column in columns:
        if _normalize_header(column) in alias_set:
            return column
    for column in columns:
        normalized = _normalize_header(column)
        if any(alias in normalized for alias in alias_set):
            return column
    return None


def _is_non_transaction_amount_column(column: str | None) -> bool:
    normalized = _normalize_header(column or "")
    ignored_tokens = {
        "reward",
        "points",
        "intl",
        "international",
        "serno",
        "serial",
        "sr no",
        "reference",
        "ref no",
        "balance",
        "available",
    }
    return any(token in normalized for token in ignored_tokens)


def _find_transaction_amount_column(columns: list[str]) -> str | None:
    preferred_headers = {
        "amount in",
        "amount inr",
        "amount in rs",
        "amount in rupees",
        "transaction amount",
        "txn amount",
        "billing amount",
        "amount",
    }
    exact_matches = [
        column
        for column in columns
        if _normalize_header(column) in preferred_headers and not _is_non_transaction_amount_column(column)
    ]
    if exact_matches:
        return exact_matches[-1]

    amount_like_columns = [
        column
        for column in columns
        if "amount" in _normalize_header(column) and not _is_non_transaction_amount_column(column)
    ]
    return amount_like_columns[-1] if amount_like_columns else None


def _to_decimal(value: object) -> Decimal | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None

    raw = str(value).strip()
    if not raw or raw.lower() == "nan":
        return None

    is_negative = raw.startswith("(") and raw.endswith(")")
    cleaned = raw.upper()
    cleaned = cleaned.replace("INR", "").replace("RS.", "").replace("RS", "")
    cleaned = cleaned.replace(",", "").replace("CR", "").replace("DR", "")
    cleaned = cleaned.replace("(", "").replace(")", "").strip()
    cleaned = cleaned.replace("−", "-")
    if "E+" in cleaned or "E-" in cleaned:
        return None

    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        return None
    if not is_reasonable_transaction_amount(amount):
        return None
    return -amount if is_negative else amount


def _infer_marker_from_value(value: object) -> str | None:
    if value is None:
        return None
    raw = str(value).strip().lower()
    if not raw:
        return None
    if "dr" in raw or "debit" in raw:
        return "debit"
    if "cr" in raw or "credit" in raw:
        return "credit"
    return None


def _to_date(value: object) -> date | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None

    if len(raw) >= 10 and raw[0:4].isdigit() and raw[4] in {"-", "/"}:
        parsed = pd.to_datetime(raw, errors="coerce", dayfirst=False)
    else:
        parsed = pd.to_datetime(raw, errors="coerce", dayfirst=True)
    if pd.isna(parsed):
        return None
    return parsed.date()


def _resolve_amount_and_type(row: pd.Series, mapping: dict[str, str | None]) -> tuple[Decimal | None, str | None]:
    debit_column = mapping.get("debit")
    credit_column = mapping.get("credit")
    amount_column = mapping.get("amount")
    type_column = mapping.get("type")

    if debit_column or credit_column:
        debit_value = _to_decimal(row.get(debit_column)) if debit_column else None
        credit_value = _to_decimal(row.get(credit_column)) if credit_column else None
        if debit_value is not None and debit_value != 0:
            return abs(debit_value), "debit"
        if credit_value is not None and credit_value != 0:
            return abs(credit_value), "credit"

    raw_amount = row.get(amount_column) if amount_column else None
    amount_value = _to_decimal(raw_amount) if amount_column else None
    if amount_value is None:
        return None, None

    tx_type = None
    if type_column:
        marker = str(row.get(type_column) or "").strip().lower()
        if marker in {"debit", "dr"}:
            tx_type = "debit"
        elif marker in {"credit", "cr"}:
            tx_type = "credit"

    if tx_type is None:
        tx_type = _infer_marker_from_value(raw_amount)
    if tx_type is None:
        tx_type = "debit" if amount_value < 0 else "credit"
    return abs(amount_value), tx_type


def _detect_document_type(file_path: Path, descriptions: list[str], override: str | None) -> tuple[str, str | None]:
    if override and override != "auto":
        return override, override.replace("_", " ").title()

    filename = file_path.name.lower()
    upi_like_count = sum(1 for description in descriptions if "upi" in description.lower())
    credit_card_like_count = sum(
        1 for description in descriptions if "credit card" in description.lower() or description.lower().startswith("pos ")
    )
    loan_like_count = sum(
        1
        for description in descriptions
        if any(
            token in description.lower()
            for token in {
                "loan recovery",
                "loan rec",
                "home loan",
                "housing loan",
                "loan account",
                "outstanding",
                "principal",
                "mbk",
            }
        )
    )

    if "upi" in filename or (descriptions and upi_like_count / max(len(descriptions), 1) >= 0.6):
        return "upi_statement", "UPI statement"
    if "card" in filename or (descriptions and credit_card_like_count / max(len(descriptions), 1) >= 0.6):
        return "credit_card_statement", "Credit card statement"
    if "loan" in filename or (descriptions and loan_like_count >= 2 and loan_like_count / max(len(descriptions), 1) >= 0.5):
        return "loan_statement", "Loan statement"
    return "bank_statement", "Bank statement"


def _load_dataframe(file_path: Path) -> pd.DataFrame:
    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(file_path)
    return pd.read_excel(file_path)


def parse_tabular_dataframe(
    dataframe: pd.DataFrame,
    session: Session,
    source_type_override: str | None = None,
    account_source: str | None = None,
    file_path: Path | None = None,
    raw_text: str | None = None,
) -> ParsedDocument:
    working_frame = dataframe.copy()
    working_frame.columns = [_normalize_header(column) for column in working_frame.columns]
    columns = list(working_frame.columns)

    mapping = {field: _find_column(columns, aliases) for field, aliases in HEADER_ALIASES.items()}
    transaction_amount_column = _find_transaction_amount_column(columns)
    if transaction_amount_column:
        mapping["amount"] = transaction_amount_column
    elif mapping.get("amount") and _is_non_transaction_amount_column(mapping["amount"]):
        mapping["amount"] = None
    if not mapping["date"] or not mapping["description"] or (not mapping["amount"] and not mapping["debit"] and not mapping["credit"]):
        raise ValueError("Could not identify required columns. Expected date, description, and amount columns.")

    parsed_rows: list[ParsedTransactionRow] = []
    descriptions: list[str] = []
    valid_rows = 0

    for _, row in working_frame.iterrows():
        tx_date = _to_date(row.get(mapping["date"]))
        raw_description = str(row.get(mapping["description"]) or "").strip()
        if tx_date is None or not raw_description:
            continue
        if raw_description.lower() in {"description", "narration", "particulars"}:
            continue

        amount, transaction_type = _resolve_amount_and_type(row, mapping)
        if amount is None or transaction_type is None:
            continue

        valid_rows += 1
        descriptions.append(raw_description)

        payment_mode = infer_payment_mode(raw_description)
        merchant_name = extract_merchant_name(raw_description, payment_mode)
        category, subcategory, category_confidence = categorize_transaction(
            description=raw_description,
            merchant_name=merchant_name,
            payment_mode=payment_mode,
            transaction_type=transaction_type,
            session=session,
        )

        running_balance = _to_decimal(row.get(mapping["balance"])) if mapping.get("balance") else None
        extra = {
            "opening_outstanding": _to_decimal(row.get(mapping["opening_outstanding"])) if mapping.get("opening_outstanding") else None,
            "closing_outstanding": _to_decimal(row.get(mapping["closing_outstanding"])) if mapping.get("closing_outstanding") else None,
            "interest_charged": _to_decimal(row.get(mapping["interest_charged"])) if mapping.get("interest_charged") else None,
            "principal_paid": _to_decimal(row.get(mapping["principal_paid"])) if mapping.get("principal_paid") else None,
            "charges_paid": _to_decimal(row.get(mapping["charges_paid"])) if mapping.get("charges_paid") else None,
            "annual_rate": _to_decimal(row.get(mapping["annual_rate"])) if mapping.get("annual_rate") else None,
        }
        extra = {key: value for key, value in extra.items() if value is not None}
        row_account_source = account_source
        if not row_account_source and mapping.get("account_source"):
            candidate = str(row.get(mapping["account_source"]) or "").strip()
            row_account_source = candidate or None

        parsed_rows.append(
            ParsedTransactionRow(
                date=tx_date,
                description=merchant_name or raw_description[:255],
                raw_description=raw_description,
                amount=amount,
                transaction_type=transaction_type,
                payment_mode=payment_mode,
                merchant_name=merchant_name,
                category=category,
                subcategory=subcategory or None,
                confidence_score=category_confidence,
                account_source=row_account_source,
                running_balance=running_balance,
                extra=extra,
            )
        )

    resolved_file_path = file_path or Path("statement.csv")
    document_type, detected_source_name = _detect_document_type(resolved_file_path, descriptions, source_type_override)
    base_fields = ["date", "description", "amount", "debit", "credit", "type", "balance", "account_source"]
    matched_columns = sum(1 for field in base_fields if mapping.get(field))
    confidence = 0.0
    confidence += min(matched_columns / len(base_fields), 1.0) * 0.45
    confidence += 0.35 if parsed_rows else 0.0
    confidence += 0.20 if valid_rows == len(parsed_rows) and parsed_rows else 0.0

    sorted_rows = [
        row
        for _, row in sorted(
            enumerate(parsed_rows),
            key=lambda item: (item[1].date, item[0]),
        )
    ]

    return ParsedDocument(
        document_type=document_type,
        parsing_confidence=round(min(confidence, 0.99), 2),
        detected_source_name=detected_source_name,
        rows=sorted_rows,
        raw_text=raw_text or "\n".join(descriptions[:500]),
    )


def parse_tabular_statement(
    file_path: Path,
    session: Session,
    source_type_override: str | None = None,
    account_source: str | None = None,
) -> ParsedDocument:
    dataframe = _load_dataframe(file_path)
    return parse_tabular_dataframe(
        dataframe=dataframe,
        session=session,
        source_type_override=source_type_override,
        account_source=account_source,
        file_path=file_path,
    )
