# Finance Logic

Use this file as the compact source of truth before changing categorization, loan, credit card, EMI, or UPI behavior. Examples are synthetic.

## Transaction Categories

| Category | Example patterns | Analysis usage |
| --- | --- | --- |
| Income | salary, payroll, salary credit | Income, savings rate |
| Rent | rent, house rent, landlord | Housing spend, benchmarks |
| Home Loan EMI | home loan, housing loan, LOAN RECOVERY | Debt repayment, loan analysis |
| Other Loan EMI | personal loan, EMI | Debt repayment |
| Loan Prepayment | MBK debit | Extra principal/prepayment |
| Loan Interest | loan interest, interest debit | Interest cost |
| Loan Charges | penal, bounce, late fee, processing charge with loan/EMI | Debt charges |
| Credit Card Payment | credit card payment, card payment | Excluded from card purchase spend |
| Credit Card Interest / Fees | late fee, finance charge, cash advance fee | Card extra costs |
| Groceries | dmart, grocery, bigbasket | Essential spend |
| Food Delivery | swiggy, zomato, instamart | Discretionary/food outside |
| Restaurants | cafe, restaurant, pizza | Food outside |
| Utilities | electricity, water, broadband | Essential utilities |
| Electricity | electricity, power bill, tsspdcl | Benchmark utilities |
| Internet | broadband, jiofiber, airtel xstream | Connectivity |
| Mobile Recharge | mobile recharge, prepaid, postpaid | Connectivity |
| Fuel | petrol, diesel, hpcl, iocl | Transport |
| Cab / Auto | uber, ola, rapido | Transport |
| Shopping | amazon, flipkart, myntra | Lifestyle/discretionary |
| Healthcare | hospital, pharmacy, clinic | Healthcare |
| Insurance | insurance, premium, LIC | Insurance |
| Investments | groww, zerodha, investment | Savings/investments |
| Mutual Funds / SIP | SIP, mutual fund | Savings/investments |
| Cash Withdrawal | ATM cash withdrawal | Cash |
| UPI Transfers | UPI fallback | UPI analysis |
| Family / Personal Transfers | family transfer, self transfer | Personal transfer separation |
| Bank Charges | bank charge, SMS fee, maintenance fee | Banking costs |
| Miscellaneous | fallback | Review queue |

## Loan Logic

### Detection

| Pattern | Required direction | Loan transaction type | Confidence intent |
| --- | --- | --- | --- |
| `MBK` | debit | `prepayment` | high |
| `LOAN RECOVERY`, `LOAN REC` | debit or loan statement row | `emi` | high |
| `EMI` plus loan hint | debit | `emi` | medium-high |
| `INTEREST` plus loan hint | debit or loan statement row | `interest` | medium-high |
| `PROCESSING FEE/CHARGE` | debit | `processing_fee` | medium-high |
| `PENAL`, `BOUNCE`, `LATE`, `CHARGE` plus loan/EMI | debit | charge subtype | medium |

### Monthly Ledger Fields

| Field | Meaning |
| --- | --- |
| `opening_outstanding` | Outstanding principal at month start |
| `emi_paid` | Sum of EMI loan transactions |
| `prepayment_paid` | Sum of prepayment loan transactions |
| `interest_charged` | Statement interest or calculated interest |
| `principal_paid` | Principal reduction excluding prepayment |
| `charges_paid` | Processing/penal/bounce/insurance/other charges |
| `closing_outstanding` | Outstanding principal after principal and prepayment |
| `inferred_monthly_rate` | `interest_charged / opening_outstanding` |
| `inferred_annual_rate` | `inferred_monthly_rate * 12 * 100` |
| `rate_source` | inferred, manual, bank_statement, unknown |
| `confidence_score` | Reliability of calculation |
| `calculation_notes` | Transparent formula/method |

### Formulas

