# Finance audit and Financial Discovery plan

Status: **audit complete, plan awaiting approval.** No code was changed for this
audit. Repository revision audited: `main` at `5c8448f` (after PR #14).

Sources: the owner's requirements (ledger, accrual, spreading, cost of life
objects), the owner's decisions below, and the Financial Discovery handoff
(treated as direction, not specification).

## Owner decisions (recorded)

| Topic | Decision |
|---|---|
| Accounting views | Both **cash basis** and **accrual basis**. |
| Car purchase | An **asset**; its cost is spread **straight-line (SLM)** over its useful life. |
| Fuel | Spread **automatically** between fills. At each fuel spend, ask for the **odometer** reading (number or photo) and compute real-world mileage. |
| EMIs | Split into **principal** and **interest**. On detecting a loan, ask for the **loan document**; if skipped, ask for principal, rate, tenure, interest method. |
| Life areas | Five visible (Money, Health, Family & Relationships, Learning, Work); unassigned spending goes to a hidden "Soul" area, shown only above 30%. |

---

## Deliverable 1 — How financial data flows today

```
Setup wizard (frontend/app/portfolio/setup.tsx)  ── mandatory gate (app/_layout.tsx:40)
   │ creates
   ▼
financial_accounts ─────────────┐   monthly_money_commitments (planned income/expense/
(portfolio_manager.py)           │   saving/investment/debt; portfolio_manager.py)
   │ snapshot: current_value     │            │
   │ + balance_as_of             │            ▼
   ▼                             │   _monthly_summary (finance_manager.py:1122) = PLAN only
financial_events  ◄── check-ins with money_spent (server.py:2140-2190)
(finance_manager.py create_event:3227)        ◄── manual entry (POST /finance/events)
   │ confirmation_status + lifecycle_status
   │ _dedupe_check (3202): same amount+date+direction AND (same source_reference
   │                       OR same description from a different source)
   ▼
money_service.py  ── compute_effective_balance / load_availability /
   │                 monthly_actual_spending  (ASSET accounts only)
   ▼
/finance/position (net worth: assets effective, liabilities = typed snapshot)
/portfolio/money-position (available for flexible spending)
finance_advanced.py: forecasts (+confidence), decision-assessment,
   expected income (one-time vs recurring), reconciliation suggestions,
   scenarios, overrides/calibration
   │
resource_allocations (money): financial commitments (reserve → consume) linked
   to goal_id / task / project; financial_audit: append-only trail

Separately: GET /api/spending (server.py) → Today's Spending card, summed from
checkins.money_spent — NOT from financial_events.
```

---

## Deliverable 2 — Requirement-to-code gap matrix

Legend: ✅ implemented · 🟡 partial · ❌ missing · 🐞 defect · ⏳ later · ➖ unnecessary

