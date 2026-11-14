# Emergent prompt pack (credits refresh on the 18th)

Paste one prompt at a time, in order. After each: "Save to GitHub" onto the
`emergent-frontend` branch so Claude can check the work before the next one.
Every prompt starts with the two safety lines; keep them.

---

## 1. Fixes still pending (small)

> Do not modify anything under `backend/`. Do not change the backend URL in `frontend/src/lib/api.ts`.
>
> Skip anything below that is already done.
> 1. Finance tab: show the available-money row (`available_liquidity` from the dashboard: `available_unreserved` as "Available to spend", `reserved` as "Set aside") and the "Pending account → Assign" shortcut.
> 2. Remove Scenarios completely (`app/finance/scenarios-index.tsx`, `app/finance/scenarios-detail.tsx`, every link to them, their API functions). Keep the Forecast screens.
> 3. Forecast screen: show each currency's `basis` text as a small grey note; in each month show `usual_spending` as "Everyday spending", and `maybe_income` / `maybe_spending` in grey as "Maybe" when non-zero.
> 4. `TimeBlockEditor`: save cross-midnight blocks as one entry (e.g. 23:00 → 07:00), keep the "ends next day" hint, and make the overlap warning include saved overnight blocks.
> 5. Planned money form: tap-to-pick month selectors instead of typed YYYY-MM.
> 6. Me screen: a "Your Pamphlet ID" card from `GET /api/auth/me` (`hymn_alias` large if present, `hymn_id` below, copy buttons) with the line "One ID for Hymn and Pamphlet — share it instead of your phone number."
>
> Tell me what you changed.

## 2. Time on every check-in + faster Finance tab

> Do not modify anything under `backend/`. Do not change the backend URL in `frontend/src/lib/api.ts`.
>
> 1. **Check-in time (required):** on every check-in form (new and edit, including the quick check-in), add a row of tappable buttons: **15m, 30m, 45m, 60m, 2h, 3h** (tap one to select it; tapping another replaces it). Send the choice as `duration_minutes` (15, 30, 45, 60, 120, 180). Saving is blocked until one is picked, with the message "How long did it take?". Show the duration on check-in lists ("· 45m").
> 2. **Finance tab in one call:** load the Finance tab from `GET /api/screens/finance` instead of separate calls. It returns `{dashboard, planned_upcoming, planned_this_month}`: `dashboard` is exactly what `GET /api/finance/dashboard` returned; `planned_upcoming` is the 6 planned-money items the tab shows; `planned_this_month` is a list of `{month, currency, income, spend, moves, set_aside, maybe_in, maybe_out}`. Keep everything the tab shows today.
>
> Tell me what you changed.

## 3. The three money statements

> Do not modify anything under `backend/`. Do not change the backend URL in `frontend/src/lib/api.ts`.
>
> Add a **Statements** section on the Finance tab with three screens. All amounts are strings; show ₹ with Indian grouping.
> 1. **Statement of Net Worth** (`GET /api/reports/net-worth`), the old side-by-side format: **left column "Liabilities & Net Worth"**, **right column "Assets"**, both ending in the same total. Left: `left.net_worth` as "Opening net worth (1 Apr)", "Add: surplus this year", "Other changes", total; then `left.liabilities[]` groups with their lines. Right: `right.assets[]` groups (`label`, `amount`, `lines[]` with `name`, `amount`). Title "Statement of Net Worth as at <as_of>". On a phone, the two columns may stack (left first) if they don't fit.
> 2. **Income & Expenditure** (`GET /api/reports/income-expenditure?month=YYYY-MM`), vertical: INCOME groups, Total income, EXPENDITURE groups, Total expenditure, SURPLUS / (DEFICIT), Savings rate. Three columns: This month, Last month, Year to date (`this_month`, `last_month`, `year_to_date`). Tap a group to expand its `categories`; tap a category to open its entries from `GET /api/reports/entries?category=<category>&start=<start>&end=<end>` (date, description, amount). Month picker at the top.
> 3. **Cash Flow** (`GET /api/reports/cash-flow?month=YYYY-MM`): Opening cash, then each section (`Living`, `Investing`, `Borrowing`, `Other`) with its lines and net, Net change, Closing cash; a small ✓ "Adds up" when `adds_up` is true.
>
> Tell me what you changed.

## 4. Time statements

