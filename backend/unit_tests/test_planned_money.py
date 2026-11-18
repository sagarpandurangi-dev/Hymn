"""Planned money: one list for what's coming in and going out."""
from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from bson.decimal128 import Decimal128

import finance_manager
from test_ledger_conversion import _account


@pytest.fixture()
def user(client):
    r = client.post("/api/auth/signup", json={
        "name": "Plan", "email": "planned@example.com", "password": "correct-horse-battery",
        "security_question": "Q?", "security_answer": "A",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    return {"id": body["user"]["id"], "headers": {"Authorization": f"Bearer {body['access_token']}"}}


def _add(client, user, status=201, **kw):
    body = {"currency": "INR", "certainty": "sure", **kw}
    r = client.post("/api/planned-money", headers=user["headers"], json=body)
    assert r.status_code == status, r.text
    return r.json()


def _months(client, user, start="2026-11", count=3):
    r = client.get(f"/api/planned-money/months?start={start}&count={count}", headers=user["headers"])
    assert r.status_code == 200, r.text
    return {row["month"]: row for row in r.json()}


def test_a_normal_month_planned(client, user):
    _add(client, user, title="Salary", direction="in", purpose="income", amount="100000",
         repeat="monthly", start_month="2026-01")
    _add(client, user, title="Rent", direction="out", purpose="spend", amount="25000",
         repeat="monthly", start_month="2026-01")
    _add(client, user, title="SIP", direction="out", purpose="investment", amount="10000",
         repeat="monthly", start_month="2026-01")
    _add(client, user, title="Car insurance", direction="out", purpose="spend", amount="18000",
         repeat="yearly", start_month="2026-12")
    _add(client, user, title="Goa trip", direction="out", purpose="spend", amount="40000",
         repeat="once", date="2027-01-20", set_aside=True)
    _add(client, user, title="Bonus", direction="in", purpose="income", amount="50000",
         repeat="once", date="2026-12-15", certainty="maybe")
    m = _months(client, user)
    assert (m["2026-11"]["income"], m["2026-11"]["spend"], m["2026-11"]["moves"]) == ("100000.00", "25000.00", "10000.00")
    assert m["2026-12"]["spend"] == "43000.00"            # rent + yearly insurance
    assert m["2026-12"]["maybe_in"] == "50000.00"         # bonus kept apart, not counted as sure
    assert m["2027-01"]["set_aside"] == "40000.00"
    assert m["2027-01"]["spend"] == "25000.00"            # insurance is yearly, not monthly


def test_rules_are_checked(client, user):
    _add(client, user, status=400, title="X", direction="in", purpose="spend", amount="10", repeat="once", date="2026-12-01")
    _add(client, user, status=400, title="X", direction="out", purpose="spend", amount="0", repeat="once", date="2026-12-01")
    _add(client, user, status=400, title="X", direction="out", purpose="spend", amount="10", repeat="monthly")
    _add(client, user, status=400, title="X", direction="out", purpose="spend", amount="10",
         repeat="monthly", start_month="2026-12", set_aside=True)


def test_older_records_show_up_read_only(client, server, user):
    db, uid = server.db, user["id"]
    asyncio.run(db.monthly_money_commitments.insert_one({
        "id": "mm1", "user_id": uid, "title": "EMI", "currency": "INR", "amount": Decimal128("15000"),
        "commitment_type": "debt_payment", "fixed_or_flexible": "fixed", "start_month": "2026-01", "end_month": None}))
    asyncio.run(db.expected_incomes.insert_one({
        "id": "ei1", "user_id": uid, "title": "Tax refund", "amount": Decimal128("8000"), "currency": "INR",
        "expected_date": "2026-12-05", "classification": "confirmed", "included_in_forecast": True,
        "received": False, "description": ""}))
    rows = {r["id"]: r for r in client.get("/api/planned-money", headers=user["headers"]).json()}
    assert (rows["mm1"]["purpose"], rows["mm1"]["repeat"], rows["mm1"]["source"]) == ("loan_payment", "monthly", "monthly_commitment")
    assert (rows["ei1"]["direction"], rows["ei1"]["certainty"], rows["ei1"]["editable"]) == ("in", "sure", False)
    r = client.patch("/api/planned-money/mm1", headers=user["headers"], json={"amount": "1"})
    assert r.status_code == 409
    m = _months(client, user, "2026-12", 1)["2026-12"]
    assert (m["income"], m["spend"]) == ("8000.00", "15000.00")


def test_edit_mark_done_and_delete(client, user):
    item = _add(client, user, title="Phone", direction="out", purpose="spend", amount="30000",
                repeat="once", date="2026-12-10", set_aside=True)
    r = client.patch(f"/api/planned-money/{item['id']}", headers=user["headers"], json={"done_amount": "10000"})
    assert r.status_code == 200 and r.json()["remaining_amount"] == "20000.00"
    assert _months(client, user, "2026-12", 1)["2026-12"]["set_aside"] == "20000.00"
    client.patch(f"/api/planned-money/{item['id']}", headers=user["headers"], json={"status": "done"})
    assert _months(client, user, "2026-12", 1)["2026-12"]["set_aside"] == "0.00"
    assert client.get("/api/planned-money", headers=user["headers"]).json() == []
    assert client.delete(f"/api/planned-money/{item['id']}", headers=user["headers"]).status_code == 200


def test_forecast_reads_planned_money(client, server, user, monkeypatch):
    monkeypatch.setattr(finance_manager, "_today_iso", lambda: "2026-11-01")
    _account(server.db, user["id"], "bank", value="200000")
    _add(client, user, title="Salary", direction="in", purpose="income", amount="100000", repeat="monthly", start_month="2026-01")
    _add(client, user, title="Rent", direction="out", purpose="spend", amount="25000", repeat="monthly", start_month="2026-01")
    _add(client, user, title="SIP", direction="out", purpose="investment", amount="10000", repeat="monthly", start_month="2026-01")
    _add(client, user, title="Goa trip", direction="out", purpose="spend", amount="40000", repeat="once",
         date="2026-12-20", set_aside=True)
    _add(client, user, title="Bonus", direction="in", purpose="income", amount="50000", repeat="once",
         date="2026-12-15", certainty="maybe")
    f = client.get("/api/finance/forecast", headers=user["headers"]).json()["by_currency"][0]
    nov, dec = f["months"][0], f["months"][1]
    assert Decimal(nov["projected_liquid_end_of_month"]) == Decimal("265000")      # +100000 -25000 -10000
    assert Decimal(nov["projected_net_worth_end_of_month"]) == Decimal("275000")   # SIP isn't lost
    assert Decimal(dec["projected_liquid_end_of_month"]) == Decimal("290000")      # trip -40000; bonus not counted
    assert dec["maybe_income"] == "50000.00"


def _available(client, user):
    d = client.get("/api/finance/dashboard", headers=user["headers"]).json()
    liq = next(x for x in d["available_liquidity"] if x["currency"] == "INR")
    res = next((x for x in d["reserved"] if x["currency"] == "INR"), {"reserved_total": "0", "planned_set_aside": []})
    return Decimal(liq["available_unreserved"]), Decimal(liq["reserved"]), res


def test_money_set_aside_for_a_one_off_is_held_back(client, server, user):
    _account(server.db, user["id"], "bank", value="200000")
    assert _available(client, user)[:2] == (Decimal("200000"), Decimal("0"))
    trip = _add(client, user, title="Goa trip", direction="out", purpose="spend", amount="40000", repeat="once",
                date="2026-12-20", set_aside=True)
    _add(client, user, title="New phone", direction="out", purpose="spend", amount="30000", repeat="once",
         date="2026-12-01")                                                    # not set aside: not held
    avail, reserved, res = _available(client, user)
    assert (avail, reserved) == (Decimal("160000"), Decimal("40000"))
    assert [(p["title"], p["amount"]) for p in res["planned_set_aside"]] == [("Goa trip", "40000.00")]
    client.patch(f"/api/planned-money/{trip['id']}", headers=user["headers"], json={"done_amount": "15000"})
    assert _available(client, user)[:2] == (Decimal("175000"), Decimal("25000"))     # only what's left is held
    client.patch(f"/api/planned-money/{trip['id']}", headers=user["headers"], json={"status": "done"})
    assert _available(client, user)[:2] == (Decimal("200000"), Decimal("0"))


def test_events_can_be_filtered_to_those_waiting_for_an_account(client, server, user):
    from test_ledger_conversion import _event
    _event(server.db, user["id"], "450", "2026-11-05", description="lunch")
    _event(server.db, user["id"], "700", "2026-11-05", account_id=None, description="cash spend",
           lifecycle_status="pending_account_assignment")
    r = client.get("/api/finance/events?lifecycle_status=pending_account_assignment", headers=user["headers"])
    assert r.status_code == 200 and [e["description"] for e in r.json()] == ["cash spend"]
    assert len(client.get("/api/finance/events", headers=user["headers"]).json()) == 2
    assert client.get("/api/finance/events?lifecycle_status=nonsense", headers=user["headers"]).status_code == 400


def test_plans_dont_count_money_set_aside_twice(client, server, user, monkeypatch):
    import life_plans
    monkeypatch.setattr(finance_manager, "_today_iso", lambda: "2026-11-01")
    _account(server.db, user["id"], "bank", value="200000")
    _add(client, user, title="Goa trip", direction="out", purpose="spend", amount="40000", repeat="once",
         date="2026-12-20", set_aside=True)
    m = asyncio.run(life_plans.money_by(server.db, user["id"], "INR", "2027-03-01"))
    assert (m["now"], m["by_then"]) == (Decimal("160000"), Decimal("160000"))   # held once, not taken off again
