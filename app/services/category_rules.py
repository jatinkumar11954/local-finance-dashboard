from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import AuditLog, CategoryRule, Transaction
from app.schemas.category_rule import CategoryRuleCreate, CategoryRuleUpdate
from app.services.categorization.rules import categorize_transaction, extract_merchant_name, infer_payment_mode


def list_category_rules(session: Session, include_inactive: bool = True) -> list[CategoryRule]:
    statement = select(CategoryRule).order_by(CategoryRule.priority.desc(), CategoryRule.name)
    if not include_inactive:
        statement = statement.where(CategoryRule.is_active.is_(True))
    return session.scalars(statement).all()


def create_category_rule(session: Session, payload: CategoryRuleCreate) -> CategoryRule:
    rule = CategoryRule(**payload.model_dump())
    session.add(rule)
    session.flush()
    session.add(
        AuditLog(
            action="category_rule_created",
            entity_type="category_rule",
            entity_id=str(rule.id),
            details=payload.model_dump(),
        )
    )
    session.commit()
    session.refresh(rule)
    return rule


def update_category_rule(session: Session, rule_id: int, payload: CategoryRuleUpdate) -> CategoryRule:
    rule = session.get(CategoryRule, rule_id)
    if rule is None:
        raise ValueError(f"Category rule {rule_id} was not found.")

    changes = payload.model_dump(exclude_unset=True)
    for field_name, value in changes.items():
        setattr(rule, field_name, value)

    session.add(
        AuditLog(
            action="category_rule_updated",
            entity_type="category_rule",
            entity_id=str(rule.id),
            details=changes,
        )
    )
    session.commit()
    session.refresh(rule)
    return rule


def delete_category_rule(session: Session, rule_id: int) -> None:
    rule = session.get(CategoryRule, rule_id)
    if rule is None:
        raise ValueError(f"Category rule {rule_id} was not found.")

    session.add(
        AuditLog(
            action="category_rule_deleted",
            entity_type="category_rule",
            entity_id=str(rule.id),
            details={"name": rule.name},
        )
    )
    session.delete(rule)
    session.commit()


def reapply_category_rules(
    session: Session,
    transaction_ids: list[int] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    document_id: int | None = None,
    only_low_confidence: bool = False,
) -> int:
    statement = select(Transaction)
    if transaction_ids:
        statement = statement.where(Transaction.id.in_(transaction_ids))
    if start_date:
        statement = statement.where(Transaction.date >= start_date)
    if end_date:
        statement = statement.where(Transaction.date <= end_date)
    if document_id:
        statement = statement.where(Transaction.source_document_id == document_id)
    if only_low_confidence:
        statement = statement.where(Transaction.confidence_score <= 0.75)

    transactions = session.scalars(statement).all()
    updated_count = 0

    for transaction in transactions:
        payment_mode = infer_payment_mode(transaction.raw_description)
        merchant_name = extract_merchant_name(transaction.raw_description, payment_mode) or transaction.merchant_name
        category, subcategory, confidence_score = categorize_transaction(
            description=transaction.raw_description,
            merchant_name=merchant_name,
            payment_mode=payment_mode,
            transaction_type=transaction.transaction_type,
            session=session,
        )

        transaction.payment_mode = payment_mode
        transaction.merchant_name = merchant_name
        transaction.description = merchant_name or transaction.raw_description[:255]
        transaction.category = category
        transaction.subcategory = subcategory or None
        transaction.confidence_score = confidence_score
        updated_count += 1

    session.add(
        AuditLog(
            action="category_rules_reapplied",
            entity_type="transaction_batch",
            entity_id=None,
            details={
                "transaction_ids": transaction_ids or [],
                "document_id": document_id,
                "updated_count": updated_count,
                "only_low_confidence": only_low_confidence,
            },
        )
    )
    session.commit()
    return updated_count
