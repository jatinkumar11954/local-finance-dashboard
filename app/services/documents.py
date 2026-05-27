from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.base import utcnow
from app.models.entities import Account, AuditLog, Document, LoanTransaction, Transaction
from app.schemas.document import DocumentRead, DocumentUploadResponse
from app.services.credit_cards import delete_credit_card_document_data, sync_credit_card_document
from app.services.loans import detect_and_store_loan_transactions, recalculate_loan_ledger
from app.services.parsers import parse_statement_file


DOCUMENT_TYPES = [
    "bank_statement",
    "credit_card_statement",
    "upi_statement",
    "loan_statement",
    "unknown",
]
DOCUMENT_TYPE_ALIASES = {
    "loan": "loan_statement",
}


def normalize_document_type(document_type: str | None) -> str | None:
    if not document_type:
        return document_type
    return DOCUMENT_TYPE_ALIASES.get(document_type, document_type)


def _compute_content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _persist_upload(filename: str, content: bytes) -> Path:
    settings = get_settings()
    suffix = Path(filename).suffix.lower()
    safe_name = f"{utcnow().strftime('%Y%m%d%H%M%S')}_{uuid4().hex}{suffix}"
    destination = settings.uploads_dir / safe_name
    destination.write_bytes(content)
    return destination


def _get_or_create_account(session: Session, account_name: str | None) -> Account | None:
    if not account_name:
        return None
    existing = session.scalar(select(Account).where(Account.name == account_name))
    if existing:
        return existing
    account = Account(name=account_name)
    session.add(account)
    session.flush()
    return account


def ingest_document_bytes(
    session: Session,
    filename: str,
    content: bytes,
    mime_type: str | None,
    account_name: str | None = None,
    source_type_override: str | None = None,
    credit_card_name: str | None = None,
    credit_card_bank_name: str | None = None,
    credit_card_last4: str | None = None,
    credit_card_usage_type: str | None = None,
    credit_card_uploaded_tag: str | None = None,
) -> DocumentUploadResponse:
    source_type_override = normalize_document_type(source_type_override)
    content_hash = _compute_content_hash(content)
    existing = session.scalar(select(Document).where(Document.content_hash == content_hash))
    if existing:
        raise ValueError("This exact file has already been imported.")

    stored_path = _persist_upload(filename, content)
    account = _get_or_create_account(session, account_name)

    document = Document(
        filename=filename,
        stored_path=str(stored_path),
        content_hash=content_hash,
        mime_type=mime_type,
        parsing_status="pending",
        account_id=account.id if account else None,
    )
    session.add(document)
    session.flush()

    try:
        parsed = parse_statement_file(
            file_path=stored_path,
            session=session,
            source_type_override=source_type_override,
            account_source=account_name,
        )
    except Exception:
        if stored_path.exists():
            stored_path.unlink()
        raise

    transactions: list[Transaction] = []
    for row in parsed.rows:
        transaction = Transaction(
            date=row.date,
            description=row.description,
            raw_description=row.raw_description,
            amount=row.amount,
            transaction_type=row.transaction_type,
            account_source=row.account_source or account_name,
            payment_mode=row.payment_mode,
            merchant_name=row.merchant_name,
            category=row.category,
            subcategory=row.subcategory,
            confidence_score=row.confidence_score,
            running_balance=row.running_balance,
            source_document_id=document.id,
            account_id=account.id if account else None,
        )
        session.add(transaction)
        transactions.append(transaction)
    session.flush()

    document.document_type = parsed.document_type
    document.detected_source_name = parsed.detected_source_name
    document.parsing_status = "parsed"
    document.parsing_confidence = parsed.parsing_confidence
    document.record_count = len(parsed.rows)
    document.raw_text = parsed.raw_text
    document.processed_at = utcnow()

    session.add(
        AuditLog(
            action="document_ingested",
            entity_type="document",
            entity_id=str(document.id),
            details={
                "filename": filename,
                "document_type": parsed.document_type,
                "transaction_count": len(parsed.rows),
            },
        )
    )
    loan_transaction_count = detect_and_store_loan_transactions(
        session=session,
        document=document,
        transactions=transactions,
        parsed_rows=parsed.rows,
    )
    if loan_transaction_count:
        session.add(
            AuditLog(
                action="loan_transactions_detected",
                entity_type="document",
                entity_id=str(document.id),
                details={
                    "filename": filename,
                    "loan_transaction_count": loan_transaction_count,
                },
            )
        )
    credit_card_transaction_count = sync_credit_card_document(
        session=session,
        document=document,
        transactions=transactions,
        card_name=credit_card_name,
        bank_name=credit_card_bank_name,
        last4=credit_card_last4,
        usage_type=credit_card_usage_type,
        uploaded_tag=credit_card_uploaded_tag,
    )
    if credit_card_transaction_count:
        session.add(
            AuditLog(
                action="credit_card_transactions_synced",
                entity_type="document",
                entity_id=str(document.id),
                details={
                    "filename": filename,
                    "credit_card_transaction_count": credit_card_transaction_count,
                },
            )
        )
    session.commit()
    session.refresh(document)

    return DocumentUploadResponse(
        document=DocumentRead.from_model(document),
        transaction_count=len(parsed.rows),
        message=f"Imported {len(parsed.rows)} transactions from {filename}.",
    )


