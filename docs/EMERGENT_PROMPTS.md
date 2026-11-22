# Emergent prompts, A to S (plus 0, the design pass)

Paste **one prompt at a time, in order**. After each one, use **"Save to GitHub"** onto the `emergent-frontend` branch and tell Claude, so it can check the work before the next. Every prompt starts with the same two safety lines: keep them.

**Status (19 Nov 2026):** A–M are built and saved. Next: **0. Design pass** first (added 21 Nov, attach the four mock-up images), then **0b. Movement and feedback**, then N–S (S, Premium, added 21 Nov): the old N–U, merged into five tighter prompts to save credits (old U, statement polish, moved to "Later").

A–B finish the earlier fixes. C lays the groundwork the rest builds on. D–E are the first-time experience and the Me screen. F–L are Money, time and plans. M–O are Health. P–R are Family, Learning and Work.

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

## 0. Design pass (run this first, before N)

```text
Do not modify anything under backend/. Do not change the backend URL in frontend/src/lib/api.ts.
Keep testing light: one quick check per screen with the existing QA account. Don't create new accounts, don't run long test suites, and don't add anything not listed here. Keep every testID.

Give the whole app a new, warmer look. Today it feels like accounting software. I've attached mock-ups of the new Today, Money, Life and My week screens; match them.

1. Fonts: add @expo-google-fonts/outfit (400, 500, 600) and @expo-google-fonts/figtree (400, 500, 600). Load them in app/_layout.tsx with useFonts and keep the splash screen until they're loaded.
2. src/lib/theme.ts — keep every existing key so screens keep working, change the values:
   colors: surface #FAF7F1, onSurface #1F2340, surfaceSecondary #FFFFFF, onSurfaceSecondary #6B7180, surfaceTertiary #F1ECE3, onSurfaceTertiary #A3A7B0, surfaceInverse #1F2340, onSurfaceInverse #FAF7F1, brand #1F2340, brandPrimary #1F2340, onBrandPrimary #FFFFFF, brandSecondary #E0812A, brandTertiary #FBEBDB, onBrandTertiary #7A3E0C, success #5E7B63, warning #C9822B, error #B5483B, border #ECE6DB, borderStrong #DDD5C8, divider #ECE6DB; add accent #E0812A, accentSoft #FBEBDB, successSoft #E4ECE3.
   fonts: display Outfit_500Medium, displayLight Outfit_400Regular, displayBold Outfit_600SemiBold, body Figtree_400Regular, bodyMedium Figtree_500Medium, bodyBold Figtree_600SemiBold.
   Add a type scale (only these six): display 34/40 Outfit 400, title 26/32 Outfit 500, heading 20/26 Outfit 500, body 16/24 Figtree, small 14/20 Figtree, label 12/16 Figtree 600 uppercase letter-spacing 1. Spacing: keep the scale, side gutter 20. Radius: card 18, button 14.
3. Add src/components/ui/: Text (variants display, title, heading, body, small, label; default body), Card (white, radius 18, soft shadow; variants highlight = accentSoft, good = successSoft), ListRow (plain row, hairline divider, left text + optional right value), SectionLabel. Then across app/ and src/: remove every fontFamily "Georgia"/"System", and replace every fontSize literal with the nearest type style (10–12 → label or small, 13–15 → small, 16–17 → body, 18–22 → heading, 24–28 → title, 32+ → display). No new sizes or colours anywhere.
4. Add src/lib/format.ts and use it wherever money, dates or durations are shown:
   - formatMoney: ₹12,450 (Indian grouping), ₹1.84 L from 1 lakh, ₹2.5 Cr from 1 crore; no ".00"; never "INR" before rupee amounts; other currencies "USD 1,250"; incoming "+ ₹1.1 L".
   - formatDay: Today / Tomorrow / Yesterday, a weekday within the coming week, else "24 Nov" (year only if not this year). Never show YYYY-MM-DD.
   - formatDuration: "45 min", "3h", "3h 20m".
5. Layout everywhere: screen titles left-aligned with no full stop ("Today", not "Today."); sections are a SectionLabel and plain ListRows on the paper background, not a grey box per section; Card only for things that stand apart; hide rows whose value is zero; empty states are one friendly line plus a button, never a table of zeros. The + button and primary buttons use ink #1F2340.
6. Today (app/(tabs)/today.tsx) — rebuild from GET /api/screens/today (one call):
   - date_label as label; greeting in title size followed by " ॥" in accent.
   - "Your 3 things": things[] as rows with a rounded checkbox; tapping an open one → PUT /api/tasks/{task_id} {"status": "done"}, then it shows a sage tick and a faint strikethrough; note in small soft text on the right; if more_things > 0 a "+N more" link to the tasks list. If things is empty: "Nothing due today." with an Add button.
   - highlight (when not null): a highlight Card with when (small, soft), title (heading), detail (small); tap → its screen (people → Family & Relationships, finance/planned → Planned money).
   - Two small Cards side by side: "Free {free_time.when}" with free_time.label, and "Left to spend" with money.label (hide either when null).
   - review (when not null): one row "Daily review · {open} waiting" → the review screen.
   - setup (when not null): one slim row "Finish setting up · {done} of {of}" → next.screen (same screen keys as before).
   - Remove the My week, Daily review, Planning and Required Check-ins cards from Today (those screens stay reachable from their tabs and Life).
7. Life tab — from GET /api/screens/life: a two-column grid of Cards, Plans full width at the end. Each: a small rounded icon tile in a soft tint (Health sage, Family saffron soft, Learning #E6E8F3, Work #F1E9DE, Plans saffron soft), title (heading), line (small, soft). status "attention" adds a small saffron dot; status "setup" shows the line in accent as an invitation. Tap → its screen.
8. Finance tab (rename the tab and title to "Money") — top part from the headline in GET /api/screens/finance: label "You're worth", net_worth_label in display size; a Card "Free to spend this month" with left_to_spend_label; "Coming up": coming_up as ListRows (title with when underneath in small soft, amount_label on the right; direction "in" in sage). The existing sections stay below with the new look, zero rows hidden, and these words: Liquid → Ready to use, Semi-liquid → Takes a few days, Illiquid → Long-term, Recurring income → Comes in every month, Recurring expenses → Goes out every month.
9. My week: a one-sentence summary at the top in heading size (e.g. "Work ran 3 hours over this week." from the existing numbers), then each area as a simple horizontal bar of actual hours with a thin mark for planned; the existing tables move under "See the full 168 hours".
10. Words: "Required Check-ins" → "Check-ins due"; anywhere a status code shows (todo, pending_account_assignment, on_track), show plain words instead.
11. Small touches: the checkbox tick animates (150 ms); cards fade in once on load; nothing moves when the phone's "reduce motion" is on.

Tell me what you changed.
```

