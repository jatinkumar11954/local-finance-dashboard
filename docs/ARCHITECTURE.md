# Architecture Plan

## Design goals

- Local-only processing for sensitive financial data
- Simple Phase 1 MVP with clear growth paths
- Deterministic ingestion and categorization first
- Modular services so future phases do not require rewrites

## High-level architecture

- `app/`
  - FastAPI backend for local APIs and shared orchestration
  - SQLAlchemy models and SQLite persistence
  - Parser services that normalize raw statements into a common transaction shape
  - Categorization services with editable rule storage
  - Analytics services that produce dashboard-ready aggregates
- `dashboard/`
  - Streamlit multipage UI
  - Imports the same backend services directly for local-only operation
- `data/`
  - Local uploads
  - Processed assets
  - SQLite database
  - Benchmark configuration seeds
- `sample_data/`
  - Dummy statements only
- `tests/`
  - Parser, categorization, analytics, and database tests

## Core data flow

1. User uploads a file in Streamlit or through FastAPI.
2. The file is written to `data/uploads/` and hashed locally.
3. A `documents` row is created with metadata and parsing state.
4. The parser detects a compatible tabular format and maps raw columns to canonical fields.
5. Each row is normalized with:
   - parsed date
   - normalized amount
   - debit or credit inference
   - payment mode inference
   - merchant extraction
   - rule-based category assignment
6. Normalized rows are written into `transactions`.
7. Loan-like rows are classified into `loan_transactions` and linked automatically when a single active loan exists.
8. Loan ledger recalculation writes transparent monthly rows into `loan_monthly_ledger`.
9. Analytics services aggregate the same local tables for dashboard charts and benchmarks.

## Database shape

The schema already includes the full target domain:

- `documents`
- `accounts`
- `transactions`
- `categories`
- `category_rules`
- `merchants`
- `loans`
- `loan_payments`
- `loan_transactions`
- `loan_monthly_ledger`
- `loan_rate_events`
- `loan_manual_overrides`
- `credit_cards`
- `credit_card_statements`
- `credit_card_transactions`
- `credit_card_emi_plans`
- `credit_card_emi_charges`
- `recurring_transactions`
- `benchmarks`
- `assistant_queries`
- `audit_log`

Phase 1 actively uses `documents`, `accounts`, `transactions`, `categories`, `category_rules`, `benchmarks`, and `audit_log`.

## Why Streamlit for MVP

- Faster path to a working local desktop-style workflow
- Good fit for review-heavy personal finance tables and charts
- Lets the project spend complexity budget on ingestion quality instead of frontend plumbing

## Phase plan

### Phase 1

- Project setup
- Local SQLite initialization
- CSV and XLSX upload
- Basic transaction normalization
- Basic categorization
- Basic dashboard

### Phase 2

- PDF parsing via local libraries only
- Better Indian transaction normalization heuristics
- Editable local category rules with re-application
- Editable benchmark UI
- Manual correction improvements including bulk updates

### Phase 3

- Loan calculator
- Amortization schedules
- Prepayment impact analysis
- Saved local loan profiles

### Phase 4

- Credit card statement analysis with card profiles and statement tags
- Credit-card EMI lifecycle tracking and no-cost EMI true-cost verification
- Credit card fee/GST/interest/processing-fee heuristics
- UPI-only and mixed card analysis kept separate from normal card shopping
- UPI deep-dive analytics and repeated-payment detection

### Phase 5

- Local assistant with keyword search and SQL-first answers
- Optional local embeddings

### Phase 6

- Stronger hardening and packaging
- Broader tests
- Backup and restore workflows

## Security posture in Phase 1

- No external APIs or telemetry in code
- Local file persistence only
- Optional local password gate in Streamlit
- Minimal audit trail without raw financial payload logging
- Account and card masking utilities ready for later forms

## Phase 2 additions

- PDF parsing uses only local libraries such as `pdfplumber` and `pypdf`
- CSV/XLSX and PDF feed the same normalization and categorization pipeline
- Rule edits and benchmark edits are persisted locally in SQLite
- Manual review can update transactions in bulk and re-run categorization rules locally

## Phase 3 and 4 additions

- Home-loan calculations are deterministic and local-only, with no advice or external pricing inputs
- Loan ingestion detects MBK prepayments, LOAN RECOVERY EMI rows, interest, fees, and loan charges without external services
- Monthly loan ledger rows record calculation method, confidence, inferred rates, and manual overrides
- Credit card analysis is derived from normalized transactions plus local card/statement metadata
- Credit card uploads can create or link card profiles and persist Normal/EMI/UPI-only/Mixed tags
- EMI plans track monthly EMI, pending/total counts, no-cost status, processing-fee status, linked charges, and manual review
- No-cost EMI checks use explicit local statement evidence for interest, reversals, cashback/discount, GST, and processing fees; missing processing fee is marked unknown, not zero
- UPI analysis uses local merchant extraction and recurring-pattern heuristics over stored transactions

## Known MVP tradeoffs

- No encryption-at-rest yet
- PDF parsing currently targets digital PDFs with extractable text or tables
- Streamlit pages call shared services directly instead of only via HTTP to preserve offline simplicity
