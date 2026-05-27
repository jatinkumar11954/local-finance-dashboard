from __future__ import annotations

from datetime import date
from pathlib import Path

from app.services.analytics import calculate_overview
from app.services.documents import ingest_document_bytes


def test_overview_metrics_are_generated(db_session):
    sample_file = Path(__file__).resolve().parents[1] / "sample_data" / "dummy_bank_statement.csv"
    ingest_document_bytes(
        session=db_session,
        filename=sample_file.name,
        content=sample_file.read_bytes(),
        mime_type="text/csv",
        account_name="Primary Account",
        source_type_override="auto",
    )

    overview = calculate_overview(
        session=db_session,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 31),
        benchmark_profile="Comfortable living",
    )

    assert overview.total_income == 125000.0
    assert overview.total_expenses > 0
    assert overview.transaction_count == 10
    assert any(item.label == "Rent" for item in overview.top_categories)
