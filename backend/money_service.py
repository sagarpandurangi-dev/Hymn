"""Authoritative Money Source-of-Truth Service.

This module owns the single, canonical calculation of:
  * an account's *effective balance* — snapshot ``current_value`` plus
    every FINANCIALLY APPLIED inflow/outflow linked to that account
    since the snapshot's ``balance_as_of`` timestamp.
  * per-currency *available unreserved money* — sum of effective
    balances of **liquid asset** accounts minus active reserved
    commitments.

Batch 2A + Correction 1 lock in the applied-event rule:
an event affects an account balance ONLY when every one of these holds:
  1. ``account_id`` is present and points to an ASSET account of the
     event's currency owned by the same user (endpoint enforces
     user_id + currency + asset_type at write time).
  2. ``confirmation_status == "confirmed"``.
  3. ``lifecycle_status`` is one of the applied set:
     ``awaiting_reconciliation`` / ``matched`` / ``resolved_unplanned``.
  4. ``occurred_at`` is present AND (parsed as tz-aware UTC datetime)
     is strictly greater than the account's ``balance_as_of``
     (also parsed as tz-aware UTC datetime). Legacy or date-only
     events with no safely-placeable ``occurred_at`` remain unapplied
     and visibly require review.

Design invariants
-----------------
* Snapshots are authoritative *as of* ``balance_as_of``. Events
  occurring at or before that timestamp are never reapplied.
* Availability subtracts only active reserved commitments (state
  ``reserved`` or ``expired``). Confirmed events are NOT subtracted at
  the aggregate again because they are already inside the effective
  balance.
* Availability includes only accounts whose ``account_type`` is in
  ``ASSET_ACCOUNT_TYPES`` and whose ``liquidity_type == 'liquid'``.
  Liabilities and semi/illiquid assets are excluded here.
* All money math flows through ``decimal.Decimal``; no binary floats.

Consumers must call one of the helpers here — no other module may
recompute "available money" or "effective balance". Test coverage is in
``backend/safety_tests/test_money_service.py``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Optional

from bson.decimal128 import Decimal128


# ---------------------------------------------------------------------------
# Constants — event lifecycle status enum for Batch 2A + Correction 1.
# ---------------------------------------------------------------------------

APPLIED_LIFECYCLE_STATUSES: frozenset = frozenset({
    "awaiting_reconciliation",
    "matched",
    "resolved_unplanned",
})

UNAPPLIED_LIFECYCLE_STATUSES: frozenset = frozenset({
    "pending_account_assignment",
    "pending_deduplication",
    "void",
})

ALL_LIFECYCLE_STATUSES: frozenset = APPLIED_LIFECYCLE_STATUSES | UNAPPLIED_LIFECYCLE_STATUSES

# Commitment states that reserve money.
RESERVING_COMMITMENT_STATES: frozenset = frozenset({"reserved", "expired"})

# Liquidity axis label used for availability filtering.
LIQUIDITY_LIQUID = "liquid"

# Asset account types recognised by Portfolio. Mirrors
# ``portfolio_manager.ASSET_ACCOUNT_TYPES`` — kept as a private set here
# so this module can be imported independently for pure unit tests. The
# HTTP layer remains the source of truth; changes to the Portfolio list
# must be reflected here.
ASSET_ACCOUNT_TYPES: frozenset = frozenset({
    "cash", "bank", "fixed_deposit", "recurring_deposit", "mutual_fund",
    "stock", "bond", "crypto", "gold", "real_estate", "other_asset",
})


# ---------------------------------------------------------------------------
# Decimal + datetime helpers.
# ---------------------------------------------------------------------------

def _to_decimal(v: Any) -> Decimal:
    if v is None or v == "":
        return Decimal(0)
    if isinstance(v, Decimal128):
        return v.to_decimal()
    if isinstance(v, Decimal):
        return v
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return Decimal(0)


def parse_utc(v: Any) -> Optional[datetime]:
    """Parse an ISO-8601 string (or ``datetime``) into a tz-aware UTC
    ``datetime``. Returns ``None`` when the input is missing or cannot
    be parsed *with* timezone information — deliberately strict: naive
    timestamps are refused so callers cannot mistake a wall-clock string
    for an authoritative UTC moment.
    """
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        if v.tzinfo is None:
            return None
        return v.astimezone(timezone.utc)
    if not isinstance(v, str):
        return None
    s = v.strip()
    if not s:
        return None
    # Python's fromisoformat handles 'Z' only from 3.11+; be permissive.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc)


def _event_occurs_after_snapshot(event: dict, account_balance_as_of: Any) -> bool:
    """Strict tz-aware comparison. When either side lacks a safely
    parseable UTC datetime we conservatively return ``False`` so the
    event does NOT affect the balance — the caller must surface the
    event for user review.
    """
    ev_dt = parse_utc(event.get("occurred_at"))
    snap_dt = parse_utc(account_balance_as_of)
    if ev_dt is None:
        return False
    if snap_dt is None:
        # Snapshot has never had an authoritative cut-off; any properly
        # dated event applies. In practice migration ensures every
        # account carries a ``balance_as_of``.
        return True
    return ev_dt > snap_dt


# ---------------------------------------------------------------------------
# Applied-event predicate — the single canonical test.
# ---------------------------------------------------------------------------

def event_is_applied_to_account(
    event: dict,
    account: dict,
    *,
    applied_statuses: Iterable[str] = APPLIED_LIFECYCLE_STATUSES,
) -> bool:
    """Return True iff ``event`` counts towards ``account``'s effective
    balance under the strict Batch 2A Correction 1 rules."""
    if event.get("account_id") != account.get("id"):
        return False
    if event.get("confirmation_status") != "confirmed":
        return False
    if event.get("lifecycle_status") not in frozenset(applied_statuses):
        return False
    # Currency guard: the endpoint layer enforces this at write time,
    # but a defensive check here means a data-corruption event never
    # contaminates a different currency's totals.
    if event.get("currency") and account.get("currency") and event["currency"] != account["currency"]:
        return False
    if not _event_occurs_after_snapshot(event, account.get("balance_as_of")):
        return False
    return True


# ---------------------------------------------------------------------------
# Pure calculation helpers — testable without a database.
# ---------------------------------------------------------------------------

def compute_effective_balance(
    account: dict,
    events: Iterable[dict],
    *,
    applied_statuses: Iterable[str] = APPLIED_LIFECYCLE_STATUSES,
) -> Decimal:
    """Return the account's effective balance (Decimal).

    Formula::

        effective = current_value
                  + Σ applied inflow after balance_as_of
                  - Σ applied outflow after balance_as_of
    """
    snapshot = _to_decimal(account.get("current_value"))
    delta = Decimal(0)
    for ev in events:
        if not event_is_applied_to_account(ev, account, applied_statuses=applied_statuses):
            continue
        amt = _to_decimal(ev.get("amount"))
        direction = ev.get("direction")
        if direction == "inflow":
            delta += amt
        elif direction == "outflow":
            delta -= amt
    return snapshot + delta


def summarise_effective_balances(
    accounts: Iterable[dict],
    events: Iterable[dict],
    *,
    applied_statuses: Iterable[str] = APPLIED_LIFECYCLE_STATUSES,
) -> list[dict]:
    """Return one row per account with snapshot / effective breakdown."""
    applied = frozenset(applied_statuses)
    by_account: dict = {}
    for ev in events:
        aid = ev.get("account_id")
        if not aid:
            continue
        by_account.setdefault(aid, []).append(ev)

    out: list[dict] = []
    for a in accounts:
        aid = a.get("id")
        snapshot = _to_decimal(a.get("current_value"))
        inflows = Decimal(0)
        outflows = Decimal(0)
        for ev in by_account.get(aid, ()):
            if not event_is_applied_to_account(ev, a, applied_statuses=applied):
                continue
            amt = _to_decimal(ev.get("amount"))
            if ev.get("direction") == "inflow":
                inflows += amt
            elif ev.get("direction") == "outflow":
                outflows += amt
        effective = snapshot + inflows - outflows
        out.append({
            "account_id": aid,
            "currency": a.get("currency"),
            "liquidity_type": a.get("liquidity_type"),
            "account_type": a.get("account_type"),
            "name": a.get("name") or "",
            "snapshot_current_value": snapshot,
            "snapshot_balance_as_of": a.get("balance_as_of"),
            "post_snapshot_inflows": inflows,
            "post_snapshot_outflows": outflows,
            "effective_current_balance": effective,
        })
    return out


def compute_available_unreserved(
    effective_by_currency: dict,
    reserved_by_currency: dict,
) -> dict:
    """Combine per-currency effective balances with reservations."""
    result: dict = {}
    for cur in set(list(effective_by_currency.keys()) + list(reserved_by_currency.keys())):
        eff = _to_decimal(effective_by_currency.get(cur, Decimal(0)))
        res = _to_decimal(reserved_by_currency.get(cur, Decimal(0)))
        result[cur] = {
            "effective": eff,
            "reserved": res,
            "available_unreserved": eff - res,
        }
    return result


def sum_liquid_effective_by_currency(rows: Iterable[dict]) -> dict:
    """Aggregate ``summarise_effective_balances`` rows into per-currency
    LIQUID ASSET totals used by availability. Only rows whose
    ``liquidity_type == 'liquid'`` AND ``account_type`` is in
    ``ASSET_ACCOUNT_TYPES`` are counted — liabilities and non-liquid
    assets never contribute to available money.
    """
    totals: dict = {}
    for r in rows:
        if r.get("liquidity_type") != LIQUIDITY_LIQUID:
            continue
        if r.get("account_type") not in ASSET_ACCOUNT_TYPES:
            continue
        cur = r.get("currency") or ""
        totals[cur] = totals.get(cur, Decimal(0)) + r.get("effective_current_balance", Decimal(0))
    return totals


def collect_pending_account_events(events: Iterable[dict]) -> list[dict]:
    """Return events that block full confidence in the position because
    they genuinely lack an account and/or a trustworthy occurred_at.

    Correction 2: dedupe-pending events (``pending_deduplication``) are
    NOT surfaced here — they belong to the dedupe resolution journey
    and already carry their own visible ticket. Only records that need
    account or time assignment appear in this list:

    * ``lifecycle_status == 'pending_account_assignment'``, or
    * confirmed with an account + applied lifecycle but no safely
      parseable ``occurred_at`` (legacy/date-only import).

    Void, rejected, and dedupe-pending events are intentionally
    excluded so the Finance dashboard "Pending account" warning shows
    only records the account-assignment path can act on.
    """
    out: list[dict] = []
    for ev in events:
        if ev.get("lifecycle_status") == "pending_account_assignment":
            out.append(ev)
            continue
        if (
            ev.get("confirmation_status") == "confirmed"
            and ev.get("lifecycle_status") in APPLIED_LIFECYCLE_STATUSES
            and ev.get("account_id")
            and parse_utc(ev.get("occurred_at")) is None
        ):
            out.append({**ev, "review_reason": "missing_occurred_at"})
    return out


# ---------------------------------------------------------------------------
# Async loaders — real database wiring.
# ---------------------------------------------------------------------------

async def _load_user_accounts(db, user_id: str) -> list[dict]:
    return await db.financial_accounts.find(
        {"user_id": user_id}, {"_id": 0},
    ).to_list(length=5000)


async def _load_applied_and_all_events(db, user_id: str):
    """Return (applied_events, all_events). Applied is the subset that
    the strict predicate accepts (confirmed + applied lifecycle +
    account_id + parseable occurred_at). This is a *pre-filter* — the
    per-account predicate is still evaluated inside the calculators to
    enforce the snapshot cutoff.
    """
    all_events = await db.financial_events.find(
        {"user_id": user_id}, {"_id": 0},
    ).to_list(length=50000)
    applied_events = [
        e for e in all_events
        if e.get("confirmation_status") == "confirmed"
        and e.get("lifecycle_status") in APPLIED_LIFECYCLE_STATUSES
        and e.get("account_id")
    ]
    return applied_events, all_events


async def _load_reserved_totals(db, user_id: str) -> dict:
    rows = await db.resource_allocations.find(
        {"user_id": user_id, "resource_type": "money",
         "financial_commitment_id": {"$ne": None},
         "state": {"$in": list(RESERVING_COMMITMENT_STATES)}},
        {"_id": 0, "currency": 1, "amount": 1, "quantity": 1},
    ).to_list(length=5000)
    totals: dict = {}
    for r in rows:
        cur = r.get("currency") or ""
        raw = r.get("amount") if r.get("amount") is not None else r.get("quantity")
        totals[cur] = totals.get(cur, Decimal(0)) + _to_decimal(raw)
    return totals


async def load_account_positions(db, user_id: str) -> list[dict]:
    accounts = await _load_user_accounts(db, user_id)
    applied_events, _ = await _load_applied_and_all_events(db, user_id)
    return summarise_effective_balances(accounts, applied_events)


async def load_availability(db, user_id: str) -> dict:
    """Load the full availability breakdown used by every current-money
    / available-money surface."""
    accounts = await _load_user_accounts(db, user_id)
    applied_events, all_events = await _load_applied_and_all_events(db, user_id)
    rows = summarise_effective_balances(accounts, applied_events)
    liquid_totals = sum_liquid_effective_by_currency(rows)
    reserved_totals = await _load_reserved_totals(db, user_id)
    by_cur_raw = compute_available_unreserved(liquid_totals, reserved_totals)
    by_currency = {
        cur: {
            "liquid_effective": v["effective"],
            "reserved": v["reserved"],
            "available_unreserved": v["available_unreserved"],
        }
        for cur, v in by_cur_raw.items()
    }
    return {
        "accounts": rows,
        "by_currency": by_currency,
        "pending_events": collect_pending_account_events(all_events),
    }


async def monthly_actual_spending(
    db, user_id: str, month: str, currency: str,
) -> Decimal:
    """Compute month-to-date outflows from CANONICAL applied events —
    the single source of truth. Sums the amount of every event that:

    * belongs to ``user_id`` and matches ``currency``
    * has ``direction == 'outflow'``
    * is applied (confirmation_status='confirmed' + lifecycle_status in
      APPLIED + account_id present + parseable ``occurred_at``).

    Correction 2: monthly bucketing uses the user-facing/reporting
    ``event_date`` (YYYY-MM-DD in the user's calendar), NOT the UTC
    month of ``occurred_at``. Using the UTC month would move
    transactions across months for users east/west of UTC.
    """
    applied_events, _ = await _load_applied_and_all_events(db, user_id)
    total = Decimal(0)
    for ev in applied_events:
        if ev.get("currency") != currency:
            continue
        if ev.get("direction") != "outflow":
            continue
        if parse_utc(ev.get("occurred_at")) is None:
            # Not trustworthy enough to affect balance — also excluded
            # from the reporting sum.
            continue
        # Bucket by the reporting calendar date, not the UTC month of
        # occurred_at.
        event_date = ev.get("event_date") or ""
        if not (isinstance(event_date, str) and event_date.startswith(month)):
            continue
        total += _to_decimal(ev.get("amount"))
    return total


__all__ = [
    "APPLIED_LIFECYCLE_STATUSES",
    "UNAPPLIED_LIFECYCLE_STATUSES",
    "ALL_LIFECYCLE_STATUSES",
    "RESERVING_COMMITMENT_STATES",
    "LIQUIDITY_LIQUID",
    "ASSET_ACCOUNT_TYPES",
    "parse_utc",
    "event_is_applied_to_account",
    "compute_effective_balance",
    "summarise_effective_balances",
    "compute_available_unreserved",
    "sum_liquid_effective_by_currency",
    "collect_pending_account_events",
    "load_account_positions",
    "load_availability",
    "monthly_actual_spending",
]
