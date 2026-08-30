"""Network-free unit tests for the authoritative Money Service.

These tests exercise the pure calculation helpers in
``backend/money_service.py`` — no MongoDB, no HTTP, no dotenv, no I/O.
Every case constructs in-memory dicts and asserts on the resulting
``Decimal``. Money precision is preserved end to end (no float math).

Coverage aligns with Foundation Cleanup Batch 2A:
* effective balance = snapshot + post-snapshot inflows - post-snapshot outflows
* events created before ``balance_as_of`` are ignored
* manual balance refresh prevents double counting
* available_unreserved subtracts reservations exactly once
* completed/cancelled reservations are released (via not appearing in the
  reserved bucket the caller supplies)
* unassigned events do not affect balances
* cross-user filtering: the pure helper filters by account_id only —
  the caller supplies the correct account set (the HTTP layer enforces
  user_id at query time). The tests below verify the account_id filter.
* currency: the pure helper does NOT convert currencies; the caller is
  responsible for filtering by currency prior to invoking availability.
* decimal precision preserved
"""
from __future__ import annotations

import importlib
import sys
from decimal import Decimal
from pathlib import Path

import pytest

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


@pytest.fixture()
def money_service():
    if "money_service" in sys.modules:
        return importlib.reload(sys.modules["money_service"])
    return importlib.import_module("money_service")


# ---------------------------------------------------------------------------
# Test data fixtures — plain dicts mirror the shape stored in Mongo.
# ---------------------------------------------------------------------------

ACCT_A = {
    "id": "acct-a",
    "user_id": "u1",
    "currency": "USD",
    "account_type": "bank",
    "liquidity_type": "liquid",
    "name": "Checking",
    "current_value": Decimal("1000.00"),
    "balance_as_of": "2026-06-01T00:00:00+00:00",
}
ACCT_B = {
    "id": "acct-b",
    "user_id": "u1",
    "currency": "USD",
    "account_type": "cash",
    "liquidity_type": "liquid",
    "name": "Wallet",
    "current_value": Decimal("50.00"),
    "balance_as_of": "2026-06-01T00:00:00+00:00",
}
ACCT_ILLIQUID = {
    "id": "acct-real",
    "user_id": "u1",
    "currency": "USD",
    "account_type": "real_estate",
    "liquidity_type": "illiquid",
    "name": "House",
    "current_value": Decimal("500000"),
    "balance_as_of": "2026-06-01T00:00:00+00:00",
}


def _ev(**kw):
    d = {
        "user_id": "u1",
        "currency": "USD",
        "amount": Decimal("0"),
        "direction": "outflow",
        "account_id": None,
        "lifecycle_status": "awaiting_reconciliation",
        "created_at": "2026-06-02T09:00:00+00:00",
    }
    d.update(kw)
    return d


# ---------------------------------------------------------------------------
# compute_effective_balance
# ---------------------------------------------------------------------------

def test_snapshot_plus_post_events_produces_effective(money_service):
    events = [
        _ev(account_id="acct-a", direction="outflow", amount=Decimal("40.00"), created_at="2026-06-02T09:00Z"),
        _ev(account_id="acct-a", direction="inflow", amount=Decimal("200.00"), created_at="2026-06-03T10:00Z"),
    ]
    result = money_service.compute_effective_balance(ACCT_A, events)
    assert result == Decimal("1160.00")


def test_events_before_balance_as_of_are_not_applied(money_service):
    events = [
        _ev(account_id="acct-a", direction="outflow", amount=Decimal("40.00"),
            created_at="2026-05-31T09:00:00+00:00"),  # BEFORE snapshot
        _ev(account_id="acct-a", direction="outflow", amount=Decimal("10.00"),
            created_at="2026-06-02T09:00:00+00:00"),  # AFTER snapshot
    ]
    result = money_service.compute_effective_balance(ACCT_A, events)
    assert result == Decimal("990.00")  # only the post-snapshot event applied


def test_manual_balance_refresh_prevents_double_counting(money_service):
    # An event existed before the balance was refreshed. When the user
    # refreshes the account balance, balance_as_of moves forward; the
    # event must NOT be reapplied.
    account = dict(ACCT_A)
    account["current_value"] = Decimal("960.00")
    account["balance_as_of"] = "2026-06-02T10:00:00+00:00"
    pre_refresh_event = _ev(account_id="acct-a", direction="outflow", amount=Decimal("40.00"),
                             created_at="2026-06-02T09:00:00+00:00")
    result = money_service.compute_effective_balance(account, [pre_refresh_event])
    assert result == Decimal("960.00")


