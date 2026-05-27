from __future__ import annotations

import re
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Category, CategoryRule


DEFAULT_CATEGORY_NAMES = [
    "Income",
    "Rent",
    "Home Loan EMI",
    "Other Loan EMI",
    "Credit Card Payment",
    "Groceries",
    "Food Delivery",
    "Restaurants",
    "Utilities",
    "Electricity",
    "Water",
    "Internet",
    "Mobile Recharge",
    "Fuel",
    "Transport",
    "Cab / Auto",
    "Shopping",
    "Healthcare",
    "Insurance",
    "Education",
    "Investments",
    "Mutual Funds / SIP",
    "Taxes",
    "Subscriptions",
    "Entertainment",
    "Travel",
    "Cash Withdrawal",
    "UPI Transfers",
    "Family / Personal Transfers",
    "Bank Charges",
    "Credit Card Interest / Fees",
    "Loan Interest",
    "Loan Prepayment",
    "Loan Charges",
    "Miscellaneous",
]


DEFAULT_RULES = [
    {"name": "salary", "pattern": r"salary|payroll|sal cred|salary credit", "category": "Income", "subcategory": "Salary", "priority": 100},
    {"name": "rent", "pattern": r"\brent\b|house rent|landlord", "category": "Rent", "subcategory": "Housing", "priority": 95},
    {"name": "home-loan-emi", "pattern": r"home loan|housing loan|hl emi", "category": "Home Loan EMI", "subcategory": "EMI", "priority": 95},
    {"name": "loan-recovery-emi", "pattern": r"loan recovery|loan rec|loan repayment", "category": "Home Loan EMI", "subcategory": "EMI", "priority": 98},
    {"name": "mbk-loan-prepayment", "pattern": r"\bmbk\b", "category": "Loan Prepayment", "subcategory": "Prepayment", "priority": 97},
    {"name": "loan-emi", "pattern": r"\bemi\b|personal loan", "category": "Other Loan EMI", "subcategory": "EMI", "priority": 90},
    {"name": "card-payment", "pattern": r"credit card payment|card payment|cc payment", "category": "Credit Card Payment", "subcategory": "Card Bill", "priority": 92},
    {"name": "groceries", "pattern": r"grocery|dmart|bigbasket|reliance fresh|ratnadeep|more super", "category": "Groceries", "subcategory": "Essentials", "priority": 88},
    {"name": "food-delivery", "pattern": r"swiggy|zomato|zepto|blinkit|instamart", "category": "Food Delivery", "subcategory": "Delivery", "priority": 88},
    {"name": "restaurants", "pattern": r"restaurant|cafe|eatery|dominos|pizza hut|kfc|mcdonald", "category": "Restaurants", "subcategory": "Dining Out", "priority": 82},
    {"name": "electricity", "pattern": r"electricity|power bill|tsspdcl", "category": "Electricity", "subcategory": "Utilities", "priority": 87},
    {"name": "water", "pattern": r"water bill|water board|hmdwsb", "category": "Water", "subcategory": "Utilities", "priority": 87},
    {"name": "internet", "pattern": r"jiofiber|airtel xstream|internet|broadband", "category": "Internet", "subcategory": "Connectivity", "priority": 86},
    {"name": "mobile", "pattern": r"mobile recharge|prepaid|postpaid|vi india|airtel mobile|jio recharge", "category": "Mobile Recharge", "subcategory": "Connectivity", "priority": 86},
    {"name": "fuel", "pattern": r"petrol|diesel|fuel|hpcl|iocl|bharat petroleum", "category": "Fuel", "subcategory": "Vehicle", "priority": 84},
    {"name": "cab", "pattern": r"uber|ola|rapido", "category": "Cab / Auto", "subcategory": "Ride Hailing", "priority": 84},
    {"name": "transport", "pattern": r"metro|irctc|bus|transport", "category": "Transport", "subcategory": "Commute", "priority": 79},
    {"name": "shopping", "pattern": r"amazon|flipkart|myntra|ajio|shopping", "category": "Shopping", "subcategory": "Retail", "priority": 78},
    {"name": "healthcare", "pattern": r"apollo|medplus|pharmacy|hospital|clinic|doctor", "category": "Healthcare", "subcategory": "Medical", "priority": 85},
    {"name": "insurance", "pattern": r"insurance|lic|premium", "category": "Insurance", "subcategory": "Policy", "priority": 85},
    {"name": "education", "pattern": r"school|college|fees|udemy|coursera", "category": "Education", "subcategory": "Learning", "priority": 75},
    {"name": "investments", "pattern": r"groww|zerodha|kuvera|investment", "category": "Investments", "subcategory": "Brokerage", "priority": 82},
    {"name": "sip", "pattern": r"\bsip\b|mutual fund|mf investment", "category": "Mutual Funds / SIP", "subcategory": "SIP", "priority": 86},
    {"name": "taxes", "pattern": r"income tax|gst|advance tax|tds", "category": "Taxes", "subcategory": "Tax", "priority": 86},
    {"name": "subscriptions", "pattern": r"netflix|spotify|youtube premium|prime|subscription", "category": "Subscriptions", "subcategory": "Digital", "priority": 80},
    {"name": "entertainment", "pattern": r"bookmyshow|movie|gaming", "category": "Entertainment", "subcategory": "Leisure", "priority": 78},
    {"name": "travel", "pattern": r"makemytrip|airbnb|hotel|flight|travel", "category": "Travel", "subcategory": "Trip", "priority": 78},
    {"name": "cash", "pattern": r"atm wd|cash withdrawal|atm withdrawal", "category": "Cash Withdrawal", "subcategory": "Cash", "priority": 88},
    {"name": "upi-transfer", "pattern": r"\bupi\b", "category": "UPI Transfers", "subcategory": "UPI", "priority": 55},
    {"name": "personal-transfer", "pattern": r"personal transfer|friend transfer|family transfer|to mom|to dad|to father|to mother|self transfer|own account", "category": "Family / Personal Transfers", "subcategory": "Personal Transfer", "priority": 83},
    {"name": "bank-charges", "pattern": r"bank charge|charges|annual fee|sms fee|maintenance fee", "category": "Bank Charges", "subcategory": "Bank Fee", "priority": 90},
    {"name": "card-fees", "pattern": r"late fee|finance charge|interest charged|over limit|cash advance fee", "category": "Credit Card Interest / Fees", "subcategory": "Card Fee", "priority": 94},
    {"name": "loan-interest", "pattern": r"interest debit|loan interest|interest amount|interest.*loan|loan.*interest", "category": "Loan Interest", "subcategory": "Interest", "priority": 93},
    {"name": "loan-charges", "pattern": r"(penal|bounce|late fee|charge|processing fee|processing charge).*(loan|emi)|(loan|emi).*(penal|bounce|late fee|charge|processing fee|processing charge)", "category": "Loan Charges", "subcategory": "Charges", "priority": 94},
]


