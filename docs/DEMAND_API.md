# Demand reports (for local sellers, through Pamphlet)

Owner, 22 Nov 2026: "120 people would like to finalize property within 100 days. Average budget: 1 crore.
Form: 3 BHK. Focus on these properties… We'll send this to the realtors in that area. Location is also
important." Code: `backend/demand.py`. Tests: `backend/unit_tests/test_demand.py`.

## What each plan carries

Every life plan has an `intent`: `category` (property, car, two_wheeler, wedding, education, travel, gadget,
renovation, business, health, child, other), `form` (e.g. 3 BHK, SUV), `budget_inr` (full price in mind),
`city`, `area`, `pincode`, `source` (planner / person / guess). The planner asks city, area, size/type and
budget for big purchases and passes them in `propose_plan`; otherwise Hymn guesses from the title and
checklist. The plan's `target_date` gives "when".

## The person (app)

| Route | What |
|---|---|
| `GET /api/demand/consent` | `{on, since, text, version}`; off until they switch it on |
| `PUT /api/demand/consent` `{on}` | switch on/off; each change is logged in `consent_log` |
| `GET /api/demand/options` | categories with labels and size/type choices (for the plan's "What and where" fields) |
| `PATCH /api/demand/plans/{plan_id}` | correct `category, form, budget_inr, city, area, pincode` |
| `POST /api/life-plans` | also takes an optional `intent` with the same fields |

## Rules (each covered by a test that fails when the rule is broken)

- Sellers only count people who switched sharing on.
- Sellers only see groups of at least `demand_min_count` people (default 20; the admin page can't set it below 10).
  Areas are only named when that area alone reaches the minimum.
- Health, child (family planning) and "other" plans are never shared.
- Never names, emails, phone numbers, pincodes, notes, plan ids or single plans; each person is counted once.
- Only active plans with a date ahead (drafts, dropped and past plans don't count).
- Nothing goes out while the admin setting `demand_sharing_on` is off (the default, until a lawyer reviews it).
- Pamphlet needs the Railway variable `HYMN_PARTNER_KEY`, sent as the `X-Hymn-Partner-Key` header; every
  pull is logged in `partner_requests` (filters and count only).

## Pamphlet (partner)

| Route | What |
|---|---|
| `GET /api/partner/demand?category=&city=&area=&form=&within_days=` | `people` (or `hidden: true`), `when` (within 100 days / 6 months / a year / later), `budget` {average, median, most_common_range}, `forms` [{form, share %}], `areas`, and `text`: "25 people would like to buy a home in Whitefield, Bengaluru within 100 days. Average budget: ₹1 Cr; most are in the ₹50 L–₹1 Cr range. Most want 3 BHK (64%). Focus on 3 BHK around … to get the most from your time and effort." |
| `GET /api/partner/demand/areas?category=&city=&within_days=` | the city/area groups big enough for a report |

Errors: 401 wrong or missing key; 503 sharing switched off; 400 a category that isn't shared.

## The owner (admin page → Demand)

`GET /api/admin/demand?category=&city=&area=&form=&within_days=`: every category with all people and those
who agreed (groups under 5 shown as "under 5"), top cities, the chosen group across all plans, what a seller
would get, a preview of the report text, how many people agreed, and the sharing switch and minimum.

## Later

Individual leads (a person asking a seller to contact them) are a separate feature with its own per-plan
consent, and need the legal review first.
