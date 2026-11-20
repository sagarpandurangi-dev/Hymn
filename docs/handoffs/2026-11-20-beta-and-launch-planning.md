# Handoff: Hymn beta and launch planning

Prepared 20 Nov 2026 by Claude Code (the session that builds Hymn's server) for a planning chat. That chat
plans the tester beta and the public launch with the owner; it does not write code. Anything that needs code
goes back to the Claude Code session as a short request.

## 0. How to work with the owner

- The owner (Sagar) is **not a developer**. Plain language, conclusion first, short. One recommendation, not a
  survey of options.
- **Never ask for passwords, keys or tokens in chat.** Railway variables are typed by the owner in Railway.
- Decisions already made (section 5) are settled; don't reopen them unless the owner does.
- When something is unverified (prices, policies, laws), say so and say how to check it.

## 1. What Hymn is

A personal life copilot: *"Hymn helps you follow through on your life."* Five areas — **Money, Health, Family &
Relationships, Learning, Work** — plus a hidden "Soul" area (untracked time and money, shown only when it passes
30%). Plans of any size (45 minutes of guitar this week → a house, a wedding, a child) are checked honestly
against the person's real free time and real money, then turned into tasks, savings and reminders.

Brand: a **double danda ॥** (how Sanskrit verses end) that doubles as the letter H; Gemini drew the logo and merch;
font shortlist made (Outfit closest to the logo; not yet chosen). India first: rupees, Indian foods, Indian tax
and loan rules, IST.

## 2. How it's built and run

| Part | Who / what |
|---|---|
| Server (all logic, AI, data) | Claude Code, in GitHub `sagarpandurangi-dev/Hymn`, folder `backend/` (Python FastAPI). Every change has automated tests; ~1,100 tests run on each change. |
| App screens | **Emergent** (an AI app builder; Expo / React Native). Works from ready-made prompts Claude Code writes. Credits renew around the **17th–18th of each month** and ran out on 19 Nov. |
| Hosting | **Railway** (Singapore), auto-deploys `main`. Live server: `https://hymn-production-4828.up.railway.app` |
| Database | **MongoDB Atlas** (Mumbai); daily backup on; a test restore is still to do |
| AI | Anthropic Claude: Haiku 5.5 for cheap reading/sorting, Opus 5.5 for planning; all through one metered client |
| Admin page | `https://hymn-production-4828.up.railway.app/admin` (after PR #55 is merged and `HYMN_ADMIN_EMAILS` is set) |

Process: Claude Code opens a pull request; the owner says "merge it"; Railway deploys. Emergent saves its work to
the `emergent-frontend` branch; Claude Code checks each save against the server and copies the app into `main`.

## 3. What's built

**Server, done and tested:**
- Sign-up / sign-in with security hardening; account export and delete (DPDP); daily AI caps per person.
- Brain dump → tasks, reminders, ideas; daily 2-minute review; weekly patterns.
- Notifications: per-area reminders, quiet hours, **at most 4 a day, one morning summary at 08:30**.
- **Money:** a true double-entry money book (no double counting; transfers and card bills aren't spending); bank
  statement upload with learning suggestions (Premium); planned money and forecast; the three money statements
  (net worth, income & expenditure, cash flow); things you own & owe with lifetime cost, loans (EMI split), fuel
  mileage (Premium); family net worth; investments from CAMS/NSDL statements (Premium); payslips (Premium).
- **Time:** weekly time statements (168 hours: planned vs actual, free time, untracked "Soul").
- **Plans:** the planner chat (finds real free time, checks money month by month, honest verdicts), with
  checklists for house, wedding and first child.
- **Health** (all marked DRAFT until a doctor reviews): consent first, daily 30-second log, six domains with no
  overall score, red flags first (112, Tele-MANAS 14416), food log with photo recognition (portions first,
  calories as a range), habits to change (no streaks), check-ups, lab report reading, 90-day report, doctor
  summary, looking after a parent (caregiver mode), watch sync (server side).
- **Family & Relationships:** people, birthdays, gentle "might like to hear from you", moments, gift budgets.
- **Learning journeys** for any goal (CA, CFA, boards, driving, a language): researched structure, spaced
  revision, daily sessions, recall questions.
- **Work:** roles, hours and commute, "work stayed in its box", leave balances, wins and appraisal pack, payslips.
- **Pamphlet ID:** a permanent 7-character ID per person, meant to be shared with the owner's other app Pamphlet.
- **WhatsApp task capture:** forward or type a message → a task with one confirm tap → reminder → "done". Built
  to Meta's and India's rules; **switched off until Meta approves** a number (section 6, WhatsApp).
- **Admin page:** usage per feature, who's active and who comes back, AI cost in ₹ per person and feature,
  monthly AI budget (warning ₹5,000, automatic pause at ₹10,000), on/off switches per AI feature, Premium /
  pause / delete per person, invite codes, error log. Counts and costs only — never content; Health never shown
  per person. (PR #55, waiting for "merge it".)
- **Beta invites:** invite-only mode with a cap (200), each person gets their own code to share (5 uses), and
  their friends get codes too. **Off until the app's sign-up has an invite box** (prompt R).

**App screens (Emergent):** prompts **A–M are built** — fixes, check-in time, Life tab, welcome wizard, Me screen
(notifications, download data, delete account), planned money, the three statements, recent activity and
investment upload, My week, things I own & owe, family net worth, the new planner, Health part 1.

**Still to build in the app — prompts N–R** (when Emergent credits renew, ~17–18 Dec): N Health food + habits;
O check-ups, labs, doctor summary, people I look after; P Family & Relationships; Q Learning; R Work, plus the
notification limit settings, Me → WhatsApp, the sign-up invite box, "Invite friends", and the app version header.
The prompts are written and ready (a copy-button page exists).

## 4. Existing beta plan (`docs/BETA_TEST_PLAN.md`, written 16 Nov)

- **Testers:** 10–15 people the owner knows, deliberately mixed (salaried and self-employed; with and without a
  watch; careful and careless with money; a student; someone looking after a parent). Android first.
- **Give each:** the app, Premium (now done from the admin page, no Railway edit needed), one place to report
  (WhatsApp group or a form: what you did / expected / happened / screenshot).
- **Day 1** (~20 min): sign up, setup checklist, brain dump, one small and one big plan, allow notifications.
- **Days 2–7** (5 min a day): reminders and evening review, money (log or statement upload), check-ins with time,
  Health log and a food photo (if opted in), one moment with someone, "stayed late" at work.
- **Week 2:** the statements, a learning journey, a payslip or investment statement, a habit and the urge button,
  try to break it, download data, one tester deletes their account.
- **Targets:** 8 in 10 finish setup on day 1; half open it on 5 of the first 7 days; any wrong money or time
  number is top priority; quote any nagging/scary message exactly; any screen slower than 3 seconds.
- **Bug priorities:** (1) someone sees another's data, money wrong, data lost, can't sign in; (2) a feature
  broken, a reminder at the wrong time, the AI states something false; (3) words, layout, wishes.
- **After two weeks:** a 15-minute call with each tester (kept / stopped / would pay for), then widen or change.
- The admin page now measures most of these targets directly (setup, coming back, features used, errors).

Suggested shape (from the WhatsApp handoff and the invite system): **phase 1** the 10–15 known testers; **phase 2**
widen through invite codes to at most 200 for about 4 weeks.

## 5. Decisions already made

- Finance is a true ledger; transfers and card bills aren't spending; cash and accrual views.
- A car is an asset depreciated straight-line; fuel cost spread between fills from odometer + price per litre.
- EMIs split into principal and interest (from the loan document, or principal, rate, tenure, method).
- Statement upload is Premium; free users type opening balances.
- Matching learns from the person's choices.
- **Emergent gives one free publish; that publish must be the tester beta.** Push notifications need a native
  build with Firebase before the beta.
- Health goes to testers marked "draft — not yet reviewed by a doctor".
- MongoDB daily backup is on; a test restore is still to do.
- The owner chose not to rotate the database password and AI key (checked where they were exposed). Don't raise it.
- AI budget: warning ₹5,000, pause at ₹10,000 a month (changeable on the admin page). Admin: only the owner.
- Invite-only beta, cap 200; people who join may invite others.
- Subscriptions: will be needed; RevenueCat for the app stores is acceptable; the owner will set up the accounts
  closer to the beta (section 6).
- Later, not now: an "intent marketplace" with the owner's vendor app (needs legal review); a Pamphlet ID shop.

## 6. Open items before the beta and before the public launch

### A. Owner actions with no code involved
| Item | Why | Notes |
|---|---|---|
| Merge PR #55, then add Railway variable `HYMN_ADMIN_EMAILS` = owner's login email | Admin page | Until then the page refuses everyone |
| Delete Emergent's test account (qa.tester@hymn.app) | Clean data | From the admin page → People |
| Test-restore the Atlas backup into a scratch database | Know backups work | 15 minutes |
| Delete the 10 old GitHub branches | Tidiness | List in `docs/audits/old-branches-2026-11-16.txt` |
| Choose the brand font | Website, app, merch | Outfit is closest to the logo |
| Try the new screens with a Premium account and report anything wrong | Emergent only tested with a non-Premium test account and sample data | Especially things I own & owe, investment upload, the planner |

### B. Company, legal, policies (blocks payments, WhatsApp, store listings)
| Item | Notes |
|---|---|
| G0: employer's position on a side business | First, before anything public |
| G1: legal entity, business address, bank account | Needed by Razorpay, Google, Apple, Meta (names and addresses must match everywhere) |
| Privacy policy and terms | Must name every processor: Anthropic (AI), Meta (WhatsApp), MongoDB (database), Railway (server), Google/Expo (notifications), RevenueCat/Razorpay (payments, later). Cross-border processing, retention (WhatsApp raw text 7 days; AI call detail 90 days; error log 30 days), that usage per feature and AI cost per account are recorded, deletion and export. DPDP review by a lawyer before public launch. |
| Doctor sign-off of Health rules; nutritionist sign-off of food values | Before Health loses its "draft" label (public launch) |
| Penetration test | Before public launch |

### C. Website (Claude Code builds it, no Emergent credits)
- Needed for Meta verification, Play Store and App Store (privacy policy page, and Google's web account-deletion
  page), DPDP, WhatsApp support contact, and the beta "join" form.
- Pages: home (॥, the five areas, join the beta), privacy policy, terms, support/contact, delete my account,
  WhatsApp explainer. A home page preview will be shown first.
- **Owner:** buy a domain (~₹800–1,500 a year); a support email on it (Zoho free plan); the business name and
  address to show; best Gemini images; a few lines in the owner's own words on why Hymn exists.

### D. The app build and stores
- The Emergent publish (the one free one) = the tester beta. Push notifications and watch sync need the **native
  build with Firebase**; plan it before inviting testers.
- Google Play developer account (~$25 once), Apple developer account (~$99 a year) if iPhone is in scope.
- After prompt R ships: switch on `HYMN_REQUIRE_CHECKIN_DURATION=1` in Railway, and switch on invite-only on the
  admin page.
- Store listings: screenshots, description, privacy answers (data safety form).

### E. Subscriptions (Premium)
- Plan: **website payments via Razorpay** (UPI AutoPay, cards; ~2% fee) and **in-app via Google Play / Apple through
  RevenueCat** (free at small revenue, then a small share — verify current pricing). Store fees on in-app
  subscriptions are often quoted at 15% — verify.
- Claude Code will build the server side: subscription record, Premium on/off from payments, grace period,
  trials, promo codes, GST invoices (18% GST on digital services — verify the right treatment with a CA), revenue
  on the admin page.
- **Owner decides:** price (e.g. ₹199 a month / ₹1,499 a year), free trial (e.g. 14 days), and exactly what is
  free vs Premium. Today Premium covers: bank statement upload, payslips, investments upload, things I own &
  owe, more food photos and lab reads, higher daily AI limits.
- **Owner sets up:** Razorpay, Google Play, Apple, RevenueCat accounts (all need the legal entity).

### F. WhatsApp
- **Owner:** Meta Business Verification and display name; a dedicated phone number on the Cloud API with a two-step
  PIN; submit 3 Utility templates (wording in `docs/WHATSAPP_API.md`); then Claude Code guides adding 5 Railway
  variables and the webhook.
- Re-check before launch: WhatsApp India rates (₹0.145 per utility message from Oct 2026 was from second-hand
  sources), Anthropic's data retention terms, whether reactions are billable.
- Closed beta ≤ 200 users for 4 weeks; Meta's quality rating must stay green.

### G. Not built, decided against for now
- **Reading SMS on Android:** not built. Google Play strictly limits SMS permissions; approval for a money app is
  uncertain and a rejection could hold up the whole listing. Safer: forward bank SMS to Hymn on WhatsApp (can be
  built once WhatsApp is live), statement upload (built), Account Aggregator later (needs a licensed partner).

### H. Security items before the public launch (from the 16 Nov audit)
- Password reset uses only a security question → email/OTP verification (needs an email service).
- Account creation limits → invites cover the beta; verified email for launch.
- App lock (fingerprint/PIN) in the native build; lock the server to the app's web address; library upgrades;
  field-level encryption for health data.

## 7. Money to plan for (rough, verify)

Emergent credits (monthly); Railway; MongoDB Atlas (a paid tier with backups); Anthropic AI (capped at ₹10,000 a
month by the admin page); domain and email; Google Play $25 once / Apple $99 a year; WhatsApp per-message
charges; payment fees (Razorpay ~2%, stores ~15% on subscriptions, RevenueCat later); lawyer (DPDP, policies),
CA (GST), doctor and nutritionist reviews, penetration test.

## 8. Suggested order (for the planning chat to refine with the owner)

1. Now: merge #55, set `HYMN_ADMIN_EMAILS`, test-restore backup, employer check, pick a font, start the company.
2. Domain + website (preview first) + privacy policy draft; start Meta verification once the company and website exist.
3. Subscription decisions (price, trial, free vs Premium); Claude Code builds the server side.
4. ~17–18 Dec: Emergent prompts N–R; Claude Code checks each; copy the app into `main`.
5. Native build with Firebase → the one Emergent publish = tester beta (phase 1, 10–15 people).
6. Two weeks of testing → fix → phase 2 via invites (≤ 200).
7. Public launch gates: email/OTP, doctor and nutritionist sign-offs, DPDP review, penetration test, store
   listings, payments live.

## 9. Where things are (in the GitHub repo)

`CLAUDE.md` (the full technical map), `docs/BETA_TEST_PLAN.md`, `docs/audits/2026-11-16-beta-readiness.md`,
`docs/EMERGENT_PROMPTS.md`, `docs/ADMIN.md`, `docs/WHATSAPP_API.md`, and the API notes in `docs/*_API.md`.
