"""Time statements (weekly) and check-in duration."""
from __future__ import annotations

import asyncio

import pytest


@pytest.fixture()
def user(client):
    r = client.post("/api/auth/signup", json={"name": "T", "email": "time@example.com",
                                              "password": "correct-horse-battery", "security_question": "Q?",
                                              "security_answer": "A"})
    b = r.json()
    return {"id": b["user"]["id"], "headers": {"Authorization": f"Bearer {b['access_token']}"}}


def _block(client, user, day, start, end, kind, title, flex="fixed"):
    r = client.post("/api/portfolio/time-commitments", headers=user["headers"], json={
        "title": title, "day_of_week": day, "start_time": start, "end_time": end, "commitment_type": kind,
        "flexibility": flex, "effective_from": "2026-01-01"})
    assert r.status_code == 201, r.text


def _goal(server, user, area_name, title):
    db = server.db
    dom = {"id": f"d-{title}", "user_id": user["id"], "name": area_name}
    asyncio.run(db.domains.insert_one(dom))
    asyncio.run(db.goals.insert_one({"id": f"g-{title}", "user_id": user["id"], "domain_id": dom["id"],
                                     "title": title}))
    return f"g-{title}"


def _checkin(server, user, goal_id, day, minutes, title="x"):
    asyncio.run(server.db.checkins.insert_one({"id": f"c-{day}-{title}", "user_id": user["id"], "goal_id": goal_id,
                                               "date": day, "title": title, "duration_minutes": minutes}))


DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def test_week_statements(client, server, user):
    for d in DAYS:
        _block(client, user, d, "23:00", "07:00", "sleep", "Sleep")                   # 56h, overnight
    for d in DAYS[:5]:
        _block(client, user, d, "09:00", "19:00", "work", "Office")                   # 50h
        _block(client, user, d, "08:00", "09:00", "commute", "Commute")               # 5h
    _block(client, user, "saturday", "07:00", "09:00", "study", "Course", flex="flexible")  # 2h planned
    gym = _goal(server, user, "Health", "Get fit")
    learn = _goal(server, user, "Knowledge", "Learn Python")
    _checkin(server, user, gym, "2026-11-16", 60, "gym")
    _checkin(server, user, gym, "2026-11-18", 45, "gym")
    _checkin(server, user, learn, "2026-11-21", 30, "python")
    r = client.get("/api/reports/time?week_start=2026-11-18", headers=user["headers"])     # any day → its Monday
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["week_start"] == "2026-11-16"
    c = t["commitments"]
    assert (c["fixed_hours"], c["flexible_and_set_aside_hours"], c["free_hours"]) == ("111.0", "2.0", "55.0")
    areas = {a["area"]: a for a in t["spent"]["areas"]}
    assert (areas["health"]["planned_hours"], areas["health"]["actual_hours"]) == ("56.0", "57.8")   # sleep + gym
    assert (areas["learning"]["planned_hours"], areas["learning"]["actual_hours"], areas["learning"]["gap_hours"]) \
        == ("2.0", "0.5", "-1.5")
    assert {l["label"] for l in areas["health"]["lines"]} == {"Sleep", "Get fit"}
    s = t["spent"]
    assert s["soul_hours"] == "54.8" and s["show_soul"] is True                         # >30% of 168h untracked
    f = t["flow"]
    assert f["adds_up"] is True and f["planned_free_hours"] == "55.0" and f["untracked_hours"] == "54.8"
    assets = {a["area"]: a["hours"] for a in c["time_assets_this_year"]}
    assert assets == {"health": "1.8", "learning": "0.5"}


def test_checkin_duration_is_stored_and_can_be_required(client, server, user, monkeypatch):
    body = {"type": "life", "title": "Walk", "date": "2026-11-16", "time": "07:00"}
    r = client.post("/api/checkins", headers=user["headers"], json={**body, "duration_minutes": 45})
    assert r.status_code in (200, 201), r.text and r.json()["duration_minutes"] == 45
    assert r.json()["duration_minutes"] == 45
    assert client.post("/api/checkins", headers=user["headers"], json=body).status_code in (200, 201)
    monkeypatch.setenv("HYMN_REQUIRE_CHECKIN_DURATION", "1")
    r = client.post("/api/checkins", headers=user["headers"], json=body)
    assert r.status_code == 400 and r.json()["detail"] == "How long did it take? Pick a time."