## 0b. Movement and feedback (run right after 0)

```text
Do not modify anything under backend/. Do not change the backend URL in frontend/src/lib/api.ts.
Keep testing light: one quick check per screen with the existing QA account. Don't create new accounts, don't run long test suites, and don't add anything not listed here. Keep every testID.

Make the app respond to every touch. Today taps do nothing visible and screens just appear. Use react-native-reanimated (already a dependency) and add expo-haptics. Put the pieces in src/components/ui so every screen uses the same ones.

1. Tap: a Tap wrapper (replaces bare TouchableOpacity/Pressable for rows, cards and buttons): presses down to scale 0.97 in 120 ms and springs back. A haptics helper: light impact for ticking a task, primary buttons and switches; success notification when something is finished; error notification with a gentle horizontal shake of the field when a form has a problem (show the server's message under it). A "Vibration on taps" switch in Me → Settings (on by default, remembered in AsyncStorage).
2. Loading: a Skeleton component (soft shimmering blocks in border #ECE6DB / paper #F7F3EC). Every screen's first load shows skeleton blocks shaped like its content instead of a spinner or a blank screen. Every list and the Today, Money and Life screens pull down to refresh (RefreshControl tinted ink #1F2340).
3. Saving: a Button component with a loading state: small spinner + action word ("Adding…", "Saving…", "Deleting…"), disabled until done.
4. Arrival: cards and list rows fade in and rise 8 px, staggered 50 ms, on a screen's first load only. Numbers in display or title size (money, hours) count up over 600 ms. Progress bars and meters fill from zero over 800 ms.
5. Screens: stack screens slide in from the side (native stack defaults); tab switches cross-fade in 150 ms; pickers and add forms open as bottom sheets that spring up, with a dim backdrop that closes them on tap.
6. Today's 3 things: tapping an open one → the checkbox fills sage with a small spring (scale 1.15 then back), the tick draws, the title fades and strikes through; after 650 ms the row fades and slides out and the next task (if any) slides in; a toast says "Nice. N left today." When all are done: "All done for today ॥" with a small bounce of the ॥ and a success buzz.
7. Toasts: a ToastHost upgrade — slide down from the top, ink background, white text, auto-hide after 2.5 s; for deletes show "Undo" (re-creates the item) when the API allows.
8. The + button rotates into × while the add sheet is open.
9. Everything is quick (under 300 ms, ease-out; springs damping ~15, no repeated wobble). When the phone has "reduce motion" on, keep fades and drop movement and count-ups.

Tell me what you changed.
```

