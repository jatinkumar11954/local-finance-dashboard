# Architecture Decisions

| Date | Decision | Reason | Impact |
| --- | --- | --- | --- |
| 2026-05-28 | Offline-first app | Financial data is confidential | All processing/storage stays local |
| 2026-05-28 | SQLite default database | Simple, local, portable MVP | No external DB service required |
| 2026-05-28 | Streamlit MVP UI | Fast local review workflows | Lower frontend complexity |
| 2026-05-28 | Rule-based categorization before AI | Deterministic, auditable, private | AI is optional enhancement only |
| 2026-05-28 | Local-only optional models | Assistant can improve without cloud | Ollama/local embeddings only |
| 2026-05-28 | No external APIs | Prevent data leakage and hidden dependencies | No hosted LLM, OCR, finance, telemetry, or rate APIs |
| 2026-05-28 | Manual override priority over auto classification | User correction is source of truth | Ledger/category recalculation honors corrections |
| 2026-05-28 | Uploaded bank/card/loan statements are source-of-truth | Calculations must be traceable | Store supporting docs/transactions and confidence |
| 2026-05-28 | No-cost EMI must be verified, not assumed | Fees/GST/reversals vary by issuer | Mark unverified when statement rows are incomplete |
| 2026-05-28 | UPI-only credit cards are analyzed separately | Some cards are used mainly for UPI, not shopping | UPI card spend is separated from normal card purchase analysis in UPI-only/Mixed modes |
| 2026-05-28 | Credit-card EMI state is stored separately from normalized transactions | EMI plans need lifecycle, charges, and manual review | `credit_card_transactions`, `credit_card_emi_plans`, and `credit_card_emi_charges` link back to source transactions |
| 2026-05-28 | Interest rates are inferred unless manually/bank-provided | App is offline and cannot fetch official rates | Rate source must be explicit |
| 2026-05-28 | Assistant memory is local and non-sensitive | Reuse corrections without storing private payloads | `assistant_memory` stores only approved reusable rules/preferences |
| 2026-05-28 | Existing uploads can be reprocessed locally | Parser and finance logic improve over time | Stored local files can rebuild normalized and derived rows without cloud calls |
| 2026-05-28 | UPI amount quality warnings are explicit | Some PDF table extraction can read row numbers as amounts | UI warns and asks user to reprocess instead of silently showing bad totals |
| 2026-05-28 | First imported loan opening can come from profile schedule | Historical bank statements often show only EMI/prepayment, not loan outstanding | Ledger uses original principal/start/rate/EMI before falling back to current outstanding |
