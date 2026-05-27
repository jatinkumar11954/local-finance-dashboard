from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BenchmarkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    city: str
    profile: str
    category: str
    min_amount: float
    max_amount: float
    currency: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class BenchmarkUpdate(BaseModel):
    min_amount: float | None = Field(default=None, ge=0)
    max_amount: float | None = Field(default=None, ge=0)
    is_active: bool | None = None
