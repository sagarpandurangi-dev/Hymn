"""Backend tests for portfolio-aware planning + commitment_type feature (iter 17).

Covers:
- commitment_type validation on Goals / Projects / Tasks (POST + PUT, default, invalid).
- Portfolio-aware planning: fresh conversation, first user turn triggers LLM.
- Life pattern extraction into time_commitments via materialize.
- Idempotency of materialize (409/400 second call).
- Exclusive-item safety net in _materialize_proposal (via direct DB proposal injection).
- Non-exclusive postpone works through materialize (direct DB proposal injection).
- /api/portfolio/time-commitments reflects newly created rows.
"""
from __future__ import annotations

import os
import sys
import uuid
import asyncio

import pytest
import requests


# ---- Backend URL ---------------------------------------------------------
# Enforced to loopback by backend/conftest.py's test guard.
BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"


# ---- Direct DB helper (for proposal injection) ---------------------------
sys.path.insert(0, "/app/backend")


def _read_env(key: str) -> str:
    with open("/app/backend/.env") as fp:
        for line in fp:
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


MONGO_URL = os.environ.get("MONGO_URL") or _read_env("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME") or _read_env("DB_NAME")


def _inject_message(conv_id: str, msg: dict) -> None:
    """Push an assistant message into a plan_conversations doc.
    Uses a fresh event loop + client each call to avoid loop-binding issues."""
    async def _do():
        from motor.motor_asyncio import AsyncIOMotorClient
        client = AsyncIOMotorClient(MONGO_URL)
        try:
            db = client[DB_NAME]
            await db.plan_conversations.update_one(
                {"id": conv_id}, {"$push": {"messages": msg}}
            )
        finally:
            client.close()

    asyncio.run(_do())


# ---- Auth ----------------------------------------------------------------
@pytest.fixture(scope="module")
def auth():
    suffix = uuid.uuid4().hex[:10]
    email = f"TEST_paware_{suffix}@example.com"
    payload = {"email": email, "password": "TestPass123!",
               "security_question": "Color?", "security_answer": "blue"}
    r = requests.post(f"{API}/auth/signup", json=payload, timeout=30)
    assert r.status_code == 201, f"signup failed: {r.status_code} {r.text}"
    data = r.json()
    return {"token": data["access_token"], "user": data["user"],
            "headers": {"Authorization": f"Bearer {data['access_token']}"}}


@pytest.fixture(scope="module")
def domain_id(auth):
    r = requests.get(f"{API}/domains", headers=auth["headers"], timeout=20)
    assert r.status_code == 200
    ds = r.json()
    return ds[0]["id"]


# ---- commitment_type validation on Goals ---------------------------------
class TestGoalCommitmentType:
    def test_default_is_postponable(self, auth, domain_id):
        r = requests.post(f"{API}/goals", headers=auth["headers"],
                          json={"title": "TEST_goal_default_ct", "domain_id": domain_id}, timeout=20)
        assert r.status_code == 201, r.text
        g = r.json()
        assert g["commitment_type"] == "postponable"

    def test_create_with_exclusive_persists(self, auth, domain_id):
        r = requests.post(f"{API}/goals", headers=auth["headers"],
                          json={"title": "TEST_goal_excl", "domain_id": domain_id,
                                "commitment_type": "exclusive"}, timeout=20)
        assert r.status_code == 201, r.text
        gid = r.json()["id"]
        r2 = requests.get(f"{API}/goals/{gid}", headers=auth["headers"], timeout=20)
        assert r2.status_code == 200
        assert r2.json()["commitment_type"] == "exclusive"

    def test_put_exclusive_ok(self, auth, domain_id):
        r = requests.post(f"{API}/goals", headers=auth["headers"],
                          json={"title": "TEST_goal_put", "domain_id": domain_id}, timeout=20)
        gid = r.json()["id"]
        r2 = requests.put(f"{API}/goals/{gid}", headers=auth["headers"],
                          json={"commitment_type": "exclusive"}, timeout=20)
        assert r2.status_code == 200, r2.text
        assert r2.json()["commitment_type"] == "exclusive"

    def test_put_garbage_400(self, auth, domain_id):
        r = requests.post(f"{API}/goals", headers=auth["headers"],
                          json={"title": "TEST_goal_bad", "domain_id": domain_id}, timeout=20)
        gid = r.json()["id"]
        r2 = requests.put(f"{API}/goals/{gid}", headers=auth["headers"],
                          json={"commitment_type": "garbage"}, timeout=20)
        assert r2.status_code == 400, r2.text


