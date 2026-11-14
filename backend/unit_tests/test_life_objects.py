"""Life objects and lifetime cost (synthetic data)."""
from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

import ledger
from life_objects import compute_ltc

ACCTS = {"bank": {"id": "bank", "account_type": "bank", "currency": "INR"},
         "card": {"id": "card", "account_type": "credit_card", "currency": "INR"},
         "loan": {"id": "loan", "account_type": "vehicle_loan", "currency": "INR"}}


def _tx(kind, day, amount=None, desc="", **kw):
    tx = ledger.build_transaction("u", ledger.Draft(kind=kind, date=day, currency="INR", amount=amount,
                                                    description=desc, **kw), ACCTS)
    return tx


def _car(**kw):
    return {"id": "car1", "type": "asset", "kind": "car", "name": "Swift", "started_on": "2026-01-01",
            "purchase_price": "800000", "acquisition_costs": "60000", "expected_life_months": 96,
            "residual_value": "200000", "categories": ["fuel", "car_upkeep", "parking_tolls", "vehicle_insurance"],
            "unit": "km", "account_id": None, **kw}


def test_car_costs_what_it_loses_plus_running_costs():
    txs = [_tx("expense", "2026-02-05", "3000", "INDIAN OIL", from_account_id="card", category="expense:fuel"),
           _tx("expense", "2026-03-10", "4500", "SERVICE", from_account_id="bank", category="expense:car_upkeep"),
           _tx("expense", "2026-03-11", "2500", "BIGBASKET", from_account_id="bank", category="expense:groceries"),
           _tx("loan_payment", "2026-03-05", from_account_id="bank", to_account_id="loan",
               principal="12000", interest="3000")]
    checkins = [{"data": {"odometer": "10000"}}, {"data": {"odometer": "12000", "minutes": "90"}}]
    ltc = compute_ltc(_car(account_id="loan"), txs, checkins, {"fuel": 1, "car_upkeep": 1}, "2026-12-31")
    b = ltc["breakdown"]
    assert b["keeping_it"] == {"Car upkeep": "4500.00", "Fuel": "3000.00"}            # groceries not counted
    assert b["cost_of_money"]["interest"] == "3000.00"                                  # EMI interest, not principal
    assert b["getting_it"] == "60000.00"                                                # registration etc.
    lost = Decimal(b["value_lost"])
    assert Decimal("74000") < lost < Decimal("76000")                                   # ~6,250 a month for ~12 months
    assert Decimal(ltc["to_date"]) == Decimal("60000") + lost + Decimal("10500")
    assert ltc["usage"] == "2000.00" and ltc["per_unit"] is not None and ltc["hours"] == "1.50"
    assert Decimal(ltc["lifetime_projected"]) > Decimal(ltc["to_date"])


def test_selling_settles_the_real_cost():
    ltc = compute_ltc(_car(ended_on="2026-06-30", sold_for="650000"), [], [], {}, "2026-12-31")
    assert ltc["breakdown"]["value_lost"] == "150000.00" and ltc["breakdown"]["came_back"] == "0.00"


def test_credit_card_costs_only_its_borrowing():
    card = {"id": "cc", "type": "liability", "kind": "credit_card", "name": "HDFC card",
            "started_on": "2026-01-01", "account_id": "card", "categories": []}
    txs = [_tx("expense", "2026-02-01", "500", "LATE PAYMENT FEE", from_account_id="card", category="expense:fees"),
           _tx("expense", "2026-02-01", "1180", "ANNUAL FEE + GST", from_account_id="card", category="expense:fees"),
           _tx("expense", "2026-02-01", "2400", "FINANCE CHARGES", from_account_id="card", category="expense:interest"),
           _tx("expense", "2026-02-03", "9000", "MYNTRA", from_account_id="card", category="expense:shopping"),
           _tx("refund", "2026-02-10", "300", "CASHBACK", to_account_id="card", category="expense:fees")]
    ltc = compute_ltc(card, txs, [], {}, "2026-12-31")
    assert ltc["breakdown"]["cost_of_money"] == {"interest": "2400.00", "fees": "0.00", "penalties": "500.00",
                                                 "annual_fees": "1180.00"}
    assert ltc["breakdown"]["came_back"] == "300.00" and ltc["breakdown"]["keeping_it"] == {}
    assert ltc["to_date"] == "3780.00"


