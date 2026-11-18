# Emergent prompts, A to U

Paste **one prompt at a time, in order**. After each one, use **"Save to GitHub"** onto the `emergent-frontend` branch and tell Claude, so it can check the work before the next. Every prompt starts with the same two safety lines: keep them.

A–B finish the earlier fixes. C lays the groundwork the rest builds on. D–E are the first-time experience and the Me screen. F–L are Money, time and plans. M–Q are Health. R–T are Family, Learning and Work. U is optional polish.

Backend API notes, if Emergent asks for more detail: `docs/HEALTH_API.md`, `docs/PEOPLE_API.md`, `docs/LEARNING_API.md`, `docs/WORK_API.md`, `docs/INVESTMENTS_API.md`, `docs/PLANNED_MONEY_API.md`, `docs/REPORTS_API.md`, `docs/NUDGES_API.md`, `docs/INBOX_API.md`.

---

## A. Pending fixes and Pamphlet ID card

```text
Do not modify anything under backend/. Do not change the backend URL in frontend/src/lib/api.ts.

Skip anything below that is already done.
1. Finance tab: show the available-money row (available_liquidity from the dashboard: available_unreserved as "Available to spend", reserved as "Set aside") and the "Pending account → Assign" shortcut.
2. Remove Scenarios completely (app/finance/scenarios-index.tsx, app/finance/scenarios-detail.tsx, every link to them, and their functions in api.ts). Keep the Forecast screens.
3. Forecast screen: show each currency's basis text as a small grey note; in each month show usual_spending as "Everyday spending", and maybe_income / maybe_spending in grey as "Maybe" when not zero.
4. TimeBlockEditor: save cross-midnight blocks as one entry (e.g. 23:00 → 07:00), keep the "ends next day" hint, and make the overlap warning include saved overnight blocks.
5. Me screen: a "Your Pamphlet ID" card from GET /api/auth/me (hymn_alias large if present, hymn_id below, a copy button for each) with the line "One ID for Hymn and Pamphlet — share it instead of your phone number."

Tell me what you changed.
```

## B. Time on every check-in, and a faster Finance tab

```text
Do not modify anything under backend/. Do not change the backend URL in frontend/src/lib/api.ts.

1. Check-in time (required): on every check-in form (new and edit, including the quick check-in), add a row of tappable buttons: 15m, 30m, 45m, 60m, 2h, 3h (tap one to select it; tapping another replaces it). Send the choice as duration_minutes (15, 30, 45, 60, 120, 180). Saving is blocked until one is picked, with the message "How long did it take?". Show the duration on check-in lists ("· 45m").
2. Finance tab in one call: load the Finance tab from GET /api/screens/finance instead of separate calls. It returns {dashboard, planned_upcoming, planned_this_month}: dashboard is exactly what GET /api/finance/dashboard returned; planned_upcoming is the next 6 planned-money items; planned_this_month is a list of {month, currency, income, spend, moves, set_aside, maybe_in, maybe_out}. Keep everything the tab shows today.

Tell me what you changed.
```

## C. Groundwork: the Life tab, friendly errors, uploads, Draft note

```text
Do not modify anything under backend/. Do not change the backend URL in frontend/src/lib/api.ts.

1. Bottom tabs become: Today · Timeline · Finance · Life. Replace the "Knowledge" tab with a new "Life" tab (app/(tabs)/life.tsx). Keep the old Knowledge screen file; it will be linked from Learning later.
2. The Life screen shows five cards, in this order unless the device has a saved list of focus areas (AsyncStorage key "hymn.focusAreas", an array like ["health","work"]) — those come first:
   - Health → a "Health" screen (placeholder for now: "Coming soon").
   - Family & Relationships → placeholder.
   - Learning → for now opens the old Knowledge screen.
   - Work → placeholder.
   - Plans → the existing planner for now.
   Each card has an icon, the area name and one short line (leave the line empty for now; later prompts fill it).
3. Friendly errors in the request() helper in api.ts (do not change the URL): for HTTP 429 show the server's "detail" text (e.g. "You've reached today's limit for this. It resets tomorrow."); for 413 show "That file is too large."; for 503 show the server's "detail"; for 401 sign out and go to sign-in. Show these as a toast or inline message, never a crash.
4. A shared upload helper (src/utils/upload.ts — extend it if it exists): pickImage() and pickPdf() that return {base64, mediaType}. Images are resized to at most 1024 px on the long side and saved as JPEG quality 0.7 before converting to base64 (expo-image-manipulator, expo-file-system). Several later screens send files as JSON {file_base64 or image_base64, media_type}.
5. A shared <DraftNote/> component: a small amber note "Draft — not yet reviewed by a doctor" (or a custom text prop). Later screens show it when the API says rules_reviewed or values_reviewed is false.
6. A shared money formatter if missing: ₹ with Indian grouping (₹1,25,000), from amount strings.

Tell me what you changed.
```

