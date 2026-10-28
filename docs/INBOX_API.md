# Brain-dump inbox API

All routes need `Authorization: Bearer <token>` and live under `/api/inbox`.
Errors return `{ "detail": "<message>" }`; show `detail` to the user.

## Item

```json
{
  "id": "uuid",
  "dump_id": "uuid",
  "text": "Renew passport",
  "category": "task | reminder | idea | plan | unsorted",
  "status": "open | nugget | done | discarded | migrated",
  "remind_at": "2026-11-12T03:30:00+00:00 or null (UTC)",
  "review_count": 0,
  "next_step": null,
  "migrated_to": null,
  "created_at": "ISO 8601"
}
```

`unsorted` means sorting failed; the item holds the raw text and can be
reviewed like any other.

## Capture

`POST /inbox/dumps`

```json
{ "text": "raw thoughts…", "client_dump_id": "random 8-128 chars", "timezone": "Asia/Kolkata" }
```

- Generate `client_dump_id` once per submit and reuse it on retry; the dump
  is stored once.
- Send the device's IANA timezone; it is remembered on the account.
- `201` → `{ "dump": {...}, "items": [Item], "ack": "Nice. Saved: 2 tasks, 1 idea." }`.
  Show `ack` as the confirmation.
- `dump.status == "unsorted"` → offer "Sort again":
  `POST /inbox/dumps/{dump_id}/sort` (same response shape; `409` if there is
  nothing to sort).

## Items

- `GET /inbox/items?status=open&category=task` → `[Item]`, newest first.
  `status` defaults to `open`.
- `PATCH /inbox/items/{id}` with any of `text`, `category`,
  `remind_at` (timezone-aware ISO 8601, or `""` to clear) → `Item`.

## Daily review

`GET /inbox/review?limit=8`

```json
{
  "prompt": "Which of these are complete? Which should be discarded? Which are nuggets of gold that need action?",
  "items": [Item],
  "open_total": 23,
  "nuggets": [Item],
  "migrate_prompt": "Where should this live? (Task, Calendar, Wishlist)"
}
```

`POST /inbox/review`

```json
{ "decisions": [ { "item_id": "uuid", "decision": "done | discard | nugget | keep" } ] }
```

Send one decision for every item shown; untouched items are `keep`.
Returns `{ "counts": {...}, "nuggets": [Item], "migrate_prompt": "..." }`.

## Migration (nuggets)

`POST /inbox/items/{id}/migrate`

```json
{
  "destination": "task | calendar | wishlist",
  "next_step": "Book a gym trial for Saturday",
  "due_date": "2026-11-01",
  "time": "07:30",
  "project_id": null,
  "expected_outcome_id": null
}
```

- `next_step` is required: ask "What's the very next step?".
- `calendar` requires `due_date`; `time` is optional.
- `task` may attach to a project (`project_id`) or a goal outcome
  (`expected_outcome_id`), not both.
- Returns `{ "item": Item, "migrated_to": { "type": "...", "id": "..." } }`.
  Task and calendar destinations are normal Hymn tasks (`GET /api/tasks/{id}`).

`GET /inbox/wishlist` → `[{ "id", "title", "next_step", "created_at" }]`.

## Weekly patterns

- `POST /inbox/patterns` analyses the last 7 days and returns the result.
- `GET /inbox/patterns` returns the latest (`404` if none yet).

```json
{
  "stats": {
    "captured": 14,
    "captured_by_category": { "task": 8, "reminder": 2, "idea": 3, "plan": 1 },
    "completed": 6, "discarded": 2, "migrated": 3, "reviews": 5,
    "avoided": [ { "id": "uuid", "text": "File taxes", "category": "task", "review_count": 4 } ]
  },
  "insight": {
    "themes": ["…"], "avoidance": ["…"], "suggestions": ["…"], "summary": "…"
  },
  "error": null,
  "created_at": "ISO 8601"
}
```

`insight` is `null` when the assistant was unavailable; still show `stats`.
