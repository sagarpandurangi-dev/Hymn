# WhatsApp task capture

Forward or type a message to Hymn's WhatsApp number and it becomes a task: Hymn asks at most one question
(usually the due date), reminds you at the due time, and you mark it done from WhatsApp. Code:
`backend/whatsapp.py` (webhook, routing, sending, reminders, app routes) and `backend/whatsapp_ai.py` (the
parser). Tasks are ordinary Hymn tasks with `source: "whatsapp"`, `source_ref` (the first message id),
`area`, `due_time` and `wa_reminded_at`.

Nothing is sent or accepted until these Railway variables are set: `WA_PHONE_NUMBER_ID`, `WA_ACCESS_TOKEN`,
`WA_APP_SECRET`, `WA_VERIFY_TOKEN`, and for linking `WA_DISPLAY_NUMBER` (Hymn's number, e.g. `+91 80000 00000`).
Optional: `WA_GRAPH_VERSION` (default `v23.0`), `WA_TEMPLATE_LANG` (`en`), `WA_MESSAGING_LIMIT` (250 numbers a
day for templates; 2000 once verified), `HYMN_WHATSAPP_MODEL` (`claude-haiku-5-5`), `HYMN_SUPPORT_EMAIL`,
`HYMN_SUPPORT_URL` (the "help" reply), `HYMN_APP_LINK` (the "open the app" link).

Meta webhook URL: `https://hymn-production-4828.up.railway.app/api/whatsapp/webhook` (verify token =
`WA_VERIFY_TOKEN`; subscribe to `messages`).

## The rules (launch blockers, each covered by a test)

| Rule | How |
|---|---|
| R01 not a general assistant | The AI only extracts a task (`TaskParse`); anything else gets the fixed reply "I only add, update and complete Hymn tasks. Open the app for more." |
| R27 AI disclosure | The first text in every new 24-hour conversation window ends with "Hymn uses AI to read what you forward and create tasks." (A ✅ reaction can't carry it, so a short text is sent instead when it's due.) |
| R06 opt-in | The app's checkbox is logged in `consent_log` (text version, method, time) before a code is issued; the code message from WhatsApp logs again with the number. |
| R07 opt-out | STOP / unsubscribe, the app's pause switch, or disconnecting → `wa_opt_out`; checked before every send. START or linking again opts back in. |
| R08 24h window | Free-form messages only within 24h of the person's last message; reminders are templates. |
| R09/R10 help | "help" / "human" → `HYMN_SUPPORT_EMAIL` / `HYMN_SUPPORT_URL`. |
| R17 webhook security | `X-Hub-Signature-256` HMAC-SHA256 of the raw body with the app secret, constant-time compare; bad → 401, nothing stored. Messages are stored once per id, answered 200 at once, handled after a 10-second pause. |
| R14/R15 limits | Reminder templates go to at most `WA_MESSAGING_LIMIT` numbers a day; a warning is logged at 80%. |
| R22/R24/R28 data | Phone numbers (7+ digits) become `[number]` before the AI sees the text; raw text is deleted after 7 days (the message id stays for dedupe); account deletion removes everything. |

## Conversation

- **Link:** the app shows a checkbox with `consent_text`; `POST /api/whatsapp/link {"consent": true}` →
  `{code: "LINK-ABC234", url: "https://wa.me/<number>?text=LINK-ABC234", expires_in_minutes: 30}`. Open the
  url; the person sends the code; Hymn replies "Connected. … Reply STOP anytime." plus the AI line.
- **Capture:** messages within 10 seconds of each other are read together → one card.
  - With a due date: "Add this task? *Pay rent* Due: tomorrow" [Add] [Edit] [Cancel].
  - Without: [Today] [Tomorrow] [Pick date] (a list of the next 10 days). Choosing a date adds it.
  - Added → ✅ on their message. Edit → "Send the task again the way you want it." Typing "cancel" cancels the
    latest card.
  - Not a task → the fixed reply. Unclear (confidence < 0.6) → "Could you send it in one line…".
  - Health → "Health things are kept in the app", nothing kept (raw text removed at once).
  - Chain messages (`frequently_forwarded`) → [Add as task] [Ignore] before anything is read.
  - Photos, voice notes → "I can only read text for now."
  - Unlinked numbers → a connect link; nothing created.
  - Counts toward the daily "light" AI allowance (`ai_budget`); token use is logged in `wa_ai_usage`.
- **Reminder:** template `task_due_reminder` at the due time (or 09:00 local on the due date), once per task:
  `Reminder: your Hymn task "{{1}}" is due {{2}}.` with quick replies Done / Snooze 1 day.
  - Snooze → due tomorrow, reminded again.
- **Done:**
  - Quote-reply "done" on a card or reminder (or tap Done) → that exact task.
  - Bare "done" → closes it if exactly one WhatsApp task is open from the last 24 hours, else a list.
  - "done priya venue" → the best-matching open task, else a list.

## Templates to submit (Utility)

- `task_due_reminder`: `Reminder: your Hymn task "{{1}}" is due {{2}}.` Buttons (quick reply): `Done`, `Snooze 1 day`.
- `task_overdue`: `Your Hymn task "{{1}}" was due {{2}} and is still open.` Buttons: `Done`, `Reschedule` (not
  sent at launch: one reminder per task).
- `link_confirmed`: `Your WhatsApp is now linked to your Hymn account. Reply STOP to unlink.` (not needed while
  the link reply is inside the window; kept for later).

## App routes

- `GET /api/whatsapp` → `{available, linked, number: "•••• 2345", linked_at, paused, consent_text,
  consent_version}`. Show the screen only when `available` is true.
- `POST /api/whatsapp/link {"consent": true}` → code and wa.me url (400 without consent, 503 until set up).
- `POST /api/whatsapp/pause {"paused": true|false}` → the in-app opt-out switch.
- `DELETE /api/whatsapp/link` → disconnect (also opts the number out).

## Collections

`wa_link`, `wa_link_codes`, `consent_log`, `wa_opt_out`, `wa_session` (last_inbound_at, window_started_at,
last_disclosure_at), `wa_inbound` (raw_text kept 7 days), `wa_outbound` (message id → task / card),
`wa_drafts` (cards waiting for an answer, deleted after 7 days), `wa_ai_usage`.
