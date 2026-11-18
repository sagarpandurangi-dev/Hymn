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
