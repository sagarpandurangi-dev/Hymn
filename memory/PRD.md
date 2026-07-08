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
