"""One screen load reads the money book once; the next request sees new data."""
from __future__ import annotations

import pytest

import ledger_sync
from test_ledger_conversion import _account, _event
from test_ledger_sync import _convert


@pytest.fixture()
def user(client):
    r = client.post("/api/auth/signup", json={"name": "M", "email": "memo@example.com",
                                              "password": "correct-horse-battery", "security_question": "Q?",
                                              "security_answer": "A"})
    b = r.json()
    return {"id": b["user"]["id"], "headers": {"Authorization": f"Bearer {b['access_token']}"}}


def test_finance_tab_syncs_once_per_request(client, server, user, monkeypatch):
    _account(server.db, user["id"], "bank")
    _event(server.db, user["id"], "500", "2026-11-05")
    _convert(client, user)
    calls = []
    real = ledger_sync._sync

    async def counting(db, uid):
        calls.append(uid)
        return await real(db, uid)
    monkeypatch.setattr(ledger_sync, "_sync", counting)
    assert client.get("/api/finance/dashboard", headers=user["headers"]).status_code == 200
    assert len(calls) == 1                                  # was once per balance / availability / month read
    before = client.get("/api/finance/position", headers=user["headers"]).json()
    _event(server.db, user["id"], "1000", "2026-11-06")    # recorded between two requests
    after = client.get("/api/finance/position", headers=user["headers"]).json()
    value = lambda p: p["currencies"][0]["accounts_asset"][0]["current_value"]
    assert float(value(before)) - float(value(after)) == 1000.0


def test_finance_screen_in_one_call(client, server, user):
    _account(server.db, user["id"], "bank")
    client.post("/api/planned-money", headers=user["headers"], json={
        "title": "Rent", "direction": "out", "purpose": "spend", "amount": "25000", "currency": "INR",
        "repeat": "monthly", "start_month": "2026-01"})
    r = client.get("/api/screens/finance", headers=user["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert "position" in body["dashboard"] and "available_liquidity" in body["dashboard"]
    assert body["planned_upcoming"][0]["title"] == "Rent"
    assert body["planned_this_month"][0]["spend"] == "25000.00"
