"""Accepting a plan locks it into planned money and tasks; drift is caught monthly."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

import finance_manager
import life_plans
import nudges


@pytest.fixture()
def user(client, server, monkeypatch):
    monkeypatch.setattr(finance_manager, "_today_iso", lambda: "2026-11-01")
    monkeypatch.setattr(life_plans, "local_now", lambda u: datetime(2026, 11, 1, 9, 0))
    r = client.post("/api/auth/signup", json={"name": "L", "email": "lock@example.com",
                                              "password": "correct-horse-battery", "security_question": "Q?",
                                              "security_answer": "A"})
    b = r.json()
    u = {"id": b["user"]["id"], "headers": {"Authorization": f"Bearer {b['access_token']}"}}
    asyncio.run(server.db.financial_accounts.insert_one({
        "id": "bank", "user_id": u["id"], "name": "Bank", "account_type": "bank", "currency": "INR",
        "current_value": "100000", "balance_as_of": "2026-10-31T00:00:00+00:00", "liquidity_type": "liquid"}))
    for title, direction, purpose, amount in (("Salary", "in", "income", "100000"), ("Rent", "out", "spend", "70000")):
        client.post("/api/planned-money", headers=u["headers"], json={
            "title": title, "direction": direction, "purpose": purpose, "amount": amount, "currency": "INR",
            "repeat": "monthly", "start_month": "2026-01"})
    return u


PLAN = {"title": "Goa trip", "target_date": "2027-03-15", "requirements": [
    {"area": "money", "what": "Trip fund", "kind": "money", "amount": "200000", "currency": "INR"},
    {"area": "money", "what": "Flights", "kind": "money", "amount": "30000", "currency": "INR"},
    {"area": "family", "what": "Partner can take leave", "kind": "condition"}],
    "risks": [{"area": "work", "what": "Leave not approved", "mitigation": "Apply for leave in December"}]}


def test_accept_locks_in_and_drop_undoes(client, server, user):
    h = user["headers"]
    plan = client.post("/api/life-plans", headers=h, json=PLAN).json()
    done = client.post(f"/api/life-plans/{plan['id']}/accept", headers=h).json()
    assert done["status"] == "active" and done["drift"] == []
    items = {i["title"]: i for i in client.get("/api/planned-money", headers=h).json()}
    save = items["Save for: Trip fund"]
    assert (save["amount"], save["repeat"], save["start_month"], save["end_month"], save["purpose"]) == \
        ("25000.00", "monthly", "2026-11", "2027-02", "saving")                   # (₹2L − ₹1L) over 4 months
    flights = items["Set aside: Flights"]
    assert (flights["repeat"], flights["date"], flights["set_aside"]) == ("once", "2027-03-15", True)
    titles = {t["title"] for t in asyncio.run(server.db.tasks.find({"user_id": user["id"]}).to_list(None))}
    assert titles == {"Reach ₹200,000 for Trip fund", "Find out: Partner can take leave",
                      "Reduce a risk: Apply for leave in December"}
    # Its own monthly saving doesn't make the plan look short.
    again = client.get(f"/api/life-plans/{plan['id']}", headers=h).json()
    trip = next(r for r in again["requirements"] if r["what"] == "Trip fund")
    assert trip["status"] == "by_then" and again["drift"] == []
    # Accepting twice doesn't duplicate anything.
    client.post(f"/api/life-plans/{plan['id']}/accept", headers=h)
    assert asyncio.run(server.db.tasks.count_documents({"user_id": user["id"]})) == 3
    client.delete(f"/api/life-plans/{plan['id']}", headers=h)
    assert asyncio.run(server.db.tasks.count_documents({"user_id": user["id"]})) == 0
    assert all(i["status"] == "cancelled" for i in asyncio.run(
        server.db.planned_money.find({"life_plan_id": plan["id"]}).to_list(None)))


def test_drift_is_caught_and_nudged_on_the_first(client, server, user):
    h = user["headers"]
    plan = client.post("/api/life-plans", headers=h, json=PLAN).json()
    client.post(f"/api/life-plans/{plan['id']}/accept", headers=h)
    # Life happens: a new ₹40k EMI from this month.
    client.post("/api/planned-money", headers=h, json={
        "title": "Car EMI", "direction": "out", "purpose": "loan_payment", "amount": "40000", "currency": "INR",
        "repeat": "monthly", "start_month": "2026-11"})
    now = client.get(f"/api/life-plans/{plan['id']}", headers=h).json()
    assert [d["what"] for d in now["drift"]] == ["Trip fund"] and now["drift"][0]["was"] == "by_then"
    asyncio.run(nudges.ensure_nudge_indexes(server.db))     # one nudge per key, as in production
    first = datetime(2026, 12, 1, 5, 0, tzinfo=timezone.utc)   # 10:30 in India
    asyncio.run(server.db.users.update_one({"id": user["id"]}, {"$set": {"timezone": "Asia/Kolkata"}}))
    u = asyncio.run(server.db.users.find_one({"id": user["id"]}))
    nudge = asyncio.run(nudges._plan_check(server.db, u, nudges.merge_settings(None), first))
    assert nudge["kind"] == "plan_drift" and nudge["title"] == "Goa trip needs attention"
    assert nudge["body"].startswith("Trip fund has slipped")
    assert asyncio.run(nudges._plan_check(server.db, u, nudges.merge_settings(None), first)) is None  # once a month
    assert asyncio.run(nudges._plan_check(server.db, u, nudges.merge_settings(None),
                                          datetime(2026, 12, 2, 5, 0, tzinfo=timezone.utc))) is None
