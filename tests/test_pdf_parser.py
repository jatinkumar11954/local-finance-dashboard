from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table

from app.services.parsers.pdf_parser import parse_pdf_statement


def _build_dummy_statement_pdf(file_path: Path) -> None:
    data = [
        ["Date", "Description", "Debit", "Credit", "Balance"],
        ["01/05/2026", "SALARY CREDIT ACME TECH", "", "125000.00", "185430.00"],
        ["02/05/2026", "NEFT HOUSE RENT TO LANDLORD", "28000.00", "", "157430.00"],
        ["03/05/2026", "UPI/SWIGGY/food order", "640.00", "", "156790.00"],
    ]
    document = SimpleDocTemplate(str(file_path), pagesize=letter)
    document.build([Table(data)])


def test_pdf_statement_parser_extracts_transactions(tmp_path: Path, db_session):
    pdf_path = tmp_path / "dummy_statement.pdf"
    _build_dummy_statement_pdf(pdf_path)

    parsed = parse_pdf_statement(
        file_path=pdf_path,
        session=db_session,
        source_type_override="auto",
        account_source="Primary Account",
    )

    assert parsed.document_type == "bank_statement"
    assert len(parsed.rows) == 3
    assert parsed.rows[0].transaction_type == "credit"
    assert parsed.rows[1].category == "Rent"
    assert parsed.rows[2].payment_mode == "UPI"


def test_pdf_parser_returns_user_friendly_error_for_unreadable_pdf(tmp_path: Path, db_session):
    pdf_path = tmp_path / "unreadable.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nnot a valid or extractable pdf\n")

    try:
        parse_pdf_statement(
            file_path=pdf_path,
            session=db_session,
            source_type_override="auto",
            account_source="Primary Account",
        )
    except ValueError as exc:
        assert "Could not extract text" in str(exc)
        assert "OCR is not enabled" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("Unreadable PDF should raise a user-friendly ValueError.")