## N. Health 2: food log and habits to change

```text
Do not modify anything under backend/. Do not change the backend URL in frontend/src/lib/api.ts.
Keep testing light: one quick check per screen with the existing QA account. Don't create new accounts, don't run long test suites, and don't add anything not listed here.
Use the design pass: Text / Card / ListRow / SectionLabel from src/components/ui and formatMoney / formatDay / formatDuration from src/lib/format.ts; no new font sizes or colours.

Add two parts to Health (both need health consent). Tone: supportive, never shaming; no streaks anywhere.

FOOD
1. Today's food (GET /api/food/day?date=YYYY-MM-DD): meals (breakfast, lunch, dinner, snack) with their items. Totals with PORTIONS FIRST (fruit & veg, protein, sweets, outside/fried meals), then calories as a range: "about 1,200 (1,000–1,450)" from totals.calories {estimate, low, high} with its note in grey. If totals.calories is null, show portions only and never mention calories. <DraftNote text="Food values are typical, pending a nutritionist's review"/> when values_reviewed is false.
2. Add a meal: meal type, "Eaten out / ordered in" switch, then items by
   a. Search (GET /api/food/search?q=): name and unit ("1 katori"); − / + in halves. My foods appear in the results.
   b. Photo (upload helper, images resized) → POST /api/food/photo {image_base64, media_type}. kind "plate": a line per item with seen_as, the matched food (or "Not sure — search"), amount − / +, "?" when confidence is low, "Change" from alternatives or search. kind "label": prefill "Save as my food". kind "not_food": "That doesn't look like food." Show photos_left small. 429 → server message; 503 → "Couldn't read the photo — search instead."
   c. "Something else": a typed name (saved, not counted).
   Save: POST /api/food/meals {date, meal, outside, from_photo, items: [{food_id, amount} | {name}]}. Delete: DELETE /api/food/meals/{id}.
3. My foods: list (GET /api/food/my-foods), add (POST /api/food/my-foods {name, unit, kcal, protein_g, carbs_g, fat_g, fibre_g, veg_fruit_portions, protein_servings, sugary, fried}), delete.

HABITS TO CHANGE
4. List (GET /api/habits): reason ("For: <serves.title or for_what>"), "N of the last M days on track" (progress.days_on_track / days_logged), money_freed and hours_freed when present.
5. Add (POST /api/habits): kind from GET /api/habits/kinds (with its label), goal quit or cut down (only the goals the kind allows), baseline_per_day, target (cut down), cost per unit (optional), "What life is this for?" (for_what, or pick a plan → serves_plan_id), private switch (on by default for "other"). After saving show the support text (helpline numbers tappable).
6. Habit screen (GET /api/habits/{id}): big "I'm having an urge" button → POST /api/habits/{id}/urge {date, trigger (optional chips: stress, after a meal, with friends, bored, tired)} → show your_reason BIG, then try_this[] and the note. Daily "How much today?" (0 = a clean day) with trigger chips → POST /api/habits/{id}/log {date, amount, triggers[]}. Show progress.welcome_back, top_triggers and steady_the_edge when present. "Send what I save to my dream" (when it has a cost and a plan) → POST /api/habits/{id}/dream-fund. Delete: DELETE /api/habits/{id}.

Tell me what you changed.
```

## O. Health 3: check-ups, lab reports, reports for the doctor, people I look after

