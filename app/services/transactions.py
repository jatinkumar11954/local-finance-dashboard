from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.entities import AuditLog, Category, Transaction


def list_categories(session: Session) -> list[str]:
    return session.scalars(select(Category.name).where(Category.is_active.is_(True)).order_by(Category.name)).all()


def query_transactions(
    session: Session,
    start_date: date | None = None,
    end_date: date | None = None,
    category: str | None = None,
    payment_mode: str | None = None,
    merchant_query: str | None = None,
    transaction_type: str | None = None,
    document_id: int | None = None,
    max_confidence: float | None = None,
    include_excluded: bool = True,
) -> list[Transaction]:
    statement: Select[tuple[Transaction]] = select(Transaction)
    if start_date:
        statement = statement.where(Transaction.date >= start_date)
    if end_date:
        statement = statement.where(Transaction.date <= end_date)
    if category:
        statement = statement.where(Transaction.category == category)
    if payment_mode:
        statement = statement.where(Transaction.payment_mode == payment_mode)
    if merchant_query:
        like_value = f"%{merchant_query}%"
        statement = statement.where(Transaction.merchant_name.ilike(like_value))
    if transaction_type:
        statement = statement.where(Transaction.transaction_type == transaction_type)
    if document_id:
        statement = statement.where(Transaction.source_document_id == document_id)
    if max_confidence is not None:
        statement = statement.where(Transaction.confidence_score <= max_confidence)
    if not include_excluded:
        statement = statement.where(Transaction.is_excluded.is_(False))
    statement = statement.order_by(Transaction.date.desc(), Transaction.id.desc())
    return session.scalars(statement).all()


def _payload_dict(payload: Any) -> dict[str, Any]:
    if hasattr(payload, "model_dump"):
        return payload.model_dump(exclude_unset=True)
    if isinstance(payload, dict):
        return payload
    raise TypeError("Payload must be a Pydantic model or dictionary.")


def _bulk_item_parts(item: Any) -> tuple[int, Any]:
    if isinstance(item, dict):
        return int(item["transaction_id"]), item["updates"]
    return int(item.transaction_id), item.updates


def update_transaction(session: Session, transaction_id: int, payload: Any) -> Transaction:
    transaction = session.get(Transaction, transaction_id)
    if transaction is None:
        raise ValueError(f"Transaction {transaction_id} was not found.")

    changed_fields: dict[str, object] = {}
    for field_name, value in _payload_dict(payload).items():
        setattr(transaction, field_name, value)
        changed_fields[field_name] = value

    session.add(
        AuditLog(
            action="transaction_updated",
            entity_type="transaction",
            entity_id=str(transaction.id),
            details=changed_fields,
        )
    )
    session.commit()
    session.refresh(transaction)
    return transaction


def bulk_update_transactions(session: Session, items: list[Any]) -> int:
    updated_count = 0

    for item in items:
        transaction_id, updates = _bulk_item_parts(item)
        transaction = session.get(Transaction, transaction_id)
        if transaction is None:
            continue

        changed_fields: dict[str, object] = {}
        for field_name, value in _payload_dict(updates).items():
            setattr(transaction, field_name, value)
            changed_fields[field_name] = value

        if not changed_fields:
            continue

        session.add(
            AuditLog(
                action="transaction_bulk_updated",
                entity_type="transaction",
                entity_id=str(transaction.id),
                details=changed_fields,
            )
        )
        updated_count += 1

    session.commit()
    return updated_count
