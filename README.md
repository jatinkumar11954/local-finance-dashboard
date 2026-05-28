# Local Finance Dashboard — Offline Personal Finance Analytics

Analyze bank statements, credit card bills, UPI payments, loans, EMIs, and no-cost EMI charges locally — without uploading sensitive financial data to the cloud.
A privacy-first personal finance dashboard that helps you understand where your money is going.

This app lets you upload bank statements, credit card statements, UPI exports, and loan documents locally, then converts them into dashboards, charts, and actionable insights.

It helps answer questions like:

Where am I spending the most?
Are my small UPI payments becoming a big monthly expense?
Am I paying hidden credit card interest, GST, or processing fees?
Is my no-cost EMI actually no-cost?
How much of my loan EMI is interest vs principal?
Are my credit card payments being double-counted as expenses?

All processing happens locally.
No cloud upload.
No external APIs.
No hosted AI.
No telemetry.
## Privacy Guarantees

- No internet APIs, cloud storage, hosted AI APIs, telemetry, crash reporting, or external financial-data calls.
- Local SQLite database and local file storage only.
- Optional AI support is local-only: localhost Ollama or local model files.
- Do not add docs/context that include uploaded statements, DB rows, secrets, or private financial data.

## Current Feature Status

| Area | Status |
| --- | --- |
| CSV/XLSX/digital PDF upload | Implemented with selected/all upload reprocessing and bilingual loan table parsing |
| Transaction normalization/review | Implemented |
| Rule-based categorization | Implemented, editable |
| Analytics API/dashboard | Implemented: source-separated bank/card/UPI/loan/all-sources analytics, true-expense deduplication, cashflow, recurring, anomaly, merchant/category, budget/benchmark views |
| Dashboard and Hyderabad benchmarks | Implemented |
| Loan analysis | Implemented: EMI vs MBK prepayment separation, floating-rate monthly ledger, base-rate variance, actual-vs-projected comparison, profile-schedule opening, overrides |
| Credit card analysis | Implemented: card profiles, Normal/EMI/UPI-only/Mixed tags, EMI plans, no-cost EMI true-cost checks, GST/fee separation, UPI-card analysis, manual review |
| UPI analysis | Implemented: receiver extraction, amount/count metrics, daily spend, repeated payments, parser-quality warnings |
| Local assistant | Implemented: deterministic handlers, keyword search, optional local embeddings/Ollama |
| Agent memory/context | Implemented: compact docs, `.codex`, `assistant_memory` schema |

## Local Setup

```bash
cd $userpathlocal-finance-dashboard
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app.init_db
```

## Run

```bash
python -m streamlit run dashboard/streamlit_app.py
```

Optional local FastAPI server:

```bash
uvicorn app.main:app --reload
```

Optional local-only assistant model:

```bash
export LFI_LOCAL_LLM_PROVIDER=ollama
export LFI_OLLAMA_BASE_URL=http://127.0.0.1:11434
export LFI_OLLAMA_MODEL=qwen2.5:7b-instruct
```

## Test

```bash
pytest
python scripts/build_agent_context.py
```

## Agent And Developer Context

- Agent instructions: [AGENTS.md]($userpathlocal-finance-dashboard/AGENTS.md)
- Compact Codex context: [.codex/context.md]($userpathlocal-finance-dashboard/.codex/context.md)
- Project memory: [docs/PROJECT_CONTEXT.md]($userpathlocal-finance-dashboard/docs/PROJECT_CONTEXT.md)
- Finance logic: [docs/FINANCE_LOGIC.md]($userpathlocal-finance-dashboard/docs/FINANCE_LOGIC.md)
- Schema summary: [docs/SCHEMA_SUMMARY.md]($userpathlocal-finance-dashboard/docs/SCHEMA_SUMMARY.md)
- Decisions: [docs/DECISIONS.md]($userpathlocal-finance-dashboard/docs/DECISIONS.md)
- Roadmap: [docs/ROADMAP.md]($userpathlocal-finance-dashboard/docs/ROADMAP.md)
- Onboarding: [docs/ONBOARDING.md]($userpathlocal-finance-dashboard/docs/ONBOARDING.md)

## Sample Data

Synthetic samples live in `sample_data/`:

- `dummy_bank_statement.csv`
- `dummy_bank_statement_with_loan.csv`
- `dummy_loan_statement.csv`
- `dummy_credit_card_statement.csv`
- `dummy_upi_export.csv`
- `dummy_bank_statement.pdf`

The dummy credit-card statement includes synthetic normal purchases, EMI rows, no-cost EMI interest/reversal, GST, processing fee, and UPI card transactions.

## Local Data Paths

- Runtime uploads: `data/uploads/`
- Runtime DB: `data/local_db/finance_dashboard.db`
- Benchmark seed: `data/benchmarks/hyderabad_benchmarks.json`

Do not include runtime uploads or DB files in agent context, docs, tests, or commits.