> Do not modify anything under `backend/`. Do not change the backend URL in `frontend/src/lib/api.ts`.
>
> Add a **My week** screen (from the Today tab) using `GET /api/reports/time?week_start=YYYY-MM-DD` (any day; it uses that week's Monday), with week arrows.
> 1. **Commitments:** Fixed, Flexible & set aside, Free (all `…_hours`), out of 168h — as a simple bar plus numbers. Below: "Time invested this year" from `commitments.time_assets_this_year` (area label + hours).
> 2. **Time spent:** a table of `spent.areas[]` — area, Planned, Actual, Gap (gap red when negative for Learning/Health/Family, red when positive for Work/Commute). Tap an area to show its `lines`. Show "Soul (untracked): X h" only when `spent.show_soul` is true. Show "Waking hours as planned: N%".
> 3. **Time flow:** Planned free → Overruns → Skipped plans → Untracked (`flow.*_hours`).
> 4. If `untimed_checkins` > 0: "N check-ins this week have no time".
>
> Tell me what you changed.

## 5. Life objects (Premium)

> Do not modify anything under `backend/`. Do not change the backend URL in `frontend/src/lib/api.ts`.
>
> Add **Things I own & owe** (Finance tab), Premium only (a 403 means show "Premium feature").
> 1. List from `GET /api/life-objects`: name, type, `ltc.to_date`, `ltc.per_month`, `ltc.per_unit` with its `unit` ("₹4.20 per km").
> 2. **Add** (`POST /api/life-objects`): type (Asset / Liability / Habit / Venture), kind (car, bike, house, phone, credit card, loan, smoking, gym, business, other), name, start date, and by type: asset → price, extra costs (registration etc.), life in months, resale value; loan → account (pick a loan or card account), loan amount, interest % a year, tenure in months, first EMI date, reducing/flat, EMI (optional); habit → "words on the bill" (`match_words`, e.g. "PAN SHOP").
> 3. **Detail** (`GET /api/life-objects/{id}`): Lifetime cost to date with the breakdown (`getting_it`, `value_lost`, `keeping_it` list, `cost_of_money`, `came_back`), per month, per unit, projected over its life, hours; the entries list. Buttons: **Loan schedule** (`GET /api/life-objects/{id}/schedule`: EMI, total interest, table of rows) for loans; **Fuel** (`GET /api/life-objects/{id}/fuel`: km per litre, cost per km, the stretches) for car/bike; **Mark sold / ended** (`PATCH` with `ended_on`, `sold_for`).
> 4. Check-ins on a car/bike (its `project_id`): add optional fields Odometer, Price per litre, Litres, Full tank (yes/no) saved in the check-in's `data` as `odometer`, `price_per_litre`, `litres`, `full_tank`.
>
> Tell me what you changed.

## 6. Family net worth

> Do not modify anything under `backend/`. Do not change the backend URL in `frontend/src/lib/api.ts`.
>
> Add a **Family** screen (from the Me tab).
> 1. `GET /api/family` → if `family` is null, a "Create my family" button (`POST /api/family`). Show `invites_for_me` with Accept (choose "Share my total" or "Share my breakdown" → `POST /api/family/invites/{id}/accept` with `share` = `total`/`full`) and Decline.
> 2. Members list with **Invite by Pamphlet ID** (`POST /api/family/invite` with `pamphlet_id`, `relation`) and **Add someone without the app** (`POST /api/family/members` with `name`, `relation`). My sharing setting (`PATCH /api/family/me`) and Leave (`POST /api/family/leave`).
> 3. **Add an entry** for someone (or joint): side (asset/liability), group (assets: fixed, investments, retirement, deposits, cash; liabilities: loans, current), name, amount, owners with % that add up to 100 (`POST /api/family/items`).
> 4. **Family net worth** (`GET /api/family/net-worth`): a column per member (`members[]`: name, `net_worth`; and `assets`/`liabilities` by group when shared in full) and the family total (`family`). Note: "Joint things are counted once."
>
> Tell me what you changed.

## Optional, if credits remain

> Do not modify anything under `backend/`. Statement review screen: (1) "Accept all guesses" accepts every line's current suggestion except `confidence` = `new`, then shows the confirm summary; (2) "Select" mode to set the same kind/category on several lines; (3) a search box on statement detail filtering lines by description or amount; (4) the category picker uses the two-level tree from `GET /api/ledger/categories` (groups, then categories). Tell me what you changed.
