from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from app.models.entities import Document, Transaction
from app.services.documents import delete_document, ingest_document_bytes, reprocess_document, update_document_type


def test_document_type_can_be_updated_for_existing_upload(db_session):
    sample_file = Path(__file__).resolve().parents[1] / "sample_data" / "dummy_bank_statement.csv"
    response = ingest_document_bytes(
        session=db_session,
        filename=sample_file.name,
        content=sample_file.read_bytes(),
        mime_type="text/csv",
        account_name="Primary Account",
        source_type_override="bank_statement",
    )

    updated = update_document_type(db_session, response.document.id, "credit_card_statement")

    assert updated.document_type == "credit_card_statement"
    assert db_session.get(Document, response.document.id).document_type == "credit_card_statement"


def test_document_delete_removes_transactions_and_local_file(db_session):
    sample_file = Path(__file__).resolve().parents[1] / "sample_data" / "dummy_bank_statement.csv"
    response = ingest_document_bytes(
        session=db_session,
        filename=sample_file.name,
        content=sample_file.read_bytes(),
        mime_type="text/csv",
        account_name="Primary Account",
        source_type_override="bank_statement",
    )
    document = db_session.get(Document, response.document.id)
    stored_path = Path(document.stored_path)
    assert stored_path.exists()
    assert db_session.scalars(select(Transaction).where(Transaction.source_document_id == document.id)).first()

    delete_document(db_session, document.id)

    assert db_session.get(Document, document.id) is None
    assert not stored_path.exists()
    assert db_session.scalars(select(Transaction).where(Transaction.source_document_id == document.id)).first() is None


def test_document_reprocess_reloads_transactions_without_duplicates(db_session):
    sample_file = Path(__file__).resolve().parents[1] / "sample_data" / "dummy_bank_statement.csv"
    response = ingest_document_bytes(
        session=db_session,
        filename=sample_file.name,
        content=sample_file.read_bytes(),
        mime_type="text/csv",
        account_name="Primary Account",
        source_type_override="bank_statement",
    )
    document_id = response.document.id
    rows_before = db_session.scalars(
        select(Transaction).where(Transaction.source_document_id == document_id).order_by(Transaction.id.asc())
    ).all()
    assert len(rows_before) == response.transaction_count

    first_original_amount = rows_before[0].amount
    rows_before[0].amount = Decimal("1.00")
    db_session.commit()

    reprocessed = reprocess_document(db_session, document_id)
    rows_after = db_session.scalars(
        select(Transaction).where(Transaction.source_document_id == document_id).order_by(Transaction.id.asc())
    ).all()
    document = db_session.get(Document, document_id)

    assert reprocessed.transaction_count == response.transaction_count
    assert len(rows_after) == response.transaction_count
    assert document.record_count == response.transaction_count
    assert rows_after[0].amount == first_original_amount