# ---- commitment_type validation on Projects ------------------------------
class TestProjectCommitmentType:
    def test_default(self, auth):
        r = requests.post(f"{API}/projects", headers=auth["headers"],
                          json={"title": "TEST_proj_default_ct"}, timeout=20)
        assert r.status_code == 201
        assert r.json()["commitment_type"] == "postponable"

    def test_create_exclusive(self, auth):
        r = requests.post(f"{API}/projects", headers=auth["headers"],
                          json={"title": "TEST_proj_excl", "commitment_type": "exclusive"}, timeout=20)
        assert r.status_code == 201
        pid = r.json()["id"]
        r2 = requests.get(f"{API}/projects/{pid}", headers=auth["headers"], timeout=20)
        assert r2.json()["commitment_type"] == "exclusive"

    def test_put_ok_and_bad(self, auth):
        r = requests.post(f"{API}/projects", headers=auth["headers"],
                          json={"title": "TEST_proj_upd"}, timeout=20)
        pid = r.json()["id"]
        ok = requests.put(f"{API}/projects/{pid}", headers=auth["headers"],
                          json={"commitment_type": "exclusive"}, timeout=20)
        assert ok.status_code == 200
        bad = requests.put(f"{API}/projects/{pid}", headers=auth["headers"],
                           json={"commitment_type": "junk"}, timeout=20)
        assert bad.status_code == 400


# ---- commitment_type validation on Tasks ---------------------------------
class TestTaskCommitmentType:
    def test_default(self, auth):
        r = requests.post(f"{API}/tasks", headers=auth["headers"],
                          json={"title": "TEST_task_default", "origin": "standalone"}, timeout=20)
        assert r.status_code == 201
        assert r.json()["commitment_type"] == "postponable"

    def test_create_exclusive(self, auth):
        r = requests.post(f"{API}/tasks", headers=auth["headers"],
                          json={"title": "TEST_task_excl", "origin": "standalone",
                                "commitment_type": "exclusive"}, timeout=20)
        assert r.status_code == 201
        assert r.json()["commitment_type"] == "exclusive"

    def test_put_ok_and_bad(self, auth):
        r = requests.post(f"{API}/tasks", headers=auth["headers"],
                          json={"title": "TEST_task_upd", "origin": "standalone"}, timeout=20)
        tid = r.json()["id"]
        ok = requests.put(f"{API}/tasks/{tid}", headers=auth["headers"],
                          json={"commitment_type": "exclusive"}, timeout=20)
        assert ok.status_code == 200
        assert ok.json()["commitment_type"] == "exclusive"
        bad = requests.put(f"{API}/tasks/{tid}", headers=auth["headers"],
                           json={"commitment_type": "nope"}, timeout=20)
        assert bad.status_code == 400


# ---- Portfolio-aware planning conversation --------------------------------
@pytest.fixture(scope="module")
def planning_goal(auth, domain_id):
    r = requests.post(f"{API}/goals", headers=auth["headers"],
                      json={"title": "TEST_paware_ceramics_target",
                            "domain_id": domain_id,
                            "target_outcome": "Take a ceramics class"}, timeout=20)
    assert r.status_code == 201
    return r.json()


