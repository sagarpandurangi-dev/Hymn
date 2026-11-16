# Audit: stale paths and duplicate paths (16 Nov 2026)

**Step 1 done (16 Nov 2026):** C2, C3, C7, C8, C10, B11, B12, C11 removed or updated; C9 (old branches) is for the owner to delete on GitHub (this session can't), listed in `old-branches-2026-11-16.txt`. Steps 2–3 still for review.

**Original note:** for review only. Each item has a recommendation and what removing it would take. Tick the ones you agree with and they become a cleanup job.

How this was checked: every server route (287) was listed from the running app and compared with every call the app makes; dead code was scanned with a tool and then checked by hand; branches, tests, files and dependencies were listed from the repository.

Legend — **Remove**: safe now. **Remove after**: safe once the named screen ships. **Merge**: two things do the same job; keep one. **Keep**: looks stale but isn't.

---

## A. The biggest finding: `main` holds an old copy of the app

- The app Emergent actually builds lives on the **`emergent-frontend`** branch. It has 25 files `main` doesn't (statements, money book, brain dump, review, nuggets, patterns, nudges, push) — about 2,400 lines.
- `main`'s `frontend/` folder is therefore **stale**: anyone reading it sees an app without those screens.
- `emergent-frontend`'s `backend/` folder is the opposite: very old (it would delete ~19,600 lines). **Never merge that branch whole.**
- **Recommendation (Merge):** after each Emergent save, copy only `frontend/` from `emergent-frontend` into `main` (I can do this as a routine PR), so `main` is the one true copy of both halves.

## B. Two paths that do the same thing

| # | Old path | New path | What overlaps | Recommendation |
|---|---|---|---|---|
| B1 | `planning_engine.py` (2,839 lines), `planning_space.py`, `/api/planning/...` (8 routes) | `plan_assistant.py` + `life_plans.py`, `/api/plan-chat`, `/api/life-plans` | Two AI planners. The old one makes goals → outcomes → tasks; the new one checks real time and money. | **Remove after** Emergent prompt 7 (the new planner screen). Keep `goal_merge.py` only if goals stay (see B6). |
| B2 | Monthly commitments (`/api/portfolio/monthly-money-commitments`), finance commitments (`/api/finance/commitments…`, 13 routes), expected income (5 routes) | `planned_money.py` (`/api/planned-money`) | Three old lists of "money expected in or out" vs one new list. The new list already shows the old ones read-only. | **Remove after** the planned-money screen ships: move old rows into planned money once, then delete the old routes. |
| B3 | Scenarios (`/api/finance/scenarios…`, 7 routes, 2 app screens) | — | You decided to remove scenarios; the backend and screens are still there. | **Remove** screens in Emergent prompt 1; then the 7 routes and the `scenarios` collection. |
| B4 | Finance events (`/api/finance/events…`, reconciliation, dedupe: ~14 routes) | The ledger / money book (`ledger.py`, statements) | Two records of what money did. `ledger_sync.py` keeps them in step for converted users. | **Keep for now, remove later.** Needs every user converted and check-in spending written straight to the ledger. The largest cleanup; do after beta. |
| B5 | Finance position (`/api/finance/position`, `/api/portfolio/money-position`), monthly (`/api/finance/monthly`) | Statement of Net Worth, Income & Expenditure (`reports.py`) | Old and new "where do I stand" screens. | **Remove after** the three-statements screens ship (prompt 3). |
| B6 | Goals in the "Knowledge" area + "Study" check-ins (Knowledge tab) | Learning journeys (`learning.py`) | Two ways to learn something. | **Remove after** the Learning screens ship: rename the tab, offer to turn each old learning goal into a journey. |
| B7 | Default areas "Knowledge, Health, Money, Soul" (`server.py`) | Hymn's five areas: Money, Health, Family & Relationships, Learning, Work | The app's areas don't match the product. Time statements guess the area from a goal's area *name*. | **Merge:** make the defaults the five areas; map Knowledge → Learning; store the area on the goal instead of guessing. |
| B8 | Life objects of type "habit" (`life_objects.py`) | Habits to change (`habits.py`) | Two things called habits: the lifetime cost of a habit vs quitting one. | **Merge:** keep `habits.py`; show cost from it (it already has cost per unit); drop the "habit" life-object type. |
| B9 | Family notional members (kids, parents in `family.py`), care profiles (`care.py`), people (`relationships.py`) | — | Three records for the same person ("Amma"). People already link to a care profile. | **Merge:** make People the one list; a person can have "money in the family total" and "health I look after" switched on. |
| B10 | "Weight" check-in type; "Revenue" check-in type (`server.py`) | Health measurements; income in the money book | Same number in two places. | **Remove after** Health screens ship (weight) — or write through to Health. |
| B11 | Time set aside: `resource_allocations` routes (`/api/portfolio/resource-allocations`, 4 routes, unused by the app) | Life-plan bookings write the same collection | The routes are unused; the collection is used. | **Remove** the 4 routes; keep the collection. |
| B12 | `backend/tests/` (19 files, old live-server tests) and root `tests/` (4 scripts) — 8,400 lines | `backend/unit_tests/` (run on every change) | Old tests need a running server and a real database; CI never runs them; several test features that no longer exist (`/api/knowledge/journeys`, Google sign-in). | **Remove** both folders and `safety_tests/test_root_planning_scripts.py` (it only guards those scripts). Before deleting, I'd port any check not already covered. |
| B13 | Legacy sign-in sessions (`user_sessions` branch in `server.py`) | Email + password tokens | Left from the removed Google sign-in; only honours old sessions until they expire. | **Remove** once the collection is empty (I can check on the live database when you say). |

## C. Stale code and files (no replacement needed)

| # | What | Why it's stale | Recommendation |
|---|---|---|---|
| C1 | Server routes the app never calls, old modules: `GET /api/planning/hierarchy/plans/{id}`, `GET /api/planning/hierarchy/targets/{type}/{id}`, `GET /api/portfolio/time-capacity/day`, `GET /api/statements/{id}/file`, `GET /api/inbox/items`, `PATCH /api/inbox/items/{id}`, `GET /api/inbox/wishlist`, statement rules (3 routes), `GET /api/hymn-id/check|find` | No screen uses them on `emergent-frontend`. | **Keep** the inbox, rules, file and Pamphlet ID ones (screens are planned). **Remove** the two hierarchy routes and time-capacity/day with B1. |
| C2 | Dead functions: `finance_manager._maybe_create_task`, `planning_space._task_is_open` | Never called. | **Remove.** |
| C3 | `backend/migrations/reform_decomposition.py` | One-time migration from the old learning engine; already run. | **Remove** (history keeps it). |
| C4 | `component_id`, `journey_type` fields on tasks, check-ins and goals (`server.py`, ~30 mentions) | Belong to the removed learning engine. | **Remove after** B6. |
| C5 | `financial_commitments` database collection | Kept "for migration verification" only; nothing writes to it. | **Remove** after a last look at the live data. |
| C6 | `.emergent/cron/` (5 files), `.emergent/markers/` | Emergent's own machinery. | **Keep** — Emergent may need them. |
| C7 | `memory/PRD.md`, `design_guidelines.json`, `README.md` (one line) | Emergent's early notes; the PRD describes July's app. | **Keep** the design guidelines (Emergent reads them); **replace** the PRD and README with a short current description. |
| C8 | `docs/plans/finance-audit.md`; the "Next" list in `CLAUDE.md` | Statuses are out of date (Family, Work, Health, Learning are built). | **Update** (not remove). |
| C9 | 10 old branches on GitHub: `conflict_300826_1348`, `foundation-release`, `fix/…` (5), `feature/…` (3) | From July–October; 150+ changes behind `main`; the two "dream" branches are the shelved drafts (PRs #5, #9) already rebuilt. | **Remove** all ten after you confirm (deleting a branch is permanent). |
| C10 | Unused libraries in `requirements.txt`: `boto3`, `requests-oauthlib`, `pandas`, `numpy`, `jq`, `typer`, `pyjwt`, plus developer tools shipped to production (`pytest`, `black`, `isort`, `flake8`, `mypy`), and `emergentintegrations` (already skipped in builds) | Nothing imports them. They slow every deploy and widen the attack surface. | **Remove** (move developer tools to `requirements-dev.txt`). `requests` stays: push notifications use it. Keep `cryptography`: opening password-protected PDFs needs it. |
| C11 | `backend/test_environment.py`, `backend/conftest.py` | Guards for the old live tests. | **Remove with** B12. |
| C12 | `calibration.py`, overrides and decision-assessment routes (`/api/finance/calibration`, `/overrides…`, `/decision-assessment`, `/rebalance-candidates`) | An early "should I spend this?" feature; still called by an app screen, but the new planner covers the question. | **Decide:** keep as is, or fold into the planner. |

## D. Not stale (looks unused, but is waiting for screens)

142 routes in 20 newer modules have no screen yet: Health (and food, habits, labs, check-ups, sync, reports, care), Family, People, Learning, Work, life objects, life plans and the plan chat, templates, the three money statements, time statements, planned money, investments upload, the ledger's own routes and the Finance one-call screen. They are covered by tests and listed under "Emergent prompts owed" in `CLAUDE.md`. **Keep.**

## E. Suggested order

1. **Now (safe, no screens needed):** C2, C3, C10, B11, B12 + C11, C9 (after your OK), C8, C7.
2. **With the 18 Nov Emergent prompts:** A (sync `frontend/` into `main`), B3, then B1, B2, B5 as each screen ships.
3. **After beta:** B6 + C4, B7, B8, B9, B10, B13, C5, and finally B4 (the old money records).

Rough size: step 1 removes about 9,000 lines and 12 libraries; steps 2–3 about 12,000 more.
