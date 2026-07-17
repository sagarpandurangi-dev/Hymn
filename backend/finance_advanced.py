"""Finance Engine — advanced calculations (\u00a715\u2013\u00a726).

This module extends ``finance_manager`` without altering its existing
endpoints. It provides:

* Reconciliation suggestions and confirmation (\u00a715)
* Expected future income CRUD + confirmation (\u00a722)
* Independent Liquidity + Net Worth 12\u2011month forecasts (\u00a718\u2013\u00a720)
* Forecast confidence (\u00a721)
* Decision assessment (\u00a723)
* Override recording (\u00a724)
* Rebalance candidates (\u00a725)
* Scenario CRUD sandbox (\u00a726)

Every calculation reads from the Portfolio-owned source records and the
finance-owned collections created in ``finance_manager``. Nothing is
duplicated; nothing on the frontend recomputes any of this.
"""

from __future__ import annotations

import re
import uuid
from decimal import Decimal
from typing import Any, List, Optional

from bson.decimal128 import Decimal128
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel

from deps import get_current_user, get_db
from finance_manager import (
    _audit,
    _current_position,
    _decimal_from_stored,
    _money_from_stored,
    _money_to_stored,
    _monthly_summary,
    _next_month,
    _now,
    _parse_date,
    _project_commitment,
    _quantize_out,
    _require,
    _require_currency,
    _require_date_str,
    _require_in,
    _today_iso,
    _uuid,
    _apply_complete,
    _month_of,
    CHANGE_SOURCES,
    PRIORITIES,
)


advanced_router = APIRouter(prefix="/finance", tags=["finance-advanced"])


# ============================================================================
# 22 \u2014 Expected future income
# ============================================================================

INCOME_CLASSIFICATIONS = ("confirmed", "expected")


class ExpectedIncomeCreate(BaseModel):
    title: str
    amount: Any
    currency: str
    expected_date: str
    classification: str  # confirmed | expected
    description: Optional[str] = ""


class ExpectedIncomeResponse(BaseModel):
    id: str
    user_id: str
    title: str
    description: str
    amount: str
    currency: str
    expected_date: str
    classification: str
    included_in_forecast: bool
    received: bool
    received_event_id: Optional[str]
    created_at: str
    updated_at: str


@advanced_router.post("/expected-income", response_model=ExpectedIncomeResponse, status_code=201)
async def create_expected_income(body: ExpectedIncomeCreate, current_user: dict = Depends(get_current_user)):
    db = get_db()
    _require(body.title.strip(), "title is required")
    _require_currency(body.currency, "currency")
    _require_date_str(body.expected_date, "expected_date")
    _require_in(body.classification, INCOME_CLASSIFICATIONS, "classification")
    stored = _money_to_stored(body.amount, "amount")
    now = _now()
    doc = {
        "id": _uuid(),
        "user_id": current_user["id"],
        "title": body.title.strip(),
        "description": (body.description or "").strip(),
        "amount": stored,
        "currency": body.currency,
        "expected_date": body.expected_date,
        "classification": body.classification,
        # Expected income requires a second confirmation before entering the forecast.
        "included_in_forecast": body.classification == "confirmed",
        "received": False,
        "received_event_id": None,
        "created_at": now,
        "updated_at": now,
    }
    await db.expected_incomes.insert_one(doc)
    await _audit(
        db, current_user["id"], "financial_event", doc["id"], "created",
        source="manual",
        new_value={"kind": "expected_income", "classification": body.classification,
                   "amount": _money_from_stored(stored), "currency": body.currency},
    )
    return _project_expected(doc)


def _project_expected(doc: dict) -> dict:
    d = dict(doc)
    d["amount"] = _money_from_stored(d.get("amount"))
    return d


@advanced_router.get("/expected-income", response_model=List[ExpectedIncomeResponse])
async def list_expected_income(current_user: dict = Depends(get_current_user)):
    db = get_db()
    docs = await db.expected_incomes.find({"user_id": current_user["id"]}, {"_id": 0}).sort("expected_date", 1).to_list(length=1000)
    return [_project_expected(d) for d in docs]


class ExpectedIncomeConfirmPayload(BaseModel):
    include_in_forecast: bool = True


@advanced_router.post("/expected-income/{income_id}/confirm-inclusion", response_model=ExpectedIncomeResponse)
async def confirm_expected_inclusion(
    income_id: str, body: ExpectedIncomeConfirmPayload,
    current_user: dict = Depends(get_current_user),
):
    """Second confirmation gate for Expected income (\u00a722): the user must
    explicitly acknowledge before the row enters the forecast."""
    db = get_db()
    d = await db.expected_incomes.find_one({"id": income_id, "user_id": current_user["id"]}, {"_id": 0})
    if not d:
        raise HTTPException(status_code=404, detail="Expected income not found")
    await db.expected_incomes.update_one(
        {"id": income_id}, {"$set": {"included_in_forecast": body.include_in_forecast, "updated_at": _now()}},
    )
    await _audit(
        db, current_user["id"], "financial_event", income_id, "updated",
        source="manual", new_value={"included_in_forecast": body.include_in_forecast},
    )
    d["included_in_forecast"] = body.include_in_forecast
    return _project_expected(d)


class ExpectedIncomeReceivePayload(BaseModel):
    event_id: Optional[str] = None
    actual_amount: Optional[Any] = None
    event_date: Optional[str] = None


