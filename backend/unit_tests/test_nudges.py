"""Nudges: scheduling rules, learning, delivery and settings."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

import inbox
import inbox_ai
import nudges

KOLKATA = ZoneInfo("Asia/Kolkata")
TOKEN = "ExponentPushToken[abc123def456]"


def _at(day: int, hhmm: str) -> datetime:
    """A November 2026 Kolkata local time, as UTC."""
    h, m = map(int, hhmm.split(":"))
    return datetime(2026, 11, day, h, m, tzinfo=KOLKATA).astimezone(timezone.utc)


@pytest.fixture()
def db(server):
    asyncio.run(nudges.ensure_nudge_indexes(server.db))
    return server.db


@pytest.fixture()
def user(client, db):
    r = client.post("/api/auth/signup", json={
        "name": "Nudge User", "email": "nudge@example.com", "password": "correct-horse-battery",
        "security_question": "Q?", "security_answer": "A",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    asyncio.run(db.users.update_one({"id": body["user"]["id"]}, {"$set": {"timezone": "Asia/Kolkata"}}))
    return {"id": body["user"]["id"], "headers": {"Authorization": f"Bearer {body['access_token']}"}}


@pytest.fixture()
def pushes(monkeypatch):
    sent = []

    def fake_send(messages):
        sent.append(messages)
        return [{"status": "ok"} for _ in messages]

    monkeypatch.setattr(nudges, "send_expo_messages", fake_send)
    return sent


def _add_item(db, user_id, text="renew passport", category="task", remind_at=None):
    item = inbox._new_item(user_id, "dump-1", text, category, remind_at)
    asyncio.run(db.inbox_items.insert_one(item))
    return item


def _add_review(db, user_id, at: datetime):
    asyncio.run(db.inbox_reviews.insert_one(
        {"id": str(at), "user_id": user_id, "decisions": [], "created_at": at.isoformat()},
    ))


def _tick(db, now):
    return asyncio.run(nudges.run_due_nudges(db, now))


def _kinds(sent):
    return sorted(n["kind"] for n in sent)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def test_quiet_hours_wrap_midnight():
    assert nudges.in_quiet_hours(23 * 60, "22:00", "07:00")
    assert nudges.in_quiet_hours(6 * 60 + 59, "22:00", "07:00")
    assert not nudges.in_quiet_hours(7 * 60, "22:00", "07:00")
    assert nudges.in_quiet_hours(13 * 60, "12:00", "14:00")
    assert not nudges.in_quiet_hours(13 * 60, "08:00", "08:00")


def test_learning_needs_enough_reviews_and_stays_near_choice():
    preferred = nudges.hhmm_to_minute("20:30")
    assert nudges.learned_review_minute([21 * 60] * 4, preferred) is None
    assert nudges.learned_review_minute([21 * 60 + 40] * 5, preferred) == 21 * 60 + 30
    # A median far from the chosen time is clamped to three hours away.
    assert nudges.learned_review_minute([6 * 60] * 5, preferred) == 17 * 60 + 30


# ---------------------------------------------------------------------------
# Daily review
# ---------------------------------------------------------------------------

def test_daily_review_sent_once_at_the_chosen_time(db, user, pushes):
    _add_item(db, user["id"])
    assert _tick(db, _at(10, "20:29")) == []
    sent = _tick(db, _at(10, "20:30"))
    assert _kinds(sent) == ["daily_review"]
    assert sent[0]["body"] == "1 thing waiting in your inbox."
    assert _tick(db, _at(10, "20:31")) == []  # once per day
    assert _kinds(_tick(db, _at(11, "20:30"))) == ["daily_review"]


def test_no_nudge_when_nothing_to_review_or_already_reviewed(db, user, pushes):
    assert _tick(db, _at(10, "20:30")) == []
    _add_item(db, user["id"])
    _add_review(db, user["id"], _at(10, "09:00"))
    assert _tick(db, _at(10, "20:30")) == []


def test_missed_nudge_is_dropped_after_catch_up_window(db, user, pushes):
    _add_item(db, user["id"])
    assert _tick(db, _at(10, "20:30") + nudges.CATCH_UP + timedelta(minutes=1)) == []


def test_quiet_hours_block_the_daily_review(db, user, pushes, client):
    _add_item(db, user["id"])
    client.put("/api/nudges/settings", headers=user["headers"],
               json={"daily_review": {"time": "23:00"}})
    assert _tick(db, _at(10, "23:00")) == []


def test_daily_review_moves_to_learned_time(db, user, pushes, client):
    _add_item(db, user["id"])
    for day in range(3, 8):
        _add_review(db, user["id"], _at(day, "21:40"))

    plan = client.get("/api/nudges/settings", headers=user["headers"]).json()["daily_review_plan"]
    assert plan["learned"] is True
    assert plan["time"] == "21:30"
    assert "21:40" in plan["explanation"]

    assert _tick(db, _at(10, "20:30")) == []
    assert _kinds(_tick(db, _at(10, "21:30"))) == ["daily_review"]


def test_learning_can_be_switched_off(db, user, pushes, client):
    for day in range(3, 8):
        _add_review(db, user["id"], _at(day, "21:40"))
    r = client.put("/api/nudges/settings", headers=user["headers"],
                   json={"daily_review": {"adaptive": False}})
    assert r.json()["daily_review_plan"]["time"] == "20:30"
    assert r.json()["daily_review_plan"]["learned"] is False


# ---------------------------------------------------------------------------
# Reminders and weekly patterns
# ---------------------------------------------------------------------------

def test_reminders_fire_once_even_in_quiet_hours(db, user, pushes):
    _add_item(db, user["id"], "call the bank", "reminder", _at(10, "06:00").isoformat())
    sent = _tick(db, _at(10, "06:01"))
    assert [(n["kind"], n["body"]) for n in sent] == [("reminder", "call the bank")]
    assert _tick(db, _at(10, "06:02")) == []


def test_reminders_can_be_turned_off(db, user, pushes, client):
    _add_item(db, user["id"], "call the bank", "reminder", _at(10, "12:00").isoformat())
    client.put("/api/nudges/settings", headers=user["headers"], json={"reminders": {"enabled": False}})
    assert _tick(db, _at(10, "12:01")) == []


def test_weekly_patterns_on_chosen_day_with_summary(db, user, pushes, monkeypatch):
    _add_item(db, user["id"])

    async def summarise_patterns(report):
        return inbox_ai.WeeklyPatterns(themes=[], avoidance=[], suggestions=[], summary="Steady week.")

    monkeypatch.setattr(inbox_ai, "summarise_patterns", summarise_patterns)
    sunday = 15
    assert _at(sunday, "18:00").astimezone(KOLKATA).weekday() == 6
    assert _tick(db, _at(14, "18:00")) == []
    sent = [n for n in _tick(db, _at(sunday, "18:00")) if n["kind"] == "weekly_patterns"]
    assert [n["body"] for n in sent] == ["Steady week."]
    assert asyncio.run(db.inbox_insights.count_documents({"user_id": user["id"]})) == 1
    assert [n for n in _tick(db, _at(sunday, "18:05")) if n["kind"] == "weekly_patterns"] == []


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------

def test_registered_phone_receives_the_push(db, user, pushes, client):
    r = client.post("/api/nudges/devices", headers=user["headers"], json={"token": TOKEN})
    assert r.status_code == 201
    _add_item(db, user["id"])
    _tick(db, _at(10, "20:30"))
    assert [[m["to"] for m in batch] for batch in pushes] == [[TOKEN]]
    assert pushes[0][0]["title"] == "Time for your 2-minute review"
    feed = client.get("/api/nudges", headers=user["headers"]).json()
    assert feed[0]["status"] == "sent"


def test_without_a_phone_the_nudge_still_lands_in_the_feed(db, user, pushes, client):
    _add_item(db, user["id"])
    _tick(db, _at(10, "20:30"))
    assert pushes == []
    feed = client.get("/api/nudges", headers=user["headers"]).json()
    assert [(n["kind"], n["status"]) for n in feed] == [("daily_review", "no_device")]


def test_unregistered_phone_token_is_dropped(db, user, client, monkeypatch):
    client.post("/api/nudges/devices", headers=user["headers"], json={"token": TOKEN})
    monkeypatch.setattr(nudges, "send_expo_messages", lambda messages: [
        {"status": "error", "details": {"error": "DeviceNotRegistered"}} for _ in messages
    ])
    _add_item(db, user["id"])
    _tick(db, _at(10, "20:30"))
    assert asyncio.run(db.push_tokens.count_documents({})) == 0


def test_push_service_outage_marks_nudge_failed(db, user, client, monkeypatch):
    import requests

    client.post("/api/nudges/devices", headers=user["headers"], json={"token": TOKEN})

    def down(messages):
        raise requests.ConnectionError("expo unreachable")

    monkeypatch.setattr(nudges, "send_expo_messages", down)
    _add_item(db, user["id"])
    _tick(db, _at(10, "20:30"))
    feed = client.get("/api/nudges", headers=user["headers"]).json()
    assert feed[0]["status"] == "failed"


def test_opening_a_nudge_is_recorded(db, user, pushes, client):
    _add_item(db, user["id"])
    nudge = _tick(db, _at(10, "20:30"))[0]
    r = client.post(f"/api/nudges/{nudge['id']}/opened", headers=user["headers"])
    assert r.status_code == 200
    assert client.get("/api/nudges", headers=user["headers"]).json()[0]["opened_at"]
    assert client.post("/api/nudges/nope/opened", headers=user["headers"]).status_code == 404


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def test_settings_defaults_and_validation(user, client):
    body = client.get("/api/nudges/settings", headers=user["headers"]).json()
    assert body["settings"] == nudges.DEFAULT_SETTINGS
    assert body["timezone"] == "Asia/Kolkata"
    bad = client.put("/api/nudges/settings", headers=user["headers"],
                     json={"daily_review": {"time": "8pm"}})
    assert bad.status_code == 400
    bad_tz = client.put("/api/nudges/settings", headers=user["headers"], json={"timezone": "Mars/Base"})
    assert bad_tz.status_code == 400


def test_settings_update_is_partial(user, client):
    r = client.put("/api/nudges/settings", headers=user["headers"], json={
        "daily_review": {"time": "07:45"}, "quiet_hours": {"start": "23:00"}, "timezone": "Europe/Oslo",
    })
    assert r.status_code == 200, r.text
    s = r.json()["settings"]
    assert s["daily_review"] == {"enabled": True, "time": "07:45", "adaptive": True}
    assert s["quiet_hours"] == {"start": "23:00", "end": "07:00"}
    assert r.json()["timezone"] == "Europe/Oslo"
