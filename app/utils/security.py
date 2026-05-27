from __future__ import annotations

import hashlib


def hash_password(raw_password: str) -> str:
    return hashlib.sha256(raw_password.encode("utf-8")).hexdigest()


def verify_password(raw_password: str, expected_hash: str | None) -> bool:
    if not expected_hash:
        return True
    return hash_password(raw_password) == expected_hash