| Requirement | Existing implementation | Verified gap | Proposed change | Priority | Risk |
|---|---|---|---|---|---|
| One source of truth for spending | money_service is canonical for Finance | 🐞 Today's Spending reads `checkins.money_spent`; a check-in spend with no account stays `pending_account_assignment` and never reaches Finance → two totals for one day | `GET /spending` reads applied events via money_service | P0 | Low |
| Exact money, audit trail, user isolation | Decimal128, `financial_audit`, `user_id` on every query | ✅ | Keep; add tests around new fields | — | — |
| No silent truncation | — | 🐞 reads capped at 20k–50k rows (`money_service.py:451`, `finance_manager.py:1030`) then summed | Aggregate in Mongo or page; fail loudly over cap | P0 | Low |
| Transfers between own accounts | none (single `account_id` + direction) | ❌ an FD deposit or bank→cash move is an outflow → counted as spending | `kind` + `counter_account_id` on events; transfers move balances, never count as spend | P0 | Med |
| Credit cards / accrual | liability types exist (`portfolio_manager.py:83`) | ❌ liability accounts rejected by `_resolve_event_account` (`finance_manager.py:264`); card balances frozen at snapshot | Allow events on liabilities; card spend raises balance; bill payment = `card_settlement` transfer | P0 | Med |
| Cash view vs accrual view | — | ❌ | Reports: accrual by purchase date (settlements excluded); cash by money-leaving-assets date (card spend counted when the bill is paid) | P1 | Low |
| Economic event vs its records (PhonePe + card + bank) | dedupe candidates + user resolution | 🟡 match needs same date AND identical description across sources → misses real duplicates; settlement can't be linked | Looser candidate rule (amount ± date window, reference ids), `economic_event_id` grouping; settlement linking | P2 | Med |
| Classification (consumption, transfer, investment, redemption, gift, refund, loan payment, unclassified) | direction only; expected income has one-time/recurring | ❌ | `kind` enum on events; existing events map to expense/income | P0 (enum) / P2 (inference) | Low |
| Provenance (document / user / inferred / estimated / unknown) | `source` + audit trail | 🟡 no confidence or provenance on classifications | `classification_provenance`; user corrections set `locked` so imports never overwrite | P2 | Low |
| Categories | none | ❌ | Default category tree, editable; one per expense | P1 | Low |
| Cost of a life object (car, house, household, habits) | none | ❌ | `cost_objects` (area, start, optional asset link); events tagged/split | P1 | Low |
| Car as asset with SLM depreciation | asset types; no vehicle type, no depreciation | ❌ | `vehicle` asset type; purchase price, date, life, salvage → monthly depreciation in accrual view, charged to the car | P1 | Low |
| Spreading (fuel between fills) | none | ❌ | `consumption_period` on events; fuel auto-period = until next fuel event for the same car | P1 | Low |
| Real-world mileage | none | ❌ | Odometer prompt at each fuel spend (number or photo → Claude vision); litres or price/litre also needed for km/l | P1 | Low |
| Loans: principal vs interest | debt payments planned; scenario loan closure | 🟡 no terms, no amortisation | Loan terms on liability (principal, rate, tenure, method, start); EMI split by schedule; loan document upload → extraction | P1 (manual) / P2 (document) | Med |
| Stock vs flow; balances dated | `balance_as_of` per account | 🟡 net worth mixes asset effective balances with stale liability snapshots | Liabilities move with events once allowed (above); show "as of" per figure | P0 (with cards) | Low |
| Recurring vs non-recurring income | expected income `classification`; forecasts use recurring separately | 🟡 actual inflows aren't classified (gift/redemption look like income) | `kind` = salary/gift/redemption/refund… on inflows | P0 | Low |
| Optional finance onboarding | setup wizard | 🐞 **mandatory**: app redirects to setup (`app/_layout.tsx:40`); completion requires ≥1 account AND ≥1 monthly commitment (`portfolio_manager.py:1374-1402`) | Allow completing setup with finance skipped; resume later | P1 | Low |
| Statement ingestion | sources enum lists `bank_statement`, `sms`… | ❌ no upload, parsing or file storage | Upload PDF/CSV → Claude extraction → pending events → dedupe → confirm | P2 | High (privacy) |
| Materiality-driven questions | reconciliation suggestions, dedupe queue, commitments due for review | 🟡 no ranked queue of material uncertainties | `finance_questions`: biggest unclassified flows first, fuel w/o odometer, loan w/o terms; answers update classification (locked) | P3 | Low |
| Partial-data honesty | forecast confidence (`finance_advanced.py:870`) | 🟡 confidence only on forecasts | Coverage indicator per report (which accounts/months are reconciled) | P3 | Low |
| Affordability ("can we go to Norway") | `decision-assessment` (`finance_advanced.py:990`) | 🟡 exists; not reachable from assistant/goals | Reuse from assistant and goals | P4 | Low |
| Goal cancelled → stop future commitments | commitments carry `goal_id`; goals have `abandoned` | ❌ abandoning a goal leaves its future commitments active | On abandon, offer to cancel future commitments; history untouched | P4 | Low |
| Recommendation → goal (user-controlled) | planning chat proposals | 🟡 | Same "apply" pattern for finance recommendations | P4 | Low |
| Spending linkable to goals | allocations owner types: task/project/knowledge_journey/standalone | 🟡 no `goal` | Via `goal_id` on commitments (exists) + area/cost object | — | — |
| Insurance as risk protection | none | ❌ | Policies (insurer, insured, cover, premium, period, exclusions, employer dependence) | ⏳ | Low |
| EPF / investments valuation | asset types incl. mutual_fund/stock | 🟡 values are typed snapshots | Later: periodic valuation updates | ⏳ | Low |
| Account deletion / data export | none | ❌ | Delete account + all data; export | P1 (before beta) | Low |
| Bank / card connections | `bank_connection` in sources enum | ➖ now | Keep `source`, `source_reference`; nothing else | Future | — |