@advanced_router.post("/expected-income/{income_id}/received", response_model=ExpectedIncomeResponse)
async def mark_expected_received(
    income_id: str, body: ExpectedIncomeReceivePayload = Body(default_factory=ExpectedIncomeReceivePayload),
    current_user: dict = Depends(get_current_user),
):
    """Mark expected income as received. Creates a confirmed inflow Financial
    Event exactly once so it never doubles with the planned line."""
    db = get_db()
    d = await db.expected_incomes.find_one({"id": income_id, "user_id": current_user["id"]}, {"_id": 0})
    if not d:
        raise HTTPException(status_code=404, detail="Expected income not found")
    _require(not d.get("received"), "This expected income is already received")

    if body.event_id:
        ev = await db.financial_events.find_one({"id": body.event_id, "user_id": current_user["id"]}, {"_id": 0})
        if not ev:
            raise HTTPException(status_code=404, detail="Referenced event not found")
        _require(ev.get("currency") == d.get("currency"), "Event currency must match expected income currency")
        event_id = ev["id"]
    else:
        amt = _decimal_from_stored(d.get("amount")) if not body.actual_amount else _decimal_from_stored(_money_to_stored(body.actual_amount, "actual_amount"))
        event_id = _uuid()
        await db.financial_events.insert_one({
            "id": event_id,
            "user_id": current_user["id"],
            "amount": Decimal128(amt),
            "currency": d["currency"],
            "direction": "inflow",
            "event_date": body.event_date or _today_iso(),
            "description": f"Received: {d['title']}",
            "source": "manual",
            "source_reference": f"expected_income:{income_id}",
            "confirmation_status": "confirmed",
            "checkin_id": None,
            "commitment_id": None,
            "created_at": _now(),
        })
        await _audit(
            db, current_user["id"], "financial_event", event_id, "created",
            source="manual", new_value={"amount": _quantize_out(amt), "currency": d["currency"],
                                         "direction": "inflow", "expected_income_id": income_id},
        )

    await db.expected_incomes.update_one(
        {"id": income_id}, {"$set": {"received": True, "received_event_id": event_id, "updated_at": _now()}},
    )
    d["received"] = True
    d["received_event_id"] = event_id
    return _project_expected(d)


@advanced_router.delete("/expected-income/{income_id}", status_code=200)
async def delete_expected_income(income_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    r = await db.expected_incomes.delete_one({"id": income_id, "user_id": current_user["id"]})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Expected income not found")
    await _audit(db, current_user["id"], "financial_event", income_id, "cancelled", source="manual",
                 notes="expected income removed by user")
    return {"detail": "deleted"}


# ============================================================================
# 15 \u2014 Reconciliation suggestions
# ============================================================================

def _lev(a: str, b: str) -> int:
    """Levenshtein distance for fuzzy description similarity. Uses a small
    dp array so we don't pull an extra dependency in for a rarely used path."""
    if a == b:
        return 0
    if not a or not b:
        return max(len(a), len(b))
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + (ca != cb))
        prev = curr
    return prev[-1]


def _similarity(a: str, b: str) -> float:
    a = (a or "").lower().strip()
    b = (b or "").lower().strip()
    if not a and not b:
        return 0.0
    m = max(len(a), len(b))
    if m == 0:
        return 0.0
    return 1.0 - _lev(a, b) / m


async def _score_matches(db, user_id: str, event: dict) -> list:
    """Return a list of (commitment, score, reasons) for a confirmed event.

    Score is a heuristic 0-100. Strong match => score >= 70 AND uniquely top.
    """
    commitments = await db.financial_commitments.find(
        {"user_id": user_id, "state": {"$in": ["reserved", "expired"]},
         "currency": event.get("currency")}, {"_id": 0},
    ).to_list(length=500)
    ev_amt = _decimal_from_stored(event.get("amount"))
    try:
        ev_date = _parse_date(event.get("event_date"))
    except Exception:
        ev_date = None
    results = []
    for c in commitments:
        reasons = []
        score = 0
        # Direction must be outflow for a commitment match.
        if event.get("direction") != "outflow":
            continue
        # Amount proximity
        c_amt = _decimal_from_stored(c.get("amount"))
        if c_amt > 0:
            diff = abs((ev_amt - c_amt) / c_amt) if c_amt != 0 else Decimal(1)
            if diff == 0:
                score += 40; reasons.append("amount_exact")
            elif diff <= Decimal("0.05"):
                score += 30; reasons.append("amount_close_5pct")
            elif diff <= Decimal("0.15"):
                score += 15; reasons.append("amount_close_15pct")
        # Description similarity
        sim = _similarity(event.get("description") or "", c.get("title") or "")
        if sim >= 0.9:
            score += 30; reasons.append("desc_exact_or_near")
        elif sim >= 0.6:
            score += 15; reasons.append("desc_fuzzy")
        # Due date proximity
        try:
            c_date = _parse_date(c.get("due_date"))
            if ev_date and c_date:
                delta = abs((ev_date - c_date).days)
                if delta <= 3:
                    score += 20; reasons.append("date_within_3d")
                elif delta <= 14:
                    score += 10; reasons.append("date_within_14d")
        except Exception:
            pass
        # Linked task/context
        if event.get("commitment_id") and event["commitment_id"] == c["id"]:
            score += 20; reasons.append("explicit_link")
        if score > 0:
            results.append({"commitment": _project_commitment(c), "score": score, "reasons": reasons})
    results.sort(key=lambda r: r["score"], reverse=True)
    return results


@advanced_router.get("/reconciliation/suggestions")
async def reconciliation_suggestions(current_user: dict = Depends(get_current_user)):
    """List confirmed unmatched events with ranked commitment candidates so
    the client can surface the appropriate prompts (\u00a715). Never auto-completes."""
    db = get_db()
    events = await db.financial_events.find(
        {"user_id": current_user["id"], "confirmation_status": "confirmed",
         "direction": "outflow", "commitment_id": None,
         "$or": [
             {"reconciliation_status": {"$exists": False}},
             {"reconciliation_status": {"$ne": "matched"}},
         ]},
        {"_id": 0},
    ).sort("event_date", -1).to_list(length=200)
    out = []
    for ev in events:
        matches = await _score_matches(db, current_user["id"], ev)
        strong = [m for m in matches if m["score"] >= 70]
        top = strong[0] if len(strong) == 1 else None
        out.append({
            "event": {**ev, "amount": _money_from_stored(ev.get("amount"))},
            "matches": matches,
            "single_strong_match": top,
        })
    return out


class ReconcileConfirmPayload(BaseModel):
    commitment_id: str
    actual_amount_override: Optional[Any] = None


