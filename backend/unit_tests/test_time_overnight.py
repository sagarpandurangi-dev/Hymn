"""Overnight weekly blocks (sleep 23:00 → 07:00) are one entry."""
from __future__ import annotations

import pytest


@pytest.fixture()
def user(client):
    r = client.post("/api/auth/signup", json={
        "name": "Sleep", "email": "sleep@example.com", "password": "correct-horse-battery",
        "security_question": "Q?", "security_answer": "A",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    return {"id": body["user"]["id"], "headers": {"Authorization": f"Bearer {body['access_token']}"}}


def _block(client, user, day, start, end, title="Sleep", status=201):
    r = client.post("/api/portfolio/time-commitments", headers=user["headers"], json={
        "title": title, "day_of_week": day, "start_time": start, "end_time": end,
        "commitment_type": "sleep", "flexibility": "fixed", "effective_from": "2026-01-01"})
    assert r.status_code == status, r.text
    return r.json()


def _day(client, user, day):
    r = client.get(f"/api/portfolio/time-capacity/day?date={day}", headers=user["headers"])
    assert r.status_code == 200, r.text
    return r.json()


def test_sleep_is_one_block_counted_across_midnight(client, user):
    _block(client, user, "monday", "23:00", "07:00")
    # 2026-11-16 is a Monday.
    assert _day(client, user, "2026-11-16")["baseline_committed_minutes"] == 60     # 23:00-24:00
    assert _day(client, user, "2026-11-17")["baseline_committed_minutes"] == 420    # 00:00-07:00
    assert _day(client, user, "2026-11-18")["baseline_committed_minutes"] == 0
    week = client.get("/api/portfolio/time-capacity/week?week_start_date=2026-11-16", headers=user["headers"]).json()
    assert sum(d["baseline_committed_minutes"] for d in week["days"]) == 480


def test_sunday_night_spills_into_monday(client, user):
    _block(client, user, "sunday", "22:00", "06:00")
    assert _day(client, user, "2026-11-16")["baseline_committed_minutes"] == 360


def test_same_start_and_end_is_refused(client, user):
    _block(client, user, "monday", "07:00", "07:00", status=400)


def test_old_split_halves_are_joined(client, user):
    _block(client, user, "monday", "23:00", "24:00")
    _block(client, user, "tuesday", "00:00", "07:00")
    _block(client, user, "tuesday", "00:00", "01:00", title="Reading")  # different block: untouched
    rows = client.get("/api/portfolio/time-commitments", headers=user["headers"]).json()
    sleep = [r for r in rows if r["title"] == "Sleep"]
    assert [(r["day_of_week"], r["start_time"], r["end_time"]) for r in sleep] == [("monday", "23:00", "07:00")]
    assert any(r["title"] == "Reading" for r in rows)
    assert _day(client, user, "2026-11-17")["baseline_committed_minutes"] == 420
