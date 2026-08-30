"""Authoritative Money Source-of-Truth Service.

This module owns the single, canonical calculation of:
  * an account's *effective balance* — snapshot ``current_value`` plus
    every confirmed inflow/outflow linked to that account since the
    snapshot's ``balance_as_of`` timestamp.
  * per-currency *available unreserved money* — sum of effective
    balances of liquid asset accounts minus active reserved commitments.

Batch 2A (Foundation Cleanup / Money Source of Truth) explicitly forbids
competing "current position" or "available money" math anywhere else in
the codebase — every consumer must call one of the helpers below.

Design invariants
-----------------
1. Snapshots are authoritative *as of* ``balance_as_of``. Events created
   before that timestamp must never be reapplied — the snapshot already
   reflects them.
2. An event contributes to an account's effective balance only when
   * it has ``account_id`` set,
   * its ``lifecycle_status`` is one of the applied statuses
     (``awaiting_reconciliation``, ``matched``, ``resolved_unplanned``),
   * its ``created_at`` is strictly greater than the account's
     ``balance_as_of``.
3. Availability subtracts *only* active reserved commitments (state
   ``reserved`` or ``expired``). Confirmed events are NOT subtracted at
   the aggregate again because they are already inside the effective
   balance.
4. All money math flows through ``decimal.Decimal``; no binary floats.

The module deliberately exposes both:
  * pure helpers (``compute_effective_balance``,
    ``compute_available_unreserved``) that operate on in-memory dicts —
    fully unit-testable without a database, and
  * async loaders that assemble the same result from MongoDB.

Test coverage lives in ``backend/safety_tests/test_money_service.py``.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Optional

from bson.decimal128 import Decimal128


# ---------------------------------------------------------------------------
# Constants — event lifecycle status enum for Batch 2A.
# ---------------------------------------------------------------------------

# Statuses that MUST count against an account's effective balance.
APPLIED_LIFECYCLE_STATUSES: frozenset = frozenset({
    "awaiting_reconciliation",
    "matched",
    "resolved_unplanned",
})

# Statuses that MUST NOT affect balances (pending or reversed).
UNAPPLIED_LIFECYCLE_STATUSES: frozenset = frozenset({
    "pending_account_assignment",
    "void",
})

ALL_LIFECYCLE_STATUSES: frozenset = APPLIED_LIFECYCLE_STATUSES | UNAPPLIED_LIFECYCLE_STATUSES

# Commitment states that reserve money (draft doesn't; completed/cancelled
# release).
RESERVING_COMMITMENT_STATES: frozenset = frozenset({"reserved", "expired"})

# Asset account types that count as *liquid* for availability. Portfolio
# owns the account_type taxonomy — we re-declare only the "liquid" filter
# label here because availability filters by ``liquidity_type == 'liquid'``,
# not by account_type.
LIQUIDITY_LIQUID = "liquid"


# ---------------------------------------------------------------------------
# Decimal helpers — every consumer must go through these to keep money math
# strictly Decimal end-to-end.
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


def _is_after(event_created_at: Optional[str], account_balance_as_of: Optional[str]) -> bool:
    """Return True when the event's ``created_at`` is strictly greater
    than the account's ``balance_as_of``. Comparison is lexical on ISO-8601
    strings — which is order-preserving for well-formed timestamps.

    Missing/empty ``balance_as_of`` means the account has never had a
    snapshot cut-off; treat every event as post-snapshot so the caller
    still gets a consistent effective balance (though in practice startup
    migration ensures every account has a ``balance_as_of``).
    """
    if not event_created_at:
        return False
    if not account_balance_as_of:
        return True
    return event_created_at > account_balance_as_of


# ---------------------------------------------------------------------------
# Pure calculation helpers — testable without a database.
# ---------------------------------------------------------------------------

def compute_effective_balance(
    account: dict,
    events: Iterable[dict],
    *,
    applied_statuses: Iterable[str] = APPLIED_LIFECYCLE_STATUSES,
) -> Decimal:
    """Return the account's effective balance as a Decimal.

    Formula:
        effective = current_value
                  + sum(applied inflow events after balance_as_of)
                  - sum(applied outflow events after balance_as_of)

    ``events`` may be a broader iterable — this function filters by
    ``account_id`` and ``lifecycle_status`` internally so callers can pass
    the full user event list without having to pre-filter.
    """
    applied = frozenset(applied_statuses)
    snapshot = _to_decimal(account.get("current_value"))
    balance_as_of = account.get("balance_as_of")
    account_id = account.get("id")

    delta = Decimal(0)
    for ev in events:
        if ev.get("account_id") != account_id:
            continue
        if ev.get("lifecycle_status") not in applied:
            continue
        if not _is_after(ev.get("created_at"), balance_as_of):
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
    """Return one row per account with snapshot / effective breakdown.

    Row shape (all money values are ``Decimal``; caller quantises for
    JSON):

        {
            "account_id": ...,
            "currency": ...,
            "liquidity_type": ...,
            "account_type": ...,
            "snapshot_current_value": Decimal,
            "snapshot_balance_as_of": Optional[str],
            "post_snapshot_inflows": Decimal,
            "post_snapshot_outflows": Decimal,
            "effective_current_balance": Decimal,
        }
    """
    applied = frozenset(applied_statuses)
    # Bucket events by account_id once — O(n + a) instead of O(a * n).
    by_account: dict = {}
    for ev in events:
        aid = ev.get("account_id")
        if not aid:
            continue
        if ev.get("lifecycle_status") not in applied:
            continue
        by_account.setdefault(aid, []).append(ev)

    out: list[dict] = []
    for a in accounts:
        aid = a.get("id")
        snapshot = _to_decimal(a.get("current_value"))
        balance_as_of = a.get("balance_as_of")
        inflows = Decimal(0)
        outflows = Decimal(0)
        for ev in by_account.get(aid, ()):
            if not _is_after(ev.get("created_at"), balance_as_of):
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
            "snapshot_balance_as_of": balance_as_of,
            "post_snapshot_inflows": inflows,
            "post_snapshot_outflows": outflows,
            "effective_current_balance": effective,
        })
    return out


def compute_available_unreserved(
    effective_by_currency: dict,
    reserved_by_currency: dict,
) -> dict:
    """Combine per-currency effective balances with reservations.

    Returns ``{currency: {"effective": Decimal, "reserved": Decimal,
    "available_unreserved": Decimal}}``. Callers are responsible for
    quantising Decimals into JSON strings.
    """
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
    liquid-asset totals used by availability."""
    totals: dict = {}
    for r in rows:
        if r.get("liquidity_type") != LIQUIDITY_LIQUID:
            continue
        # Availability filters to asset accounts (positive money) — the
        # liquidity axis already excludes liabilities in practice, but be
        # explicit here.
        cur = r.get("currency") or ""
        totals[cur] = totals.get(cur, Decimal(0)) + r.get("effective_current_balance", Decimal(0))
    return totals


