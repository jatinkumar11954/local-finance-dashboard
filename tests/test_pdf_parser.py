from __future__ import annotations

from pathlib import Path

import pandas as pd
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table

import app.services.parsers.pdf_parser as pdf_parser
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


def test_credit_card_pdf_ignores_suspicious_tiny_table_amounts(tmp_path: Path, db_session, monkeypatch):
    pdf_path = tmp_path / "card_statement.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nsynthetic placeholder\n")

    tiny_table = pd.DataFrame(
        [
            {
                "date": f"{day:02d}/05/2026",
                "description": f"POS/SHOP {day}",
                "debit": "1.00",
                "credit": "",
                "balance": "100.00",
            }
            for day in range(1, 31)
        ]
    )
    raw_text = "\n".join(
        f"{day:02d}/05/2026 POS/SHOP {day} 100.00 900.00"
        for day in range(1, 31)
    )

    monkeypatch.setattr(pdf_parser, "_extract_pdf_tables", lambda _: [tiny_table])
    monkeypatch.setattr(pdf_parser, "_extract_text_with_pdfplumber", lambda _: raw_text)
    monkeypatch.setattr(pdf_parser, "_extract_text_with_pypdf", lambda _: "")

    parsed = parse_pdf_statement(
        file_path=pdf_path,
        session=db_session,
        source_type_override="auto",
        account_source="UPI Card",
    )

    assert parsed.document_type == "credit_card_statement"
    assert len(parsed.rows) == 30
    assert sum(row.amount for row in parsed.rows) == 3000


def test_credit_card_upi_text_fallback_uses_last_rupee_amount_not_reward_points(tmp_path: Path, db_session, monkeypatch):
    pdf_path = tmp_path / "upi_card_statement.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nsynthetic placeholder\n")
    raw_text = "\n".join(
        [
            "Date SerNo. Transaction Details Reward Points Intl.# amount Amount (in₹)",
            "05/04/2026 13177133111 UPI-303541940118-JAI DURG A MAA APNA TA IN 1 180.00",
            "12/04/2026 13214289619 UPI-035395113383-Airtel Payments Bank IN 15 1,500.00",
        ]
    )

    monkeypatch.setattr(pdf_parser, "_extract_pdf_tables", lambda _: [])
    monkeypatch.setattr(pdf_parser, "_extract_text_with_pdfplumber", lambda _: raw_text)
    monkeypatch.setattr(pdf_parser, "_extract_text_with_pypdf", lambda _: "")

    parsed = parse_pdf_statement(
        file_path=pdf_path,
        session=db_session,
        source_type_override="credit_card_statement",
        account_source="UPI Card",
    )

    assert len(parsed.rows) == 2
    assert [row.amount for row in parsed.rows] == [180, 1500]
    assert [row.payment_mode for row in parsed.rows] == ["UPI", "UPI"]


