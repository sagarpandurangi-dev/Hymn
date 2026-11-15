# Family & Relationships — API notes for the app

The people who matter, the days that matter, and time together. Gentle by design: no streaks, never "overdue"; at most "might like to hear from you".

## People
- `POST /api/people` `{name, relation, circle: inner|close|wider, birthday: "MM-DD"|"YYYY-MM-DD", birthday_gift, occasions: [{label, date, gift_budget}], keep_in_touch_days, notes, care_id}` → the person.
  - `relation`: mother, father, spouse, partner, child, sibling, grandparent, grandchild, parent_in_law, relative, friend, mentor, colleague, neighbour, other.
  - `keep_in_touch_days` defaults from the circle (inner 7, close 30, wider none). A year in a date lets Hymn say "turns 70" / "46 years".
  - A gift budget adds a yearly "Birthday: Amma" item to planned money in that month (category Gifts), kept in step with edits.
  - `care_id`: link to a care profile (Health → people I look after).
- `GET /api/people` → everyone, inner circle first: each with `last_together`, `days_since`, `might_like_to_hear_from_you`, `next_day {label, on, in_days, years?, gift_budget?}`.
- `GET /api/people/{id}` → the person + their last 50 `moments`.
- `PATCH /api/people/{id}` (any fields; `keep_in_touch_days: 0` = don't remind). `DELETE /api/people/{id}` (also their moments and gift items).
- `GET /api/people/upcoming?days=30` → `[{person_id, name, label, on, in_days, years?, gift_budget?}]`.
- `GET /api/people/summary` → the home card: `{month, moments_this_month, people_reached, inner_circle_hours, might_like_to_hear_from_you[≤3], coming_up[≤5], people}`.

## Moments
- `POST /api/people/moments` `{person_ids[], date, kind: call|video_call|visit|meal|outing|message|help|celebration|other, minutes?, note}`. One moment can include several people. Quick buttons: "Called", "Met", "Messaged", with 15m / 30m / 1h / 2h+.
- `DELETE /api/people/moments/{id}`.
- With the health consent, each week's hours with people show in Health as "Time with people you care about".

## Nudges
Setting `people` (`{enabled, time}`, default 09:00) in `/api/nudges/settings`:
- "Tomorrow: Amma's birthday (turns 70)" (with the gift budget if planned) and "Today: …".
- At most once a week, the inner-circle person it's been longest with: "Papa might like to hear from you — It's been 12 days."
- Push `data`: `{screen: "people", person_id}`. Never in quiet hours.
