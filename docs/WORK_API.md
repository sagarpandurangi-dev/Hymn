# Work — API notes for the app

Keep work in its place: it pays for the life you want, it grows you, and it doesn't quietly eat everything else.

## Work roles — `/api/work/roles`
- `POST` `{type: salaried|self_employed|business_owner|freelancer|articleship|looking_for_work|homemaker, organisation, title, started_on, work_days[], start_time "09:30", end_time "18:30", office_days[], commute_minutes (each way), leave_types[{key, label, per_year, carried_forward, carry_forward_max, year_starts "MM-DD"}], next_appraisal, notes}`.
  Saving a role creates its fixed time blocks (work, plus commute before and after on office days), so free time, plans, study and the time statements all see it. A person can have more than one role (job + side business).
- Each role comes back with `features {leave, appraisal, payslips, wins, time}` — show only those parts. Employed (salaried, articleship): leave + appraisals; salaried: payslips. Also `planned_hours_per_week`, `commute_hours_per_week`, and `leave[]` balances.
- `GET` (all), `GET /{id}`, `PATCH /{id}` (any field; `ended_on` ends the role and frees its time), `DELETE /{id}`.

## Work time
- `POST /api/work/days` `{role_id, date, extra_minutes, note}` — "stayed 2h late" = 120, "left 1h early" = −60, a weekend morning = 180. One per role per day (a new one replaces it). Quick buttons: +30m, +1h, +2h, −1h, half day.
- `GET /api/work/week?week_start=` → `{work_planned, work_actual, commute, family, over_plan_hours, in_its_box, family_change_hours, last_week{…}, sleep_avg?, stress_avg? (with health consent), summary}`. Show `summary` big: "Work stayed in its box this week." / "Work ran 5.5 hours over plan, family time was down 3 hours."

## Leave (employed roles)
- `POST /api/work/leave` `{role_id, type, from, to, half_day, days?, reason}` → the leave with `days` (work days only; `days` overrides for holidays) and the type's `balance`; `warning` if it goes beyond.
- `DELETE /api/work/leave/{id}` cancels.
- Balances (on the role): `{type, label, per_year, carried_forward, taken, planned, left, year_ends, expiring?}` — `expiring` = days that will be lost at year end beyond the carry-forward limit.
- The planner checks leave for plans that need time off.

## Wins and appraisals
- `POST /api/work/wins` `{role_id, date, text}` (one line: "Closed the audit two weeks early"); `DELETE /api/work/wins/{id}`.
- `GET /api/work/roles/{id}/appraisal-pack?since=` → `{wins, wins_by_month[{month, wins[]}], learning[{journey, hours}], next_appraisal}`.

## Payslips (Premium, salaried)
1. `POST /api/work/payslips/read` `{file_base64, media_type, password}` → `{month, employer, earnings[{label, amount}], deductions[{label, amount, kind: pf|income_tax|professional_tax|health_insurance|other}], gross, net, employer_pf, problems[]}`. Nothing saved; file and password not kept. Show `problems` (sums that don't match) for the person to fix.
2. `POST /api/work/payslips` `{role_id, month, earnings, deductions, gross, net, employer_pf, pf_account_id}` — 400 if the sums don't add up, 409 if that month is already saved. On the money book: PF (yours + employer's) goes into the EPF account, tax / professional tax / employer health insurance show as costs, other deductions as "not yet sorted" — so income shows gross while take-home still arrives through the bank, never twice. `recorded_in_money_book` says what was recorded.
3. `GET /api/work/payslips?role_id=`.

## Nudges
Setting `work` (`{enabled, time}`, default 18:30): appraisal in 3 weeks (with the wins count); leave days expiring in 30 days; Friday "Work ran 4 hours over this week — the weekend is yours" when it ran over by more than 2 hours. Push `data`: `{screen: "work", role_id?}`.