## D. First-time welcome and setup wizard

```text
Do not modify anything under backend/. Do not change the backend URL in frontend/src/lib/api.ts.

Build a welcome wizard for new people (app/welcome/…). Calm, one question per screen, a progress line at the top, a Back button, and "Skip" on every step except the first. The whole thing should take about 3 minutes.

When it shows: right after sign-up, and for a signed-in person whose user has no portfolio_setup_completed_at (this replaces the current redirect to /portfolio/setup in app/_layout.tsx). At the end, call PUT /api/portfolio/setup-status with {"completed": true, "reporting_currency": "<the bank account's currency from step 7, else INR>"} and go to Today. This works even if every step was skipped (the server needs nothing else). If the person closes the app halfway, start again at the step they reached (remember it in AsyncStorage "hymn.welcome.step").

Steps:
1. Promise: "Hymn helps you follow through on your life." Under it, one line each: Money, Health, Family & Relationships, Learning, Work. Button "Let's start".
2. "What matters most right now?" Pick up to 3 of the five areas (chips). Save to AsyncStorage "hymn.focusAreas" (e.g. ["money","learning"]).
3. Time zone: detect it (Intl.DateTimeFormat().resolvedOptions().timeZone), show it with "Change", save with PUT /api/nudges/settings {"timezone": "<zone>"}.
4. Your week:
   a. "Do you work?" — Salaried, Self-employed, Business owner, Freelancer, Articleship / intern, Looking for work, Homemaker, Not now. For any of the first five: work days (Mon–Sun chips, Mon–Fri preselected), start and end time, commute minutes each way (0, 15, 30, 45, 60, 90). Save with POST /api/work/roles {type, work_days: ["monday",…], start_time "09:30", end_time "18:30", commute_minutes}. Types: salaried, self_employed, business_owner, freelancer, articleship, looking_for_work, homemaker.
   b. Sleep: bedtime and wake-up time (e.g. 23:00 and 07:00). Save one block per day of the week with POST /api/portfolio/time-commitments {title: "Sleep", day_of_week: "monday"…"sunday", start_time: "23:00", end_time: "07:00", commitment_type: "sleep", flexibility: "fixed", effective_from: today YYYY-MM-DD}. Overnight blocks are allowed as one entry.
5. "Empty your head": a big text box — "Type everything on your mind. Hymn will sort it." Send it through the existing brain-dump flow (POST /api/inbox/dumps, then the existing sort step). Show "Sorted into N things".
6. "People who matter": up to 3 rows of name, relation (mother, father, spouse, partner, child, sibling, friend, other) and optional birthday (day + month picker; send "MM-DD"). Save each with POST /api/people {name, relation, circle: "inner", birthday}.
7. Money (optional): "Add your main bank account" using the existing add-account form (POST /api/portfolio/financial-accounts), or Skip.
8. Notifications: show a preview of one gentle reminder ("Amma's birthday is tomorrow"), then ask for permission and register the device (existing push code).
9. The payoff: "You have X free hours this week" from GET /api/reports/time (commitments.free_hours), and "Your 3 things for today" from GET /api/inbox/review (first 3 items). Button "Tell Hymn one thing you want" → the planner.

After the wizard, the Today screen shows a small "Finish setting up — N of M done" card from GET /api/account/setup ({steps[{key,title,why,screen,done,optional}], done, of, complete, next}) with the `next` step's title and a button to its screen. Map screen keys: settings → Me/notification settings, portfolio/setup → add account, work → Work, people → Family & Relationships, plan-chat → planner, health → Health, inbox/dump → brain dump. Hide the card when complete is true or the person taps "Not now" (remember for 7 days).

Health is deliberately not in the wizard.

Tell me what you changed.
```

## E. Me screen: notifications, download my data, delete my account

