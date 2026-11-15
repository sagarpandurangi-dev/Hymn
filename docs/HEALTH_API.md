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
