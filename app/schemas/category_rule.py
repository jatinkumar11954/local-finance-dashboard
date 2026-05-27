from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class CategoryRuleBase(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    pattern: str = Field(min_length=1, max_length=255)
    field_name: str = Field(default="description", max_length=50)
    target_category: str = Field(min_length=2, max_length=100)
    target_subcategory: str | None = Field(default=None, max_length=100)
    priority: int = Field(default=50, ge=0, le=1000)
    is_regex: bool = True
    case_sensitive: bool = False
    is_active: bool = True


class CategoryRuleCreate(CategoryRuleBase):
    pass


class CategoryRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    pattern: str | None = Field(default=None, min_length=1, max_length=255)
    field_name: str | None = Field(default=None, max_length=50)
    target_category: str | None = Field(default=None, min_length=2, max_length=100)
    target_subcategory: str | None = Field(default=None, max_length=100)
    priority: int | None = Field(default=None, ge=0, le=1000)
    is_regex: bool | None = None
    case_sensitive: bool | None = None
    is_active: bool | None = None


class CategoryRuleRead(CategoryRuleBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class ReapplyRulesRequest(BaseModel):
    transaction_ids: list[int] | None = None
    start_date: date | None = None
    end_date: date | None = None
    document_id: int | None = None
    only_low_confidence: bool = False


class ReapplyRulesResponse(BaseModel):
    updated_count: int
