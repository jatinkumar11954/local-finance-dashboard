from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class AssistantTransactionEvidence(BaseModel):
    transaction_id: int
    date: date
    amount: float
    transaction_type: str
    category: str
    merchant_name: str | None
    payment_mode: str
    description: str
    source_document_id: int | None


class AssistantDocumentEvidence(BaseModel):
    document_id: int
    filename: str
    document_type: str
    snippet: str | None


class AssistantQueryRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    start_date: date | None = None
    end_date: date | None = None
    use_local_embeddings: bool = False
    use_local_llm: bool = False


class AssistantResponse(BaseModel):
    answer: str
    date_range_start: date | None
    date_range_end: date | None
    supporting_transactions: list[AssistantTransactionEvidence]
    supporting_documents: list[AssistantDocumentEvidence]
    calculation_method: str
    confidence_level: str
    confidence_score: float
    data_available: bool
    handler: str
    used_local_embeddings: bool
    used_local_llm: bool = False
    local_llm_model: str | None = None
