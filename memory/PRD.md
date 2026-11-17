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