```text
Do not modify anything under backend/. Do not change the backend URL in frontend/src/lib/api.ts.
Keep testing light: one quick check per screen with the existing QA account. Don't create new accounts, don't run long test suites, and don't add anything not listed here.
Use the design pass: Text / Card / ListRow / SectionLabel from src/components/ui and formatMoney / formatDay / formatDuration from src/lib/format.ts; no new font sizes or colours.

Show <DraftNote/> wherever rules_reviewed is false.
1. Check-ups (GET /api/health/checkups): overdue first, then never done, due soon, OK: label, why, last done, next due, "Ask your doctor" tag when ask_doctor. "Done" → date → POST /api/health/checkups/{key}/done {date}. If missing_profile is not empty: "Add your date of birth and sex for a better list."
2. Lab reports (optional, never nagged): upload a PDF or photo → POST /api/health/labs/read {file_base64, media_type}. Each result as printed (test, value, unit, range, flag); for tracked ones also hymn_value + hymn_unit and a status dot; a warning on lines with check. "Save" → POST /api/health/labs {report_date, lab, results}. List (GET /api/health/labs), delete (DELETE /api/health/labs/{id}). 429 → server message; 503 → "Couldn't read it — you can type values in."
3. 90-day report (GET /api/health/progress): "Day N of 90" until complete; lines with before → after and better (green) / worse (amber) / steady / changed (weight: no colour, no praise or blame).
4. Doctor summary (GET /api/health/doctor-summary): a clean one-page view of its sections. "Share as text" (?format=text → share sheet), a switch "Include private habits" (include_private=true), and editing "My questions for the doctor" (profile doctor_questions, up to 10).
5. People I look after (Health → "People I look after"): list (GET /api/care: name, relation, a dot when checkups_due > 0). Add (POST /api/care {name, relation: mother|father|parent_in_law|grandparent|spouse|child|sibling|other, their_consent: true}) with a required checkbox "They know and agree, or I'm their guardian". Rename (PATCH /api/care/{id} {name}); remove (DELETE /api/care/{id}; confirm "This deletes all their health data").
6. A person switcher at the top of Health: "Me" or a person I look after. For a person, every call for profile, measurements, daily log, dashboard, suggestions, check-ups, labs, 90-day report and doctor summary adds ?for=<their id>; hide food and habits for them; titles say whose ("Amma's health").
7. Health settings: a switch "Use my health in plans" (profile use_in_planner) with "The planner sees a short summary — never your logs, lab values or symptoms." (save the full profile with PUT /api/health/profile), and a line "Watch and phone sync is coming in the next app update."

Tell me what you changed.
```

## P. Family & Relationships

```text
Do not modify anything under backend/. Do not change the backend URL in frontend/src/lib/api.ts.
Keep testing light: one quick check per screen with the existing QA account. Don't create new accounts, don't run long test suites, and don't add anything not listed here.
Use the design pass: Text / Card / ListRow / SectionLabel from src/components/ui and formatMoney / formatDay / formatDuration from src/lib/format.ts; no new font sizes or colours.

Build Family & Relationships (Life tab). Gentle by design: never "overdue", no streaks.
1. Home (GET /api/people/summary): hours with your inner circle this month, people reached, "Might like to hear from you" (up to 3, "It's been N days"), "Coming up" ("Amma's birthday · Friday · turns 70"). Below it, people (GET /api/people) grouped Inner circle / Close / Wider, each with relation, last together ("3 days ago"), a soft dot when might_like_to_hear_from_you, and next_day.
2. Add / edit a person (POST /api/people, PATCH /api/people/{id}): name, relation (mother, father, spouse, partner, child, sibling, grandparent, grandchild, parent_in_law, relative, friend, mentor, colleague, neighbour, other), circle (inner/close/wider), birthday (day + month, optional year → "MM-DD" or "YYYY-MM-DD"), birthday gift budget (birthday_gift), other days (occasions: label, date, gift_budget), "Keep in touch every N days" (keep_in_touch_days; 0 = don't remind), private notes, optional link to a person I look after (care_id from GET /api/care). Delete: DELETE /api/people/{id}.
3. Person screen (GET /api/people/{id}): details, next day, recent moments.
4. Log a moment: quick buttons Called, Video call, Met, Meal, Messaged, Helped; time chips 15m / 30m / 1h / 2h+; optional note; several people allowed. POST /api/people/moments {person_ids[], date, kind: call|video_call|visit|meal|outing|message|help|celebration|other, minutes, note}. Delete: DELETE /api/people/moments/{id}.
5. Life tab → Family card line: the first of might_like_to_hear_from_you or coming_up.

Tell me what you changed.
```

## Q. Learning journeys

