from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.services.parsers.tabular_parser import parse_tabular_dataframe
from app.services.parsers.tabular_parser import parse_tabular_statement


def test_tabular_parser_extracts_transactions(db_session):
    sample_file = Path(__file__).resolve().parents[1] / "sample_data" / "dummy_bank_statement.csv"

    parsed = parse_tabular_statement(
        file_path=sample_file,
        session=db_session,
        source_type_override="auto",
        account_source="Primary Account",
    )

    assert parsed.document_type == "bank_statement"
    assert len(parsed.rows) == 10
    assert parsed.rows[0].transaction_type == "credit"
    assert parsed.rows[1].category == "Rent"
    assert parsed.rows[2].payment_mode == "UPI"


def test_tabular_parser_skips_invalid_scientific_notation_amounts(db_session, tmp_path):
    sample_path = tmp_path / "invalid_amounts.csv"
    sample_path.write_text(
        "date,description,amount\n"
        "2026-05-01,SALARY CREDIT,125000\n"
        "2026-05-02,OFFUS EMI,9.999999980513001e+21\n",
        encoding="utf-8",
    )

    parsed = parse_tabular_statement(
        file_path=sample_path,
        session=db_session,
        source_type_override="bank_statement",
        account_source="Primary Account",
    )

    assert len(parsed.rows) == 1
    assert parsed.rows[0].amount == 125000


def test_credit_card_upi_table_uses_final_rupee_amount_not_reward_points(db_session):
    dataframe = pd.DataFrame(
        [
            {
                "Date": "05/04/2026",
                "SerNo.": "13177133111",
                "Transaction Details": "UPI-303541940118-JAI DURG A MAA APNA TA IN",
                "Reward Points": "1",
                "Intl.# amount": "",
                "Amount (in₹)": "180.00",
            },
            {
                "Date": "12/04/2026",
                "SerNo.": "13214289619",
                "Transaction Details": "UPI-035395113383-Airtel Payments Bank IN",
                "Reward Points": "15",
                "Intl.# amount": "",
                "Amount (in₹)": "1,500.00",
            },
        ]
    )

    parsed = parse_tabular_dataframe(
        dataframe=dataframe,
        session=db_session,
        source_type_override="credit_card_statement",
        account_source="UPI Card",
        file_path=Path("card_statement.pdf"),
    )

    assert [row.amount for row in parsed.rows] == [180, 1500]
    assert all(row.payment_mode == "UPI" for row in parsed.rows)
