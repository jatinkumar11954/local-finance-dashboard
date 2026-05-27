from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from app.models.entities import Document, Transaction
from app.services.documents import delete_document, ingest_document_bytes, update_document_type


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