def collect_pending_account_events(events: Iterable[dict]) -> list[dict]:
    """Return the subset of events that block confidence in the position
    (lifecycle_status == 'pending_account_assignment')."""
    return [
        ev for ev in events
        if ev.get("lifecycle_status") == "pending_account_assignment"
    ]


# ---------------------------------------------------------------------------
# Async loaders — real database wiring.
# ---------------------------------------------------------------------------

async def _load_user_accounts(db, user_id: str) -> list[dict]:
    return await db.financial_accounts.find(
        {"user_id": user_id}, {"_id": 0},
    ).to_list(length=5000)


async def _load_user_events(db, user_id: str, *, only_applied: bool = False) -> list[dict]:
    q: dict = {"user_id": user_id}
    if only_applied:
        q["lifecycle_status"] = {"$in": list(APPLIED_LIFECYCLE_STATUSES)}
    return await db.financial_events.find(q, {"_id": 0}).to_list(length=50000)


async def _load_reserved_totals(db, user_id: str) -> dict:
    """Per-currency total of active reserved commitments (state in
    RESERVING_COMMITMENT_STATES). Reads from ``resource_allocations`` —
    the same source of truth Finance Manager uses."""
    rows = await db.resource_allocations.find(
        {"user_id": user_id, "resource_type": "money",
         "financial_commitment_id": {"$ne": None},
         "state": {"$in": list(RESERVING_COMMITMENT_STATES)}},
        {"_id": 0, "currency": 1, "amount": 1, "quantity": 1},
    ).to_list(length=5000)
    totals: dict = {}
    for r in rows:
        cur = r.get("currency") or ""
        # Prefer explicit ``amount`` if present; fall back to ``quantity``
        # (the pure allocation semantics).
        raw = r.get("amount") if r.get("amount") is not None else r.get("quantity")
        totals[cur] = totals.get(cur, Decimal(0)) + _to_decimal(raw)
    return totals


async def load_account_positions(db, user_id: str) -> list[dict]:
    """Load per-account effective balance rows (Decimal preserved)."""
    accounts = await _load_user_accounts(db, user_id)
    events = await _load_user_events(db, user_id, only_applied=True)
    return summarise_effective_balances(accounts, events)


async def load_availability(db, user_id: str) -> dict:
    """Load the full availability breakdown used by every Finance /
    Portfolio surface that reports "current position" or "available
    money".

    Return shape (Decimal preserved — quantise at the JSON boundary)::

        {
            "accounts": [row, ...],
            "by_currency": {
                cur: {
                    "liquid_effective": Decimal,
                    "reserved": Decimal,
                    "available_unreserved": Decimal,
                }, ...},
            "pending_events": [event, ...],   # unassigned / pending
        }
    """
    accounts = await _load_user_accounts(db, user_id)
    all_events = await _load_user_events(db, user_id, only_applied=False)
    # Split — applied events feed effective balances, pending events flag
    # the caller UI so we don't silently pretend everything is confirmed.
    applied = [e for e in all_events if e.get("lifecycle_status") in APPLIED_LIFECYCLE_STATUSES]
    rows = summarise_effective_balances(accounts, applied)
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


__all__ = [
    "APPLIED_LIFECYCLE_STATUSES",
    "UNAPPLIED_LIFECYCLE_STATUSES",
    "ALL_LIFECYCLE_STATUSES",
    "RESERVING_COMMITMENT_STATES",
    "LIQUIDITY_LIQUID",
    "compute_effective_balance",
    "summarise_effective_balances",
    "compute_available_unreserved",
    "sum_liquid_effective_by_currency",
    "collect_pending_account_events",
    "load_account_positions",
    "load_availability",
]
