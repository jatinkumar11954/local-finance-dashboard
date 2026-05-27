from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from app.services.parsers.models import ParsedDocument
from app.services.parsers.tabular_parser import HEADER_ALIASES, _normalize_header, parse_tabular_dataframe

try:
    import pdfplumber
except ImportError:  # pragma: no cover - handled at runtime when dependency missing
    pdfplumber = None

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover - handled at runtime when dependency missing
    PdfReader = None


DATE_PREFIX_PATTERN = re.compile(
    r"^(?P<date>\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2}|\d{1,2}\s+[A-Za-z]{3}\s+\d{2,4})\b"
)
AMOUNT_PATTERN = re.compile(r"^[(-]?(?:INR|Rs\.?)?\s*[\d,]+(?:\.\d{1,2})?[)]?\s*(?:CR|DR)?$", re.IGNORECASE)


def _normalize_cell(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _looks_like_date(value: str) -> bool:
    return bool(DATE_PREFIX_PATTERN.match(value.strip()))


def _looks_like_amount(value: str) -> bool:
    candidate = value.strip()
    if not candidate:
        return False
    return bool(AMOUNT_PATTERN.match(candidate))


def _infer_transaction_type_from_description(description: str) -> str:
    normalized = description.lower()
    credit_hints = [
        "salary",
        "credit",
        "refund",
        "cashback",
        "interest credit",
        "cash deposit",
        "deposit",
        "reversal",
        "inward",
    ]
    if any(hint in normalized for hint in credit_hints):
        return "credit"
    return "debit"


def _looks_like_header_row(row: list[str]) -> bool:
    normalized_row = [_normalize_header(cell) for cell in row]
    header_hits = 0
    for aliases in HEADER_ALIASES.values():
        alias_set = {_normalize_header(alias) for alias in aliases}
        if any(cell in alias_set for cell in normalized_row):
            header_hits += 1
    return header_hits >= 2


def _rows_to_dataframe(rows: list[list[str]]) -> pd.DataFrame | None:
    clean_rows = [
        [_normalize_cell(cell) for cell in row]
        for row in rows
        if row and any(_normalize_cell(cell) for cell in row)
    ]
    if len(clean_rows) < 2:
        return None

    if _looks_like_header_row(clean_rows[0]):
        headers = [_normalize_header(cell) or f"column_{index}" for index, cell in enumerate(clean_rows[0])]
        padded_rows = []
        for row in clean_rows[1:]:
            normalized_row = row[: len(headers)] + [""] * max(0, len(headers) - len(row))
            if normalized_row and _normalize_header(normalized_row[0]) == headers[0]:
                continue
            padded_rows.append(normalized_row)
        return pd.DataFrame(padded_rows, columns=headers)

    structured_records: list[dict[str, str]] = []
    for row in clean_rows:
        if not _looks_like_date(row[0]):
            continue

        if len(row) >= 6 and _looks_like_date(row[1]):
            description = " ".join(part for part in row[2:-3] if part)
            structured_records.append(
                {
                    "date": row[0],
                    "value date": row[1],
                    "description": description,
                    "debit": row[-3],
                    "credit": row[-2],
                    "balance": row[-1],
                }
            )
            continue

        if len(row) >= 5:
            description = " ".join(part for part in row[1:-3] if part)
            structured_records.append(
                {
                    "date": row[0],
                    "description": description,
                    "debit": row[-3],
                    "credit": row[-2],
                    "balance": row[-1],
                }
            )
            continue

        if len(row) == 4:
            structured_records.append(
                {
                    "date": row[0],
                    "description": row[1],
                    "amount": row[2],
                    "balance": row[3],
                }
            )

    if not structured_records:
        return None
    return pd.DataFrame.from_records(structured_records)


def _extract_text_with_pdfplumber(file_path: Path) -> str:
    if pdfplumber is None:
        return ""
    page_text: list[str] = []
    try:
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                if text:
                    page_text.append(text)
    except Exception:
        return ""
    return "\n".join(page_text)


def _extract_text_with_pypdf(file_path: Path) -> str:
    if PdfReader is None:
        return ""
    try:
        reader = PdfReader(str(file_path))
        if reader.is_encrypted:
            return ""
        page_text = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if text:
                page_text.append(text)
    except Exception:
        return ""
    return "\n".join(page_text)


def _extract_pdf_tables(file_path: Path) -> list[pd.DataFrame]:
    if pdfplumber is None:
        return []

    dataframes: list[pd.DataFrame] = []
    try:
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables() or []:
                    dataframe = _rows_to_dataframe(table)
                    if dataframe is not None and not dataframe.empty:
                        dataframes.append(dataframe)
    except Exception:
        return []
    return dataframes


def _group_text_lines(raw_text: str) -> list[str]:
    grouped_lines: list[str] = []
    buffer = ""

    for raw_line in raw_text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        if DATE_PREFIX_PATTERN.match(line):
            if buffer:
                grouped_lines.append(buffer)
            buffer = line
        elif buffer:
            buffer = f"{buffer} {line}"
    if buffer:
        grouped_lines.append(buffer)
    return grouped_lines


def _line_to_record(line: str) -> dict[str, str] | None:
    date_match = DATE_PREFIX_PATTERN.match(line)
    if not date_match:
        return None
    date_token = date_match.group("date")

    parts = [part.strip() for part in re.split(r"\s{2,}|\t+", line) if part.strip()]
    first_part = parts[0] if parts else date_token
    if not _looks_like_date(first_part):
        first_part = date_token

    if len(parts) >= 5 and _looks_like_amount(parts[-1]):
        if len(parts) >= 6 and _looks_like_date(parts[1]):
            return {
                "date": first_part,
                "value date": parts[1],
                "description": " ".join(parts[2:-3]),
                "debit": parts[-3],
                "credit": parts[-2],
                "balance": parts[-1],
            }
        return {
            "date": first_part,
            "description": " ".join(parts[1:-3]),
            "debit": parts[-3],
            "credit": parts[-2],
            "balance": parts[-1],
        }

    if len(parts) == 4 and _looks_like_amount(parts[-1]):
        return {
            "date": first_part,
            "description": parts[1],
            "amount": parts[2],
            "balance": parts[3],
            "type": _infer_transaction_type_from_description(parts[1]),
        }

    trailing_amounts = re.findall(r"(?:INR|Rs\.?)?\s*[\d,]+(?:\.\d{1,2})?\s*(?:CR|DR)?", line, flags=re.IGNORECASE)
    if len(trailing_amounts) >= 2:
        last_amount = trailing_amounts[-1].strip()
        txn_amount = trailing_amounts[-2].strip()
        amount_start = line.rfind(txn_amount)
        description = line[date_match.end() : amount_start].strip()
        return {
            "date": date_token,
            "description": description,
            "amount": txn_amount,
            "balance": last_amount,
            "type": _infer_transaction_type_from_description(description),
        }

    return None


def _extract_text_dataframe(raw_text: str) -> pd.DataFrame | None:
    records = [record for line in _group_text_lines(raw_text) if (record := _line_to_record(line))]
    if not records:
        return None
    return pd.DataFrame.from_records(records)


def parse_pdf_statement(
    file_path: Path,
    session: Session,
    source_type_override: str | None = None,
    account_source: str | None = None,
) -> ParsedDocument:
    if pdfplumber is None and PdfReader is None:
        raise ValueError("PDF parsing dependencies are not installed. Install local PDF libraries to enable Phase 2 PDF support.")

    raw_text = _extract_text_with_pdfplumber(file_path)
    if not raw_text:
        raw_text = _extract_text_with_pypdf(file_path)
    if not raw_text:
        raise ValueError(
            "Could not extract text from this PDF. It may be encrypted, password-protected, corrupted, or scanned. "
            "Upload an unlocked digital PDF, CSV, or XLSX export. OCR is not enabled."
        )

    parsed_rows = []
    best_confidence = 0.0
    detected_document_type = "unknown"
    detected_source_name: str | None = None

    for dataframe in _extract_pdf_tables(file_path):
        try:
            parsed = parse_tabular_dataframe(
                dataframe=dataframe,
                session=session,
                source_type_override=source_type_override,
                account_source=account_source,
                file_path=file_path,
                raw_text=raw_text,
            )
        except ValueError:
            continue
        parsed_rows.extend(parsed.rows)
        best_confidence = max(best_confidence, parsed.parsing_confidence)
        detected_document_type = parsed.document_type
        detected_source_name = parsed.detected_source_name

    if parsed_rows:
        return ParsedDocument(
            document_type=detected_document_type,
            parsing_confidence=min(round(best_confidence + 0.05, 2), 0.99),
            detected_source_name=detected_source_name,
            rows=parsed_rows,
            raw_text=raw_text,
        )

    fallback_dataframe = _extract_text_dataframe(raw_text)
    if fallback_dataframe is not None and not fallback_dataframe.empty:
        parsed = parse_tabular_dataframe(
            dataframe=fallback_dataframe,
            session=session,
            source_type_override=source_type_override,
            account_source=account_source,
            file_path=file_path,
            raw_text=raw_text,
        )
        parsed.parsing_confidence = max(min(parsed.parsing_confidence - 0.1, 0.9), 0.4)
        return parsed

    raise ValueError("Could not parse transactions from this PDF. Try a digital statement export with visible transaction tables.")
