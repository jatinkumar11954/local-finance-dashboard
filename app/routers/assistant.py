from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.assistant import AssistantQueryRequest, AssistantResponse
from app.services.rag import answer_local_finance_query


router = APIRouter(prefix="/api/assistant", tags=["assistant"])


@router.post("/ask", response_model=AssistantResponse)
def post_assistant_query(
    payload: AssistantQueryRequest,
    session: Session = Depends(get_db),
) -> AssistantResponse:
    return answer_local_finance_query(
        session=session,
        question=payload.question,
        start_date=payload.start_date,
        end_date=payload.end_date,
        use_local_embeddings=payload.use_local_embeddings,
        use_local_llm=payload.use_local_llm,
    )
