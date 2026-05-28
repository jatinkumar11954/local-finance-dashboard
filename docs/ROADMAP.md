# Roadmap

## Completed

- Local SQLite app initialization.
- Streamlit multipage MVP.
- CSV, XLSX, and digital PDF parsing.
- Transaction normalization and manual review.
- Editable categorization rules.
- Hyderabad benchmark comparison.
- Loan profiles, amortization, prepayment scenarios.
- Loan ingestion with EMI/prepayment separation, floating-rate monthly actuals, base-rate variance, actual-vs-projected tables, profile-schedule first opening, import summaries/relinking, monthly ledger, inferred rates, overrides.
- Credit card profiles, Normal/EMI/UPI-only/Mixed statement tags, EMI lifecycle plans, no-cost EMI verification, GST/processing-fee split, UPI-card separation, and manual review.
- Upload reprocessing for selected/all locally stored files after parser/logic changes.
- UPI daily spend, amount/count metrics, top receivers, repeated payments, and parser-quality warnings.
- Local assistant with deterministic handlers, keyword search, optional local embeddings/Ollama.
- Compact agent context and schema memory.

## In Progress

- More robust parser profiles for varied Indian statements.
- Better manual correction reuse through `assistant_memory`.
- More institution-specific credit-card PDF schedule extraction profiles.

## Next

- Add user-approved assistant memory write/read service.
- Add split-transaction editing UI.
- Add deterministic institution-specific parser profiles.
- Improve loan statement parsing for richer amortization exports.
- Add backup/restore workflow for local DB and uploaded files.

## Later

- Optional local OCR integration.
- Optional local database encryption.
- Richer account/card/loan mapping UI and bulk card statement retagging.
- Export reports to local files.
- Local-only semantic search with packaged model checks.

## Technical Debt

- Replace ad hoc SQLite schema extensions with a lightweight migration pattern.
- Add transaction-level deduplication beyond file hash.
- Improve PDF parser confidence reporting by institution/profile.
- Reduce duplicate Streamlit table-edit patterns.

## Security Hardening

- Database encryption option.
- Backup encryption option.
- Stronger masking for extracted account/card identifiers.
- Privacy-focused audit log review.
- More tests preventing external hosts in optional model settings.
