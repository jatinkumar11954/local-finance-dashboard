from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.services.categorization.rules import normalize_text


LOAN_CHARGE_TYPES = {
    "charge",
    "processing_fee",
    "insurance",
    "penal_interest",
    "bounce_charge",
}


@dataclass(frozen=True)
class LoanClassification:
    loan_transaction_type: str
    loan_match_reason: str
    confidence_score: float


def classify_loan_transaction(
    description: str,
    amount: Decimal | float | int | str,
    transaction_type: str,
    document_type: str | None = None,
) -> LoanClassification | None:
    text = normalize_text(description)
    is_debit = transaction_type == "debit"
    document_is_loan = document_type == "loan_statement"
    loan_hint = any(
        hint in text
        for hint in {
            "loan",
            "home loan",
            "housing loan",
            "loan recovery",
            "loan rec",
            "loan repayment",
            "lan",
            "mbk",
            "principal",
            "outstanding",
        }
    )

    if not is_debit and not document_is_loan:
        return None

    if "mbk" in text and is_debit:
        return LoanClassification("prepayment", "Description contains MBK debit pattern.", 0.86)
    if "loan recovery" in text or "loan rec" in text:
        return LoanClassification("emi", "Description contains loan recovery pattern.", 0.92)
    if "loan account payment" in text and is_debit:
        return LoanClassification("prepayment", "Description contains loan account payment debit pattern.", 0.84)
    if "loan repayment" in text or ("emi" in text and loan_hint):
        return LoanClassification("emi", "Description contains EMI with loan-related terms.", 0.84)
    if "processing fee" in text or "processing charge" in text or "procng fee" in text or "proc fee" in text:
        return LoanClassification("processing_fee", "Description contains loan processing fee pattern.", 0.84)
    if "insurance" in text and loan_hint:
        return LoanClassification("insurance", "Description contains loan-linked insurance pattern.", 0.78)
    if "bounce" in text and (loan_hint or "emi" in text):
        return LoanClassification("bounce_charge", "Description contains loan/EMI bounce charge pattern.", 0.86)
    if ("penal" in text or "late" in text) and (loan_hint or "emi" in text):
        return LoanClassification("penal_interest", "Description contains penal or late charge pattern.", 0.84)
    if "charge" in text and (loan_hint or "emi" in text):
        return LoanClassification("charge", "Description contains loan charge pattern.", 0.72)
    if "interest" in text and (loan_hint or document_is_loan):
        return LoanClassification("interest", "Description contains interest with loan reference.", 0.82)
    if "principal" in text and (loan_hint or document_is_loan):
        return LoanClassification("principal_adjustment", "Description contains principal adjustment pattern.", 0.78)
    if document_is_loan and is_debit:
        return LoanClassification("unknown", "Loan document debit row requires review.", 0.45)

    return None
