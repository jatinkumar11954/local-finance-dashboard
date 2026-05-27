# Schema Summary

Compact memory of SQLAlchemy models. Do not paste full model definitions into prompts.

| Table | Purpose | Important fields | Relationships/notes |
| --- | --- | --- | --- |
| `accounts` | Local account/source metadata | name, institution, account_type, masked_account_number | Linked to documents and transactions |
| `documents` | Uploaded file metadata and extracted text | filename, stored_path, hash, document_type, status, confidence, raw_text | Parent of transactions; stored file is local only |
| `transactions` | Normalized finance rows | date, description, amount, transaction_type, payment_mode, merchant, category, flags, source_document_id | Main analytics table |
| `categories` | Category reference data | name, parent_name, active | Seeded defaults |
| `category_rules` | Editable categorization rules | pattern, field_name, target_category, priority, regex flags | Higher priority wins |
| `merchants` | Merchant normalization memory | name, aliases, category | Not heavily used yet |
| `loans` | Loan profile | name, bank/lender, masked account, principal, rate, tenure, EMI, outstanding | Supports one or more loans |
| `loan_payments` | Legacy/simple loan payment rows | payment_date, amount, principal, interest, extra_principal | Retained for compatibility |
| `loan_transactions` | Detected loan-related transaction records | loan_id, transaction_id, date, amount, type, confidence, review_status, components | Linked to original transaction/document when available |
| `loan_monthly_ledger` | Calculated monthly loan ledger | opening, EMI, prepayment, interest, principal, charges, closing, inferred rates, notes | Unique per loan/month |
| `loan_rate_events` | Manual/bank-provided rate events | effective_date, rate_name, rate_percent, source_note, document_id | No external rate fetching |
| `loan_manual_overrides` | User override per loan/month | opening, closing, interest, principal, charges, annual_rate, notes | Takes priority over auto logic |
| `credit_cards` | Card metadata | name, bank/issuer, last4, masked_card_number, usage_type, active, statement/due day, limit | `usage_type`: normal, upi_only, mixed, emi_focused |
| `credit_card_statements` | Statement summary metadata | card_id, document_id, statement_month, due dates, total/minimum due, uploaded_tag, fees, interest | Source document link and upload analysis tag |
| `credit_card_transactions` | Card-specific parsed transaction rows | card_id, statement_id, transaction_id, date, parsed_type, merchant, confidence, manual_override | Mirrors normalized transaction for card analysis |
| `credit_card_emi_plans` | EMI lifecycle plan | card_id, merchant, EMI start/end, monthly amount, counts, no-cost status, processing fee status, lifecycle status | Tracks active/completed/review EMI plans |
| `credit_card_emi_charges` | Charges linked to EMI plans | plan_id, transaction_id, month, charge_type, amount, manual_override | Stores EMI debit, principal, interest, reversal, GST, processing fee, cashback/discount/manual entries |
| `recurring_transactions` | Recurring transaction memory | merchant, category, mode, typical_amount, cadence, last_seen, confidence | Separate from UPI recurring output |
| `benchmarks` | Hyderabad benchmark ranges | city, profile, category, min/max, active | Used by dashboard comparison |
| `assistant_queries` | Query history | question, answer, date range, confidence | Keep concise; avoid raw private payloads |
| `assistant_memory` | Local reusable assistant memory | memory_type, key, value, source, confidence, active | Store only approved/non-sensitive reusable rules |
| `audit_log` | Local audit events | action, entity_type, entity_id, details | Avoid raw statement payloads |

## Relationships

- `documents.id -> transactions.source_document_id`
- `accounts.id -> documents.account_id`, `transactions.account_id`
- `transactions.id -> loan_transactions.transaction_id`
- `documents.id -> loan_transactions.source_document_id`
- `loans.id -> loan_transactions.loan_id`, `loan_monthly_ledger.loan_id`, `loan_rate_events.loan_id`, `loan_manual_overrides.loan_id`
- `documents.id -> credit_card_statements.source_document_id`
- `credit_cards.id -> credit_card_statements.credit_card_id`, `credit_card_transactions.card_id`, `credit_card_emi_plans.card_id`
- `transactions.id -> credit_card_transactions.transaction_id`, `credit_card_emi_charges.transaction_id`
- `credit_card_emi_plans.id -> credit_card_emi_charges.emi_plan_id`

## Schema Change Rules

- Use `Base.metadata.create_all` for new tables.
- Existing SQLite columns need safe idempotent extensions in `app/database.py`.
- Do not drop or rewrite local user tables.
- Add tests for new tables/columns.
- Do not store raw statement content in memory tables.