```text
Do not modify anything under backend/. Do not change the backend URL in frontend/src/lib/api.ts.

1. Notification settings (Me → Notifications), from GET /api/nudges/settings → settings{...}. For each section show an on/off switch and a time picker (where it has a time), saving with PUT /api/nudges/settings (send only what changed, e.g. {"health": {"enabled": false}}):
   - daily_review "Evening review" (time, plus the existing "adapt to my routine" switch and daily_review_plan.explanation)
   - weekly_patterns "Your week in Hymn" (weekday + time)
   - reminders "Reminders" (switch only)
   - health "Health" (time, default 09:30)
   - people "Birthdays and keeping in touch" (time, default 09:00)
   - learning "Today's study" (time, default 07:00)
   - work "Work" (time, default 18:30)
   - quiet_hours "Quiet hours" (start and end)
2. Notifications feed (the existing nudges screen) and tapping a push notification: route by data.screen — "inbox/review", "inbox/patterns", "plans" (with plan_id), "health", "health/checkups", "health/progress", "health/daily", "habits" (habit_id), "people" (person_id), "learning" (journey_id), "work" (role_id). If data.for is set, open Health for that person (see prompt Q). Unknown screens open Today.
3. "Download my data": GET /api/account/export → save as hymn-data-YYYY-MM-DD.json and open the share sheet (expo-sharing). Note under the button: "Everything Hymn holds for you, in one file."
4. "Delete my account": a separate screen. Explain what is deleted (everything, including people you look after and their health data; your Pamphlet ID is retired, never given to anyone else). A password field and a field where the person types DELETE. Button stays disabled until both are filled. DELETE /api/account with JSON body {"password": "...", "confirm": "DELETE"}. On success, sign out and show "Your account has been deleted." Show the server's message on 400.

Tell me what you changed.
```

## F. Planned money

```text
Do not modify anything under backend/. Do not change the backend URL in frontend/src/lib/api.ts.

Add a "Planned money" screen (Finance tab, under the forecast): one list of everything expected to come in or go out.
1. List from GET /api/planned-money: title, amount (₹), direction (in green / out), repeat ("Once on 12 Dec", "Monthly from Jan 2027", "Yearly in March"), certainty (a grey "Maybe" tag when certainty is maybe), "Set aside" tag when set_aside is true, and remaining_amount when part is done. Items with editable: false come from older screens: show them with a small lock and "Edit on the old screen" (no edit button).
2. Add / edit form (POST /api/planned-money, PATCH /api/planned-money/{id}): title; In or Out; purpose (in: income; out: spend, saving, investment, loan payment, other → spend, saving, investment, loan_payment, other); amount; Once (date picker) / Monthly / Yearly (start month and optional end month, with tap-to-pick month selectors); Sure / Maybe; for a one-off spend, a "Set money aside for this" switch (set_aside). Currency INR by default.
3. Swipe actions: Mark done (PATCH {status: "done"}), Cancel (PATCH {status: "cancelled"}), Delete (DELETE).
4. A "Next 12 months" view from GET /api/planned-money/months?count=12: per month, In, Out, To savings/investments (moves), Set aside, and Maybe in/out in grey.

Tell me what you changed.
```

## G. The three money statements

```text
Do not modify anything under backend/. Do not change the backend URL in frontend/src/lib/api.ts.

Add a Statements section on the Finance tab with three screens. All amounts are strings; show ₹ with Indian grouping.
1. Statement of Net Worth (GET /api/reports/net-worth), the old side-by-side format: left column "Liabilities & Net Worth", right column "Assets", both ending in the same total. Left: left.net_worth as "Opening net worth (1 Apr)", "Add: surplus this year", "Other changes", total; then left.liabilities[] groups with their lines. Right: right.assets[] groups (label, amount, lines[] with name, amount). Title "Statement of Net Worth as at <as_of>". On a phone the two columns may stack (left first).
2. Income & Expenditure (GET /api/reports/income-expenditure?month=YYYY-MM), vertical: INCOME groups, Total income, EXPENDITURE groups, Total expenditure, SURPLUS / (DEFICIT), Savings rate. Three columns: This month, Last month, Year to date (this_month, last_month, year_to_date). Tap a group to expand its categories; tap a category to open its entries from GET /api/reports/entries?category=<category>&start=<start>&end=<end> (date, description, amount). Month picker at the top.
3. Cash Flow (GET /api/reports/cash-flow?month=YYYY-MM): Opening cash, then each section (Living, Investing, Borrowing, Other) with its lines and net, Net change, Closing cash; a small ✓ "Adds up" when adds_up is true.

Tell me what you changed.
```

## H. Recent activity from the money book, and investment statements

