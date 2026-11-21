# Premium and subscriptions

Code: `backend/billing.py` (trial, beta pass, promo codes, subscriptions, payment webhooks, admin revenue),
`backend/plans.py` (who is Premium, Premium-only features, limits). Tests: `backend/unit_tests/test_billing.py`.

## Who is Premium (first match wins)

1. A manual choice on the admin page (People → a person → Give Premium / Make free).
2. Email in the Railway variable `HYMN_PREMIUM_EMAILS`.
3. `premium_until` in the future, which is the latest of:
   - **the free trial**: every new person gets `trial_days` (14) of Premium, no card needed;
   - **the beta pass**: people who sign up before `beta_premium_until` (or everyone, if the admin applies it now)
     get Premium until that date and become **founding members** (first year at the founding price);
   - **promo codes**: free Premium days;
   - **a paid subscription**: until the end of the paid period; after a failed payment, `grace_days` (7) more
     while the payment is retried; when cancelled, until the end of what was paid for.
4. Otherwise free.

## What's free and what's Premium (editable on the admin page → Settings)

| Limit | Free | Premium |
|---|---|---|
| Planning conversations a month | 3 | no limit |
| Learning journeys at a time | 1 | no limit |
| People you look after | 1 | 5 |
| Food photos a month | 30 | 300 |
| Lab reports read a month | 3 | 20 |
| WhatsApp tasks a month | 20 | no limit |

Premium only: reading statements (bank, investments, payslips) and Things I own & owe. Never paywalled: safety
(health red flags), downloading or deleting your data, privacy. Daily AI caps stay as they were (`ai_budget`).
At a limit the app gets **403** with a friendly line ("The free plan includes 3 planning conversations a month.
Premium has more — see Me → Premium.").

Prices (editable): **₹199 a month, ₹1,499 a year, founding members ₹999 for the first year.**

## Payments

| Where | How | Status |
|---|---|---|
| Website (and the app, by opening the payment page) | **Razorpay** subscriptions: UPI AutoPay, cards; Razorpay issues invoices | Built; switches on with the keys |
| Google Play, App Store | **RevenueCat** (the app's buy button, store billing) | Server built; the app part comes with the native build |

### Owner setup: Razorpay
1. Create a Razorpay account (needs the company and bank account) and finish KYC.
2. In Razorpay → Subscriptions → Plans, create three plans: monthly ₹199, yearly ₹1,499, founding yearly ₹999.
   Paste their plan ids into the admin page → Settings → Razorpay plan ids. (When a price changes, create a new
   plan at that price and paste its id.)
3. In Razorpay → Settings → Webhooks: URL `https://hymn-production-4828.up.railway.app/api/billing/webhooks/razorpay`,
   events `subscription.*`, a secret of your choice.
4. In Railway → Variables: `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` (from Razorpay → API keys) and
   `RAZORPAY_WEBHOOK_SECRET` (the secret from step 3). The admin page → Revenue shows ✓ for each.
5. Test with Razorpay's test mode keys first.

### Owner setup: RevenueCat (with the native build)
1. Google Play and App Store developer accounts; create subscription products whose ids contain "monthly" or
   "yearly" (e.g. `hymn_premium_monthly`, `hymn_premium_yearly`).
2. A RevenueCat project connected to both stores; one entitlement "premium" with both products.
3. RevenueCat → Integrations → Webhooks: URL `https://hymn-production-4828.up.railway.app/api/billing/webhooks/revenuecat`
   and an Authorization header value of your choice; put the same value in Railway as `REVENUECAT_WEBHOOK_AUTH`.
4. The app logs in to RevenueCat with the person's **Hymn user id** (the Emergent prompt says so).

GST: Razorpay invoices web subscriptions; Google and Apple handle tax on store purchases. Confirm the GST treatment
with a CA.

## API

| Route | What |
|---|---|
| `GET /api/billing/plans` (no sign-in) | prices, trial days, Premium-only features, limits (free / premium) |
| `GET /api/billing` | `plan`, `premium_until`, `source` (manual / trial / beta / promo / subscription), `in_trial`, `trial_days_left`, `founding_member`, `subscription` {provider, plan, status, renews_on, ends_on, store}, `prices` (founding only for founding members), `can_buy_on_web`, `limits` |
| `POST /api/billing/checkout {plan: monthly|yearly}` | creates a Razorpay subscription → `{subscription_id, key_id, short_url, plan, amount_inr}`; open `short_url`. Founding members buying yearly get the founding plan. 503 until set up; 409 if already paying |
| `POST /api/billing/cancel` | website subscriptions: cancel at the end of the period. Store subscriptions: 409 "cancel it in Google Play / the App Store" |
| `POST /api/billing/redeem {code}` | promo code → free Premium days (once per person) |
| `POST /api/billing/webhooks/razorpay` | signed with `X-Razorpay-Signature`; deduped by `X-Razorpay-Event-Id` |
| `POST /api/billing/webhooks/revenuecat` | `Authorization` must equal `REVENUECAT_WEBHOOK_AUTH`; deduped by event id |
| Admin: `GET /api/admin/billing`, `POST /api/admin/billing/promos`, `POST /api/admin/billing/promos/{code}/off`, `POST /api/admin/billing/beta {until, apply_to_everyone_now}` | revenue, promo codes, beta pass |

Deleting an account cancels its website subscription; a store subscription has to be cancelled in the store.
