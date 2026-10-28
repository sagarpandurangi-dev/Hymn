"""Backend tests for the reformed Planning / Decomposition engine.

Covers:
- Auth still works (test@hymn.app / TestPass123!).
- Old planning + old knowledge endpoints removed (404/405).
- New conversational planning endpoints (get/reset/messages/materialize).
- journey_type persisted on Goal create/update + returned in GoalResponse.
- Tasks / check-ins project_id filter.
"""

from __future__ import annotations

import os
import time
import uuid

import pytest
import requests

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
EMAIL = "test@hymn.app"
PASSWORD = "TestPass123!"


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")
def token() -> str:
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": EMAIL, "password": PASSWORD},
        timeout=30,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    assert "access_token" in data and data["access_token"]
    return data["access_token"]


@pytest.fixture(scope="session")
def api(token):
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    return s


@pytest.fixture(scope="session")
def knowledge_domain(api):
    r = api.get(f"{BASE_URL}/api/domains", timeout=15)
    assert r.status_code == 200
    for d in r.json():
        if d["name"] == "Knowledge":
            return d
    pytest.skip("No Knowledge domain seeded for this user")


@pytest.fixture(scope="session")
def existing_knowledge_goal(api):
    """Reuse an existing Knowledge-domain goal (seeded, migrated, etc.)."""
    r = api.get(f"{BASE_URL}/api/goals", timeout=15)
    assert r.status_code == 200
    for g in r.json():
        if g.get("domain_name") == "Knowledge":
            return g
    pytest.skip("No existing Knowledge goal available")


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #


class TestAuth:
    def test_login_returns_bearer_token(self):
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": EMAIL, "password": PASSWORD},
            timeout=15,
        )
        assert r.status_code == 200
        body = r.json()
        assert "access_token" in body and body["access_token"]
        assert body.get("token_type", "bearer").lower() == "bearer"


# --------------------------------------------------------------------------- #
# Old endpoints removed
# --------------------------------------------------------------------------- #


OLD_PLANNING_ENDPOINTS = [
    "/api/planning/analyze",
    "/api/planning/confirm",
    "/api/planning/generate",
    "/api/planning/approve",
    "/api/planning/reject",
    "/api/planning/pause",
    "/api/planning/select-tradeoff",
    "/api/planning/reassess",
    "/api/planning/proposals",
    "/api/planning/proposals/some-id",
]

OLD_KNOWLEDGE_ENDPOINTS = [
    "/api/knowledge/journeys",
    "/api/knowledge/stages",
    "/api/knowledge/components",
]


class TestOldEndpointsRemoved:
    @pytest.mark.parametrize("ep", OLD_PLANNING_ENDPOINTS)
    def test_old_planning_endpoint_removed(self, api, ep):
        r_get = api.get(f"{BASE_URL}{ep}", timeout=15)
        r_post = api.post(f"{BASE_URL}{ep}", json={}, timeout=15)
        assert r_get.status_code in (404, 405), f"{ep} GET = {r_get.status_code}"
        assert r_post.status_code in (404, 405), f"{ep} POST = {r_post.status_code}"

    @pytest.mark.parametrize("ep", OLD_KNOWLEDGE_ENDPOINTS)
    def test_old_knowledge_endpoint_removed(self, api, ep):
        r_get = api.get(f"{BASE_URL}{ep}", timeout=15)
        r_post = api.post(f"{BASE_URL}{ep}", json={}, timeout=15)
        r_put = api.put(f"{BASE_URL}{ep}", json={}, timeout=15)
        r_del = api.delete(f"{BASE_URL}{ep}", timeout=15)
        for verb, code in [("GET", r_get.status_code), ("POST", r_post.status_code),
                            ("PUT", r_put.status_code), ("DELETE", r_del.status_code)]:
            assert code in (404, 405), f"{ep} {verb} = {code}"


# --------------------------------------------------------------------------- #
# journey_type on Goal create/update
# --------------------------------------------------------------------------- #