```text
Do not modify anything under backend/. Do not change the backend URL in frontend/src/lib/api.ts.

1. Finance → Recent activity: rows now come from the money book for people who switched to it. Each row has id, detail ("event" or "ledger"), kind, description, event_date, currency, direction ("inflow", "outflow" or "transfer"), amount, source. Show transfers with "↔" and no + or −, in grey. When detail is "ledger", tapping a row opens a small read-only sheet from the row's own fields (date, description, amount, a plain label for kind — expense "Spent", income "Received", transfer "Moved between your accounts", card_settlement "Card bill paid", loan_payment "Loan EMI", revaluation "Market value change", investment "Invested", redemption "Taken out", refund "Refund", borrowing "Loan received" — and source) instead of the event screen. When detail is "event", keep opening the event screen.
2. Investments (Premium; a 403 means show "Premium feature"): Finance → "Add investments from a statement".
   a. Explain where to get the PDF: "Mutual funds: request a Consolidated Account Statement on the CAMS or KFintech website (detailed, with transactions); the password is the one you set. Shares and demat: NSDL or CDSL email it every month; the password is usually your PAN in capitals."
   b. Pick a PDF and type its password → POST /api/investments/cas/preview {file_base64, password}. Show "Reading your statement…" (it can take a few seconds). A 400 shows the server's message.
   c. Preview: source, period, investor name (so people notice a spouse's statement), the total, and each line: name, folio, units, price, value, valued_on, an "action" tag (new → "New", update → "Update" with the change, same → "No change", older → "Older than what Hymn has"), and a warning row when check is set. Lines of kind stock, bond or nps expand to their items. If already_applied is true, say "This statement is already in your money book."
   d. If your_other_investment_accounts is not empty, ask: "Is any of these the same as a fund in this statement?" For each account let the person pick: "This is the same fund as …" (choose a line → links {line key: account id}), "This statement replaces it" (→ replaces [account id]) or "Something else" (nothing).
   e. Apply: POST /api/investments/cas/{id}/apply {links, replaces} → show "Added N, updated N" and any missing funds ("Not in this statement — maybe sold?").
   f. "Past statements" list from GET /api/investments/cas.

Tell me what you changed.
```

## I. My week (time statements)

```text
Do not modify anything under backend/. Do not change the backend URL in frontend/src/lib/api.ts.

Add a "My week" screen (from the Today tab) using GET /api/reports/time?week_start=YYYY-MM-DD (any day; it uses that week's Monday), with week arrows.
1. Commitments: Fixed, Flexible & set aside, Free (all …_hours), out of 168h — a simple bar plus numbers. Below: "Time invested this year" from commitments.time_assets_this_year (area label + hours).
2. Time spent: a table of spent.areas[] — area, Planned, Actual, Gap (gap red when negative for Learning, Health and Family; red when positive for Work and Commute). Tap an area to show its lines (Work can include "Overtime" and "Shorter days"). Show "Soul (untracked): X h" only when spent.show_soul is true. Show "Waking hours as planned: N%".
3. Time flow: Planned free → Overruns → Skipped plans → Untracked (flow.*_hours).
4. If untimed_checkins > 0: "N check-ins this week have no time".

Tell me what you changed.
```

## J. Things I own & owe (Premium)

```text
Do not modify anything under backend/. Do not change the backend URL in frontend/src/lib/api.ts.

Add "Things I own & owe" (Finance tab), Premium only (a 403 means show "Premium feature").
1. List from GET /api/life-objects: name, type, ltc.to_date, ltc.per_month, ltc.per_unit with its unit ("₹4.20 per km").
2. Add (POST /api/life-objects): type (Asset / Liability / Venture), kind (car, bike, house, phone, credit card, loan, business, other), name, start date, and by type: asset → price, extra costs (registration etc.), life in months, resale value; loan → account (pick a loan or card account), loan amount, interest % a year, tenure in months, first EMI date, reducing/flat, EMI (optional).
3. Detail (GET /api/life-objects/{id}): lifetime cost to date with the breakdown (getting_it, value_lost, keeping_it list, cost_of_money, came_back), per month, per unit, projected over its life, hours; the entries list. Buttons: "Loan schedule" (GET /api/life-objects/{id}/schedule: EMI, total interest, table of rows) for loans; "Fuel" (GET /api/life-objects/{id}/fuel: km per litre, cost per km, the stretches) for car/bike; "Mark sold / ended" (PATCH with ended_on, sold_for).
4. Check-ins on a car/bike (its project_id): add optional fields Odometer, Price per litre, Litres, Full tank (yes/no) saved in the check-in's data as odometer, price_per_litre, litres, full_tank.

Tell me what you changed.
```

## K. Family net worth

```text
Do not modify anything under backend/. Do not change the backend URL in frontend/src/lib/api.ts.

Add a "Family net worth" screen (from the Finance tab).
1. GET /api/family → if family is null, a "Create my family" button (POST /api/family). Show invites_for_me with Accept (choose "Share my total" or "Share my breakdown" → POST /api/family/invites/{id}/accept with share = total/full) and Decline (POST /api/family/invites/{id}/decline).
2. Members list with "Invite by Pamphlet ID" (POST /api/family/invite with pamphlet_id, relation) and "Add someone without the app" (POST /api/family/members with name, relation). My sharing setting (PATCH /api/family/me) and Leave (POST /api/family/leave).
3. Add an entry for someone (or joint): side (asset/liability), group (assets: fixed, investments, retirement, deposits, cash; liabilities: loans, current), name, amount, owners with % that add up to 100 (POST /api/family/items). Delete with DELETE /api/family/items/{id}.
4. Family net worth (GET /api/family/net-worth): a column per member (members[]: name, net_worth; and assets/liabilities by group when shared in full) and the family total (family). Note: "Joint things are counted once."

Tell me what you changed.
```