def list_documents(session: Session) -> list[Document]:
    return session.scalars(select(Document).order_by(Document.uploaded_at.desc())).all()


def update_document_type(session: Session, document_id: int, document_type: str) -> Document:
    document_type = normalize_document_type(document_type) or "unknown"
    if document_type not in DOCUMENT_TYPES:
        raise ValueError(f"Unsupported document type: {document_type}")

    document = session.get(Document, document_id)
    if document is None:
        raise ValueError(f"Document {document_id} was not found.")

    previous_type = document.document_type
    document.document_type = document_type
    document.detected_source_name = document_type.replace("_", " ").title()
    session.add(
        AuditLog(
            action="document_type_updated",
            entity_type="document",
            entity_id=str(document.id),
            details={
                "filename": document.filename,
                "previous_type": previous_type,
                "new_type": document_type,
            },
        )
    )
    session.commit()
    if document.document_type == "loan_statement":
        transactions = session.scalars(
            select(Transaction).where(Transaction.source_document_id == document.id).order_by(Transaction.id.asc())
        ).all()
        detect_and_store_loan_transactions(session, document, transactions)
    if document.document_type == "credit_card_statement":
        transactions = session.scalars(
            select(Transaction).where(Transaction.source_document_id == document.id).order_by(Transaction.id.asc())
        ).all()
        sync_credit_card_document(session, document, transactions)
    session.refresh(document)
    return document


def delete_document(session: Session, document_id: int, delete_file: bool = True) -> None:
    document = session.get(Document, document_id)
    if document is None:
        raise ValueError(f"Document {document_id} was not found.")

    stored_path = Path(document.stored_path)
    filename = document.filename
    transaction_count = session.scalar(
        select(func.count(Transaction.id)).where(Transaction.source_document_id == document_id)
    )
    affected_loan_ids = {
        loan_id
        for loan_id in session.scalars(
            select(LoanTransaction.loan_id).where(LoanTransaction.source_document_id == document_id)
        ).all()
        if loan_id
    }
    delete_credit_card_document_data(session, document_id)
    session.execute(delete(LoanTransaction).where(LoanTransaction.source_document_id == document_id))
    session.execute(delete(Transaction).where(Transaction.source_document_id == document_id))
    session.delete(document)
    session.add(
        AuditLog(
            action="document_deleted",
            entity_type="document",
            entity_id=str(document_id),
            details={
                "filename": filename,
                "transactions_deleted": int(transaction_count or 0),
                "file_deleted": delete_file,
            },
        )
    )
    session.commit()

    for loan_id in affected_loan_ids:
        recalculate_loan_ledger(session, loan_id)

    if delete_file and stored_path.exists() and stored_path.is_file():
        stored_path.unlink()
