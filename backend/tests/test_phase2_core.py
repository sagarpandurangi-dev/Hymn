"""Phase 2 core-model tests: outcome_type registry, contextual check-in validation,
check-in source, task assignment (self/external), follow-up assignment,
and backward-compat (missing fields fall back to defaults)."""
import os
import uuid
import requests
import pytest

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://personal-os-app-8.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


def _signup_user():
    email = f"TEST_p2_{uuid.uuid4().hex[:10]}@hymn.app"
    r = requests.post(f"{API}/auth/signup", json={
        "email": email, "password": "TestPass123!",
        "security_question": "q?", "security_answer": "a",
    }, timeout=30)
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def auth():
    tok = _signup_user()
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def goal_id(auth):
    dr = requests.get(f"{API}/domains", headers=auth, timeout=30)
    assert dr.status_code == 200
    domain = dr.json()[0]
    gr = requests.post(f"{API}/goals", headers=auth, json={
        "title": "TEST_p2_goal", "domain_id": domain["id"],
    }, timeout=30)
    assert gr.status_code == 201, gr.text
    return gr.json()["id"]


# ---------- outcome-type registry ----------
class TestOutcomeTypeRegistry:
    def test_registry_shape(self, auth):
        r = requests.get(f"{API}/outcome-types", headers=auth, timeout=30)
        assert r.status_code == 200
        body = r.json()
        assert "types" in body
        types = body["types"]
        for key in ["generic", "weight", "study", "revenue", "project_milestone", "count"]:
            assert key in types, f"missing type {key}"
            t = types[key]
            assert "label" in t and "description" in t
            assert "checkin_fields" in t and isinstance(t["checkin_fields"], list)
            assert "units" in t
            assert "progress" in t

    def test_weight_fields(self, auth):
        r = requests.get(f"{API}/outcome-types", headers=auth, timeout=30)
        weight = r.json()["types"]["weight"]
        keys = {f["key"] for f in weight["checkin_fields"]}
        assert {"value", "unit"} <= keys
        assert "kg" in weight["units"] and "lb" in weight["units"]


# ---------- EO outcome_type ----------
class TestEOOutcomeType:
    def test_create_weight_eo(self, auth, goal_id):
        r = requests.post(f"{API}/expected-outcomes", headers=auth, json={
            "goal_id": goal_id, "title": "TEST_p2_weight_eo", "outcome_type": "weight",
        }, timeout=30)
        assert r.status_code == 201, r.text
        eo = r.json()
        assert eo["outcome_type"] == "weight"
        # verify persistence via GET
        gr = requests.get(f"{API}/expected-outcomes/{eo['id']}", headers=auth, timeout=30)
        assert gr.status_code == 200
        assert gr.json()["outcome_type"] == "weight"

    def test_invalid_outcome_type_rejected(self, auth, goal_id):
        r = requests.post(f"{API}/expected-outcomes", headers=auth, json={
            "goal_id": goal_id, "title": "TEST_p2_bad", "outcome_type": "invalid_type",
        }, timeout=30)
        assert r.status_code == 400
        assert "outcome" in r.text.lower() or "type" in r.text.lower()

    def test_put_updates_outcome_type(self, auth, goal_id):
        r = requests.post(f"{API}/expected-outcomes", headers=auth, json={
            "goal_id": goal_id, "title": "TEST_p2_switch",
        }, timeout=30)
        eo = r.json()
        assert eo["outcome_type"] == "generic"
        pr = requests.put(f"{API}/expected-outcomes/{eo['id']}", headers=auth,
                          json={"outcome_type": "study"}, timeout=30)
        assert pr.status_code == 200
        assert pr.json()["outcome_type"] == "study"


