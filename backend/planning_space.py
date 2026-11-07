"""Unified Planning Space read model (Foundation Planning Batch 3A).

A single read-only endpoint that assembles the user's current planning
picture by combining the authoritative sources already owned by:

- ``planning_engine.py``  — Goals, Projects, Plans, Expected Outcomes,
  Tasks and Required Check-ins.
- ``time_service.py``     — weekly time capacity.
- ``money_service.py``    — current money availability.

This module intentionally performs NO monetary arithmetic, NO time-interval
math, NO replanning, NO scheduling, NO writes, NO migrations and NO LLM /
web calls. It never redefines or recomputes anything the authoritative
services already compute; it only aggregates and shapes a response.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

from bson.decimal128 import Decimal128
from fastapi import APIRouter, Depends, HTTPException, Query

from deps import get_current_user, get_db
from money_service import load_availability
from time_service import load_week_time_capacity


planning_space_router = APIRouter(
    prefix="/planning-space",
    tags=["planning-space"],
)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _parse_week_start(value: Optional[str], today: date) -> date:
    """Validate ``week_start_date`` strictly as a Monday in ``YYYY-MM-DD``.

    When no value is supplied, falls back to the Monday of the current
    week (``today - timedelta(days=today.weekday())``).
    """
    if value is None or value == "":
        return today - timedelta(days=today.weekday())
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="week_start_date must be a valid YYYY-MM-DD date",
        )
    if parsed.weekday() != 0:
        raise HTTPException(
            status_code=400,
            detail="week_start_date must be a Monday",
        )
    return parsed


def _money_json(value: Any) -> Any:
    """Recursively convert BSON ``Decimal128`` / ``Decimal`` values to the
    canonical two-decimal string shape used by the money service's JSON
    responses. Performs ONLY serialization — never any arithmetic.
    """
    if isinstance(value, Decimal128):
        value = value.to_decimal()
    if isinstance(value, Decimal):
        return format(value.quantize(Decimal("0.01")), "f")
    if isinstance(value, dict):
        return {key: _money_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_money_json(item) for item in value]
    return value


def _required_id(record: dict, record_kind: str) -> str:
    """Return a validated non-blank ``id`` or raise. Used before indexing or
    deduplicating any Goal, Project, Plan, Expected Outcome, Task or
    Required Check-in. Never fabricates an identity for a malformed row.
    """
    value = record.get("id")
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{record_kind} record is missing a valid id")
    return value


def _valid_task_due_date(task: dict) -> Optional[date]:
    """Parse a Task ``due_date`` as ``YYYY-MM-DD`` or return ``None``.

    A missing, blank, non-string or invalidly-formatted due date is simply
    treated as "unknown" — never overdue, never due-this-week. The Task
    record itself is never modified.
    """
    value = task.get("due_date")
    if not isinstance(value, str) or value.strip() == "":
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _task_is_open(task: dict) -> bool:
    """A Task is "open" iff its status is not one of the two terminal
    states. ``deferred`` and similar states are NOT terminal.
    """
    return task.get("status") not in {"done", "cancelled"}


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@planning_space_router.get("/current")
async def get_current_planning_space(
    week_start_date: Optional[str] = Query(default=None),
    current_user: dict = Depends(get_current_user),
):
    # One request time, captured exactly once. ``as_of`` reflects the
    # moment processing began — it is NOT a transactional snapshot
    # guarantee across the independent MongoDB reads below.
    now = datetime.now(timezone.utc)
    today = now.date()
    week_start = _parse_week_start(week_start_date, today)
    week_end = week_start + timedelta(days=6)
    week_start_iso = week_start.isoformat()

    db = get_db()
    user_id = current_user["id"]

    # -- Canonical capacity (never re-queried / re-computed locally) --
    time_capacity = await load_week_time_capacity(db, user_id, week_start_iso)
    money_availability = await load_availability(db, user_id)
    money_capacity = _money_json(money_availability)

    # -- Goals -------------------------------------------------------------
    goals = await db.goals.find(
        {"user_id": user_id, "status": {"$in": ["active", "paused"]}},
        {
            "_id": 0,
            "id": 1,
            "title": 1,
            "status": 1,
            "deadline": 1,
            "commitment_type": 1,
        },
    ).to_list(length=None)
    for g in goals:
        _required_id(g, "goal")
    goal_ids = [_required_id(g, "goal") for g in goals]
    goal_id_set = set(goal_ids)

    # -- Projects ----------------------------------------------------------
    projects = await db.projects.find(
        {"user_id": user_id, "status": {"$in": ["active", "paused"]}},
        {
            "_id": 0,
            "id": 1,
            "title": 1,
            "status": 1,
            "target_end_date": 1,
            "commitment_type": 1,
        },
    ).to_list(length=None)
    for p in projects:
        _required_id(p, "project")
    project_ids = [_required_id(p, "project") for p in projects]
    project_id_set = set(project_ids)

    # -- Plans -------------------------------------------------------------
    plans_raw: list[dict]
    if not goal_ids and not project_ids:
        plans_raw = []
    else:
        plans_raw = await db.plans.find(
            {
                "user_id": user_id,
                "$or": [
                    {"target_type": "goal", "target_id": {"$in": goal_ids}},
                    {"target_type": "project", "target_id": {"$in": project_ids}},
                ],
            },
            {
                "_id": 0,
                "id": 1,
                "target_type": 1,
                "target_id": 1,
                "title": 1,
                "status": 1,
                "created_at": 1,
            },
        ).to_list(length=None)
    for pl in plans_raw:
        _required_id(pl, "plan")

    # Keep only Plans whose (target_type, target_id) matches a returned
    # Goal / Project. Orphaned Plans are ignored but never repaired.
    plans: list[dict] = []
    plan_target_by_id: dict[str, tuple[str, str]] = {}
    for pl in plans_raw:
        t_type = pl.get("target_type")
        t_id = pl.get("target_id")
        if t_type == "goal" and isinstance(t_id, str) and t_id in goal_id_set:
            plans.append(pl)
            plan_target_by_id[pl["id"]] = ("goal", t_id)
        elif t_type == "project" and isinstance(t_id, str) and t_id in project_id_set:
            plans.append(pl)
            plan_target_by_id[pl["id"]] = ("project", t_id)

    # -- Expected Outcomes (only when Goals exist) -------------------------
    if not goal_ids:
        expected_outcomes_raw = []
    else:
        expected_outcomes_raw = await db.expected_outcomes.find(
            {"user_id": user_id, "goal_id": {"$in": goal_ids}},
            {"_id": 0, "id": 1, "goal_id": 1},
        ).to_list(length=None)
    for eo in expected_outcomes_raw:
        _required_id(eo, "expected_outcome")
    outcome_goal_by_id: dict[str, str] = {}
    for eo in expected_outcomes_raw:
        g_id = eo.get("goal_id")
        if isinstance(g_id, str) and g_id in goal_id_set:
            outcome_goal_by_id[eo["id"]] = g_id

    # -- Open Tasks --------------------------------------------------------
    tasks_raw = await db.tasks.find(
        {"user_id": user_id, "status": {"$nin": ["done", "cancelled"]}},
        {
            "_id": 0,
            "id": 1,
            "status": 1,
            "due_date": 1,
            "plan_id": 1,
            "goal_id": 1,
            "expected_outcome_id": 1,
            "project_id": 1,
        },
    ).to_list(length=None)
    task_by_id: dict[str, dict] = {}
    for t in tasks_raw:
        tid = _required_id(t, "task")
        if tid in task_by_id:
            continue  # retain one row per id; never count duplicates
        task_by_id[tid] = t

    # -- Task → target associations ---------------------------------------
    # Multiple stored links on one Task may point to multiple returned
    # targets. We respect those links as-is, deduplicating per-target by
    # Task id and globally by Task id, but we never choose a "preferred"
    # target or rewrite conflicting links.
    tasks_by_goal: dict[str, set[str]] = {gid: set() for gid in goal_id_set}
    tasks_by_project: dict[str, set[str]] = {pid: set() for pid in project_id_set}
    task_target_identities: dict[str, set[tuple[str, str]]] = {}
    scoped_task_ids: set[str] = set()

    for tid, task in task_by_id.items():
        identities: set[tuple[str, str]] = set()

        plan_id = task.get("plan_id") if isinstance(task.get("plan_id"), str) else None
        plan_target = plan_target_by_id.get(plan_id) if plan_id else None

        goal_link = task.get("goal_id") if isinstance(task.get("goal_id"), str) else None
        outcome_link = (
            task.get("expected_outcome_id")
            if isinstance(task.get("expected_outcome_id"), str)
            else None
        )
        outcome_goal = outcome_goal_by_id.get(outcome_link) if outcome_link else None

        # Goal associations.
        for gid in goal_id_set:
            if (
                (plan_target is not None and plan_target == ("goal", gid))
                or (goal_link == gid)
                or (outcome_goal == gid)
            ):
                identities.add(("goal", gid))
                tasks_by_goal[gid].add(tid)

        # Project associations.
        project_link = (
            task.get("project_id") if isinstance(task.get("project_id"), str) else None
        )
        for pid in project_id_set:
            if (
                (plan_target is not None and plan_target == ("project", pid))
                or (project_link == pid)
            ):
                identities.add(("project", pid))
                tasks_by_project[pid].add(tid)

        task_target_identities[tid] = identities
        if identities:
            scoped_task_ids.add(tid)

    # -- Task date classification -----------------------------------------
    overdue_task_ids: set[str] = set()
    due_this_week_task_ids: set[str] = set()
    for tid, task in task_by_id.items():
        due = _valid_task_due_date(task)
        if due is None:
            continue
        if due < today:
            overdue_task_ids.add(tid)
        if week_start <= due <= week_end:
            due_this_week_task_ids.add(tid)

    # -- Required Check-ins (durable collection only) ---------------------
    # Only Plans whose stored status is EXACTLY "active" are eligible.
    active_plan_ids: set[str] = set()
    plans_by_target: dict[tuple[str, str], list[dict]] = {}
    for pl in plans:
        t_type = pl["target_type"]
        t_id = pl["target_id"]
        plans_by_target.setdefault((t_type, t_id), []).append(pl)
        if pl.get("status") == "active":
            active_plan_ids.add(pl["id"])

    open_task_ids = set(task_by_id.keys())
    if not active_plan_ids or not open_task_ids:
        required_checkins_raw: list[dict] = []
    else:
        required_checkins_raw = await db.required_checkins.find(
            {
                "user_id": user_id,
                "status": "active",
                "plan_id": {"$in": list(active_plan_ids)},
                "task_id": {"$in": list(open_task_ids)},
            },
            {"_id": 0, "id": 1, "plan_id": 1, "task_id": 1, "status": 1},
        ).to_list(length=None)
    for rc in required_checkins_raw:
        _required_id(rc, "required_checkin")

    # Associate Required Check-ins per-target. The Plan-Task pair encoded
    # on the Required Check-in must agree with the Task's own plan_id; a
    # record that straddles two different Plans is ignored (but never
    # mutated or repaired).
    required_checkins_by_goal: dict[str, set[str]] = {gid: set() for gid in goal_id_set}
    required_checkins_by_project: dict[str, set[str]] = {
        pid: set() for pid in project_id_set
    }
    global_required_checkin_ids: set[str] = set()

    for rc in required_checkins_raw:
        if rc.get("status") != "active":
            continue
        plan_id = rc.get("plan_id")
        task_id = rc.get("task_id")
        if not isinstance(plan_id, str) or plan_id not in active_plan_ids:
            continue
        if not isinstance(task_id, str) or task_id not in open_task_ids:
            continue
        linked_task = task_by_id.get(task_id)
        if linked_task is None:
            continue
        if linked_task.get("plan_id") != plan_id:
            continue
        target = plan_target_by_id.get(plan_id)
        if target is None:
            continue
        rc_id = rc["id"]
        global_required_checkin_ids.add(rc_id)
        t_type, t_id = target
        if t_type == "goal" and t_id in required_checkins_by_goal:
            required_checkins_by_goal[t_id].add(rc_id)
        elif t_type == "project" and t_id in required_checkins_by_project:
            required_checkins_by_project[t_id].add(rc_id)

    # -- Plan summaries per target ----------------------------------------
    def _plan_summary(pl: dict) -> dict:
        title = pl.get("title")
        status = pl.get("status")
        created_at = pl.get("created_at")
        return {
            "id": pl["id"],
            "title": title if isinstance(title, str) else "",
            "status": status if isinstance(status, str) else "",
            "created_at": created_at if isinstance(created_at, str) else "",
        }

    def _sorted_plan_summaries(target_key: tuple[str, str]) -> list[dict]:
        seen: set[str] = set()
        bucket: list[dict] = []
        for pl in plans_by_target.get(target_key, []):
            pid = pl["id"]
            if pid in seen:
                continue
            seen.add(pid)
            bucket.append(pl)
        bucket.sort(
            key=lambda p: (
                p.get("created_at") if isinstance(p.get("created_at"), str) else "",
                p["id"],
            ),
            reverse=True,
        )
        return [_plan_summary(p) for p in bucket]

    # -- Target responses --------------------------------------------------
    def _target_dict(
        record: dict,
        target_type: str,
        deadline_field: str,
    ) -> dict:
        rec_id = record["id"]
        title = record.get("title")
        status = record.get("status")
        deadline = record.get(deadline_field)
        commitment = (
            "exclusive"
            if record.get("commitment_type") == "exclusive"
            else "postponable"
        )
        if target_type == "goal":
            per_target_task_ids = tasks_by_goal.get(rec_id, set())
            per_target_rc_ids = required_checkins_by_goal.get(rec_id, set())
        else:
            per_target_task_ids = tasks_by_project.get(rec_id, set())
            per_target_rc_ids = required_checkins_by_project.get(rec_id, set())
        overdue = per_target_task_ids & overdue_task_ids
        due_week = per_target_task_ids & due_this_week_task_ids
        return {
            "target_type": target_type,
            "target_id": rec_id,
            "title": title if isinstance(title, str) else "",
            "status": status if isinstance(status, str) else "",
            "deadline": deadline if isinstance(deadline, str) else "",
            "commitment_type": commitment,
            "plans": _sorted_plan_summaries((target_type, rec_id)),
            "open_task_count": len(per_target_task_ids),
            "overdue_task_count": len(overdue),
            "due_this_week_task_count": len(due_week),
            "active_plan_required_checkin_count": len(per_target_rc_ids),
        }

    target_rows: list[dict] = []
    for g in goals:
        target_rows.append(_target_dict(g, "goal", "deadline"))
    for p in projects:
        target_rows.append(_target_dict(p, "project", "target_end_date"))

    target_rows.sort(
        key=lambda row: (
            0 if row["target_type"] == "goal" else 1,
            (row.get("title") or "").lower(),
            row.get("target_id") or "",
        )
    )

    # -- Unscoped workload -------------------------------------------------
    unscoped_task_ids = {
        tid for tid in task_by_id.keys() if tid not in scoped_task_ids
    }
    unscoped_overdue = unscoped_task_ids & overdue_task_ids
    unscoped_due_week = unscoped_task_ids & due_this_week_task_ids
    unscoped_workload = {
        "open_task_count": len(unscoped_task_ids),
        "overdue_task_count": len(unscoped_overdue),
        "due_this_week_task_count": len(unscoped_due_week),
    }

    # -- Portfolio totals --------------------------------------------------
    active_goal_count = sum(1 for g in goals if g.get("status") == "active")
    paused_goal_count = sum(1 for g in goals if g.get("status") == "paused")
    active_project_count = sum(1 for p in projects if p.get("status") == "active")
    paused_project_count = sum(1 for p in projects if p.get("status") == "paused")
    unique_plan_ids = {pl["id"] for pl in plans}  # already filtered to returned targets

    portfolio_totals = {
        "active_goal_count": active_goal_count,
        "paused_goal_count": paused_goal_count,
        "active_project_count": active_project_count,
        "paused_project_count": paused_project_count,
        "plan_count": len(unique_plan_ids),
        "open_task_count": len(task_by_id),
        "overdue_task_count": len(overdue_task_ids),
        "due_this_week_task_count": len(due_this_week_task_ids),
        "active_plan_required_checkin_count": len(global_required_checkin_ids),
    }

    return {
        "as_of": now.isoformat(),
        "week_start_date": week_start_iso,
        "capacity": {
            "time": time_capacity,
            "money": money_capacity,
        },
        "targets": target_rows,
        "unscoped_workload": unscoped_workload,
        "portfolio_totals": portfolio_totals,
    }
