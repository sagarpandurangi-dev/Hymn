"""The core objects — areas (domains), goals, expected outcomes, projects,
tasks (defer, recurrence) and check-ins (search) — and that each person only
sees their own. These replace the old live-server tests in backend/tests."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

import recurrence

TODAY = date.today()


def _signup(client, email):
    b = client.post("/api/auth/signup", json={"name": "Core", "email": email, "password": "correct-horse-battery",
                                              "security_question": "Q?", "security_answer": "A"}).json()
    return {"Authorization": f"Bearer {b['access_token']}"}


@pytest.fixture()
def h(client):
    return _signup(client, "core@example.com")


@pytest.fixture()
def other(client):
    return _signup(client, "core-other@example.com")


def _domain(client, h, name="Money"):
    return next(d for d in client.get("/api/domains", headers=h).json() if d["name"] == name)


# --- Recurrence (pure) ------------------------------------------------------------

def test_recurrence_dates():
    d = date(2026, 1, 31)
    assert recurrence.step(d, "monthly") == date(2026, 2, 28)          # clamps to month end
    assert recurrence.step(d, "quarterly") == date(2026, 4, 30)
    assert recurrence.step(date(2026, 1, 1), "alternate_day") == date(2026, 1, 3)
    assert recurrence.step(date(2026, 1, 1), "fortnightly") == date(2026, 1, 15)
    assert recurrence.next_occurrence(date(2026, 1, 1), "weekly", after=date(2026, 1, 10)) == date(2026, 1, 15)
    assert recurrence.next_date_str("2026-03-01", {"cadence": "monthly", "end_type": "until",
                                                   "end_date": "2026-03-15"}) is None
    assert recurrence.should_spawn_next({"end_type": "count", "occurrences_remaining": 1}) is False
    assert recurrence.should_spawn_next({"end_type": "count", "occurrences_remaining": 2}) is True
    with pytest.raises(ValueError):
        recurrence.next_occurrence(date(2026, 1, 1), "hourly")


# --- Domains and goals --------------------------------------------------------------

def test_default_areas_and_custom_ones(client, h):
    names = {d["name"] for d in client.get("/api/domains", headers=h).json()}
    assert {"Money", "Health"} <= names
    d = client.post("/api/domains", headers=h, json={"name": "Garden"})
    assert d.status_code == 201
    assert client.post("/api/domains", headers=h, json={"name": "garden"}).status_code == 400   # same, any case
    assert client.put(f"/api/domains/{d.json()['id']}", headers=h, json={"name": "Garden & plants"}).status_code == 200


def test_goal_outcome_task_chain_and_isolation(client, h, other):
    money = _domain(client, h)
    g = client.post("/api/goals", headers=h, json={"title": "Emergency fund", "domain_id": money["id"],
                                                    "checkin_cadence": "weekly"})
    assert g.status_code == 201, g.text
    gid = g.json()["id"]
    assert client.post("/api/goals", headers=h, json={"title": "X", "domain_id": money["id"],
                                                       "checkin_cadence": "hourly"}).status_code == 400
    eo = client.post("/api/expected-outcomes", headers=h, json={"goal_id": gid, "title": "₹3L saved"}).json()
    t = client.post("/api/tasks", headers=h, json={"title": "Open RD", "origin": "expected_outcome",
                                                    "expected_outcome_id": eo["id"]})
    assert t.status_code == 201, t.text
    assert [x["title"] for x in client.get(f"/api/goals/{gid}/expected-outcomes", headers=h).json()] == ["₹3L saved"]
    # Another person sees none of it and can't touch it.
    assert client.get(f"/api/goals/{gid}", headers=other).status_code == 404
    assert client.get(f"/api/tasks/{t.json()['id']}", headers=other).status_code == 404
    assert client.put(f"/api/goals/{gid}", headers=other, json={"title": "Mine now"}).status_code == 404
    assert client.delete(f"/api/tasks/{t.json()['id']}", headers=other).status_code == 404
    assert client.get("/api/goals", headers=other).json() == []
    # The goal can't be attached to someone else's area.
    other_money = _domain(client, other)
    assert client.post("/api/goals", headers=h, json={"title": "Sneaky", "domain_id": other_money["id"]}) \
        .status_code in (400, 404)


def test_projects_and_their_tasks(client, h, other):
    p = client.post("/api/projects", headers=h, json={"title": "Move house"}).json()
    t = client.post("/api/tasks", headers=h, json={"title": "Book movers", "origin": "project",
                                                    "project_id": p["id"]})
    assert t.status_code == 201
    assert [x["title"] for x in client.get(f"/api/tasks?project_id={p['id']}", headers=h).json()] == ["Book movers"]
    assert client.post("/api/tasks", headers=other, json={"title": "Into theirs", "origin": "project",
                                                           "project_id": p["id"]}).status_code in (400, 404)


# --- Tasks: defer and repeat ----------------------------------------------------------

def test_defer_has_limits(client, h):
    due = (TODAY + timedelta(days=2)).isoformat()
    t = client.post("/api/tasks", headers=h, json={"title": "Call bank", "due_date": due}).json()
    ok = client.post(f"/api/tasks/{t['id']}/defer", headers=h,
                     json={"deferred_until": (TODAY + timedelta(days=5)).isoformat()})
    assert ok.status_code == 200 and ok.json()["defer_count"] == 1
    too_far = client.post(f"/api/tasks/{t['id']}/defer", headers=h,
                          json={"deferred_until": (TODAY + timedelta(days=60)).isoformat()})
    assert too_far.status_code == 400
    past = client.post(f"/api/tasks/{t['id']}/defer", headers=h,
                       json={"deferred_until": (TODAY - timedelta(days=1)).isoformat()})
    assert past.status_code == 400


def test_repeating_task_spawns_the_next_one(client, h):
    due = TODAY.isoformat()
    t = client.post("/api/tasks", headers=h, json={"title": "Water plants", "due_date": due,
                                                    "recurrence": {"cadence": "weekly", "anchor_date": due}})
    assert t.status_code == 201, t.text
    done = client.put(f"/api/tasks/{t.json()['id']}", headers=h, json={"status": "done"})
    assert done.status_code == 200
    titles = [(x["title"], x["due_date"], x["status"]) for x in client.get("/api/tasks", headers=h).json()]
    assert ("Water plants", (TODAY + timedelta(days=7)).isoformat(), "todo") in titles
    bad = client.post("/api/tasks", headers=h, json={"title": "Bad", "due_date": due,
                                                      "recurrence": {"cadence": "hourly"}})
    assert bad.status_code == 400


# --- Check-ins --------------------------------------------------------------------------

def test_checkins_search_and_isolation(client, h, other):
    for title, note in (("Morning run", "5 km by the lake"), ("Budget review", "cut food delivery"),
                        ("Guitar", "chords (C, G)")):
        r = client.post("/api/checkins", headers=h, json={"type": "life", "title": title, "date": TODAY.isoformat(),
                                                          "time": "07:00", "notes": note})
        assert r.status_code == 201, r.text
    found = [c["title"] for c in client.get("/api/checkins?q=lake", headers=h).json()]
    assert found == ["Morning run"]
    assert [c["title"] for c in client.get("/api/checkins?q=(C,", headers=h).json()] == ["Guitar"]   # literal
    assert client.get("/api/checkins?q=.*", headers=h).json() == []
    assert client.get("/api/checkins", headers=other).json() == []
