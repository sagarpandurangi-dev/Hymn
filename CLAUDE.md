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
  region currently US-West — moving to Singapore is a parked speed fix).
  MongoDB Atlas (Mumbai). Railway auto-deploys `main`.
- **Railway access from a session:** the "Hymn" cloud environment holds a
  Railway project token (proxy-injected header `Project-Access-Token` for
  `backboard.railway.com`) and allows `hymn-production-4828.up.railway.app`.
  Use the GraphQL API to read deployments/logs; list variable *names* only.
- **Env vars (Railway):** `MONGO_URL`, `DB_NAME`, `JWT_SECRET`,
  `HYMN_RUNTIME_MODE=production`, `ANTHROPIC_API_KEY`, `HYMN_PREMIUM_EMAILS`.
  Optional: `HYMN_ASSISTANT_MODEL`, `HYMN_PLANNING_MODEL`,
  `HYMN_STATEMENT_MODEL`, `HYMN_DEFAULT_PLAN`, `HYMN_NUDGES`, `CORS_ORIGINS`.
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
| `hymn_ids.py` | Hymn ID: every ID 7 characters. Real ID = 1 letter (no I/O) + 6 digits, free random standard one per user (assigned at signup / first seen), permanent, meant to be shared with Pamphlet. Alias = 7 letters+digits (2+ letters, never real-ID shaped, e.g. PRIYA88), costs more. Special numbers (repeats, sacred, sequences, palindromes, birthdays DDMMYY) and aliases are graded and reserved until the shop (payments) opens. Look-alikes O=0, I=1 are the same ID. Rate-limited check/find |
| `ledger.py` | double-entry ledger: transactions with inline postings summing to zero; accrual and cash views; starter categories |
| `ledger_conversion.py` | one-time, self-verifying conversion of old finance data into the ledger (preview → fingerprinted apply) |
| `ledger_sync.py` | after conversion, keeps the ledger in step with old finance records (new/changed/rejected events, retyped balances) using the conversion's own rules; only touches derived entries; links to statement entries instead of double counting; runs before ledger reads and statement suggestions |
| `statements.py`, `statements_ai.py` | Premium: PDF upload (password used in memory only), Claude reads lines (debit = money out, credit = money in), arithmetic verification, plain-language reasons |
| `statement_matching.py` | Xero-style suggestions per line (already recorded / own-account match / learned rules / patterns / built-in merchant list / similar names the user filed / spending habits by amount / one AI guess per unknown merchant per user), confirm into ledger, learning, opening balance, reconciliation |
| `merchant_directory.py` | free built-in list of ~900 well-known (mostly Indian) merchant keywords → spending category; mixed merchants and people's names deliberately left out |

Plans and decisions: `docs/plans/finance-audit.md`. API notes for Emergent:
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
  Before beta: rotate the MongoDB password and Anthropic key (both appeared
  in chat), move Railway to Singapore, push notifications need a native build
  with Firebase.

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
4. Speed: Railway → Singapore; reduce round trips per screen.
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
