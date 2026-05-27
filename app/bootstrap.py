from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from app.config import get_settings
from app.database import get_session_factory, initialize_database, reset_database_state
from app.models.entities import AuditLog, Benchmark, Transaction
from app.services.benchmarks import load_benchmark_seed_data, seed_benchmarks
from app.services.categorization.rules import seed_default_categories, seed_default_rules
from app.utils.amounts import MAX_REASONABLE_TRANSACTION_AMOUNT


def ensure_directories() -> None:
    settings = get_settings()
    for path in (
        settings.data_dir,
        settings.uploads_dir,
        settings.processed_dir,
        settings.local_db_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)


def bootstrap_application() -> None:
    ensure_directories()
    initialize_database()

    session = get_session_factory()()
    try:
        seed_default_categories(session)
        seed_default_rules(session)
        if session.scalar(select(Benchmark.id).limit(1)) is None:
            benchmarks = load_benchmark_seed_data(get_settings().benchmark_seed_file)
            seed_benchmarks(session, benchmarks)
        exclude_invalid_amount_transactions(session)
        session.commit()
    finally:
        session.close()


def exclude_invalid_amount_transactions(session) -> int:
    transactions = session.scalars(
        select(Transaction).where(
            Transaction.amount > MAX_REASONABLE_TRANSACTION_AMOUNT,
            Transaction.is_excluded.is_(False),
        )
    ).all()
    for transaction in transactions:
        transaction.is_excluded = True
        note = f"Auto-excluded parser outlier over {MAX_REASONABLE_TRANSACTION_AMOUNT}."
        transaction.notes = f"{transaction.notes}\n{note}" if transaction.notes else note
        session.add(
            AuditLog(
                action="transaction_auto_excluded_outlier",
                entity_type="transaction",
                entity_id=str(transaction.id),
                details={
                    "amount": str(transaction.amount),
                    "threshold": str(MAX_REASONABLE_TRANSACTION_AMOUNT),
                    "source_document_id": transaction.source_document_id,
                },
            )
        )
    return len(transactions)


def reset_local_data() -> None:
    settings = get_settings()
    reset_database_state()

    if settings.database_path.exists():
        settings.database_path.unlink()

    for folder in (settings.uploads_dir, settings.processed_dir):
        if not folder.exists():
            continue
        for child in folder.iterdir():
            if child.is_file():
                child.unlink()

    bootstrap_application()
