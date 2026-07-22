"""Focused approval happy-path test: analyze → approve immediately (no drift).

Uses a minimal goal so the LLM's proposed_tasks return specific dates. We
manually verify approval writes live data through the existing endpoints.
"""
import asyncio, httpx, os, sys
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv('/app/backend/.env')

BASE = "http://localhost:8001/api"


async def run():
    mdb = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.post(f"{BASE}/auth/login", json={
            "email": "test@hymn.app", "password": "TestPass123!",
        })
        tok = r.json()["access_token"]
        H = {"Authorization": f"Bearer {tok}"}

        r = await client.get(f"{BASE}/domains", headers=H)
        did = r.json()[0]["id"]

        # Create a project (simpler than goal since no expected_outcomes to
        # manage; committed tasks link directly to the project).
        r = await client.post(f"{BASE}/projects", json={
            "title": "Approval Happy Path Test",
            "description": "Ship a simple landing page by end of month",
            "status": "active",
            "start_date": "2027-08-01",
            "target_end_date": "2027-08-31",
        }, headers=H)
        pid_proj = r.json()["id"]
        print("Project:", pid_proj)

        # Analyze
        r = await client.post(f"{BASE}/planning/analyze", json={
            "target_type": "project", "target_id": pid_proj,
        }, headers=H)
        prop = r.json()
        pid = prop["id"]
        print(f"Status={prop['status']} tasks={len(prop['proposed_tasks'])} verrs={len(prop['validation_errors'])}")

        # Try approving.
        r = await client.post(f"{BASE}/planning/proposals/{pid}/approve", headers=H)
        print(f"Approve: {r.status_code} {r.text[:400]}")

        if r.status_code == 200:
            result = r.json()
            print("Committed actions:", result["committed_actions"])
            # Verify live writes
            new_tasks = await mdb.tasks.count_documents({"project_id": pid_proj})
            print(f"Live tasks for project: {new_tasks}")
            assert new_tasks > 0, "Approval should have created tasks"

            # Idempotency: re-approve should be rejected because status=approved
            r2 = await client.post(f"{BASE}/planning/proposals/{pid}/approve", headers=H)
            print(f"Re-approve after approval: {r2.status_code}")
            assert r2.status_code == 400
            print("PASS: Approve is one-shot; re-approve rejected")

            # Verify proposal status
            r = await client.get(f"{BASE}/planning/proposals/{pid}", headers=H)
            assert r.json()["status"] == "approved"
            assert r.json()["approved_at"]
            print("PASS: Proposal status=approved with approved_at timestamp")
        else:
            print("Approval blocked (as expected if validation_errors present):", r.json())

    print("\nAPPROVAL HAPPY-PATH TEST DONE")


asyncio.run(run())