```text
Do not modify anything under backend/. Do not change the backend URL in frontend/src/lib/api.ts.
Keep testing light: one quick check per screen with the existing QA account. Don't create new accounts, don't run long test suites, and don't add anything not listed here.
Use the design pass: Text / Card / ListRow / SectionLabel from src/components/ui and formatMoney / formatDay / formatDuration from src/lib/format.ts; no new font sizes or colours.

Build Learning (Life tab → Learning; the old Knowledge screen stays reachable as "Older learning goals").
1. List (GET /api/learning): title, status, pace (on_track / behind by N h / ahead), today_minutes. Button "Start learning something".
2. Start: "What do you want to learn or pass?" → POST /api/learning {goal} → questions[] {key, question, options[]}, asked one at a time (chips when options exist, else a text box) → POST /api/learning/{id}/answers {answers: {key: value}}. This takes up to a minute: show "Checking the facts…".
3. Review before starting (the journey response). All edits: PATCH /api/learning/{id} with only what changed; the response is the whole journey.
   a. checks[] FIRST: "confirm" → "Looks right" (adds its key to confirmed) or pick an option (fact_choices {fact key without "fact:": value}); "error" → must be fixed (e.g. exam date picker → stage_dates {stage key: date}).
   b. "Where are you in each subject?": chips not started / attending classes / classes done / first reading done / revising / done → subject_status {"stage.subject": status}.
   c. The plan: total_hours, verdict (fits / short); per stage: exam date, hours needed vs capacity_hours; when short: short_by_hours, needs_weekly_hours, would_fit_by and options[] as buttons. Phases as a simple timeline. Subjects with hours and their source ("Hymn's estimate" in grey with "Edit" → estimates {"stage.subject": {class_hours, self_study_hours}}). Facts with source links. Editable weekly_hours and leave_weeks.
   d. "Start" (when can_start) → POST /api/learning/{id}/accept; a 400 shows the remaining checks.
4. Today (GET /api/learning/{id}/today): sessions in order — revisions first ("N days late" when overdue_days > 0), then new chapters, then practice. For a revision: recall questions (GET /api/learning/{id}/chapters/{chapter_key}/questions — question first, tap to reveal; on 503 "Revise from your notes"), then Easy / OK / Hard. "Done" → POST /api/learning/{id}/sessions {kind, chapter_key or subject_key, minutes, date, rating (revisions)}. Show pace after.
5. Stop a journey: DELETE /api/learning/{id}.
6. Life tab → Learning card line: "N min today" across active journeys.

Tell me what you changed.
```

## R. Work, and one Finance fix

```text
Do not modify anything under backend/. Do not change the backend URL in frontend/src/lib/api.ts.
Keep testing light: one quick check per screen with the existing QA account. Don't create new accounts, don't run long test suites, and don't add anything not listed here.
Use the design pass: Text / Card / ListRow / SectionLabel from src/components/ui and formatMoney / formatDay / formatDuration from src/lib/format.ts; no new font sizes or colours.

Build Work (Life tab → Work): work pays for the life you want and grows you, without eating everything else.
1. Roles (GET /api/work/roles): type, organisation, title, planned hours a week, commute hours a week. Add / edit (POST /api/work/roles, PATCH /api/work/roles/{id}): type, organisation, title, started_on, work days, start/end time, office days, commute minutes each way, next appraisal date, and — only for salaried / articleship — leave types (key earned/casual/sick/other, label, per year, carried forward, carry-forward limit, leave year starts MM-DD). "I left this job" → PATCH {ended_on}. Show only the parts in the role's features {leave, appraisal, payslips, wins, time}.
2. This week (GET /api/work/week): the summary BIG ("Work stayed in its box this week."), work planned vs actual, commute, family hours vs last week, sleep and stress when present. Quick buttons for today: "+30m", "+1h", "+2h", "Left 1h early", "Half day" → POST /api/work/days {role_id, date, extra_minutes (30, 60, 120, −60, −240)}.
3. Leave (employed roles): balances from the role's leave[] (type, left, taken, planned; "N days expire on <year_ends>"). Book: POST /api/work/leave {role_id, type, from, to, half_day, reason} → show the balance and any warning. Cancel: DELETE /api/work/leave/{id}.
4. Wins: "Something went well" box → POST /api/work/wins {role_id, date, text}; list; delete. Appraisal pack (GET /api/work/roles/{id}/appraisal-pack) with a share button.
5. Payslips (salaried, Premium; 403 → "Premium feature"): upload PDF (optional password) or photo → POST /api/work/payslips/read {file_base64, media_type, password}. Show earnings and deductions (each with its kind, editable), gross, net, employer PF, problems[] in amber. "Save" → POST /api/work/payslips {role_id, month, earnings, deductions, gross, net, employer_pf, pf_account_id (the EPF account if any)} → show recorded_in_money_book. 400 shows what doesn't add up; 409 "That month is already saved". List: GET /api/work/payslips.
6. Life tab → Work card line: the week's summary.
7. Finance fix: the "Pending account → Assign" shortcut should open the events list filtered with GET /api/finance/events?lifecycle_status=pending_account_assignment.
8. Me → Notifications: add "At most [N] notifications a day" (limits.daily_max, 1–20) and a "Morning summary" switch with its time (limits.morning_brief, limits.brief_time) through PUT /api/nudges/settings {"limits": {...}}. A push with data.screen "nudges" opens the notifications feed.
9. Me → WhatsApp (show only when GET /api/whatsapp returns available: true): if not linked, the consent_text with a checkbox and "Connect WhatsApp" → POST /api/whatsapp/link {"consent": true} → open the returned url (it opens WhatsApp with the code typed in; the person taps send). If linked: the number, a "Pause messages" switch (POST /api/whatsapp/pause {"paused": true|false}) and "Disconnect" (DELETE /api/whatsapp/link).
10. Invites: on the sign-up screen add an optional "Invite code" box sent as invite_code with POST /api/auth/signup (a 403 shows the server's message). Me → "Invite friends": GET /api/invites/mine → show the code big with a copy and share button and "N invites left".
11. On every API call send the header X-App-Version with the app's version (from app.json).

Tell me what you changed.
```

