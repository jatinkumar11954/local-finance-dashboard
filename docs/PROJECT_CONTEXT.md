# Project Context

## Product Goal

Build a fully local personal finance dashboard that imports statements, normalizes transactions, categorizes spend, analyzes loans/cards/UPI, compares Hyderabad benchmarks, and answers local-data questions without exposing private data.

## Implemented Scope

| Area | Status |
| --- | --- |
| Upload | CSV, XLSX, digital PDF ingestion; metadata and raw text stored locally |
| Transactions | Normalized table with review/edit flows |
| Categorization | Rule-based engine plus editable rule UI |
| Benchmarks | Hyderabad benchmark ranges in local SQLite/JSON seed |
| Dashboard | Income, expenses, savings, categories, merchants, trends |
| Loans | Profiles, loan statement routing, MBK prepayment, LOAN RECOVERY EMI, monthly ledger, overrides |
| Credit cards | Card profiles, statement tags, EMI plans, no-cost EMI verification, GST/fee separation, UPI-only card analysis |
| UPI | Receiver extraction, daily spend, top receivers, repeated payments |
| Assistant | Deterministic query handlers, keyword search, optional local model rerank/rewrite |
| App memory | `assistant_memory` schema added; behavior planned and privacy-limited |

## Main User Workflows

| Workflow | Path |
| --- | --- |
| Upload statement | `dashboard/pages/1_Upload.py` |
| Correct transactions | `dashboard/pages/2_Transactions.py` |
| View overview | `dashboard/pages/3_Dashboard.py` |
| Analyze loans | `dashboard/pages/4_Loans.py` |
| Review credit cards | `dashboard/pages/5_Credit_Cards.py` |
| Analyze UPI | `dashboard/pages/6_UPI_Analysis.py` |
| Ask local assistant | `dashboard/pages/7_Assistant.py` |
| Reset/settings | `dashboard/pages/8_Settings.py` |
| Rules/benchmarks | `dashboard/pages/9_Rules_and_Benchmarks.py` |

## Data Ingestion Flow

1. User uploads local file.
2. `app/services/documents.py` hashes and persists it locally.
3. Parser selected by extension in `app/services/parsers/factory.py`.
4. Tabular/PDF parser maps columns to canonical rows.
5. Rows become `transactions`.
6. Loan-like rows also become `loan_transactions`.
7. Credit-card statements can also create/link card profiles and synced card transaction rows.
8. Audit log records event metadata, not raw sensitive payloads.
9. Upload page can reprocess one/all stored files to reload normalized rows after parser/categorization/loan/card/UPI logic changes.

## Reprocessing Flow

| Step | Behavior |
| --- | --- |
| Trigger | Upload page: reprocess selected upload or all uploads |
| Scope | Rebuilds `transactions` and derived loan/card rows from the locally stored original file |
| Preservation | Keeps document metadata, stored file, account, prior loan/card links where possible |
| Use case | Apply newer parsing logic to existing uploads without deleting/reuploading |
| Safety | Local only; no private rows are written to docs/logs |

## Transaction Normalization Flow

| Step | Logic |
| --- | --- |
| Date | Parse date with Indian statement tolerance; PDF rows can start with `Sr.No` before the transaction date |
| Amount | Resolve debit/credit columns or signed amount; ignore opening/closing rows with no debit/credit amount |
| Type | `debit` or `credit` |
| Mode | UPI, IMPS, NEFT, RTGS, CARD, CASH, EMI, AUTOPAY, NETBANKING, WALLET, unknown |
| Merchant | Rule/token extraction from description |
| Category | Editable rule engine, fallback to heuristics/Miscellaneous |
| PDF tables | Handles split/repeated bilingual headers like Hindi labels plus `Sr.No`, `Transaction Date`, `Debit`, `Credit`, `Balance` |
| Safety | Exclude unreasonable parser outliers from analytics |

## Categorization Flow

- Defaults seeded in `app/services/categorization/rules.py`.
- Rules stored in `category_rules`.
- Higher priority wins.
- Manual transaction corrections should be treated as higher priority than automatic classification.
- Reapply rules through local API/UI only.

## Loan Analysis Flow

