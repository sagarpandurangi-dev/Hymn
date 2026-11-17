# Planned money API (for the app)

One list for everything expected to come in or go out. Replaces monthly
commitments, one-off commitments and expected income on screens.

## Item
| field | values |
|---|---|
| `title` | text |
| `direction` | `in` / `out` |
| `purpose` | `income` (in) · `spend`, `saving`, `investment`, `loan_payment`, `other` (out) |
| `amount`, `currency` | `"25000"`, `"INR"` |
| `repeat` | `once` (needs `date` YYYY-MM-DD) · `monthly` / `yearly` (need `start_month` YYYY-MM, optional `end_month`) |
| `certainty` | `sure` (counted) · `maybe` (shown apart, not counted) |
| `set_aside` | one-off spends only: hold money aside for it |
| `status` | `active` · `done` · `cancelled` |
| `done_amount`, `remaining_amount` | paid/received so far, what's left |
| `source`, `editable` | `planned` items are editable here; items from older screens (`monthly_commitment`, `financial_commitment`, `expected_income`) are read-only (edit returns 409) |

## Endpoints
- `GET /api/planned-money?include_done=false` — the list.
- `POST /api/planned-money` — add (fields above).
- `PATCH /api/planned-money/{id}` — change any field, incl. `status`, `done_amount`.
- `DELETE /api/planned-money/{id}`.
- `GET /api/planned-money/months?start=YYYY-MM&count=12` — per month and
  currency: `income`, `spend`, `moves` (to savings/investments), `set_aside`,
  `maybe_in`, `maybe_out`.

The forecast (`GET /api/finance/forecast`) reads this list; each month also
has `maybe_income` and `maybe_spending`.

## Set aside
An active one-off spend with `set_aside: true` holds what's left of it (amount − `done_amount`) out of
"Available to spend": the Finance dashboard's `available_liquidity[].reserved` includes it and
`available_unreserved` goes down by it. `reserved[]` lists it under `planned_set_aside[]`
(`id`, `title`, `date`, `amount`) next to `commitments[]`. Marking it done (or cancelling it) releases it.

## Events waiting for an account
`GET /api/finance/events?lifecycle_status=pending_account_assignment` lists only spends that still need
an account (the "Pending account → Assign" shortcut).