**Conclusion.** The existing engine is a careful cash-flow planner with a
sound balance service and audit trail. It is inadequate as a ledger in three
demonstrated ways — no transfers, no credit-card accounting, no
classification — and those three block every owner requirement. The plan
therefore **evolves `financial_events` into the ledger** rather than adding a
parallel one: same collection, same confirmation semantics, same
money_service, new fields with backward-compatible defaults.

---

## Deliverable 3 — Minimal amendment plan

### A. Event kinds, transfers, cards (P0)
- **Edit** `finance_manager.py` (`FinancialEventCreate`, `create_event`,
  `_resolve_event_account`), `money_service.py` (`compute_effective_balance`,
  `monthly_actual_spending`, `event_is_applied_to_account`).
- **New fields** on events: `kind`, `counter_account_id`. Existing rows read as
  `expense` (outflow) / `income` (inflow) — no migration needed to keep working.
- **Rules**: transfer/settlement/investment = outflow on `account_id`, inflow on
  `counter_account_id`, excluded from spending. Liability accounts accept
  events: expense raises outstanding, settlement lowers it.
- **Must not change**: confirmation/lifecycle semantics, available-money
  definition for asset accounts, audit trail, API shape for existing fields.
- **Accept**: moving ₹50,000 bank→FD leaves spending unchanged and net worth
  unchanged; a ₹2,000 card dinner is ₹2,000 spending on that day and +₹2,000 card
  outstanding; paying the card bill changes bank and card, not spending.
- **Tests**: extend `safety_tests/test_money_service.py`; new unit tests.

### B. Single spending truth + no truncation (P0)
- **Edit** `server.py` `get_spending` to use applied events; replace capped
  `to_list` sums with Mongo aggregation in `money_service.py`.
- **Accept**: Today's Spending equals Finance month-to-date for the same day.

### C. Optional finance setup (P1)
- **Edit** `portfolio_manager.py` completion rule (finance rows optional when
  `finance_skipped`), `app/portfolio/setup.tsx` skip/resume (Emergent).
- **Must not change**: time-commitment requirement; existing completed users.

### D. Categories, cost objects, areas, spreading, depreciation, mileage (P1)
- **New** `ledger_meta.py` (categories, cost objects, asset depreciation
  schedule) — new because nothing comparable exists.
- **Edit** events: `category_id`, `cost_object_id` (+ optional splits),
  `consumption_period`, `odometer_km`, `fuel_litres`.
- Reports: `/finance/reports/spending?basis=accrual|cash&group=category|area|object`,
  `/finance/objects/{id}/cost`.

### E. Loans (P1 manual, P2 document)
- Loan terms on liability accounts; EMI split; vehicle-loan interest charged to
  the car.

### F. Questions queue, statement ingestion, goal hooks (P2–P4)
- As in the matrix; each its own approved patch.

---

## Deliverable 4 — Priorities

| Phase | Contents |
|---|---|
| **P0 Integrity** | B (single truth, no truncation) → A (kinds, transfers, cards) |
| **P1 Manual-first** | C (optional setup) · D (categories, objects, spreading, depreciation, mileage) · E-manual (loans) · account deletion |
| **P2 Evidence** | Statement upload + extraction · better duplicate matching · provenance/locks · loan documents |
| **P3 Clarification** | Material-questions queue (wired into nudges/daily review) · coverage indicators |
| **P4 Goals** | Abandon → cancel future commitments · assistant uses decision-assessment ("can we go to Norway") |
| **Future** | Bank/card connections (fields only today) |

---

## Deliverable 5 — First surgical patch (proposed)

**"One spending truth"** (part B).

- **Files**: `backend/server.py` (`get_spending`), `backend/money_service.py`
  (new `daily_actual_spending` helper next to `monthly_actual_spending`),
  tests in `backend/unit_tests/`.
- **User-visible**: Today's Spending card shows only spends that Finance also
  counts. A check-in spend without an account no longer appears there until an
  account is assigned (the card can show "1 spend needs an account").
- **Backend impact**: one endpoint changes its source; response shape unchanged.
- **Data-model impact**: none.
- **Regression concerns**: the Today card total may drop for users with
  unassigned spends — intended, and surfaced.
- **Tests**: Today total == monthly service for same date; unassigned spend
  excluded and counted as "needs account"; pending/void/rejected excluded.
- **Excluded**: transfers, cards, categories, any frontend change beyond
  optionally showing the "needs account" count.

Next patch after approval: **A (kinds, transfers, cards)** — the change that
unblocks every owner requirement.
