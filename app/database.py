from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None
_engine_url: str | None = None
_session_factory_url: str | None = None


def get_engine() -> Engine:
    global _engine, _engine_url

    settings = get_settings()
    if _engine is None or _engine_url != settings.database_url:
        _engine = create_engine(
            settings.database_url,
            connect_args={"check_same_thread": False},
            future=True,
        )
        _engine_url = settings.database_url
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory, _session_factory_url

    engine = get_engine()
    settings = get_settings()
    if _session_factory is None or _session_factory_url != settings.database_url:
        _session_factory = sessionmaker(
            bind=engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            class_=Session,
        )
        _session_factory_url = settings.database_url
    return _session_factory


def get_db() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def reset_database_state() -> None:
    global _engine, _session_factory, _engine_url, _session_factory_url

    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
    _engine_url = None
    _session_factory_url = None


def initialize_database() -> None:
    from app.models.base import Base
    from app.models import entities  # noqa: F401

    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    _apply_sqlite_schema_extensions(engine)


def _apply_sqlite_schema_extensions(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        return

    inspector = inspect(engine)
    if "loans" not in inspector.get_table_names():
        return

    loan_columns = {column["name"] for column in inspector.get_columns("loans")}
    required_loan_columns = {
        "bank_name": "VARCHAR(120)",
        "masked_loan_account_number": "VARCHAR(32)",
        "rate_type": "VARCHAR(20) NOT NULL DEFAULT 'unknown'",
        "summary_total_paid": "NUMERIC(14, 2)",
        "summary_interest_paid": "NUMERIC(14, 2)",
        "summary_principal_paid": "NUMERIC(14, 2)",
        "summary_prepayment_paid": "NUMERIC(14, 2)",
        "source_document_id": "INTEGER",
    }

    with engine.begin() as connection:
        for column_name, column_sql in required_loan_columns.items():
            if column_name not in loan_columns:
                connection.execute(text(f"ALTER TABLE loans ADD COLUMN {column_name} {column_sql}"))

    if "loan_monthly_ledger" in inspector.get_table_names():
        ledger_columns = {column["name"] for column in inspector.get_columns("loan_monthly_ledger")}
        required_ledger_columns = {
            "principal_from_emi": "NUMERIC(14, 2)",
            "principal_from_prepayment": "NUMERIC(14, 2) NOT NULL DEFAULT 0",
            "total_principal_reduced": "NUMERIC(14, 2)",
            "base_annual_rate": "NUMERIC(8, 4)",
            "rate_variance": "NUMERIC(10, 6)",
            "rate_variance_percent": "NUMERIC(10, 6)",
            "calculation_method": "VARCHAR(60) NOT NULL DEFAULT 'unknown'",
            "manual_override_used": "BOOLEAN NOT NULL DEFAULT 0",
            "review_status": "VARCHAR(40) NOT NULL DEFAULT 'ok'",
        }
        with engine.begin() as connection:
            for column_name, column_sql in required_ledger_columns.items():
                if column_name not in ledger_columns:
                    connection.execute(text(f"ALTER TABLE loan_monthly_ledger ADD COLUMN {column_name} {column_sql}"))

    if "loan_manual_overrides" in inspector.get_table_names():
        override_columns = {column["name"] for column in inspector.get_columns("loan_manual_overrides")}
        required_override_columns = {
            "emi_paid": "NUMERIC(14, 2)",
            "prepayment_paid": "NUMERIC(14, 2)",
        }
        with engine.begin() as connection:
            for column_name, column_sql in required_override_columns.items():
                if column_name not in override_columns:
                    connection.execute(text(f"ALTER TABLE loan_manual_overrides ADD COLUMN {column_name} {column_sql}"))

    if "credit_cards" in inspector.get_table_names():
        card_columns = {column["name"] for column in inspector.get_columns("credit_cards")}
        required_card_columns = {
            "bank_name": "VARCHAR(120)",
            "last4": "VARCHAR(4)",
            "usage_type": "VARCHAR(30) NOT NULL DEFAULT 'normal'",
            "active": "BOOLEAN NOT NULL DEFAULT 1",
        }
        with engine.begin() as connection:
            for column_name, column_sql in required_card_columns.items():
                if column_name not in card_columns:
                    connection.execute(text(f"ALTER TABLE credit_cards ADD COLUMN {column_name} {column_sql}"))

    if "credit_card_statements" in inspector.get_table_names():
        statement_columns = {column["name"] for column in inspector.get_columns("credit_card_statements")}
        required_statement_columns = {
            "statement_month": "DATE",
            "total_amount_due": "NUMERIC(14, 2)",
            "minimum_amount_due": "NUMERIC(14, 2)",
            "payment_due_date": "DATE",
            "uploaded_tag": "VARCHAR(40) NOT NULL DEFAULT 'normal'",
        }
        with engine.begin() as connection:
            for column_name, column_sql in required_statement_columns.items():
                if column_name not in statement_columns:
                    connection.execute(text(f"ALTER TABLE credit_card_statements ADD COLUMN {column_name} {column_sql}"))
