"""Manual Goal Merge wizard — server side.

Two endpoints attached to the ``planning`` router:

* ``POST /api/planning/merge/preview``  → analyze the requested goals and
  return a proposed merger plan (LLM-assisted where possible, deterministic
  richness score as the ultimate tiebreaker) alongside duplicate hints
  and a capacity impact report.
* ``POST /api/planning/merge/apply``     → execute the plan the user
  approved. Reparent surviving outcomes + their tasks + check-ins onto
  the survivor goal; convert "nest" outcomes into tasks under the
  parent outcome (their check-ins are re-anchored to the survivor
  goal but retain their expected_outcome_id, which now points to the
  survivor). Deletes duplicates the user explicitly ticked. Deletes
  the loser goals last. Also applies user-approved postpone/cancel
  actions on other portfolio items when a capacity conflict was
  detected.

Never touches items whose ``commitment_type == 'exclusive'``.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from deps import get_current_user, get_db

# Reuse helpers + router from the conversational engine.
from planning_engine import (
    _iso_date, _now, _uuid,
    _richness_score, _is_exclusive,
    VALID_COMMITMENT_TYPES,
    VALID_GOAL_STATUSES, VALID_PROJECT_STATUSES, VALID_TASK_STATUSES,
    planning_router,
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class MergePreviewRequest(BaseModel):
    goal_ids: List[str] = Field(min_length=2, max_length=8)


class NestingRule(BaseModel):
    outcome_id: str
    action: str  # "keep" | "nest" | "delete"
    parent_outcome_id: Optional[str] = None  # required when action == "nest"


class TradeoffAction(BaseModel):
    kind: str  # "goal" | "project" | "task"
    id: str
    action: str  # "postpone" | "cancel"
    new_due_date: Optional[str] = None


class MergeApplyRequest(BaseModel):
    goal_ids: List[str] = Field(min_length=2, max_length=8)
    survivor_id: str
    outcome_rules: List[NestingRule] = []
    delete_duplicate_ids: List[str] = []
    tradeoffs: List[TradeoffAction] = []


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _norm_title(v: str) -> str:
    return re.sub(r"\s+", " ", (v or "").strip().lower())


async def _load_goal_bundle(db, user_id: str, goal_id: str) -> Optional[Dict[str, Any]]:
    goal = await db.goals.find_one({"id": goal_id, "user_id": user_id}, {"_id": 0})
    if not goal:
        return None
    outcomes = await db.expected_outcomes.find(
        {"goal_id": goal_id, "user_id": user_id}, {"_id": 0},
    ).to_list(length=500)
    outcome_ids = [e["id"] for e in outcomes]
    tasks = await db.tasks.find(
        {"expected_outcome_id": {"$in": outcome_ids}, "user_id": user_id}, {"_id": 0},
    ).to_list(length=2000) if outcome_ids else []
    checkins_count = await db.checkins.count_documents(
        {"goal_id": goal_id, "user_id": user_id},
    )
    return {"goal": goal, "outcomes": outcomes, "tasks": tasks, "checkins_count": checkins_count}


def _duplicate_pairs(all_outcomes: List[Dict[str, Any]]) -> List[List[str]]:
    """Naive duplicate detection by normalized title match across the pool."""
    buckets: Dict[str, List[str]] = {}
    for e in all_outcomes:
        buckets.setdefault(_norm_title(e.get("title") or ""), []).append(e["id"])
    return [ids for ids in buckets.values() if len(ids) > 1]


def _minutes_of_commitments(commitments: List[dict]) -> int:
    def _m(hhmm: str) -> int:
        try:
            h, m = hhmm.split(":")
            return int(h) * 60 + int(m)
        except Exception:
            return 0
    total = 0
    for tc in commitments:
        total += max(0, _m(tc.get("end_time", "0:0")) - _m(tc.get("start_time", "0:0")))
    return total


async def _capacity_snapshot(db, user_id: str) -> Dict[str, Any]:
    today = datetime.now(timezone.utc).date().isoformat()
    tcs = await db.time_commitments.find(
        {"user_id": user_id, "effective_from": {"$lte": today}}, {"_id": 0},
    ).to_list(length=1000)
    tcs = [t for t in tcs if not t.get("effective_until") or t["effective_until"] >= today]
    committed_min = _minutes_of_commitments(tcs)
    open_tasks = await db.tasks.count_documents({
        "user_id": user_id, "status": {"$nin": ["done", "cancelled"]},
    })
    active_goals = await db.goals.count_documents({
        "user_id": user_id, "status": "active",
    })
    active_projects = await db.projects.count_documents({
        "user_id": user_id, "status": "active",
    })
    return {
        "committed_hours_per_week": round(committed_min / 60.0, 1),
        "free_hours_per_week_estimate": max(0.0, round(168 - committed_min / 60.0, 1)),
        "active_goals": active_goals,
        "active_projects": active_projects,
        "open_tasks": open_tasks,
    }


def _capacity_conflicts(snapshot: Dict[str, Any], new_open_task_count: int) -> List[Dict[str, Any]]:
    """Simple heuristic: after merger we still have all the tasks from all
    goals (nothing deleted), so open workload changes only when the user
    explicitly cancels/postpones something. This function surfaces an
    advisory conflict when the current portfolio is already stretched.

    We flag a conflict when free_hours_per_week_estimate < 8 (i.e. less
    than one hour a day) AND active_goals + active_projects > 10, on the
    assumption that a merger doesn't reduce workload — it consolidates
    metadata. The block is advisory: the wizard treats it as a hard
    block per user's request until they add tradeoffs."""
    conflicts: List[Dict[str, Any]] = []
    free = snapshot.get("free_hours_per_week_estimate", 168)
    total_active = snapshot.get("active_goals", 0) + snapshot.get("active_projects", 0)
    if free < 8:
        conflicts.append({
            "type": "time",
            "detail": f"Only ~{free}h/week free after existing recurring commitments. Consider postponing / cancelling something before consolidating.",
        })
    if total_active > 10:
        conflicts.append({
            "type": "portfolio_breadth",
            "detail": f"{total_active} active goals + projects — merging tightens metadata but not workload. Consider closing out completed items first.",
        })
    return conflicts


