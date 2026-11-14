# Hymn — working notes for Claude

Hymn is a personal life-management app ("help me follow through on my life"),
growing into a copilot for daily and life decisions across five areas:
**Money, Health, Family & Relationships, Learning, Work**. Untracked time and
money go to a hidden "Soul" area, shown only above 30% of time or money.

The owner is not a developer. Explain in plain language, conclusion first,
short. Never ask them to paste secrets into chat.

## How the project is run

- **Two builders.** Claude Code owns `backend/` (and infrastructure). Emergent
  (an AI app builder) owns `frontend/` screens. Emergent cannot pull from
  GitHub, so it must never edit `backend/`. Give the owner precise Emergent
  prompts that start with "Do not modify anything under `backend/`". When
  Emergent guesses response field names wrong, prefer adding the expected
  names on the backend over spending Emergent credits.
- **Frontend backend URL** is hard-coded in `frontend/src/lib/api.ts`
  (`https://hymn-production-4828.up.railway.app`) because Emergent's
  environment kept resetting the env var. Don't change it.
- **Git:** work on the session's designated branch; open a PR into `main`;
  merge (method: merge, never squash) only when the owner says "merge it" and
  CI is green. After a merge, reset the branch to `origin/main`.
- **CI:** `.github/workflows/backend-tests.yml` runs `backend/safety_tests`
  and `backend/unit_tests` (offline; mongomock-motor; Claude replaced by
  fakes). Every change ships with tests; for important rules, break the code
  on purpose once and confirm a test fails.
- **Hosting:** Railway (project "determined-patience", service "Hymn", root
  `/backend`, Dockerfile, healthcheck `/api/` for zero-downtime deploys,
  region Singapore `asia-southeast1-eqsg3a` since 14 Nov 2026).
  MongoDB Atlas (Mumbai). Railway auto-deploys `main`.
- **Railway access from a session:** the "Hymn" cloud environment holds a
  Railway project token (proxy-injected header `Project-Access-Token` for
  `backboard.railway.com`) and allows `hymn-production-4828.up.railway.app`.
  Use the GraphQL API to read deployments/logs; list variable *names* only.
- **Env vars (Railway):** `MONGO_URL`, `DB_NAME`, `JWT_SECRET`,
  `HYMN_RUNTIME_MODE=production`, `ANTHROPIC_API_KEY`, `HYMN_PREMIUM_EMAILS`.
  Optional: `HYMN_ASSISTANT_MODEL`, `HYMN_PLANNING_MODEL`,
  `HYMN_STATEMENT_MODEL`, `HYMN_DEFAULT_PLAN`, `HYMN_NUDGES`, `CORS_ORIGINS`, `HYMN_ALIAS_GRANTS`, `HYMN_REQUIRE_CHECKIN_DURATION`, `HYMN_TEMPLATE_PREVIEW_EMAILS`, `HYMN_REVIEWED_TEMPLATES`.
- **AI models:** brain dump, weekly patterns, statement reading → Claude Haiku
  5.5 (cost); planning chat, goal merge → Claude Opus 5.5. All through
  `backend/claude_client.py` (shared client, refusal fallbacks only for models
  that support them).

## Backend map (`backend/`)

