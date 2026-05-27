from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.category_rule import (
    CategoryRuleCreate,
    CategoryRuleRead,
    CategoryRuleUpdate,
    ReapplyRulesRequest,
    ReapplyRulesResponse,
)
from app.services.category_rules import (
    create_category_rule,
    delete_category_rule,
    list_category_rules,
    reapply_category_rules,
    update_category_rule,
)


router = APIRouter(prefix="/api/category-rules", tags=["category-rules"])


@router.get("", response_model=list[CategoryRuleRead])
def get_category_rules(session: Session = Depends(get_db)) -> list[CategoryRuleRead]:
    return [CategoryRuleRead.model_validate(rule) for rule in list_category_rules(session)]


@router.post("", response_model=CategoryRuleRead)
def post_category_rule(payload: CategoryRuleCreate, session: Session = Depends(get_db)) -> CategoryRuleRead:
    return CategoryRuleRead.model_validate(create_category_rule(session, payload))


@router.patch("/{rule_id}", response_model=CategoryRuleRead)
def patch_category_rule(
    rule_id: int,
    payload: CategoryRuleUpdate,
    session: Session = Depends(get_db),
) -> CategoryRuleRead:
    try:
        return CategoryRuleRead.model_validate(update_category_rule(session, rule_id, payload))
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{rule_id}", status_code=204)
def remove_category_rule(rule_id: int, session: Session = Depends(get_db)) -> None:
    try:
        delete_category_rule(session, rule_id)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/reapply", response_model=ReapplyRulesResponse)
def post_reapply_rules(payload: ReapplyRulesRequest, session: Session = Depends(get_db)) -> ReapplyRulesResponse:
    updated_count = reapply_category_rules(
        session=session,
        transaction_ids=payload.transaction_ids,
        start_date=payload.start_date,
        end_date=payload.end_date,
        document_id=payload.document_id,
        only_low_confidence=payload.only_low_confidence,
    )
    return ReapplyRulesResponse(updated_count=updated_count)
