# Agent Guide

## Project Summary

- Local Finance Intelligence Dashboard is an offline-first personal finance app.
- It imports local bank, UPI, credit card, and loan statements.
- It parses CSV, XLSX, and digital PDF files using local libraries only.
- It normalizes transactions into SQLite and categorizes them with editable rules.
- It provides Streamlit dashboards for spending, UPI, credit cards, loans, benchmarks, and assistant queries.
- It includes deterministic loan ledger logic for EMI, prepayment, interest, principal, and inferred rates.
- It includes local keyword/deterministic assistant behavior with optional localhost-only Ollama/local embeddings.
- It must never transmit financial data outside the local machine.

## Non-Negotiable Privacy Rules

- Do not add internet APIs, hosted AI APIs, cloud storage, telemetry, analytics, crash reporting, or external logging.
- Do not send user data to OpenAI, cloud LLMs, financial APIs, OCR services, or analytics services.
- Do not read, summarize, paste, or index private files under `data/uploads`, `data/processed`, or `data/local_db`.
- Do not include uploaded statements, database rows, secrets, account numbers, or card numbers in docs/context.
- Keep examples synthetic and masked.
- Optional AI must be local-only: localhost Ollama or local model files.

## Local-Only Constraints

- Database: local SQLite at `data/local_db/finance_dashboard.db`.
- Uploads: local disk only.
- Assistant: deterministic handlers first; optional local LLM only if URL host is `127.0.0.1`, `localhost`, or `::1`.
- Rate events and benchmarks are user-entered or uploaded locally; do not fetch RBI/SEBI/bank data.

## Tech Stack

| Area | Stack |
| --- | --- |
| Backend | Python, FastAPI, SQLAlchemy, Pydantic |
| Database | SQLite |
| Parsing/analysis | Pandas, local PDF/text libraries |
| UI | Streamlit multipage app |
| Tests | pytest |

## Start Here

1. Read [.codex/context.md]($userpathlocal-finance-dashboard/.codex/context.md).
2. Read this file.
3. Read [docs/PROJECT_CONTEXT.md]($userpathlocal-finance-dashboard/docs/PROJECT_CONTEXT.md) for product context.
4. Read [docs/FINANCE_LOGIC.md]($userpathlocal-finance-dashboard/docs/FINANCE_LOGIC.md) only for finance logic changes.
5. Read [docs/SCHEMA_SUMMARY.md]($userpathlocal-finance-dashboard/docs/SCHEMA_SUMMARY.md) only for database changes.
6. Use [.codex/module_map.yaml]($userpathlocal-finance-dashboard/.codex/module_map.yaml) to locate files/tests.

## Commands

```bash
cd $userpathlocal-finance-dashboard
source .venv/bin/activate
python -m app.init_db
python -m streamlit run dashboard/streamlit_app.py
uvicorn app.main:app --reload
pytest
python scripts/build_agent_context.py
```

## Folder Map

| Path | Purpose |
| --- | --- |
| `app/` | FastAPI app, models, services, routers, schemas |
| `dashboard/` | Streamlit multipage UI |
| `docs/` | Compact project, finance, schema, decision, roadmap docs |
| `.codex/` | Token-efficient agent context and task templates |
| `scripts/` | Local utility scripts |
| `tests/` | pytest coverage |
| `sample_data/` | Synthetic demo statements only |
| `data/` | Local runtime data; do not scan private subfolders |

## Key Modules

| Module | Files | Responsibility |
| --- | --- | --- |
| Upload/parsing | `app/services/documents.py`, `app/services/parsers/`, `dashboard/pages/1_Upload.py` | Local file ingestion, statement parsing, and safe reprocessing of existing uploads |
| Categorization | `app/services/categorization/rules.py`, `app/services/category_rules.py` | Rule-based categories and editable rules |
| Transactions | `app/services/transactions.py`, `dashboard/pages/2_Transactions.py` | Manual correction and bulk updates |
| Dashboard | `app/services/analytics/overview.py`, `dashboard/pages/3_Dashboard.py` | Overview metrics and benchmark comparison |
| Loans | `app/services/loans/`, `dashboard/pages/4_Loans.py`, `app/routers/loans.py` | Loan detection, import relinking, ledger, amortization, overrides |
| Credit cards | `app/services/credit_cards/analysis.py`, `app/services/credit_cards/service.py`, `dashboard/pages/5_Credit_Cards.py` | Card profiles, statement tags, EMI/no-cost EMI, GST/fees, UPI-card analysis, manual review |
| UPI | `app/services/analytics/upi.py`, `dashboard/pages/6_UPI_Analysis.py` | UPI receiver, spend, recurring analysis |
| Assistant | `app/services/rag/assistant.py`, `dashboard/pages/7_Assistant.py` | Local deterministic Q&A and optional local models |
| Database | `app/models/entities.py`, `app/database.py`, `app/bootstrap.py` | SQLite schema, initialization, safe local state |

## Coding Rules

- Keep changes scoped to the requested module.
- Prefer deterministic logic and explicit confidence scores.
- Manual user corrections must override automatic rules.
- Do not hide assumptions in calculations; store/show notes where relevant.
- Use type hints and small service functions.
- Avoid raw financial payloads in logs, docs, tests, or exceptions.
- Do not refactor unrelated business logic.

## Testing Rules

- Run focused tests for the changed module.
- Run full `pytest` before finishing.
- Add tests when adding behavior or schema.
- Use only synthetic fixtures from `sample_data/` or inline dummy values.
- Do not create tests that depend on private local files.

## Do-Not-Touch Rules

- Do not inspect or include `data/uploads`, `data/processed`, `data/local_db`, `.venv`, `.git`, caches, or `*.db`.
- Do not delete local runtime data unless the user explicitly asks.
- Do not add network calls except localhost-only optional local model calls already guarded in assistant code.
- Do not hardcode official financial rates or personal assumptions.

## Current Feature Status

| Area | Status |
| --- | --- |
| CSV/XLSX/PDF parsing | Implemented for common digital statements |
| Categorization rules | Implemented, editable locally |
| Hyderabad benchmarks | Implemented, editable locally |
| Loan ledger | Implemented with MBK/Loan Account Payment prepayment, LOAN RECOVERY EMI, sorted profiles/transactions, profile-schedule first opening, import summaries/relinking, inferred rates, overrides |
| Credit card analysis | Implemented: card profiles, Normal/EMI/UPI-only/Mixed statement tags, EMI plans, no-cost EMI verification, GST/processing-fee split, UPI-card separation, manual review |
| UPI analysis | Implemented for receiver extraction, daily spend, recurring payments |
| Upload reprocessing | Implemented for selected/all stored uploads so parser/logic changes reload normalized and derived rows |
| Local assistant | Implemented deterministic handlers, keyword search, optional local embeddings/Ollama |
| App memory | Schema groundwork in `assistant_memory`; future behavior must stay non-sensitive |

## Compact Context

- Primary agent context: [.codex/context.md]($userpathlocal-finance-dashboard/.codex/context.md)
- Project memory: [docs/PROJECT_CONTEXT.md]($userpathlocal-finance-dashboard/docs/PROJECT_CONTEXT.md)
- Finance rules: [docs/FINANCE_LOGIC.md]($userpathlocal-finance-dashboard/docs/FINANCE_LOGIC.md)
- Schema summary: [docs/SCHEMA_SUMMARY.md]($userpathlocal-finance-dashboard/docs/SCHEMA_SUMMARY.md)
- Generated snapshot: `.codex/generated_context.md` from `python scripts/build_agent_context.py`
