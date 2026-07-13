"""Tests for the Learn -> Knowledge architectural refactor (iteration 8).

Covers:
- /api/learning-journeys/* fully removed (404).
- POST /api/knowledge/journeys atomic wizard.
- GET /api/knowledge/journeys scoping.
- checkin_cadence on Goal create/update.
- Idempotent Knowledge domain seeding for existing users.
- goal_id filter on /api/tasks and /api/checkins.
- User isolation on knowledge journeys.
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://personal-os-app-8.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


def _unique_email() -> str:
    return f"TEST_kn_{uuid.uuid4().hex[:10]}@hymn.app"


@pytest.fixture(scope="module")
def fresh_user():
    email = _unique_email()
    r = requests.post(f"{API}/auth/signup", json={
        "email": email,
        "password": "TestPass123!",
        "security_question": "color?",
        "security_answer": "blue",
    })
    assert r.status_code == 201, r.text
    tok = r.json()["access_token"]
    return {"email": email, "token": tok, "headers": {"Authorization": f"Bearer {tok}"}}


@pytest.fixture(scope="module")
def existing_user():
    r = requests.post(f"{API}/auth/login", json={
        "email": "test@hymn.app", "password": "TestPass123!",
    })
    assert r.status_code == 200, r.text
    tok = r.json()["access_token"]
    return {"token": tok, "headers": {"Authorization": f"Bearer {tok}"}}


# ---------- 1. Old /api/learning-journeys removed ----------
class TestLearningJourneysRemoved:
    def test_collection_verbs_are_gone(self, fresh_user):
        h = fresh_user["headers"]
        for verb in ("get", "post", "put", "delete"):
            fn = getattr(requests, verb)
            kwargs = {"headers": h}
            if verb in ("post", "put"):
                kwargs["json"] = {"title": "x"}
            r = fn(f"{API}/learning-journeys", **kwargs)
            assert r.status_code in (404, 405), f"{verb} /learning-journeys -> {r.status_code}"

    def test_item_verbs_are_gone(self, fresh_user):
        h = fresh_user["headers"]
        fake_id = str(uuid.uuid4())
        for verb in ("get", "put", "delete"):
            fn = getattr(requests, verb)
            kwargs = {"headers": h}
            if verb == "put":
                kwargs["json"] = {"title": "x"}
            r = fn(f"{API}/learning-journeys/{fake_id}", **kwargs)
            assert r.status_code in (404, 405), f"{verb} /learning-journeys/id -> {r.status_code}"


# ---------- 2. Wizard happy path ----------
class TestKnowledgeWizardHappyPath:
    def test_knowledge_domain_present(self, fresh_user):
        r = requests.get(f"{API}/domains", headers=fresh_user["headers"])
        assert r.status_code == 200
        names = [d["name"] for d in r.json()]
        assert "Knowledge" in names

    def test_create_journey_full_body(self, fresh_user):
        payload = {
            "journey_type": "skill",
            "title": "TEST_Learn Spanish",
            "why": "To speak with abuela",
            "target_completion_date": "2026-12-31",
            "first_outcome": {"title": "Complete A1", "target_value": "100", "unit": "lessons", "outcome_type": "study"},
            "first_task": {"title": "Install Duolingo", "due_date": "2026-02-01", "priority": "high"},
            "checkin_cadence": "weekly",
        }
        r = requests.post(f"{API}/knowledge/journeys", json=payload, headers=fresh_user["headers"])
        assert r.status_code == 201, r.text
        g = r.json()
        assert g["domain_name"] == "Knowledge"
        assert g["checkin_cadence"] == "weekly"
        assert g["expected_outcomes_total"] == 1
        assert g["expected_outcomes_completed"] == 0
        assert g["notes"] == "To speak with abuela"
        assert g["deadline"] == "2026-12-31"
        fresh_user["journey_id"] = g["id"]
        fresh_user["goal_id"] = g["goal_id"]

    def test_list_returns_new_journey(self, fresh_user):
        r = requests.get(f"{API}/knowledge/journeys", headers=fresh_user["headers"])
        assert r.status_code == 200
        items = r.json()
        assert len(items) == 1
        assert items[0]["id"] == fresh_user["journey_id"]

    def test_get_goal_returns_same(self, fresh_user):
        r = requests.get(f"{API}/goals/{fresh_user['goal_id']}", headers=fresh_user["headers"])
        assert r.status_code == 200
        g = r.json()
        assert "abuela" in g["notes"]

    def test_expected_outcome_created(self, fresh_user):
        r = requests.get(f"{API}/goals/{fresh_user['goal_id']}/expected-outcomes", headers=fresh_user["headers"])
        assert r.status_code == 200
        eos = r.json()
        assert len(eos) == 1
        assert eos[0]["title"] == "Complete A1"
        fresh_user["eo_id"] = eos[0]["id"]

    def test_task_with_goal_filter(self, fresh_user):
        r = requests.get(f"{API}/tasks", params={"goal_id": fresh_user["goal_id"]}, headers=fresh_user["headers"])
        assert r.status_code == 200
        tasks = r.json()
        assert len(tasks) == 1
        assert tasks[0]["expected_outcome_id"] == fresh_user["eo_id"]
        assert tasks[0]["title"] == "Install Duolingo"

    def test_task_without_filter_contains_task(self, fresh_user):
        r = requests.get(f"{API}/tasks", headers=fresh_user["headers"])
        assert r.status_code == 200
        titles = [t["title"] for t in r.json()]
        assert "Install Duolingo" in titles

    def test_checkins_with_goal_filter_empty(self, fresh_user):
        r = requests.get(f"{API}/checkins", params={"goal_id": fresh_user["goal_id"]}, headers=fresh_user["headers"])
        assert r.status_code == 200
        assert r.json() == []


# ---------- 3. Rejection cases ----------
def _count_journeys(headers) -> int:
    r = requests.get(f"{API}/knowledge/journeys", headers=headers)
    assert r.status_code == 200
    return len(r.json())


class TestKnowledgeWizardRejections:
    def _base(self):
        return {
            "journey_type": "skill",
            "title": "TEST_reject",
            "why": "reason",
            "target_completion_date": "",
            "first_outcome": {"title": "x", "outcome_type": "generic"},
            "first_task": {"title": "t", "priority": "medium"},
            "checkin_cadence": "weekly",
        }

    @pytest.mark.parametrize("mutation,expected_codes", [
        ("missing_why", (400, 422)),
        ("missing_title", (400, 422)),
        ("missing_outcome_title", (400, 422)),
        ("missing_task_title", (400, 422)),
        ("missing_cadence", (400, 422)),
        ("bad_cadence", (400,)),
        ("bad_outcome_type", (400,)),
        ("bad_priority", (400,)),
    ])
    def test_reject(self, fresh_user, mutation, expected_codes):
        before = _count_journeys(fresh_user["headers"])
        body = self._base()
        if mutation == "missing_why":
            body.pop("why")
        elif mutation == "missing_title":
            body.pop("title")
        elif mutation == "missing_outcome_title":
            body["first_outcome"] = {"outcome_type": "generic"}
        elif mutation == "missing_task_title":
            body["first_task"] = {"priority": "medium"}
        elif mutation == "missing_cadence":
            body.pop("checkin_cadence")
        elif mutation == "bad_cadence":
            body["checkin_cadence"] = "yearly"
        elif mutation == "bad_outcome_type":
            body["first_outcome"]["outcome_type"] = "nope"
        elif mutation == "bad_priority":
            body["first_task"]["priority"] = "urgent"
        r = requests.post(f"{API}/knowledge/journeys", json=body, headers=fresh_user["headers"])
        assert r.status_code in expected_codes, f"{mutation}: {r.status_code} {r.text}"
        after = _count_journeys(fresh_user["headers"])
        assert after == before, f"{mutation} leaked a goal ({before} -> {after})"


# ---------- 4. Goal cadence on regular POST/PUT ----------
class TestGoalCadence:
    def test_create_and_update(self, fresh_user):
        h = fresh_user["headers"]
        d = requests.get(f"{API}/domains", headers=h).json()
        health = next(x for x in d if x["name"] == "Health")
        r = requests.post(f"{API}/goals", json={
            "title": "TEST_cad", "domain_id": health["id"], "checkin_cadence": "weekly",
        }, headers=h)
        assert r.status_code == 201, r.text
        assert r.json()["checkin_cadence"] == "weekly"
        gid = r.json()["id"]

        r2 = requests.put(f"{API}/goals/{gid}", json={"checkin_cadence": "daily"}, headers=h)
        assert r2.status_code == 200
        assert r2.json()["checkin_cadence"] == "daily"

        r3 = requests.put(f"{API}/goals/{gid}", json={"checkin_cadence": "yearly"}, headers=h)
        assert r3.status_code == 400

        # Existing goal without cadence still works
        r4 = requests.post(f"{API}/goals", json={
            "title": "TEST_no_cad", "domain_id": health["id"],
        }, headers=h)
        assert r4.status_code == 201
        assert r4.json()["checkin_cadence"] == ""

        # Cleanup
        requests.delete(f"{API}/goals/{gid}", headers=h)
        requests.delete(f"{API}/goals/{r4.json()['id']}", headers=h)


# ---------- 5. Idempotent seeding for existing user ----------
class TestIdempotentSeeding:
    def test_existing_user_has_knowledge(self, existing_user):
        r = requests.get(f"{API}/domains", headers=existing_user["headers"])
        assert r.status_code == 200
        names = [d["name"] for d in r.json()]
        assert "Knowledge" in names


# ---------- 6. Regression on classic CRUD ----------
class TestRegression:
    def test_auth_me(self, fresh_user):
        r = requests.get(f"{API}/auth/me", headers=fresh_user["headers"])
        assert r.status_code == 200

    def test_outcome_types(self, fresh_user):
        r = requests.get(f"{API}/outcome-types", headers=fresh_user["headers"])
        assert r.status_code == 200
        assert "types" in r.json()

    def test_project_full_crud(self, fresh_user):
        h = fresh_user["headers"]
        r = requests.post(f"{API}/projects", json={"title": "TEST_proj"}, headers=h)
        assert r.status_code == 201
        pid = r.json()["id"]
        assert requests.get(f"{API}/projects/{pid}", headers=h).status_code == 200
        r2 = requests.put(f"{API}/projects/{pid}", json={"title": "TEST_proj2"}, headers=h)
        assert r2.status_code == 200 and r2.json()["title"] == "TEST_proj2"
        assert requests.delete(f"{API}/projects/{pid}", headers=h).status_code == 200

    def test_domain_and_goal_and_eo_and_task_and_checkin_flow(self, fresh_user):
        h = fresh_user["headers"]
        # domain
        dr = requests.post(f"{API}/domains", json={"name": f"TEST_D_{uuid.uuid4().hex[:6]}"}, headers=h)
        assert dr.status_code == 201
        did = dr.json()["id"]
        # goal
        gr = requests.post(f"{API}/goals", json={"title": "TEST_g", "domain_id": did}, headers=h)
        assert gr.status_code == 201
        gid = gr.json()["id"]
        # eo
        er = requests.post(f"{API}/expected-outcomes", json={"goal_id": gid, "title": "TEST_eo"}, headers=h)
        assert er.status_code == 201
        eoid = er.json()["id"]
        # task
        tr = requests.post(f"{API}/tasks", json={
            "title": "TEST_t", "origin": "expected_outcome", "expected_outcome_id": eoid,
        }, headers=h)
        assert tr.status_code == 201
        tid = tr.json()["id"]
        # checkin
        cr = requests.post(f"{API}/checkins", json={
            "type": "goal", "title": "TEST_c", "date": "2026-01-15", "time": "10:00",
            "expected_outcome_id": eoid, "data": {"note": "ok"},
        }, headers=h)
        assert cr.status_code == 201, cr.text
        cid = cr.json()["id"]
        # goal_id filter for checkins
        f = requests.get(f"{API}/checkins", params={"goal_id": gid}, headers=h)
        assert f.status_code == 200
        assert any(c["id"] == cid for c in f.json())
        # cleanup
        requests.delete(f"{API}/checkins/{cid}", headers=h)
        requests.delete(f"{API}/tasks/{tid}", headers=h)
        requests.delete(f"{API}/expected-outcomes/{eoid}", headers=h)
        requests.delete(f"{API}/goals/{gid}", headers=h)
        requests.delete(f"{API}/domains/{did}", headers=h)


# ---------- 7. User isolation ----------
class TestIsolation:
    def test_other_users_journeys_not_leaked(self, fresh_user):
        other_email = _unique_email()
        r = requests.post(f"{API}/auth/signup", json={
            "email": other_email, "password": "TestPass123!",
            "security_question": "?", "security_answer": "a",
        })
        assert r.status_code == 201
        other_h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        # Other user creates a journey
        rj = requests.post(f"{API}/knowledge/journeys", json={
            "journey_type": "skill",
            "title": "TEST_other_journey", "why": "reason",
            "first_outcome": {"title": "eo"}, "first_task": {"title": "t"},
            "checkin_cadence": "manual",
        }, headers=other_h)
        assert rj.status_code == 201
        other_id = rj.json()["id"]

        # fresh_user should not see it
        mine = requests.get(f"{API}/knowledge/journeys", headers=fresh_user["headers"]).json()
        assert all(j["id"] != other_id for j in mine)
        assert all(j["title"] != "TEST_other_journey" for j in mine)
