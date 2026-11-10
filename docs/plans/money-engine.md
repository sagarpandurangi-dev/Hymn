# Money engine — audit and plan

Status: **draft for approval**. Nothing here is built yet.

## What the owner asked for

1. Every rupee moves **from** an account **to** an account; nothing is counted twice.
2. **Accrual**: a credit-card purchase is spending on the day of purchase; paying
   the card bill is not new spending.
3. **Spreading**: some costs are consumed over time (fuel lasts until the next
   fill) and should be spread across that period.
4. **Cost of a part of life**: the full cost of a car (fuel, repairs, tolls,
   modifications, insurance, loan interest), a house, the household, habits
   (alcohol, cigarettes), since it started and per month.

## Audit of the current engine (~6,000 lines)

What is solid:

- Money is exact decimals everywhere; amounts never pass through floats.
- An append-only audit trail and per-user isolation.
- Account balances = snapshot + confirmed events after the snapshot date, in one
  service (`money_service.py`), so "available money" has a single definition.
- Duplicate *detection* for the same event arriving twice (check-in vs SMS vs
  statement), with a user decision step.
- Planned recurring income/expenses, commitments, forecasts and scenarios.

What is missing or wrong against the requirements:

| # | Finding | Effect |
|---|---|---|
| 1 | **No transfers.** An event has one account and a direction (in/out). Moving money between your own accounts can only be recorded as an outflow + an inflow. | Moving ₹50,000 to an FD shows as ₹50,000 *spent*. |
| 2 | **Credit cards are explicitly unsupported** (`_resolve_event_account` rejects liability accounts; card balances stay at the typed-in snapshot). | Card spending can't be recorded against the card, so accrual is impossible and card balances go stale. |
| 3 | **No categories at all.** Events link to commitments/goals/tasks, not to "Fuel" or "Groceries". | No "where did my money go" view. |
| 4 | **No cost centres** (car, house, habit). | "How much does my car cost" can't be answered. |
| 5 | **No spreading.** Every spend lands on its date. | Fuel, insurance, annual fees make months lumpy. |
| 6 | **Two sources of truth for spending.** Today's Spending card (`GET /spending`) sums `checkins.money_spent`; Finance uses confirmed events. | The two can disagree (pending/rejected events still show on Today). |
| 7 | "Actual spending" = every outflow event, including savings, investments and (because of #1) transfers. | Overstates spending. |
| 8 | The "monthly" summary is built from **planned** recurring amounts only. | Shows the budget, not what happened. |
| 9 | Loan EMIs are planned outflows; interest vs principal isn't separated. | A car loan's true cost (interest) is invisible; principal looks like spending. |
| 10 | Some reads cap at 20,000–50,000 rows and then compute. | Silent wrong totals after a few years of data. |

Conclusion: the current engine is a well-built **cash-flow planner**, not a
**ledger**. The requirements need a ledger at the core.

## Proposed design: a double-entry ledger

**Transactions** (the single source of truth for actual money):

| Kind | From → To | Counts as spending? |
|---|---|---|
| Expense | bank / cash / **card** → category | Yes, on the purchase date |
| Income | source → bank | — (income) |
| Transfer | own account → own account (bank → FD, bank → card bill, bank → cash) | **No** |
| Loan payment | bank → loan (principal) + bank → "Interest" (expense) | Interest only |
| Refund | category → account | Reduces spending |

- **Accounts** include cards and loans (liabilities). A card purchase raises the
  card balance; paying the bill is a transfer. Accrual falls out naturally.
- **Categories**: a short default tree (Food › Groceries, Transport › Fuel, …),
  editable. Every expense has one.
- **Cost centres ("life objects")**: Car, House, Household, Alcohol, … Each has a
  start date, optional purchase price, and the area of life it belongs to
  (Money, Health, Family, Learning, Work). An expense can be tagged to one, or
  split across several.
- **Spreading**: an expense can carry a consumption period. For recurring
  consumables (fuel), "until the next one of the same kind" is the default, so
  a fill on the 1st and the next on the 11th spreads the first over 10 days.
- **Dedupe**: one real-world payment = one transaction, however many sources
  report it (check-in, SMS, statement). The existing duplicate detection is
  reused.

**Reports** (all on accrual basis, transfers excluded, spreading applied):

- Spending by month × category × area.
- Cost of a life object: per month, last 12 months, since start, and with
  purchase price included or excluded.
- Area cost: how much each of the five areas costs; unassigned spending goes to
  the hidden "Soul" area (shown only above 30%).

**What happens to the current engine**: the ledger becomes the source of truth
for actuals and balances. Planning features (commitments, forecasts,
scenarios) stay and read actuals from the ledger. Existing events and check-in
spends are migrated into transactions once, with a dry-run report first.
Today's Spending reads the ledger.

## Build order

1. Ledger core: accounts incl. cards/loans, transactions, transfers, balances.
2. Categories + cost centres + area mapping.
3. Spreading.
4. Reports (category, area, life object).
5. Migration of existing data + switch Today's Spending and balances over.
6. Capture shortcuts: brain dump "₹500 petrol" → draft transaction; later SMS /
   statement import.

## Questions for the owner

1. **Car purchase price**: include it in "cost of the car" (spread over the
   years you expect to keep it), or show it separately?
2. **Fuel spreading**: automatic between fills (default above), or do you
   prefer to set a period yourself?
3. **EMIs**: OK to split each EMI into principal (transfer) and interest
   (cost)? Hymn needs the loan's rate and tenure for that.