class TestGoalJourneyType:
    _created_goal_id = None

    def test_create_goal_with_journey_type(self, api, knowledge_domain):
        payload = {
            "title": f"TEST_planning_journey_{uuid.uuid4().hex[:6]}",
            "domain_id": knowledge_domain["id"],
            "target_outcome": "Ship the reform",
            "deadline": "2027-06-30",
            "checkin_cadence": "weekly",
            "journey_type": "certification",
        }
        r = api.post(f"{BASE_URL}/api/goals", json=payload, timeout=15)
        assert r.status_code == 201, r.text
        g = r.json()
        assert g["journey_type"] == "certification"
        assert g["domain_name"] == "Knowledge"
        TestGoalJourneyType._created_goal_id = g["id"]

    def test_update_goal_journey_type_persists(self, api):
        gid = TestGoalJourneyType._created_goal_id
        assert gid, "prev test must have created a goal"
        r = api.put(
            f"{BASE_URL}/api/goals/{gid}",
            json={"journey_type": "language"},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        assert r.json()["journey_type"] == "language"
        # Verify via GET
        g = api.get(f"{BASE_URL}/api/goals/{gid}", timeout=15).json()
        assert g["journey_type"] == "language"

    def test_zzz_cleanup_created_goal(self, api):
        gid = TestGoalJourneyType._created_goal_id
        if gid:
            api.delete(f"{BASE_URL}/api/goals/{gid}", timeout=15)


# --------------------------------------------------------------------------- #
# Planning conversation endpoints
# --------------------------------------------------------------------------- #


class TestConversationLifecycle:
    def test_get_conversation_bad_target_type_400(self, api, existing_knowledge_goal):
        r = api.get(
            f"{BASE_URL}/api/planning/badtype/{existing_knowledge_goal['id']}/conversation",
            timeout=15,
        )
        assert r.status_code == 400, r.text

    def test_get_conversation_unknown_goal_404(self, api):
        r = api.get(
            f"{BASE_URL}/api/planning/goal/00000000-0000-0000-0000-000000000000/conversation",
            timeout=15,
        )
        assert r.status_code == 404, r.text

    def test_get_conversation_shape_and_idempotency(self, api, existing_knowledge_goal):
        gid = existing_knowledge_goal["id"]
        r1 = api.get(f"{BASE_URL}/api/planning/goal/{gid}/conversation", timeout=20)
        assert r1.status_code == 200, r1.text
        c1 = r1.json()
        assert c1["target_type"] == "goal"
        assert c1["target_id"] == gid
        assert isinstance(c1["messages"], list)
        assert "id" in c1

        r2 = api.get(f"{BASE_URL}/api/planning/goal/{gid}/conversation", timeout=20)
        assert r2.status_code == 200
        c2 = r2.json()
        assert c2["id"] == c1["id"], "conversation id must be idempotent"

    def test_reset_returns_fresh_empty(self, api, existing_knowledge_goal):
        gid = existing_knowledge_goal["id"]
        r = api.post(f"{BASE_URL}/api/planning/goal/{gid}/reset", timeout=20)
        assert r.status_code == 200, r.text
        c = r.json()
        assert c["messages"] == []
        assert c["target_id"] == gid


# --------------------------------------------------------------------------- #
# LLM message + materialize (LIVE — Claude Sonnet 4.5, may take 15-30s)
# --------------------------------------------------------------------------- #


class TestMessageAndMaterialize:
    """These tests invoke the live LLM. Kept in one class so we run once."""

    _conv_id: str | None = None
    _proposal_msg_id: str | None = None
    _goal_id: str | None = None

    @pytest.fixture(scope="class")
    def dedicated_goal(self, api, knowledge_domain):
        # Fresh goal to avoid polluting existing data with LLM materializations.
        r = api.post(
            f"{BASE_URL}/api/goals",
            json={
                "title": f"TEST_planning_llm_{uuid.uuid4().hex[:6]}",
                "domain_id": knowledge_domain["id"],
                "target_outcome": "Learn planning reform testing",
                "deadline": "2027-06-30",
                "checkin_cadence": "weekly",
                "journey_type": "skill",
            },
            timeout=15,
        )
        assert r.status_code == 201, r.text
        gid = r.json()["id"]
        yield r.json()
        # Cleanup: delete goal (cascades to outcomes/tasks if implemented; we
        # also individually clean tasks/outcomes we tracked).
        api.delete(f"{BASE_URL}/api/goals/{gid}", timeout=15)

    def test_post_message_produces_assistant_reply(self, api, dedicated_goal):
        gid = dedicated_goal["id"]
        # Ensure conversation is fresh
        api.post(f"{BASE_URL}/api/planning/goal/{gid}/reset", timeout=20)

        r = api.post(
            f"{BASE_URL}/api/planning/goal/{gid}/messages",
            json={"content": "Suggest 3 concrete next tasks for this goal."},
            timeout=90,
        )
        assert r.status_code == 200, r.text
        conv = r.json()
        assert conv["target_id"] == gid
        msgs = conv["messages"]
        # Must have at least 1 user + 1 assistant
        roles = [m["role"] for m in msgs]
        assert "user" in roles and "assistant" in roles
        # No delimiters leaked
        for m in msgs:
            assert "<<<HYMN_PROPOSAL>>>" not in (m["content"] or "")
            assert "<<<END>>>" not in (m["content"] or "")
        TestMessageAndMaterialize._conv_id = conv["id"]
        TestMessageAndMaterialize._goal_id = gid

        # find the proposal message (if any)
        for m in msgs:
            if m.get("role") == "assistant" and m.get("proposal"):
                TestMessageAndMaterialize._proposal_msg_id = m["id"]
                break

    def test_materialize_requires_proposal(self, api):
        """If a proposal was not emitted, coerce one by asking more explicitly."""
        if not TestMessageAndMaterialize._proposal_msg_id:
            gid = TestMessageAndMaterialize._goal_id
            assert gid
            # Retry with a very explicit prompt (up to 2 additional attempts)
            for i in range(2):
                r = api.post(
                    f"{BASE_URL}/api/planning/goal/{gid}/messages",
                    json={
                        "content": (
                            "Please propose 2 concrete expected outcomes and "
                            "3 tasks I can add to my plan right now. Include "
                            "the HYMN_PROPOSAL block."
                        ),
                    },
                    timeout=90,
                )
                assert r.status_code == 200, r.text
                conv = r.json()
                for m in conv["messages"]:
                    if m.get("role") == "assistant" and m.get("proposal"):
                        TestMessageAndMaterialize._proposal_msg_id = m["id"]
                        break
                if TestMessageAndMaterialize._proposal_msg_id:
                    break
                time.sleep(2)
        assert TestMessageAndMaterialize._proposal_msg_id, (
            "LLM never emitted a HYMN_PROPOSAL block — cannot test materialize"
        )

    def test_materialize_success_creates_outcomes_and_tasks(self, api):
        conv_id = TestMessageAndMaterialize._conv_id
        msg_id = TestMessageAndMaterialize._proposal_msg_id
        gid = TestMessageAndMaterialize._goal_id
        assert conv_id and msg_id and gid

        r = api.post(
            f"{BASE_URL}/api/planning/conversations/{conv_id}/materialize",
            json={"message_id": msg_id},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        payload = r.json()
        assert "result" in payload and "conversation" in payload
        result = payload["result"]
        assert isinstance(result["created_outcomes"], list)
        assert isinstance(result["created_tasks"], list)
        # At least some content should have been created
        assert len(result["created_outcomes"]) + len(result["created_tasks"]) > 0

        # Verify persisted: fetch the goal's expected outcomes + tasks
        eos = api.get(
            f"{BASE_URL}/api/goals/{gid}/expected-outcomes", timeout=15,
        ).json()
        assert isinstance(eos, list)
        tasks = api.get(
            f"{BASE_URL}/api/tasks?goal_id={gid}", timeout=15,
        ).json()
        assert isinstance(tasks, list)
        if result["created_tasks"]:
            created_ids = set(result["created_tasks"])
            found = [t for t in tasks if t["id"] in created_ids]
            assert found, "Created tasks must be retrievable via /api/tasks?goal_id=..."
            # Each new task must attach to an outcome (goal target requires it)
            for t in found:
                assert t.get("expected_outcome_id"), (
                    f"Task {t['id']} should be attached to an expected outcome"
                )

    def test_materialize_idempotent_400_on_reapply(self, api):
        conv_id = TestMessageAndMaterialize._conv_id
        msg_id = TestMessageAndMaterialize._proposal_msg_id
        r = api.post(
            f"{BASE_URL}/api/planning/conversations/{conv_id}/materialize",
            json={"message_id": msg_id},
            timeout=15,
        )
        assert r.status_code == 400, r.text
        assert "already" in r.text.lower()

    def test_materialize_missing_proposal_message_400(self, api):
        conv_id = TestMessageAndMaterialize._conv_id
        assert conv_id
        # find a user message id (no proposal)
        gid = TestMessageAndMaterialize._goal_id
        conv = api.get(
            f"{BASE_URL}/api/planning/goal/{gid}/conversation", timeout=15,
        ).json()
        user_msg = next((m for m in conv["messages"] if m["role"] == "user"), None)
        assert user_msg
        r = api.post(
            f"{BASE_URL}/api/planning/conversations/{conv_id}/materialize",
            json={"message_id": user_msg["id"]},
            timeout=15,
        )
        assert r.status_code == 400, r.text


# --------------------------------------------------------------------------- #
# Tasks / Check-ins filters
# --------------------------------------------------------------------------- #


class TestTaskCheckinFilters:
    _project_id: str | None = None
    _task_id: str | None = None
    _checkin_id: str | None = None

    def test_create_project_task_and_checkin(self, api):
        # Get an existing goal to attach the project to
        goals = api.get(f"{BASE_URL}/api/goals", timeout=15).json()
        assert goals, "need at least one goal"
        goal = goals[0]

        pr = api.post(
            f"{BASE_URL}/api/projects",
            json={
                "title": f"TEST_filter_project_{uuid.uuid4().hex[:6]}",
                "goal_id": goal["id"],
            },
            timeout=15,
        )
        assert pr.status_code == 201, pr.text
        pid = pr.json()["id"]
        TestTaskCheckinFilters._project_id = pid

        tr = api.post(
            f"{BASE_URL}/api/tasks",
            json={
                "title": "TEST_filter_task",
                "project_id": pid,
                "origin": "project",
                "priority": "medium",
                "status": "todo",
                "assigned_to_type": "self",
            },
            timeout=15,
        )
        assert tr.status_code == 201, tr.text
        TestTaskCheckinFilters._task_id = tr.json()["id"]

        cr = api.post(
            f"{BASE_URL}/api/checkins",
            json={
                "type": "project",
                "title": "TEST_filter_checkin",
                "notes": "just testing",
                "project_id": pid,
                "date": "2026-01-10",
                "time": "09:00",
            },
            timeout=15,
        )
        assert cr.status_code == 201, cr.text
        TestTaskCheckinFilters._checkin_id = cr.json()["id"]

    def test_tasks_project_id_filter(self, api):
        pid = TestTaskCheckinFilters._project_id
        r = api.get(f"{BASE_URL}/api/tasks?project_id={pid}", timeout=15)
        assert r.status_code == 200
        tasks = r.json()
        assert any(t["id"] == TestTaskCheckinFilters._task_id for t in tasks)
        assert all(t.get("project_id") == pid for t in tasks)

    def test_checkins_project_id_filter(self, api):
        pid = TestTaskCheckinFilters._project_id
        r = api.get(f"{BASE_URL}/api/checkins?project_id={pid}", timeout=15)
        assert r.status_code == 200
        rows = r.json()
        assert any(c["id"] == TestTaskCheckinFilters._checkin_id for c in rows)

    def test_checkins_goal_id_filter_still_works(self, api):
        goals = api.get(f"{BASE_URL}/api/goals", timeout=15).json()
        goal = goals[0]
        r = api.get(f"{BASE_URL}/api/checkins?goal_id={goal['id']}", timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_zzz_cleanup(self, api):
        if TestTaskCheckinFilters._checkin_id:
            api.delete(
                f"{BASE_URL}/api/checkins/{TestTaskCheckinFilters._checkin_id}",
                timeout=15,
            )
        if TestTaskCheckinFilters._task_id:
            api.delete(
                f"{BASE_URL}/api/tasks/{TestTaskCheckinFilters._task_id}",
                timeout=15,
            )
        if TestTaskCheckinFilters._project_id:
            api.delete(
                f"{BASE_URL}/api/projects/{TestTaskCheckinFilters._project_id}",
                timeout=15,
            )
