"""After conversion, Today and Finance read the ledger (synthetic data)."""
from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

import ledger
import money_service
from test_ledger_conversion import _account, _event
from test_ledger_sync import _convert


@pytest.fixture()
def user(client):
    r = client.post("/api/auth/signup", json={
        "name": "Switch", "email": "switch@example.com", "password": "correct-horse-battery",
        "security_question": "Q?", "security_answer": "A",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    return {"id": body["user"]["id"], "headers": {"Authorization": f"Bearer {body['access_token']}"}}


@pytest.fixture()
def book(client, server, user):
    db, uid = server.db, user["id"]
    _account(db, uid, "bank")                                         # 100000 held
    _account(db, uid, "card", account_type="credit_card", value="3000")  # 3000 owed
    asyncio.run(db.checkins.insert_one({"id": "c1", "user_id": uid, "title": "Lunch with team",
                                        "time": "13:00", "notes": "", "goal_id": "g1"}))
    _event(db, uid, "450", "2026-11-05", checkin_id="c1", description="lunch")
    _event(db, uid, "700", "2026-11-05", account_id="card", description="Shoes")
    return db, uid


def _today(client, user, day="2026-11-05"):
    r = client.get(f"/api/spending?date={day}", headers=user["headers"])
    assert r.status_code == 200, r.text
    return r.json()


def _position(client, user):
    r = client.get("/api/finance/position", headers=user["headers"])
    assert r.status_code == 200, r.text
    rows = r.json()["currencies"][0]
    return {a["id"]: Decimal(a["current_value"]) for a in rows["accounts_asset"] + rows["accounts_liability"]}, rows


def test_before_conversion_nothing_changes(client, server, user, book):
    before = _today(client, user)
    assert before["groups"][0]["total"] == "1150.00"
    values, _ = _position(client, user)
    assert values["card"] == Decimal("3000")  # old engine: liabilities stay on the typed value


def test_today_reads_the_ledger_after_conversion(client, server, user, book):
    db, uid = book
    _convert(client, user)
    # A statement-only spend the old records never had now shows on Today.
    asyncio.run(ledger.record(db, uid, ledger.Draft(
        kind="expense", date="2026-11-05", currency="INR", amount="99", from_account_id="bank",
        category="expense:food", description="SWIGGY"), provenance="user", evidence_ids=["stmt:s1:3"]))
    day = _today(client, user)
    g = day["groups"][0]
    assert g["total"] == "1249.00"
    titles = {e["title"]: e for e in g["entries"]}
    assert set(titles) == {"Lunch with team", "Shoes", "SWIGGY"}
    assert titles["Lunch with team"]["goal_id"] == "g1" and titles["Lunch with team"]["id"] == "c1"
    # A new check-in spend after conversion arrives too.
    _event(db, uid, "51", "2026-11-05", description="Chai")
    assert _today(client, user)["groups"][0]["total"] == "1300.00"


def test_finance_balances_come_from_the_ledger(client, server, user, book):
    db, uid = book
    _convert(client, user)
    values, rows = _position(client, user)
    assert values["bank"] == Decimal("99550.00")
    assert values["card"] == Decimal("3700.00")  # card spend raises what's owed
    assert Decimal(rows["net_worth"]) == Decimal("95850.00")
    # Paying the card bill moves both, and isn't spending.
    asyncio.run(ledger.record(db, uid, ledger.Draft(
        kind="card_settlement", date="2026-11-20", currency="INR", amount="3700",
        from_account_id="bank", to_account_id="card"), provenance="user"))
    values, rows = _position(client, user)
    assert (values["bank"], values["card"]) == (Decimal("95850.00"), Decimal("0.00"))
    assert Decimal(rows["net_worth"]) == Decimal("95850.00")
    month = asyncio.run(money_service.monthly_actual_spending(db, uid, "2026-11", "INR"))
    assert month == Decimal("1150")


def test_available_money_follows_the_ledger(client, server, user, book):
    db, uid = book
    _convert(client, user)
    avail = asyncio.run(money_service.load_availability(db, uid))
    assert avail["by_currency"]["INR"]["liquid_effective"] == Decimal("99550.00")
    r = client.get("/api/finance/dashboard", headers=user["headers"])
    assert r.status_code == 200, r.text
    assert Decimal(r.json()["available_liquidity"][0]["liquid_effective"]) == Decimal("99550.00")
