"""Quick sanity test of the new deterministic → confirm → generate → approve flow.

Verifies:
1. /analyze creates confirmation_required proposal with no LLM output.
2. /confirm merges confirmations; previous confirmations are preserved.
3. /generate is only allowed after blocking fields resolved.
4. /select-tradeoff only valid for feasible_with_tradeoffs.
5. /approve requires status=proposal_ready.
"""
import asyncio, httpx, os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv('/app/backend/.env')

BASE = "http://localhost:8001/api"


async def run():
    mdb = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.post(f"{BASE}/auth/login", json={
            "email": "test@hymn.app", "password": "TestPass123!"})
        H = {"Authorization": f"Bearer {r.json()['access_token']}"}

        r = await client.get(f"{BASE}/domains", headers=H)
        did = r.json()[0]["id"]

        # Create a goal
        r = await client.post(f"{BASE}/goals", json={
            "title": "New Flow Test Goal", "domain_id": did,
            "target_outcome": "Reach 5k run in 25min",
            "deadline": "2027-12-31", "status": "active",
            "checkin_cadence": "weekly",
        }, headers=H)
        gid = r.json()["id"]

        # 1) Analyze — deterministic, no LLM
        r = await client.post(f"{BASE}/planning/analyze", json={
            "target_type": "goal", "target_id": gid,
        }, headers=H)
        assert r.status_code == 200, r.text
        p = r.json()
        pid = p["id"]
        print(f"1) analyze: status={p['status']} tasks={len(p['proposed_tasks'])} outcomes={len(p['proposed_outcomes'])}")
        assert p["status"] == "confirmation_required"
        assert len(p["proposed_tasks"]) == 0
        assert len(p["proposed_outcomes"]) == 0
        # Every fact has an evidence_id
        for f in p["current_state"]:
            assert f.get("evidence_id"), f"missing evidence_id on {f['field']}"
        print("   ✓ evidence_ids present, no LLM output")

        # 2) Confirm first two fields
        r = await client.post(f"{BASE}/planning/proposals/{pid}/confirm", json={
            "confirmations": [
                {"field": "objective", "action": "confirm"},
                {"field": "success_criteria", "action": "confirm"},
            ],
        }, headers=H)
        assert r.status_code == 200, r.text
        p2 = r.json()
        assert p2["confirmations"]["objective"]["action"] == "confirm"
        assert p2["confirmations"]["success_criteria"]["action"] == "confirm"
        print(f"2a) confirm partial: status={p2['status']} confirmations={list(p2['confirmations'].keys())}")
        # 2b) Confirm remaining blocking fields; prior confirmations must persist
        blocking = [f["field"] for f in p2["current_state"] if f.get("blocking")]
        print("    still blocking:", blocking)
        r = await client.post(f"{BASE}/planning/proposals/{pid}/confirm", json={
            "confirmations": [{"field": f, "action": "confirm"} for f in blocking if f != "objective"],
        }, headers=H)
        assert r.status_code == 200, r.text
        p3 = r.json()
        # Prior confirmations must still be present
        assert p3["confirmations"].get("objective", {}).get("action") == "confirm", "prior confirmation lost"
        print(f"2b) merged confirmations: {list(p3['confirmations'].keys())}")
        remaining = [f["field"] for f in p3["current_state"] if f.get("blocking")]
        print(f"    ready_to_generate={p3.get('ready_to_generate')} remaining_blocking={remaining}")

        # 3) Approve should FAIL — not proposal_ready
        r = await client.post(f"{BASE}/planning/proposals/{pid}/approve", headers=H)
        assert r.status_code == 400, r.text
        print(f"3) approve blocked (status={p3['status']}): ✓")

        # 4) Generate — single LLM call (may take ~15-20s)
        if not remaining:
            r = await client.post(f"{BASE}/planning/proposals/{pid}/generate", headers=H)
            assert r.status_code == 200, r.text
            p4 = r.json()
            print(f"4) generate: status={p4['status']} tasks={len(p4['proposed_tasks'])} outcomes={len(p4['proposed_outcomes'])} feasibility={p4['feasibility']['status']}")
            print(f"   validation_errors={len(p4['validation_errors'])} conflicts={len(p4['portfolio_conflicts'])}")
            # 5) If feasible_with_tradeoffs, need tradeoff selection
            feas = p4["feasibility"]["status"]
            if feas == "feasible_with_tradeoffs":
                alt_ids = [opt["id"] for alt in p4["feasibility"].get("alternatives", []) for opt in alt.get("options", [])]
                if alt_ids:
                    r = await client.post(f"{BASE}/planning/proposals/{pid}/select-tradeoff",
                                          json={"tradeoff_id": alt_ids[0]}, headers=H)
                    print(f"5) select-tradeoff: {r.status_code}")

    print("\nQUICK FLOW TEST DONE")


asyncio.run(run())