## S. Premium

```text
Do not modify anything under backend/. Do not change the backend URL in frontend/src/lib/api.ts.
Keep testing light: one quick check per screen with the existing QA account. Don't create new accounts, don't run long test suites, and don't add anything not listed here.
Use the design pass: Text / Card / ListRow / SectionLabel from src/components/ui and formatMoney / formatDay / formatDuration from src/lib/format.ts; no new font sizes or colours.

Add Premium to the app.
1. Me → "Premium" (GET /api/billing): the plan in one line — "Premium · free trial, 9 days left" (in_trial, trial_days_left), "Premium · beta pass", "Premium · renews 12 Jan" (subscription.renews_on), "Premium · ends 12 Jan" (subscription.ends_on), or "Free". "Founding member" tag when founding_member is true.
2. The Premium screen (GET /api/billing/plans, no sign-in needed): a calm comparison — the limits table (name, free, premium; empty premium = "No limit") and the Premium-only list ("Reading statements, investments and payslips", "Things I own & owe"). Prices: ₹monthly a month, ₹yearly a year ("save N%"); founding members see prices.founding_yearly from GET /api/billing instead of the yearly price, with "Founding member price for your first year". A line "Try every Premium feature free for {trial_days} days" for people who never had a trial. Never pushy; a clear "Not now".
3. Buying (website payments for now): when can_buy_on_web is true, "Get Premium monthly / yearly" → POST /api/billing/checkout {plan} → open short_url in the browser (expo-web-browser). When the browser closes, reload GET /api/billing. 409 → "You already have Premium". 503 → "Payments are coming soon." When can_buy_on_web is false, show the prices with "Coming soon".
4. Cancel (only when subscription.provider is "razorpay" and there's no ends_on): "Cancel Premium" → confirm → POST /api/billing/cancel → show its detail. For store subscriptions show "Manage in Google Play / the App Store".
5. "Have a code?" → POST /api/billing/redeem {code} → show its detail; 400 shows the server's message.
6. Anywhere the server answers 403 with a detail that mentions Premium, show that message with a "See Premium" button to this screen.
7. Today: a small line while in_trial: "Premium trial: N days left" → the Premium screen.

Tell me what you changed.
```

## Later: in-app purchases (with the native build)

When the native build exists: install react-native-purchases (RevenueCat), configure it with the RevenueCat public SDK keys, call Purchases.logIn(<the Hymn user id from GET /api/auth/me>) after sign-in, show the "premium" offering's monthly and yearly packages on the Premium screen instead of the website buttons on Android/iPhone, buy with Purchases.purchasePackage, then reload GET /api/billing (the server learns about the purchase from RevenueCat). "Restore purchases" → Purchases.restorePurchases.

---

## Later (after the beta, only if wanted)

Statement review polish: "Accept all guesses" (except confidence = new), "Select" mode to set one kind/category on several lines, a search box on statement detail, and the two-level category picker from GET /api/ledger/categories.

---

## After the last prompt

- Tell Claude; it will check the whole app against the backend and copy `frontend/` into `main`.
- Then switch on `HYMN_REQUIRE_CHECKIN_DURATION=1` in Railway (prompt B made time required in the app).
- The published tester build is your one free Emergent publish. Push notifications and watch sync need the native build with Firebase, so plan that before inviting testers.
