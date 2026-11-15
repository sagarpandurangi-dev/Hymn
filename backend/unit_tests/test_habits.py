"""Habits to change: for-what, no streaks, urges, welcome back, freed money and hours."""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pytest

from habits import progress

TODAY = date.today()


def _day(n):
    return (TODAY - timedelta(days=n)).isoformat()


@pytest.fixture()
def user(client):
    r = client.post("/api/auth/signup", json={"name": "Hb", "email": "habit@example.com",
                                              "password": "correct-horse-battery", "security_question": "Q?",
                                              "security_answer": "A"})
    b = r.json()
    return {"id": b["user"]["id"], "headers": {"Authorization": f"Bearer {b['access_token']}"}}


def test_quit_only_where_it_matters_and_alcohol_safety(client, user):
    h = user["headers"]
    r = client.post("/api/habits", headers=h, json={"kind": "tobacco", "goal": "cut_down", "baseline_per_day": 10,
                                                    "target_per_day": 5})
    assert r.status_code == 400 and "quitting fully" in r.json()["detail"]
    assert client.post("/api/habits", headers=h, json={"kind": "betting", "goal": "cut_down",
                                                       "baseline_per_day": 2, "target_per_day": 1}).status_code == 400
    a = client.post("/api/habits", headers=h, json={"kind": "alcohol", "goal": "quit", "baseline_per_day": 4,
                                                    "cost_per_unit": 200}).json()
    assert "don't stop suddenly" in a["support"]
    bad = client.post("/api/habits", headers=h, json={"kind": "sugar", "goal": "cut_down", "baseline_per_day": 3,
                                                      "target_per_day": 5})
    assert bad.status_code == 400
    other = client.post("/api/habits", headers=h, json={"kind": "other", "label": "Nail biting", "goal": "quit",
                                                        "baseline_per_day": 5}).json()
    assert other["private"] is True


def test_smoking_for_a_dream_with_urges_slips_and_the_dream_fund(client, server, user):
    h = user["headers"]
    dream = client.post("/api/life-plans", headers=h, json={
        "title": "Trek with my son", "target_date": "2027-12-01",
        "requirements": [{"area": "family", "what": "Son is free", "kind": "condition"}]}).json()
    hab = client.post("/api/habits", headers=h, json={
        "kind": "tobacco", "goal": "quit", "baseline_per_day": 10, "cost_per_unit": 18,
        "serves_plan_id": dream["id"], "started_on": _day(10)}).json()
    assert hab["serves"]["title"] == "Trek with my son" and "1800-112-356" in hab["support"]
    for d, amt, trig in ((10, 0, []), (9, 0, []), (8, 3, ["stress"]), (7, 0, []), (6, 0, ["after lunch"])):
        client.post(f"/api/habits/{hab['id']}/log", headers=h, json={"date": _day(d), "amount": amt, "triggers": trig})
    u = client.post(f"/api/habits/{hab['id']}/urge", headers=h, json={"date": _day(6), "trigger": "Stress"}).json()
    assert u["your_reason"] == "Trek with my son" and u["try_this"]
    p = client.get(f"/api/habits/{hab['id']}", headers=h).json()["progress"]
    assert (p["days_logged"], p["days_on_track"]) == (5, 4)                     # one slip, progress kept
    assert p["money_freed"] == "846"                                            # (10×4 + 7) × ₹18
    assert p["top_triggers"][0] == ["stress", 2]
    assert p["welcome_back"].startswith("Welcome back")                         # last log 6 days ago
    fund = client.post(f"/api/habits/{hab['id']}/dream-fund", headers=h).json()
    assert fund["monthly"] == "5400" and fund["goes_to"] == "Trek with my son"  # ₹180 a day × 30
    item = asyncio.run(server.db.planned_money.find_one({"id": fund["planned_money_id"]}))
    assert (item["purpose"], item["life_plan_id"]) == ("saving", dream["id"])
    assert client.post(f"/api/habits/{hab['id']}/dream-fund", headers=h).status_code == 409


def test_progress_rules():
    habit = {"kind": "screens", "started_on": _day(40), "baseline_per_day": "180", "target_per_day": "60",
             "cost_per_unit": None}
    logs = [{"date": _day(1), "amount": "200"}, {"date": TODAY.isoformat(), "amount": "50"}]
    p = progress(habit, logs, TODAY, [{"metric": "stress", "value": 4, "taken_on": _day(1)},
                                      {"metric": "sleep_hours", "value": 5, "taken_on": _day(1)}])
    assert p["days_considered"] == 28 and p["days_on_track"] == 1
    assert p["welcome_back"] == "Welcome back. A slip is part of changing; this is a good day."
    assert p["hours_freed"] == "2.2" and "money_freed" not in p
    assert len(p["steady_the_edge"]) == 2


def test_deleting_health_data_removes_habits(client, server, user):
    h = user["headers"]
    client.put("/api/health/profile", headers=h, json={"consent": True})
    hab = client.post("/api/habits", headers=h, json={"kind": "sugar", "goal": "quit", "baseline_per_day": 3}).json()
    client.post(f"/api/habits/{hab['id']}/log", headers=h, json={"date": TODAY.isoformat(), "amount": 0})
    client.delete("/api/health/all", headers=h)
    assert client.get("/api/habits", headers=h).json() == []
    assert asyncio.run(server.db.habit_logs.count_documents({"user_id": user["id"]})) == 0
