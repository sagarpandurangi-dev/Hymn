"""Caregiver mode, health nudges and health in plans."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

import health_nudges
import nudges
import plan_assistant

KOLKATA = ZoneInfo("Asia/Kolkata")
TODAY = datetime.now(KOLKATA).date()


def _day(n):
    return (TODAY - timedelta(days=n)).isoformat()


def _local(n_days_from_today: int, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    d = TODAY + timedelta(days=n_days_from_today)
    return datetime(d.year, d.month, d.day, h, m, tzinfo=KOLKATA).astimezone(timezone.utc)


@pytest.fixture()
def db(server):
    asyncio.run(nudges.ensure_nudge_indexes(server.db))
    return server.db


def _signup(client, db, email, profile=None):
    b = client.post("/api/auth/signup", json={"name": "Ravi", "email": email, "password": "correct-horse-battery",
                                              "security_question": "Q?", "security_answer": "A"}).json()
    asyncio.run(db.users.update_one({"id": b["user"]["id"]}, {"$set": {"timezone": "Asia/Kolkata"}}))
    h = {"Authorization": f"Bearer {b['access_token']}"}
    if profile is not None:
        client.put("/api/health/profile", headers=h, json={"consent": True, **profile})
    # These tests check each area's own timing; the morning brief and daily limit are tested in test_nudge_limits.
    client.put("/api/nudges/settings", headers=h, json={"limits": {"morning_brief": False, "daily_max": 20}})
    return b["user"]["id"], h


def _tick(db, now):
    return asyncio.run(nudges.run_due_nudges(db, now))


# --- Caregiver mode ---------------------------------------------------------

def test_look_after_a_parent(client, db):
    uid, h = _signup(client, db, "care@example.com", {})
    assert client.post("/api/care", headers=h, json={"name": "Amma", "relation": "mother",
                                                     "their_consent": False}).status_code == 400
    amma = client.post("/api/care", headers=h, json={"name": "Amma", "relation": "mother",
                                                     "their_consent": True}).json()
    q = f"?for={amma['id']}"
    client.put(f"/api/health/profile{q}", headers=h, json={
        "consent": True, "date_of_birth": "1955-03-01", "sex": "female", "conditions": ["diabetes"],
        "medicines": ["Metformin 500"]})
    client.post(f"/api/health/measurements{q}", headers=h, json=[{"metric": "bp_systolic", "value": 150,
                                                                   "taken_on": _day(1)}])
    # Her readings are hers; yours stay yours.
    assert client.get("/api/health/measurements", headers=h).json() == []
    bp = client.get(f"/api/health/measurements{q}", headers=h).json()
    assert bp[0]["value"] == 150
    dash = client.get(f"/api/health/dashboard{q}", headers=h).json()
    assert dash["age"] >= 70 and dash["risks"][0]["metric"] == "bp_systolic"
    keys = {c["key"] for c in client.get(f"/api/health/checkups{q}", headers=h).json()["checks"]}
    assert {"kidney", "diabetic_eye", "bones"} <= keys and "cervical" not in keys
    s = client.get(f"/api/health/doctor-summary{q}", headers=h).json()
    assert s["name"] == "Amma" and s["medicines"] == ["Metformin 500"]
    people = client.get("/api/care", headers=h).json()
    assert people[0]["name"] == "Amma" and people[0]["profile_done"] and people[0]["checkups_due"] >= 1
    # Nobody else can reach her data.
    _, other = _signup(client, db, "stranger@example.com", {})
    assert client.get(f"/api/health/dashboard{q}", headers=other).status_code == 404
    assert client.delete(f"/api/care/{amma['id']}", headers=other).status_code == 404
    # Removing her deletes her data.
    client.delete(f"/api/care/{amma['id']}", headers=h)
    assert asyncio.run(db.health_measurements.count_documents({"user_id": amma["id"]})) == 0
    assert client.get(f"/api/health/dashboard{q}", headers=h).status_code == 404


# --- Health nudges -------------------------------------------------------------

def test_one_health_nudge_a_day_report_first_then_checkups(client, db):
    uid, h = _signup(client, db, "hn@example.com", {"date_of_birth": "1980-01-01", "sex": "male"})
    client.post("/api/health/measurements", headers=h, json=[
        {"metric": "bp_systolic", "value": 124, "taken_on": _day(400)},       # BP check overdue
        {"metric": "sleep_hours", "value": 7, "taken_on": _day(1)}])
    amma = client.post("/api/care", headers=h, json={"name": "Amma", "relation": "mother",
                                                     "their_consent": True}).json()
    client.put(f"/api/health/profile?for={amma['id']}", headers=h,
               json={"consent": True, "date_of_birth": "1955-01-01", "sex": "female"})
    client.post(f"/api/health/checkups/dental/done?for={amma['id']}", headers=h, json={"date": _day(400)})
    client.post(f"/api/health/measurements?for={amma['id']}", headers=h,
                json=[{"metric": "bp_systolic", "value": 130, "taken_on": _day(400)}])   # two checks overdue

    assert [n for n in _tick(db, _local(0, "09:00")) if n["kind"].startswith("health")] == []   # not yet
    day1 = [n for n in _tick(db, _local(0, "09:35")) if n["kind"].startswith("health")]
    mine = [n for n in day1 if n["data"]["for"] is None]
    hers = [n for n in day1 if n["data"]["for"] == amma["id"]]
    assert len(mine) == 1 and mine[0]["kind"] == "health_report"           # first log 400 days ago
    assert [n["title"] for n in hers] == ["Amma's 90-day health report is ready"]   # her first log: 400 days
    assert _tick(db, _local(0, "09:50")) == []                              # once a day
    day2 = [n for n in _tick(db, _local(1, "09:35")) if n["kind"].startswith("health")]
    assert [n["title"] for n in day2 if n["data"]["for"] is None] == ["Time for a blood pressure check"]
    assert [n["title"][:6] for n in day2 if n["data"]["for"] == amma["id"]] == ["Amma: "]
    day3 = [n for n in _tick(db, _local(2, "09:35")) if n["data"].get("for") == amma["id"]]
    assert day3 == []                                                        # a week between check-up nudges
    assert [n for n in _tick(db, _local(2, "09:35")) if n["data"].get("for") is None and
            n["kind"] == "health_checkup"] == []


def test_gentle_log_reminder_quiet_hours_and_switch_off(client, db):
    uid, h = _signup(client, db, "log@example.com", {"date_of_birth": "1995-01-01"})
    for d in (10, 9, 8, 5):
        client.post("/api/health/daily", headers=h, json={"date": _day(d), "mood": 4})
    asyncio.run(db.health_checkups.insert_many([{"user_id": uid, "key": c, "date": _day(1)} for c in
                                                ("blood_pressure", "lipids", "dental", "oral_cancer",
                                                 "weight_waist", "diabetes")]))
    got = [n for n in _tick(db, _local(0, "09:35")) if n["kind"].startswith("health")]
    assert [n["kind"] for n in got] == ["health_log"] and "No catching up" in got[0]["body"]
    assert [n for n in _tick(db, _local(1, "09:35")) if n["kind"] == "health_log"] == []   # weekly at most
    client.put("/api/nudges/settings", headers=h, json={"health": {"enabled": False}})
    assert [n for n in _tick(db, _local(8, "09:35")) if n["kind"].startswith("health")] == []
    client.put("/api/nudges/settings", headers=h, json={"health": {"enabled": True, "time": "23:00"}})
    assert [n for n in _tick(db, _local(8, "23:05")) if n["kind"].startswith("health")] == []   # quiet hours


def test_urge_check_in_just_before_the_usual_time(client, db):
    uid, h = _signup(client, db, "urge@example.com", {})
    dream = client.post("/api/life-plans", headers=h, json={
        "title": "Trek with my son", "target_date": "2028-12-01",
        "requirements": [{"area": "family", "what": "Son is free", "kind": "condition"}]}).json()
    hab = client.post("/api/habits", headers=h, json={"kind": "tobacco", "goal": "quit", "baseline_per_day": 5,
                                                      "serves_plan_id": dream["id"]}).json()
    r = client.post(f"/api/habits/{hab['id']}/urge", headers=h, json={"date": _day(0)})
    assert r.status_code == 200
    times = [_local(-d, "20:00").isoformat() for d in (1, 2, 3)]
    asyncio.run(db.habit_logs.update_one({"habit_id": hab["id"], "date": _day(0)},
                                         {"$set": {"urge_times": times}}))
    assert [n for n in _tick(db, _local(0, "19:30")) if n["kind"] == "habit_urge"] == []
    got = [n for n in _tick(db, _local(0, "19:50")) if n["kind"] == "habit_urge"]
    assert got[0]["title"] == "For Trek with my son" and "Urges often come around now" in got[0]["body"]
    assert [n for n in _tick(db, _local(0, "20:00")) if n["kind"] == "habit_urge"] == []   # once a day
    assert health_nudges.usual_urge_minute(times[:2], KOLKATA, _local(0, "19:50")) is None   # too few


# --- Health in plans ----------------------------------------------------------------

def _steps(client, h, value, days):
    client.post("/api/health/measurements", headers=h,
                json=[{"metric": "steps", "value": value, "taken_on": _day(d)} for d in days])


def test_health_reaches_plans_only_when_shared(client, db):
    uid, h = _signup(client, db, "plan@example.com", {"date_of_birth": "1985-01-01"})
    _steps(client, h, 5000, range(1, 8))
    plan_body = {"title": "Trek with my son", "target_date": (TODAY + timedelta(days=300)).isoformat(),
                 "requirements": [{"area": "health", "what": "Walk enough to trek", "kind": "health",
                                   "metric": "steps", "target": 8000}]}
    p = client.post("/api/life-plans", headers=h, json=plan_body).json()
    req = p["requirements"][0]
    assert req["status"] == "unknown" and "isn't shared" in req["note"]
    ctx = asyncio.run(plan_assistant.get_context(db, {"id": uid}))
    facts = {f["key"]: f for f in ctx["facts"]}
    assert "Not shared" in facts["health_data"]["value"] and "recent_steps" not in facts
    # Switch it on.
    client.put("/api/health/profile", headers=h, json={"consent": True, "date_of_birth": "1985-01-01",
                                                       "use_in_planner": True})
    ctx = asyncio.run(plan_assistant.get_context(db, {"id": uid}))
    facts = {f["key"]: f for f in ctx["facts"]}
    assert facts["recent_steps"]["value"] == "5000.0" and "health_data" not in facts
    p = client.get(f"/api/life-plans/{p['id']}", headers=h).json()
    req = p["requirements"][0]
    assert (req["status"], req["available_now"], req["gap"]) == ("by_then", "5000.0", "3000.0")
    acc = client.post(f"/api/life-plans/{p['id']}/accept", headers=h).json()
    tasks = asyncio.run(db.tasks.find({"user_id": uid, "life_plan_id": p["id"]}, {"_id": 0}).to_list(None))
    assert any(t["title"].startswith("Build up: Walk enough to trek (now 5000.0") for t in tasks), acc
    # Reaching it shows as done.
    _steps(client, h, 9000, range(0, 14))
    assert client.get(f"/api/life-plans/{p['id']}", headers=h).json()["requirements"][0]["status"] == "now"


def test_health_requirements_are_checked(client, db):
    uid, h = _signup(client, db, "plan2@example.com", {"use_in_planner": True})
    bad = client.post("/api/life-plans", headers=h, json={
        "title": "x", "target_date": "2028-01-01",
        "requirements": [{"area": "health", "what": "Lower HbA1c", "kind": "health", "metric": "hba1c",
                          "target": 6}]})
    assert bad.status_code == 400                                    # not something a plan tracks from logs
    _steps(client, h, 5000, range(1, 8))
    past = client.post("/api/life-plans", headers=h, json={
        "title": "Walk more", "target_date": _day(0),
        "requirements": [{"area": "health", "what": "Walk", "kind": "health", "metric": "steps", "target": 8000}]})
    assert past.json()["requirements"][0]["status"] == "short"       # the date has come and it isn't there
    # Weight-loss plans wait for a doctor when the screen says so.
    client.put("/api/health/profile", headers=h, json={"consent": True, "use_in_planner": True,
                                                       "eating_disorder_history": True})
    facts = {f["key"]: f for f in asyncio.run(plan_assistant.get_context(db, {"id": uid}))["facts"]}
    assert "eating" in facts["weight_loss_needs_doctor"]["value"]