| Module | What |
|---|---|
| `server.py` | FastAPI app, auth (throttle, token_version revocation, 10-char passwords), goals/projects/tasks/check-ins, router wiring, startup indexes |
| `plans.py` | free/premium plans (`users.plan` → `HYMN_PREMIUM_EMAILS` → `HYMN_DEFAULT_PLAN`) |
| `inbox.py`, `inbox_ai.py` | brain dump → task/reminder/idea/plan; daily review; nuggets → task/calendar/wishlist; weekly patterns |
| `nudges.py` | scheduler (every minute): daily review (adaptive time), reminders, weekly summary; Expo push; in-app feed |
| `planning_engine.py`, `goal_merge.py` | AI planning chat with web search; plan hierarchy; goal merge |
| `finance_manager.py`, `finance_advanced.py`, `money_service.py`, `portfolio_manager.py` | existing finance engine: plans, commitments, forecasts. For converted users `money_service` (balances, availability, monthly spending), Finance position and Today `/spending` read the ledger; shapes unchanged |
| `planned_money.py` | one list of expected money in/out (once / monthly / yearly; sure / maybe; set-aside one-offs); shows older monthly commitments, one-off commitments and expected income read-only; the forecast reads it. API notes: `docs/PLANNED_MONEY_API.md` |
| `hymn_ids.py` | Hymn ID: every ID 7 characters. Real ID = 1 letter (no I/O) + 6 digits, free random standard one per user (assigned at signup / first seen), permanent, meant to be shared with Pamphlet. Alias = 7 letters+digits (2+ letters, never real-ID shaped, e.g. PRIYA88), costs more. Special numbers (repeats, sacred, sequences, palindromes, birthdays DDMMYY) and aliases are graded and reserved until the shop (payments) opens. Look-alikes O=0, I=1 are the same ID; aliases also can't share a look-alike skeleton (5/S, 8/B, 2/Z, 6/G, 0/O, 1/I/L) or read as a real ID. Rate-limited check/find. Owner can grant aliases before the shop via Railway var `HYMN_ALIAS_GRANTS` ("email=ALIAS,..."). Prices set themselves: base per grade (`HYMN_ID_BASE_PRICES` override) × rarity × demand (distinct people checking it in 30 days) × name popularity, rounded to price points; very wanted IDs go to auction |
| `categories.py` | two-level category tree (group → category) for spending and income; older flat keys stay valid as "<Group> (other)"; `GET /api/ledger/categories` |
| `life_objects.py` | Premium: assets, liabilities, habits, ventures, each backed by an auto-created project (check-ins, tasks). Lifetime cost (LTC): getting it + value lost (straight-line) + keeping it (tagged or auto-claimed categories, match words) + cost of money (interest, fees, penalties, annual fees; liabilities count only borrowing costs) − what came back; to date, per month, per unit (km from check-in odometer, visits, days), projected over life, hours from check-ins. No opportunity cost (owner decision). Loans: EMI schedule from terms (reducing / flat, or the document's EMI), `GET /api/life-objects/{id}/schedule`; statement lines matching an EMI (±₹1, ±10 days) are suggested as loan_payment split into principal and interest. Fuel: fill check-ins (odometer + price per litre or litres + amount) give mileage between full tanks, cost per km and per day (`GET /api/life-objects/{id}/fuel`) |
| `reports.py` | the three statements from the ledger + life objects: Statement of Net Worth (side by side; opening at 31 Mar + surplus + other changes), Income & Expenditure (vertical, group → category → entries; month / last month / FY to date; asset value loss included), Cash Flow (living / investing / borrowing). API notes: `docs/REPORTS_API.md` |
| `family.py` | family net worth: households; members with accounts invited by Pamphlet ID/alias and must accept, each chooses to share total or full breakdown (never leaked via group lines), can leave; notional members (kids, parents) with entries only their creator edits; joint items with ownership shares counted once. `/api/family/...` |
| `time_reports.py` | weekly time statements (168h) in one call `GET /api/reports/time?week_start=`: Time Commitments (fixed / flexible + set aside / free; time assets = hours this year per area), Time Spent (area planned vs actual vs gap; fixed blocks taken as kept + check-in durations; Soul = untracked, shown above 30%; % waking hours as planned), Time Flow (planned free − overruns + skipped = untracked). Sleep under Health. Check-ins carry `duration_minutes`; required when Railway var `HYMN_REQUIRE_CHECKIN_DURATION=1` (switch on once the app's time buttons ship) |
| `request_cache.py`, `screens.py` | speed: within one GET request the ledger is synced and loaded once (per-request memo, cleared by writes); `GET /api/screens/finance` returns the whole Finance tab (dashboard + next 6 planned items + this month's planned totals) in one call |
| `life_plans.py` | the planning engine for any ask (45 min of guitar → house + wedding + kids): a plan has a target date T, requirements ("what must go right": time / money / condition, by area) and risks ("what may stop it": likelihood, early-warning sign, mitigation). Code (never the AI) benchmarks each requirement against what's available now and what can be built up by T−1 (time: real free slots from blocks + bookings in the user's time zone; money: available today and a month-by-month projection from planned money + usual spending; condition: the user's answer) → status now / by_then / short / unknown and a verdict. `POST /api/life-plans`, `/quick-time`, `/{id}/book` (reserves a free slot), `/{id}/requirements/{rid}/answer`. Accepting locks a plan in: money → monthly "Save for" items in planned money until the month before (or a set-aside one-off if already covered), unanswered/no conditions → "Find out"/"Sort out" tasks, unbooked time → "Book time" task, risk mitigations → tasks; a plan's own savings count as kept for it in its benchmark; statuses at acceptance are stored and `drift` lists what slipped to short; nudges send a "needs attention" nudge on the 1st of the month (10:00 local). Dropping undoes the lock-in |
| `plan_assistant.py` | the new planning chat (`POST /api/plan-chat`): Opus with tools — get_context (facts with sources; user corrections in `user_facts` win), remember_fact, find_time, check_money, future_cost (6% default), loan_affordability (EMI ≤ ~50% of take-home), propose_plan (saves a **draft** life plan and returns the benchmark), web search. The AI never computes numbers about the person; tool errors go back to it; outages keep nothing. `POST /api/life-plans/{id}/accept` activates one option and drops the conversation's other drafts. Replaces `planning_engine.py` once the app switches (prompt 7 of the pack) |
| `plan_templates.py` | checklists (requirements + risks with sources, across all areas) for house (RBI LTV down payment, stamp duty, EMI ≤ ~50%, credit score, job stability, RERA), wedding, first child (health items marked DRAFT pending a doctor). Planner tool `use_template`. Drafts visible only to `HYMN_TEMPLATE_PREVIEW_EMAILS`; reviewed keys go in `HYMN_REVIEWED_TEMPLATES` after an expert signs off |
| `ledger.py` | double-entry ledger: transactions with inline postings summing to zero; accrual and cash views; starter categories |
| `ledger_conversion.py` | one-time, self-verifying conversion of old finance data into the ledger (preview → fingerprinted apply) |
| `ledger_sync.py` | after conversion, keeps the ledger in step with old finance records (new/changed/rejected events, retyped balances) using the conversion's own rules; only touches derived entries; links to statement entries instead of double counting; runs before ledger reads and statement suggestions |
| `statements.py`, `statements_ai.py` | Premium: PDF upload (password used in memory only), Claude reads lines (debit = money out, credit = money in), arithmetic verification, plain-language reasons |
| `statement_matching.py` | Xero-style suggestions per line (already recorded / own-account match / learned rules / patterns / built-in merchant list / similar names the user filed / spending habits by amount / one AI guess per unknown merchant per user), confirm into ledger, learning, opening balance, reconciliation |
| `merchant_directory.py` | free built-in list of ~900 well-known (mostly Indian) merchant keywords → spending category; mixed merchants and people's names deliberately left out |

Plans and decisions: `docs/plans/finance-audit.md`. Ready-to-paste Emergent prompts for the 18 Nov credit refresh: `docs/EMERGENT_PROMPTS_NOV18.md`. API notes for Emergent:
`docs/INBOX_API.md`, `docs/NUDGES_API.md`. Deploy guide: `docs/DEPLOY_RAILWAY.md`.

## Owner decisions to respect

- Finance must be a true ledger: no double counting; transfers and card bill
  payments are not spending; both cash and accrual views.
- Car = asset, straight-line depreciation over its life. Fuel spread between
  fills; ask odometer + price per litre at each fill; compute real mileage.
- EMIs split into principal and interest; ask for the loan document, else
  principal, rate, tenure, method.
- Statement upload is Premium; free users enter opening balances by hand.
- Matching must learn from the user's choices and suggest next time.
- One free Emergent publish: the published build must be the tester beta.
  Before beta: push notifications need a native build with Firebase.
- The MongoDB password and Anthropic key appeared in chat; the owner checked
  where they're exposed (only this chat, behind their Claude login; repo
  history clean; phone screenshot deleted) and chose **not** to rotate them
  (14 Nov 2026). Don't raise it again unless the Claude account may be
  compromised or is shared.

## Roadmap

Done: auth hardening, CI, Railway, brain dump + review + nuggets, nudges
backend, planning on Anthropic SDK, one spending truth, ledger core,
conversion preview/apply, statement upload + verification, statement matching
with learning.

Next:
1. Owner tests statement review/confirm; fix what they find.
2. Money book switch-over: done for balances, availability, monthly and Today spending (converted users). Left: recent-activity list still shows old events; owner must run the conversion (Money book screen) for the switch to apply.
3. Categories/life objects (car, house, habits) per area; depreciation; fuel
   and mileage; loans (principal/interest, documents); cash vs accrual views.
4. Speed: Singapore (done); one sync/load per request (done); one call per screen (Finance done: `/api/screens/finance`, app to adopt).
5. Dream journey (blueprint: shelved draft PRs #5 and #9 on the old July code
   — never merge them; rebuild on today's code): context review with
   corrections, feasibility on real time and money, editable plan map.
6. Family, Work (via time commitments; company runs MS Office), Health
   (Android Health Connect; owner uses a Samsung watch), Learning.

Later (owner's strategy, decided but not to build yet): intent marketplace —
classify fulfillable brain-dump items (category, locality, time window),
aggregate demand counts with minimum-count suppression, per-item opt-in
"Let Hymn assist" consent behind a feature flag, matching with the owner's
separate vendor app. Needs legal review (DPDP; SEBI/RIA for investment
matching) before anything leaves Hymn.