# ---------- Contextual check-in validation ----------
class TestContextualCheckin:
    @pytest.fixture(scope="class")
    def weight_eo(self, auth, goal_id):
        r = requests.post(f"{API}/expected-outcomes", headers=auth, json={
            "goal_id": goal_id, "title": "TEST_p2_weight_ctx", "outcome_type": "weight",
        }, timeout=30)
        return r.json()["id"]

    @pytest.fixture(scope="class")
    def study_eo(self, auth, goal_id):
        r = requests.post(f"{API}/expected-outcomes", headers=auth, json={
            "goal_id": goal_id, "title": "TEST_p2_study_ctx", "outcome_type": "study",
        }, timeout=30)
        return r.json()["id"]

    @pytest.fixture(scope="class")
    def generic_eo(self, auth, goal_id):
        r = requests.post(f"{API}/expected-outcomes", headers=auth, json={
            "goal_id": goal_id, "title": "TEST_p2_generic_ctx",
        }, timeout=30)
        return r.json()["id"]

    def test_weight_checkin_success(self, auth, weight_eo):
        r = requests.post(f"{API}/checkins", headers=auth, json={
            "type": "goal", "title": "TEST_p2_wci", "date": "2026-01-15", "time": "10:00",
            "expected_outcome_id": weight_eo,
            "data": {"value": 78, "unit": "kg"},
        }, timeout=30)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["outcome_type"] == "weight"
        assert body["data"]["value"] == 78
        assert body["data"]["unit"] == "kg"

    def test_weight_missing_value_fails(self, auth, weight_eo):
        r = requests.post(f"{API}/checkins", headers=auth, json={
            "type": "goal", "title": "TEST_p2_wci_bad", "date": "2026-01-15", "time": "10:00",
            "expected_outcome_id": weight_eo, "data": {"unit": "kg"},
        }, timeout=30)
        assert r.status_code == 400, r.text
        assert "value" in r.text.lower()

    def test_study_requires_duration(self, auth, study_eo):
        r = requests.post(f"{API}/checkins", headers=auth, json={
            "type": "goal", "title": "TEST_p2_sci_bad", "date": "2026-01-15", "time": "10:00",
            "expected_outcome_id": study_eo, "data": {"topic": "x"},
        }, timeout=30)
        assert r.status_code == 400
        assert "duration_minutes" in r.text.lower() or "duration" in r.text.lower()

    def test_study_success(self, auth, study_eo):
        r = requests.post(f"{API}/checkins", headers=auth, json={
            "type": "goal", "title": "TEST_p2_sci", "date": "2026-01-15", "time": "10:00",
            "expected_outcome_id": study_eo,
            "data": {"duration_minutes": 30, "topic": "fastapi"},
        }, timeout=30)
        assert r.status_code == 201
        assert r.json()["outcome_type"] == "study"

    def test_generic_eo_empty_data_ok(self, auth, generic_eo):
        r = requests.post(f"{API}/checkins", headers=auth, json={
            "type": "goal", "title": "TEST_p2_gen", "date": "2026-01-15", "time": "10:00",
            "expected_outcome_id": generic_eo, "data": {},
        }, timeout=30)
        assert r.status_code == 201, r.text
        assert r.json()["outcome_type"] == "generic"


# ---------- source field ----------
class TestCheckinSource:
    def test_default_source_is_manual(self, auth):
        r = requests.post(f"{API}/checkins", headers=auth, json={
            "type": "life", "title": "TEST_p2_src_def", "date": "2026-01-15", "time": "10:00",
        }, timeout=30)
        assert r.status_code == 201, r.text
        assert r.json()["source"] == "manual"

    def test_explicit_source_whatsapp(self, auth):
        r = requests.post(f"{API}/checkins", headers=auth, json={
            "type": "life", "title": "TEST_p2_src_wa", "date": "2026-01-15", "time": "10:00",
            "source": "whatsapp",
        }, timeout=30)
        assert r.status_code == 201
        cid = r.json()["id"]
        gr = requests.get(f"{API}/checkins/{cid}", headers=auth, timeout=30)
        assert gr.json()["source"] == "whatsapp"

    def test_invalid_source_rejected(self, auth):
        r = requests.post(f"{API}/checkins", headers=auth, json={
            "type": "life", "title": "TEST_p2_src_bad", "date": "2026-01-15", "time": "10:00",
            "source": "foo",
        }, timeout=30)
        assert r.status_code == 400
        assert "source" in r.text.lower()

    def test_life_checkin_outcome_type_is_null(self, auth):
        r = requests.post(f"{API}/checkins", headers=auth, json={
            "type": "life", "title": "TEST_p2_life_ot", "date": "2026-01-15", "time": "10:00",
        }, timeout=30)
        assert r.status_code == 201
        assert r.json()["outcome_type"] is None