class TestPlanningLifePattern:
    """End-to-end LLM turn producing time_commitments; then materialize."""
    conv_id = None
    assistant_msg_id = None

    def test_get_conversation_empty(self, auth, planning_goal):
        r = requests.get(f"{API}/planning/goal/{planning_goal['id']}/conversation",
                         headers=auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        conv = r.json()
        assert conv["messages"] == []
        TestPlanningLifePattern.conv_id = conv["id"]

    def test_post_life_pattern_message(self, auth, planning_goal):
        content = ("I want to add a Ceramics class next month. I have a job Mon-Fri "
                   "10:00-18:00 and Pilates on Mon, Wed, Fri 07:00-08:00. "
                   "Please plan this in.")
        r = requests.post(f"{API}/planning/goal/{planning_goal['id']}/messages",
                          headers=auth["headers"],
                          json={"content": content}, timeout=90)
        assert r.status_code == 200, r.text
        conv = r.json()
        # find the last assistant message
        asst = [m for m in conv["messages"] if m["role"] == "assistant"]
        assert asst, "No assistant reply returned"
        last = asst[-1]
        # visible content must never contain markers
        assert "<<<HYMN_PROPOSAL>>>" not in last["content"]
        assert "<<<END>>>" not in last["content"]
        TestPlanningLifePattern.assistant_msg_id = last["id"]
        # If proposal is present, it may include time_commitments — validate shape only when present.
        prop = last.get("proposal")
        if prop and isinstance(prop, dict):
            tcs = prop.get("time_commitments") or []
            for tc in tcs:
                assert "day_of_week" in tc
                assert "start_time" in tc
                assert "end_time" in tc


# ---- Materialization (via injected proposal so deterministic) ------------
class TestMaterializeInjected:
    """Directly inject a well-formed proposal into db.plan_conversations
    then call materialize — bypasses LLM non-determinism per review note."""

    def test_materialize_time_commitments_and_idempotency(self, auth, planning_goal):
        # Get or create a fresh conversation via API to obtain conv id.
        r = requests.get(f"{API}/planning/goal/{planning_goal['id']}/conversation",
                         headers=auth["headers"], timeout=20)
        conv = r.json()
        conv_id = conv["id"]

        # Inject an assistant message with proposal into DB directly.
        msg_id = str(uuid.uuid4())
        proposal = {
            "summary": "Adding weekly time commitments",
            "time_commitments": [
                {"title": "Job", "day_of_week": "monday",
                 "start_time": "10:00", "end_time": "18:00",
                 "commitment_type": "work", "flexibility": "fixed"},
                {"title": "Pilates", "day_of_week": "wednesday",
                 "start_time": "07:00", "end_time": "08:00",
                 "commitment_type": "health", "flexibility": "flexible"},
            ],
        }
        _inject_message(conv_id, {
            "id": msg_id, "role": "assistant",
            "content": "Injected proposal.",
            "proposal": proposal,
            "created_at": "2026-01-01T00:00:00+00:00",
        })

        # Materialize
        r = requests.post(f"{API}/planning/conversations/{conv_id}/materialize",
                          headers=auth["headers"],
                          json={"message_id": msg_id}, timeout=30)
        assert r.status_code == 200, r.text
        result = r.json()["result"]
        assert len(result["created_time_commitments"]) == 2
        # summary references time commitments
        conv = r.json()["conversation"]
        target = next(m for m in conv["messages"] if m["id"] == msg_id)
        assert "time commitment" in (target.get("materialized_summary") or "").lower()

        # Re-materialize the same message_id → 400
        r2 = requests.post(f"{API}/planning/conversations/{conv_id}/materialize",
                           headers=auth["headers"],
                           json={"message_id": msg_id}, timeout=30)
        assert r2.status_code == 400, r2.text

        # /api/portfolio/time-commitments lists them
        r3 = requests.get(f"{API}/portfolio/time-commitments",
                          headers=auth["headers"], timeout=20)
        assert r3.status_code == 200
        titles = {tc["title"] for tc in r3.json()}
        assert "Job" in titles and "Pilates" in titles
        # source_type=system on injected rows
        for tc in r3.json():
            if tc["title"] in ("Job", "Pilates"):
                assert tc.get("source_type") == "system"


# ---- Exclusive-item safety in materialize --------------------------------
class TestExclusiveSafety:
    def test_exclusive_goal_not_modified(self, auth, domain_id, planning_goal):
        # Create an exclusive goal that a bad proposal will try to postpone.
        r = requests.post(f"{API}/goals", headers=auth["headers"],
                          json={"title": "TEST_excl_should_not_move",
                                "domain_id": domain_id,
                                "commitment_type": "exclusive",
                                "deadline": "2026-06-30"}, timeout=20)
        excl_gid = r.json()["id"]

        # Fresh conversation on another target (planning_goal).
        r = requests.get(f"{API}/planning/goal/{planning_goal['id']}/conversation",
                         headers=auth["headers"], timeout=20)
        conv_id = r.json()["id"]

        msg_id = str(uuid.uuid4())
        proposal = {
            "summary": "Try to postpone exclusive",
            "existing_item_changes": [{
                "kind": "goal", "id": excl_gid, "action": "postpone",
                "new_due_date": "2027-12-31", "reason": "test"
            }],
        }
        _inject_message(conv_id, {
            "id": msg_id, "role": "assistant",
            "content": "Injected exclusive attack.",
            "proposal": proposal,
            "created_at": "2026-01-01T00:00:00+00:00",
        })

        r = requests.post(f"{API}/planning/conversations/{conv_id}/materialize",
                          headers=auth["headers"],
                          json={"message_id": msg_id}, timeout=30)
        assert r.status_code == 200, r.text
        applied = r.json()["result"]["applied_existing_changes"]
        # Exclusive item must NOT be in applied changes.
        assert not any(c["id"] == excl_gid for c in applied), \
            f"exclusive item was modified: {applied}"

        # Verify DB — status stayed 'active', deadline unchanged.
        r2 = requests.get(f"{API}/goals/{excl_gid}", headers=auth["headers"], timeout=20)
        g = r2.json()
        assert g["status"] == "active"
        assert g["deadline"] == "2026-06-30"


# ---- Non-exclusive postpone happy path -----------------------------------
class TestPostponablePostpone:
    def test_postponable_goal_gets_postponed(self, auth, domain_id, planning_goal):
        r = requests.post(f"{API}/goals", headers=auth["headers"],
                          json={"title": "TEST_postponable_target",
                                "domain_id": domain_id,
                                "commitment_type": "postponable",
                                "deadline": "2026-12-31"}, timeout=20)
        gid = r.json()["id"]

        r = requests.get(f"{API}/planning/goal/{planning_goal['id']}/conversation",
                         headers=auth["headers"], timeout=20)
        conv_id = r.json()["id"]
        msg_id = str(uuid.uuid4())
        proposal = {
            "summary": "Postpone to make room",
            "existing_item_changes": [{
                "kind": "goal", "id": gid, "action": "postpone",
                "new_due_date": "2027-03-31", "reason": "test"
            }],
        }
        _inject_message(conv_id, {
            "id": msg_id, "role": "assistant",
            "content": "Injected postpone.",
            "proposal": proposal,
            "created_at": "2026-01-01T00:00:00+00:00",
        })

        r = requests.post(f"{API}/planning/conversations/{conv_id}/materialize",
                          headers=auth["headers"],
                          json={"message_id": msg_id}, timeout=30)
        assert r.status_code == 200, r.text
        applied = r.json()["result"]["applied_existing_changes"]
        assert any(c["id"] == gid and c["action"] == "postpone" for c in applied)

        r2 = requests.get(f"{API}/goals/{gid}", headers=auth["headers"], timeout=20)
        g = r2.json()
        assert g["status"] == "paused"
        assert g["deadline"] == "2027-03-31"