def test_loan_pdf_table_parser_handles_bilingual_multipage_headers(tmp_path: Path, db_session, monkeypatch):
    pdf_path = tmp_path / "loan_statement.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nsynthetic placeholder\n")

    header_hindi = ["क्र.सं", "लेनदेन की तारीख", "प्रभाव तारीख", "विवरण", "चेक नंबर", "नामे", "जमा", "शेष"]
    header_english = ["Sr.No", "Transaction Date", "Value Date", "Description", "Cheque Number", "Debit", "Credit", "Balance"]
    page_1_rows = [
        header_hindi,
        header_english,
        ["1", "08-11-2025", "", "Opening Balance", "", "-", "-", "8,55,231.88"],
        ["2", "08-11-2025", "08-11-2025", "NEFT-KKBKH25312998525-SYNTHETIC USER", "", "-", "50,000.00", "9,05,231.88"],
        ["3", "10-11-2025", "10-11-2025", "Loan Recovery For1234", "", "25,204.00", "-", "8,80,027.88"],
        ["4", "10-11-2025", "10-11-2025", "MBK/531483715294/ToLoan/1234/", "", "10,000.00", "-", "8,70,027.88"],
        ["5", "10-11-2025", "10-11-2025", "MBK/531483727123/ToLoan/1234/", "", "2,398.00", "-", "8,67,629.88"],
        ["6", "07-12-2025", "07-12-2025", "Loan Account Payments For :1234", "", "40,000.00", "-", "8,27,629.88"],
        ["7", "08-12-2025", "08-12-2025", "NEFT-KKBKH25342934866-SYNTHETIC USER", "", "-", "50,000.00", "8,77,629.88"],
    ]
    page_2_rows = [
        header_hindi,
        header_english,
        ["8", "10-12-2025", "10-12-2025", "Loan Recovery For1234", "", "25,204.00", "-", "8,52,425.88"],
        ["9", "10-12-2025", "10-12-2025", "MBK/534401099409/ToLoan/1234/", "", "10,000.00", "-", "8,42,425.88"],
        ["10", "08-01-2026", "08-01-2026", "NEFT-KKBKH26008638305-SYNTHETIC USER", "", "-", "50,000.00", "8,92,425.88"],
        ["11", "10-01-2026", "10-01-2026", "Loan Recovery For1234", "", "27,602.00", "-", "8,64,823.88"],
    ]

    monkeypatch.setattr(
        pdf_parser,
        "_extract_pdf_tables",
        lambda _: [pdf_parser._rows_to_dataframe(page_1_rows), pdf_parser._rows_to_dataframe(page_2_rows)],
    )
    monkeypatch.setattr(pdf_parser, "_extract_text_with_pdfplumber", lambda _: "synthetic extractable text")
    monkeypatch.setattr(pdf_parser, "_extract_text_with_pypdf", lambda _: "")

    parsed = parse_pdf_statement(
        file_path=pdf_path,
        session=db_session,
        source_type_override="loan_statement",
        account_source="Loan Source",
    )

    assert parsed.document_type == "loan_statement"
    assert len(parsed.rows) == 10
    assert [row.raw_description for row in parsed.rows if row.raw_description.startswith("Loan Recovery")] == [
        "Loan Recovery For1234",
        "Loan Recovery For1234",
        "Loan Recovery For1234",
    ]
    assert all(
        row.payment_mode == "EMI"
        for row in parsed.rows
        if row.raw_description.startswith("Loan Recovery") or "ToLoan" in row.raw_description
    )
    assert sum(row.amount for row in parsed.rows if row.transaction_type == "debit") == 140408
    assert sum(row.amount for row in parsed.rows if row.transaction_type == "credit") == 150000
    assert [row.date for row in parsed.rows] == sorted(row.date for row in parsed.rows)


def test_loan_pdf_text_fallback_handles_rows_starting_with_serial_number(tmp_path: Path, db_session, monkeypatch):
    pdf_path = tmp_path / "loan_text_statement.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nsynthetic placeholder\n")
    raw_text = "\n".join(
        [
            "Sr.No Transaction Date Value Date Description Cheque Number Debit Credit Balance",
            "1 08-11-2025 Opening Balance - - 8,55,231.88",
            "2 08-11-2025 08-11-2025 NEFT-KKBKH25312998525-SYNTHETIC USER - 50,000.00 9,05,231.88",
            "3 10-11-2025 10-11-2025 Loan Recovery For1234 25,204.00 - 8,80,027.88",
            "4 10-11-2025 10-11-2025 MBK/531483715294/ToLoan/1234/ 10,000.00 - 8,70,027.88",
            "5 10-11-2025 10-11-2025 MBK/531483727123/ToLoan/1234/ 2,398.00 - 8,67,629.88",
            "6 07-12-2025 07-12-2025 Loan Account Payments For :1234 40,000.00 - 8,27,629.88",
            "7 08-12-2025 08-12-2025 NEFT-KKBKH25342934866-SYNTHETIC USER - 50,000.00 8,77,629.88",
            "8 10-12-2025 10-12-2025 Loan Recovery For1234 25,204.00 - 8,52,425.88",
            "9 10-12-2025 10-12-2025 MBK/534401099409/ToLoan/1234/ 10,000.00 - 8,42,425.88",
            "10 08-01-2026 08-01-2026 NEFT-KKBKH26008638305-SYNTHETIC USER - 50,000.00 8,92,425.88",
            "11 10-01-2026 10-01-2026 Loan Recovery For1234 27,602.00 - 8,64,823.88",
        ]
    )

    monkeypatch.setattr(pdf_parser, "_extract_pdf_tables", lambda _: [])
    monkeypatch.setattr(pdf_parser, "_extract_text_with_pdfplumber", lambda _: raw_text)
    monkeypatch.setattr(pdf_parser, "_extract_text_with_pypdf", lambda _: "")

    parsed = parse_pdf_statement(
        file_path=pdf_path,
        session=db_session,
        source_type_override="loan_statement",
        account_source="Loan Source",
    )

    assert len(parsed.rows) == 10
    assert parsed.rows[0].transaction_type == "credit"
    assert parsed.rows[-1].amount == 27602
    assert sum(row.amount for row in parsed.rows if row.transaction_type == "debit") == 140408