## L. The new planner

```text
Do not modify anything under backend/. Do not change the backend URL in frontend/src/lib/api.ts.

Replace the planning chat with the new planner (keep the old screen reachable from Settings as "Old planner" for now). The Life tab's Plans card opens it.
1. Chat: POST /api/plan-chat with {message, chat_id} (no chat_id for a new conversation) → {chat_id, reply, latest_plan, plan_ids}. Show reply as the assistant's message. History: GET /api/plan-chat/{chat_id} → turns[] (role, text). A 503 means "The planner is unavailable right now"; a 429 shows the server's message. In both cases keep the typed message.
2. Plan card under the chat whenever latest_plan is present: title, target date, a verdict badge (fits_now "Fits now", fits_by_then "Fits by then", needs_answers "Needs your answers", doesnt_fit "Doesn't fit yet"), then "What must go right" (requirements[]: area, what, and by kind:
   - money → Needed amount, Available now available_now, By then built_up_by_then, Short gap;
   - time → free slots with a "Book" button calling POST /api/life-plans/{id}/book with {requirement_id, date, start, minutes};
   - condition → Yes / No / Not yet buttons calling POST /api/life-plans/{id}/requirements/{rid}/answer {answer: yes|no|unknown};
   - health → "Now" available_now and "Aim" target with unit (e.g. "Now 5,000 · Aim 8,000 steps a day"), "Building up" when building is true, and the note in grey when present),
   each with a status tick (now ✓, by_then ✓ "by then", short ✗, unknown ?). Then "What may stop it" (risks[]: what, likelihood, early warning, what to do).
3. When the conversation produced several plans (plan_ids), let the person swipe between them (GET /api/life-plans/{id}) and pick one with "Go with this" (POST /api/life-plans/{id}/accept).
4. A "My plans" list from GET /api/life-plans (active plans with their verdict), opening the same card. "Drop this plan" → DELETE /api/life-plans/{id}.
5. Life tab → Plans card line: "N plans" from GET /api/life-plans.

Tell me what you changed.
```

## M. Health 1: consent, profile, daily log, dashboard, suggestions

```text
Do not modify anything under backend/. Do not change the backend URL in frontend/src/lib/api.ts.

Build the Health screens (Life tab → Health). Tone: calm, never scary, never guilt. Show <DraftNote/> wherever the response has rules_reviewed: false.
1. Consent first: GET /api/health/profile. If consent is false, show what Hymn stores (your answers and readings), that nothing is shared, and that you can delete it all any time; a checkbox "I agree to Hymn storing my health data"; then the profile form. Save with PUT /api/health/profile — it replaces the whole profile, so always send every field: {consent: true, date_of_birth, sex (male/female/other), height_cm, conditions[], medicines[] (names only), family_history[], smoking (never/former/current), alcohol_drinks_per_week, pregnant_or_breastfeeding, eating_disorder_history, on_glucose_lowering_medicine, hearing_difficulty, doctor_questions[], use_in_planner}. Get the lists for conditions and family history from GET /api/health/options.
2. Daily log ("30 seconds"): POST /api/health/daily {date, energy, mood, stress, digestion (1–5 faces), bowel (0 none, 1 hard, 2 easy), sleep_hours, steps, active_minutes, strength_session (0–3), veg_fruit_portions, protein_servings, sugary_items, outside_meals, water_glasses, symptoms[]}. Only send what was filled in. Symptoms: a short list from GET /api/health/options (symptoms). The response may contain red_flags[] — show them FIRST, big and clear, before anything else, with their action text (helpline numbers tappable to dial: 112, 14416).
3. Health home: the dashboard (GET /api/health/dashboard): six domain cards (label, the Sanskrit lens in small italics, a colour dot green/amber/red or grey "missing"), tap to open its indicators (label, value + unit, date, source, status, why). There is NO overall score — never show one. red_flags[] at the top if any. "Missing" indicators as a gentle "Add" list. Lab metrics may say not_measured — show "Not measured" in grey, never as a problem.
4. Suggestions (GET /api/health/suggestions): up to 3 cards (what, why, action, "Check again in N days").
5. Health settings: edit profile; "Delete all my health data" (confirm screen → DELETE /api/health/all).
6. Life tab → Health card line: "Set up" when consent is false; otherwise the first suggestion's what.

Tell me what you changed.
```

## N. Health 2: food log with photos

