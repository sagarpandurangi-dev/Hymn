# Investments from a CAS statement — API notes for the app

Premium (like bank statements). Free for Hymn to read: parsed in code, no AI.

## Where people get the PDF (show this on the upload screen)
- **Mutual funds (all of them under your PAN):** request a "Consolidated Account Statement" on the CAMS or KFintech website (detailed, with transactions). It's emailed as a PDF; the password is the one you set when requesting it.
- **Demat (shares, bonds, funds in demat, NPS):** NSDL or CDSL emails it every month. The password is usually your PAN in capitals.

## Calls
1. `POST /api/investments/cas/preview` `{file_base64, password}` → nothing saved to the money book yet (the password is used in memory only):
   ```json
   {"id": "…", "source": "CAMS/KFintech | NSDL/CDSL", "period": {"from": "2026-04-01", "to": "2026-11-10"},
    "investor": "RAVI KUMAR", "already_applied": false, "converted": true, "total": "14050.00",
    "lines": [{"key": "mutual_fund:inf846k01k35:123/45", "kind": "mutual_fund|stock|bond|nps", "name": "…",
               "folio": "123/45", "units": "100.000", "price": "100.50", "value": "10050.00", "cost": "9000",
               "valued_on": "2026-11-10", "items": null, "check": null,
               "action": "new|update|same|older", "before": "…", "change": "…"}],
    "missing": [{"account_id": "…", "name": "…"}],
    "your_other_investment_accounts": [{"id": "…", "name": "Mutual funds", "account_type": "mutual_fund", "value": "…"}],
    "note": "…"}
   ```
   - Show the investor name so people notice a spouse's statement.
   - `check` (if any): show a warning on that line ("please check").
   - `older`: Hymn already has a newer value; it won't be changed.
   - `stock` / `bond` / `nps` lines are one per demat account / PRAN, with `items` (each share or scheme) to expand.
   - 400 with a plain message when the password is wrong or it isn't a CAS. 403 for free users.
2. **Avoid double counting.** If `your_other_investment_accounts` isn't empty, ask: "Is any of these the same as a fund in this statement?" For each, the person picks one of:
   - **the same fund** → send it in `links` (holding key → account id); that account is updated instead of a new one;
   - **this statement replaces it** (e.g. one "Mutual funds" total typed earlier) → send it in `replaces`; its value goes to zero on the statement date;
   - **something else** → leave it.
3. `POST /api/investments/cas/{id}/apply` `{links: {}, replaces: []}` → `{applied: {new, update, same, older}, linked, replaced, total, missing}`. 409 if this statement is already in.
4. `GET /api/investments/cas` → past imports `{id, source, period, investor, applied_at, result}`.

## How it shows up
- Each fund is an investment account (type `mutual_fund`); shares, bonds and NPS one account each per demat account / PRAN. They appear under **Investments** in the Statement of Net Worth.
- A change in value between statements is a **market value change**: part of "other changes" in net worth, never income or spending, and not cash flow. Earlier months are not rewritten.
- `missing`: funds imported before that aren't in this statement (maybe sold). Show them; nothing is changed automatically.
