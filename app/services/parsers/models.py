from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any


@dataclass
class ParsedTransactionRow:
    date: date
    description: str
    raw_description: str
    amount: Decimal
    transaction_type: str
    payment_mode: str
    merchant_name: str | None
    category: str
    subcategory: str | None
    confidence_score: float
    account_source: str | None = None
    running_balance: Decimal | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedDocument:
    document_type: str
    parsing_confidence: float
    detected_source_name: str | None
    rows: list[ParsedTransactionRow] = field(default_factory=list)
    raw_text: str | None = None