# ---------- Task assignment ----------
class TestTaskAssignment:
    def test_default_self(self, auth):
        r = requests.post(f"{API}/tasks", headers=auth, json={"title": "TEST_p2_task_self"}, timeout=30)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["assigned_to_type"] == "self"
        assert body["assigned_to_name"] == ""
        assert body["assigned_to_phone"] == ""

    def test_external_with_name(self, auth):
        r = requests.post(f"{API}/tasks", headers=auth, json={
            "title": "TEST_p2_task_ext",
            "assigned_to_type": "external",
            "assigned_to_name": "Alex",
        }, timeout=30)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["assigned_to_type"] == "external"
        assert body["assigned_to_name"] == "Alex"

    def test_external_missing_contact(self, auth):
        r = requests.post(f"{API}/tasks", headers=auth, json={
            "title": "TEST_p2_task_ext_bad",
            "assigned_to_type": "external",
        }, timeout=30)
        assert r.status_code == 400

    def test_invalid_type(self, auth):
        r = requests.post(f"{API}/tasks", headers=auth, json={
            "title": "TEST_p2_task_bad", "assigned_to_type": "foo",
        }, timeout=30)
        assert r.status_code == 400

    def test_switch_back_to_self_clears_fields(self, auth):
        r = requests.post(f"{API}/tasks", headers=auth, json={
            "title": "TEST_p2_task_switch",
            "assigned_to_type": "external",
            "assigned_to_name": "Alex", "assigned_to_phone": "555-1234",
        }, timeout=30)
        tid = r.json()["id"]
        pr = requests.put(f"{API}/tasks/{tid}", headers=auth,
                          json={"assigned_to_type": "self"}, timeout=30)
        assert pr.status_code == 200
        body = pr.json()
        assert body["assigned_to_type"] == "self"
        assert body["assigned_to_name"] == ""
        assert body["assigned_to_phone"] == ""


# ---------- Follow-up task assignment ----------
class TestFollowUpAssignment:
    def test_followup_external(self, auth):
        r = requests.post(f"{API}/checkins", headers=auth, json={
            "type": "life", "title": "TEST_p2_ci_ft", "date": "2026-01-15", "time": "10:00",
            "follow_up_task": {
                "title": "TEST_p2_ft", "assigned_to_type": "external", "assigned_to_name": "Bob",
            },
        }, timeout=30)
        assert r.status_code == 201, r.text
        ft_id = r.json()["follow_up_task_id"]
        assert ft_id
        tr = requests.get(f"{API}/tasks/{ft_id}", headers=auth, timeout=30)
        assert tr.status_code == 200
        task = tr.json()
        assert task["assigned_to_type"] == "external"
        assert task["assigned_to_name"] == "Bob"


# ---------- Backward compatibility ----------
class TestBackwardCompat:
    """Legacy docs missing new fields should still deserialize via defaults."""

    def test_legacy_task_defaults(self, auth):
        # Directly poke a legacy-shaped task doc via API is not possible; instead ensure
        # POST without any assignment fields still returns assigned_to_type='self'.
        r = requests.post(f"{API}/tasks", headers=auth, json={"title": "TEST_p2_legacy_task"}, timeout=30)
        assert r.status_code == 201
        assert r.json()["assigned_to_type"] == "self"

    def test_legacy_checkin_defaults(self, auth):
        r = requests.post(f"{API}/checkins", headers=auth, json={
            "type": "life", "title": "TEST_p2_legacy_ci", "date": "2026-01-15", "time": "10:00",
        }, timeout=30)
        assert r.status_code == 201
        body = r.json()
        assert body["source"] == "manual"
        assert body["data"] == {}
        assert body["outcome_type"] is None

    def test_legacy_eo_defaults(self, auth, goal_id):
        r = requests.post(f"{API}/expected-outcomes", headers=auth, json={
            "goal_id": goal_id, "title": "TEST_p2_legacy_eo",
        }, timeout=30)
        assert r.status_code == 201
        assert r.json()["outcome_type"] == "generic"
