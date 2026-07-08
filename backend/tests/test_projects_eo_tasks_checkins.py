"""Backend tests for Projects, Expected Outcomes, Tasks, Check-ins (Hymn core model pivot)."""
import os
import uuid

import pytest
import requests

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

DEFAULTS = {"Knowledge", "Health", "Money", "Soul"}


def _signup(email: str, password: str = "TestPass123!") -> str:
    r = requests.post(
        f"{API}/auth/signup",
        json={"email": email, "password": password, "security_question": "q?", "security_answer": "a"},
        timeout=15,
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


def _h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _first_default_domain_id(tok: str) -> str:
    lst = requests.get(f"{API}/domains", headers=_h(tok), timeout=10).json()
    for d in lst:
        if d["name"] in DEFAULTS:
            return d["id"]
    raise AssertionError("no default domain found")


def _mk_goal(tok: str, title: str = "TEST_goal") -> dict:
    did = _first_default_domain_id(tok)
    r = requests.post(f"{API}/goals", headers=_h(tok), json={"title": title, "domain_id": did}, timeout=10)
    assert r.status_code == 201, r.text
    return r.json()


def _mk_eo(tok: str, goal_id: str, title: str = "TEST_eo", status: str = "active") -> dict:
    r = requests.post(
        f"{API}/expected-outcomes",
        headers=_h(tok),
        json={"goal_id": goal_id, "title": title, "status": status},
        timeout=10,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _mk_project(tok: str, title: str = "TEST_proj", status: str = "active") -> dict:
    r = requests.post(
        f"{API}/projects",
        headers=_h(tok),
        json={"title": title, "status": status},
        timeout=10,
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture(scope="module")
def token_a() -> str:
    return _signup(f"TEST_core_a_{uuid.uuid4().hex[:8]}@hymn.app")


@pytest.fixture(scope="module")
def token_b() -> str:
    return _signup(f"TEST_core_b_{uuid.uuid4().hex[:8]}@hymn.app")


# ---------- Legacy /events endpoint gone ----------
class TestEventsRemoved:
    def test_get_events_404(self, token_a):
        r = requests.get(f"{API}/events", headers=_h(token_a), timeout=10)
        assert r.status_code == 404

    def test_post_events_404_or_405(self, token_a):
        r = requests.post(f"{API}/events", headers=_h(token_a), json={"title": "x"}, timeout=10)
        assert r.status_code in (404, 405)


# ---------- Projects CRUD ----------
class TestProjects:
    def test_create_and_get(self, token_a):
        p = _mk_project(token_a, title=f"TEST_p_{uuid.uuid4().hex[:6]}")
        r = requests.get(f"{API}/projects/{p['id']}", headers=_h(token_a), timeout=10)
        assert r.status_code == 200
        assert r.json()["title"] == p["title"]
        assert r.json()["status"] == "active"

    def test_create_invalid_status_400(self, token_a):
        r = requests.post(f"{API}/projects", headers=_h(token_a), json={"title": "x", "status": "bogus"}, timeout=10)
        assert r.status_code == 400

    def test_list_only_own(self, token_a, token_b):
        p = _mk_project(token_a, title=f"TEST_own_{uuid.uuid4().hex[:6]}")
        lst_b = requests.get(f"{API}/projects", headers=_h(token_b), timeout=10).json()
        assert not any(x["id"] == p["id"] for x in lst_b)

    def test_cross_user_get_returns_404(self, token_a, token_b):
        p = _mk_project(token_a, title="TEST_iso_p")
        assert requests.get(f"{API}/projects/{p['id']}", headers=_h(token_b), timeout=10).status_code == 404
        assert requests.put(f"{API}/projects/{p['id']}", headers=_h(token_b), json={"title": "hack"}, timeout=10).status_code == 404
        assert requests.delete(f"{API}/projects/{p['id']}", headers=_h(token_b), timeout=10).status_code == 404

    def test_update_and_delete(self, token_a):
        p = _mk_project(token_a, title="TEST_upd_p")
        r = requests.put(f"{API}/projects/{p['id']}", headers=_h(token_a), json={"title": "TEST_upd_p2", "status": "paused"}, timeout=10)
        assert r.status_code == 200
        assert r.json()["title"] == "TEST_upd_p2"
        assert r.json()["status"] == "paused"
        # invalid status update
        assert requests.put(f"{API}/projects/{p['id']}", headers=_h(token_a), json={"status": "bogus"}, timeout=10).status_code == 400
        # delete
        assert requests.delete(f"{API}/projects/{p['id']}", headers=_h(token_a), timeout=10).status_code == 200
        assert requests.get(f"{API}/projects/{p['id']}", headers=_h(token_a), timeout=10).status_code == 404


# ---------- Expected Outcomes ----------
class TestExpectedOutcomes:
    def test_create_valid(self, token_a):
        g = _mk_goal(token_a, "TEST_g_eo1")
        eo = _mk_eo(token_a, g["id"], "TEST_eo_1")
        assert eo["goal_id"] == g["id"]
        # via list
        lst = requests.get(f"{API}/goals/{g['id']}/expected-outcomes", headers=_h(token_a), timeout=10).json()
        assert any(x["id"] == eo["id"] for x in lst)

    def test_create_missing_goal_400(self, token_a):
        r = requests.post(f"{API}/expected-outcomes", headers=_h(token_a), json={"goal_id": "does-not-exist", "title": "x"}, timeout=10)
        assert r.status_code == 400

    def test_create_invalid_status_400(self, token_a):
        g = _mk_goal(token_a, "TEST_g_eo_stat")
        r = requests.post(f"{API}/expected-outcomes", headers=_h(token_a), json={"goal_id": g["id"], "title": "x", "status": "bogus"}, timeout=10)
        assert r.status_code == 400

    def test_list_scoped_to_owner(self, token_a, token_b):
        g = _mk_goal(token_a, "TEST_g_scoped")
        _mk_eo(token_a, g["id"], "eo1")
        # user_b cannot list this goal's EOs
        r = requests.get(f"{API}/goals/{g['id']}/expected-outcomes", headers=_h(token_b), timeout=10)
        assert r.status_code == 404

    def test_put_delete_and_invalid_status_400(self, token_a):
        g = _mk_goal(token_a, "TEST_g_put")
        eo = _mk_eo(token_a, g["id"], "eo_upd")
        r = requests.put(f"{API}/expected-outcomes/{eo['id']}", headers=_h(token_a), json={"title": "eo_upd2", "status": "completed"}, timeout=10)
        assert r.status_code == 200
        assert r.json()["title"] == "eo_upd2"
        assert r.json()["status"] == "completed"
        assert requests.put(f"{API}/expected-outcomes/{eo['id']}", headers=_h(token_a), json={"status": "bogus"}, timeout=10).status_code == 400
        assert requests.delete(f"{API}/expected-outcomes/{eo['id']}", headers=_h(token_a), timeout=10).status_code == 200
        assert requests.get(f"{API}/expected-outcomes/{eo['id']}", headers=_h(token_a), timeout=10).status_code == 404

    def test_max_7_per_goal(self, token_a):
        g = _mk_goal(token_a, "TEST_g_max")
        for i in range(7):
            _mk_eo(token_a, g["id"], f"eo_{i}")
        r = requests.post(f"{API}/expected-outcomes", headers=_h(token_a), json={"goal_id": g["id"], "title": "8th"}, timeout=10)
        assert r.status_code == 400
        assert "7" in r.json().get("detail", "")


# ---------- Goal stats & cascade delete ----------
class TestGoalStatsAndCascade:
    def test_stats_and_completion(self, token_a):
        g = _mk_goal(token_a, "TEST_g_stats")
        got0 = requests.get(f"{API}/goals/{g['id']}", headers=_h(token_a), timeout=10).json()
        assert got0["expected_outcomes_total"] == 0
        assert got0["expected_outcomes_completed"] == 0
        assert got0["completion_pct"] == 0.0
        eo1 = _mk_eo(token_a, g["id"], "eo_a")
        _mk_eo(token_a, g["id"], "eo_b")
        got1 = requests.get(f"{API}/goals/{g['id']}", headers=_h(token_a), timeout=10).json()
        assert got1["expected_outcomes_total"] == 2
        assert got1["expected_outcomes_completed"] == 0
        # mark one completed
        requests.put(f"{API}/expected-outcomes/{eo1['id']}", headers=_h(token_a), json={"status": "completed"}, timeout=10)
        got2 = requests.get(f"{API}/goals/{g['id']}", headers=_h(token_a), timeout=10).json()
        assert got2["expected_outcomes_completed"] == 1
        assert got2["completion_pct"] == 50.0

    def test_delete_goal_cascades_expected_outcomes(self, token_a):
        g = _mk_goal(token_a, "TEST_g_casc")
        eo = _mk_eo(token_a, g["id"], "eo_casc")
        assert requests.delete(f"{API}/goals/{g['id']}", headers=_h(token_a), timeout=10).status_code == 200
        # EO should be gone
        assert requests.get(f"{API}/expected-outcomes/{eo['id']}", headers=_h(token_a), timeout=10).status_code == 404


# ---------- Tasks ----------
class TestTasks:
    def test_standalone_create(self, token_a):
        r = requests.post(f"{API}/tasks", headers=_h(token_a), json={"title": "TEST_t_std", "origin": "standalone"}, timeout=10)
        assert r.status_code == 201
        assert r.json()["origin"] == "standalone"
        assert r.json()["expected_outcome_id"] is None
        assert r.json()["project_id"] is None

    def test_expected_outcome_task_requires_eo(self, token_a):
        r = requests.post(f"{API}/tasks", headers=_h(token_a), json={"title": "x", "origin": "expected_outcome"}, timeout=10)
        assert r.status_code == 400
        r = requests.post(f"{API}/tasks", headers=_h(token_a), json={"title": "x", "origin": "expected_outcome", "expected_outcome_id": "nope"}, timeout=10)
        assert r.status_code == 400

    def test_expected_outcome_task_valid(self, token_a):
        g = _mk_goal(token_a, "TEST_g_t_eo")
        eo = _mk_eo(token_a, g["id"], "eo_for_task")
        r = requests.post(f"{API}/tasks", headers=_h(token_a), json={"title": "TEST_t_eo", "origin": "expected_outcome", "expected_outcome_id": eo["id"]}, timeout=10)
        assert r.status_code == 201
        assert r.json()["expected_outcome_id"] == eo["id"]

    def test_project_task_requires_project(self, token_a):
        r = requests.post(f"{API}/tasks", headers=_h(token_a), json={"title": "x", "origin": "project"}, timeout=10)
        assert r.status_code == 400
        r = requests.post(f"{API}/tasks", headers=_h(token_a), json={"title": "x", "origin": "project", "project_id": "nope"}, timeout=10)
        assert r.status_code == 400

    def test_project_task_valid(self, token_a):
        p = _mk_project(token_a, "TEST_p_for_task")
        r = requests.post(f"{API}/tasks", headers=_h(token_a), json={"title": "TEST_t_p", "origin": "project", "project_id": p["id"]}, timeout=10)
        assert r.status_code == 201
        assert r.json()["project_id"] == p["id"]

    def test_invalid_status_priority_origin_400(self, token_a):
        assert requests.post(f"{API}/tasks", headers=_h(token_a), json={"title": "x", "origin": "standalone", "status": "bogus"}, timeout=10).status_code == 400
        assert requests.post(f"{API}/tasks", headers=_h(token_a), json={"title": "x", "origin": "standalone", "priority": "bogus"}, timeout=10).status_code == 400
        assert requests.post(f"{API}/tasks", headers=_h(token_a), json={"title": "x", "origin": "bogus"}, timeout=10).status_code == 400

    def test_status_transitions(self, token_a):
        r = requests.post(f"{API}/tasks", headers=_h(token_a), json={"title": "TEST_trans", "origin": "standalone"}, timeout=10)
        tid = r.json()["id"]
        r = requests.put(f"{API}/tasks/{tid}", headers=_h(token_a), json={"status": "done"}, timeout=10)
        assert r.status_code == 200 and r.json()["status"] == "done"
        r = requests.put(f"{API}/tasks/{tid}", headers=_h(token_a), json={"status": "deferred"}, timeout=10)
        assert r.status_code == 200 and r.json()["status"] == "deferred"

    def test_cross_user_isolation(self, token_a, token_b):
        r = requests.post(f"{API}/tasks", headers=_h(token_a), json={"title": "TEST_iso", "origin": "standalone"}, timeout=10)
        tid = r.json()["id"]
        assert requests.get(f"{API}/tasks/{tid}", headers=_h(token_b), timeout=10).status_code == 404
        assert requests.put(f"{API}/tasks/{tid}", headers=_h(token_b), json={"title": "hack"}, timeout=10).status_code == 404
        assert requests.delete(f"{API}/tasks/{tid}", headers=_h(token_b), timeout=10).status_code == 404


# ---------- Check-ins ----------
class TestCheckins:
    def test_life_checkin(self, token_a):
        r = requests.post(f"{API}/checkins", headers=_h(token_a), json={"type": "life", "title": "TEST_life", "date": "2026-01-01", "time": "09:00"}, timeout=10)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["type"] == "life"
        assert body["goal_id"] is None and body["project_id"] is None and body["expected_outcome_id"] is None

    def test_invalid_type_400(self, token_a):
        r = requests.post(f"{API}/checkins", headers=_h(token_a), json={"type": "bogus", "title": "x", "date": "2026-01-01", "time": "09:00"}, timeout=10)
        assert r.status_code == 400

    def test_goal_checkin_requires_eo(self, token_a):
        r = requests.post(f"{API}/checkins", headers=_h(token_a), json={"type": "goal", "title": "x", "date": "2026-01-01", "time": "09:00"}, timeout=10)
        assert r.status_code == 400
        r = requests.post(f"{API}/checkins", headers=_h(token_a), json={"type": "goal", "title": "x", "date": "2026-01-01", "time": "09:00", "expected_outcome_id": "nope"}, timeout=10)
        assert r.status_code == 400

    def test_goal_checkin_valid_returns_goal_id(self, token_a):
        g = _mk_goal(token_a, "TEST_g_chk")
        eo = _mk_eo(token_a, g["id"], "eo_chk")
        r = requests.post(f"{API}/checkins", headers=_h(token_a), json={"type": "goal", "title": "TEST_c_g", "date": "2026-01-01", "time": "09:00", "expected_outcome_id": eo["id"]}, timeout=10)
        assert r.status_code == 201
        body = r.json()
        assert body["expected_outcome_id"] == eo["id"]
        assert body["goal_id"] == g["id"]

    def test_project_checkin_requires_project(self, token_a):
        r = requests.post(f"{API}/checkins", headers=_h(token_a), json={"type": "project", "title": "x", "date": "2026-01-01", "time": "09:00"}, timeout=10)
        assert r.status_code == 400
        r = requests.post(f"{API}/checkins", headers=_h(token_a), json={"type": "project", "title": "x", "date": "2026-01-01", "time": "09:00", "project_id": "nope"}, timeout=10)
        assert r.status_code == 400

    def test_project_checkin_task_must_belong_to_project(self, token_a):
        p1 = _mk_project(token_a, "TEST_p1")
        p2 = _mk_project(token_a, "TEST_p2")
        # task under p2
        t = requests.post(f"{API}/tasks", headers=_h(token_a), json={"title": "TEST_t_wrong", "origin": "project", "project_id": p2["id"]}, timeout=10).json()
        # checkin under p1 referencing task from p2 should fail
        r = requests.post(f"{API}/checkins", headers=_h(token_a), json={"type": "project", "title": "x", "date": "2026-01-01", "time": "09:00", "project_id": p1["id"], "task_id": t["id"]}, timeout=10)
        assert r.status_code == 400

    def test_list_get_put_delete_isolation(self, token_a, token_b):
        r = requests.post(f"{API}/checkins", headers=_h(token_a), json={"type": "life", "title": "TEST_iso_c", "date": "2026-01-01", "time": "09:00"}, timeout=10)
        cid = r.json()["id"]
        # list by A includes
        lst = requests.get(f"{API}/checkins", headers=_h(token_a), timeout=10).json()
        assert any(x["id"] == cid for x in lst)
        # list by B excludes
        lst_b = requests.get(f"{API}/checkins", headers=_h(token_b), timeout=10).json()
        assert not any(x["id"] == cid for x in lst_b)
        # cross-user 404
        assert requests.get(f"{API}/checkins/{cid}", headers=_h(token_b), timeout=10).status_code == 404
        assert requests.put(f"{API}/checkins/{cid}", headers=_h(token_b), json={"title": "hack"}, timeout=10).status_code == 404
        assert requests.delete(f"{API}/checkins/{cid}", headers=_h(token_b), timeout=10).status_code == 404
        # update by A
        r = requests.put(f"{API}/checkins/{cid}", headers=_h(token_a), json={"title": "TEST_iso_c2"}, timeout=10)
        assert r.status_code == 200 and r.json()["title"] == "TEST_iso_c2"
        assert requests.delete(f"{API}/checkins/{cid}", headers=_h(token_a), timeout=10).status_code == 200


# ---------- Follow-up tasks ----------
class TestFollowUpTasks:
    def test_life_followup_standalone(self, token_a):
        r = requests.post(f"{API}/checkins", headers=_h(token_a), json={
            "type": "life", "title": "TEST_life_ft", "date": "2026-01-01", "time": "09:00",
            "follow_up_task": {"title": "TEST_ft_life"},
        }, timeout=10)
        assert r.status_code == 201
        ftid = r.json()["follow_up_task_id"]
        assert ftid
        t = requests.get(f"{API}/tasks/{ftid}", headers=_h(token_a), timeout=10).json()
        assert t["origin"] == "standalone"
        assert t["expected_outcome_id"] is None and t["project_id"] is None

    def test_project_followup(self, token_a):
        p = _mk_project(token_a, "TEST_p_ft")
        r = requests.post(f"{API}/checkins", headers=_h(token_a), json={
            "type": "project", "title": "TEST_p_ft_c", "date": "2026-01-01", "time": "09:00",
            "project_id": p["id"],
            "follow_up_task": {"title": "TEST_ft_p"},
        }, timeout=10)
        assert r.status_code == 201
        ftid = r.json()["follow_up_task_id"]
        t = requests.get(f"{API}/tasks/{ftid}", headers=_h(token_a), timeout=10).json()
        assert t["origin"] == "project"
        assert t["project_id"] == p["id"]

    def test_goal_followup(self, token_a):
        g = _mk_goal(token_a, "TEST_g_ft")
        eo = _mk_eo(token_a, g["id"], "eo_ft")
        r = requests.post(f"{API}/checkins", headers=_h(token_a), json={
            "type": "goal", "title": "TEST_g_ft_c", "date": "2026-01-01", "time": "09:00",
            "expected_outcome_id": eo["id"],
            "follow_up_task": {"title": "TEST_ft_g"},
        }, timeout=10)
        assert r.status_code == 201
        ftid = r.json()["follow_up_task_id"]
        t = requests.get(f"{API}/tasks/{ftid}", headers=_h(token_a), timeout=10).json()
        assert t["origin"] == "expected_outcome"
        assert t["expected_outcome_id"] == eo["id"]


# ---------- Persistence via list endpoints ----------
class TestPersistence:
    def test_records_persist_via_list(self, token_a):
        # Create one of each and re-list
        g = _mk_goal(token_a, f"TEST_persist_g_{uuid.uuid4().hex[:6]}")
        eo = _mk_eo(token_a, g["id"], "eo_persist")
        p = _mk_project(token_a, f"TEST_persist_p_{uuid.uuid4().hex[:6]}")
        t = requests.post(f"{API}/tasks", headers=_h(token_a), json={"title": "TEST_persist_t", "origin": "standalone"}, timeout=10).json()
        c = requests.post(f"{API}/checkins", headers=_h(token_a), json={"type": "life", "title": "TEST_persist_c", "date": "2026-01-02", "time": "10:00"}, timeout=10).json()
        assert any(x["id"] == g["id"] for x in requests.get(f"{API}/goals", headers=_h(token_a), timeout=10).json())
        assert any(x["id"] == eo["id"] for x in requests.get(f"{API}/goals/{g['id']}/expected-outcomes", headers=_h(token_a), timeout=10).json())
        assert any(x["id"] == p["id"] for x in requests.get(f"{API}/projects", headers=_h(token_a), timeout=10).json())
        assert any(x["id"] == t["id"] for x in requests.get(f"{API}/tasks", headers=_h(token_a), timeout=10).json())
        assert any(x["id"] == c["id"] for x in requests.get(f"{API}/checkins", headers=_h(token_a), timeout=10).json())
