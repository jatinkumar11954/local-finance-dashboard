# Developer Onboarding

## Setup

```bash
cd $userpathlocal-finance-dashboard
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app.init_db
```

## Run

```bash
cd $userpathlocal-finance-dashboard
source .venv/bin/activate
PYTHONPATH=$(pwd) python -m streamlit run dashboard/streamlit_app.py
python -m streamlit run dashboard/streamlit_app.py
uvicorn app.main:app --reload
```

## Test

```bash
pytest
python scripts/build_agent_context.py
```

## Where To Change Things

| Change | Start here |
| --- | --- |
| Parser logic | `app/services/parsers/` |
| Upload workflow | `app/services/documents.py`, `dashboard/pages/1_Upload.py` |
| Transaction correction | `app/services/transactions.py`, `dashboard/pages/2_Transactions.py` |
| Categorization | `app/services/categorization/rules.py`, `app/services/category_rules.py` |
| Dashboard metrics | `app/services/analytics/overview.py`, `dashboard/pages/3_Dashboard.py` |
| Loan logic/import relinking | `app/services/loans/`, `dashboard/pages/4_Loans.py` |
| Credit card ingestion and card metadata | `app/services/credit_cards/service.py`, `app/services/documents.py`, `dashboard/pages/1_Upload.py` |
| Credit card analysis/UI | `app/services/credit_cards/analysis.py`, `dashboard/pages/5_Credit_Cards.py` |
| UPI logic | `app/services/analytics/upi.py`, `dashboard/pages/6_UPI_Analysis.py` |
| Assistant logic | `app/services/rag/assistant.py`, `dashboard/pages/7_Assistant.py` |
| Database models | `app/models/entities.py`, `app/database.py` |
| API endpoints | `app/routers/` |

## Reprocessing Existing Uploads

- Use Upload page reprocess controls after parser/categorization/loan/card/UPI logic changes.
- Reprocessing rebuilds normalized transactions and derived rows from locally stored files.
- It should preserve account metadata and prior loan/card links where possible.

## Privacy Mistakes To Avoid

- Do not inspect runtime uploads or local DB files while building context.
- Do not add network calls to external hosts.
- Do not log raw descriptions, statement text, or DB rows unnecessarily.
- Do not store full account/card numbers.
- Do not use real statements in tests.
- Keep examples synthetic and masked.
