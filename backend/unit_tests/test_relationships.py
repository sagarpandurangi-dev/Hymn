"""Family & Relationships: people, days that matter, moments, gentle nudges."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

import nudges
import plan_assistant
from relationships import days_coming, next_occurrence, touch_status

KOLKATA = ZoneInfo("Asia/Kolkata")
TODAY = date.today()


def _mmdd(d: date) -> str:
    return d.isoformat()[5:]


def _ago(n):
    return (TODAY - timedelta(days=n)).isoformat()


@pytest.fixture()
def db(server):
    asyncio.run(nudges.ensure_nudge_indexes(server.db))
    return server.db


@pytest.fixture()
def user(client, db):
    b = client.post("/api/auth/signup", json={"name": "Ravi", "email": "people@example.com",
                                              "password": "correct-horse-battery", "security_question": "Q?",
                                              "security_answer": "A"}).json()
    asyncio.run(db.users.update_one({"id": b["user"]["id"]}, {"$set": {"timezone": "Asia/Kolkata"}}))
    return {"id": b["user"]["id"], "headers": {"Authorization": f"Bearer {b['access_token']}"}}


def test_dates_come_round_each_year():
    assert next_occurrence("03-15", date(2026, 3, 16)) == date(2027, 3, 15)
    assert next_occurrence("03-15", date(2026, 3, 15)) == date(2026, 3, 15)            # today counts
    assert next_occurrence("1992-02-29", date(2026, 1, 1)) == date(2026, 2, 28)        # leap-day birthdays
    p = {"id": "p", "name": "Amma", "birthday": "1956-11-20", "occasions": [
        {"label": "Anniversary", "date": "1980-11-18", "gift_budget": 3000}]}
    c = days_coming(p, date(2026, 11, 15), 7)
    assert [(x["label"], x["in_days"], x["years"]) for x in c] == [("Birthday", 5, 70), ("Anniversary", 3, 46)]
    assert c[1]["gift_budget"] == 3000
    s = touch_status({"keep_in_touch_days": 7}, "2026-11-01", date(2026, 11, 15))
    assert s["might_like_to_hear_from_you"] and s["days_since"] == 14
    assert not touch_status({"keep_in_touch_days": None}, None, date(2026, 11, 15))["might_like_to_hear_from_you"]


def test_people_moments_and_the_summary(client, db, user):
    h = user["headers"]
    amma = client.post("/api/people", headers=h, json={
        "name": "Amma", "relation": "mother", "circle": "inner", "birthday": "1956-" + _mmdd(TODAY + timedelta(days=5)),
        "birthday_gift": 2500}).json()
    assert amma["keep_in_touch_days"] == 7 and amma["next_day"]["in_days"] == 5
    assert amma["next_day"]["years"] == (TODAY + timedelta(days=5)).year - 1956
    priya = client.post("/api/people", headers=h, json={"name": "Priya", "relation": "friend"}).json()
    assert priya["keep_in_touch_days"] == 30 and priya["circle"] == "close"
    bad = client.post("/api/people", headers=h, json={"name": "X", "relation": "friend", "birthday": "13-40"})
    assert bad.status_code == 400
    # The gift is in planned money (yearly, in the birthday month).
    gift = asyncio.run(db.planned_money.find_one({"user_id": user["id"], "person_id": amma["id"]}, {"_id": 0}))
    assert gift["title"] == "Birthday: Amma" and gift["repeat"] == "yearly" and gift["category"] == "expense:gifts"
    assert gift["start_month"] == (TODAY + timedelta(days=5)).isoformat()[:7]
    # Moments.
    client.post("/api/people/moments", headers=h, json={"person_ids": [amma["id"], priya["id"]], "date": _ago(1),
                                                        "kind": "meal", "minutes": 90})
    client.post("/api/people/moments", headers=h, json={"person_ids": [priya["id"]], "date": _ago(40),
                                                        "kind": "call", "minutes": 20})
    other = client.post("/api/auth/signup", json={"name": "O", "email": "o2@example.com",
                                                  "password": "correct-horse-battery", "security_question": "Q?",
                                                  "security_answer": "A"}).json()
    oh = {"Authorization": f"Bearer {other['access_token']}"}
    assert client.post("/api/people/moments", headers=oh, json={"person_ids": [amma["id"]], "date": _ago(1)}) \
        .status_code == 400                                                     # not your people
    assert client.get(f"/api/people/{amma['id']}", headers=oh).status_code == 404
    people = {p["name"]: p for p in client.get("/api/people", headers=h).json()}
    assert people["Amma"]["days_since"] == 1 and not people["Amma"]["might_like_to_hear_from_you"]
    assert people["Priya"]["days_since"] == 1
    s = client.get("/api/people/summary", headers=h).json()
    if _ago(1)[:7] == TODAY.isoformat()[:7]:
        assert s["inner_circle_hours"] == 1.5 and s["people_reached"] == 2
    assert s["coming_up"][0]["name"] == "Amma"
    up = client.get("/api/people/upcoming?days=10", headers=h).json()
    assert [u["label"] for u in up] == ["Birthday"]
    # Removing someone removes their moments and gift.
    client.delete(f"/api/people/{priya['id']}", headers=h)
    left = asyncio.run(db.people_moments.find({"user_id": user["id"]}, {"_id": 0}).to_list(None))
    assert len(left) == 1 and left[0]["person_ids"] == [amma["id"]]
    client.patch(f"/api/people/{amma['id']}", headers=h, json={"birthday_gift": None, "keep_in_touch_days": 0})
    assert asyncio.run(db.planned_money.count_documents({"person_id": amma["id"]})) == 0
    assert client.get(f"/api/people/{amma['id']}", headers=h).json()["keep_in_touch_days"] is None


def test_time_with_people_reaches_health_only_with_consent(client, db, user):
    h = user["headers"]
    p = client.post("/api/people", headers=h, json={"name": "Amma", "relation": "mother", "circle": "inner"}).json()
    client.post("/api/people/moments", headers=h, json={"person_ids": [p["id"]], "date": _ago(0), "minutes": 60})
    assert asyncio.run(db.health_measurements.count_documents({"user_id": user["id"]})) == 0
    client.put("/api/health/profile", headers=h, json={"consent": True})
    m = client.post("/api/people/moments", headers=h, json={"person_ids": [p["id"]], "date": _ago(0),
                                                            "minutes": 30}).json()
    rows = client.get("/api/health/measurements?metric=social_hours", headers=h).json()
    assert [r["value"] for r in rows] == [1.5]                                  # the week's total, once
    client.delete(f"/api/people/moments/{m['id']}", headers=h)
    assert [r["value"] for r in client.get("/api/health/measurements?metric=social_hours", headers=h).json()] == [1.0]


def _local(days_from_today: int, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    d = datetime.now(KOLKATA).date() + timedelta(days=days_from_today)
    return datetime(d.year, d.month, d.day, h, m, tzinfo=KOLKATA).astimezone(timezone.utc)


def test_birthday_and_keep_in_touch_nudges(client, db, user):
    h = user["headers"]
    local_today = datetime.now(KOLKATA).date()
    amma = client.post("/api/people", headers=h, json={
        "name": "Amma", "relation": "mother", "circle": "inner", "birthday": "1956-" +
        _mmdd(local_today + timedelta(days=1)), "birthday_gift": 2500}).json()
    papa = client.post("/api/people", headers=h, json={"name": "Papa", "relation": "father", "circle": "inner"}).json()
    client.post("/api/people/moments", headers=h, json={"person_ids": [papa["id"]],
                                                        "date": (local_today - timedelta(days=12)).isoformat()})
    client.post("/api/people/moments", headers=h, json={"person_ids": [amma["id"]],
                                                        "date": (local_today - timedelta(days=9)).isoformat()})
    got = [n for n in asyncio.run(nudges.run_due_nudges(db, _local(0, "09:05"))) if n["kind"].startswith("people")]
    turns = (local_today + timedelta(days=1)).year - 1956
    titles = sorted(n["title"] for n in got)
    assert titles == ["Papa might like to hear from you", f"Tomorrow: Amma's birthday (turns {turns})"]
    assert any("₹2,500" in n["body"] for n in got)
    assert [n for n in asyncio.run(nudges.run_due_nudges(db, _local(0, "09:30"))) if n["kind"].startswith("people")] == []
    day2 = [n["title"] for n in asyncio.run(nudges.run_due_nudges(db, _local(1, "09:05")))
            if n["kind"].startswith("people")]
    assert day2 == [f"Today: Amma's birthday (turns {turns})"]                         # touch nudge: weekly at most
    client.put("/api/nudges/settings", headers=h, json={"people": {"time": "23:00"}})
    assert [n for n in asyncio.run(nudges.run_due_nudges(db, _local(9, "23:05")))
            if n["kind"].startswith("people")] == []                                 # quiet hours
    client.put("/api/nudges/settings", headers=h, json={"people": {"enabled": False, "time": "09:00"}})
    assert [n for n in asyncio.run(nudges.run_due_nudges(db, _local(9, "09:05"))) if n["kind"].startswith("people")] == []


def test_the_planner_knows_who_matters(client, db, user):
    h = user["headers"]
    client.post("/api/people", headers=h, json={"name": "Amma", "relation": "mother", "circle": "inner",
                                                "birthday": "1956-" + _mmdd(TODAY + timedelta(days=20))})
    client.post("/api/people", headers=h, json={"name": "Raj", "relation": "colleague", "circle": "wider"})
    facts = {f["key"]: f for f in asyncio.run(plan_assistant.get_context(db, {"id": user["id"]}))["facts"]}
    assert facts["inner_circle"]["value"] == "Amma (mother)"
    assert "Amma's birthday" in facts["days_coming_up"]["value"]
