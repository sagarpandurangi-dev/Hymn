"""One spending truth: Today's Spending and Finance use the same rule."""
from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import pytest

import money_service

DAY = "2026-11-10"


@pytest.fixture()
def user(client):
    r = client.post("/api/auth/signup", json={
        "name": "Spender", "email": "spend@example.com", "password": "correct-horse-battery",
        "security_question": "Q?", "security_answer": "A",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    return {"id": body["user"]["id"], "headers": {"Authorization": f"Bearer {body['access_token']}"}}


@pytest.fixture()
def account(client, user):
    r = client.post("/api/portfolio/financial-accounts", headers=user["headers"], json={
        "account_type": "bank", "name": "Salary", "currency": "INR", "current_value": "100000",
        "liquidity_type": "liquid", "fixed_or_flexible": "flexible",
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _event(db, user_id, **overrides):
    ev = {
        "id": str(uuid.uuid4()), "user_id": user_id, "amount": "100.00", "currency": "INR",
        "direction": "outflow", "event_date": DAY, "description": "Coffee",
        "source": "manual", "confirmation_status": "confirmed",
        "lifecycle_status": "awaiting_reconciliation", "account_id": "acct-1",
        "occurred_at": None, "occurred_at_precision": "date_only",
    }
    ev.update(overrides)
    asyncio.run(db.financial_events.insert_one(ev))
    return ev


def _today(client, user):
    r = client.get(f"/api/spending?date={DAY}", headers=user["headers"])
    assert r.status_code == 200, r.text
    return r.json()


def _monthly(db, user_id):
    return asyncio.run(money_service.monthly_actual_spending(db, user_id, DAY[:7], "INR"))


# ---------------------------------------------------------------------------
# The rule
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("overrides, counts", [
    ({}, True),
    ({"direction": "inflow"}, False),
    ({"confirmation_status": "pending"}, False),
    ({"lifecycle_status": "pending_account_assignment", "account_id": None}, False),
    ({"lifecycle_status": "pending_deduplication"}, False),
    ({"lifecycle_status": "void"}, False),
    ({"account_id": None}, False),
    ({"event_date": None}, False),
    ({"occurred_at": None, "occurred_at_precision": "date_only"}, True),
])
def test_counts_as_spending(overrides, counts):
    ev = {
        "direction": "outflow", "confirmation_status": "confirmed",
        "lifecycle_status": "matched", "account_id": "a", "event_date": DAY,
    }
    ev.update(overrides)
    assert money_service.counts_as_spending(ev) is counts


# ---------------------------------------------------------------------------
# Today and Finance agree
# ---------------------------------------------------------------------------

def test_today_equals_finance_for_the_same_events(client, user, server):
    _event(server.db, user["id"], amount="120.50")
    _event(server.db, user["id"], amount="79.50", lifecycle_status="matched")
    _event(server.db, user["id"], amount="999", confirmation_status="pending",
           lifecycle_status="pending_deduplication")
    _event(server.db, user["id"], amount="555", direction="inflow")
    _event(server.db, user["id"], amount="10", event_date="2026-11-11")

    today = _today(client, user)
    assert today["groups"][0]["total"] == "200.00"
    assert today["needs_review"] == 1
    assert _monthly(server.db, user["id"]) == Decimal("210.00")  # includes the 11th


def test_date_only_spends_count_in_finance(server, user):
    _event(server.db, user["id"], amount="40", occurred_at=None)
    assert _monthly(server.db, user["id"]) == Decimal("40")


def test_checkin_spend_without_account_waits_for_an_account(client, user, account):
    r = client.post("/api/checkins", headers=user["headers"], json={
        "type": "life", "title": "Lunch", "date": DAY, "time": "13:00",
        "money_spent": "250", "money_currency": "INR",
    })
    assert r.status_code == 201, r.text
    today = _today(client, user)
    assert today["groups"] == []
    assert today["needs_account"] == 1


def test_checkin_spend_with_account_shows_with_its_checkin_details(client, user, account):
    r = client.post("/api/checkins", headers=user["headers"], json={
        "type": "life", "title": "Lunch", "date": DAY, "time": "13:00", "notes": "team",
        "money_spent": "250", "money_currency": "INR", "account_id": account,
    })
    assert r.status_code == 201, r.text
    checkin_id = r.json()["id"]
    today = _today(client, user)
    entries = today["groups"][0]["entries"]
    assert [(e["id"], e["title"], e["time"], e["amount"], e["notes"]) for e in entries] == [
        (checkin_id, "Lunch", "13:00", "250", "team"),
    ]
    assert today["needs_account"] == 0


def test_other_users_spending_is_invisible(client, user, server):
    _event(server.db, "someone-else", amount="500")
    assert _today(client, user)["groups"] == []
