from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.bootstrap import bootstrap_application
from app.config import get_settings
from app.routers.assistant import router as assistant_router
from app.routers.analytics import router as analytics_router
from app.routers.benchmarks import router as benchmarks_router
from app.routers.category_rules import router as category_rules_router
from app.routers.documents import router as documents_router
from app.routers.loans import loan_transactions_router, router as loans_router
from app.routers.transactions import router as transactions_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    bootstrap_application()
    yield


settings = get_settings()
app = FastAPI(title=settings.project_name, lifespan=lifespan)
app.include_router(documents_router)
app.include_router(transactions_router)
app.include_router(analytics_router)
app.include_router(category_rules_router)
app.include_router(benchmarks_router)
app.include_router(assistant_router)
app.include_router(loans_router)
app.include_router(loan_transactions_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "local-only"}


@app.get("/")
def root() -> dict[str, str]:
    return {
        "name": settings.project_name,
        "privacy_mode": "local-only",
        "phase": "Phase 5 local assistant",
    }
