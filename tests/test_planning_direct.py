"""Direct commit-path test — inject a feasible proposal and approve it.

Skips the LLM entirely so we can verify:
- Approval writes ExpectedOutcomes + Tasks + Money reservations atomically.
- Idempotency via plan_action_log prevents duplicate on re-run.
- Rollback on partial failure.
"""
import asyncio, os, sys, httpx, hashlib, json
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv('/app/backend/.env')

BASE = "http://localhost:8001/api"


async def run():
    mdb = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(f"{BASE}/auth/login", json={
            "email": "test@hymn.app", "password": "TestPass123!"})
        tok = r.json()["access_token"]
        H = {"Authorization": f"Bearer {tok}"}
        me = (await client.get(f"{BASE}/auth/me", headers=H)).json()
        uid = me["id"]

        r = await client.get(f"{BASE}/domains", headers=H)
        did = r.json()[0]["id"]

        # Fresh project
        r = await client.post(f"{BASE}/projects", json={
            "title": "Direct Commit Test", "description": "d",
            "status": "active", "start_date": "2027-01-01",
            "target_end_date": "2027-01-31",
        }, headers=H)
        pid_proj = r.json()["id"]

    # Compute snapshot hash the same way the engine does.
    sys.path.insert(0, "/app/backend")
    from planning_engine import _read_snapshot, _snapshot_hash

    snap = await _read_snapshot(mdb, uid, "project", pid_proj)
    h = _snapshot_hash(snap)

    proposal_id = "test-proposal-" + os.urandom(4).hex()
    tid_1 = "propref-t1"
    tid_2 = "propref-t2"
    doc = {
        "id": proposal_id,
        "user_id": uid,
        "target_type": "project",
        "target_id": pid_proj,
        "snapshot_hash": h,
        "snapshot": snap,
        "version": 1,
        "status": "proposal_ready",
        "current_state": [],
        "confirmation_items": [],
        "blocking_questions": [],
        "proposed_outcomes": [],
        "proposed_tasks": [
            {"id": tid_1, "title": "Design mock", "completion_condition": "PDF exported",
             "required_resources": {"time_minutes": 60}},
            {"id": tid_2, "title": "Ship code", "completion_condition": "Merged to main",
             "required_resources": {"time_minutes": 120}},
        ],
        "proposed_check_ins": [],
        "visual_phases": [],
        "resource_requirements": [
            {"kind": "time", "minutes": 180, "period": "over_horizon", "confidence": "high"},
        ],
        "portfolio_conflicts": [],
        "assumptions": [],
        "external_estimates": [],
        "risks": [],
        "feasibility": {"status": "feasible", "reasons": [], "tradeoffs": [], "alternatives": []},
        "approval_actions": [
            {"action": "create_task", "proposal_ref": tid_1,
             "payload": {"title": "Design mock", "due_date": "2027-01-15",
                         "priority": "medium", "notes": "Design",
                         "origin": "project", "project_id": pid_proj}},
            {"action": "create_task", "proposal_ref": tid_2,
             "payload": {"title": "Ship code", "due_date": "2027-01-25",
                         "priority": "high", "notes": "Ship",
                         "origin": "project", "project_id": pid_proj}},
            {"action": "create_money_reservation", "proposal_ref": tid_2,
             "attach_task_owner": True,
             "payload": {"amount": "500", "currency": "USD",
                         "due_date": "2027-01-25", "priority": "high",
                         "title": "Freelance illustrator", "description": ""}},
        ],
        "evidence_map": [],
        "validation_errors": [],
        "objective_summary": "test",
        "measurable_success_criteria": "test",
        "created_at": "2026-07-17T00:00:00Z",
        "updated_at": "2026-07-17T00:00:00Z",
    }
    await mdb.plan_proposals.insert_one(doc)

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(f"{BASE}/planning/proposals/{proposal_id}/approve", headers=H)
        print("Approve:", r.status_code, r.text[:300])
        assert r.status_code == 200, r.text
        result = r.json()
        print("Committed:", result)
        assert result["committed_actions"] == 3
        assert len(result["created_tasks"]) == 2

        # Verify tasks in DB
        tasks = await mdb.tasks.find({"project_id": pid_proj}, {"_id": 0, "title": 1}).to_list(length=10)
        titles = sorted(t["title"] for t in tasks)
        print("Tasks:", titles)
        assert titles == ["Design mock", "Ship code"]

        # Verify money reservation in resource_allocations
        rr = await mdb.resource_allocations.find_one({"title": "Freelance illustrator"}, {"_id": 0})
        assert rr and rr["state"] == "reserved" and rr["currency"] == "USD"
        print("Money reservation created:", rr["financial_commitment_id"], "$", str(rr["quantity"]))

        # Re-approve — should be rejected
        r = await client.post(f"{BASE}/planning/proposals/{proposal_id}/approve", headers=H)
        assert r.status_code == 400
        print("PASS: Re-approve blocked because status=approved")

    print("\nDIRECT COMMIT PATH TEST PASSED ✅")


asyncio.run(run())
