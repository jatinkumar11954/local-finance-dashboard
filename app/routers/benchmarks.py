from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.benchmark import BenchmarkRead, BenchmarkUpdate
from app.services.benchmarks import list_benchmarks, update_benchmark


router = APIRouter(prefix="/api/benchmarks", tags=["benchmarks"])


@router.get("", response_model=list[BenchmarkRead])
def get_benchmarks(
    city: str = Query(default="Hyderabad"),
    profile: str | None = Query(default=None),
    session: Session = Depends(get_db),
) -> list[BenchmarkRead]:
    benchmarks = list_benchmarks(session, city=city, profile=profile)
    return [BenchmarkRead.model_validate(benchmark) for benchmark in benchmarks]


@router.patch("/{benchmark_id}", response_model=BenchmarkRead)
def patch_benchmark(
    benchmark_id: int,
    payload: BenchmarkUpdate,
    session: Session = Depends(get_db),
) -> BenchmarkRead:
    try:
        benchmark = update_benchmark(
            session=session,
            benchmark_id=benchmark_id,
            min_amount=payload.min_amount,
            max_amount=payload.max_amount,
            is_active=payload.is_active,
        )
        return BenchmarkRead.model_validate(benchmark)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
