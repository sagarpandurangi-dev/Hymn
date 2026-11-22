"""The redesigned screens' answers (Today, Life, the Money headline) and the
wording rules behind them: ₹12,450 / ₹1.84 L, "Tuesday", "3h 20m"."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

import display

TODAY = date.today()


def test_money_reads_the_way_people_say_it():
    assert display.money(12450) == "₹12,450"
    assert display.money("12450.00") == "₹12,450"
    assert display.money(184500) == "₹1.85 L" or display.money(184500) == "₹1.84 L"
    assert display.money(184000) == "₹1.84 L"
    assert display.money(100000) == "₹1 L"
    assert display.money(25_000_000) == "₹2.5 Cr"
    assert display.money(1234567, short=False) == "₹12,34,567"
    assert display.money(-1200) == "− ₹1,200"
    assert display.money(110000, sign=True) == "+ ₹1.1 L"
    assert display.money("49.50") == "₹49.5"
    assert display.money(1250, "usd") == "USD 1,250"
    assert display.money(None) == "" and display.money("abc") == ""


def test_days_and_durations():
    assert display.day(TODAY, TODAY) == "Today"
    assert display.day(TODAY + timedelta(days=1), TODAY) == "Tomorrow"
    assert display.day(TODAY - timedelta(days=1), TODAY) == "Yesterday"
    in3 = TODAY + timedelta(days=3)
    assert display.day(in3.isoformat(), TODAY) == in3.strftime("%A")
    far = date(TODAY.year + 1, 3, 5)
    assert display.day(far, TODAY) == f"5 Mar {TODAY.year + 1}"
    assert display.duration(45) == "45 min" and display.duration(180) == "3h" and display.duration(200) == "3h 20m"
    assert display.greeting(7, "Sagar Pandurangi") == "Good morning, Sagar"
    assert display.greeting(20, None) == "Good evening"


@pytest.fixture()
def me(client):
    b = client.post("/api/auth/signup", json={"name": "Sagar", "email": "today@example.com", "password": "correct-horse-battery",
                                              "security_question": "Q?", "security_answer": "A"}).json()
    return {"Authorization": f"Bearer {b['access_token']}"}


def _iso(days):
    return (TODAY + timedelta(days=days)).isoformat()


def test_today_leads_with_your_day(client, me):
    client.post("/api/tasks", headers=me, json={"title": "Pay electricity bill", "due_date": _iso(0)})
    client.post("/api/tasks", headers=me, json={"title": "Return library book", "due_date": _iso(-2)})
    client.post("/api/tasks", headers=me, json={"title": "Renew passport", "due_date": _iso(5)})
    run = client.post("/api/tasks", headers=me, json={"title": "Morning run", "due_date": _iso(0)}).json()
    client.put(f"/api/tasks/{run['id']}", headers=me, json={"status": "done"})
    bday = (TODAY + timedelta(days=3))
    client.post("/api/people", headers=me, json={"name": "Amma", "relation": "mother", "circle": "inner",
                                                 "birthday": f"1962-{bday:%m-%d}", "birthday_gift": "3000"})
    client.post("/api/portfolio/financial-accounts", headers=me, json={
        "account_type": "bank", "name": "Savings", "currency": "INR", "current_value": "12450",
        "liquidity_type": "liquid", "fixed_or_flexible": "flexible"})
    t = client.get("/api/screens/today", headers=me).json()
    assert t["greeting"].endswith(", Sagar")
    assert [(x["title"], x["done"]) for x in t["things"]] == [
        ("Morning run", True), ("Return library book", False), ("Pay electricity bill", False)]
    assert t["things"][1]["note"].startswith("since ")                # overdue first, and says so
    assert "Renew passport" not in str(t["things"])                    # not due yet
    h = t["highlight"]
    assert h["title"] == "Amma's birthday" and h["when"] == bday.strftime("%A")
    assert h["detail"] == f"Turns {bday.year - 1962} · gift budget ₹3,000"
    assert t["money"]["label"] == "₹12,450"
    assert t["free_time"]["minutes"] >= 0 and t["free_time"]["when"] in ("today", "this evening")
    assert t["setup"]["of"] >= 1 and t["setup"]["next"]["title"]


def test_today_falls_back_to_a_payment_due_and_says_nothing_when_empty(client, me):
    t = client.get("/api/screens/today", headers=me).json()
    assert t["things"] == [] and t["highlight"] is None and t["review"] is None
    client.post("/api/planned-money", headers=me, json={"title": "Car insurance", "direction": "out", "purpose": "spend",
                                                        "amount": "18000", "currency": "INR", "date": _iso(2)})
    h = client.get("/api/screens/today", headers=me).json()["highlight"]
    assert (h["kind"], h["title"], h["detail"]) == ("money_due", "Car insurance", "₹18,000")


def test_life_says_how_each_area_is_going(client, me):
    areas = {a["key"]: a for a in client.get("/api/screens/life", headers=me).json()["areas"]}
    assert list(areas) == ["health", "family", "learning", "work", "plans"]
    assert all(a["status"] == "setup" for a in areas.values())
    assert areas["family"]["line"] == "Add the people who matter most."
    soon = TODAY + timedelta(days=4)
    client.post("/api/people", headers=me, json={"name": "Amma", "relation": "mother", "circle": "inner",
                                                 "birthday": f"{soon:%m-%d}"})
    fam = {a["key"]: a for a in client.get("/api/screens/life", headers=me).json()["areas"]}["family"]
    assert fam["status"] == "attention" and fam["line"] == f"Amma's birthday on {soon.strftime('%A')}."


def test_the_money_headline_is_short_and_friendly(client, me):
    client.post("/api/portfolio/financial-accounts", headers=me, json={
        "account_type": "bank", "name": "Savings", "currency": "INR", "current_value": "184000",
        "liquidity_type": "liquid", "fixed_or_flexible": "flexible"})
    client.post("/api/planned-money", headers=me, json={"title": "Rent", "direction": "out", "purpose": "spend",
                                                        "amount": "32000", "currency": "INR", "repeat": "monthly",
                                                        "start_month": TODAY.isoformat()[:7]})
    client.post("/api/planned-money", headers=me, json={"title": "Bonus", "direction": "in", "purpose": "income",
                                                        "amount": "110000", "currency": "INR", "date": _iso(10)})
    h = client.get("/api/screens/finance", headers=me).json()["headline"]
    assert h["net_worth_label"] == "₹1.84 L" and h["left_to_spend_label"]
    rows = {r["title"]: r for r in h["coming_up"]}
    assert rows["Rent"]["when"] == "Every month" and rows["Rent"]["amount_label"] == "₹32,000"
    assert rows["Bonus"]["amount_label"] == "+ ₹1.1 L"