def test_unassigned_event_does_not_silently_affect_balance(money_service):
    unassigned = _ev(account_id=None, direction="outflow", amount=Decimal("50.00"),
                     lifecycle_status="pending_account_assignment", created_at="2026-06-02T09:00Z")
    result = money_service.compute_effective_balance(ACCT_A, [unassigned])
    assert result == Decimal("1000.00")


def test_only_applied_lifecycle_statuses_affect_balance(money_service):
    # void, pending_account_assignment are unapplied.
    events = [
        _ev(account_id="acct-a", direction="outflow", amount=Decimal("40.00"),
            lifecycle_status="void", created_at="2026-06-02T09:00Z"),
        _ev(account_id="acct-a", direction="outflow", amount=Decimal("60.00"),
            lifecycle_status="pending_account_assignment", created_at="2026-06-02T09:00Z"),
        _ev(account_id="acct-a", direction="outflow", amount=Decimal("10.00"),
            lifecycle_status="matched", created_at="2026-06-02T09:00Z"),
        _ev(account_id="acct-a", direction="outflow", amount=Decimal("5.00"),
            lifecycle_status="resolved_unplanned", created_at="2026-06-02T09:00Z"),
    ]
    result = money_service.compute_effective_balance(ACCT_A, events)
    assert result == Decimal("985.00")  # only matched + resolved_unplanned counted


def test_events_belong_to_only_their_account(money_service):
    events = [
        _ev(account_id="acct-a", direction="outflow", amount=Decimal("30")),
        _ev(account_id="acct-b", direction="outflow", amount=Decimal("20")),
    ]
    assert money_service.compute_effective_balance(ACCT_A, events) == Decimal("970")
    assert money_service.compute_effective_balance(ACCT_B, events) == Decimal("30")


# ---------------------------------------------------------------------------
# summarise_effective_balances — the per-account row summary used by
# transparency-heavy surfaces.
# ---------------------------------------------------------------------------

def test_summarise_effective_balances_row_shape(money_service):
    events = [
        _ev(account_id="acct-a", direction="outflow", amount=Decimal("40"),
            created_at="2026-06-02T09:00Z"),
        _ev(account_id="acct-a", direction="inflow", amount=Decimal("100"),
            created_at="2026-06-03T09:00Z"),
        _ev(account_id="acct-b", direction="outflow", amount=Decimal("5"),
            created_at="2026-06-02T10:00Z"),
    ]
    rows = money_service.summarise_effective_balances([ACCT_A, ACCT_B, ACCT_ILLIQUID], events)
    assert len(rows) == 3
    row_a = next(r for r in rows if r["account_id"] == "acct-a")
    assert row_a["snapshot_current_value"] == Decimal("1000.00")
    assert row_a["snapshot_balance_as_of"] == "2026-06-01T00:00:00+00:00"
    assert row_a["post_snapshot_inflows"] == Decimal("100")
    assert row_a["post_snapshot_outflows"] == Decimal("40")
    assert row_a["effective_current_balance"] == Decimal("1060")
    assert row_a["liquidity_type"] == "liquid"


# ---------------------------------------------------------------------------
# sum_liquid_effective_by_currency + compute_available_unreserved
# ---------------------------------------------------------------------------

def test_available_subtracts_reservations_exactly_once(money_service):
    events = [
        _ev(account_id="acct-a", direction="outflow", amount=Decimal("40"),
            created_at="2026-06-02T09:00Z"),
    ]
    rows = money_service.summarise_effective_balances([ACCT_A, ACCT_B], events)
    liquid_totals = money_service.sum_liquid_effective_by_currency(rows)
    reserved_totals = {"USD": Decimal("200")}
    avail = money_service.compute_available_unreserved(liquid_totals, reserved_totals)
    # Effective liquid: (1000-40) + 50 = 1010; minus 200 reserved = 810.
    # Crucially, the outflow is NOT subtracted again at the aggregate.
    assert avail["USD"]["effective"] == Decimal("1010")
    assert avail["USD"]["reserved"] == Decimal("200")
    assert avail["USD"]["available_unreserved"] == Decimal("810")