```text
Do not modify anything under backend/. Do not change the backend URL in frontend/src/lib/api.ts.

Add "Food" in Health (needs health consent).
1. Today's food (GET /api/food/day?date=YYYY-MM-DD): meals in order (breakfast, lunch, dinner, snack) with their items; totals with PORTIONS FIRST (fruit & veg, protein, sweets, outside/fried meals) and calories after, as a range: "about 1,200 (1,000–1,450)" from totals.calories {estimate, low, high} with its note in grey. If totals.calories is null, show portions only and never mention calories. Show <DraftNote text="Food values are typical, pending a nutritionist's review"/> when values_reviewed is false.
2. Add a meal: pick breakfast/lunch/dinner/snack, "Eaten out / ordered in" switch, then add items by:
   a. Search (GET /api/food/search?q=): name and unit ("1 katori", "1 piece"); − / + amount in halves; "My foods" appear in the results too.
   b. Photo: take or pick a photo (use the upload helper; images resized) → POST /api/food/photo {image_base64, media_type}. For kind "plate": a line per item with seen_as, the matched food (or "Not sure — search"), amount with − / +, confidence (show "?" for low), and "Change" picking from alternatives or search. For kind "label": prefill "Save as my food" (step 4). For kind "not_food": "That doesn't look like food." Show photos_left small. 429 → server message; 503 → "Couldn't read the photo — search instead."
   c. "Something else": type a name (saved but not counted).
   Save with POST /api/food/meals {date, meal, outside, from_photo, items: [{food_id, amount} | {name}]}.
3. Delete a meal: DELETE /api/food/meals/{id}.
4. My foods: list (GET /api/food/my-foods), add (POST /api/food/my-foods {name, unit, kcal, protein_g, carbs_g, fat_g, fibre_g, veg_fruit_portions, protein_servings, sugary, fried}), delete.

Tell me what you changed.
```

## O. Health 3: habits to change

```text
Do not modify anything under backend/. Do not change the backend URL in frontend/src/lib/api.ts.

Add "Habits to change" in Health. Tone: supportive, never shaming; no streaks anywhere.
1. List (GET /api/habits): each habit with its reason ("For: <serves.title or for_what>"), "N of the last M days on track" (progress.days_on_track / days_logged), money_freed and hours_freed when present.
2. Add (POST /api/habits): kind from GET /api/habits/kinds (tobacco, betting, alcohol, sugar, junk food, screens, late nights, caffeine, other — with its label), goal quit or cut down (only the goals that kind allows), usual amount a day (baseline_per_day), target (for cut down), cost per unit (₹, optional), "What life is this for?" (for_what, or pick one of my plans → serves_plan_id), private switch (on by default for "other"). Show the habit's support text after saving (e.g. the quitline number, tappable).
3. Habit screen (GET /api/habits/{id}): a big "I'm having an urge" button → POST /api/habits/{id}/urge {date, trigger (optional chips: stress, after a meal, with friends, bored, tired)} → show your_reason BIG, then try_this[] and the note. A daily check-in: "How much today?" (0 = a clean day) with trigger chips → POST /api/habits/{id}/log {date, amount, triggers[]}. Show progress.welcome_back when present, top_triggers, steady_the_edge tips.
4. "Send what I save to my dream" (when the habit has a cost and a plan): POST /api/habits/{id}/dream-fund.
5. Delete (DELETE /api/habits/{id}).

Tell me what you changed.
```

## P. Health 4: check-ups, lab reports, 90-day report, doctor summary

```text
Do not modify anything under backend/. Do not change the backend URL in frontend/src/lib/api.ts.

Add four Health screens. Show <DraftNote/> when rules_reviewed is false.
1. Check-ups (GET /api/health/checkups): overdue first, then never done, due soon, OK: label, why, last done, next due, "Ask your doctor" tag when ask_doctor. Button "Done" → date picker → POST /api/health/checkups/{key}/done {date}. If missing_profile is not empty: "Add your date of birth and sex for a better list."
2. Lab reports (optional — never required): upload a PDF or photo (upload helper) → POST /api/health/labs/read {file_base64, media_type}. Show each result as printed (test name, value, unit, reference range, flag); for tracked ones (metric set) also hymn_value + hymn_unit and a status dot; a warning on lines with check. "Save" → POST /api/health/labs {report_date, lab, results} (send the lines back). List past reports (GET /api/health/labs), delete (DELETE /api/health/labs/{id}). 429 → server message; 503 → "Couldn't read it — you can type values in."
3. 90-day report (GET /api/health/progress): "Day N of 90" until complete; lines with before → after and a word: better (green), worse (amber), steady, changed (for weight — no colour, no praise or blame). Note when lines is empty.
4. Doctor summary (GET /api/health/doctor-summary): a clean one-page view of the sections (about, conditions, medicines, family history, latest readings with date and source, changes over 90 days, symptoms logged, habits, check-ups due, latest lab report, my questions). Buttons: "Share as text" (GET /api/health/doctor-summary?format=text → share sheet) and a switch "Include private habits" (include_private=true). Edit "My questions for the doctor" (doctor_questions in the profile, up to 10).

Tell me what you changed.
```

