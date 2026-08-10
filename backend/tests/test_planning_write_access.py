"""Backend edge tests for iteration 18 — planning full write access.

Covers (all via direct proposal injection into db.plan_conversations to
avoid LLM non-determinism):
- Exclusive-item safety in existing_item_updates.
- Exclusive-item safety in consolidations (survivor MUST be non-exclusive).
- Weekday-filtered recurrence expansion (Mon/Wed/Fri window → 6 check-ins).
- Empty days_of_week means every day (5-day window → 5 check-ins).
- Life-type recurrence with no anchor still creates check-ins.
- Badly-formed proposal fields silently skipped (no 500).
- Consolidations do NOT destroy the current planning target.
- Materialize is not re-runnable on same message_id (400).
- Idempotency of consolidation — losers 404, survivor 200.
- Reparent correctness: EO / task / check-in counts summed onto survivor.
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import date, timedelta

import pytest
import requests


# ---- Backend URL ---------------------------------------------------------
def _load_backend_url() -> str:
    with open("/app/frontend/.env", "r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
                return line.split("=", 1)[1].strip().strip('"').rstrip("/")
    raise RuntimeError("EXPO_PUBLIC_BACKEND_URL not found")


BASE_URL = _load_backend_url()
API = f"{BASE_URL}/api"

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
    email = f"TEST_pwr_{suffix}@example.com"
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
    return r.json()[0]["id"]


def _fresh_goal(auth, domain_id, title: str, **kwargs) -> dict:
    payload = {"title": title, "domain_id": domain_id, **kwargs}
    r = requests.post(f"{API}/goals", headers=auth["headers"],
                      json=payload, timeout=20)
    assert r.status_code == 201, r.text
    return r.json()


def _fresh_project(auth, title: str, **kwargs) -> dict:
    payload = {"title": title, **kwargs}
    r = requests.post(f"{API}/projects", headers=auth["headers"],
                      json=payload, timeout=20)
    assert r.status_code == 201, r.text
    return r.json()


def _conv_id(auth, goal_id: str) -> str:
    r = requests.get(f"{API}/planning/goal/{goal_id}/conversation",
                     headers=auth["headers"], timeout=20)
    assert r.status_code == 200
    return r.json()["id"]


def _inject_and_materialize(auth, conv_id: str, proposal: dict) -> dict:
    msg_id = str(uuid.uuid4())
    _inject_message(conv_id, {
        "id": msg_id, "role": "assistant",
        "content": "Injected.", "proposal": proposal,
        "created_at": "2026-01-01T00:00:00+00:00",
    })
    r = requests.post(f"{API}/planning/conversations/{conv_id}/materialize",
                      headers=auth["headers"], json={"message_id": msg_id},
                      timeout=45)
    return {"status": r.status_code, "body": r.json() if r.status_code == 200 else r.text,
            "msg_id": msg_id}


# ---- 1. Exclusive-item safety in existing_item_updates -------------------
class TestExistingItemUpdatesExclusiveSafety:
    def test_exclusive_goal_updates_are_rejected(self, auth, domain_id):
        # Anchor goal for the conversation (must exist and be non-exclusive
        # so it survives its own conv).
        anchor = _fresh_goal(auth, domain_id, "TEST_pwr_anchor_upd")
        excl = _fresh_goal(auth, domain_id, "TEST_pwr_excl_upd",
                           commitment_type="exclusive",
                           notes="original_notes_do_not_touch")

        conv_id = _conv_id(auth, anchor["id"])
        proposal = {
            "summary": "attack exclusive",
            "existing_item_updates": [
                {"kind": "goal", "id": excl["id"],
                 "patch": {"status": "paused", "notes": "changed"}}
            ],
        }
        res = _inject_and_materialize(auth, conv_id, proposal)
        assert res["status"] == 200, res["body"]
        applied = res["body"]["result"]["applied_existing_updates"]
        assert not any(u["id"] == excl["id"] for u in applied), applied

        # Verify DB: exclusive goal unchanged
        got = requests.get(f"{API}/goals/{excl['id']}",
                           headers=auth["headers"], timeout=15).json()
        assert got["status"] == "active"
        assert got["notes"] == "original_notes_do_not_touch"
        assert got["commitment_type"] == "exclusive"


# ---- 2. Exclusive-item safety in consolidations --------------------------
class TestConsolidationExclusiveSafety:
    def test_exclusive_survives_and_non_exclusive_consolidated(self, auth, domain_id):
        anchor = _fresh_goal(auth, domain_id, "TEST_pwr_anchor_cons_excl")
        # 3 goals with identical title; middle one is exclusive.
        g1 = _fresh_goal(auth, domain_id, "DUP_EXCL_Test",
                         notes="candidate1_notes")
        g2 = _fresh_goal(auth, domain_id, "DUP_EXCL_Test",
                         commitment_type="exclusive",
                         notes="EXCL_notes_must_remain")
        g3 = _fresh_goal(auth, domain_id, "DUP_EXCL_Test",
                         notes="candidate3_notes")

        conv_id = _conv_id(auth, anchor["id"])
        proposal = {"summary": "merge dups",
                    "consolidations": [{"kind": "goal",
                                        "candidate_ids": [g1["id"], g2["id"], g3["id"]],
                                        "reason": "identical title"}]}
        res = _inject_and_materialize(auth, conv_id, proposal)
        assert res["status"] == 200, res["body"]

        # Exclusive g2 must survive intact.
        got_excl = requests.get(f"{API}/goals/{g2['id']}",
                                headers=auth["headers"], timeout=15)
        assert got_excl.status_code == 200
        assert got_excl.json()["notes"] == "EXCL_notes_must_remain"
        assert got_excl.json()["commitment_type"] == "exclusive"

        # Exactly one survivor between g1/g3; the other should be gone.
        s1 = requests.get(f"{API}/goals/{g1['id']}", headers=auth["headers"], timeout=15)
        s3 = requests.get(f"{API}/goals/{g3['id']}", headers=auth["headers"], timeout=15)
        alive = {"g1": s1.status_code == 200, "g3": s3.status_code == 200}
        assert sum(alive.values()) == 1, f"expected exactly one of g1/g3 alive, got {alive}"

        applied = res["body"]["result"]["applied_consolidations"]
        assert len(applied) == 1
        assert applied[0]["survivor_id"] in (g1["id"], g3["id"])
        assert g2["id"] != applied[0]["survivor_id"]

    def test_only_one_non_exclusive_left_is_silent_skip(self, auth, domain_id):
        anchor = _fresh_goal(auth, domain_id, "TEST_pwr_anchor_solo")
        g1 = _fresh_goal(auth, domain_id, "SoloDup", commitment_type="exclusive")
        g2 = _fresh_goal(auth, domain_id, "SoloDup")  # only non-exclusive candidate

        conv_id = _conv_id(auth, anchor["id"])
        proposal = {"consolidations": [{"kind": "goal",
                                        "candidate_ids": [g1["id"], g2["id"]]}]}
        res = _inject_and_materialize(auth, conv_id, proposal)
        assert res["status"] == 200
        assert res["body"]["result"]["applied_consolidations"] == []
        # Both goals should still exist.
        for gid in (g1["id"], g2["id"]):
            r = requests.get(f"{API}/goals/{gid}", headers=auth["headers"], timeout=15)
            assert r.status_code == 200, f"goal {gid} unexpectedly deleted"


# ---- 3. Weekday-filtered recurrences -------------------------------------
class TestWeekdayRecurrence:
    def test_mon_wed_fri_two_weeks_exactly_six(self, auth, domain_id):
        goal = _fresh_goal(auth, domain_id, "TEST_pwr_recur_weekday")
        # Create an existing EO to anchor.
        r = requests.post(f"{API}/expected-outcomes",
                          headers=auth["headers"],
                          json={"title": "AnchorEO", "goal_id": goal["id"]}, timeout=15)
        assert r.status_code in (200, 201), r.text
        eo_title = "AnchorEO"

        conv_id = _conv_id(auth, goal["id"])
        proposal = {"checkin_recurrences": [{
            "type": "goal", "title": "Weekday morning",
            "start_date": "2026-08-10",  # Monday
            "end_date": "2026-08-23",    # Sunday of next week
            "days_of_week": ["monday", "wednesday", "friday"],
            "time": "06:00",
            "expected_outcome_title": eo_title,
        }]}
        res = _inject_and_materialize(auth, conv_id, proposal)
        assert res["status"] == 200, res["body"]
        created = res["body"]["result"]["created_checkins"]
        assert len(created) == 6, f"expected 6 checkins, got {len(created)}"

        # Verify weekday only Mon/Wed/Fri; anchor set correctly.
        r = requests.get(f"{API}/checkins?goal_id={goal['id']}",
                         headers=auth["headers"], timeout=15)
        assert r.status_code == 200
        rows = [c for c in r.json() if c["id"] in created]
        assert len(rows) == 6
        for c in rows:
            assert c["type"] == "goal"
            assert c["goal_id"] == goal["id"]
            assert c["expected_outcome_id"], "EO anchor must be set"
            d = date.fromisoformat(c["date"])
            assert d.weekday() in (0, 2, 4), f"date {c['date']} not Mon/Wed/Fri"

    def test_empty_dow_means_every_day(self, auth, domain_id):
        goal = _fresh_goal(auth, domain_id, "TEST_pwr_recur_everyday")
        requests.post(f"{API}/expected-outcomes",
                      headers=auth["headers"],
                      json={"title": "EODaily", "goal_id": goal["id"]}, timeout=15)

        conv_id = _conv_id(auth, goal["id"])
        proposal = {"checkin_recurrences": [{
            "type": "goal", "title": "Daily",
            "start_date": "2026-08-10", "end_date": "2026-08-14",  # 5 days
            "days_of_week": [],
            "time": "07:00",
            "expected_outcome_title": "EODaily",
        }]}
        res = _inject_and_materialize(auth, conv_id, proposal)
        assert res["status"] == 200
        created = res["body"]["result"]["created_checkins"]
        assert len(created) == 5, f"expected 5 checkins, got {len(created)}"

    def test_life_recurrence_needs_no_anchor(self, auth, domain_id):
        goal = _fresh_goal(auth, domain_id, "TEST_pwr_life_recur")
        conv_id = _conv_id(auth, goal["id"])
        proposal = {"checkin_recurrences": [{
            "type": "life", "title": "Meditation",
            "start_date": "2026-09-01", "end_date": "2026-09-03",
            "days_of_week": [], "time": "05:30",
        }]}
        res = _inject_and_materialize(auth, conv_id, proposal)
        assert res["status"] == 200
        created = res["body"]["result"]["created_checkins"]
        assert len(created) == 3
        r = requests.get(f"{API}/checkins", headers=auth["headers"], timeout=15)
        assert r.status_code == 200
        rows = [c for c in r.json() if c["id"] in created]
        assert len(rows) == 3
        for c in rows:
            assert c["type"] == "life"
            assert c.get("goal_id") in (None, "")
            assert c.get("project_id") in (None, "")
            assert c.get("expected_outcome_id") in (None, "")


# ---- 4. Badly-formed proposal silently skipped ---------------------------
class TestBadlyFormedSilentSkip:
    def test_no_500_all_buckets_empty(self, auth, domain_id):
        # Anchor goal + one postponable target for the update case.
        anchor = _fresh_goal(auth, domain_id, "TEST_pwr_bad_anchor")
        real = _fresh_goal(auth, domain_id, "TEST_pwr_real_goal",
                           notes="original")
        conv_id = _conv_id(auth, anchor["id"])

        proposal = {
            "summary": "junk",
            "checkin_recurrences": [
                # (a) missing time
                {"type": "life", "title": "no time",
                 "start_date": "2026-08-01", "end_date": "2026-08-05",
                 "days_of_week": []},
                # (f) end_date before start_date
                {"type": "life", "title": "bad range",
                 "start_date": "2026-08-10", "end_date": "2026-08-01",
                 "time": "09:00", "days_of_week": []},
            ],
            "checkins": [
                # (b) invalid type
                {"type": "invalid_type", "title": "bad", "date": "2026-08-01",
                 "time": "09:00"},
            ],
            "existing_item_updates": [
                # (c) unknown key 'foo'
                {"kind": "goal", "id": real["id"], "patch": {"foo": "bar"}},
                # (e) garbage status
                {"kind": "goal", "id": real["id"], "patch": {"status": "garbage_status"}},
            ],
            "consolidations": [
                # (d) only one candidate
                {"kind": "goal", "candidate_ids": [real["id"]]},
            ],
        }
        res = _inject_and_materialize(auth, conv_id, proposal)
        assert res["status"] == 200, res["body"]
        r = res["body"]["result"]
        assert r["created_checkins"] == []
        assert r["applied_existing_updates"] == []
        assert r["applied_consolidations"] == []

        # Real goal untouched.
        got = requests.get(f"{API}/goals/{real['id']}",
                           headers=auth["headers"], timeout=15).json()
        assert got["status"] == "active"
        assert got["notes"] == "original"


# ---- 5. Current planning target protected in consolidations --------------
class TestCurrentTargetProtected:
    def test_current_target_survives_consolidation(self, auth, domain_id):
        # Create three dup goals, one of them being the CURRENT target of the
        # planning conversation.
        target = _fresh_goal(auth, domain_id, "TARGET_DUP",
                             notes="target_notes")
        g2 = _fresh_goal(auth, domain_id, "TARGET_DUP", notes="g2")
        g3 = _fresh_goal(auth, domain_id, "TARGET_DUP", notes="g3")

        conv_id = _conv_id(auth, target["id"])
        proposal = {"consolidations": [{"kind": "goal",
                                        "candidate_ids": [target["id"], g2["id"], g3["id"]]}]}
        res = _inject_and_materialize(auth, conv_id, proposal)
        assert res["status"] == 200, res["body"]

        # Current target must still exist.
        r = requests.get(f"{API}/goals/{target['id']}",
                         headers=auth["headers"], timeout=15)
        assert r.status_code == 200, "current planning target was destroyed!"


# ---- 6. Materialize not re-runnable + consolidation idempotency ----------
class TestMaterializeIdempotencyAndConsolidation:
    def test_reparent_correctness_and_losers_404(self, auth, domain_id):
        anchor = _fresh_goal(auth, domain_id, "TEST_pwr_anchor_reparent")
        g1 = _fresh_goal(auth, domain_id, "REPARENT_DUP", notes="g1")
        g2 = _fresh_goal(auth, domain_id, "REPARENT_DUP", notes="g2 has more metadata "
                                                                 "and check-in cadence",
                        checkin_cadence="daily", deadline="2027-06-30")

        # Attach EOs to each so richness_score differs, and add check-ins.
        for gid, ntitle in ((g1["id"], "EO_g1"), (g2["id"], "EO_g2a"), (g2["id"], "EO_g2b")):
            requests.post(f"{API}/expected-outcomes",
                          headers=auth["headers"],
                          json={"title": ntitle, "goal_id": gid}, timeout=15)
        # Add a check-in tied to g1 (life-type or via a manual insert path is
        # simpler; use the /api/checkins endpoint w/ goal type).
        # We need an EO of that goal to attach a goal check-in — fetch g1's EO.
        eos_g1 = requests.get(f"{API}/goals/{g1['id']}/expected-outcomes",
                              headers=auth["headers"], timeout=15).json()
        eo_g1_id = eos_g1[0]["id"] if eos_g1 else None
        n_ci_g1_before = 0
        if eo_g1_id:
            cr = requests.post(f"{API}/checkins", headers=auth["headers"],
                               json={"type": "goal", "title": "TEST_ci_g1",
                                     "date": "2026-05-01", "time": "09:00",
                                     "expected_outcome_id": eo_g1_id}, timeout=15)
            if cr.status_code == 201:
                n_ci_g1_before = 1

        # Count EOs pre.
        eos_g1_before = len(requests.get(f"{API}/goals/{g1['id']}/expected-outcomes",
                                         headers=auth["headers"], timeout=15).json())
        eos_g2_before = len(requests.get(f"{API}/goals/{g2['id']}/expected-outcomes",
                                         headers=auth["headers"], timeout=15).json())

        conv_id = _conv_id(auth, anchor["id"])
        proposal = {"consolidations": [{"kind": "goal",
                                        "candidate_ids": [g1["id"], g2["id"]]}]}
        res = _inject_and_materialize(auth, conv_id, proposal)
        assert res["status"] == 200, res["body"]
        applied = res["body"]["result"]["applied_consolidations"]
        assert len(applied) == 1
        survivor_id = applied[0]["survivor_id"]
        merged_ids = applied[0]["merged_ids"]
        assert survivor_id in (g1["id"], g2["id"])
        assert len(merged_ids) == 1

        # Survivor GET → 200; loser GET → 404
        assert requests.get(f"{API}/goals/{survivor_id}",
                            headers=auth["headers"], timeout=15).status_code == 200
        for lid in merged_ids:
            r = requests.get(f"{API}/goals/{lid}", headers=auth["headers"], timeout=15)
            assert r.status_code == 404, f"loser {lid} still exists: {r.status_code}"

        # Reparent: survivor now has sum of EO counts and check-ins.
        eos_after = requests.get(f"{API}/goals/{survivor_id}/expected-outcomes",
                                 headers=auth["headers"], timeout=15).json()
        assert len(eos_after) == eos_g1_before + eos_g2_before, (
            f"EO reparent mismatch: got {len(eos_after)} "
            f"expected {eos_g1_before + eos_g2_before}"
        )

        ci_after = requests.get(f"{API}/checkins?goal_id={survivor_id}",
                                headers=auth["headers"], timeout=15).json()
        # Check-ins from loser g1 should now be attached to survivor.
        assert len(ci_after) >= n_ci_g1_before

        # Re-run materialize on same message → 400.
        r2 = requests.post(f"{API}/planning/conversations/{conv_id}/materialize",
                           headers=auth["headers"],
                           json={"message_id": res["msg_id"]}, timeout=15)
        assert r2.status_code == 400, r2.text
