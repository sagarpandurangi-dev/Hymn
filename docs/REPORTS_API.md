# Money statements API (for the app)

All amounts are strings, per currency. Read-only.

## Statement of Net Worth — `GET /api/reports/net-worth?as_of=YYYY-MM-DD`
Side by side: **left** = net worth + liabilities, **right** = assets; `left.total == right.total`.
- `left.net_worth`: `opening` (31 March), `surplus_this_year`, `other_changes`, `total`.
- `left.liabilities[]` / `right.assets[]`: `{group, label, amount, lines: [{id, name, amount}]}`.
  Asset groups: Fixed assets, Investments, Retirement & long-term, Deposits & money lent, Cash & bank.
  Liability groups: Loans, Current liabilities.

## Income & Expenditure — `GET /api/reports/income-expenditure?month=YYYY-MM`
Vertical. Columns `this_month`, `last_month`, `year_to_date` (from 1 April), each:
`income[]`, `total_income`, `expenditure[]`, `total_expenditure`, `surplus`, `savings_rate_percent`.
Groups: `{group, label, amount, categories: [{category, label, amount}]}` — tap a group to show
its categories, tap a category to load entries:
`GET /api/reports/entries?category=expense:groceries&start=…&end=…` → `[{id, date, description, amount}]`.

## Cash Flow — `GET /api/reports/cash-flow?month=YYYY-MM` (or `start`/`end`)
`opening_cash` → `sections[]` (`Living`, `Investing`, `Borrowing`, `Other`; each `{label, lines, net}`)
→ `net_change` → `closing_cash`; `adds_up` is true when they reconcile.
