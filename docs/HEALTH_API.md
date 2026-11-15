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
