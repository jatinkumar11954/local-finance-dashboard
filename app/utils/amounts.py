from __future__ import annotations

from decimal import Decimal, InvalidOperation


MAX_REASONABLE_TRANSACTION_AMOUNT = Decimal("1000000000")


def is_reasonable_transaction_amount(value: Decimal | float | int | str | None) -> bool:
    if value is None:
        return False
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        return False
    return Decimal("0.00") <= abs(amount) <= MAX_REASONABLE_TRANSACTION_AMOUNT