def test_completed_or_cancelled_reservations_are_released(money_service):
    # The caller supplies only *active* reservations. Completed/cancelled
    # commitments simply DON'T appear in the reservations map.
    liquid_totals = {"USD": Decimal("500")}
    reserved_totals = {"USD": Decimal("0")}  # nothing active
    avail = money_service.compute_available_unreserved(liquid_totals, reserved_totals)
    assert avail["USD"]["available_unreserved"] == Decimal("500")


def test_illiquid_accounts_do_not_add_to_available(money_service):
    events: list = []
    rows = money_service.summarise_effective_balances([ACCT_A, ACCT_ILLIQUID], events)
    liquid_totals = money_service.sum_liquid_effective_by_currency(rows)
    assert liquid_totals.get("USD") == Decimal("1000")  # ACCT_A only, not the house


def test_multi_currency_isolated(money_service):
    acct_eur = dict(ACCT_A)
    acct_eur["id"] = "acct-eur"
    acct_eur["currency"] = "EUR"
    acct_eur["current_value"] = Decimal("2000")
    rows = money_service.summarise_effective_balances([ACCT_A, acct_eur], [])
    liquid_totals = money_service.sum_liquid_effective_by_currency(rows)
    assert liquid_totals == {"USD": Decimal("1000"), "EUR": Decimal("2000")}


def test_pending_events_collected_for_transparency(money_service):
    events = [
        _ev(account_id=None, lifecycle_status="pending_account_assignment",
            amount=Decimal("15"), direction="outflow"),
        _ev(account_id="acct-a", lifecycle_status="awaiting_reconciliation",
            amount=Decimal("10"), direction="outflow"),
    ]
    pending = money_service.collect_pending_account_events(events)
    assert len(pending) == 1
    assert pending[0]["lifecycle_status"] == "pending_account_assignment"


# ---------------------------------------------------------------------------
# Decimal precision preserved end-to-end.
# ---------------------------------------------------------------------------

def test_decimal_precision_preserved(money_service):
    account = dict(ACCT_A)
    account["current_value"] = Decimal("1000.123456789")
    events = [
        _ev(account_id="acct-a", direction="outflow", amount=Decimal("0.000000001"),
            created_at="2026-06-02T09:00Z"),
    ]
    result = money_service.compute_effective_balance(account, events)
    # Must NOT round or truncate — Decimal precision is preserved.
    assert result == Decimal("1000.123456788")


def test_lexical_iso_timestamp_ordering(money_service):
    # ISO-8601 strings sort correctly lexically — this is a property
    # the module relies on to compare event.created_at vs
    # account.balance_as_of without dateutil.
    account = dict(ACCT_A)
    account["balance_as_of"] = "2026-06-02T09:00:00+00:00"
    just_before = _ev(account_id="acct-a", direction="outflow", amount=Decimal("1"),
                       created_at="2026-06-02T08:59:59+00:00")
    just_after = _ev(account_id="acct-a", direction="outflow", amount=Decimal("2"),
                      created_at="2026-06-02T09:00:00.001+00:00")
    result = money_service.compute_effective_balance(account, [just_before, just_after])
    assert result == Decimal("998")  # only the "after" event applied


# ---------------------------------------------------------------------------
# Currency-mismatch is enforced by the endpoint, not the pure helper — the
# helper reasons over one account at a time. This test locks in that the
# helper does NOT accidentally cross currencies when the caller pre-groups
# by currency correctly (baseline safety).
# ---------------------------------------------------------------------------

def test_currency_mismatch_between_accounts_isolated(money_service):
    acct_eur = dict(ACCT_A)
    acct_eur["id"] = "acct-eur"
    acct_eur["currency"] = "EUR"
    # An event mis-linked to a USD account (currency stamped as EUR)
    # cannot happen because create_event / create_checkin refuse this,
    # but if it *did* the pure helper still sums by account_id — the
    # aggregator groups by currency using the ACCOUNT's currency, so a
    # bogus event never contaminates a different currency's totals.
    events = [
        _ev(account_id="acct-a", currency="EUR", amount=Decimal("10"),
            direction="outflow", created_at="2026-06-02T09:00Z"),
    ]
    rows = money_service.summarise_effective_balances([ACCT_A, acct_eur], events)
    totals = money_service.sum_liquid_effective_by_currency(rows)
    # ACCT_A is USD; the (bogus, would-have-been-rejected) event still
    # only affects that ONE account's row.
    assert totals["USD"] == Decimal("990")
    assert totals["EUR"] == Decimal("1000")
