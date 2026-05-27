from __future__ import annotations

import re


def mask_numeric_identifier(value: str, keep_last: int = 4) -> str:
    digits = re.sub(r"\D", "", value)
    if len(digits) <= keep_last:
        return digits
    return f"{'*' * (len(digits) - keep_last)}{digits[-keep_last:]}"
