# Hymn - Personal Operating System

## Product Overview
Hymn is an Android/mobile app foundation that helps a person remember what they said mattered, record what actually happened, and follow through until things are completed, changed or abandoned.

## Scope (Foundation)
- Real JWT-based email/password authentication (no mocks). Persistent sessions until explicit logout.
- Forgot password via security question (no email delivery).
- 5-tab bottom navigation: Today, Timeline, [+ centered floating], Finance, Me.
- The + button opens Add Event from every tab.
- Today dashboard: 4 navigable cards (Required Check-ins, Upcoming Tasks, Today's Events, Today's Spending).
- Full Event module (Timeline, Add Event, Event Detail, Edit Event) with Type/Title/Date/Time/Notes.
- Per-user data isolation enforced by user_id filter on every event query.

## Design
- Calm minimal Editorial LIGHT — Paper White (#FBFBF9) with Sage Green (#808B76) brand.
- Serif display type + system sans body. No shadows, generous whitespace.

## Backend
- FastAPI + Motor MongoDB. All routes under `/api`.
- Auth: /api/auth/signup, /login, /me, /logout, /security-question, /forgot-password.
- Events: GET/POST /api/events, GET/PUT /api/events/{id}.
- bcrypt for passwords + security answers; JWT (HS256) 30-day tokens; token stored via expo-secure-store.

## Verified
- 22/22 backend pytest suite passing (auth + events + isolation).
- 17/17 frontend flow tests passing on mobile viewport.

## Deferred
- Event delete, Finance/Me detail modules, Check-ins/Tasks/Spending detail modules, email-based password reset, refresh tokens.

## Regression pass (Jun 2026) — Planned money / Finance tab / Forecast / Overnight blocks / Pamphlet ID
- Finance tab 12-month forecast now reads dashboard.forecast (same server calc as full forecast screen); twin call removed.
- Finance tab refreshes on focus; negative free cash shows red; forecast basis note shows.
- Full forecast: maybe note no longer clipped. Planned screen: "Going out" keeps decimals, no spinner flash on return.
- Planned form: errors clear when a field is edited.
- Portfolio: overnight blocks show a "continues until HH:MM (from X night)" line on the next day.
- Deferred (backend): planned items marked "Set money aside" not counted in Set aside / Available to spend.

## Check-in duration + Finance screen endpoint (Jun 2026)
- Required duration row (15m/30m/45m/60m/2h/3h → duration_minutes) on Life/Goal/Project/Edit check-in forms; blocked with "How long did it take?"; "· 45m" on Timeline, Today, Goal/Project lists, check-in detail. Component: src/components/DurationPicker.tsx.
- Finance tab loads from GET /api/screens/finance (dashboard + planned_upcoming); reconciliation suggestions still separate.

## Life tab + shared helpers (Jun 2026)
- Tabs: Today · Timeline · Finance · Life. Life (app/(tabs)/life.tsx) cards: Health, Family & Relationships, Learning (→ old knowledge tab, hidden), Work, Plans (→ planning-space). AsyncStorage "hymn.focusAreas" puts saved areas first. Placeholders at app/life/[area].tsx.
- api.ts request(): 413 "That file is too large.", 429/503 server detail as toast (src/lib/toast.ts + ToastHost), 401 on auth calls → sign out.
- src/utils/upload.ts: pickImage() (≤1024px, JPEG 0.7) / pickPdf() → {base64, mediaType}.
- src/components/DraftNote.tsx; formatINR in src/lib/finance/format.ts.

## Welcome wizard (Jun 2026)
- /welcome (app/welcome/index.tsx + src/components/welcome/*): 10 screens — promise, focus areas (hymn.focusAreas), time zone (PUT /nudges/settings), work (POST /work/roles), sleep (7 overnight time-commitments), brain dump, people (POST /people), optional bank account (AccountEditor), notifications, payoff (reports/time free_hours + inbox/review top 3).
- Gate in app/_layout.tsx sends users without portfolio_setup_completed_at to /welcome (replaced /portfolio/setup redirect). Progress in AsyncStorage hymn.welcome.step / .saved / .user (per user). Steps skip saves already on server.
- Finish: PUT /portfolio/setup-status {completed:true, reporting_currency from bank account else INR if missing}.
- Today: SetupProgressCard from GET /account/setup; "Not now" snoozes 7 days (hymn.setupCard.snoozedUntil).

## Notifications, export, account delete (Jun 2026)
- /nudges titled "Notifications": reads GET /nudges/settings `settings{}`; sections Evening review, Your week in Hymn, Reminders, Health, Birthdays and keeping in touch, Today's study, Work, Quiet hours. PUT sends only changed fields.
- openNudgeScreen(router, data) in src/lib/push.ts routes data.screen (+ids, data.for → /life/health?for=) for feed and push taps; unknown → Today.
- Me: AccountDataSection (Download my data → hymn-data-YYYY-MM-DD.json via share sheet / web download; Delete my account → /account/delete). Delete allowed before setup is complete (gate exception).

## Planned money screen v2 (Jun 2026)
- /finance/planned: GET /planned-money?include_done=true; rows show ₹ (formatINR), "Once on 12 Dec"/"Monthly from Jan 2027"/"Yearly in March", Maybe/Set aside/Done/Cancelled tags, "₹X left", lock + "Edit on the old screen" for editable:false. Groups: Every month/year, Coming up, Maybe, Done or cancelled.
- Swipe-left actions (SwipeablePlannedRow): Done / Cancel / Delete; form also has Mark done / Cancel item / Delete.
- "Next 12 months" section from /planned-money/months. Finance tab has a "Planned money" row under the forecast.

## Statements (reports) (Jun 2026)
- Finance tab "Statements" section → /finance/reports/net-worth (side-by-side ≥720px, stacked on phones), /finance/reports/income-expenditure (month picker, 3 columns, expand groups → categories → /finance/reports/entries), /finance/reports/cash-flow (sections, net change, closing, ✓ Adds up).
- Helpers in src/components/finance/ReportBits.tsx read group fields defensively (label/name, amount/total, lines/categories). Actual group shapes not yet seen with real data.
- Report lines: multi-column lines put the label on its own row (phone-readable); negatives shown in brackets; Documents row renamed "Bank statements".

## Recent activity (ledger rows) + CAS import (Jun 2026)
- Finance Recent activity → RecentActivityList: transfers "↔" grey no sign; detail "ledger" opens read-only sheet (kind labels), "event" opens event screen.
- /finance/investments/cas (Premium; 403 → "Premium feature"): how-to text, pickPdf + password → POST /investments/cas/preview, preview card (CasPreviewCard: source, period, investor, total, lines w/ action tags, check warnings, expandable stock/bond/nps items), CasAccountLinker for your_other_investment_accounts → links/replaces, apply → "Added N, updated N" + missing, Past statements (GET /investments/cas). Field names read defensively (shape unverified — QA user is not Premium).

## My week (Jun 2026)
- /my-week (card on Today): GET /reports/time?week_start=, week arrows; commitments bar (fixed/flexible & set aside/free of 168h) + time invested this year; time spent table (planned/actual/gap, red rules per area, expandable lines), soul when show_soul, waking-hours %; time flow; untimed check-ins notice.

## Things I own & owe (life objects, Premium) — frontend
- Finance tab > Statements > "Things I own & owe" → app/finance/things/{index,new,[id],schedule,fuel}.tsx; helpers in src/components/finance/lifeObjects.tsx; api.ts listLifeObjects/createLifeObject/getLifeObject/updateLifeObject/getLifeObjectSchedule/getLifeObjectFuel.
- 403 → "Premium feature" card. POST fields: type, kind, name, started_on, price, extra_costs, expected_life_months, resale_value, account_id, loan_amount, interest_rate, tenure_months, first_emi_date, method, emi, currency.
- Project check-in on a car/bike project: data.{odometer, price_per_litre, litres, full_tank}.
- Set aside detail on Finance tab lists reserved[].planned_set_aside under commitments.

## Family net worth — frontend
- Finance tab > Statements > "Family net worth" → app/finance/family/{index,add-item,net-worth}.tsx; FamilyMemberSheet; src/lib/family.ts.
- No server list of entries: entries added on this phone are kept in AsyncStorage (hymn.family.items.<familyId>) for deletion. My member id remembered on accept (hymn.family.me.<familyId>), else owner→"self" row, else name match.
