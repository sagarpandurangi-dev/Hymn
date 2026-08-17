"""Recurrence (task/check-in cadence) smoke tests for Hymn.

Covers:
- Task creation with recurrence (spec normalisation + series_id)
- Auto-spawn on completion (option A)
- Pre-generate (option B)
- POST/DELETE /tasks/{id}/recurrence
- POST /tasks/{id}/recurrence/generate (idempotency by due_date)
- end_type=until and end_type=count end-conditions
- Extended goal cadences (quarterly, fortnightly) accepted, invalid rejected
- /checkins/required scheduler for extended cadences
- Legacy cadences still work
- Invalid recurrence payloads rejected with 400
"""

import os
from datetime import date, timedelta

import pytest
import requests

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
EMAIL = "test@hymn.app"
PASSWORD = "TestPass123!"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    token = r.json().get("token") or r.json().get("access_token")
    assert token, f"No token in login response: {r.json()}"
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


@pytest.fixture(scope="module")
def domain_id(session):
    r = session.get(f"{BASE_URL}/api/domains")
    assert r.status_code == 200, r.text
    doms = r.json()
    assert doms, "No domains available for user"
    return doms[0]["id"]


# Track ids we create so we can clean up
_created_task_ids: list = []
_created_goal_ids: list = []
_created_series_ids: set = set()
_created_eo_ids: list = []
_created_checkin_ids: list = []


def _track_task(t):
    if t and t.get("id"):
        _created_task_ids.append(t["id"])
        sid = (t.get("recurrence") or {}).get("series_id") or t.get("series_id")
        if sid:
            _created_series_ids.add(sid)


# ---------------------------------------------------------------------------
# 1. Task creation with recurrence
# ---------------------------------------------------------------------------
class TestRecurrenceCreation:
    def test_create_task_with_weekly_count_recurrence(self, session):
        payload = {
            "title": "TEST_Recur test",
            "origin": "standalone",
            "due_date": "2026-06-15",
            "recurrence": {
                "cadence": "weekly",
                "anchor_date": "2026-06-15",
                "end_type": "count",
                "occurrences_remaining": 5,
                "pre_generate_count": 0,
            },
        }
        r = session.post(f"{BASE_URL}/api/tasks", json=payload)
        assert r.status_code == 201, r.text
        t = r.json()
        _track_task(t)
        assert t["recurrence"] is not None
        assert t["recurrence"]["series_id"], "series_id not populated"
        assert t.get("occurrence_index") == 1, f"expected occurrence_index=1 got {t.get('occurrence_index')}"
        assert t["recurrence"]["cadence"] == "weekly"
        assert t["recurrence"]["occurrences_remaining"] == 5
        pytest.head_weekly_task_id = t["id"]
        pytest.head_weekly_series_id = t["recurrence"]["series_id"]


