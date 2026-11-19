"""Notification limits: at most N pushes a day (what the person asked to be reminded of
always gets through), and the morning parts arrive together as one brief."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

import nudges

KOLKATA = ZoneInfo("Asia/Kolkata")
TODAY = datetime.now(KOLKATA).date()


def _at(hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime(TODAY.year, TODAY.month, TODAY.day, h, m, tzinfo=KOLKATA).astimezone(timezone.utc)


@pytest.fixture()
def db(server):
    asyncio.run(nudges.ensure_nudge_indexes(server.db))
    return server.db


@pytest.fixture()
def pushes(monkeypatch):
    sent = []
    monkeypatch.setattr(nudges, "send_expo_messages", lambda msgs: (sent.extend(msgs), [{"status": "ok"}] * len(msgs))[1])
    return sent


@pytest.fixture()
def user(client, db):
    b = client.post("/api/auth/signup", json={"name": "Asha", "email": "limits@example.com",
                                              "password": "correct-horse-battery", "security_question": "Q?",
                                              "security_answer": "A"}).json()
    asyncio.run(db.users.update_one({"id": b["user"]["id"]}, {"$set": {"timezone": "Asia/Kolkata"}}))
    h = {"Authorization": f"Bearer {b['access_token']}"}
    assert client.post("/api/nudges/devices", headers=h, json={"token": "ExponentPushToken[limits-test]"}).status_code == 201
    return {"id": b["user"]["id"], "headers": h, "tz": "Asia/Kolkata"}


def _claim(db, user, kind, key, title, at):
    return asyncio.run(nudges._claim(db, user["id"], kind, key, title, "body", {}, at))


def _dispatch(db, user, due, at, **limits):
    settings = nudges.merge_settings({"limits": limits} if limits else None)
    return asyncio.run(nudges._dispatch(db, {"id": user["id"], "timezone": user["tz"]}, settings, due, at))


def test_morning_areas_move_to_the_brief_time_only_when_the_brief_is_on():
    s = nudges.merge_settings({"health": {"time": "14:00"}})
    moved = nudges.with_brief(s)
    assert moved["people"]["time"] == "08:30" and moved["learning"]["time"] == "08:30"
    assert moved["health"]["time"] == "14:00"            # an afternoon time the person chose stays
    assert moved["work"]["time"] == "18:30"              # work isn't a morning part
    assert s["people"]["time"] == "09:00"                # the stored settings aren't changed
    off = nudges.with_brief(nudges.merge_settings({"limits": {"morning_brief": False}}))
    assert off["people"]["time"] == "09:00" and off["learning"]["time"] == "07:00"


def test_several_at_once_arrive_as_one_brief_and_all_stay_in_the_feed(client, db, user, pushes):
    at = _at("08:30")
    due = [_claim(db, user, k, f"{k}:x", t, at) for k, t in
           (("people_day", "Amma's birthday today"), ("learning_today", "2 revisions today"),
            ("health_checkup", "Eye check due"))]
    _dispatch(db, user, due, at)
    assert len(pushes) == 1
    assert pushes[0]["title"] == "Your morning from Hymn"
    assert pushes[0]["body"] == "Amma's birthday today · 2 revisions today · Eye check due"
    feed = client.get("/api/nudges", headers=user["headers"]).json()
    assert sorted(n["kind"] for n in feed) == ["health_checkup", "learning_today", "people_day"]   # no wrapper
    assert {n["status"] for n in feed} == {"in_brief"}


def test_a_long_brief_says_how_many_more():
    items = [{"title": f"T{i}"} for i in range(5)]
    assert nudges._brief_text(items) == "T0 · T1 · T2 · and 2 more"


def test_the_daily_limit_holds_extras_but_never_what_you_asked_for(client, db, user, pushes):
    for i, hhmm in enumerate(("09:00", "12:00")):
        _dispatch(db, user, [_claim(db, user, "work_leave", f"w{i}", f"Note {i}", _at(hhmm))], _at(hhmm), daily_max=2)
    assert len(pushes) == 2
    late = _claim(db, user, "people_touch", "late", "Ravi might like to hear from you", _at("17:00"))
    _dispatch(db, user, [late], _at("17:00"), daily_max=2)
    assert len(pushes) == 2                                                   # over the limit: held
    held = client.get("/api/nudges", headers=user["headers"]).json()
    assert next(n for n in held if n["key"] == "late")["status"] == "held"   # still in the feed
    rem = _claim(db, user, "reminder", "rem", "Call the bank", _at("17:05"))
    _dispatch(db, user, [rem], _at("17:05"), daily_max=2)
    assert [m["title"] for m in pushes][-1] == "Call the bank"              # reminders always get through


def test_the_limit_starts_again_the_next_day(db, user, pushes):
    _dispatch(db, user, [_claim(db, user, "work_week", "a", "A", _at("09:00"))], _at("09:00"), daily_max=1)
    tomorrow = _at("09:00") + timedelta(days=1)
    _dispatch(db, user, [_claim(db, user, "work_week", "b", "B", tomorrow)], tomorrow, daily_max=1)
    assert [m["title"] for m in pushes] == ["A", "B"]


def test_a_birthday_arrives_at_the_brief_time(client, db, user, pushes):
    assert client.post("/api/people", headers=user["headers"], json={
        "name": "Amma", "relation": "mother", "circle": "inner",
        "birthday": TODAY.strftime("%m-%d")}).status_code == 201
    assert asyncio.run(nudges.run_due_nudges(db, _at("08:00"))) == []
    sent = asyncio.run(nudges.run_due_nudges(db, _at("08:30")))
    assert [n["kind"] for n in sent] == ["people_day"]
    assert len(pushes) == 1
    assert asyncio.run(nudges.run_due_nudges(db, _at("09:00"))) == []        # not again at the old 09:00


def test_limit_settings_are_checked(client, user):
    h = user["headers"]
    assert client.put("/api/nudges/settings", headers=h, json={"limits": {"brief_time": "8:30"}}).status_code == 400
    assert client.put("/api/nudges/settings", headers=h, json={"limits": {"daily_max": 0}}).status_code == 422
    r = client.put("/api/nudges/settings", headers=h, json={"limits": {"daily_max": 6, "brief_time": "07:45"}})
    assert r.status_code == 200
    assert r.json()["settings"]["limits"] == {"daily_max": 6, "morning_brief": True, "brief_time": "07:45"}