| Case | Formula |
| --- | --- |
| Known annual rate | `interest = opening * annual_rate / 1200` |
| EMI-only principal | `principal = emi - interest - charges` |
| Closing from calculated values | `closing = opening - principal - prepayment` |
| Interest from opening/closing | `interest = closing - opening + emi + prepayment - charges` |
| Principal from opening/closing with explicit interest | `principal = opening - closing - prepayment` |
| Monthly rate inference | `monthly_rate = interest / opening` |
| Annual rate inference | `annual_rate_percent = monthly_rate * 12 * 100` |

### Manual Override Rules

- Monthly manual override applies before calculated values.
- Override fields replace only provided values.
- Override annual rate sets `rate_source = manual`.
- Manual transaction reclassification replaces automatic loan transaction type.
- Imported loan transactions may be relinked from a placeholder/unlinked group to the selected loan profile; affected ledgers are recalculated.
- Ignored loan transactions are excluded from ledger recalculation.

### Confidence Rules

| Situation | Confidence |
| --- | --- |
| Direct statement opening, interest, principal, closing | high |
| Statement opening/closing plus inferred interest | medium-high |
| Profile opening plus manual annual rate | medium |
| Previous closing carried forward | medium |
| Missing first opening outstanding | low |
| Unknown loan document debit row | low, needs review |

## Credit Card Logic

### Statement Modes

| Mode | Behavior |
| --- | --- |
| Normal | Standard card purchase/fee analysis |
| EMI analysis | Adds EMI installment, schedule, pending EMI, and no-cost EMI cost checks |
| UPI-only | Extracts UPI rows and keeps them out of normal card shopping spend |
| Mixed | Shows normal card shopping and UPI rows separately |

Card usage types: `normal`, `upi_only`, `mixed`, `emi_focused`.

### Classification

| Type | Pattern examples | Notes |
| --- | --- | --- |
| Normal spend | merchant purchase, POS, ecommerce | Counts as purchase spend |
| Payment | payment received, credit card payment | Payment, not purchase |
| Refund/reversal | refund, reversal, chargeback | Credit or offset |
| Interest | finance charge, revolving interest | Extra cost, risk flag |
| EMI debit | EMI, SMART EMI, LOAN ON CARD, EMI 1/6 | EMI obligation; not automatically bad |
| EMI principal | EMI plus principal | Principal component, not extra cost |
| EMI interest | EMI plus interest | Extra cost unless reversed/credited |
| Interest reversal | interest reversal, interest credit | Offsets EMI/card interest |
| Cashback/discount | cashback, merchant discount, bank offer credit | Offsets EMI cost only when statement shows it |
| Late fee | late fee, late payment fee | Extra cost, risk flag |
| Cash withdrawal charge | cash advance fee, cash withdrawal fee | Extra cost, risk flag |
| EMI conversion | merchant EMI, EMI conversion fee | Risk flag, needs cost review |
| Processing fee | processing fee, EMI processing | Extra cost |
| GST on interest | GST/IGST/CGST/SGST with interest/finance | Extra cost, separate from base interest |
| GST on processing fee | GST with processing/proc/conversion fee | Extra cost |
| GST unknown | GST with no parent charge | Needs review |
| Over-limit fee | over limit fee | Extra cost, risk flag |
| Annual fee | annual fee, membership fee | Extra cost |

### No-Cost EMI

- Never assume no-cost EMI is truly free.
- Verify with statement rows: purchase, interest, interest reversal/cashback, processing fee, GST.
- Synthetic example components:
  - purchase principal = `P`
  - interest charged = `I`
  - interest reversal/cashback = `R`
  - processing fee = `F`
  - GST on interest = `GI`
  - GST on processing fee = `GF`
- Net extra cost:
  - `net_extra_cost = interest_charged + gst_on_interest + processing_fee + gst_on_processing_fee + other_charges - interest_reversal - cashback - discount - other_credits`
- Status:
  - `truly_no_cost`: net extra cost <= tolerance and evidence is complete.
  - `partial_no_cost`: interest is reversed/credited but GST/fee remains.
  - `not_no_cost`: net extra cost > tolerance without enough offsets.
  - `unknown`: processing fee/reversal/GST data is missing or future statements are needed.
