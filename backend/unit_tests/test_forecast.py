"""Forecast: real balance + plans + usual everyday spending (synthetic data)."""
from __future__ import annotations

from decimal import Decimal

import pytest

import finance_manager
from test_ledger_conversion import _account, _event


@pytest.fixture()
def user(client):
    r = client.post("/api/auth/signup", json={
        "name": "Fore", "email": "forecast@example.com", "password": "correct-horse-battery",
        "security_question": "Q?", "security_answer": "A",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    return {"id": body["user"]["id"], "headers": {"Authorization": f"Bearer {body['access_token']}"}}


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(finance_manager, "_today_iso", lambda: "2026-11-16")  # 15 of 30 days left


def _plan(client, user, title, kind, amount):
    r = client.post("/api/portfolio/monthly-money-commitments", headers=user["headers"], json={
        "title": title, "currency": "INR", "amount": amount, "commitment_type": kind,
        "fixed_or_flexible": "fixed", "start_month": "2026-01"})
    assert r.status_code == 201, r.text


def _forecast(client, user):
    r = client.get("/api/finance/forecast", headers=user["headers"])
    assert r.status_code == 200, r.text
    return r.json()["by_currency"][0]


def _spent(db, uid, amount, day):
    _event(db, uid, amount, day, occurred_at=f"{day}T10:00:00+00:00", occurred_at_precision="exact")


def test_everyday_spending_and_saving_are_counted_right(client, server, user):
    db, uid = server.db, user["id"]
    _account(db, uid, "bank", value="300000", as_of="2026-08-01T00:00:00+00:00")
    for month in ("08", "09", "10"):
        _spent(db, uid, "30000", f"2026-{month}-10")
    _plan(client, user, "Salary", "income", "100000")
    _plan(client, user, "Rent", "expense", "20000")
    _plan(client, user, "SIP", "saving", "10000")
    f = _forecast(client, user)
    assert f["usual_monthly_spending"] == "30000.00" and f["history_months_used"] == 3
    nov, dec = f["months"][0], f["months"][1]
    # Rent is planned; the other 10,000 is everyday spending, half of it still ahead in November.
    assert nov["usual_spending"] == "5000.00" and dec["usual_spending"] == "10000.00"
    assert Decimal(nov["projected_liquid_end_of_month"]) == Decimal("275000")      # 210000 + 100000 - 30000 - 5000
    assert Decimal(dec["projected_liquid_end_of_month"]) == Decimal("335000")
    # The SIP moves money; it isn't lost.
    assert Decimal(nov["projected_net_worth_end_of_month"]) == Decimal("285000")   # 210000 + 100000 - 20000 - 5000
    assert Decimal(dec["projected_net_worth_end_of_month"]) == Decimal("355000")
    assert "30000.00 INR a month" in f["basis"]


def test_no_history_says_so(client, server, user):
    _account(server.db, user["id"], "bank", value="50000")
    f = _forecast(client, user)
    assert f["usual_monthly_spending"] == "0.00" and f["confidence"] == "medium"
    assert "Record a few weeks" in f["basis"]
