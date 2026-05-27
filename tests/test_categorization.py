from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.models.entities import Transaction
from app.schemas.category_rule import CategoryRuleCreate
from app.services.category_rules import create_category_rule, reapply_category_rules
from app.services.categorization.rules import categorize_transaction, extract_merchant_name, infer_payment_mode


def test_upi_transaction_is_categorized(db_session):
    description = "UPI/SWIGGY/food order"
    payment_mode = infer_payment_mode(description)
    merchant_name = extract_merchant_name(description, payment_mode)

    category, subcategory, confidence = categorize_transaction(
        description=description,
        merchant_name=merchant_name,
        payment_mode=payment_mode,
        transaction_type="debit",
        session=db_session,
    )

    assert payment_mode == "UPI"
    assert merchant_name == "Swiggy"
    assert category == "Food Delivery"
    assert confidence >= 0.9


def test_personal_transfer_is_detected(db_session):
    description = "UPI/ANIL KUMAR/personal transfer"
    payment_mode = infer_payment_mode(description)
    merchant_name = extract_merchant_name(description, payment_mode)

    category, subcategory, confidence = categorize_transaction(
        description=description,
        merchant_name=merchant_name,
        payment_mode=payment_mode,
        transaction_type="debit",
        session=db_session,
    )

    assert merchant_name == "Anil Kumar"
    assert category == "Family / Personal Transfers"
    assert subcategory == "Personal Transfer"
    assert confidence >= 0.72


def test_custom_rule_can_be_reapplied_to_existing_transactions(db_session):
    transaction = Transaction(
        date=date(2026, 5, 20),
        description="Cultfit Monthly Membership",
        raw_description="UPI/CULTFIT/monthly membership",
        amount=Decimal("1499.00"),
        transaction_type="debit",
        payment_mode="UPI",
        merchant_name="Cultfit",
        category="Miscellaneous",
        confidence_score=0.35,
    )
    db_session.add(transaction)
    db_session.commit()
    db_session.refresh(transaction)

    create_category_rule(
        db_session,
        CategoryRuleCreate(
            name="cultfit-subscription",
            pattern=r"cultfit|cult fit",
            target_category="Subscriptions",
            target_subcategory="Fitness",
            priority=91,
            is_regex=True,
            case_sensitive=False,
            is_active=True,
        ),
    )

    updated_count = reapply_category_rules(db_session, transaction_ids=[transaction.id])
    refreshed = db_session.get(Transaction, transaction.id)

    assert updated_count == 1
    assert refreshed is not None
    assert refreshed.category == "Subscriptions"
    assert refreshed.subcategory == "Fitness"
