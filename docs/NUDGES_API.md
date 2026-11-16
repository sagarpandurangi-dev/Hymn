# Nudges API

All routes need `Authorization: Bearer <token>` and live under `/api/nudges`.
Errors return `{ "detail": "<message>" }`; show `detail` to the user.

The backend decides when to nudge. The app only registers the phone, shows
settings and the feed, and reports opens.

## Phone registration

`POST /nudges/devices` with `{ "token": "ExponentPushToken[…]", "platform": "android" | "ios" }`

- Get the token with `expo-notifications` (`getExpoPushTokenAsync`) after the
  user grants permission; send it after every login and app start.
- On logout: `DELETE /nudges/devices?token=<token>`.
- Push needs an installed build (Android APK / iOS build); Expo Go and the web
  preview can't receive remote pushes. Without a phone, nudges still appear
  in the feed below.

## Notification tap

Each push carries `data`:

```json
{ "screen": "inbox/review" | "inbox/patterns" | "plans" | "health" | "health/checkups" | "health/progress"
            | "health/daily" | "habits" | "people",
  "item_id": "uuid (reminders only)", "plan_id": "…", "habit_id": "…", "check": "dental",
  "for": "care_… (health nudges about someone you look after; null = yourself)" }
```

Open that screen. Nudges in the feed have an `id`; when one is opened (from
the feed, or from a push whose matching feed entry you find by time), call
`POST /nudges/{id}/opened`. Hymn learns from opens and reviews.

## Feed

`GET /nudges?limit=20` → newest first:

```json
[{
  "id": "uuid",
  "kind": "daily_review | reminder | weekly_patterns | plan_drift | health_report | health_checkup | health_log | habit_urge | people_day | people_touch",
  "title": "Time for your 2-minute review",
  "body": "3 things waiting in your inbox.",
  "data": { "screen": "inbox/review" },
  "status": "pending | sent | no_device | failed",
  "opened_at": null,
  "created_at": "ISO 8601"
}]
```

## Settings

`GET /nudges/settings`

```json
{
  "settings": {
    "daily_review":    { "enabled": true, "time": "20:30", "adaptive": true },
    "weekly_patterns": { "enabled": true, "weekday": 6, "time": "18:00" },
    "reminders":       { "enabled": true },
    "health":          { "enabled": true, "time": "09:30" },
    "people":          { "enabled": true, "time": "09:00" },
    "quiet_hours":     { "start": "22:00", "end": "07:00" }
  },
  "timezone": "Asia/Kolkata",
  "daily_review_plan": {
    "time": "21:30",
    "learned": true,
    "explanation": "You usually review around 21:40, so Hymn nudges you at 21:30."
  },
  "devices": 1
}
```

- `weekday`: 0 = Monday … 6 = Sunday. Times are `HH:MM`, 24-hour, local.
- `adaptive`: when on, Hymn moves the daily nudge to just before the time the
  user usually reviews (after 5 reviews, within 3 hours of their time).
  Show `daily_review_plan.explanation` under the time setting.

- `health`: at most one health nudge a day per person (you, and each person you look after), at that time:
  the 90-day report is ready → a check-up overdue or due within 30 days (at most one a week) → (you only)
  a gentle "30 seconds today?" after 3 days without logging (at most weekly). Habit check-ins come 15
  minutes before the time urges usually hit (3+ urges in 3 weeks), with the person's own reason. Never
  in quiet hours.

- `people`: birthdays and other days the day before and on the day; at most once a week, one inner-circle
  person it's been a while with. See `docs/PEOPLE_API.md`.

`PUT /nudges/settings` takes any subset, e.g.
`{ "daily_review": { "time": "07:45" }, "timezone": "Asia/Kolkata" }`, and
returns the same shape as `GET`.

## Weekly patterns screen

The weekly nudge opens `inbox/patterns`. Data comes from the inbox API:
`GET /inbox/patterns` (latest; `404` if none yet) — see `INBOX_API.md`.
