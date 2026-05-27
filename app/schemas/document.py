from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.entities import Document


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    stored_path: str
    mime_type: str | None
    document_type: str
    detected_source_name: str | None
    parsing_status: str
    parsing_confidence: float
    record_count: int
    uploaded_at: datetime
    processed_at: datetime | None

    @classmethod
    def from_model(cls, document: Document) -> "DocumentRead":
        return cls.model_validate(document)


class DocumentUploadResponse(BaseModel):
    document: DocumentRead
    transaction_count: int
    message: str