## Q. Health 5: people I look after, watch, health in plans

```text
Do not modify anything under backend/. Do not change the backend URL in frontend/src/lib/api.ts.

1. People I look after (Health → "People I look after"): list from GET /api/care (name, relation, a dot when checkups_due > 0, last reading). Add (POST /api/care {name, relation: mother|father|parent_in_law|grandparent|spouse|child|sibling|other, their_consent: true}) with a required checkbox "They know and agree, or I'm their guardian". Rename (PATCH /api/care/{id} {name}), remove (DELETE /api/care/{id}, confirm: "This deletes all their health data").
2. A person switcher at the top of Health: "Me" or one of the people I look after. When a person is chosen, every Health call for profile, measurements, daily log, dashboard, suggestions, check-ups, lab reports, 90-day report and doctor summary adds ?for=<their id>. Food, habits and watch stay "Me" only (hide them for others). The screens say whose data it is ("Amma's health").
3. Watch & phone (Health → "Connect a watch"): from GET /api/health/sync show hubs[] (phone, hub, works_with) and sources[] (connected apps with last_sync). The actual connection to Health Connect / Apple Health comes with the next native app update: show a disabled "Connect" button with "Coming in the next app update". "Disconnect" for a listed source → POST /api/health/sync/disconnect {source_app, delete_data} (ask whether to delete its readings).
4. In Health settings, a switch "Use my health in plans" (profile use_in_planner) with the line "The planner sees a short summary — never your logs, lab values or symptoms." Save through PUT /api/health/profile with the full profile.

Tell me what you changed.
```

## R. Family & Relationships

```text
Do not modify anything under backend/. Do not change the backend URL in frontend/src/lib/api.ts.

Build Family & Relationships (Life tab). Gentle by design: never "overdue", no streaks.
1. Home: the summary card (GET /api/people/summary): hours with your inner circle this month, people reached, "Might like to hear from you" (up to 3, with "It's been N days"), "Coming up" (next days that matter: "Amma's birthday · Friday · turns 70").
2. People list (GET /api/people): grouped Inner circle / Close / Wider; each with relation, last together ("3 days ago"), a soft dot when might_like_to_hear_from_you, and next_day.
3. Add / edit a person (POST /api/people, PATCH /api/people/{id}): name, relation (mother, father, spouse, partner, child, sibling, grandparent, grandchild, parent_in_law, relative, friend, mentor, colleague, neighbour, other), circle (inner/close/wider), birthday (day + month, optional year → "MM-DD" or "YYYY-MM-DD"), gift budget for the birthday (birthday_gift), other days (occasions: label, date, gift_budget), "Keep in touch every N days" (keep_in_touch_days; 0 = don't remind), private notes, and a link to a person I look after (care_id from GET /api/care, optional). Delete: DELETE /api/people/{id}.
4. Person screen (GET /api/people/{id}): details, next day, last 50 moments.
5. Log a moment: quick buttons "Called", "Video call", "Met", "Meal", "Messaged", "Helped", with time chips 15m / 30m / 1h / 2h+ and an optional note; can include several people. POST /api/people/moments {person_ids[], date, kind: call|video_call|visit|meal|outing|message|help|celebration|other, minutes, note}. Delete a moment: DELETE /api/people/moments/{id}.
6. Life tab → Family card line: the first of might_like_to_hear_from_you or coming_up.

Tell me what you changed.
```

## S. Learning journeys

