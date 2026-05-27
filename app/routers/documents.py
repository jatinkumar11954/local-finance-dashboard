from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.document import DocumentRead, DocumentUploadResponse
from app.services.documents import delete_document, ingest_document_bytes, list_documents, update_document_type


router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.get("", response_model=list[DocumentRead])
def get_documents(session: Session = Depends(get_db)) -> list[DocumentRead]:
    return [DocumentRead.from_model(document) for document in list_documents(session)]


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    account_name: str | None = Form(default=None),
    source_type_override: str | None = Form(default="auto"),
    session: Session = Depends(get_db),
) -> DocumentUploadResponse:
    try:
        content = await file.read()
        return ingest_document_bytes(
            session=session,
            filename=file.filename or "upload.csv",
            content=content,
            mime_type=file.content_type,
            account_name=account_name,
            source_type_override=source_type_override,
        )
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/{document_id}/type", response_model=DocumentRead)
def patch_document_type(
    document_id: int,
    document_type: str = Query(...),
    session: Session = Depends(get_db),
) -> DocumentRead:
    try:
        return DocumentRead.from_model(update_document_type(session, document_id, document_type))
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{document_id}", status_code=204)
def delete_uploaded_document(
    document_id: int,
    delete_file: bool = Query(default=True),
    session: Session = Depends(get_db),
) -> None:
    try:
        delete_document(session, document_id, delete_file=delete_file)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
