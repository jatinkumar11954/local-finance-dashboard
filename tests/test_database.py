from __future__ import annotations

from datetime import date

from sqlalchemy import inspect
from sqlalchemy import select

from app.bootstrap import exclude_invalid_amount_transactions
from app.database import get_engine
from app.models.entities import Benchmark, Category
from app.models.entities import Transaction


def test_reference_data_is_seeded(db_session):
    category_names = db_session.scalars(select(Category.name)).all()
    benchmark_count = len(db_session.scalars(select(Benchmark)).all())

    assert "Groceries" in category_names
    assert "Rent" in category_names
    assert benchmark_count > 0


def test_assistant_memory_table_exists(db_session):
    tables = set(inspect(get_engine()).get_table_names())

    assert "assistant_memory" in tables


def test_outlier_transactions_are_auto_excluded(db_session):
    transaction = Transaction(
        date=date(2026, 5, 1),
        description="Parser outlier",
        raw_description="OFFUS EMI,PRIN NB",
        amount=9999999980513001472000,
        transaction_type="debit",
        payment_mode="EMI",
        category="Other Loan EMI",
        confidence_score=0.3,
    )
    db_session.add(transaction)
    db_session.commit()

    updated_count = exclude_invalid_amount_transactions(db_session)
    db_session.commit()
    db_session.refresh(transaction)

    assert updated_count == 1
    assert transaction.is_excluded is True
    assert "Auto-excluded parser outlier" in transaction.notes
