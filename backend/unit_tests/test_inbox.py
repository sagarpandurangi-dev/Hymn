"""Brain-dump inbox: capture, review, migration, patterns.

Claude is replaced by fakes; ``test_inbox_ai.py`` covers the real call's
error handling.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

import inbox
import inbox_ai


@pytest.fixture()
def auth(client):
    r = client.post("/api/auth/signup", json={
        "name": "Test User",
        "email": "dump@example.com",
        "password": "correct-horse-battery",
        "security_question": "City?",
        "security_answer": "Pune",
    })
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def fake_sorter(monkeypatch):
    """Sorts each line of the dump; a line starting with "remind" is a reminder."""
    calls = []

    async def sort_dump(raw_text, *, now_local, tz_name):
        calls.append({"raw_text": raw_text, "now_local": now_local, "tz_name": tz_name})
        items = []
        for line in filter(None, (l.strip() for l in raw_text.splitlines())):
            if line.startswith("remind"):
                items.append(inbox_ai.SortedItem(
                    text=line, category="reminder", remind_at_local="2026-11-12T09:00",
                ))
            elif line.startswith("maybe"):
                items.append(inbox_ai.SortedItem(text=line, category="idea", remind_at_local=""))
            else:
                items.append(inbox_ai.SortedItem(text=line, category="task", remind_at_local=""))
        return inbox_ai.SortedDump(items=items, encouragement="Nice, that's out of your head.")

    monkeypatch.setattr(inbox_ai, "sort_dump", sort_dump)
    return calls


@pytest.fixture()
def broken_sorter(monkeypatch):
    async def sort_dump(raw_text, *, now_local, tz_name):
        raise inbox_ai.AssistantUnavailable("API error 529")

    monkeypatch.setattr(inbox_ai, "sort_dump", sort_dump)


def _dump(client, auth, text, **extra):
    r = client.post("/api/inbox/dumps", json={"text": text, **extra}, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


def _open_items(client, auth):
    r = client.get("/api/inbox/items", headers=auth)
    assert r.status_code == 200
    return r.json()


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------

def test_dump_is_split_and_acknowledged(client, auth, fake_sorter):
    body = _dump(client, auth, "renew passport\nmaybe learn guitar\nremind mom birthday",
                 timezone="Asia/Kolkata")
    assert body["dump"]["status"] == "sorted"
    assert [i["category"] for i in body["items"]] == ["task", "idea", "reminder"]
    assert body["ack"] == "Nice, that's out of your head. Saved: 1 task, 1 reminder, 1 idea."
    assert fake_sorter[0]["tz_name"] == "Asia/Kolkata"


def test_reminder_time_is_converted_from_user_timezone(client, auth, fake_sorter):
    body = _dump(client, auth, "remind mom birthday", timezone="Asia/Kolkata")
    # 09:00 in Kolkata (UTC+5:30) is 03:30 UTC.
    assert body["items"][0]["remind_at"] == "2026-11-12T03:30:00+00:00"


def test_timezone_is_remembered_for_later_dumps(client, auth, fake_sorter):
    _dump(client, auth, "a", timezone="Europe/Oslo")
    _dump(client, auth, "b")
    assert fake_sorter[1]["tz_name"] == "Europe/Oslo"


def test_unknown_timezone_is_rejected(client, auth, fake_sorter):
    r = client.post("/api/inbox/dumps", json={"text": "x", "timezone": "Mars/Base"}, headers=auth)
    assert r.status_code == 400


def test_retried_submit_is_stored_once(client, auth, fake_sorter):
    first = _dump(client, auth, "renew passport", client_dump_id="dump-0001-abcd")
    second = _dump(client, auth, "renew passport", client_dump_id="dump-0001-abcd")
    assert first["dump"]["id"] == second["dump"]["id"]
    assert len(fake_sorter) == 1
    assert len(_open_items(client, auth)) == 1


def test_dump_is_never_lost_when_sorting_fails(client, auth, broken_sorter):
    body = _dump(client, auth, "renew passport and call Raj")
    assert body["dump"]["status"] == "unsorted"
    assert [(i["category"], i["text"]) for i in body["items"]] == [
        ("unsorted", "renew passport and call Raj"),
    ]
    assert "safe in your inbox" in body["ack"]
    review = client.get("/api/inbox/review", headers=auth).json()
    assert [i["text"] for i in review["items"]] == ["renew passport and call Raj"]


def test_resort_replaces_the_unsorted_item(client, auth, broken_sorter, monkeypatch):
    dump_id = _dump(client, auth, "renew passport\ncall Raj")["dump"]["id"]

    async def sort_dump(raw_text, *, now_local, tz_name):
        return inbox_ai.SortedDump(items=[
            inbox_ai.SortedItem(text="renew passport", category="task", remind_at_local=""),
            inbox_ai.SortedItem(text="call Raj", category="task", remind_at_local=""),
        ], encouragement="Done.")

    monkeypatch.setattr(inbox_ai, "sort_dump", sort_dump)
    r = client.post(f"/api/inbox/dumps/{dump_id}/sort", headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["dump"]["status"] == "sorted"
    assert sorted(i["text"] for i in _open_items(client, auth)) == ["call Raj", "renew passport"]


def test_resort_refuses_once_the_raw_item_was_handled(client, auth, broken_sorter):
    body = _dump(client, auth, "renew passport")
    item_id = body["items"][0]["id"]
    client.post("/api/inbox/review", json={"decisions": [{"item_id": item_id, "decision": "done"}]},
                headers=auth)
    r = client.post(f"/api/inbox/dumps/{body['dump']['id']}/sort", headers=auth)
    assert r.status_code == 409


def test_resort_of_a_sorted_dump_is_refused(client, auth, fake_sorter):
    dump_id = _dump(client, auth, "renew passport")["dump"]["id"]
    assert client.post(f"/api/inbox/dumps/{dump_id}/sort", headers=auth).status_code == 409


def test_dumps_are_private(client, auth, fake_sorter):
    _dump(client, auth, "renew passport")
    r = client.post("/api/auth/signup", json={
        "name": "Other", "email": "other@example.com", "password": "another-long-password",
        "security_question": "Q?", "security_answer": "A",
    })
    other = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert _open_items(client, other) == []


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------

def test_review_decisions_update_items(client, auth, fake_sorter):
    items = _dump(client, auth, "a\nb\nc\nd")["items"]
    ids = [i["id"] for i in items]
    r = client.post("/api/inbox/review", headers=auth, json={"decisions": [
        {"item_id": ids[0], "decision": "done"},
        {"item_id": ids[1], "decision": "discard"},
        {"item_id": ids[2], "decision": "nugget"},
        {"item_id": ids[3], "decision": "keep"},
    ]})
    assert r.status_code == 200, r.text
    assert r.json()["counts"] == {"done": 1, "discard": 1, "nugget": 1, "keep": 1}
    assert [n["id"] for n in r.json()["nuggets"]] == [ids[2]]

    still_open = _open_items(client, auth)
    assert [(i["id"], i["review_count"]) for i in still_open] == [(ids[3], 1)]


def test_review_batch_is_capped_and_puts_due_reminders_first(client, auth, fake_sorter, server):
    _dump(client, auth, "\n".join(f"task {n}" for n in range(12)))
    reminder = _dump(client, auth, "remind dentist")["items"][0]
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    asyncio.run(server.db.inbox_items.update_one({"id": reminder["id"]}, {"$set": {"remind_at": past}}))

    review = client.get("/api/inbox/review?limit=5", headers=auth).json()
    assert len(review["items"]) == 5
    assert review["items"][0]["id"] == reminder["id"]
    assert review["open_total"] == 13
    assert review["prompt"] == inbox.REVIEW_PROMPT


def test_review_rejects_items_that_are_not_open(client, auth, fake_sorter):
    item_id = _dump(client, auth, "a")["items"][0]["id"]
    done = {"decisions": [{"item_id": item_id, "decision": "done"}]}
    assert client.post("/api/inbox/review", json=done, headers=auth).status_code == 200
    assert client.post("/api/inbox/review", json=done, headers=auth).status_code == 400


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

def _nugget(client, auth, text="get fit"):
    item_id = _dump(client, auth, text)["items"][0]["id"]
    client.post("/api/inbox/review", json={"decisions": [{"item_id": item_id, "decision": "nugget"}]},
                headers=auth)
    return item_id


def test_migrate_to_task_creates_a_hymn_task(client, auth, fake_sorter):
    item_id = _nugget(client, auth)
    r = client.post(f"/api/inbox/items/{item_id}/migrate", headers=auth, json={
        "destination": "task", "next_step": "Book a gym trial for Saturday",
    })
    assert r.status_code == 200, r.text
    task_id = r.json()["migrated_to"]["id"]
    task = client.get(f"/api/tasks/{task_id}", headers=auth).json()
    assert task["title"] == "Book a gym trial for Saturday"
    assert task["notes"] == "From your brain dump: get fit"
    assert r.json()["item"]["status"] == "migrated"
    assert client.get("/api/inbox/review", headers=auth).json()["nuggets"] == []


def test_migrate_to_calendar_needs_a_date(client, auth, fake_sorter):
    item_id = _nugget(client, auth)
    url = f"/api/inbox/items/{item_id}/migrate"
    no_date = {"destination": "calendar", "next_step": "Gym trial"}
    assert client.post(url, json=no_date, headers=auth).status_code == 400
    r = client.post(url, headers=auth, json={**no_date, "due_date": "2026-11-01", "time": "07:30"})
    assert r.status_code == 200, r.text
    task = client.get(f"/api/tasks/{r.json()['migrated_to']['id']}", headers=auth).json()
    assert task["due_date"] == "2026-11-01"
    assert task["notes"].startswith("Scheduled for 07:30.")


def test_migrate_to_wishlist(client, auth, fake_sorter):
    item_id = _nugget(client, auth, "noise-cancelling headphones")
    r = client.post(f"/api/inbox/items/{item_id}/migrate", headers=auth, json={
        "destination": "wishlist", "next_step": "Compare two models",
    })
    assert r.status_code == 200, r.text
    wishlist = client.get("/api/inbox/wishlist", headers=auth).json()
    assert [(w["title"], w["next_step"]) for w in wishlist] == [
        ("noise-cancelling headphones", "Compare two models"),
    ]


def test_migrate_twice_is_refused(client, auth, fake_sorter):
    item_id = _nugget(client, auth)
    body = {"destination": "wishlist", "next_step": "x"}
    assert client.post(f"/api/inbox/items/{item_id}/migrate", json=body, headers=auth).status_code == 200
    assert client.post(f"/api/inbox/items/{item_id}/migrate", json=body, headers=auth).status_code == 409


def test_failed_migration_leaves_the_item_where_it_was(client, auth, fake_sorter):
    item_id = _nugget(client, auth)
    r = client.post(f"/api/inbox/items/{item_id}/migrate", headers=auth, json={
        "destination": "task", "next_step": "x", "project_id": "no-such-project",
    })
    assert r.status_code == 400
    review = client.get("/api/inbox/review", headers=auth).json()
    assert [n["id"] for n in review["nuggets"]] == [item_id]


# ---------------------------------------------------------------------------
# Item edits
# ---------------------------------------------------------------------------

def test_user_can_correct_category_and_reminder_time(client, auth, fake_sorter):
    item_id = _dump(client, auth, "dentist")["items"][0]["id"]
    r = client.patch(f"/api/inbox/items/{item_id}", headers=auth, json={
        "category": "reminder", "remind_at": "2026-11-03T10:00:00+05:30",
    })
    assert r.status_code == 200, r.text
    assert r.json()["category"] == "reminder"
    assert r.json()["remind_at"] == "2026-11-03T04:30:00+00:00"
    naive = {"remind_at": "2026-11-03T10:00:00"}
    assert client.patch(f"/api/inbox/items/{item_id}", json=naive, headers=auth).status_code == 400


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

def test_weekly_patterns_flag_avoided_items(client, auth, fake_sorter, monkeypatch):
    items = _dump(client, auth, "file taxes\ncall Raj")["items"]
    taxes = items[0]["id"]
    for _ in range(inbox.AVOIDED_AFTER_REVIEWS):
        client.post("/api/inbox/review", json={"decisions": [{"item_id": taxes, "decision": "keep"}]},
                    headers=auth)
    client.post("/api/inbox/review", json={"decisions": [{"item_id": items[1]["id"], "decision": "done"}]},
                headers=auth)

    reports = []

    async def summarise_patterns(week_report):
        reports.append(week_report)
        return inbox_ai.WeeklyPatterns(
            themes=["admin"], avoidance=["file taxes: unclear next step"],
            suggestions=["Split taxes into a 15-minute first step"], summary="Good week.",
        )

    monkeypatch.setattr(inbox_ai, "summarise_patterns", summarise_patterns)
    r = client.post("/api/inbox/patterns", headers=auth)
    assert r.status_code == 201, r.text
    stats = r.json()["stats"]
    assert stats["captured"] == 2
    assert stats["completed"] == 1
    assert stats["reviews"] == inbox.AVOIDED_AFTER_REVIEWS + 1
    assert [a["text"] for a in stats["avoided"]] == ["file taxes"]
    assert "file taxes" in reports[0]
    assert r.json()["insight"]["avoidance"] == ["file taxes: unclear next step"]
    assert client.get("/api/inbox/patterns", headers=auth).json()["id"] == r.json()["id"]


def test_patterns_keep_stats_when_the_model_is_down(client, auth, fake_sorter, monkeypatch):
    _dump(client, auth, "a")

    async def summarise_patterns(week_report):
        raise inbox_ai.AssistantUnavailable("connection error")

    monkeypatch.setattr(inbox_ai, "summarise_patterns", summarise_patterns)
    body = client.post("/api/inbox/patterns", headers=auth).json()
    assert body["insight"] is None
    assert body["error"] == "connection error"
    assert body["stats"]["captured"] == 1


def test_no_patterns_yet_is_404(client, auth):
    assert client.get("/api/inbox/patterns", headers=auth).status_code == 404