# ---------------------------------------------------------------------------
# LLM-assisted plan generation (best-effort; falls back to a deterministic
# scaffold if the LLM is unavailable).
# ---------------------------------------------------------------------------


_MERGE_SYSTEM_PROMPT = """You are Hymn's Goal Merge planner. The user has picked N
goals they consider duplicates. You will be shown each goal's title,
notes, and its expected outcomes. Propose a MERGER PLAN:

1) survivor_goal_id: pick the goal whose title/notes/outcomes are the
   most complete and specific. If none is obviously better, pick the
   one with the most detailed outcomes.
2) For every outcome in every goal, choose ONE action:
   - "keep": retains the outcome on the survivor, at the top level.
   - "nest": nest this outcome UNDER another outcome (identified by
     parent_outcome_id from any of the goals) because it's a more
     detailed sub-plan of that outcome.
   - "delete": the outcome is a duplicate of another — mark it for
     deletion. Only use this when the titles clearly refer to the same
     thing (case-insensitive after trimming punctuation).
3) Prefer nesting over deleting. Never delete an outcome that carries
   unique information.
4) When two outcomes look like duplicates, keep the one with more
   attached tasks or a more specific title (e.g. "Complete first-pass
   study of all 6 CA Final papers" is more specific than
   "Study all subjects").

Respond ONLY with a single JSON object on one line:
{"survivor_goal_id": "<id>",
 "outcome_rules": [
   {"outcome_id": "<id>", "action": "keep|nest|delete",
    "parent_outcome_id": "<other outcome id if nest else null>",
    "reason": "one short line"}
 ]}

No prose. No code fences. If you cannot decide for an outcome, default
to action='keep' with parent_outcome_id=null."""


