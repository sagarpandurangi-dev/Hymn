# Admin page, usage tracking and beta invites

**Page:** `https://hymn-production-4828.up.railway.app/admin` (works on a phone). Sign in with your Hymn
email and password. Only emails in the Railway variable **`HYMN_ADMIN_EMAILS`** get in (now:
sagar9739@gmail.com), and only with a login from the last 12 hours. Every change made on the page is
recorded in its Log tab.

Code: `backend/metering.py` (counting, AI cost, budget, switches, settings), `backend/admin.py` (the admin
API, invites), `backend/admin_ui/index.html` (the page). Tests: `backend/unit_tests/test_admin.py`.

## What it shows

| Tab | What |
|---|---|
| Overview | accounts; active today / 7 / 30 days; new this week; active people per day (30 days); AI spend today and this month against the warning and stop; came back after a day / week / month; sign-up → habit funnel; areas and features used in the last 7 days (people, uses, errors); beta seats and invite-only |
| People | everyone with plan, last active, active days, AI spend this month, what they use most; search by email, name or group; "Open" shows one person (activity per day, features, AI by feature, setup steps, friends invited, errors) with actions |
| AI | spend per day, by feature, by model (tokens read/written, web searches), top spenders; switch each AI feature on or off |
| Invites | make codes (how many, uses each, group); every code with who made it, group, uses; turn one off |
| System | errors by route and the latest ones (route and status only); notifications today; phones registered; WhatsApp numbers |
| Settings | AI warning (₹5,000) and stop (₹10,000) a month; ₹ per US$ (88); invite-only (off); most accounts (200); uses of each person's code (5) |
| Log | every admin change |

**Actions on a person:** give Premium / make free / back to the Railway setting; extra AI for a week; sign out
everywhere; pause (they're signed out and can't sign in: "This account is paused"); delete (type their email;
uses the same deletion as the app). You can't pause or delete yourself here.

## Privacy rules (tested)

- The admin sees **counts, costs and dates, never content**: no task titles, notes, check-ins, people's
  names, money amounts or account names, messages, health readings or conditions.
- **Health is never shown per person.** In one person's view, health features (Health, food, habits, care,
  labs, watch, check-ups) are folded into "private", and the Health setup step is left out. Health appears only
  in totals with no person attached.
- Deleting an account deletes its usage and AI rows; totals with no person attached (`usage_totals`,
  `ai_daily`) stay. Per-call AI rows are kept 90 days, error rows 30 days.
- The privacy policy should say Hymn records which features each account uses and the AI cost per account.

## How it works

- **Usage:** a middleware counts every `/api/...` call per person (from the login token, no database read),
  day and feature (the first part of the route; a few finer: labs, payslips, investments, time-statements);
  written once a minute (`usage_daily`, `usage_totals`), with `users.last_active_at`. The admin page itself
  isn't counted. 5xx answers go to `errors` (method, route, status, person id).
- **AI cost:** `claude_client.get_client()` returns a metered client. Before each `messages.create/parse` it
  refuses (as "not available right now") when that feature is switched off or the month's spend has reached
  the stop; after it, tokens (read, written, cache read/write), web searches, model, feature, person and cost
  in $ and ₹ go to `ai_calls` and `ai_daily`. Prices (per million tokens): Haiku 5.5 $0.10 / $0.50, Sonnet 5.5
  $2 / $10, Opus 5.5 $4 / $20, Fable 5.2 $8 / $40; web search $10 per 1,000; unknown models counted at Opus
  prices. Metering trouble never blocks an AI call.
- **AI features that can be switched off:** plan-chat, planning, goals, life-plans, learning, inbox (brain
  dump), statements, payslips, food, labs, whatsapp.
- **Extra AI allowance** adds to the person's daily caps (`ai_budget`) until a date.

## Invites

- `invite_only` is **off** until the app's sign-up screen has an invite box (prompt R adds it); then switch it on
  in Settings.
- While on, sign-up needs a valid code, and stops at `beta_cap` accounts ("The beta is full right now").
- Every person has their own code (`GET /api/invites/mine` → `{code, used, left, link, invite_only}`), usable
  `invites_per_person` times; the people they invite get their own codes too. Admin codes have their own number
  of uses and a group ("cohort"); invited people inherit the inviter's group.
- `GET /api/invites/check?code=` → `{valid, invite_only, beta_full}` (for the sign-up screen).
- Sign-up takes an optional `invite_code`; the account records `invited_by`, `invite_code`, `cohort`.
- Optional Railway variable `HYMN_INVITE_LINK` (e.g. the website's join page) makes `/mine` return a link.

## Admin API

All under `/api/admin`, admin only: `GET overview`, `GET users?q=&sort=last_active|ai|joined`,
`GET users/{id}`, `POST users/{id}/plan {plan: premium|free|default}`,
`POST users/{id}/ai-allowance {strong, light, days}`, `POST users/{id}/sign-out`,
`POST users/{id}/suspend {suspended}`, `DELETE users/{id} {confirm_email}`, `GET ai?days=`, `GET system`,
`GET|PUT settings`, `GET|POST invites`, `POST invites/{code}/off`, `GET audit`.