# ---------------------------------------------------------------------------
# 2. Auto-spawn on completion (option A)
# ---------------------------------------------------------------------------
class TestAutoSpawnOnCompletion:
    def test_completing_recurring_task_spawns_next(self, session):
        head_id = getattr(pytest, "head_weekly_task_id", None)
        assert head_id, "prerequisite task from test 1 missing"
        series_id = pytest.head_weekly_series_id

        # Mark done
        r = session.put(f"{BASE_URL}/api/tasks/{head_id}", json={"status": "done"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "done"

        # List tasks including completed
        r = session.get(f"{BASE_URL}/api/tasks", params={"includeCompleted": "true"})
        assert r.status_code == 200, r.text
        tasks = r.json()

        series_tasks = [t for t in tasks if (t.get("series_id") == series_id) or ((t.get("recurrence") or {}).get("series_id") == series_id)]
        assert len(series_tasks) >= 2, f"expected at least 2 tasks in series, got {len(series_tasks)}"

        original = next((t for t in series_tasks if t["id"] == head_id), None)
        spawned = next((t for t in series_tasks if t["id"] != head_id and t["due_date"] == "2026-06-22"), None)
        assert original is not None and original["status"] == "done"
        assert spawned is not None, f"no spawned sibling with due_date=2026-06-22. series_tasks={series_tasks}"
        _track_task(spawned)
        assert spawned["status"] == "todo"
        rec = spawned.get("recurrence") or {}
        assert rec.get("occurrences_remaining") == 4, f"expected decremented to 4, got {rec.get('occurrences_remaining')}"


# ---------------------------------------------------------------------------
# 3. Pre-generate (option B)
# ---------------------------------------------------------------------------
class TestPreGenerate:
    def test_alternate_day_pre_generate_three(self, session):
        payload = {
            "title": "TEST_Pregen alt-day",
            "origin": "standalone",
            "due_date": "2026-07-01",
            "recurrence": {
                "cadence": "alternate_day",
                "anchor_date": "2026-07-01",
                "end_type": "never",
                "pre_generate_count": 3,
            },
        }
        r = session.post(f"{BASE_URL}/api/tasks", json=payload)
        assert r.status_code == 201, r.text
        head = r.json()
        _track_task(head)
        series_id = head["recurrence"]["series_id"]

        # List and count series
        r = session.get(f"{BASE_URL}/api/tasks", params={"includeCompleted": "true"})
        assert r.status_code == 200
        tasks = r.json()
        siblings = [t for t in tasks if (t.get("series_id") == series_id) or ((t.get("recurrence") or {}).get("series_id") == series_id)]
        for t in siblings:
            _track_task(t)
        due_dates = sorted([t["due_date"] for t in siblings])
        expected = ["2026-07-01", "2026-07-03", "2026-07-05", "2026-07-07"]
        assert due_dates == expected, f"expected {expected}, got {due_dates}"


# ---------------------------------------------------------------------------
# 4. POST/DELETE /tasks/{id}/recurrence
# ---------------------------------------------------------------------------
class TestSetClearRecurrence:
    def test_set_then_clear_recurrence(self, session):
        # Create plain task (no recurrence)
        r = session.post(f"{BASE_URL}/api/tasks", json={
            "title": "TEST_Plain then rec",
            "origin": "standalone",
            "due_date": "2026-08-01",
        })
        assert r.status_code == 201, r.text
        t = r.json()
        _track_task(t)
        assert (t.get("recurrence") or None) is None

        # Attach recurrence
        r = session.post(f"{BASE_URL}/api/tasks/{t['id']}/recurrence", json={
            "cadence": "monthly",
            "anchor_date": "2026-08-01",
            "end_type": "never",
            "pre_generate_count": 0,
        })
        assert r.status_code == 200, r.text
        attached = r.json()
        assert attached["recurrence"]["cadence"] == "monthly"
        assert attached["recurrence"]["series_id"]

        # Clear recurrence
        r = session.delete(f"{BASE_URL}/api/tasks/{t['id']}/recurrence")
        assert r.status_code == 200, r.text
        cleared = r.json()
        assert (cleared.get("recurrence") or None) is None, f"recurrence not cleared: {cleared.get('recurrence')}"


# ---------------------------------------------------------------------------
# 5. POST /tasks/{id}/recurrence/generate — idempotent by due_date
# ---------------------------------------------------------------------------
class TestGenerateEndpoint:
    def test_generate_three_and_idempotency(self, session):
        r = session.post(f"{BASE_URL}/api/tasks", json={
            "title": "TEST_Gen idempotent",
            "origin": "standalone",
            "due_date": "2026-09-01",
            "recurrence": {
                "cadence": "weekly",
                "anchor_date": "2026-09-01",
                "end_type": "never",
                "pre_generate_count": 0,
            },
        })
        assert r.status_code == 201, r.text
        head = r.json()
        _track_task(head)
        series_id = head["recurrence"]["series_id"]
        tid = head["id"]

        r = session.post(f"{BASE_URL}/api/tasks/{tid}/recurrence/generate", json={"count": 3})
        assert r.status_code == 200, r.text
        spawned = r.json()
        assert len(spawned) == 3, f"expected 3 new siblings, got {len(spawned)}"
        for s in spawned:
            _track_task(s)
        due_dates_new = sorted([s["due_date"] for s in spawned])
        assert due_dates_new == ["2026-09-08", "2026-09-15", "2026-09-22"], due_dates_new

        # Re-run — idempotent by due_date. New calls should NOT duplicate existing.
        r = session.post(f"{BASE_URL}/api/tasks/{tid}/recurrence/generate", json={"count": 3})
        assert r.status_code == 200, r.text
        second = r.json()
        # The endpoint should have avoided duplicating the same 3 due_dates.
        second_due_dates = sorted([s["due_date"] for s in second])
        overlap = set(second_due_dates) & set(due_dates_new)
        assert not overlap, f"idempotency broken: overlapping due_dates {overlap} (second={second_due_dates})"
        for s in second:
            _track_task(s)


# ---------------------------------------------------------------------------
# 6. end_type=until
# ---------------------------------------------------------------------------
class TestEndUntil:
    def test_monthly_until_end(self, session):
        r = session.post(f"{BASE_URL}/api/tasks", json={
            "title": "TEST_Until",
            "origin": "standalone",
            "due_date": "2026-06-01",
            "recurrence": {
                "cadence": "monthly",
                "anchor_date": "2026-06-01",
                "end_type": "until",
                "end_date": "2026-08-15",
                "pre_generate_count": 0,
            },
        })
        assert r.status_code == 201, r.text
        head = r.json()
        _track_task(head)
        series_id = head["recurrence"]["series_id"]

        def _get_series():
            resp = session.get(f"{BASE_URL}/api/tasks", params={"includeCompleted": "true"})
            resp.raise_for_status()
            return [t for t in resp.json() if (t.get("series_id") == series_id) or ((t.get("recurrence") or {}).get("series_id") == series_id)]

        # Complete #1 (2026-06-01) → spawn 07-01
        r = session.put(f"{BASE_URL}/api/tasks/{head['id']}", json={"status": "done"})
        assert r.status_code == 200
        siblings = _get_series()
        for s in siblings:
            _track_task(s)
        due_dates = sorted([t["due_date"] for t in siblings])
        assert "2026-07-01" in due_dates, f"first spawn missing: {due_dates}"

        # Complete #2 (2026-07-01)
        july = next(t for t in siblings if t["due_date"] == "2026-07-01")
        r = session.put(f"{BASE_URL}/api/tasks/{july['id']}", json={"status": "done"})
        assert r.status_code == 200
        siblings = _get_series()
        for s in siblings:
            _track_task(s)
        due_dates = sorted([t["due_date"] for t in siblings])
        assert "2026-08-01" in due_dates, f"second spawn missing: {due_dates}"

        # Complete #3 (2026-08-01) — NO further spawn (2026-09-01 > end_date 2026-08-15)
        aug = next(t for t in siblings if t["due_date"] == "2026-08-01")
        r = session.put(f"{BASE_URL}/api/tasks/{aug['id']}", json={"status": "done"})
        assert r.status_code == 200
        siblings = _get_series()
        for s in siblings:
            _track_task(s)
        due_dates = sorted([t["due_date"] for t in siblings])
        assert "2026-09-01" not in due_dates, f"unexpected spawn past end_date: {due_dates}"
        # Should have exactly 3 tasks in series
        assert len(siblings) == 3, f"expected exactly 3 tasks, got {len(siblings)}: {due_dates}"


# ---------------------------------------------------------------------------
# 7. end_type=count with occurrences_remaining=1
# ---------------------------------------------------------------------------
class TestEndCountOne:
    def test_count_one_no_followup(self, session):
        r = session.post(f"{BASE_URL}/api/tasks", json={
            "title": "TEST_Count-one",
            "origin": "standalone",
            "due_date": "2026-10-01",
            "recurrence": {
                "cadence": "weekly",
                "anchor_date": "2026-10-01",
                "end_type": "count",
                "occurrences_remaining": 1,
                "pre_generate_count": 0,
            },
        })
        assert r.status_code == 201, r.text
        head = r.json()
        _track_task(head)
        series_id = head["recurrence"]["series_id"]

        # Complete
        r = session.put(f"{BASE_URL}/api/tasks/{head['id']}", json={"status": "done"})
        assert r.status_code == 200
        r = session.get(f"{BASE_URL}/api/tasks", params={"includeCompleted": "true"})
        siblings = [t for t in r.json() if (t.get("series_id") == series_id) or ((t.get("recurrence") or {}).get("series_id") == series_id)]
        for s in siblings:
            _track_task(s)
        assert len(siblings) == 1, f"expected NO spawn (count=1), got {len(siblings)} tasks: {[t['due_date'] for t in siblings]}"


# ---------------------------------------------------------------------------
# 8. Extended goal cadences accepted / bogus rejected
# ---------------------------------------------------------------------------
class TestGoalExtendedCadences:
    def test_quarterly_accepted(self, session, domain_id):
        r = session.post(f"{BASE_URL}/api/goals", json={
            "title": "TEST_Goal quarterly",
            "domain_id": domain_id,
            "checkin_cadence": "quarterly",
            "checkin_anchor_date": "2026-01-15",
        })
        assert r.status_code == 201, r.text
        g = r.json()
        _created_goal_ids.append(g["id"])
        assert g["checkin_cadence"] == "quarterly"

    def test_fortnightly_accepted(self, session, domain_id):
        r = session.post(f"{BASE_URL}/api/goals", json={
            "title": "TEST_Goal fortnightly",
            "domain_id": domain_id,
            "checkin_cadence": "fortnightly",
        })
        assert r.status_code == 201, r.text
        g = r.json()
        _created_goal_ids.append(g["id"])
        assert g["checkin_cadence"] == "fortnightly"

    def test_bogus_rejected(self, session, domain_id):
        r = session.post(f"{BASE_URL}/api/goals", json={
            "title": "TEST_Goal bogus",
            "domain_id": domain_id,
            "checkin_cadence": "bogus",
        })
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"


# ---------------------------------------------------------------------------
# 9. Required-checkin scheduler with extended cadence (alternate_day)
# ---------------------------------------------------------------------------
class TestRequiredCheckinAlternateDay:
    def test_alternate_day_period_membership(self, session, domain_id):
        # Create goal
        r = session.post(f"{BASE_URL}/api/goals", json={
            "title": "TEST_Goal alt-day",
            "domain_id": domain_id,
            "checkin_cadence": "alternate_day",
            "checkin_anchor_date": "2026-06-10",
        })
        assert r.status_code == 201, r.text
        goal = r.json()
        _created_goal_ids.append(goal["id"])

        # Create an EO under the goal so we can make a check-in
        r = session.post(f"{BASE_URL}/api/expected-outcomes", json={
            "goal_id": goal["id"],
            "title": "TEST_EO alt-day",
            "outcome_type": "generic",
        })
        assert r.status_code == 201, r.text
        eo = r.json()
        _created_eo_ids.append(eo["id"])

        # Both 2026-06-10 and 2026-06-11 should show the goal as required
        for d in ("2026-06-10", "2026-06-11"):
            r = session.get(f"{BASE_URL}/api/checkins/required", params={"date": d})
            assert r.status_code == 200, r.text
            required_ids = {g["goal_id"] for g in r.json()}
            assert goal["id"] in required_ids, f"goal missing from required on {d}: {r.json()}"

        # Create a check-in on 2026-06-10
        r = session.post(f"{BASE_URL}/api/checkins", json={
            "type": "goal",
            "title": "TEST_Checkin alt-day",
            "date": "2026-06-10",
            "time": "09:00",
            "expected_outcome_id": eo["id"],
            "data": {"note": "period covered"},
        })
        assert r.status_code == 201, r.text
        ci = r.json()
        _created_checkin_ids.append(ci["id"])

        # Goal should disappear from BOTH 06-10 and 06-11 responses
        for d in ("2026-06-10", "2026-06-11"):
            r = session.get(f"{BASE_URL}/api/checkins/required", params={"date": d})
            assert r.status_code == 200
            required_ids = {g["goal_id"] for g in r.json()}
            assert goal["id"] not in required_ids, f"goal STILL required on {d} after check-in: {r.json()}"


# ---------------------------------------------------------------------------
# 10. Legacy daily cadence still works
# ---------------------------------------------------------------------------
class TestLegacyDaily:
    def test_daily_goal_shows_as_required_today(self, session, domain_id):
        today = date.today().isoformat()
        r = session.post(f"{BASE_URL}/api/goals", json={
            "title": "TEST_Goal daily legacy",
            "domain_id": domain_id,
            "checkin_cadence": "daily",
        })
        assert r.status_code == 201, r.text
        g = r.json()
        _created_goal_ids.append(g["id"])

        r = session.get(f"{BASE_URL}/api/checkins/required", params={"date": today})
        assert r.status_code == 200
        required_ids = {x["goal_id"] for x in r.json()}
        assert g["id"] in required_ids, f"daily goal not in required list for {today}"


# ---------------------------------------------------------------------------
# 11. Invalid recurrence payloads → 400
# ---------------------------------------------------------------------------
class TestInvalidRecurrence:
    @pytest.mark.parametrize("rec, label", [
        ({"anchor_date": "2026-06-15", "end_type": "never"}, "missing cadence"),
        ({"cadence": "every_leap_year", "anchor_date": "2026-06-15", "end_type": "never"}, "unknown cadence"),
        ({"cadence": "weekly", "anchor_date": "2026-06-15", "end_type": "until"}, "until without end_date"),
        ({"cadence": "weekly", "anchor_date": "2026-06-15", "end_type": "count", "occurrences_remaining": 0}, "count with 0"),
        ({"cadence": "weekly", "anchor_date": "2026-06-15", "end_type": "until", "end_date": "2026-06-01"}, "end_date < anchor"),
    ])
    def test_invalid_recurrence(self, session, rec, label):
        payload = {
            "title": f"TEST_Invalid {label}",
            "origin": "standalone",
            "due_date": "2026-06-15",
            "recurrence": rec,
        }
        r = session.post(f"{BASE_URL}/api/tasks", json=payload)
        # If a task somehow gets created, track it for cleanup
        if r.status_code == 201:
            _track_task(r.json())
        assert r.status_code == 400, f"[{label}] expected 400, got {r.status_code}: {r.text}"


# ---------------------------------------------------------------------------
# Cleanup — runs after all tests in module
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module", autouse=True)
def _cleanup(session):
    yield
    # Delete tasks (unique)
    for tid in set(_created_task_ids):
        try:
            session.delete(f"{BASE_URL}/api/tasks/{tid}")
        except Exception:
            pass
    # Also sweep any task in tracked series that we may have missed
    for sid in _created_series_ids:
        try:
            r = session.get(f"{BASE_URL}/api/tasks", params={"includeCompleted": "true"})
            if r.status_code == 200:
                for t in r.json():
                    if (t.get("series_id") == sid) or ((t.get("recurrence") or {}).get("series_id") == sid):
                        session.delete(f"{BASE_URL}/api/tasks/{t['id']}")
        except Exception:
            pass
    # Delete check-ins
    for cid in set(_created_checkin_ids):
        try:
            session.delete(f"{BASE_URL}/api/checkins/{cid}")
        except Exception:
            pass
    # Delete EOs
    for eid in set(_created_eo_ids):
        try:
            session.delete(f"{BASE_URL}/api/expected-outcomes/{eid}")
        except Exception:
            pass
    # Delete goals (last, after EOs)
    for gid in set(_created_goal_ids):
        try:
            session.delete(f"{BASE_URL}/api/goals/{gid}")
        except Exception:
            pass