@advanced_router.post("/reconciliation/{event_id}/confirm")
async def reconcile_confirm(
    event_id: str, body: ReconcileConfirmPayload,
    current_user: dict = Depends(get_current_user),
):
    """User confirms an event is a match for a commitment. This completes the
    commitment with the event as the actual (per \u00a713 rules) and marks the
    event ``matched`` so subsequent forecasts don't double-count."""
    db = get_db()
    ev = await db.financial_events.find_one({"id": event_id, "user_id": current_user["id"]}, {"_id": 0})
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found")
    c = await db.financial_commitments.find_one({"id": body.commitment_id, "user_id": current_user["id"]}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Commitment not found")
    _require(c.get("state") in ("reserved", "expired"),
             f"Cannot reconcile against a commitment in state '{c.get('state')}'")

    # Attach event to commitment then use the shared complete path
    if body.actual_amount_override is not None:
        stored = _money_to_stored(body.actual_amount_override, "actual_amount_override")
        await db.financial_events.update_one({"id": event_id}, {"$set": {"amount": stored}})
        ev["amount"] = stored
    await db.financial_events.update_one(
        {"id": event_id}, {"$set": {"commitment_id": c["id"], "reconciliation_status": "matched"}},
    )
    updated = await _apply_complete(db, current_user["id"], c, None, event_id, ev.get("event_date"))
    await _audit(
        db, current_user["id"], "financial_event", event_id, "reconciled",
        source="reconciliation",
        new_value={"commitment_id": c["id"], "outcome": "matched"},
        related_event_id=event_id,
    )
    return {"commitment": _project_commitment(updated)}


@advanced_router.post("/reconciliation/{event_id}/reject")
async def reconcile_reject(event_id: str, current_user: dict = Depends(get_current_user)):
    """User rejects all suggested matches. Event is treated as unplanned;
    Finance already counted it once via the pipeline (\u00a713)."""
    db = get_db()
    ev = await db.financial_events.find_one({"id": event_id, "user_id": current_user["id"]}, {"_id": 0})
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found")
    await db.financial_events.update_one(
        {"id": event_id}, {"$set": {"reconciliation_status": "unmatched"}},
    )
    await _audit(
        db, current_user["id"], "financial_event", event_id, "reconciled",
        source="reconciliation", new_value={"outcome": "unmatched"},
    )
    return {"detail": "marked unmatched"}


# ============================================================================
# 18-21 \u2014 Twin twelve-month forecasts with confidence
# ============================================================================

async def _twin_forecasts(db, user_id: str) -> dict:
    """Return both Liquidity Forecast and Net Worth Forecast, per currency.

    Both are derived independently from the same source records (\u00a718).
    Each per-month row carries the assumptions used (\u00a721) so the client
    can drill into confidence.
    """
    pos = await _current_position(db, user_id)
    liquid_by_cur = {c["currency"]: _decimal_from_stored(c["liquid_assets"]) for c in pos["currencies"]}
    assets_by_cur = {c["currency"]: _decimal_from_stored(c["total_assets"]) for c in pos["currencies"]}
    liab_by_cur = {c["currency"]: _decimal_from_stored(c["total_liabilities"]) for c in pos["currencies"]}

    # Reserved commitments per (currency, due_month)
    reserved_docs = await db.financial_commitments.find(
        {"user_id": user_id, "state": {"$in": ["reserved", "expired"]}}, {"_id": 0},
    ).to_list(length=5000)
    # Expected income (per included_in_forecast)
    expected_docs = await db.expected_incomes.find(
        {"user_id": user_id, "included_in_forecast": True, "received": False}, {"_id": 0},
    ).to_list(length=1000)
    # Confirmed month-to-date events by (currency, month, direction)
    all_events = await db.financial_events.find(
        {"user_id": user_id, "confirmation_status": "confirmed"},
        {"_id": 0, "amount": 1, "currency": 1, "direction": 1, "event_date": 1, "commitment_id": 1},
    ).to_list(length=20000)

    current_month = _today_iso()[:7]
    months = [current_month]
    for _ in range(11):
        months.append(_next_month(months[-1]))

    all_currencies = set(liquid_by_cur.keys())
    for c in reserved_docs:
        all_currencies.add(c.get("currency") or "")
    for e in expected_docs:
        all_currencies.add(e.get("currency") or "")

    liquidity_by_cur = []
    networth_by_cur = []

    for cur in sorted(all_currencies):
        # Bucket reserved commitments by month and by id (for netting)
        reserved_by_month: dict = {m: [] for m in months}
        reserved_ids_reconciled_this_cur = set()
        for c in reserved_docs:
            if c.get("currency") != cur:
                continue
            due_month = _month_of(c.get("due_date") or "")
            if due_month in reserved_by_month:
                reserved_by_month[due_month].append(c)
        for e in all_events:
            if e.get("currency") == cur and e.get("commitment_id"):
                reserved_ids_reconciled_this_cur.add(e["commitment_id"])

        # Bucket expected income by month
        expected_by_month: dict = {m: [] for m in months}
        for e in expected_docs:
            if e.get("currency") != cur:
                continue
            em = _month_of(e.get("expected_date") or "")
            if em in expected_by_month:
                expected_by_month[em].append(e)

        # Confirmed monthly events by direction
        confirmed_out: dict = {m: Decimal(0) for m in months}
        confirmed_in: dict = {m: Decimal(0) for m in months}
        confirmed_evs_by_month: dict = {m: [] for m in months}
        for e in all_events:
            if e.get("currency") != cur:
                continue
            m = _month_of(e.get("event_date") or "")
            if m not in confirmed_out:
                continue
            amt = _decimal_from_stored(e.get("amount"))
            if e.get("direction") == "outflow":
                confirmed_out[m] += amt
            else:
                confirmed_in[m] += amt
            confirmed_evs_by_month[m].append(e)

        rolling_liquid = liquid_by_cur.get(cur, Decimal(0))
        rolling_assets = assets_by_cur.get(cur, Decimal(0))
        rolling_liab = liab_by_cur.get(cur, Decimal(0))

        liq_rows = []
        nw_rows = []
        for i, m in enumerate(months):
            summary = await _monthly_summary(db, user_id, m, cur)
            recurring_income = _decimal_from_stored(summary["recurring_income"])
            recurring_expenses = _decimal_from_stored(summary["recurring_expenses"])
            debt_payments = _decimal_from_stored(summary["debt_payments"])
            savings = _decimal_from_stored(summary["savings"])
            investments = _decimal_from_stored(summary["investments"])
            # Financial Commitments due this month (skip those already reconciled to an event)
            fc_this_month = [c for c in reserved_by_month[m] if c["id"] not in reserved_ids_reconciled_this_cur]
            fc_amount = sum((_decimal_from_stored(c.get("amount")) for c in fc_this_month), Decimal(0))
            # Expected income (already gated by confirmation)
            exp_amount = sum((_decimal_from_stored(e.get("amount")) for e in expected_by_month[m]), Decimal(0))
            exp_confirmed = sum((_decimal_from_stored(e.get("amount")) for e in expected_by_month[m] if e.get("classification") == "confirmed"), Decimal(0))
            exp_expected = exp_amount - exp_confirmed

            # Actual events already recorded this month (do not double-count with FC when reconciled)
            actual_outflow = confirmed_out[m]
            actual_inflow = confirmed_in[m]

            opening = rolling_liquid
            closing = (
                opening
                + recurring_income
                + exp_amount
                + actual_inflow
                - recurring_expenses
                - debt_payments
                - savings
                - investments
                - fc_amount
                - actual_outflow
            )
            available_unreserved = closing  # by definition here, closing already excludes reservations

            # Confidence per month (\u00a721)
            assumptions = ["current_accounts", "recurring_income", "recurring_expenses"]
            confidence = "high"
            if exp_expected > 0:
                assumptions.append("expected_income_unconfirmed")
                confidence = "low"
            if fc_amount > 0:
                assumptions.append("financial_commitments")
                if confidence == "high":
                    confidence = "medium"
            if fc_amount > 0 and closing < recurring_expenses + debt_payments:
                confidence = "low"
            if closing < 0:
                confidence = "low"
            # Stale unresolved commitments
            for c in fc_this_month:
                if (c.get("last_reviewed_at") or "") < _today_iso()[:10] and c.get("state") == "expired":
                    if confidence != "low":
                        confidence = "low"
                    if "stale_expired_commitments" not in assumptions:
                        assumptions.append("stale_expired_commitments")

            liq_rows.append({
                "month": m,
                "opening_liquid_money": _quantize_out(opening),
                "confirmed_recurring_income": _quantize_out(recurring_income),
                "confirmed_one_time_income": _quantize_out(exp_confirmed),
                "expected_income": _quantize_out(exp_expected),
                "recurring_expenses": _quantize_out(recurring_expenses),
                "debt_payments": _quantize_out(debt_payments),
                "savings": _quantize_out(savings),
                "investments": _quantize_out(investments),
                "financial_commitments_due": _quantize_out(fc_amount),
                "financial_commitment_ids": [c["id"] for c in fc_this_month],
                "confirmed_actual_events_outflow": _quantize_out(actual_outflow),
                "confirmed_actual_events_inflow": _quantize_out(actual_inflow),
                "confirmed_actual_event_ids": [e.get("source_reference") or "" for e in confirmed_evs_by_month[m]],
                "closing_liquid_money": _quantize_out(closing),
                "available_unreserved_liquid_money": _quantize_out(available_unreserved),
                "confidence": confidence,
                "assumptions_used": assumptions,
                "shortfall": closing < 0,
            })

            # Net Worth forecast (\u00a720) \u2014 principal-preserving:
            #  income increases assets; consumption expenses decrease assets & NW;
            #  savings and investments move money between asset buckets \u2014 no NW change;
            #  debt payments reduce liabilities & liquid assets (principal only \u2014 no NW change);
            #  FC principal outflow is treated as consumption unless reconciled to a
            #  savings/investment/asset event (we don't have that classification here,
            #  so we conservatively treat FC outflow as consumption per \u00a720 defaults).
            asset_change = (
                recurring_income
                + exp_confirmed  # only confirmed one-time income
                - recurring_expenses
                - fc_amount
                - actual_outflow
                + actual_inflow
            )
            # Savings & investments are principal-preserving; they move value between buckets.
            # Debt repayment principal is not a NW change; we do NOT deduct it from NW.
            liability_change = -debt_payments
            rolling_assets = rolling_assets + asset_change
            rolling_liab = rolling_liab + liability_change
            nw = rolling_assets - rolling_liab
            nw_rows.append({
                "month": m,
                "total_assets": _quantize_out(rolling_assets),
                "total_liabilities": _quantize_out(rolling_liab),
                "net_worth": _quantize_out(nw),
                "asset_changes": _quantize_out(asset_change),
                "liability_changes": _quantize_out(liability_change),
                "contributing_record_ids": [c["id"] for c in fc_this_month],
                "confidence": confidence,
                "assumptions_used": assumptions,
            })

            rolling_liquid = closing

        # Currency-level confidence: worst monthly confidence in the horizon.
        def _worst(rows):
            order = {"high": 3, "medium": 2, "low": 1}
            return min(rows, key=lambda r: order.get(r["confidence"], 1))["confidence"] if rows else "high"

        liquidity_by_cur.append({
            "currency": cur, "confidence": _worst(liq_rows), "months": liq_rows,
        })
        networth_by_cur.append({
            "currency": cur, "confidence": _worst(nw_rows), "months": nw_rows,
        })

    return {
        "generated_at": _now(),
        "liquidity_forecast": {"by_currency": liquidity_by_cur},
        "net_worth_forecast": {"by_currency": networth_by_cur},
        "multi_currency": len(all_currencies) > 1,
    }


@advanced_router.get("/forecasts")
async def get_twin_forecasts(current_user: dict = Depends(get_current_user)):
    db = get_db()
    return await _twin_forecasts(db, current_user["id"])


# ============================================================================
# 23 \u2014 Decision assessment
# ============================================================================

class DecisionAssessmentPayload(BaseModel):
    amount: Any
    currency: str
    due_date: str
    priority: str


def _priority_rank(p: str) -> int:
    return {"low": 0, "medium": 1, "high": 2, "critical": 3}.get(p, 1)


@advanced_router.post("/decision-assessment")
async def decision_assessment(
    body: DecisionAssessmentPayload, current_user: dict = Depends(get_current_user),
):
    db = get_db()
    _require_currency(body.currency, "currency")
    _require_date_str(body.due_date, "due_date")
    _require_in(body.priority, PRIORITIES, "priority")
    prop_amt = _decimal_from_stored(_money_to_stored(body.amount, "amount"))
    prop_month = _month_of(body.due_date)
    prop_prio = _priority_rank(body.priority)

    base = await _twin_forecasts(db, current_user["id"])
    liq = next((x for x in base["liquidity_forecast"]["by_currency"] if x["currency"] == body.currency), None)
    nw = next((x for x in base["net_worth_forecast"]["by_currency"] if x["currency"] == body.currency), None)
    if not liq or not nw:
        # No baseline in this currency \u2014 treat as Severe Risk with note.
        return {
            "classification": "severe_risk",
            "reason": "No baseline for this currency; add accounts first.",
            "projected_liquidity_by_due_date": None,
            "projected_shortfall": None,
            "projected_surplus": None,
            "net_worth_impact": None,
            "affected_commitments": [],
            "affected_savings": [],
            "affected_investments": [],
            "forecast_confidence": "low",
            "assumptions_used": [],
        }

    # Apply the proposed commitment to the liquidity rows going forward.
    projected_liquid_at_due: Optional[Decimal] = None
    negative_months = []
    projected_close_current = None
    for row in liq["months"]:
        # Reservations subtract capacity immediately (\u00a76). But the cash outflow is on the due month.
        rolling = _decimal_from_stored(row["closing_liquid_money"])
        if row["month"] == prop_month:
            rolling = rolling - prop_amt
            projected_liquid_at_due = rolling
        if row["month"] >= _today_iso()[:7]:
            if rolling < 0:
                negative_months.append({"month": row["month"], "closing": _quantize_out(rolling)})
        if row["month"] == _today_iso()[:7]:
            projected_close_current = rolling

    # Load existing commitments to find those the proposal might displace.
    all_commit = await db.financial_commitments.find(
        {"user_id": current_user["id"], "state": "reserved", "currency": body.currency},
        {"_id": 0},
    ).to_list(length=1000)
    higher_priority_displaced = [
        _project_commitment(c) for c in all_commit
        if _priority_rank(c.get("priority", "medium")) > prop_prio and (c.get("due_date") or "") >= body.due_date
    ]

    # Classification (\u00a723)
    if negative_months or higher_priority_displaced:
        classification = "severe_risk"
    else:
        # Materially constrained: does adding the proposal squeeze other commitments in due months?
        affected: list = []
        for c in all_commit:
            due = c.get("due_date") or ""
            due_month = _month_of(due)
            row = next((r for r in liq["months"] if r["month"] == due_month), None)
            if row is None:
                continue
            close_after = _decimal_from_stored(row["closing_liquid_money"]) - (prop_amt if due_month >= prop_month else Decimal(0))
            if close_after < _decimal_from_stored(c.get("amount")):
                affected.append(_project_commitment(c))
        if affected:
            classification = "warning"
        else:
            classification = "safe"

    # Order affected commitments per \u00a723
    def _order_key(c: dict):
        rank = _priority_rank(c.get("priority", "medium"))
        flex = 0 if c.get("fixed_or_flexible") == "flexible" else 1
        return (rank, flex, -_parse_date(c["due_date"]).toordinal())
    affected = [c for c in [_project_commitment(x) for x in all_commit]
                if c.get("due_date") and c.get("due_date") >= body.due_date]
    affected.sort(key=_order_key)

    # Assumptions: worst-confidence of any affected month
    assumptions = []
    for row in liq["months"]:
        for a in row.get("assumptions_used", []):
            if a not in assumptions:
                assumptions.append(a)
    confidence = liq.get("confidence", "medium")

    return {
        "classification": classification,
        "projected_liquidity_by_due_date": _quantize_out(projected_liquid_at_due) if projected_liquid_at_due is not None else None,
        "projected_shortfall": (
            _quantize_out(-projected_liquid_at_due)
            if projected_liquid_at_due is not None and projected_liquid_at_due < 0 else None
        ),
        "projected_surplus": (
            _quantize_out(projected_liquid_at_due)
            if projected_liquid_at_due is not None and projected_liquid_at_due >= 0 else None
        ),
        "net_worth_impact": _quantize_out(-prop_amt),  # principal outflow treated as consumption by default
        "affected_commitments": affected,
        "affected_savings": [],  # populated when monthly savings/investment breakdown feature added
        "affected_investments": [],
        "displaced_higher_priority": higher_priority_displaced,
        "negative_months": negative_months,
        "forecast_confidence": confidence,
        "assumptions_used": assumptions,
    }


# ============================================================================
# 24 \u2014 Override recording
# ============================================================================

class OverrideRecordPayload(BaseModel):
    commitment_id: str
    forecast_snapshot: dict
    liquidity_result: dict
    net_worth_result: dict
    confidence: str
    warning_classification: str
    projected_shortfall: Optional[Any] = None
    affected_commitments: list = []
    user_comment: Optional[str] = None


@advanced_router.post("/overrides")
async def record_override(body: OverrideRecordPayload, current_user: dict = Depends(get_current_user)):
    db = get_db()
    doc = {
        "id": _uuid(),
        "user_id": current_user["id"],
        "commitment_id": body.commitment_id,
        "decision_timestamp": _now(),
        "forecast_snapshot": body.forecast_snapshot,
        "liquidity_result": body.liquidity_result,
        "net_worth_result": body.net_worth_result,
        "confidence": body.confidence,
        "warning_classification": body.warning_classification,
        "projected_shortfall": (_money_from_stored(_money_to_stored(body.projected_shortfall, "projected_shortfall")) if body.projected_shortfall is not None else None),
        "affected_commitments": body.affected_commitments,
        "user_comment": body.user_comment,
        "actual_outcome": None,
        "user_or_hymn_correct": None,
    }
    await db.override_decisions.insert_one(doc)
    await _audit(
        db, current_user["id"], "financial_commitment", body.commitment_id, "reviewed",
        source="manual",
        new_value={"override": True, "warning": body.warning_classification, "confidence": body.confidence},
        notes="user proceeded despite warning",
    )
    return {"id": doc["id"]}


@advanced_router.get("/overrides")
async def list_overrides(current_user: dict = Depends(get_current_user)):
    db = get_db()
    docs = await db.override_decisions.find(
        {"user_id": current_user["id"]}, {"_id": 0},
    ).sort("decision_timestamp", -1).to_list(length=500)
    return docs


# ============================================================================
# 25 \u2014 Rebalance candidates
# ============================================================================

@advanced_router.get("/rebalance-candidates")
async def rebalance_candidates(
    currency: str = Query(...), exclude_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Return Reserved commitments for the currency ordered per \u00a725:
    1) lower priority first, 2) flexible before fixed, 3) later due date first
    when tied. The user picks candidates; nothing is auto-rebalanced."""
    db = get_db()
    _require_currency(currency, "currency")
    q = {"user_id": current_user["id"], "state": "reserved", "currency": currency}
    if exclude_id:
        q["id"] = {"$ne": exclude_id}
    docs = await db.financial_commitments.find(q, {"_id": 0}).to_list(length=1000)

    def _key(c: dict):
        return (
            _priority_rank(c.get("priority", "medium")),
            0 if c.get("fixed_or_flexible") == "flexible" else 1,
            -_parse_date(c["due_date"]).toordinal(),
        )
    docs.sort(key=_key)
    out = []
    for c in docs:
        row = _project_commitment(c)
        # Preview impact of postponing or cancelling this candidate.
        row["preview"] = {
            "money_released_if_cancelled": row["amount"],
            "linked_task_id": row.get("task_id"),
            "note": "Linked task will remain active. Cancel it separately if desired.",
        }
        out.append(row)
    return out


# ============================================================================
# 26 \u2014 Scenarios (persistent sandbox)
# ============================================================================

class ScenarioSavePayload(BaseModel):
    name: str
    currency: str
    assumptions: dict  # arbitrary lever overrides; interpreted server-side


class ScenarioResponse(BaseModel):
    id: str
    user_id: str
    name: str
    currency: str
    assumptions: dict
    created_at: str
    updated_at: str


def _project_scenario(doc: dict) -> dict:
    return {k: doc[k] for k in ("id", "user_id", "name", "currency", "assumptions", "created_at", "updated_at") if k in doc}


@advanced_router.post("/scenarios/save", response_model=ScenarioResponse, status_code=201)
async def scenario_save(body: ScenarioSavePayload, current_user: dict = Depends(get_current_user)):
    db = get_db()
    _require(body.name.strip(), "name is required")
    _require_currency(body.currency, "currency")
    now = _now()
    doc = {
        "id": _uuid(),
        "user_id": current_user["id"],
        "name": body.name.strip(),
        "currency": body.currency,
        "assumptions": body.assumptions or {},
        "created_at": now,
        "updated_at": now,
    }
    await db.scenarios.insert_one(doc)
    return _project_scenario(doc)


@advanced_router.get("/scenarios/list", response_model=List[ScenarioResponse])
async def scenario_list(current_user: dict = Depends(get_current_user)):
    db = get_db()
    docs = await db.scenarios.find({"user_id": current_user["id"]}, {"_id": 0}).sort("updated_at", -1).to_list(length=200)
    return [_project_scenario(d) for d in docs]


@advanced_router.get("/scenarios/detail/{scenario_id}")
async def scenario_detail(scenario_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    doc = await db.scenarios.find_one({"id": scenario_id, "user_id": current_user["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return _project_scenario(doc)


@advanced_router.put("/scenarios/detail/{scenario_id}", response_model=ScenarioResponse)
async def scenario_update(scenario_id: str, body: ScenarioSavePayload, current_user: dict = Depends(get_current_user)):
    db = get_db()
    doc = await db.scenarios.find_one({"id": scenario_id, "user_id": current_user["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Scenario not found")
    _require(body.name.strip(), "name is required")
    _require_currency(body.currency, "currency")
    update = {"name": body.name.strip(), "currency": body.currency, "assumptions": body.assumptions or {}, "updated_at": _now()}
    await db.scenarios.update_one({"id": scenario_id}, {"$set": update})
    doc.update(update)
    return _project_scenario(doc)


@advanced_router.post("/scenarios/detail/{scenario_id}/duplicate", response_model=ScenarioResponse, status_code=201)
async def scenario_duplicate(scenario_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    doc = await db.scenarios.find_one({"id": scenario_id, "user_id": current_user["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Scenario not found")
    now = _now()
    clone = {**doc, "id": _uuid(), "name": f"{doc['name']} (copy)", "created_at": now, "updated_at": now}
    await db.scenarios.insert_one(clone)
    return _project_scenario(clone)


@advanced_router.delete("/scenarios/detail/{scenario_id}", status_code=200)
async def scenario_delete(scenario_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    r = await db.scenarios.delete_one({"id": scenario_id, "user_id": current_user["id"]})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return {"detail": "deleted"}


@advanced_router.post("/scenarios/detail/{scenario_id}/evaluate")
async def scenario_evaluate(scenario_id: str, current_user: dict = Depends(get_current_user)):
    """Return base vs scenario twin forecasts. Scenario assumptions are
    applied inside this call ONLY \u2014 never persisted to real records."""
    db = get_db()
    scen = await db.scenarios.find_one({"id": scenario_id, "user_id": current_user["id"]}, {"_id": 0})
    if not scen:
        raise HTTPException(status_code=404, detail="Scenario not found")
    base = await _twin_forecasts(db, current_user["id"])
    ass = scen.get("assumptions") or {}
    cur = scen["currency"]
    # Recognised levers: additional_monthly_income, additional_monthly_expense,
    # additional_reservation + reservation_due_month, salary_change_from_month +
    # salary_delta, one_time_income (amount+month), one_time_expense (amount+month),
    # loan_closure (liability_id + close_month), asset_purchase (amount+month),
    # asset_sale (amount+month), commitment_change (id + new_amount + new_due).
    #
    # We apply each lever to a fresh copy of the base per-currency rows for
    # the scenario's currency only.
    liq_by_cur = base["liquidity_forecast"]["by_currency"]
    nw_by_cur = base["net_worth_forecast"]["by_currency"]
    target_liq = next((x for x in liq_by_cur if x["currency"] == cur), None)
    target_nw = next((x for x in nw_by_cur if x["currency"] == cur), None)
    if not target_liq or not target_nw:
        return {"scenario": _project_scenario(scen), "base": base, "scenario_forecast": base, "diff": []}

    def _to_dec(v: Any) -> Decimal:
        try:
            return _decimal_from_stored(v)
        except Exception:
            return Decimal(0)

    def _apply_liq(rows: list) -> list:
        rolling_delta = Decimal(0)
        add_inc = _to_dec(ass.get("additional_monthly_income", 0))
        add_exp = _to_dec(ass.get("additional_monthly_expense", 0))
        add_res = _to_dec(ass.get("additional_reservation", 0))
        res_month = ass.get("reservation_due_month")
        salary_delta = _to_dec(ass.get("salary_delta", 0))
        salary_from = ass.get("salary_change_from_month")
        one_time_income_amt = _to_dec(ass.get("one_time_income_amount", 0))
        one_time_income_month = ass.get("one_time_income_month")
        one_time_expense_amt = _to_dec(ass.get("one_time_expense_amount", 0))
        one_time_expense_month = ass.get("one_time_expense_month")
        out = []
        for row in rows:
            delta = Decimal(0)
            delta += add_inc - add_exp
            if salary_from and row["month"] >= salary_from:
                delta += salary_delta
            if one_time_income_month and row["month"] == one_time_income_month:
                delta += one_time_income_amt
            if one_time_expense_month and row["month"] == one_time_expense_month:
                delta -= one_time_expense_amt
            if res_month and row["month"] == res_month:
                delta -= add_res
            rolling_delta += delta
            new_closing = _decimal_from_stored(row["closing_liquid_money"]) + rolling_delta
            new_available = _decimal_from_stored(row["available_unreserved_liquid_money"]) + rolling_delta
            out.append({
                **row,
                "closing_liquid_money": _quantize_out(new_closing),
                "available_unreserved_liquid_money": _quantize_out(new_available),
                "shortfall": new_closing < 0,
            })
        return out

    def _apply_nw(rows: list) -> list:
        rolling_delta_assets = Decimal(0)
        rolling_delta_liab = Decimal(0)
        add_inc = _to_dec(ass.get("additional_monthly_income", 0))
        add_exp = _to_dec(ass.get("additional_monthly_expense", 0))
        salary_delta = _to_dec(ass.get("salary_delta", 0))
        salary_from = ass.get("salary_change_from_month")
        one_time_income_amt = _to_dec(ass.get("one_time_income_amount", 0))
        one_time_income_month = ass.get("one_time_income_month")
        one_time_expense_amt = _to_dec(ass.get("one_time_expense_amount", 0))
        one_time_expense_month = ass.get("one_time_expense_month")
        loan_closure_amt = _to_dec(ass.get("loan_closure_amount", 0))
        loan_close_month = ass.get("loan_closure_month")
        out = []
        for row in rows:
            asset_delta = add_inc - add_exp
            if salary_from and row["month"] >= salary_from:
                asset_delta += salary_delta
            if one_time_income_month and row["month"] == one_time_income_month:
                asset_delta += one_time_income_amt
            if one_time_expense_month and row["month"] == one_time_expense_month:
                asset_delta -= one_time_expense_amt
            liab_delta = Decimal(0)
            if loan_close_month and row["month"] == loan_close_month:
                # closing a loan reduces liabilities AND liquid assets by the same principal
                liab_delta -= loan_closure_amt
                asset_delta -= loan_closure_amt
            rolling_delta_assets += asset_delta
            rolling_delta_liab += liab_delta
            new_assets = _decimal_from_stored(row["total_assets"]) + rolling_delta_assets
            new_liab = _decimal_from_stored(row["total_liabilities"]) + rolling_delta_liab
            out.append({
                **row,
                "total_assets": _quantize_out(new_assets),
                "total_liabilities": _quantize_out(new_liab),
                "net_worth": _quantize_out(new_assets - new_liab),
            })
        return out

    scen_liq_rows = _apply_liq(target_liq["months"])
    scen_nw_rows = _apply_nw(target_nw["months"])

    diff = []
    for base_row, scen_row in zip(target_liq["months"], scen_liq_rows):
        diff.append({
            "month": base_row["month"],
            "base_liquid": base_row["closing_liquid_money"],
            "scenario_liquid": scen_row["closing_liquid_money"],
            "base_shortfall": base_row["shortfall"],
            "scenario_shortfall": scen_row["shortfall"],
        })

    return {
        "scenario": _project_scenario(scen),
        "base": {
            "liquidity_forecast": target_liq,
            "net_worth_forecast": target_nw,
        },
        "scenario_forecast": {
            "liquidity_forecast": {"currency": cur, "confidence": target_liq["confidence"], "months": scen_liq_rows},
            "net_worth_forecast": {"currency": cur, "confidence": target_nw["confidence"], "months": scen_nw_rows},
        },
        "diff": diff,
    }


# ============================================================================
# 17 \u2014 Shared expense helper
# ============================================================================

class SharedExpenseIOwe(BaseModel):
    total_amount: Any
    currency: str
    other_paid_by: str   # display name of who paid
    my_share: Any
    description: Optional[str] = ""
    due_date: str
    priority: str = "medium"
    create_task: bool = True


@advanced_router.post("/shared-expenses/i-owe")
async def shared_expense_i_owe(body: SharedExpenseIOwe, current_user: dict = Depends(get_current_user)):
    """When someone else paid and the user owes a share (\u00a717). Creates a
    Reserved Financial Commitment for the user's share plus a repay Task."""
    db = get_db()
    _require_currency(body.currency, "currency")
    _require_date_str(body.due_date, "due_date")
    _require_in(body.priority, PRIORITIES, "priority")
    now = _now()
    share_stored = _money_to_stored(body.my_share, "my_share")
    commitment_id = _uuid()
    task_id = _uuid() if body.create_task else None
    doc = {
        "id": commitment_id,
        "user_id": current_user["id"],
        "title": f"Repay {body.other_paid_by}",
        "description": (body.description or "").strip(),
        "amount": share_stored,
        "currency": body.currency,
        "due_date": body.due_date,
        "original_due_date": body.due_date,
        "priority": body.priority,
        "state": "draft",
        "domain_id": None, "goal_id": None, "project_id": None,
        "task_id": task_id,
        "resource_allocation_id": None,
        "actual_amount": None, "variance": None, "unused_reservation": None, "overrun_amount": None,
        "completed_at": None, "cancelled_at": None,
        "postpone_count": 0, "last_reviewed_at": None, "next_review_date": None,
        "source": "shared_expense",
        "created_at": now, "updated_at": now,
    }
    await db.financial_commitments.insert_one(doc)
    if task_id:
        await db.tasks.insert_one({
            "id": task_id, "user_id": current_user["id"],
            "title": f"Repay {body.other_paid_by}",
            "notes": f"Shared expense repayment linked to commitment {commitment_id}",
            "priority": body.priority, "status": "todo", "due_date": body.due_date,
            "goal_id": None, "project_id": None, "expected_outcome_id": None, "domain_id": None,
            "financial_commitment_id": commitment_id,
            "created_at": now, "updated_at": now,
        })
    # Immediately reserve so it enters the Liquidity Forecast (\u00a717 says
    # "reserve the amount immediately" when another person paid).
    alloc_id = _uuid()
    await db.resource_allocations.insert_one({
        "id": alloc_id, "user_id": current_user["id"],
        "resource_type": "money", "owner_type": "task" if task_id else "standalone",
        "owner_id": task_id, "allocation_mode": "one_time",
        "date": body.due_date, "day_of_week": None, "start_time": None, "end_time": None,
        "quantity": share_stored, "unit": "currency", "currency": body.currency,
        "status": "reserved", "fixed_or_flexible": "fixed",
        "created_at": now, "updated_at": now,
    })
    await db.financial_commitments.update_one(
        {"id": commitment_id},
        {"$set": {"state": "reserved", "resource_allocation_id": alloc_id,
                  "next_review_date": _today_iso(), "updated_at": _now()}},
    )
    # Schema-prep mirror \u2014 keep the new allocation in lock-step with the FC.
    from finance_manager import _mirror_fc_to_allocation as _mirror  # noqa: WPS433
    fresh = await db.financial_commitments.find_one({"id": commitment_id}, {"_id": 0})
    await _mirror(db, fresh or {})
    await _audit(
        db, current_user["id"], "financial_commitment", commitment_id, "created",
        source="manual",
        new_value={"kind": "shared_expense_i_owe", "amount": _money_from_stored(share_stored),
                   "currency": body.currency, "paid_by": body.other_paid_by, "task_id": task_id},
    )
    return {"commitment_id": commitment_id, "task_id": task_id}


