"""One-time conversion of existing finance data into the ledger (plan A2).

``preview`` builds the full conversion in memory and reports it — nothing is
written. ``apply`` writes exactly what the preview showed, refusing if the
data changed since (the preview carries a fingerprint) or if the user has
already been converted.

What becomes what
-----------------
* Each financial account with a non-zero snapshot → an ``opening_balance``.
  Events already reflected in the snapshot (by money_service's own rule) are
  converted too, so history is kept; the opening balance is the snapshot
  minus their effect, dated before them. Ledger balances therefore equal
  today's Finance balances by construction — and the preview checks it.
* Each financial event that counts in Finance today → an ``expense``
  (outflow) or ``income`` (inflow), uncategorised, provenance ``conversion``
  and not locked, so later classification (transfer, card bill, gift…) can
  refine it. The event becomes the transaction's evidence.
* Everything else is listed, not converted: events waiting on an account or
  a duplicate decision, void or rejected ones, currency mismatches, and
  old check-in spends that never became events.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel

import ledger
import money_service
from deps import get_current_user, get_db

ZERO = Decimal(0)


def _date_part(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).date().isoformat()
    if isinstance(value, str) and len(value) >= 10:
        try:
            return ledger.valid_date(value[:10])
        except ledger.LedgerError:
            return None
    return None


def _skip_reason(ev: dict, accounts: Dict[str, dict]) -> Optional[str]:
    if ev.get("confirmation_status") == "rejected":
        return "rejected"
    if ev.get("lifecycle_status") == "void":
        return "void"
    if ev.get("lifecycle_status") == "pending_account_assignment" or not ev.get("account_id"):
        return "needs_account"
    if ev.get("lifecycle_status") == "pending_deduplication" or ev.get("confirmation_status") != "confirmed":
        return "needs_review"
    if ev.get("lifecycle_status") not in money_service.APPLIED_LIFECYCLE_STATUSES:
        return "unknown_status"
    acct = accounts.get(ev["account_id"])
    if acct is None:
        return "account_missing"
    if acct.get("account_type") not in ledger.ASSET_TYPES | ledger.LIABILITY_TYPES:
        return "account_type_unsupported"
    if ev.get("currency") != acct.get("currency"):
        return "currency_mismatch"
    if _date_part(ev.get("event_date")) is None:
        return "no_date"
    if ev.get("direction") not in ("inflow", "outflow"):
        return "no_direction"
    try:
        if ledger.to_decimal(ev.get("amount")) <= 0:
            return "zero_amount"
    except ledger.LedgerError:
        return "zero_amount"
    return None


def plan_conversion(accounts: List[dict], events: List[dict],
                    orphan_checkins: List[dict], today: str) -> dict:
    """Pure: the transactions to write and a report. ``accounts`` and
    ``events`` are raw documents; amounts may be Decimal128 or strings."""
    by_id = {a["id"]: a for a in accounts}
    drafts: List[dict] = []
    skipped: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"count": 0, "totals": defaultdict(Decimal)})
    converted_events: Dict[str, List[dict]] = defaultdict(list)

    for ev in sorted(events, key=lambda e: (str(e.get("event_date")), str(e.get("created_at")))):
        reason = _skip_reason(ev, by_id)
        if reason:
            skipped[reason]["count"] += 1
            skipped[reason]["totals"][ev.get("currency") or "?"] += ledger.to_decimal(ev.get("amount") or 0)
            continue
        converted_events[ev["account_id"]].append(ev)

    account_rows = []
    for acct in accounts:
        if acct.get("account_type") not in ledger.ASSET_TYPES | ledger.LIABILITY_TYPES:
            continue
        evs = converted_events.get(acct["id"], [])
        snapshot = ledger.to_decimal(acct.get("current_value") or 0)
        is_liability = acct.get("account_type") in ledger.LIABILITY_TYPES
        # Events money_service already counts in the snapshot (before it, or
        # same-day ambiguous) are folded out of the opening balance.
        in_snapshot = [e for e in evs if not money_service.event_is_applied_to_account(e, acct)]
        signed = (lambda e: ledger.to_decimal(e["amount"]) * (1 if e["direction"] == "inflow" else -1))
        before = sum((signed(e) for e in in_snapshot), ZERO)
        after = sum((signed(e) for e in evs if e not in in_snapshot), ZERO)
        # As people read it: held for assets, owed for liabilities.
        opening = snapshot - (-before if is_liability else before)
        snapshot_date = _date_part(acct.get("balance_as_of"))
        candidate_dates = [d for d in [snapshot_date] + [_date_part(e["event_date"]) for e in evs] if d]
        opening_date = min(candidate_dates) if candidate_dates else (_date_part(acct.get("created_at")) or today)
        if opening:
            drafts.append({
                "draft": ledger.Draft(kind="opening_balance", date=opening_date, currency=acct["currency"],
                                      description=f"Opening balance: {acct.get('name', '')}".strip(),
                                      amount=str(opening), account_id=acct["id"]),
                "evidence_ids": [],
            })
        for e in evs:
            kind = "income" if e["direction"] == "inflow" else "expense"
            side = {"to_account_id": acct["id"]} if kind == "income" else {"from_account_id": acct["id"]}
            if kind == "income" and is_liability:
                kind, side = "refund", {"to_account_id": acct["id"]}
            drafts.append({
                "draft": ledger.Draft(kind=kind, date=_date_part(e["event_date"]), currency=e["currency"],
                                      description=e.get("description") or "", amount=str(ledger.to_decimal(e["amount"])),
                                      **side),
                "evidence_ids": [e["id"]],
            })
        effective = snapshot + (-after if is_liability else after)
        account_rows.append({
            "account_id": acct["id"],
            "name": acct.get("name", ""),
            "account_type": acct.get("account_type"),
            "currency": acct.get("currency"),
            "snapshot": format(snapshot, "f"),
            "snapshot_date": snapshot_date,
            "opening_balance": format(opening, "f"),
            "opening_date": opening_date,
            "events_converted": len(evs),
            "events_in_snapshot": len(in_snapshot),
            "finance_balance_today": format(effective, "f"),
        })

    orphan_totals: Dict[str, Decimal] = defaultdict(Decimal)
    for c in orphan_checkins:
        orphan_totals[c.get("money_currency") or "?"] += ledger.to_decimal(c.get("money_spent") or 0)

    return {
        "drafts": drafts,
        "accounts": account_rows,
        "skipped": {
            k: {"count": v["count"], "totals": {c: format(t, "f") for c, t in v["totals"].items()}}
            for k, v in sorted(skipped.items())
        },
        "orphan_checkin_spends": {
            "count": len(orphan_checkins),
            "totals": {c: format(t, "f") for c, t in orphan_totals.items()},
        },
    }


def _fingerprint(plan: dict) -> str:
    payload = [
        {**{k: v for k, v in vars(d["draft"]).items()}, "evidence_ids": d["evidence_ids"]}
        for d in plan["drafts"]
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]


async def _gather(db, user_id: str) -> tuple:
    accounts = await db.financial_accounts.find({"user_id": user_id}, {"_id": 0}).to_list(length=None)
    events = await db.financial_events.find({"user_id": user_id}, {"_id": 0}).to_list(length=None)
    with_event = {e.get("checkin_id") for e in events if e.get("checkin_id")}
    checkins = await db.checkins.find(
        {"user_id": user_id, "money_spent": {"$ne": None}},
        {"_id": 0, "id": 1, "money_spent": 1, "money_currency": 1},
    ).to_list(length=None)
    orphans = [c for c in checkins if c["id"] not in with_event]
    return accounts, events, orphans


def _verify(plan: dict, accounts: List[dict], events: List[dict], today: str) -> dict:
    """Recompute balances and monthly spending from the planned ledger and
    compare them with what Finance reports today."""
    real = {a["id"]: a for a in accounts}
    txs = []
    for i, d in enumerate(plan["drafts"]):
        postings = ledger.build_postings(d["draft"], real)
        txs.append({"date": d["draft"].date, "currency": d["draft"].currency, "kind": d["draft"].kind,
                    "postings": postings, "created_at": f"{i:08d}"})
    raw: Dict[str, Decimal] = defaultdict(Decimal)
    for tx in txs:
        for p in tx["postings"]:
            if p["account_id"] in real:
                raw[p["account_id"]] += p["amount"]
    mismatched_accounts = []
    for row in plan["accounts"]:
        cls = ledger.account_class(row["account_id"], real)
        ledger_balance = ledger.displayed_balance(cls, raw[row["account_id"]])
        row["ledger_balance_today"] = format(ledger_balance, "f")
        if ledger_balance != Decimal(row["finance_balance_today"]):
            mismatched_accounts.append(row["account_id"])

    finance_months: Dict[tuple, Decimal] = defaultdict(Decimal)
    for e in events:
        if money_service.counts_as_spending(e) and e.get("account_id") in real \
                and e.get("currency") == real[e["account_id"]].get("currency"):
            finance_months[(e["currency"], e["event_date"][:7])] += ledger.to_decimal(e["amount"])
    ledger_months: Dict[tuple, Decimal] = defaultdict(Decimal)
    for tx in txs:
        for p in tx["postings"]:
            if ledger.NOMINAL_ACCOUNTS.get(p["account_id"]) == "expense":
                ledger_months[(tx["currency"], tx["date"][:7])] += p["amount"]
    months = sorted(set(finance_months) | set(ledger_months))
    monthly = [
        {"currency": cur, "month": m, "finance": format(finance_months[(cur, m)], "f"),
         "ledger": format(ledger_months[(cur, m)], "f"),
         "matches": finance_months[(cur, m)] == ledger_months[(cur, m)]}
        for cur, m in months
    ]
    return {
        "balances_match": not mismatched_accounts,
        "mismatched_accounts": mismatched_accounts,
        "spending_matches": all(r["matches"] for r in monthly),
        "monthly_spending": monthly,
    }


def summary_lines(report: dict) -> List[str]:
    """Plain-language lines for the app to show as-is."""
    lines = []
    lines.append(f"{report['transactions_to_create']} money-book entries will be created "
                 f"from {len(report['accounts'])} accounts.")
    v = report["verification"]
    lines.append("✓ Every account balance matches Finance today." if v["balances_match"]
                 else f"✗ {len(v['mismatched_accounts'])} account balance(s) differ from Finance.")
    lines.append("✓ Spending matches Finance for every month." if v["spending_matches"]
                 else "✗ Some months' spending differs from Finance.")
    labels = {
        "needs_account": "spends waiting for an account", "needs_review": "spends waiting on a duplicate check",
        "void": "voided entries", "rejected": "rejected entries", "currency_mismatch": "entries in the wrong currency",
        "account_missing": "entries for deleted accounts", "account_type_unsupported": "entries on unsupported accounts",
        "no_date": "entries without a date", "no_direction": "entries without a direction",
        "zero_amount": "entries with no amount",
        "unknown_status": "entries in an unknown state",
    }
    for reason, info in report["skipped"].items():
        lines.append(f"Not moved: {info['count']} {labels.get(reason, reason)}.")
    if report["orphan_checkin_spends"]["count"]:
        lines.append(f"Not moved: {report['orphan_checkin_spends']['count']} older check-in spends "
                     f"that were never recorded in Finance.")
    lines.append("All moved spending starts as 'uncategorised'; you'll be able to sort it later.")
    return lines


async def preview(db, user_id: str) -> dict:
    accounts, events, orphans = await _gather(db, user_id)
    today = datetime.now(timezone.utc).date().isoformat()
    plan = plan_conversion(accounts, events, orphans, today)
    report = {
        "fingerprint": _fingerprint(plan),
        "already_converted": bool(await db.ledger_transactions.find_one(
            {"user_id": user_id, "provenance": "conversion"}, {"_id": 1})),
        "transactions_to_create": len(plan["drafts"]),
        "accounts": plan["accounts"],
        "skipped": plan["skipped"],
        "orphan_checkin_spends": plan["orphan_checkin_spends"],
    }
    report["verification"] = _verify(plan, accounts, events, today)
    report["summary"] = summary_lines(report)
    return report, plan


async def apply(db, user_id: str, fingerprint: str) -> dict:
    report, plan = await preview(db, user_id)
    if report["already_converted"]:
        raise HTTPException(status_code=409, detail="Already converted")
    if fingerprint != report["fingerprint"]:
        raise HTTPException(status_code=409, detail="Your data changed since the preview; review it again.")
    v = report["verification"]
    if not (v["balances_match"] and v["spending_matches"]):
        raise HTTPException(status_code=409, detail="The preview found differences; conversion is blocked.")
    created = 0
    for d in plan["drafts"]:
        await ledger.record(db, user_id, d["draft"], provenance="conversion", evidence_ids=d["evidence_ids"])
        created += 1
    return {"created": created, "fingerprint": fingerprint}


class ApplyRequest(BaseModel):
    fingerprint: str


@ledger.ledger_router.get("/conversion/preview")
async def conversion_preview(current_user: dict = Depends(get_current_user)):
    report, _ = await preview(get_db(), current_user["id"])
    return report


@ledger.ledger_router.post("/conversion/apply")
async def conversion_apply(body: ApplyRequest, current_user: dict = Depends(get_current_user)):
    return await apply(get_db(), current_user["id"], body.fingerprint)