STOPWORDS = {
    "upi",
    "upi payment",
    "p2a",
    "p2m",
    "collect",
    "vpa",
    "imps",
    "neft",
    "rtgs",
    "mbk",
    "mob",
    "inb",
    "ib",
    "ach",
    "ecs",
    "nach",
    "ecom",
    "pos",
    "debit",
    "credit",
    "dr",
    "cr",
    "txn",
    "trf",
    "transfer to",
    "transfer from",
    "transfer",
    "payment",
    "ref",
    "utr",
    "rrn",
    "upi ref",
    "txn ref",
    "to",
    "by",
    "from",
    "merchant",
    "via",
    "pvt",
    "ltd",
}

UPI_PROVIDER_TOKENS = {
    "gpay",
    "google pay",
    "phonepe",
    "paytm",
    "amazon pay",
    "bharatpe",
}

BUSINESS_KEYWORDS = {
    "store",
    "mart",
    "supermarket",
    "restaurant",
    "cafe",
    "medical",
    "pharmacy",
    "service",
    "agency",
    "petrol",
    "fuel",
    "electricity",
    "broadband",
    "insurance",
    "recharge",
    "telecom",
    "retail",
    "fashion",
    "mall",
    "foods",
    "kitchen",
    "hospital",
}

PERSONAL_TRANSFER_HINTS = {
    "personal transfer",
    "family transfer",
    "friend transfer",
    "self transfer",
    "own account",
    "to mom",
    "to dad",
    "to mother",
    "to father",
    "to wife",
    "to husband",
    "to brother",
    "to sister",
}


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = re.sub(r"[^a-zA-Z0-9@.&/\s-]+", " ", value.lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def infer_payment_mode(description: str) -> str:
    text = normalize_text(description)
    if "upi" in text or any(token in text for token in UPI_PROVIDER_TOKENS):
        return "UPI"
    if "imps" in text or "p2a" in text or "mbk" in text or "mob" in text:
        return "IMPS"
    if "neft" in text:
        return "NEFT"
    if "rtgs" in text:
        return "RTGS"
    if "pos" in text or "card" in text or "ecom" in text or "rupay" in text or "visa" in text or "mastercard" in text:
        return "CARD"
    if "atm" in text or "cash withdrawal" in text:
        return "CASH"
    if "emi" in text or "loan repayment" in text:
        return "EMI"
    if "autopay" in text or "auto debit" in text or "nach" in text or "ecs" in text or "standing instruction" in text or "ach" in text:
        return "AUTOPAY"
    if "cheque" in text or "chq" in text:
        return "CHEQUE"
    if "netbanking" in text or "inb" in text or text.startswith("ib ") or "fund transfer" in text:
        return "NETBANKING"
    if "wallet" in text:
        return "WALLET"
    return "unknown"


def _cleanup_merchant_candidate(value: str) -> str:
    cleaned = value.split("@", maxsplit=1)[0]
    cleaned = re.sub(r"\b(?:ref|utr|rrn|txn|vpa|p2a|p2m|mbk|mob|inb|ib)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[^a-zA-Z0-9&.\s-]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -/")
    return cleaned.title()


def _is_meaningful_candidate(value: str) -> bool:
    normalized = normalize_text(value)
    if not normalized or normalized in STOPWORDS or normalized.isdigit():
        return False
    if len(normalized) < 3 or not any(char.isalpha() for char in normalized):
        return False
    return True


def _extract_via_keyword_patterns(raw: str) -> str | None:
    patterns = [
        r"(?:\bto\b|\bby\b|\bfrom\b)\s+(?P<merchant>[a-z][a-z0-9&.\s-]{2,})$",
        r"(?:merchant|beneficiary)\s*[:/-]\s*(?P<merchant>[a-z][a-z0-9&.\s-]{2,})",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if match:
            candidate = _cleanup_merchant_candidate(match.group("merchant"))
            if _is_meaningful_candidate(candidate):
                return candidate
    return None


def _candidate_tokens(raw: str) -> list[str]:
    tokens = re.split(r"[/|:-]+", raw)
    return [token.strip() for token in tokens if token and token.strip()]


def extract_merchant_name(description: str, payment_mode: str) -> str | None:
    raw = description or ""
    by_keyword = _extract_via_keyword_patterns(raw)
    if by_keyword:
        return by_keyword

    if payment_mode == "UPI":
        for candidate in _candidate_tokens(raw):
            candidate = candidate.split("@", maxsplit=1)[0]
            normalized = normalize_text(candidate)
            if normalized in UPI_PROVIDER_TOKENS:
                continue
            if _is_meaningful_candidate(candidate):
                return _cleanup_merchant_candidate(candidate)

    if payment_mode == "CARD":
        match = re.search(r"(?:pos|card|ecom)\s+(?:\w+\s+)?(?:\d+\s+)?(.*)", raw, flags=re.IGNORECASE)
        if match:
            candidate = _cleanup_merchant_candidate(match.group(1))
            if _is_meaningful_candidate(candidate):
                return candidate

    if payment_mode in {"IMPS", "NEFT", "RTGS", "NETBANKING", "AUTOPAY"}:
        match = re.search(
            r"(?:to|by|from|beneficiary|ach dr|nach dr|ecs dr)\s+(?P<merchant>[a-z][a-z0-9&.\s-]{2,})",
            raw,
            flags=re.IGNORECASE,
        )
        if match:
            candidate = _cleanup_merchant_candidate(match.group("merchant"))
            if _is_meaningful_candidate(candidate):
                return candidate

    for token in _candidate_tokens(raw):
        if _is_meaningful_candidate(token):
            return _cleanup_merchant_candidate(token)
    return None


def is_probable_personal_transfer(description: str, merchant_name: str | None, payment_mode: str) -> bool:
    haystack = normalize_text(" ".join(part for part in [description, merchant_name] if part))
    if any(hint in haystack for hint in PERSONAL_TRANSFER_HINTS):
        return True
    if payment_mode not in {"UPI", "IMPS", "NEFT", "NETBANKING"}:
        return False
    if not merchant_name:
        return False

    normalized_merchant = normalize_text(merchant_name)
    if any(keyword in normalized_merchant for keyword in BUSINESS_KEYWORDS):
        return False
    words = [word for word in normalized_merchant.split() if word]
    return 1 <= len(words) <= 3 and all(word.isalpha() for word in words)


def seed_default_categories(session: Session) -> None:
    existing_names = set(session.scalars(select(Category.name)).all())
    for category_name in DEFAULT_CATEGORY_NAMES:
        if category_name not in existing_names:
            session.add(Category(name=category_name))


def seed_default_rules(session: Session) -> None:
    existing_names = set(session.scalars(select(CategoryRule.name)).all())
    for rule in DEFAULT_RULES:
        if rule["name"] in existing_names:
            continue
        session.add(
            CategoryRule(
                name=rule["name"],
                pattern=rule["pattern"],
                target_category=rule["category"],
                target_subcategory=rule["subcategory"],
                priority=rule["priority"],
                is_regex=True,
                case_sensitive=False,
            )
        )


def _iter_rules(session: Session | None) -> Iterable[dict[str, str | int | bool]]:
    if session is None:
        return DEFAULT_RULES
    rules = session.scalars(
        select(CategoryRule)
        .where(CategoryRule.is_active.is_(True))
        .order_by(CategoryRule.priority.desc())
    ).all()
    if not rules:
        return DEFAULT_RULES
    return [
        {
            "name": rule.name,
            "pattern": rule.pattern,
            "category": rule.target_category,
            "subcategory": rule.target_subcategory,
            "priority": rule.priority,
            "is_regex": rule.is_regex,
            "case_sensitive": rule.case_sensitive,
        }
        for rule in rules
    ]


def categorize_transaction(
    description: str,
    merchant_name: str | None,
    payment_mode: str,
    transaction_type: str,
    session: Session | None = None,
) -> tuple[str, str | None, float]:
    haystack = " ".join(
        part for part in [normalize_text(description), normalize_text(merchant_name), payment_mode.lower()] if part
    )
    for rule in _iter_rules(session):
        flags = 0 if rule.get("case_sensitive") else re.IGNORECASE
        if re.search(str(rule["pattern"]), haystack, flags=flags):
            return str(rule["category"]), str(rule.get("subcategory") or ""), 0.9

    if transaction_type == "credit":
        return "Income", "Other", 0.55
    if is_probable_personal_transfer(description, merchant_name, payment_mode):
        return "Family / Personal Transfers", "Personal Transfer", 0.72
    if payment_mode == "UPI":
        return "UPI Transfers", "UPI", 0.45
    return "Miscellaneous", None, 0.35
