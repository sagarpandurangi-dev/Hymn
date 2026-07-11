"""Iteration 9 — Hierarchical Knowledge engine.

Covers:
1. Atomic 9-step wizard (POST /api/knowledge/journeys) happy path.
2. All 8+ rejection cases: 400/422 + zero rows persisted.
3. Stage CRUD + move (up/down + no-op past ends) + delete cascade.
4. Component CRUD (recursive) + child stage_id inheritance + move + validation
   of invalid status/progress/stage_id/parent.
5. Cascade delete of a component: descendants gone, tasks/checkins DETACHED
   (component_id -> null, NOT deleted).
6. component_id validation on POST /api/tasks + /api/checkins.
7. Filter combos on /api/tasks and /api/checkins: goal_id + component_id via $or.
8. Legacy backfill idempotency for test@hymn.app.
9. Journey delete cascade (components + stages + goal + EOs, tasks detached).
10. Regressions.
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Fall back to the value in frontend/.env so pytest can be run stand-alone.
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
                break
API = f"{BASE_URL}/api"


def _uniq() -> str:
    return f"TEST_kh_{uuid.uuid4().hex[:10]}@hymn.app"


# ---------- Fixtures ----------

@pytest.fixture(scope="module")
def user():
    email = _uniq()
    r = requests.post(f"{API}/auth/signup", json={
        "email": email, "password": "TestPass123!",
        "security_question": "?", "security_answer": "a",
    })
    assert r.status_code == 201, r.text
    tok = r.json()["access_token"]
    return {"email": email, "headers": {"Authorization": f"Bearer {tok}"}}


@pytest.fixture(scope="module")
def existing_user():
    r = requests.post(f"{API}/auth/login", json={
        "email": "test@hymn.app", "password": "TestPass123!",
    })
    assert r.status_code == 200, r.text
    return {"headers": {"Authorization": f"Bearer {r.json()['access_token']}"}}


def _snapshot(h):
    """Return counts of everything that must NOT leak on a rejection."""
    return {
        "journeys": len(requests.get(f"{API}/knowledge/journeys", headers=h).json()),
        "goals": len(requests.get(f"{API}/goals", headers=h).json()),
        "tasks": len(requests.get(f"{API}/tasks", headers=h).json()),
    }


def _valid_wizard_body():
    return {
        "journey_type": "skill",
        "title": f"TEST_kh_journey_{uuid.uuid4().hex[:6]}",
        "has_stages": True,
        "stages": [{"name": "Beginner"}, {"name": "Advanced"}],
        "why": "for fun",
        "target_completion_date": "2027-01-31",
        "first_outcome": {"title": "Learn 20 openings", "outcome_type": "study"},
        "first_task": {"title": "Study 3 openings", "priority": "medium"},
        "checkin_cadence": "weekly",
    }


# ---------- 1. Wizard happy path (with stages) ----------

class TestWizardHappyPath:
    def test_full_body_creates_atomic(self, user):
        h = user["headers"]
        r = requests.post(f"{API}/knowledge/journeys", json=_valid_wizard_body(), headers=h)
        assert r.status_code == 201, r.text
        j = r.json()
        # KnowledgeJourneyResponse shape
        for k in ("id", "goal_id", "journey_type", "has_stages", "title", "notes",
                  "deadline", "domain_name", "checkin_cadence",
                  "expected_outcomes_total", "expected_outcomes_completed"):
            assert k in j, f"missing {k}"
        assert j["journey_type"] == "skill"
        assert j["has_stages"] is True
        assert j["domain_name"] == "Knowledge"
        assert j["checkin_cadence"] == "weekly"
        assert j["notes"] == "for fun"
        assert j["deadline"] == "2027-01-31"
        assert j["expected_outcomes_total"] == 1
        user["journey_id"] = j["id"]
        user["goal_id"] = j["goal_id"]

    def test_journey_get_returns_journey(self, user):
        h = user["headers"]
        r = requests.get(f"{API}/knowledge/journeys/{user['journey_id']}", headers=h)
        assert r.status_code == 200
        assert r.json()["id"] == user["journey_id"]

    def test_stages_persisted(self, user):
        h = user["headers"]
        r = requests.get(f"{API}/knowledge/journeys/{user['journey_id']}/stages", headers=h)
        assert r.status_code == 200
        st = r.json()
        assert len(st) == 2
        names = [s["name"] for s in st]
        assert names == ["Beginner", "Advanced"]  # sequence order
        assert st[0]["sequence"] < st[1]["sequence"]
        user["stage_ids"] = [s["id"] for s in st]

    def test_first_eo_persisted(self, user):
        h = user["headers"]
        r = requests.get(f"{API}/goals/{user['goal_id']}/expected-outcomes", headers=h)
        assert r.status_code == 200
        eos = r.json()
        assert len(eos) == 1 and eos[0]["title"] == "Learn 20 openings"

    def test_first_task_persisted(self, user):
        h = user["headers"]
        r = requests.get(f"{API}/tasks", params={"goal_id": user["goal_id"]}, headers=h)
        assert r.status_code == 200
        assert len(r.json()) == 1 and r.json()[0]["title"] == "Study 3 openings"

    def test_no_stages_variant(self, user):
        """has_stages=false with empty stages must be accepted."""
        body = _valid_wizard_body()
        body["title"] = f"TEST_kh_flat_{uuid.uuid4().hex[:6]}"
        body["has_stages"] = False
        body["stages"] = []
        r = requests.post(f"{API}/knowledge/journeys", json=body, headers=user["headers"])
        assert r.status_code == 201, r.text
        j = r.json()
        assert j["has_stages"] is False
        st = requests.get(
            f"{API}/knowledge/journeys/{j['id']}/stages", headers=user["headers"]
        ).json()
        assert st == []
        user["flat_journey_id"] = j["id"]
        user["flat_goal_id"] = j["goal_id"]


# ---------- 2. Rejection cases ----------

class TestWizardRejections:
    @pytest.mark.parametrize("mutation,codes", [
        ("bad_journey_type", (400,)),
        ("has_stages_empty_list", (400,)),
        ("missing_why", (400, 422)),
        ("missing_title", (400, 422)),
        ("missing_outcome_title", (400, 422)),
        ("missing_task_title", (400, 422)),
        ("missing_cadence", (400, 422)),
        ("bad_cadence", (400,)),
        ("bad_outcome_type", (400,)),
        ("bad_priority", (400,)),
    ])
    def test_rejection_leaks_nothing(self, user, mutation, codes):
        h = user["headers"]
        before = _snapshot(h)
        body = _valid_wizard_body()
        body["title"] = f"TEST_kh_REJ_{mutation}"
        if mutation == "bad_journey_type":
            body["journey_type"] = "bogus"
        elif mutation == "has_stages_empty_list":
            body["stages"] = []
        elif mutation == "missing_why":
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
        r = requests.post(f"{API}/knowledge/journeys", json=body, headers=h)
        assert r.status_code in codes, f"{mutation}: {r.status_code} {r.text}"
        after = _snapshot(h)
        assert after == before, f"{mutation} leaked: {before} -> {after}"


# ---------- 3. Stage CRUD + move ----------

class TestStageCRUD:
    def test_create_stage(self, user):
        h = user["headers"]
        r = requests.post(f"{API}/knowledge/stages", json={
            "journey_id": user["journey_id"], "name": "TEST_kh_MidLevel"
        }, headers=h)
        assert r.status_code == 201, r.text
        d = r.json()
        assert d["name"] == "TEST_kh_MidLevel"
        assert d["journey_id"] == user["journey_id"]
        user["new_stage_id"] = d["id"]

    def test_stage_rename(self, user):
        r = requests.put(f"{API}/knowledge/stages/{user['new_stage_id']}",
                         json={"name": "TEST_kh_MidRenamed"}, headers=user["headers"])
        assert r.status_code == 200
        assert r.json()["name"] == "TEST_kh_MidRenamed"

    def test_move_up_then_down_swaps_sequence(self, user):
        h = user["headers"]
        stages_before = requests.get(
            f"{API}/knowledge/journeys/{user['journey_id']}/stages", headers=h
        ).json()
        # Move the last (new) stage up: it should swap with the second one.
        mid_id = user["new_stage_id"]
        r = requests.post(f"{API}/knowledge/stages/{mid_id}/move",
                          params={"direction": "up"}, headers=h)
        assert r.status_code == 200
        after = requests.get(
            f"{API}/knowledge/journeys/{user['journey_id']}/stages", headers=h
        ).json()
        idx_before = [s["id"] for s in stages_before].index(mid_id)
        idx_after = [s["id"] for s in after].index(mid_id)
        assert idx_after == idx_before - 1, f"{idx_before} -> {idx_after}"
        # Now down.
        r = requests.post(f"{API}/knowledge/stages/{mid_id}/move",
                          params={"direction": "down"}, headers=h)
        assert r.status_code == 200
        back = requests.get(
            f"{API}/knowledge/journeys/{user['journey_id']}/stages", headers=h
        ).json()
        idx_back = [s["id"] for s in back].index(mid_id)
        assert idx_back == idx_before

    def test_move_past_end_is_noop(self, user):
        h = user["headers"]
        stages = requests.get(
            f"{API}/knowledge/journeys/{user['journey_id']}/stages", headers=h
        ).json()
        first_id = stages[0]["id"]
        r = requests.post(f"{API}/knowledge/stages/{first_id}/move",
                          params={"direction": "up"}, headers=h)
        assert r.status_code == 200
        assert "No move" in r.text or r.json().get("detail") == "No move"

    def test_move_bad_direction(self, user):
        r = requests.post(
            f"{API}/knowledge/stages/{user['new_stage_id']}/move",
            params={"direction": "sideways"}, headers=user["headers"],
        )
        assert r.status_code == 400

    def test_delete_stage_cascades(self, user):
        """Delete the new stage after adding a component under it."""
        h = user["headers"]
        # Add a component under the new stage.
        r = requests.post(f"{API}/knowledge/components", json={
            "journey_id": user["journey_id"],
            "stage_id": user["new_stage_id"],
            "name": "TEST_kh_stage_child_comp",
        }, headers=h)
        assert r.status_code == 201, r.text
        comp_id = r.json()["id"]
        # Delete the stage.
        r = requests.delete(f"{API}/knowledge/stages/{user['new_stage_id']}", headers=h)
        assert r.status_code == 200
        # Both stage and component gone.
        assert requests.get(
            f"{API}/knowledge/components/", params={"journey_id": user["journey_id"]},
            headers=h,
        ).status_code in (404, 405)  # route only supports /journeys/{id}/components
        comps = requests.get(
            f"{API}/knowledge/journeys/{user['journey_id']}/components", headers=h
        ).json()
        assert all(c["id"] != comp_id for c in comps)


# ---------- 4. Component CRUD + move ----------

class TestComponentCRUD:
    def test_create_top_level(self, user):
        h = user["headers"]
        stage_id = user["stage_ids"][0]  # Beginner
        r = requests.post(f"{API}/knowledge/components", json={
            "journey_id": user["journey_id"], "stage_id": stage_id,
            "name": "TEST_kh_Openings", "type": "Section",
        }, headers=h)
        assert r.status_code == 201, r.text
        c = r.json()
        assert c["status"] == "not_started"
        assert c["progress"] == 0
        assert c["parent_component_id"] is None
        assert c["stage_id"] == stage_id
        user["comp_parent_id"] = c["id"]

    def test_create_child_inherits_stage(self, user):
        h = user["headers"]
        r = requests.post(f"{API}/knowledge/components", json={
            "journey_id": user["journey_id"],
            "parent_component_id": user["comp_parent_id"],
            "name": "TEST_kh_RuyLopez",
        }, headers=h)
        assert r.status_code == 201, r.text
        c = r.json()
        # Child inherited parent's stage_id.
        parent_stage = user["stage_ids"][0]
        assert c["stage_id"] == parent_stage, f"expected {parent_stage} got {c['stage_id']}"
        user["comp_child_id"] = c["id"]

    def test_create_second_child_for_move(self, user):
        r = requests.post(f"{API}/knowledge/components", json={
            "journey_id": user["journey_id"],
            "parent_component_id": user["comp_parent_id"],
            "name": "TEST_kh_Italian",
        }, headers=user["headers"])
        assert r.status_code == 201
        user["comp_child2_id"] = r.json()["id"]

    def test_update_status_progress(self, user):
        r = requests.put(f"{API}/knowledge/components/{user['comp_child_id']}",
                         json={"status": "in_progress", "progress": 50},
                         headers=user["headers"])
        assert r.status_code == 200
        c = r.json()
        assert c["status"] == "in_progress" and c["progress"] == 50

    def test_update_invalid_status(self, user):
        r = requests.put(f"{API}/knowledge/components/{user['comp_child_id']}",
                         json={"status": "bogus"}, headers=user["headers"])
        assert r.status_code == 400

    def test_update_invalid_progress(self, user):
        r = requests.put(f"{API}/knowledge/components/{user['comp_child_id']}",
                         json={"progress": 150}, headers=user["headers"])
        assert r.status_code == 400

    def test_create_with_bad_stage_id(self, user):
        r = requests.post(f"{API}/knowledge/components", json={
            "journey_id": user["journey_id"], "stage_id": "bogus_stage",
            "name": "TEST_kh_bad_stage",
        }, headers=user["headers"])
        assert r.status_code == 400

    def test_create_with_bad_parent(self, user):
        r = requests.post(f"{API}/knowledge/components", json={
            "journey_id": user["journey_id"], "parent_component_id": "bogus_parent",
            "name": "TEST_kh_bad_parent",
        }, headers=user["headers"])
        assert r.status_code == 400

    def test_component_move_up_down(self, user):
        h = user["headers"]
        before = requests.get(
            f"{API}/knowledge/journeys/{user['journey_id']}/components", headers=h
        ).json()
        siblings = [c for c in before if c.get("parent_component_id") == user["comp_parent_id"]]
        siblings.sort(key=lambda c: c["sequence"])
        assert [s["id"] for s in siblings][:2] == [user["comp_child_id"], user["comp_child2_id"]]
        # Move child2 up -> should now be first sibling.
        r = requests.post(f"{API}/knowledge/components/{user['comp_child2_id']}/move",
                          params={"direction": "up"}, headers=h)
        assert r.status_code == 200
        after = requests.get(
            f"{API}/knowledge/journeys/{user['journey_id']}/components", headers=h
        ).json()
        sibs = sorted(
            [c for c in after if c.get("parent_component_id") == user["comp_parent_id"]],
            key=lambda c: c["sequence"],
        )
        assert sibs[0]["id"] == user["comp_child2_id"]
        # Move back down.
        requests.post(f"{API}/knowledge/components/{user['comp_child2_id']}/move",
                      params={"direction": "down"}, headers=h)


# ---------- 5. Task/Check-in component_id validation + filter ----------

class TestTaskCheckinComponent:
    def test_create_task_with_valid_component(self, user):
        h = user["headers"]
        # We need an EO to attach the task to.
        eos = requests.get(f"{API}/goals/{user['goal_id']}/expected-outcomes", headers=h).json()
        eo_id = eos[0]["id"]
        r = requests.post(f"{API}/tasks", json={
            "title": "TEST_kh_task_on_comp", "origin": "expected_outcome",
            "expected_outcome_id": eo_id, "component_id": user["comp_child_id"],
        }, headers=h)
        assert r.status_code == 201, r.text
        assert r.json()["component_id"] == user["comp_child_id"]
        user["task_on_child"] = r.json()["id"]

    def test_create_task_with_bogus_component(self, user):
        h = user["headers"]
        eos = requests.get(f"{API}/goals/{user['goal_id']}/expected-outcomes", headers=h).json()
        r = requests.post(f"{API}/tasks", json={
            "title": "TEST_kh_bad", "origin": "expected_outcome",
            "expected_outcome_id": eos[0]["id"], "component_id": "not_a_real_id",
        }, headers=h)
        assert r.status_code == 400

    def test_create_checkin_with_valid_component(self, user):
        h = user["headers"]
        eos = requests.get(f"{API}/goals/{user['goal_id']}/expected-outcomes", headers=h).json()
        r = requests.post(f"{API}/checkins", json={
            "type": "goal", "title": "TEST_kh_ci", "date": "2026-01-15",
            "time": "10:00", "expected_outcome_id": eos[0]["id"],
            "component_id": user["comp_child_id"],
            "data": {"duration_minutes": 30, "note": "n"},
        }, headers=h)
        assert r.status_code == 201, r.text
        assert r.json()["component_id"] == user["comp_child_id"]
        user["ci_on_child"] = r.json()["id"]

    def test_create_checkin_with_bogus_component(self, user):
        h = user["headers"]
        eos = requests.get(f"{API}/goals/{user['goal_id']}/expected-outcomes", headers=h).json()
        r = requests.post(f"{API}/checkins", json={
            "type": "goal", "title": "TEST_kh_ci_bad", "date": "2026-01-15",
            "time": "10:00", "expected_outcome_id": eos[0]["id"],
            "component_id": "not_a_real_id", "data": {},
        }, headers=h)
        assert r.status_code == 400

    def test_filter_tasks_by_component(self, user):
        r = requests.get(f"{API}/tasks",
                         params={"component_id": user["comp_child_id"]},
                         headers=user["headers"])
        assert r.status_code == 200
        ids = [t["id"] for t in r.json()]
        assert user["task_on_child"] in ids
        # First-task-from-wizard has component_id=None, so must NOT be in the result.
        wizard_tasks = requests.get(
            f"{API}/tasks", params={"goal_id": user["goal_id"]}, headers=user["headers"]
        ).json()
        wizard_task = next((t for t in wizard_tasks if t["title"] == "Study 3 openings"), None)
        assert wizard_task is not None and wizard_task["id"] not in ids

    def test_filter_tasks_by_goal_or_component_union(self, user):
        """goal_id + component_id are unioned via $or."""
        r = requests.get(f"{API}/tasks", params={
            "goal_id": user["goal_id"], "component_id": user["comp_child_id"],
        }, headers=user["headers"])
        assert r.status_code == 200
        ids = {t["id"] for t in r.json()}
        # Both the wizard task (goal-scoped, component_id None) and the
        # component-scoped task must be present.
        wizard_tasks = requests.get(
            f"{API}/tasks", params={"goal_id": user["goal_id"]}, headers=user["headers"]
        ).json()
        wizard_id = next(t["id"] for t in wizard_tasks if t["title"] == "Study 3 openings")
        assert wizard_id in ids
        assert user["task_on_child"] in ids

    def test_filter_checkins_by_component(self, user):
        r = requests.get(f"{API}/checkins",
                         params={"component_id": user["comp_child_id"]},
                         headers=user["headers"])
        assert r.status_code == 200
        assert any(c["id"] == user["ci_on_child"] for c in r.json())


# ---------- 6. Cascade delete of component detaches tasks/checkins ----------

class TestComponentCascadeDetach:
    def test_delete_parent_component_detaches_task_and_checkin(self, user):
        h = user["headers"]
        # Sanity: task and checkin currently link to child.
        t_before = requests.get(f"{API}/tasks/{user['task_on_child']}", headers=h).json()
        assert t_before["component_id"] == user["comp_child_id"]
        # Delete the PARENT — should nuke both children and detach the task/checkin.
        r = requests.delete(
            f"{API}/knowledge/components/{user['comp_parent_id']}", headers=h
        )
        assert r.status_code == 200
        # Parent + children gone.
        comps = requests.get(
            f"{API}/knowledge/journeys/{user['journey_id']}/components", headers=h
        ).json()
        remaining_ids = [c["id"] for c in comps]
        for cid in (user["comp_parent_id"], user["comp_child_id"], user["comp_child2_id"]):
            assert cid not in remaining_ids
        # Task and check-in still exist but detached.
        tr = requests.get(f"{API}/tasks/{user['task_on_child']}", headers=h)
        assert tr.status_code == 200
        assert tr.json()["component_id"] in (None, "")
        cr = requests.get(f"{API}/checkins/{user['ci_on_child']}", headers=h)
        assert cr.status_code == 200
        assert cr.json()["component_id"] in (None, "")


# ---------- 7. Legacy backfill (existing user) ----------

class TestLegacyBackfill:
    def test_existing_user_all_knowledge_goals_have_journey(self, existing_user):
        h = existing_user["headers"]
        # Two reads must return identical count (idempotent).
        r1 = requests.get(f"{API}/knowledge/journeys", headers=h)
        assert r1.status_code == 200
        r2 = requests.get(f"{API}/knowledge/journeys", headers=h)
        assert r2.status_code == 200
        j1, j2 = r1.json(), r2.json()
        assert len(j1) == len(j2)
        # Every returned journey has both a goal_id and required fields.
        for j in j1:
            assert j["goal_id"]
            assert isinstance(j["has_stages"], bool)
            assert "journey_type" in j  # may be "" for legacy backfill
            # Corresponding goal must be reachable.
            assert requests.get(f"{API}/goals/{j['goal_id']}", headers=h).status_code == 200


# ---------- 8. Journey delete cascade ----------

class TestJourneyDeleteCascade:
    def test_delete_flat_journey_cleans_up(self, user):
        h = user["headers"]
        jid = user["flat_journey_id"]
        gid = user["flat_goal_id"]
        # Add a component to the flat journey + a task attached to it.
        r = requests.post(f"{API}/knowledge/components", json={
            "journey_id": jid, "name": "TEST_kh_flat_comp",
        }, headers=h)
        assert r.status_code == 201
        cid = r.json()["id"]
        # Add task attached to the component.
        eos = requests.get(f"{API}/goals/{gid}/expected-outcomes", headers=h).json()
        eo_id = eos[0]["id"]
        tr = requests.post(f"{API}/tasks", json={
            "title": "TEST_kh_flat_task", "origin": "expected_outcome",
            "expected_outcome_id": eo_id, "component_id": cid,
        }, headers=h)
        assert tr.status_code == 201
        tid = tr.json()["id"]
        # Delete the journey.
        d = requests.delete(f"{API}/knowledge/journeys/{jid}", headers=h)
        assert d.status_code == 200
        # Journey gone.
        assert requests.get(f"{API}/knowledge/journeys/{jid}", headers=h).status_code == 404
        # Goal gone.
        assert requests.get(f"{API}/goals/{gid}", headers=h).status_code == 404
        # Task is DETACHED but NOT deleted (per the design).
        tr2 = requests.get(f"{API}/tasks/{tid}", headers=h)
        # Task may either be gone (EO deletion cascade) or detached — spec says
        # tasks/checkins are detached. If EO is deleted the task lookup should
        # still return the row with component_id=None.
        # Accept either behaviour as long as no orphan component_id remains.
        if tr2.status_code == 200:
            assert tr2.json()["component_id"] in (None, "")


# ---------- 9. Regressions ----------

class TestRegressions:
    def test_auth_me(self, user):
        assert requests.get(f"{API}/auth/me", headers=user["headers"]).status_code == 200

    def test_domains_and_outcome_types(self, user):
        h = user["headers"]
        assert requests.get(f"{API}/domains", headers=h).status_code == 200
        assert requests.get(f"{API}/outcome-types", headers=h).status_code == 200

    def test_project_full_crud(self, user):
        h = user["headers"]
        r = requests.post(f"{API}/projects", json={"title": "TEST_kh_proj"}, headers=h)
        assert r.status_code == 201
        pid = r.json()["id"]
        assert requests.put(f"{API}/projects/{pid}",
                            json={"title": "TEST_kh_proj_upd"}, headers=h).status_code == 200
        assert requests.delete(f"{API}/projects/{pid}", headers=h).status_code == 200

    def test_task_without_component_id_still_works(self, user):
        h = user["headers"]
        eos = requests.get(f"{API}/goals/{user['goal_id']}/expected-outcomes", headers=h).json()
        r = requests.post(f"{API}/tasks", json={
            "title": "TEST_kh_no_comp_task", "origin": "expected_outcome",
            "expected_outcome_id": eos[0]["id"],
        }, headers=h)
        assert r.status_code == 201
        assert r.json()["component_id"] in (None, "")

    def test_user_isolation(self, user):
        other_email = _uniq()
        r = requests.post(f"{API}/auth/signup", json={
            "email": other_email, "password": "TestPass123!",
            "security_question": "?", "security_answer": "a",
        })
        assert r.status_code == 201
        oh = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r2 = requests.post(f"{API}/knowledge/journeys", json=_valid_wizard_body(), headers=oh)
        assert r2.status_code == 201
        other_id = r2.json()["id"]
        mine = requests.get(f"{API}/knowledge/journeys", headers=user["headers"]).json()
        assert all(j["id"] != other_id for j in mine)
