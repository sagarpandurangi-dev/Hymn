# Beta readiness check (16 Nov 2026)

Four parts: security review, database backups, first-time setup, and the tester plan (`docs/BETA_TEST_PLAN.md`).

## 1. Security review

### Fixed in this change
| Finding | Risk | Fix |
|---|---|---|
| The interactive API docs page (`/docs`, `/openapi.json`) was public on the live server | Anyone could read the full list of 287 endpoints | Off in production; still on in test and preview |
| No limit on AI calls per person | One account (or a stolen login) could run up the AI bill: the planner and learning setup use the expensive model with web search | Daily caps per person (`ai_budget.py`): expensive 15 a day (Premium 60), cheap 100 (Premium 300); adjustable in Railway |
| No limit on upload size | A huge request could exhaust the server's memory | Requests over 30 MB are refused before being read |
| No safe-browser headers | Minor hardening gaps | Added (no sniffing, no framing, HTTPS only, API answers not cached) |
| An area name like `.*` was treated as a pattern | Wrong "already exists" matches | Names are matched literally |
| No way to delete an account or take your data out | Required by India's data protection law (DPDP), and by app stores | `DELETE /api/account` (password + typing DELETE) and `GET /api/account/export` |

### Checked and fine
- **Passwords:** stored hashed (bcrypt), minimum 10 characters. **Sign-in:** 10 wrong tries per 15 minutes per email, then locked out for a while.
- **Sign-out and password reset** end every session on every device.
- **Each person only sees their own data:** I traced every database lookup by id in every module; each is tied to the signed-in person (or checked just before). Tests cover this for health, care, people, learning, work, food, payslips and investments.
- **Secrets:** none in the code or its history (searched for database passwords, AI keys, private keys). The server refuses to start in production without its signing secret.
- **Uploads:** statement and payslip passwords are used in memory only; photos, lab reports and payslips are never stored.
- **AI safety:** the AI never decides numbers about a person; health and food rules are marked draft until reviewed.

### Open — your decision or needs outside help
| # | Finding | Risk | What it would take |
|---|---|---|---|
| S1 | **Password reset uses only a security question.** No email is sent. | Anyone who can guess the answer (5 tries per 15 minutes, 20 a day) can take over an account. The question itself is shown to anyone who types the email, which also reveals whether that email has an account. | Email (or SMS OTP) verification for sign-up and reset. Needs an email service (a small monthly cost) and one Emergent screen change. **Recommended before a public launch; acceptable for a small invited beta.** |
| S2 | No limit on creating accounts | Someone could create many accounts to multiply the AI caps | Comes with S1 (verified email), or an invite code for the beta |
| S3 | Sign-in lasts 30 days on a device | A lost unlocked phone stays signed in | Add an app lock (fingerprint/PIN) in the native build |
| S4 | Any website can call the API (`CORS_ORIGINS` is open) | Low: sign-in uses a token, not cookies | Set `CORS_ORIGINS` in Railway to the app's web address once it's final |
| S5 | Libraries are several versions old (FastAPI 0.110, others) | Known fixes missing | A careful upgrade with the full test suite; half a day |
| S6 | Health data is stored like other data | It is the most sensitive data you hold | Before public launch: field-level encryption for health records, a privacy policy, and DPDP legal review (already on your list) |
| S7 | No independent test | I reviewed the code; nobody has attacked the live system | A paid penetration test before public launch |

## 2. Database backups

**What I can and can't see:** I can't see your MongoDB Atlas account from here, so I don't know which plan the database is on. That decides everything:

| Atlas plan | Backups |
|---|---|
| Free (M0) | **None.** If the data is deleted or corrupted, it's gone. |
| Flex / shared paid | Daily snapshots, restore from the last few days |
| Dedicated (M10+) | Continuous backup: restore to any minute |

**Please check (2 minutes):** Atlas → your cluster → the plan name is at the top; the **Backup** tab shows whether snapshots exist.

**Recommendation before beta:** be on a plan with backups (Flex is enough for a beta), and do one test restore into a scratch database so you know it works. If you stay on the free plan, tell me and I'll build a nightly export to storage you own instead.

**Built now, regardless of plan:** each person can download all their own data (`GET /api/account/export`), which also protects them individually.

## 3. First-time setup

A new person today is sent to one setup screen (money and time) and nothing else. Now there's a checklist the app can show: `GET /api/account/setup`.

- Steps, in order: time zone → bank account and cards → work hours and sleep → the people who matter → one thing you want (a first plan) → brain dump; Health is optional.
- Each step says why it matters and which screen opens it; `next` is the one thing to do now; `done` / `of` drives a progress ring.
- The screen itself is on the Emergent list.

## 4. Tester plan

See `docs/BETA_TEST_PLAN.md`: who to invite, what each tester does on day 1, days 2–7 and week 2, what to report and how, and the go / no-go list.

## Go / no-go for an invited beta

| Must be true | Status |
|---|---|
| All automated checks pass | ✅ |
| Fixes above are live | ⏳ on your "merge it" |
| Database has backups (or the nightly export) | ❓ you check Atlas |
| The published app has the screens testers will use | ⏳ Emergent, 18 Nov |
| Push notifications work | ⏳ needs the native build |
| A doctor has reviewed the health rules — or Health is hidden from testers | ❓ your call |
| Testers know it's a beta and how to report problems | ✅ plan written |
