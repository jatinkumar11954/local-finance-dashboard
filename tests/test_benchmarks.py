from __future__ import annotations

from datetime import date
from pathlib import Path

from app.services.benchmarks import compare_to_benchmarks, map_transaction_category_to_benchmark
from app.services.documents import ingest_document_bytes


def test_benchmark_category_mapping_function():
    assert map_transaction_category_to_benchmark("Food Delivery") == "Food outside"
    assert map_transaction_category_to_benchmark("Rent") == "Rent / Housing"
    assert map_transaction_category_to_benchmark("Miscellaneous") is None


def test_compare_to_benchmarks_aggregates_transactions(db_session):
    sample_file = Path(__file__).resolve().parents[1] / "sample_data" / "dummy_bank_statement.csv"
    ingest_document_bytes(
        session=db_session,
        filename=sample_file.name,
        content=sample_file.read_bytes(),
        mime_type="text/csv",
        account_name="Primary Account",
        source_type_override="auto",
    )

    comparison = compare_to_benchmarks(
        session=db_session,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 31),
        city="Hyderabad",
        profile="Comfortable living",
    )
    comparison_lookup = {item["category"]: item for item in comparison}

    assert comparison_lookup["Rent / Housing"]["actual"] == 28000.0
    assert comparison_lookup["Food outside"]["actual"] == 1460.0
    assert comparison_lookup["Savings / Investments"]["actual"] == 10000.0
