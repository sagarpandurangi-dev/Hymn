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
  `HYMN_STATEMENT_MODEL`, `HYMN_DEFAULT_PLAN`, `HYMN_NUDGES`, `CORS_ORIGINS`, `HYMN_ALIAS_GRANTS`, `HYMN_REQUIRE_CHECKIN_DURATION`, `HYMN_TEMPLATE_PREVIEW_EMAILS`, `HYMN_REVIEWED_TEMPLATES`, `HYMN_FOOD_MODEL`, `HYMN_FOOD_PHOTOS_FREE`, `HYMN_FOOD_PHOTOS_PREMIUM`, `HYMN_LAB_MODEL`, `HYMN_LAB_READS_FREE`, `HYMN_LAB_READS_PREMIUM`, `HYMN_LEARNING_MODEL`, `HYMN_LEARNING_LIGHT_MODEL`, `HYMN_PAYSLIP_MODEL`, `HYMN_AI_STRONG_PER_DAY`(`_PREMIUM`), `HYMN_AI_LIGHT_PER_DAY`(`_PREMIUM`). WhatsApp (when Meta approves): `WA_PHONE_NUMBER_ID`, `WA_ACCESS_TOKEN`, `WA_APP_SECRET`, `WA_VERIFY_TOKEN`, `WA_DISPLAY_NUMBER`; optional `WA_GRAPH_VERSION`, `WA_TEMPLATE_LANG`, `WA_MESSAGING_LIMIT`, `HYMN_WHATSAPP_MODEL`, `HYMN_SUPPORT_EMAIL`, `HYMN_SUPPORT_URL`, `HYMN_APP_LINK`. Admin: `HYMN_ADMIN_EMAILS` (owner's email); optional `HYMN_INVITE_LINK`. Payments (when set up): `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`, `REVENUECAT_WEBHOOK_AUTH`; optional `HYMN_TRIAL_DAYS`.
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
| `nudges.py` | scheduler (every minute): daily review (adaptive time), reminders, weekly summary; Expo push; in-app feed. Limits (setting `limits`): at most `daily_max` pushes a day (default 4; reminders, habit urges and the daily review always get through, extras `held` in the feed); morning brief (default on, 08:30): health/people/learning morning times move to `brief_time` and arrive as one push; any 2+ due together are bundled |
| `planning_engine.py`, `goal_merge.py` | AI planning chat with web search; plan hierarchy; goal merge |
| `finance_manager.py`, `finance_advanced.py`, `money_service.py`, `portfolio_manager.py` | existing finance engine: plans, commitments, forecasts. For converted users `money_service` (balances, availability, monthly spending), Finance position and Today `/spending` read the ledger; shapes unchanged |
| `planned_money.py` | one list of expected money in/out (once / monthly / yearly; sure / maybe; set-aside one-offs); shows older monthly commitments, one-off commitments and expected income read-only; the forecast reads it. API notes: `docs/PLANNED_MONEY_API.md` |
| `hymn_ids.py` | Hymn ID: every ID 7 characters. Real ID = 1 letter (no I/O) + 6 digits, free random standard one per user (assigned at signup / first seen), permanent, meant to be shared with Pamphlet. Alias = 7 letters+digits (2+ letters, never real-ID shaped, e.g. PRIYA88), costs more. Special numbers (repeats, sacred, sequences, palindromes, birthdays DDMMYY) and aliases are graded and reserved until the shop (payments) opens. Look-alikes O=0, I=1 are the same ID; aliases also can't share a look-alike skeleton (5/S, 8/B, 2/Z, 6/G, 0/O, 1/I/L) or read as a real ID. Rate-limited check/find. Owner can grant aliases before the shop via Railway var `HYMN_ALIAS_GRANTS` ("email=ALIAS,..."). Prices set themselves: base per grade (`HYMN_ID_BASE_PRICES` override) × rarity × demand (distinct people checking it in 30 days) × name popularity, rounded to price points; very wanted IDs go to auction |
| `categories.py` | two-level category tree (group → category) for spending and income; older flat keys stay valid as "<Group> (other)"; `GET /api/ledger/categories` |
| `life_objects.py` | Premium: assets, liabilities, habits, ventures, each backed by an auto-created project (check-ins, tasks). Lifetime cost (LTC): getting it + value lost (straight-line) + keeping it (tagged or auto-claimed categories, match words) + cost of money (interest, fees, penalties, annual fees; liabilities count only borrowing costs) − what came back; to date, per month, per unit (km from check-in odometer, visits, days), projected over life, hours from check-ins. No opportunity cost (owner decision). Loans: EMI schedule from terms (reducing / flat, or the document's EMI), `GET /api/life-objects/{id}/schedule`; statement lines matching an EMI (±₹1, ±10 days) are suggested as loan_payment split into principal and interest. Fuel: fill check-ins (odometer + price per litre or litres + amount) give mileage between full tanks, cost per km and per day (`GET /api/life-objects/{id}/fuel`) |
| `reports.py` | the three statements from the ledger + life objects: Statement of Net Worth (side by side; opening at 31 Mar + surplus + other changes), Income & Expenditure (vertical, group → category → entries; month / last month / FY to date; asset value loss included), Cash Flow (living / investing / borrowing). API notes: `docs/REPORTS_API.md` |
| `family.py` | family net worth: households; members with accounts invited by Pamphlet ID/alias and must accept, each chooses to share total or full breakdown (never leaked via group lines), can leave; notional members (kids, parents) with entries only their creator edits; joint items with ownership shares counted once. `/api/family/...` |
| `time_reports.py` | weekly time statements (168h) in one call `GET /api/reports/time?week_start=`: Time Commitments (fixed / flexible + set aside / free; time assets = hours this year per area), Time Spent (area planned vs actual vs gap; fixed blocks taken as kept + check-in durations; Soul = untracked, shown above 30%; % waking hours as planned), Time Flow (planned free − overruns + skipped = untracked). Sleep under Health. Check-ins carry `duration_minutes`; required when Railway var `HYMN_REQUIRE_CHECKIN_DURATION=1` (switch on once the app's time buttons ship) |
| `request_cache.py`, `screens.py`, `display.py` | speed: within one GET request the ledger is synced and loaded once (per-request memo, cleared by writes); one call per screen: `GET /api/screens/finance` (dashboard + next 6 planned items + month totals + a ready-worded `headline`), `/api/screens/today` (greeting, 3 things, next day that matters, free time, left to spend, setup), `/api/screens/life` (one line per area with status). `display.py` words money (₹12,450 / ₹1.84 L / ₹2.5 Cr), days (Today / Tuesday / 24 Nov) and durations the design guide's way |
| `life_plans.py` | the planning engine for any ask (45 min of guitar → house + wedding + kids): a plan has a target date T, requirements ("what must go right": time / money / condition, by area) and risks ("what may stop it": likelihood, early-warning sign, mitigation). Code (never the AI) benchmarks each requirement against what's available now and what can be built up by T−1 (time: real free slots from blocks + bookings in the user's time zone; money: available today and a month-by-month projection from planned money + usual spending; condition: the user's answer) → status now / by_then / short / unknown and a verdict. `POST /api/life-plans`, `/quick-time`, `/{id}/book` (reserves a free slot), `/{id}/requirements/{rid}/answer`. Accepting locks a plan in: money → monthly "Save for" items in planned money until the month before (or a set-aside one-off if already covered), unanswered/no conditions → "Find out"/"Sort out" tasks, unbooked time → "Book time" task, risk mitigations → tasks; a plan's own savings count as kept for it in its benchmark; statuses at acceptance are stored and `drift` lists what slipped to short; nudges send a "needs attention" nudge on the 1st of the month (10:00 local). Dropping undoes the lock-in |
| `plan_assistant.py` | the new planning chat (`POST /api/plan-chat`): Opus with tools — get_context (facts with sources; user corrections in `user_facts` win), remember_fact, find_time, check_money, future_cost (6% default), loan_affordability (EMI ≤ ~50% of take-home), propose_plan (saves a **draft** life plan and returns the benchmark), web search. The AI never computes numbers about the person; tool errors go back to it; outages keep nothing. `POST /api/life-plans/{id}/accept` activates one option and drops the conversation's other drafts. Replaces `planning_engine.py` once the app switches (prompt 7 of the pack) |
| `plan_templates.py` | checklists (requirements + risks with sources, across all areas) for house (RBI LTV down payment, stamp duty, EMI ≤ ~50%, credit score, job stability, RERA), wedding, first child (health items marked DRAFT pending a doctor). Planner tool `use_template`. Drafts visible only to `HYMN_TEMPLATE_PREVIEW_EMAILS`; reviewed keys go in `HYMN_REVIEWED_TEMPLATES` after an expert signs off |
| `health.py` | Health (healthspan): consent-gated profile (conditions, medicines, family history, smoking, screening answers), measurements with source (you/watch/lab/doctor/ai) and date, 30-second daily log, six domains with Sanskrit lens and DRAFT Indian-cut-off rules (`RULES_REVIEWED=False` until a doctor signs off): rating 0–4 from the worst indicator, **no overall score**, missing/outdated never treated as normal, red flags first (112, Tele-MANAS 14416), weight-loss screening, delete-all. Health plans are life plans with `for_what` / `serves_plan_id` ("what life is this for?"); the planner asks it and never motivates with fear. API notes: `docs/HEALTH_API.md` |
| `habits.py` | habits to change (tobacco, betting — quit only; alcohol with "don't stop suddenly if heavy daily" safety; sugar, junk food, screens, late nights, caffeine, custom/private): tied to "for what" / a dream plan; days on track in the last 28 (no streaks); urge button returns their own reason + what to do instead; welcome back after slips or gaps; money freed (and a dream-fund monthly saving in planned money) and hours freed; "steady the edge" tips from stress/sleep. Health also has a portions food log, optional labs ("not measured", never nagged) and log-based suggestions (`/api/health/suggestions`) |
| `food_catalog.py`, `food_ai.py`, `food_log.py` | food log: built-in list of 200 everyday Indian + foreign foods per real serving (roti, katori, plate) with typical values and ranges (±10% simple, −20/+25% dishes; `VALUES_REVIEWED=False` until a nutritionist checks); photo → Haiku names foods and servings only (never calories; or transcribes a nutrition label) → person confirms → numbers from the list in code; own foods; calories shown as a range, portions first and written into Health's daily log; eating-disorder history → portions only; photo allowance per month (`HYMN_FOOD_PHOTOS_FREE` 30, `HYMN_FOOD_PHOTOS_PREMIUM` 300); photos never stored. API notes in `docs/HEALTH_API.md` |
| `health_sync.py`, `health_labs.py`, `health_checkups.py`, `health_reports.py` | Health stage 2: any-watch sync (Health Connect / Apple Health / phone steps; one value per metric per day; your own entry beats the watch via `health.one_per_day`); optional lab reports (AI copies as printed, code recognises tracked tests by whole name, converts units, refuses unexpected units; file never stored; `HYMN_LAB_READS_FREE` 3 / `_PREMIUM` 20); check-up calendar from age/sex/conditions/family history/tobacco (DRAFT); 90-day progress (first 30 days vs days 61–90; no verdict on weight); doctor summary (JSON or text; private habits only on request). API notes in `docs/HEALTH_API.md` |
| `care.py`, `health_nudges.py` | caregiver mode: care profiles (`care_…` ids, owned by one account, their consent confirmed) used as the health subject via `?for=` on every health route (`health.person`/`subject`); deleting one deletes their data. Health nudges (setting `health`, default 09:30): one a day per person — 90-day report ready → check-up overdue/due soon (weekly cap) → gentle log reminder after 3 quiet days (self, weekly cap); habit urge check-ins 15 min before the usual urge time (`habit_logs.urge_times`); never in quiet hours. Planner sees health only with profile `use_in_planner` (summary only: `health.planner_summary`); life plans have `health` requirements (metric + target, benchmarked from 2-week averages; `health.HEALTH_TARGETS`) |
| `ledger.py` | double-entry ledger: transactions with inline postings summing to zero; accrual and cash views; starter categories |
| `ledger_conversion.py` | one-time, self-verifying conversion of old finance data into the ledger (preview → fingerprinted apply) |
| `ledger_sync.py` | after conversion, keeps the ledger in step with old finance records (new/changed/rejected events, retyped balances) using the conversion's own rules; only touches derived entries; links to statement entries instead of double counting; runs before ledger reads and statement suggestions |
| `statements.py`, `statements_ai.py` | Premium: PDF upload (password used in memory only), Claude reads lines (debit = money out, credit = money in), arithmetic verification, plain-language reasons |
| `statement_matching.py` | Xero-style suggestions per line (already recorded / own-account match / learned rules / patterns / built-in merchant list / similar names the user filed / spending habits by amount / one AI guess per unknown merchant per user), confirm into ledger, learning, opening balance, reconciliation |
| `merchant_directory.py` | free built-in list of ~900 well-known (mostly Indian) merchant keywords → spending category; mixed merchants and people's names deliberately left out |
| `cas_import.py` | Premium: investments from a CAMS/KFintech or NSDL/CDSL CAS PDF, parsed in code with `casparser` (MIT, pinned; no AI). Preview (password in memory only; PAN/contact details not stored) → apply: one account per fund folio (`mutual_fund`), per demat account for shares/bonds, per PRAN for NPS (`cas_key`); value = market value on the valuation date. Money-book users: first value is an `opening_balance` (provenance `cas`), later changes are `revaluation` entries (`equity:revaluation`: an "other change" in net worth, never income/spending/cash flow); others: snapshot update. Older statements never overwrite newer values; the same statement can't apply twice; hand-typed investment accounts can be linked or replaced to avoid double counting. API notes: `docs/INVESTMENTS_API.md` |
| `relationships.py` | Family & Relationships: people (relation, circle inner/close/wider, birthday and yearly occasions MM-DD or YYYY-MM-DD, keep-in-touch days by circle, private notes, optional care link), moments with several people and minutes; last together / "might like to hear from you" (never "overdue", no streaks); upcoming days with ages; gift budgets → yearly planned-money items (`person_id`); week's hours with people → Health `social_hours` (only with health consent); nudges (setting `people`, 09:00): day before / day of, one keep-in-touch a week; planner context lists inner circle and days coming up. API notes: `docs/PEOPLE_API.md` |
| `learning.py`, `learning_ai.py` | learning journeys for any goal (CA, CFA, boards, driving, a language). AI (`learning_ai`): intake → title, shape (exam/skill/fluency/project), 3–5 starting-point questions (level first); structure via web search with sources (stages → subjects → chapters, exam dates, requirements, fees; only what's left); recall questions per chapter (cached). Code (`learning`): checks (disagreeing sources / unsourced facts, dates, estimates → confirm; past or out-of-order dates, missing exam dates, requirements after the exam → errors that can't be waved away); hours = remaining by subject status (`STATUS_REMAINING`) + spaced revisions (`REVIEW_LADDER` 1d/1w/1m/3m/6m, shrinking) + practice and mocks + final revisions; fit against hours a week and study leave up to each exam (options: more hours, later attempt with date, one stage first); phases backwards from the exam; daily sessions (due revisions first, two subjects interleaved, then practice/revision), Easy/OK/Hard moves the next revision, pace. Accept → requirement tasks + fees in planned money. Study time → time statements (Learning) and Health `learning_hours` (consent); nudges (setting `learning`, 07:00). API notes: `docs/LEARNING_API.md` |
| `work.py`, `payslip_ai.py` | Work: roles (type salaried/self_employed/business_owner/freelancer/articleship/looking_for_work/homemaker; one schema, parts switch on by type: leave + appraisals for employed, payslips for salaried) whose hours and commute become fixed time blocks (`source_type` system, `source_id` role); work days that ran over/ended early → "Overtime" in time statements; week view "in its box" (≤2h over) with family time, sleep, stress; leave balances per leave year with expiry beyond carry-forward, planner tool `check_leave`; wins log and appraisal pack; payslips (Premium): AI copies, code checks sums and sorts deductions; on the money book PF → EPF (`income:salary_withheld`), tax/PT/insurance/other → `salary_deduction` entries, so income shows gross without double counting take-home; nudges (setting `work`, 18:30): appraisal −21 days, leave expiring −30 days, Friday overtime. API notes: `docs/WORK_API.md` |
| `whatsapp.py`, `whatsapp_ai.py` | WhatsApp task capture (Cloud API direct, no BSP): forward/type → task. Webhook `/api/whatsapp/webhook` (X-Hub-Signature-256, dedupe by message id, 10 s batching); router STOP → link code → START → help → button/list replies → done → content; Haiku parser only extracts (`TaskParse`), off-topic → fixed reply (R01); confirm card Add/Edit/Cancel or Today/Tomorrow/Pick date; done by quote-reply (context.id → `wa_outbound`), bare done, fuzzy, list; reminder template `task_due_reminder` (Done/Snooze) once per task at due time or 09:00; sender refuses opted-out numbers and free-form outside 24h, adds AI disclosure on the first text of each new window (R27); consent logged (app checkbox + code); phone numbers redacted before AI; raw text purged after 7 days; Health → app link; daily template limit `WA_MESSAGING_LIMIT`. Off until `WA_*` vars are set. API notes: `docs/WHATSAPP_API.md` |
| `metering.py`, `admin.py`, `admin_ui/` | admin page `/admin` (only `HYMN_ADMIN_EMAILS`, login < 12 h, every change in `admin_audit`): overview (active people, retention, funnel, features/areas, AI spend vs budget, errors, beta), people (+ plan / extra AI / sign out / pause / delete), AI (by day, feature, model, top spenders, on/off switches), invites, system, settings, log. Metering: middleware counts each `/api/...` call per person/day/feature (`usage_daily`, unnamed `usage_totals`, `users.last_active_at`), 5xx → `errors`; `claude_client.get_client()` is metered: refuses when a feature is off (`ai_off`) or the month's ₹ spend ≥ `ai_stop_inr`, then logs tokens/searches/cost (`ai_calls` per person, `ai_daily` unnamed). Privacy: counts and costs only, never content; Health never shown per person ("private"). Invites: `invite_only` (off until the app has the box), `beta_cap` 200, each person's own code (`invites_per_person` 5), `GET /api/invites/mine|check`, sign-up `invite_code`. API notes: `docs/ADMIN.md` |
| `billing.py`, `plans.py` | Premium: `plans.user_plan` = manual `users.plan` → `HYMN_PREMIUM_EMAILS` → `users.premium_until` (kept by `billing.refresh` from trial `trial_until` (14 days at sign-up, `trial_days`), beta pass `beta_until` (sign-ups before `beta_premium_until` → also `founding_member`), promo `promo_until`, subscriptions' `access_until` incl. `grace_days`) → default. Premium-only list and per-plan limits (planner chats/month 3, learning journeys 1, care 1/5, food photos 30/300, lab reads 3/20, WhatsApp tasks/month 20) are admin settings (`premium_only`, `limits`; `plans.require_within` → 403). Payments: Razorpay web subscriptions (`/api/billing/checkout`, cancel, signed webhook; keys `RAZORPAY_*`; plan ids in settings) and RevenueCat for stores (`/api/billing/webhooks/revenuecat`, `REVENUECAT_WEBHOOK_AUTH`); promo codes; admin Revenue tab. Prices ₹199 / ₹1,499 / founding ₹999 (editable). Tests set `HYMN_TRIAL_DAYS=0`. API notes: `docs/BILLING.md` |
| `ai_budget.py`, `account.py` | beta safety: daily AI caps per person (`ai_budget.daily("strong"|"light")` route dependency; strong 15/60 Premium, light 100/300; attempts counted) on plan chat, learning setup, old planner, goal merge, brain dump, payslips, statements; `GET /api/account/setup` (first-time checklist across areas), `GET /api/account/export` (all data, no secrets), `DELETE /api/account` (password + "DELETE"; also care profiles and their data, family membership; Pamphlet ID retired, never reissued). `server.py`: API docs off in production, 30 MB body cap, safe headers |

Design guide (owner-approved 21 Nov 2026: Outfit + Figtree, six sizes, paper/ink/saffron/sage, your day first, friendly words and numbers): `docs/DESIGN.md`, mock-ups in `docs/design/`; the app gets it from Emergent prompt **0. Design pass** (run before N). Plans and decisions: `docs/plans/finance-audit.md`. Audits (16 Nov 2026): `docs/audits/2026-11-16-stale-and-duplicate-paths.md` (removal review — nothing removed until the owner ticks items; `main`'s `frontend/` was synced from `emergent-frontend` on 19 Nov 2026 (prompts A–M); copy only `frontend/`, never that branch's `backend/`), `docs/audits/2026-11-16-beta-readiness.md` (security, backups, setup), tester plan `docs/BETA_TEST_PLAN.md`. Ready-to-paste Emergent prompts, A–S in build order: `docs/EMERGENT_PROMPTS.md` (also a copy-button page for the owner). API notes for Emergent:
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
- Health is shown to beta testers marked **draft** (owner, 16 Nov 2026): the app must show a clear
  "draft — not yet reviewed by a doctor" note wherever `rules_reviewed` / `values_reviewed` is false.
- MongoDB Atlas daily backup is enabled (owner, 16 Nov 2026); a test restore is still to be done.
- The MongoDB password and Anthropic key appeared in chat; the owner checked
  where they're exposed (only this chat, behind their Claude login; repo
  history clean; phone screenshot deleted) and chose **not** to rotate them
  (14 Nov 2026). Don't raise it again unless the Claude account may be
  compromised or is shared.

## Roadmap

Done: auth hardening, CI, Railway (Singapore), brain dump + review + nuggets, nudges, planning on the
Anthropic SDK, ledger + conversion + sync, statements + matching, planned money + forecast, Pamphlet ID,
the three money statements, life objects (loans, fuel), family net worth, time statements, life plans +
plan chat + templates, Health (stages 1–2, caregiver, nudges), Family & Relationships, Learning journeys,
Work, investments (CAS), beta readiness (AI caps, export/delete, setup checklist), step 1 of the
stale-path cleanup, notification limit + morning brief, WhatsApp task capture (code; waits on Meta and the owner's G0–G3), admin page + usage/AI-cost metering + budget stop + beta invites, Premium (trial, beta pass, limits, Razorpay + RevenueCat server side; waits on the owner's accounts).

Next:
1. Emergent screens (see below), then the published tester beta (`docs/BETA_TEST_PLAN.md`).
2. Native build with Firebase (push notifications, Health Connect / Apple Health sync).
3. Cleanup steps 2–3 of `docs/audits/2026-11-16-stale-and-duplicate-paths.md` as screens ship.
4. Before public launch: email/OTP verification for sign-up and reset, health data encryption, privacy
   policy and DPDP review, a penetration test, doctor and nutritionist sign-offs.

**Emergent prompts:** A–M are built (19 Nov 2026; credits ran out). What's left is **0 (design pass) first**, then N–S in `docs/EMERGENT_PROMPTS.md`
(the old N–U merged to save credits; statement polish moved to Later), for when credits renew around 17–18 Dec. The owner pastes them in order and saves to `emergent-frontend`
after each; check each save against the backend (field names, routes) before the next, and add any
missing response fields on the backend rather than spending Emergent credits. After the last: copy
`frontend/` from `emergent-frontend` into `main` (never its `backend/`) and switch on
`HYMN_REQUIRE_CHECKIN_DURATION=1`.

Later (owner's strategy, decided but not to build yet): intent marketplace —
classify fulfillable brain-dump items (category, locality, time window),
aggregate demand counts with minimum-count suppression, per-item opt-in
"Let Hymn assist" consent behind a feature flag, matching with the owner's
separate vendor app. Needs legal review (DPDP; SEBI/RIA for investment
matching) before anything leaves Hymn.
