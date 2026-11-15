# Health API (for the app)

Healthspan: live longer, think clearly, remain independent. Six domains with
a Sanskrit lens (from Sushruta's swasthya) and modern measurements.
**Thresholds and red flags are a draft until a doctor reviews them**
(`rules_reviewed: false`). Health data is stored only after consent.

- `PUT /api/health/profile` — `{consent: true, date_of_birth, sex, height_cm, conditions[], medicines[],
  family_history[], smoking (never/former/current), alcohol_drinks_per_week, pregnant_or_breastfeeding,
  eating_disorder_history, on_glucose_lowering_medicine, hearing_difficulty}`. `GET` returns it (or `{consent:false}`).
- `GET /api/health/options` — metric labels/units, conditions, family history, symptoms, domains (for pickers).
- `POST /api/health/daily` — the 30-second log: `{date, energy, mood, stress, digestion (1–5), bowel (0 none,
  1 hard, 2 easy), sleep_hours, steps, active_minutes, symptoms[]}` → `{saved, red_flags[]}`. **Show
  `red_flags` first, prominently** (`level`: emergency / emergency_mental / doctor_today / doctor_soon,
  `action` text with helplines).
- `POST /api/health/measurements` — list of `{metric, value, taken_on, source (you/watch/lab/doctor/ai), note}`.
  `GET /api/health/measurements?metric=` — history.
- `GET /api/health/dashboard` — `domains[]` (`label`, `lens` (Sanskrit), `rating` 0–4 or null, `colour`
  green/amber/red/missing, `indicators[]` with value, unit, date, source, status green/amber/red/outdated/
  missing/recorded and `why`), `risks[]`, `missing[]`, `red_flags[]`, `screening` (`weight_loss_ok`,
  `see_doctor_first_because[]`), `note`. **There is no overall score — never invent one.**
- `DELETE /api/health/all` — deletes all health data.
- Health plans are life plans with `for_what` (the life it serves) and `serves_plan_id` (a dream plan);
  responses include `serves`.

## Food (portions, not calories) and suggestions
- The daily log also takes `strength_session` (0–3), `veg_fruit_portions`, `protein_servings`, `sugary_items`,
  `outside_meals`, `water_glasses`.
- Lab values are **optional**: without them they show `status: "not_measured"` and are never listed as
  missing; nothing is suggested from them.
- `GET /api/health/suggestions` → up to 3 `{what, why, action, measure, review_in_days}` from what the person
  logs. With under 5 logged days in 2 weeks it just says to log food and movement for a week.

## Habits to change — `/api/habits`
- `GET /api/habits/kinds` → kinds with allowed goals (tobacco and betting: quit only) and units.
- `POST /api/habits` `{kind, label (for "other"), goal quit|cut_down, baseline_per_day, target_per_day (cut
  down), cost_per_unit (₹), for_what, serves_plan_id, private, started_on}`.
- `GET /api/habits` / `GET /api/habits/{id}` → habit + `serves` (dream) + `support` (real help, e.g. quitline,
  alcohol safety) + `progress` (`days_on_track` of `days_logged` in the last 28 — **no streaks**,
  `welcome_back` message, `top_triggers`, `money_freed`, `hours_freed` for screens, `steady_the_edge` tips).
- `POST /api/habits/{id}/log` `{date, amount (0 = clean day), triggers[]}` — one per day.
- `POST /api/habits/{id}/urge` `{date, trigger}` → `{your_reason, serves, try_this[], note}`: show the reason big.
- `POST /api/habits/{id}/dream-fund` → monthly saving of what the habit used to cost, to the dream.
- `DELETE /api/habits/{id}`. Deleting all health data also deletes habits.

## Food log (search or photo) — `/api/food`

Needs the health consent. Numbers always come from Hymn's food list (200 everyday Indian and foreign foods, in real servings: roti, katori, plate, glass) or the person's own foods — never from the AI. Calories are shown as a rough range; portions come first. People whose health profile has `eating_disorder_history` get portions only (no `kcal`, no grams anywhere). Values are typical, pending a nutritionist's review (`values_reviewed: false`).

- `GET /api/food/search?q=` → foods `{id, name, unit, kcal, protein_g, carbs_g, fat_g, fibre_g, counts{veg_fruit_portions, protein_servings, sugary_items}, fried, group, custom}`. Hindi/regional names and partial words work (chapati, dahi, palya, biry).
- `POST /api/food/photo` `{image_base64, media_type: image/jpeg|png|webp}` (under 5 MB; resize to ~1024 px in the app) → nothing saved, photo not kept:
  - plate: `{kind: "plate", items: [{seen_as, amount, confidence: high|medium|low, food, alternatives[3], nutrition{kcal, kcal_low, kcal_high, protein_g…, veg_fruit_portions…}}], photos_left, note}`. Show each line with − / + (halves) and a "change" picker from `alternatives` or search; `food` can be null (let them search).
  - label: `{kind: "label", label: {product_name, serving_size, kcal, protein_g, carbs_g, fat_g, sugar_g}}` → prefill "Save as my food".
  - `not_food`. Errors: 429 monthly photos used (free 30, Premium 300), 503 AI down (allowance not used) — fall back to search.
- `POST /api/food/meals` `{date, meal: breakfast|lunch|dinner|snack, outside, from_photo, items: [{food_id, amount} | {name}]}` → the meal with per-line nutrition and `totals`. Items with only a name are kept but counted in nothing (`not_counted`).
- `GET /api/food/day?date=` → `{meals[], totals: {portions{veg_fruit_portions, protein_servings, sugary_items, outside_meals}, calories{estimate, low, high, note} | null, protein_g…}}`. Show portions first; calories as "about 1,200 (1,000–1,450)".
- `DELETE /api/food/meals/{id}`.
- `POST /api/food/my-foods` `{name, unit, kcal, protein_g, carbs_g, fat_g, fibre_g, veg_fruit_portions, protein_servings, sugary, fried}`, `GET`, `DELETE /api/food/my-foods/{id}`.

The day's portions are written into the daily log automatically (what suggestions read). A manual tap in the daily log for the same day replaces them until the next meal is logged. Deleting all health data also deletes meals and own foods.

## Watch and phone sync — any brand, or none — `/api/health/sync`

The app reads the phone's health hub and posts the numbers; Hymn doesn't care which watch.
- Android: **Health Connect** (Samsung Health, Google Fit, Fitbit and many other apps write into it). iPhone: **Apple Health**. No watch: the phone's step counter via the same hub, or the daily log.
- `POST /api/health/sync` `{source_app: "Samsung Health"|"Fitbit"|"Apple Health"…, device, readings: [{metric, value, date (local YYYY-MM-DD), unit?}]}` → `{saved, skipped, last_sync}`. Metrics: steps, active_minutes, sleep_hours (or minutes with `unit: "minutes"`), resting_hr, weight_kg (or `unit: "lb"`), vo2max, bp_systolic, bp_diastolic. One value per metric per day; re-sending a day replaces it. Bad readings are skipped, never fail the batch. Send the last 30 days on first connect, then daily.
- What the person types for a day wins over the watch for that day.
- `GET /api/health/sync` → `{sources[{source_app, device, last_sync, readings}], metrics, hubs[], note}` (use `hubs` for the "connect" screen).
- `POST /api/health/sync/disconnect` `{source_app, delete_data}`.

## Lab reports (optional, never required) — `/api/health/labs`

- `POST /api/health/labs/read` `{file_base64, media_type: application/pdf|image/jpeg|png|webp}` (under 10 MB; unlock password PDFs first) → nothing saved, file not kept → `{is_lab_report, report_date, lab, results: [{test_name, value, unit, reference_range, flag, metric|null, hymn_value, hymn_unit, status, why, check?}], note}`. Hymn tracks fasting glucose, HbA1c, LDL, HDL, triglycerides, eGFR, urine albumin (units converted: mmol/L, mmol/mol, mg/mmol); everything else is kept as printed. A line with `check` couldn't be read safely: ask the person to check it.
- `POST /api/health/labs` `{report_date, lab, results[]}` (send back the confirmed lines) → `{id, tracked_saved, kept_as_printed}`. `GET /api/health/labs`, `DELETE /api/health/labs/{id}` (also removes its values).
- Allowance: free 3 reports a month, Premium 20 (`HYMN_LAB_READS_FREE` / `_PREMIUM`); 429 when used, 503 when the AI is down (not counted). Typing values in (`POST /api/health/measurements` with `source: "lab"`) is always free.

## Check-up calendar — `/api/health/checkups`

- `GET` → `{checks: [{key, label, why, every_months, last_done, next_due, status: overdue|never|due_soon|ok, ask_doctor}], missing_profile[], rules_reviewed, note}`, overdue first. Fits age, sex, conditions, family history and tobacco (India's screening programme for 30+: BP, diabetes, oral, breast, cervical; plus lipids, kidney and eyes for diabetes/BP, dental, hearing 60+, bones for women 65+, bowel from 50 "ask your doctor", weight & waist every 3 months). DRAFT until a doctor reviews.
- A logged value counts as done (a BP reading, an HbA1c). `POST /api/health/checkups/{key}/done` `{date}` for the rest → the updated calendar.

## 90-day progress — `GET /api/health/progress?start=`

First 30 days from `start` (default: the start of the last 90 days with logs) vs days 61–90 (or the latest 30 while running) → `{day, complete, baseline, compared_with, lines: [{metric, label, unit, before, after, change, verdict: better|worse|steady|changed, points}], note}`. Weight shows `changed`, never better/worse. Before day 31: `lines: []` and a "Day N of 90" note.

## Doctor summary — `GET /api/health/doctor-summary?format=json|text&include_private=false`

One page for a doctor: age, sex, conditions, medicines, family history, smoking/alcohol, latest readings (value · date · source), 90-day changes, symptoms logged in 90 days, habits (private ones only with `include_private=true`), check-ups due, latest lab report as printed, and the person's questions (`doctor_questions` in the profile, up to 10). `format=text` returns plain text for WhatsApp / email / print.

## Caregiver mode — `/api/care` and `?for=`

Look after a parent's (or child's) health from your own account.
- `POST /api/care` `{name, relation: mother|father|parent_in_law|grandparent|spouse|child|sibling|other, their_consent: true}` → `{id: "care_…", …}`. `their_consent` = "they know and agree, or I'm their guardian" (required). Up to 10 people.
- Every Health call works for them with `?for=<id>`: `PUT/GET /api/health/profile`, `/measurements`, `/daily`, `/dashboard`, `/suggestions`, `/checkups` (and `/done`), `/labs` (read/save/list/delete), `/progress`, `/doctor-summary` (uses their name), `DELETE /api/health/all`. Not for them: food log, habits, watch sync.
- `GET /api/care` → `[{id, name, relation, profile_done, checkups_due, last_reading}]` (a "People I look after" list; show a dot when `checkups_due` > 0).
- `PATCH /api/care/{id}` `{name}`; `DELETE /api/care/{id}` removes them and all their health data.
- Their check-ups and 90-day report nudge you (`data.for` = their id).

## Health in plans (opt-in)

- Profile switch `use_in_planner` (default off): "Use my health in plans". When on, the planner sees a short summary — age, conditions, areas needing attention, 2-week averages of steps / active minutes / sleep / strength, habits being changed (not private ones), and whether weight loss needs a doctor first. Never raw logs, lab values or symptoms. When off, the planner sees only that health isn't shared and may ask once.
- Plans can have **health requirements**: `{area: "health", kind: "health", what, metric, target}` with `metric` one of steps, active_minutes, strength_session (a week), sleep_hours, veg_fruit_portions, water_glasses, sugary_items, outside_meals, screen_hours, resting_hr, waist_cm, bp_systolic. Benchmarked from the last 2 weeks of logs: reached → `now`; not yet and before the date → `by_then` (`building: true`, `gap`); date passed → `short`; no data / not shared → `unknown` with a `note`. Accepting adds a "Build up: …" task.