async def _llm_merge_plan(bundles: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Ask the LLM for a plan. Returns parsed plan dict or None on any error."""
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        return None
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage  # noqa
    except Exception:
        return None
    payload_bits: List[str] = []
    for b in bundles:
        g = b["goal"]
        payload_bits.append(
            f"GOAL id={g['id']} title={g.get('title')!r} "
            f"notes={(g.get('notes') or '')[:200]!r} "
            f"deadline={g.get('deadline') or '—'} "
            f"outcomes={len(b['outcomes'])} tasks={len(b['tasks'])} "
            f"checkins={b['checkins_count']}"
        )
        for e in b["outcomes"]:
            attached_tasks = sum(1 for t in b["tasks"] if t.get("expected_outcome_id") == e["id"])
            payload_bits.append(
                f"  OUTCOME id={e['id']} goal_id={g['id']} title={e.get('title')!r} "
                f"target={e.get('target_value') or '—'} unit={e.get('unit') or '—'} "
                f"attached_tasks={attached_tasks}"
            )
    user_text = "Goals & outcomes to merge:\n" + "\n".join(payload_bits)
    try:
        chat = LlmChat(
            api_key=api_key,
            session_id=f"merge-{uuid.uuid4().hex[:8]}",
            system_message=_MERGE_SYSTEM_PROMPT,
        ).with_model("anthropic", "claude-sonnet-4-6")
        response = await chat.send_message(UserMessage(text=user_text))
        raw = (response or "").strip()
        # Strip any accidental code fences.
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and "outcome_rules" in parsed:
            return parsed
    except Exception:
        return None
    return None


def _fallback_plan(bundles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Deterministic fallback: richest goal survives, every outcome keeps."""
    # bundles are sorted by richness descending outside.
    survivor = bundles[0]["goal"]["id"] if bundles else ""
    rules: List[Dict[str, Any]] = []
    for b in bundles:
        for e in b["outcomes"]:
            rules.append({
                "outcome_id": e["id"], "action": "keep",
                "parent_outcome_id": None,
                "reason": "kept by default",
            })
    return {"survivor_goal_id": survivor, "outcome_rules": rules}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@planning_router.post("/merge/preview")
async def merge_preview(
    body: MergePreviewRequest,
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    user_id = current_user["id"]

    # Load all goal bundles.
    bundles: List[Dict[str, Any]] = []
    for gid in body.goal_ids:
        b = await _load_goal_bundle(db, user_id, gid)
        if not b:
            raise HTTPException(status_code=404, detail=f"Goal not found: {gid}")
        if _is_exclusive(b["goal"]):
            raise HTTPException(
                status_code=400,
                detail=f"Goal '{b['goal'].get('title')}' is marked exclusive and cannot be merged.",
            )
        bundles.append(b)

    # Deterministic richness ranking (used as tie-break AND fallback survivor).
    scored: List[Tuple[int, str, dict]] = []
    for b in bundles:
        s = await _richness_score(db, user_id, "goal", b["goal"])
        scored.append((s, b["goal"].get("created_at", ""), b))
    scored.sort(key=lambda x: (-x[0], x[1]))
    ordered_bundles = [b for _, _, b in scored]

    # LLM plan (best-effort).
    llm_plan = await _llm_merge_plan(ordered_bundles)
    plan = llm_plan or _fallback_plan(ordered_bundles)

    # Sanity: survivor must be one of the provided goals.
    survivor_id = plan.get("survivor_goal_id") or ordered_bundles[0]["goal"]["id"]
    if survivor_id not in {b["goal"]["id"] for b in bundles}:
        survivor_id = ordered_bundles[0]["goal"]["id"]

    # Validate every rule refers to a real outcome; drop stragglers.
    all_outcome_ids = {e["id"]: e for b in bundles for e in b["outcomes"]}
    rules: List[Dict[str, Any]] = []
    for r in plan.get("outcome_rules", []) or []:
        oid = r.get("outcome_id")
        if oid not in all_outcome_ids:
            continue
        action = (r.get("action") or "keep").lower()
        if action not in ("keep", "nest", "delete"):
            action = "keep"
        parent = r.get("parent_outcome_id") or None
        if action == "nest" and (not parent or parent == oid or parent not in all_outcome_ids):
            # Can't nest under nothing / itself — downgrade to keep.
            action = "keep"
            parent = None
        rules.append({
            "outcome_id": oid,
            "action": action,
            "parent_outcome_id": parent,
            "reason": r.get("reason") or "",
        })
    # Any outcome missing a rule → default to keep.
    seen = {r["outcome_id"] for r in rules}
    for oid in all_outcome_ids:
        if oid not in seen:
            rules.append({
                "outcome_id": oid, "action": "keep",
                "parent_outcome_id": None, "reason": "default",
            })

    # Duplicate hints (title-based).
    duplicates = _duplicate_pairs(list(all_outcome_ids.values()))

    # Capacity snapshot + conflicts.
    snapshot = await _capacity_snapshot(db, user_id)
    conflicts = _capacity_conflicts(snapshot, snapshot["open_tasks"])

    # Rich payload for the client — includes goal + outcome + task details
    # so the client can render everything without an extra round-trip.
    outcome_payload: List[Dict[str, Any]] = []
    for e in all_outcome_ids.values():
        parent_goal = next(
            (b["goal"] for b in bundles if any(oo["id"] == e["id"] for oo in b["outcomes"])),
            None,
        )
        attached = [
            {"id": t["id"], "title": t["title"], "status": t["status"], "due_date": t.get("due_date")}
            for b in bundles for t in b["tasks"]
            if t.get("expected_outcome_id") == e["id"]
        ]
        outcome_payload.append({
            "id": e["id"], "title": e.get("title"),
            "target_value": e.get("target_value"), "unit": e.get("unit"),
            "deadline": e.get("deadline"), "notes": (e.get("notes") or "")[:400],
            "source_goal_id": e["goal_id"],
            "source_goal_title": parent_goal.get("title") if parent_goal else "",
            "attached_tasks": attached,
        })

    return {
        "survivor_id": survivor_id,
        "goals": [
            {"id": b["goal"]["id"], "title": b["goal"].get("title"),
             "notes": (b["goal"].get("notes") or "")[:400],
             "deadline": b["goal"].get("deadline"),
             "status": b["goal"].get("status"),
             "richness_score": next((s for s, _, bb in scored if bb["goal"]["id"] == b["goal"]["id"]), 0),
             "outcome_count": len(b["outcomes"]),
             "task_count": len(b["tasks"]),
             "checkins_count": b["checkins_count"]}
            for b in bundles
        ],
        "outcomes": outcome_payload,
        "outcome_rules": rules,
        "duplicates": duplicates,
        "capacity_snapshot": snapshot,
        "capacity_conflicts": conflicts,
    }


@planning_router.post("/merge/apply")
async def merge_apply(
    body: MergeApplyRequest,
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    user_id = current_user["id"]
    now = _now()

    if body.survivor_id not in body.goal_ids:
        raise HTTPException(status_code=400, detail="survivor_id must be one of goal_ids")

    # Reload bundles.
    bundles: List[Dict[str, Any]] = []
    for gid in body.goal_ids:
        b = await _load_goal_bundle(db, user_id, gid)
        if not b:
            raise HTTPException(status_code=404, detail=f"Goal not found: {gid}")
        if _is_exclusive(b["goal"]):
            raise HTTPException(status_code=400, detail="Cannot merge an exclusive goal.")
        bundles.append(b)

    all_outcomes = {e["id"]: e for b in bundles for e in b["outcomes"]}
    rules_by_id = {r.outcome_id: r for r in body.outcome_rules}

    # Refuse if a nesting rule points to an outcome that will itself be deleted.
    for r in body.outcome_rules:
        if r.action == "nest" and r.parent_outcome_id in {r2.outcome_id for r2 in body.outcome_rules if r2.action == "delete"}:
            raise HTTPException(status_code=400, detail=f"Outcome {r.outcome_id} cannot nest under a deleted parent.")

    # Refuse if capacity conflicts exist and no tradeoffs supplied.
    snapshot = await _capacity_snapshot(db, user_id)
    conflicts = _capacity_conflicts(snapshot, snapshot["open_tasks"])
    if conflicts and not body.tradeoffs:
        raise HTTPException(
            status_code=409,
            detail={"message": "Capacity conflicts must be resolved before merging.",
                    "conflicts": conflicts},
        )

    # Apply user-approved tradeoffs first.
    applied_tradeoffs: List[Dict[str, Any]] = []
    for t in body.tradeoffs:
        if t.kind not in ("goal", "project", "task"):
            continue
        coll = {"goal": "goals", "project": "projects", "task": "tasks"}[t.kind]
        doc = await db[coll].find_one({"id": t.id, "user_id": user_id}, {"_id": 0})
        if not doc or _is_exclusive(doc):
            continue
        patch = {"updated_at": now}
        if t.action == "postpone":
            due = _iso_date(t.new_due_date) if t.new_due_date else None
            if not due:
                continue
            if t.kind == "goal":
                patch.update({"deadline": due, "status": "paused"})
            elif t.kind == "project":
                patch.update({"target_end_date": due, "status": "paused"})
            else:
                patch.update({"due_date": due})
        elif t.action == "cancel":
            patch["status"] = "cancelled" if t.kind == "task" else "abandoned"
        else:
            continue
        await db[coll].update_one({"id": t.id, "user_id": user_id}, {"$set": patch})
        applied_tradeoffs.append({"kind": t.kind, "id": t.id, "action": t.action})

    survivor_id = body.survivor_id
    losers = [b["goal"]["id"] for b in bundles if b["goal"]["id"] != survivor_id]
    reparented_outcomes: List[str] = []
    nested_as_tasks: List[str] = []
    deleted_outcomes: List[str] = []
    deleted_duplicates: List[str] = []

    # Process outcomes.
    for oid, eo in all_outcomes.items():
        rule = rules_by_id.get(oid)
        action = rule.action if rule else "keep"
        parent = rule.parent_outcome_id if rule else None

        if action == "delete":
            # Detach tasks + reparent-to-survivor checkins so we don't
            # orphan history, then delete the outcome.
            await db.checkins.update_many(
                {"expected_outcome_id": oid, "user_id": user_id},
                {"$set": {"goal_id": survivor_id, "expected_outcome_id": None, "updated_at": now}},
            )
            await db.tasks.update_many(
                {"expected_outcome_id": oid, "user_id": user_id},
                {"$set": {"expected_outcome_id": None, "origin": "standalone", "updated_at": now}},
            )
            await db.expected_outcomes.delete_one({"id": oid, "user_id": user_id})
            deleted_outcomes.append(oid)
            continue

        if action == "nest" and parent and parent in all_outcomes and parent != oid:
            # Convert this outcome into a task under `parent` and re-anchor
            # its check-ins to the survivor goal (they keep their EO link
            # to the parent outcome after we retarget below).
            task_id = _uuid()
            await db.tasks.insert_one({
                "id": task_id, "user_id": user_id,
                "title": eo.get("title") or "Task",
                "due_date": eo.get("deadline") or "",
                "priority": "medium", "status": "todo",
                "notes": (eo.get("notes") or "") + ("\n\n" if eo.get("notes") else "") +
                         f"Nested from outcome (merge).",
                "origin": "expected_outcome",
                "expected_outcome_id": parent,
                "project_id": None, "component_id": None,
                "assigned_to_type": "self", "assigned_to_name": "", "assigned_to_phone": "",
                "commitment_type": "postponable",
                "created_at": now, "updated_at": now,
            })
            # Any tasks under the old outcome move to the parent outcome
            # too (they become peers of our new task under `parent`).
            await db.tasks.update_many(
                {"expected_outcome_id": oid, "user_id": user_id},
                {"$set": {"expected_outcome_id": parent, "updated_at": now}},
            )
            # Check-ins move to the survivor goal AND retarget to parent.
            await db.checkins.update_many(
                {"expected_outcome_id": oid, "user_id": user_id},
                {"$set": {"goal_id": survivor_id, "expected_outcome_id": parent, "updated_at": now}},
            )
            await db.expected_outcomes.delete_one({"id": oid, "user_id": user_id})
            nested_as_tasks.append(task_id)
            continue

        # action == "keep" (default): reparent to survivor if not already.
        if eo.get("goal_id") != survivor_id:
            await db.expected_outcomes.update_one(
                {"id": oid, "user_id": user_id},
                {"$set": {"goal_id": survivor_id, "updated_at": now}},
            )
            await db.checkins.update_many(
                {"expected_outcome_id": oid, "user_id": user_id},
                {"$set": {"goal_id": survivor_id, "updated_at": now}},
            )
            reparented_outcomes.append(oid)

    # Apply explicit duplicate deletions (any outcome id the user ticked).
    for oid in body.delete_duplicate_ids:
        if oid in deleted_outcomes:
            continue
        eo = all_outcomes.get(oid)
        if not eo:
            continue
        # Detach tasks + retarget any check-ins to the survivor's other
        # outcome that has the same title if any, else just null-out.
        same_title = next(
            (e for e in all_outcomes.values()
             if e["id"] != oid and _norm_title(e.get("title") or "") == _norm_title(eo.get("title") or "")),
            None,
        )
        if same_title:
            await db.checkins.update_many(
                {"expected_outcome_id": oid, "user_id": user_id},
                {"$set": {"goal_id": survivor_id, "expected_outcome_id": same_title["id"], "updated_at": now}},
            )
            await db.tasks.update_many(
                {"expected_outcome_id": oid, "user_id": user_id},
                {"$set": {"expected_outcome_id": same_title["id"], "updated_at": now}},
            )
        else:
            await db.checkins.update_many(
                {"expected_outcome_id": oid, "user_id": user_id},
                {"$set": {"goal_id": survivor_id, "expected_outcome_id": None, "updated_at": now}},
            )
            await db.tasks.update_many(
                {"expected_outcome_id": oid, "user_id": user_id},
                {"$set": {"expected_outcome_id": None, "origin": "standalone", "updated_at": now}},
            )
        await db.expected_outcomes.delete_one({"id": oid, "user_id": user_id})
        deleted_duplicates.append(oid)

    # Move any leftover tasks/checkins/outcomes still pointing at a
    # loser goal onto the survivor.
    await db.expected_outcomes.update_many(
        {"goal_id": {"$in": losers}, "user_id": user_id},
        {"$set": {"goal_id": survivor_id, "updated_at": now}},
    )
    await db.checkins.update_many(
        {"goal_id": {"$in": losers}, "user_id": user_id},
        {"$set": {"goal_id": survivor_id, "updated_at": now}},
    )

    # Merge notes and delete the losers.
    survivor_doc = await db.goals.find_one({"id": survivor_id, "user_id": user_id}, {"_id": 0})
    merged_notes = (survivor_doc.get("notes") or "").strip() if survivor_doc else ""
    for b in bundles:
        if b["goal"]["id"] == survivor_id:
            continue
        ln = (b["goal"].get("notes") or "").strip()
        if ln and ln not in merged_notes:
            merged_notes = (merged_notes + "\n\n" + ln).strip() if merged_notes else ln
    if survivor_doc and merged_notes and merged_notes != (survivor_doc.get("notes") or ""):
        await db.goals.update_one(
            {"id": survivor_id, "user_id": user_id},
            {"$set": {"notes": merged_notes[:8000], "updated_at": now}},
        )
    await db.goals.delete_many({"id": {"$in": losers}, "user_id": user_id})

    return {
        "survivor_id": survivor_id,
        "deleted_goal_ids": losers,
        "reparented_outcome_ids": reparented_outcomes,
        "nested_as_tasks": nested_as_tasks,
        "deleted_outcome_ids": deleted_outcomes,
        "deleted_duplicate_outcome_ids": deleted_duplicates,
        "applied_tradeoffs": applied_tradeoffs,
    }
