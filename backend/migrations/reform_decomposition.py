"""One-shot migration for the Decomposition Engine reform.

Actions (idempotent for missing collections; destructive for collection docs):

1. For every ``knowledge_journeys`` doc:
     * copy ``journey_type`` onto the referenced Goal (new nullable field).
     * for each ``knowledge_stages`` row (ordered by sequence) → create an
       ``expected_outcomes`` row on the same Goal (title = stage.name,
       status="active"). Retain a mapping stage_id → new_eo_id.
     * for each ``knowledge_components`` row → create a ``tasks`` row under
       the Goal's expected_outcome (either the migrated stage or the goal's
       first EO). Preserves ordering by ``sequence``. Parent/child hierarchy
       captured in the task's notes for reference; deep nesting is flattened
       (Hymn tasks don't currently model tree structure).
2. Detach every existing task/checkin whose ``component_id`` is set (safe
   nullification — data is preserved).
3. Delete every doc in ``knowledge_journeys``, ``knowledge_stages`` and
   ``knowledge_components``.
4. Archive every existing ``plan_proposals`` row (set status="archived").

Run once with::

    python -m backend.migrations.reform_decomposition
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from typing import Dict, List

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _migrate_one_journey(db, journey: dict) -> Dict[str, int]:
    """Migrate a single knowledge_journey doc. Returns per-journey counters."""
    stats = {"outcomes": 0, "tasks": 0}
    user_id = journey["user_id"]
    goal_id = journey.get("goal_id")
    if not goal_id:
        return stats

    goal = await db.goals.find_one({"id": goal_id, "user_id": user_id}, {"_id": 0})
    if not goal:
        return stats

    now = _now()

    # 1. Copy journey_type on the goal.
    if journey.get("journey_type"):
        await db.goals.update_one(
            {"id": goal_id, "user_id": user_id},
            {"$set": {"journey_type": journey["journey_type"], "updated_at": now}},
        )

    # 2. Load stages ordered by sequence.
    stages = await db.knowledge_stages.find(
        {"user_id": user_id, "journey_id": journey["id"]}, {"_id": 0},
    ).to_list(length=1000)
    stages.sort(key=lambda s: int(s.get("sequence", 0)))

    stage_to_eo: Dict[str, str] = {}
    for stage in stages:
        eo_id = str(uuid.uuid4())
        await db.expected_outcomes.insert_one({
            "id": eo_id, "user_id": user_id, "goal_id": goal_id,
            "title": stage.get("name", "Stage").strip(),
            "target_value": "", "current_value": "", "unit": "",
            "deadline": "", "status": "active", "notes": "",
            "outcome_type": "generic",
            "created_at": now, "updated_at": now,
        })
        stage_to_eo[stage["id"]] = eo_id
        stats["outcomes"] += 1

    # Fallback expected_outcome — if there are components but no stages, we
    # need one to hang tasks off of.
    fallback_eo_id = None
    components = await db.knowledge_components.find(
        {"user_id": user_id, "journey_id": journey["id"]}, {"_id": 0},
    ).to_list(length=5000)
    components.sort(key=lambda c: int(c.get("sequence", 0)))
    if components and not stages:
        existing = await db.expected_outcomes.find_one(
            {"user_id": user_id, "goal_id": goal_id}, {"_id": 0},
        )
        if existing:
            fallback_eo_id = existing["id"]
        else:
            fallback_eo_id = str(uuid.uuid4())
            await db.expected_outcomes.insert_one({
                "id": fallback_eo_id, "user_id": user_id, "goal_id": goal_id,
                "title": "Learning components",
                "target_value": "", "current_value": "", "unit": "",
                "deadline": "", "status": "active", "notes": "",
                "outcome_type": "generic",
                "created_at": now, "updated_at": now,
            })
            stats["outcomes"] += 1

    # 3. Build a parent map for hierarchy note.
    comp_by_id = {c["id"]: c for c in components}

    def _lineage(cid: str) -> str:
        chain: List[str] = []
        seen = set()
        cur = cid
        while cur and cur not in seen:
            seen.add(cur)
            c = comp_by_id.get(cur)
            if not c:
                break
            chain.append(c.get("name", "Component"))
            cur = c.get("parent_component_id")
        return " › ".join(reversed(chain[1:])) if len(chain) > 1 else ""

    for comp in components:
        eo_id = stage_to_eo.get(comp.get("stage_id") or "") or fallback_eo_id
        if not eo_id:
            continue  # Extremely rare — component with no stage and no fallback.
        lineage = _lineage(comp["id"])
        notes_bits = []
        if lineage:
            notes_bits.append(f"Path: {lineage}")
        if comp.get("notes"):
            notes_bits.append(comp["notes"])
        task_id = str(uuid.uuid4())
        await db.tasks.insert_one({
            "id": task_id, "user_id": user_id,
            "title": comp.get("name", "Component").strip(),
            "due_date": "", "priority": "medium",
            "status": "done" if comp.get("status") == "completed" else "todo",
            "notes": "\n\n".join(notes_bits),
            "origin": "expected_outcome",
            "expected_outcome_id": eo_id,
            "project_id": None, "component_id": None,
            "assigned_to_type": "self", "assigned_to_name": "", "assigned_to_phone": "",
            "created_at": now, "updated_at": now,
        })
        stats["tasks"] += 1

    return stats


async def run() -> Dict[str, int]:
    mongo_url = os.environ.get("MONGO_URL") or "mongodb://localhost:27017"
    db_name = os.environ.get("DB_NAME") or "test_database"
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    total = {
        "journeys": 0, "outcomes": 0, "tasks": 0,
        "detached_tasks": 0, "detached_checkins": 0,
        "archived_proposals": 0,
    }

    # 1. Migrate journeys.
    journeys = await db.knowledge_journeys.find({}, {"_id": 0}).to_list(length=10000)
    for journey in journeys:
        try:
            per = await _migrate_one_journey(db, journey)
            total["outcomes"] += per["outcomes"]
            total["tasks"] += per["tasks"]
            total["journeys"] += 1
        except Exception as exc:  # pragma: no cover
            print(f"[warn] failed to migrate journey {journey.get('id')}: {exc}")

    # 2. Detach tasks/checkins that referenced components — they still exist
    # under the goal by another route, they just no longer reference deleted
    # collections.
    if journeys:
        r1 = await db.tasks.update_many(
            {"component_id": {"$ne": None, "$exists": True}},
            {"$set": {"component_id": None}},
        )
        r2 = await db.checkins.update_many(
            {"component_id": {"$ne": None, "$exists": True}},
            {"$set": {"component_id": None}},
        )
        total["detached_tasks"] = int(getattr(r1, "modified_count", 0) or 0)
        total["detached_checkins"] = int(getattr(r2, "modified_count", 0) or 0)

    # 3. Delete the parallel-planning collections (destructive per user choice).
    await db.knowledge_components.delete_many({})
    await db.knowledge_stages.delete_many({})
    await db.knowledge_journeys.delete_many({})

    # 4. Archive all legacy plan_proposals.
    r3 = await db.plan_proposals.update_many(
        {"status": {"$ne": "archived"}},
        {"$set": {"status": "archived", "archived_at": _now()}},
    )
    total["archived_proposals"] = int(getattr(r3, "modified_count", 0) or 0)

    client.close()
    return total


if __name__ == "__main__":
    print(asyncio.run(run()))