| Stage | Details |
| --- | --- |
| Detection | `MBK` debit and `Loan Account Payment(s)` debit = prepayment; `LOAN RECOVERY`/`LOAN REC` = EMI |
| Mapping | Auto-link if one loan exists; else review/link manually |
| Ledger | Month-level EMI, prepayment, interest, principal, charges, closing; sorted by month |
| First opening | Statement opening wins; otherwise estimate first imported month from profile schedule when principal/start/rate/EMI exist |
| Rates | Infer annual rate from `interest / opening * 12 * 100` when data exists |
| Overrides | Manual monthly override wins over calculated values |
| Import summary | Loan page shows detected transaction counts, ledger months, EMI, MBK/prepayment, interest, current outstanding |
| Relink | Loan page can move imported transactions from placeholder/unlinked groups to the selected profile and recalculate |
| Confidence | Low when opening/rate/statement data is missing; surfaced in UI |

## Credit Card Analysis Flow

- Source rows from credit card statements or card-like transactions.
- Upload can tag statement as Normal, EMI analysis, UPI-only, or Mixed and link/create a card profile.
- Classify purchases, payments, EMI debit/principal/interest, interest reversal, cashback/discount, processing fee, GST parent charge, late/finance/cash charges.
- Persist card-specific rows in `credit_card_transactions`; track EMI lifecycle in `credit_card_emi_plans` and `credit_card_emi_charges`.
- No-cost EMI must be verified from interest, reversal, GST, processing fee, cashback/discount; missing processing fee means `processing_fee_unknown`, not zero.
- Manual corrections in the Credit Cards page override auto parsed type or EMI plan review status.

## UPI Analysis Flow

- UPI mode inferred from `payment_mode` or description/provider tokens, including UPI-card rows parsed as card transactions.
- Receiver from `merchant_name` or normalized description.
- Personal transfer if marked manually or category/description indicates person/family/self.
- Repeated payment if same receiver has repeated cadence and low amount variation.
- UI separates total spend amount, transaction count, average amount, merchant spend, and personal transfers.
- Credit-card UPI parser ignores reward points/serial/reference columns and uses the final rupee amount column.
- If many UPI rows have tiny amounts, show a quality warning and ask user to reprocess the upload because the older PDF parser may have read row counts as amounts.

## Local Assistant/RAG Flow

| Layer | Behavior |
| --- | --- |
| Deterministic handlers | SQL/dataframe-style answers from local DB |
| Keyword search | Local document text and transactions |
| Local embeddings | Optional local sentence-transformer path only |
| Local LLM | Optional Ollama on localhost only |
| Answer contract | Answer, date range, support rows/docs, method, confidence |
| No data | Say data is unavailable |

## Database Summary

- Core: `documents`, `accounts`, `transactions`, `categories`, `category_rules`, `merchants`, `benchmarks`.
- Loans: `loans`, `loan_payments`, `loan_transactions`, `loan_monthly_ledger`, `loan_rate_events`, `loan_manual_overrides`.
- Cards: `credit_cards`, `credit_card_statements`, `credit_card_transactions`, `credit_card_emi_plans`, `credit_card_emi_charges`.
- Assistant/audit: `assistant_queries`, `assistant_memory`, `audit_log`.
- See [SCHEMA_SUMMARY.md]($userpathlocal-finance-dashboard/docs/SCHEMA_SUMMARY.md).

## Security/Privacy Model

- Local SQLite and local file storage only.
- No cloud sync, telemetry, hosted LLMs, hosted OCR, or external finance APIs.
- Local password gate is optional.
- Store masked account/card identifiers only when needed.
- Docs/context must never include private uploads, DB rows, or secrets.

## Assistant Memory Rules

| Allowed | Not Allowed |
| --- | --- |
| User-approved preferences | Full raw statement text |
| Reusable category corrections | Private transaction details not needed for reuse |
| Synthetic project facts | Account/card full numbers |
| General finance notes | Secrets or credentials |

Examples: `MBK debit is loan prepayment`, `LOAN RECOVERY is loan EMI`, `merchant_x -> Groceries`, `card ****1234 is UPI-only`.

## Known Limitations

- OCR not included.
- PDF parsing targets digital PDFs with extractable text/tables.
- Parser profiles are heuristic, not bank-specific for every institution.
- Database encryption is not enabled by default.
- No-cost EMI net cost requires explicit statement evidence.
- Official rate changes are manual/local uploads only.

## Roadmap

- See [ROADMAP.md]($userpathlocal-finance-dashboard/docs/ROADMAP.md).