def test_habit_by_words_per_day():
    smoking = {"id": "sm", "type": "habit", "kind": "smoking", "name": "Smoking", "started_on": "2026-03-01",
               "categories": [], "match_words": ["PAN SHOP"], "unit": "day"}
    txs = [_tx("expense", f"2026-03-0{d}", "40", "UPI/RAJU PAN SHOP", from_account_id="bank") for d in range(1, 6)]
    ltc = compute_ltc(smoking, txs, [], {}, "2026-03-05")
    assert (ltc["to_date"], ltc["usage"], ltc["per_unit"]) == ("200.00", "5.00", "40.00")


def test_two_cars_dont_both_take_the_fuel():
    fuel = _tx("expense", "2026-02-05", "3000", "IOCL", from_account_id="bank", category="expense:fuel")
    assert compute_ltc(_car(), [fuel], [], {"fuel": 2}, "2026-12-31")["breakdown"]["keeping_it"] == {}
    fuel["object_ids"] = ["car1"]
    assert compute_ltc(_car(), [fuel], [], {"fuel": 2}, "2026-12-31")["breakdown"]["keeping_it"] == {"Fuel": "3000.00"}


@pytest.fixture()
def premium(client, monkeypatch):
    monkeypatch.setenv("HYMN_PREMIUM_EMAILS", "rich@example.com")
    out = {}
    for email in ("rich@example.com", "free@example.com"):
        r = client.post("/api/auth/signup", json={"name": "U", "email": email, "password": "correct-horse-battery",
                                                  "security_question": "Q?", "security_answer": "A"})
        out[email] = {"id": r.json()["user"]["id"], "headers": {"Authorization": f"Bearer {r.json()['access_token']}"}}
    return out


def test_api_is_premium_and_uses_projects(client, server, premium):
    free, rich = premium["free@example.com"], premium["rich@example.com"]
    body = {"type": "asset", "kind": "car", "name": "Swift", "started_on": "2026-01-01", "purchase_price": "800000",
            "expected_life_months": 96, "residual_value": "200000"}
    assert client.post("/api/life-objects", headers=free["headers"], json=body).status_code == 403
    r = client.post("/api/life-objects", headers=rich["headers"], json=body)
    assert r.status_code == 201, r.text
    car = r.json()
    assert car["categories"] == ["fuel", "car_upkeep", "parking_tolls", "vehicle_insurance"] and car["unit"] == "km"
    project = asyncio.run(server.db.projects.find_one({"id": car["project_id"]}))
    assert project["title"] == "Swift" and project["life_object"] is True
    asyncio.run(server.db.financial_accounts.insert_one({**ACCTS["bank"], "user_id": rich["id"]}))
    tx = asyncio.run(ledger.record(server.db, rich["id"], ledger.Draft(
        kind="expense", date="2026-02-01", currency="INR", amount="999", from_account_id="bank",
        category="expense:shopping", description="Seat covers"), provenance="user"))
    assert client.post(f"/api/life-objects/{car['id']}/tag", headers=rich["headers"],
                       json={"transaction_ids": [tx["id"]]}).json() == {"matched": 1}
    d = client.get(f"/api/life-objects/{car['id']}", headers=rich["headers"]).json()
    assert d["ltc"]["breakdown"]["keeping_it"] == {"Shopping": "999.00"}
    assert client.get("/api/life-objects", headers=rich["headers"]).json()[0]["ltc"]["to_date"]
    bad = client.post("/api/life-objects", headers=rich["headers"], json={**body, "categories": ["nonsense"]})
    assert bad.status_code == 400
