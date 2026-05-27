from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.services.parsers.models import ParsedDocument
from app.services.parsers.pdf_parser import parse_pdf_statement
from app.services.parsers.tabular_parser import parse_tabular_statement


def parse_statement_file(
    file_path: Path,
    session: Session,
    source_type_override: str | None = None,
    account_source: str | None = None,
) -> ParsedDocument:
    suffix = file_path.suffix.lower()
    if suffix in {".csv", ".xlsx", ".xls"}:
        return parse_tabular_statement(
            file_path=file_path,
            session=session,
            source_type_override=source_type_override,
            account_source=account_source,
        )
    if suffix == ".pdf":
        return parse_pdf_statement(
            file_path=file_path,
            session=session,
            source_type_override=source_type_override,
            account_source=account_source,
        )
    raise ValueError(f"Unsupported file type: {suffix}")