```text
Do not modify anything under backend/. Do not change the backend URL in frontend/src/lib/api.ts.

Build Learning (Life tab → Learning; replaces the old Knowledge screen, which stays reachable as "Older learning goals").
1. List (GET /api/learning): each journey with title, status, pace (on_track / behind by N h / ahead) and today_minutes. Button "Start learning something".
2. Start: one text box "What do you want to learn or pass?" (e.g. "CA", "Driving licence by March") → POST /api/learning {goal} → it returns questions[] {key, question, options[]}. Ask them one at a time (chips when options exist, else a text box). Then POST /api/learning/{id}/answers {answers: {key: value}} — this takes up to a minute (web lookups): show "Checking the facts…".
3. Review before starting (the journey response):
   a. checks[] FIRST: level "confirm" → a card with "Looks right" (adds its key to confirmed) or, when options exist, pick one (fact_choices {fact key without "fact:": value}); level "error" → must be fixed (e.g. set an exam date with a date picker → stage_dates {stage key: date}).
   b. "Where are you in each subject?": for each subject, chips not started / attending classes / classes done / first reading done / revising / done → subject_status {"stage.subject": status}.
   c. The plan: total_hours, verdict (fits / short), per stage: exam date, hours needed vs capacity_hours, and when short: short_by_hours, needs_weekly_hours, would_fit_by, and options[] as buttons ("Study 22 hours a week", "Aim for after <date>", "Take Group I first"). Phases as a timeline (learning, practice, revision 1, revision 2, study leave). Subjects with hours (learning, reviews, practice, final_revision) and their source ("Hymn's estimate" in grey with "Edit" → estimates {"stage.subject": {class_hours, self_study_hours}}). Facts with source links. Hours a week and study-leave weeks editable (weekly_hours, leave_weeks).
   All edits: PATCH /api/learning/{id} with only what changed; the response is the whole updated journey.
   d. "Start" (enabled when can_start) → POST /api/learning/{id}/accept. A 400 shows the remaining checks.
4. Every day (GET /api/learning/{id}/today): today's sessions in order — revisions first (with "N days late" when overdue_days > 0), then new chapters, then practice/revision. For a revision: show recall questions (GET /api/learning/{id}/chapters/{chapter_key}/questions — question first, tap to reveal the answer; on 503 "Revise from your notes"), then Easy / OK / Hard. "Done" → POST /api/learning/{id}/sessions {kind, chapter_key or subject_key, minutes, date, rating (for revisions)}. Show pace after each.
5. Stop a journey: DELETE /api/learning/{id}.
6. Life tab → Learning card line: "N min today" across active journeys.

Tell me what you changed.
```

## T. Work

```text
Do not modify anything under backend/. Do not change the backend URL in frontend/src/lib/api.ts.

Build Work (Life tab → Work). Its message: work pays for the life you want and grows you, without eating everything else.
1. Roles (GET /api/work/roles): each role with type, organisation, title, planned hours a week, commute hours a week. Add / edit (POST /api/work/roles, PATCH /api/work/roles/{id}): type, organisation, title, started_on, work days, start/end time, office days (for commute), commute minutes each way, next appraisal date, and — only for salaried / articleship — leave types (key earned/casual/sick/other, label, per year, carried forward, carry-forward limit, leave year starts MM-DD). "I left this job" → PATCH {ended_on}. Show only the parts in the role's features {leave, appraisal, payslips, wins, time}.
2. This week (GET /api/work/week): summary BIG ("Work stayed in its box this week." / "Work ran 5.5 hours over plan, family time was down 3 hours."), work planned vs actual, commute, family hours vs last week, sleep and stress averages when present. Quick buttons to log today: "+30m", "+1h", "+2h", "Left 1h early", "Half day" → POST /api/work/days {role_id, date, extra_minutes (30, 60, 120, −60, −240)}.
3. Leave (employed roles): balances from the role's leave[] (type, left, taken, planned; "N days expire on <year_ends>" when expiring). Book leave: POST /api/work/leave {role_id, type, from, to, half_day, days (optional override), reason} → show the balance and the warning if any. Cancel: DELETE /api/work/leave/{id}.
4. Wins: one-line "Something went well" box → POST /api/work/wins {role_id, date, text}; list; delete. Appraisal pack (GET /api/work/roles/{id}/appraisal-pack): wins by month and learning hours, with a share button.
5. Payslips (salaried, Premium; 403 → "Premium feature"): upload a PDF (with optional password) or photo → POST /api/work/payslips/read {file_base64, media_type, password}. Show earnings and deductions (each deduction with its kind: PF, income tax, professional tax, health insurance, other — editable), gross, net, employer PF, and problems[] in amber. "Save" → POST /api/work/payslips {role_id, month, earnings, deductions, gross, net, employer_pf, pf_account_id (pick the EPF account if there is one)} → show recorded_in_money_book. 400 shows what doesn't add up; 409 "That month is already saved". List: GET /api/work/payslips.
6. Life tab → Work card line: the week's summary.

Tell me what you changed.
```

## U. Optional polish: statement review

```text
Do not modify anything under backend/. Do not change the backend URL in frontend/src/lib/api.ts.

Statement review screen: (1) "Accept all guesses" accepts every line's current suggestion except confidence = new, then shows the confirm summary; (2) "Select" mode to set the same kind/category on several lines; (3) a search box on statement detail filtering lines by description or amount; (4) the category picker uses the two-level tree from GET /api/ledger/categories (groups, then categories).

Tell me what you changed.
```

---

## After the last prompt

- Tell Claude; it will check the whole app against the backend and copy `frontend/` into `main`.
- Then switch on `HYMN_REQUIRE_CHECKIN_DURATION=1` in Railway (prompt B made time required in the app).
- The published tester build is your one free Emergent publish. Push notifications and watch sync need the native build with Firebase, so plan that before inviting testers.