- If processing fee is not found, keep `processing_fee_unknown`; do not assume zero.
- If rows are missing, show `awaiting_more_statements` / review warnings.

### EMI Plan Tracking

| Table | Role |
| --- | --- |
| `credit_card_transactions` | Card-specific parsed type linked to normalized transaction |
| `credit_card_emi_plans` | Lifecycle, merchant, EMI counts, no-cost status, processing-fee status |
| `credit_card_emi_charges` | Linked EMI debit, interest, reversal, GST, processing fee, cashback/discount |

- EMI schedule extraction uses statement `raw_text`, including raw text from PDFs when available.
- Schedule fields can include merchant, original transaction date, EMI start date, monthly amount, installment count, pending count, interest rate, outstanding, processing fee, and EMI reference.
- Processing fees can link from earlier/later uploaded statements for the same card when an active EMI plan exists.

### Credit Card EMI Rules

| EMI type | Required evidence | Treatment |
| --- | --- | --- |
| Standard card EMI | EMI conversion/purchase row plus fees/interest rows if present | Purchase principal plus extra cost tracking |
| No-cost EMI | Purchase, interest, reversal/cashback, processing fee, GST rows | Verify net extra cost; do not assume zero |
| Merchant discount EMI | Discount/cashback row linked to EMI | Offset only when statement shows it |
| Missing EMI details | EMI keyword without fee/interest/reversal detail | Mark unverified; show review need |

- Card EMI principal is not automatically an extra charge.
- Processing fees, GST, finance charges, and unreversed interest are extra costs.
- Interest reversal/cashback offsets only documented charges.
- Manual override note format: `cc_charge_type=<type>`; valid overrides win over automatic matching.
- Manual EMI link note format: `cc_emi_plan_id=<id>`.
- Manual no-cost status can be stored on the EMI plan review notes/status.

### GST Rules

| Component | Treatment |
| --- | --- |
| GST on interest | Extra cost unless explicitly reversed |
| GST on processing fee | Extra cost |
| GST on late fee / finance charge | Extra cost, separate from base charge |
| Generic GST | Needs review until parent charge is known |
| GST reversal | Offset only if statement shows reversal/refund |

### UPI-Only Card Behavior

- If a card/account is marked UPI-only, avoid assuming revolving credit behavior.
- Analyze UPI spend by receiver/category, daily trend, repeated receiver, person-vs-merchant split, and small frequent payments.
- Keep UPI-only card spend separate from normal shopping spend unless user selects mixed/overall mode.
- Still flag explicit statement fees or interest if present.
- Memory example allowed only if user-approved: `card ****1234 is UPI-only`.

## UPI Logic

### Detection

- Payment mode is UPI if description contains UPI/provider tokens such as `gpay`, `phonepe`, `paytm`, `amazon pay`, `bharatpe`.
- UPI export documents can also be selected/detected as `upi_statement`.

### Receiver Extraction

| Source | Method |
| --- | --- |
| Parsed merchant | Use `merchant_name` if available |
| UPI tokens | Split on `/`, `|`, `:`, `-`; remove refs/provider tokens |
| Keyword pattern | Extract after `to`, `by`, `from`, `merchant`, `beneficiary` |
| Fallback | Normalized description prefix |

### Merchant vs Person Transfer

| Merchant hint | Person hint |
| --- | --- |
| store, mart, restaurant, pharmacy, fuel, electricity, recharge | personal transfer, family transfer, self transfer, mom, dad, wife, husband |

- Manual labels override heuristic.
- Category `Family / Personal Transfers` marks person-to-person.

### Repeated Payment Detection

| Step | Rule |
| --- | --- |
| Group | Same receiver |
| Minimum | At least 2 occurrences |
| Cadence | Daily 1-2 days, weekly 6-8, fortnightly 12-17, monthly 25-35 |
| Amount variation | Exclude if variation ratio > 20 percent |
| Output | Receiver, cadence, occurrences, typical amount, total spend, last seen |