class SharedExpenseIPaid(BaseModel):
    total_amount: Any
    currency: str
    participants: List[str]  # display names — the payer is the current user
    event_date: str
    description: Optional[str] = ""
    prepare_repayment_message: bool = False


@advanced_router.post("/shared-expenses/i-paid")
async def shared_expense_i_paid(body: SharedExpenseIPaid, current_user: dict = Depends(get_current_user)):
    """User paid a shared expense. Creates one outflow Actual Financial Event
    for the total and returns per-person expected inflow lines (\u00a717).
    Does NOT increase cash for owed amounts until repayment is confirmed."""
    db = get_db()
    _require_currency(body.currency, "currency")
    _require_date_str(body.event_date, "event_date")
    _require(len(body.participants) > 0, "at least one other participant required")
    total_stored = _money_to_stored(body.total_amount, "total_amount")
    total_dec = _decimal_from_stored(total_stored)
    share = (total_dec / (len(body.participants) + 1)).quantize(Decimal("0.01"))
    # 1. Outflow event for the total the user paid
    ev_id = _uuid()
    await db.financial_events.insert_one({
        "id": ev_id, "user_id": current_user["id"],
        "amount": total_stored, "currency": body.currency,
        "direction": "outflow", "event_date": body.event_date,
        "description": (body.description or "Shared expense").strip(),
        "source": "manual", "source_reference": None,
        "confirmation_status": "confirmed",
        "checkin_id": None, "commitment_id": None,
        "created_at": _now(),
    })
    # 2. Per-participant expected inflow ledger \u2014 stored in expected_incomes
    #    with classification "expected" and included_in_forecast=false. The user
    #    must confirm inclusion or mark received.
    lines = []
    for name in body.participants:
        income_id = _uuid()
        await db.expected_incomes.insert_one({
            "id": income_id, "user_id": current_user["id"],
            "title": f"Repayment from {name}",
            "description": (body.description or "").strip(),
            "amount": Decimal128(share),
            "currency": body.currency,
            "expected_date": body.event_date,
            "classification": "expected",
            "included_in_forecast": False,
            "received": False, "received_event_id": None,
            "created_at": _now(), "updated_at": _now(),
        })
        lines.append({"participant": name, "amount": _quantize_out(share), "expected_income_id": income_id})

    result = {
        "outflow_event_id": ev_id,
        "per_participant_amount": _quantize_out(share),
        "expected_inflow_lines": lines,
    }
    if body.prepare_repayment_message:
        # NEVER auto-send. Return a draft the user can share externally.
        message = "Hey! Splitting the shared expense:\n" + "\n".join(
            f"- {l['participant']}: {body.currency} {l['amount']}" for l in lines
        )
        result["draft_repayment_message"] = message
    return result


# ============================================================================
# Index bootstrap
# ============================================================================

async def ensure_finance_advanced_indexes(database) -> None:
    await database.expected_incomes.create_index("id", unique=True)
    await database.expected_incomes.create_index([("user_id", 1), ("expected_date", 1)])
    await database.override_decisions.create_index("id", unique=True)
    await database.override_decisions.create_index([("user_id", 1), ("decision_timestamp", -1)])
    await database.scenarios.create_index("id", unique=True)
    await database.scenarios.create_index([("user_id", 1), ("updated_at", -1)])


# Re-export CHANGE_SOURCES to keep imports stable for the wiring layer.
__all__ = ["advanced_router", "ensure_finance_advanced_indexes", "CHANGE_SOURCES"]
