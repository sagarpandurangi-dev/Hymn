"""Hymn Planning Engine — Goal / Project / Learning Journey decomposition.

Turns a target planning object into an executable, portfolio-aware plan while
respecting Hymn's hard rules:

* Read from Hymn first. Never invent unknowns — return "unknown".
* Every inferred fact carries evidence + confidence.
* Show inferred state for confirmation before touching live data.
* Portfolio-wide planning uses only capacity remaining after approved
  commitments. Unknown capacity is NOT available capacity.
* Reuse the existing ``resource_allocations`` collection for allocations.
  Reuse tasks, expected_outcomes, and check-ins. No new planning entities.
* Live objects are not mutated until ``/approve`` and only if the portfolio
  snapshot hash still matches the one the proposal was built from.
* Scenarios and forecasts are read-only until separately approved.

Backend owns:

* Deterministic snapshot read, snapshot hash, conflict detection, cycle
  detection, evidence precedence, capacity calculation, validation, atomic
  commit, idempotency, versioning.

The LLM (Claude Sonnet 4.5 via ``emergentintegrations``) is used solely for:

* Objective interpretation
* Current-state summarisation
* Proposing measurable Expected Outcomes and Tasks
* Explaining conflicts in plain English
* Generating precise blocking questions

Every LLM output is validated against a strict schema before being persisted
onto a proposal. Anything the model cannot ground in the supplied Hymn
snapshot is expected to be returned as ``"unknown"`` with evidence
``"llm_estimate"`` and confidence ``"low"``.

Storage:

* ``plan_proposals`` — versioned proposals. Immutable once approved/rejected.
* ``plan_action_log`` — append-only trail of committed actions per proposal.

No mirror of existing entities is kept — proposed_outcomes/tasks live inside
the proposal document and, upon approval, are materialised into the existing
``expected_outcomes``, ``tasks``, and ``resource_allocations`` collections.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import uuid
from datetime import date as date_type, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from bson.decimal128 import Decimal128
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from deps import get_current_user, get_db

load_dotenv()

logger = logging.getLogger(__name__)

planning_router = APIRouter(prefix="/planning", tags=["planning"])


# ============================================================================
# Constants
# ============================================================================

TARGET_TYPES = ("goal", "project", "journey")
PROPOSAL_STATUSES = (
    "draft",
    "confirmation_required",
    "blocking_input_required",
    "proposal_ready",
    "infeasible",
    "approved",
    "rejected",
    "abandoned",
    "paused",
    "error",
)
FEASIBILITY_STATUSES = (
    "feasible",
    "feasible_with_tradeoffs",
    "not_currently_feasible",
    "unknown",
)
CONFIDENCE_LEVELS = ("high", "medium", "low")
EVIDENCE_TYPES = (
    "explicit_user_confirmation",
    "verified_structured_field",
    "approved_plan",
    "current_activity_checkin",
    "inference",
    "external_estimate",
    "llm_estimate",
    "none",
)
EVIDENCE_PRECEDENCE: Tuple[str, ...] = (
    "explicit_user_confirmation",
    "verified_structured_field",
    "approved_plan",
    "current_activity_checkin",
    "inference",
    "external_estimate",
    "llm_estimate",
    "none",
)


# ============================================================================
# Utilities
# ============================================================================

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


def _parse_date(s: str) -> Optional[date_type]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _require(cond: bool, msg: str, code: int = 400) -> None:
    if not cond:
        raise HTTPException(status_code=code, detail=msg)


def _require_in(v: str, choices: Tuple[str, ...], field: str) -> None:
    _require(v in choices, f"{field} must be one of {list(choices)}")


def _decimal_from_stored(v: Any) -> Decimal:
    if v is None or v == "":
        return Decimal(0)
    if isinstance(v, Decimal128):
        return v.to_decimal()
    if isinstance(v, Decimal):
        return v
    try:
        return Decimal(str(v))
    except Exception:
        return Decimal(0)


def _hhmm_to_minutes(s: str) -> int:
    try:
        h, m = s.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return 0


def _stable_json(obj: Any) -> str:
    """Deterministic JSON — used for snapshot hashing. Sorts keys and coerces
    all Decimal128 / datetime values to strings so the hash is reproducible."""
    def default(o: Any) -> Any:
        if isinstance(o, Decimal128):
            return str(o.to_decimal())
        if isinstance(o, Decimal):
            return str(o)
        if isinstance(o, datetime):
            return o.isoformat()
        if isinstance(o, date_type):
            return o.isoformat()
        return str(o)
    return json.dumps(obj, sort_keys=True, default=default, separators=(",", ":"))


def _snapshot_hash(snapshot: Dict[str, Any]) -> str:
    """SHA-256 hash of the deterministic JSON of a snapshot. Used to detect
    portfolio changes between proposal generation and approval commit.

    Excludes ``generated_at`` (the read timestamp) so re-reading an unchanged
    portfolio always yields the same hash.
    """
    clone = {k: v for k, v in snapshot.items() if k != "generated_at"}
    return hashlib.sha256(_stable_json(clone).encode("utf-8")).hexdigest()


def _evidence_rank(evidence: str) -> int:
    try:
        return EVIDENCE_PRECEDENCE.index(evidence)
    except ValueError:
        return len(EVIDENCE_PRECEDENCE)


def _pick_stronger_evidence(a: dict, b: dict) -> dict:
    """Return whichever fact has stronger evidence per the hierarchy. Never
    silently overrides — ties break in favour of the newer timestamp."""
    ra, rb = _evidence_rank(a.get("evidence") or "none"), _evidence_rank(b.get("evidence") or "none")
    if ra < rb:
        return a
    if rb < ra:
        return b
    ta, tb = a.get("recorded_at") or "", b.get("recorded_at") or ""
    return a if ta >= tb else b


# ============================================================================
# Fact / Evidence record shape
# ============================================================================

def _fact(field: str, value: Any, evidence: str, confidence: str,
          source: Optional[str] = None, note: Optional[str] = None) -> dict:
    """Build a normalized evidence-tagged fact."""
    _require_in(evidence, EVIDENCE_TYPES, "evidence")
    _require_in(confidence, CONFIDENCE_LEVELS, "confidence")
    return {
        "field": field,
        "value": value,
        "evidence": evidence,
        "confidence": confidence,
        "source": source,
        "note": note,
        "recorded_at": _now(),
    }


# ============================================================================
# Portfolio snapshot — deterministic read of every Hymn record that could
# affect this planning decision.
# ============================================================================

async def _read_target(db, user_id: str, target_type: str, target_id: str) -> Optional[dict]:
    coll_map = {"goal": "goals", "project": "projects", "journey": "knowledge_journeys"}
    doc = await db[coll_map[target_type]].find_one(
        {"id": target_id, "user_id": user_id}, {"_id": 0},
    )
    return doc


async def _read_snapshot(db, user_id: str, target_type: str, target_id: str) -> Dict[str, Any]:
    """Read every Hymn record relevant to planning the target object.

    The returned snapshot is passed verbatim to the LLM AND hashed to detect
    portfolio drift between proposal generation and approval commit.
    """
    _require_in(target_type, TARGET_TYPES, "target_type")

    target = await _read_target(db, user_id, target_type, target_id)
    if not target:
        raise HTTPException(status_code=404, detail=f"{target_type.title()} not found")

    # ---- Linked objects ----
    linked_outcomes: List[dict] = []
    linked_stages: List[dict] = []
    linked_components: List[dict] = []
    linked_journey: Optional[dict] = None
    linked_goal: Optional[dict] = None

    if target_type == "goal":
        linked_outcomes = await db.expected_outcomes.find(
            {"goal_id": target_id, "user_id": user_id}, {"_id": 0},
        ).to_list(length=200)
        # If a Learning Journey wraps this Goal, include it.
        linked_journey = await db.knowledge_journeys.find_one(
            {"goal_id": target_id, "user_id": user_id}, {"_id": 0},
        )
        if linked_journey:
            linked_stages = await db.knowledge_stages.find(
                {"journey_id": linked_journey["id"], "user_id": user_id}, {"_id": 0},
            ).to_list(length=100)
            linked_components = await db.knowledge_components.find(
                {"journey_id": linked_journey["id"], "user_id": user_id}, {"_id": 0},
            ).to_list(length=500)
    elif target_type == "journey":
        # A Journey plans through its linked Goal + Knowledge Stages/Components.
        linked_goal = await db.goals.find_one(
            {"id": target.get("goal_id"), "user_id": user_id}, {"_id": 0},
        )
        linked_outcomes = await db.expected_outcomes.find(
            {"goal_id": target.get("goal_id"), "user_id": user_id}, {"_id": 0},
        ).to_list(length=200)
        linked_stages = await db.knowledge_stages.find(
            {"journey_id": target_id, "user_id": user_id}, {"_id": 0},
        ).to_list(length=100)
        linked_components = await db.knowledge_components.find(
            {"journey_id": target_id, "user_id": user_id}, {"_id": 0},
        ).to_list(length=500)

    # ---- Tasks ----
    if target_type == "goal":
        eo_ids = [o["id"] for o in linked_outcomes]
        task_q = {"user_id": user_id, "$or": [
            {"expected_outcome_id": {"$in": eo_ids}} if eo_ids else {"expected_outcome_id": "__none__"},
        ]}
        # If no expected_outcomes, this becomes a no-op query — return []
        if not eo_ids:
            tasks = []
        else:
            tasks = await db.tasks.find(task_q, {"_id": 0}).to_list(length=1000)
    elif target_type == "project":
        tasks = await db.tasks.find(
            {"user_id": user_id, "project_id": target_id}, {"_id": 0},
        ).to_list(length=1000)
    else:  # journey
        comp_ids = [c["id"] for c in linked_components]
        eo_ids = [o["id"] for o in linked_outcomes]
        tasks = await db.tasks.find(
            {"user_id": user_id, "$or": [
                {"component_id": {"$in": comp_ids}} if comp_ids else {"component_id": "__none__"},
                {"expected_outcome_id": {"$in": eo_ids}} if eo_ids else {"expected_outcome_id": "__none__"},
            ]}, {"_id": 0},
        ).to_list(length=1000) if (comp_ids or eo_ids) else []

    # ---- Check-ins linked to any of these ----
    checkin_target_ids: List[str] = []
    if target_type == "goal":
        checkin_target_ids = [target_id]
    elif target_type == "project":
        checkin_target_ids = [target_id]
    else:
        checkin_target_ids = [target.get("goal_id")] if target.get("goal_id") else []
    checkins: List[dict] = []
    if checkin_target_ids:
        checkins = await db.checkins.find(
            {"user_id": user_id, "target_id": {"$in": checkin_target_ids}}, {"_id": 0},
        ).sort("created_at", -1).to_list(length=200)

    # ---- Domain (goal / journey-linked-goal) ----
    domain_id = target.get("domain_id") or (linked_goal or {}).get("domain_id")
    domain = None
    if domain_id:
        domain = await db.domains.find_one({"id": domain_id, "user_id": user_id}, {"_id": 0})

    # ---- Portfolio: resource_allocations (time + money, all statuses) ----
    allocations = await db.resource_allocations.find(
        {"user_id": user_id}, {"_id": 0},
    ).to_list(length=5000)

    # ---- Portfolio: time commitments ----
    time_commitments = await db.time_commitments.find(
        {"user_id": user_id}, {"_id": 0},
    ).to_list(length=1000)

    # ---- Portfolio: financial accounts + monthly commitments ----
    accounts = await db.financial_accounts.find(
        {"user_id": user_id}, {"_id": 0},
    ).to_list(length=200)
    monthly_money = await db.monthly_money_commitments.find(
        {"user_id": user_id}, {"_id": 0},
    ).to_list(length=500)

    # ---- Every other active/paused Goal/Project so portfolio-wide planning
    # sees competing commitments ----
    other_goals = await db.goals.find(
        {"user_id": user_id, "status": {"$in": ["active", "paused"]}}, {"_id": 0},
    ).to_list(length=500)
    other_projects = await db.projects.find(
        {"user_id": user_id, "status": {"$in": ["active", "paused"]}}, {"_id": 0},
    ).to_list(length=500)

    # ---- Serialize decimals to strings so the snapshot is JSON-stable ----
    def _clean(doc: dict) -> dict:
        out = {}
        for k, v in doc.items():
            if isinstance(v, Decimal128):
                out[k] = str(v.to_decimal())
            else:
                out[k] = v
        return out

    return {
        "target_type": target_type,
        "target_id": target_id,
        "target": _clean(target),
        "linked_goal": _clean(linked_goal) if linked_goal else None,
        "linked_journey": _clean(linked_journey) if linked_journey else None,
        "expected_outcomes": [_clean(o) for o in linked_outcomes],
        "knowledge_stages": [_clean(s) for s in linked_stages],
        "knowledge_components": [_clean(c) for c in linked_components],
        "tasks": [_clean(t) for t in tasks],
        "checkins": [_clean(c) for c in checkins],
        "domain": _clean(domain) if domain else None,
        "portfolio": {
            "resource_allocations": [_clean(a) for a in allocations],
            "time_commitments": [_clean(c) for c in time_commitments],
            "financial_accounts": [_clean(a) for a in accounts],
            "monthly_money_commitments": [_clean(m) for m in monthly_money],
            "active_goals": [{"id": g["id"], "title": g["title"], "status": g.get("status"),
                              "deadline": g.get("deadline")} for g in other_goals],
            "active_projects": [{"id": p["id"], "title": p["title"], "status": p.get("status"),
                                 "target_end_date": p.get("target_end_date")} for p in other_projects],
        },
        "generated_at": _now(),
    }


# ============================================================================
# Deterministic capacity math — re-use portfolio helpers where possible.
# ============================================================================

def _week_daily_minutes(snapshot: Dict[str, Any]) -> Dict[str, int]:
    """Return per-weekday committed minutes (union of time_commitments +
    reserved time allocations). Unknown fields are excluded."""
    weekdays = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    result: Dict[str, int] = {d: 0 for d in weekdays}
    for tc in snapshot["portfolio"]["time_commitments"]:
        wd = (tc.get("day_of_week") or "").lower()
        if wd in result and tc.get("start_time") and tc.get("end_time"):
            result[wd] += max(0, _hhmm_to_minutes(tc["end_time"]) - _hhmm_to_minutes(tc["start_time"]))
    for alloc in snapshot["portfolio"]["resource_allocations"]:
        if alloc.get("resource_type") != "time":
            continue
        if alloc.get("status") not in ("reserved", "consumed"):
            continue
        wd = (alloc.get("day_of_week") or "").lower()
        if wd in result and alloc.get("start_time") and alloc.get("end_time"):
            result[wd] += max(0, _hhmm_to_minutes(alloc["end_time"]) - _hhmm_to_minutes(alloc["start_time"]))
    return result


def _reserved_money_by_currency(snapshot: Dict[str, Any]) -> Dict[str, str]:
    """Sum reserved money per currency from resource_allocations."""
    totals: Dict[str, Decimal] = {}
    for a in snapshot["portfolio"]["resource_allocations"]:
        if a.get("resource_type") != "money":
            continue
        if a.get("state") not in ("reserved", "expired"):
            continue
        cur = a.get("currency") or ""
        totals[cur] = totals.get(cur, Decimal(0)) + _decimal_from_stored(a.get("amount"))
    return {cur: str(v) for cur, v in totals.items()}


def _liquid_money_by_currency(snapshot: Dict[str, Any]) -> Dict[str, str]:
    totals: Dict[str, Decimal] = {}
    for acc in snapshot["portfolio"]["financial_accounts"]:
        cur = acc.get("currency") or ""
        amt = _decimal_from_stored(acc.get("current_value"))
        # Only "liquid" categories count — mirror portfolio_manager.
        if acc.get("liquidity") == "liquid":
            totals[cur] = totals.get(cur, Decimal(0)) + amt
    return {cur: str(v) for cur, v in totals.items()}


def _available_capacity(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic remaining capacity.

    Formula (per HARD RULE 5):
        available = total_capacity - approved_commitments - locked_allocations

    Unknown capacity is NOT available capacity."""
    weekly_minutes = _week_daily_minutes(snapshot)
    total_week = 7 * 24 * 60
    committed_week = sum(weekly_minutes.values())
    unrestricted_week = max(0, total_week - committed_week)

    liquid = _liquid_money_by_currency(snapshot)
    reserved = _reserved_money_by_currency(snapshot)
    available_money: Dict[str, str] = {}
    all_curr = set(liquid) | set(reserved)
    for cur in all_curr:
        avail = Decimal(liquid.get(cur, "0")) - Decimal(reserved.get(cur, "0"))
        available_money[cur] = str(avail)

    return {
        "time_weekly": {
            "total_minutes": total_week,
            "committed_minutes": committed_week,
            "available_minutes": unrestricted_week,
            "by_weekday_committed": weekly_minutes,
        },
        "money": {
            "liquid_by_currency": liquid,
            "reserved_by_currency": reserved,
            "available_by_currency": available_money,
        },
    }


# ============================================================================
# Deterministic current-state inference.
# ============================================================================

def _infer_current_state(snapshot: Dict[str, Any]) -> List[dict]:
    """Build the ``current_state`` array — every field carries evidence and
    confidence. Fields that Hymn does not know are returned as ``value=None``
    with ``evidence=none`` so the UI can force a user answer."""
    facts: List[dict] = []
    t = snapshot["target"]
    target_type = snapshot["target_type"]

    # Objective — always present as target.title.
    facts.append(_fact(
        "objective",
        t.get("title") or None,
        evidence="verified_structured_field", confidence="high",
        source=f"{target_type}.title",
    ))

    # Success criteria
    if target_type == "goal":
        val = t.get("target_outcome") or None
        facts.append(_fact(
            "success_criteria", val,
            evidence="verified_structured_field" if val else "none",
            confidence="high" if val else "low",
            source="goal.target_outcome",
            note=None if val else "Not captured on the goal; ask the user.",
        ))
    elif target_type == "project":
        val = t.get("description") or None
        facts.append(_fact(
            "success_criteria", val,
            evidence="verified_structured_field" if val else "none",
            confidence="medium" if val else "low",
            source="project.description",
            note=None if val else "Project has no description; ask the user.",
        ))
    else:  # journey
        goal = snapshot.get("linked_goal") or {}
        val = goal.get("target_outcome") or None
        facts.append(_fact(
            "success_criteria", val,
            evidence="verified_structured_field" if val else "none",
            confidence="medium" if val else "low",
            source="linked_goal.target_outcome",
            note=None if val else "Linked goal has no target outcome.",
        ))

    # Target date
    deadline = (t.get("deadline") or t.get("target_end_date") or
                (snapshot.get("linked_goal") or {}).get("deadline") or "") or None
    facts.append(_fact(
        "target_date", deadline,
        evidence="verified_structured_field" if deadline else "none",
        confidence="high" if deadline else "low",
        source=f"{target_type}.deadline",
        note=None if deadline else "No target date on record.",
    ))

    # Current progress
    eos = snapshot["expected_outcomes"]
    if eos:
        completed = sum(1 for e in eos if e.get("status") == "completed")
        facts.append(_fact(
            "current_progress",
            {"expected_outcomes_completed": completed,
             "expected_outcomes_total": len(eos),
             "pct": round(100 * completed / len(eos), 1) if eos else 0.0},
            evidence="verified_structured_field", confidence="high",
            source="expected_outcomes.status",
        ))
    else:
        facts.append(_fact(
            "current_progress", None,
            evidence="none", confidence="low",
            note="No Expected Outcomes exist yet — progress cannot be computed.",
        ))

    # Completed and active work
    ts = snapshot["tasks"]
    facts.append(_fact(
        "completed_and_active_work",
        {
            "tasks_total": len(ts),
            "tasks_done": sum(1 for x in ts if x.get("status") == "done"),
            "tasks_todo": sum(1 for x in ts if x.get("status") == "todo"),
            "tasks_deferred": sum(1 for x in ts if x.get("status") == "deferred"),
            "recent_checkins": len(snapshot["checkins"]),
        },
        evidence="verified_structured_field", confidence="high",
        source="tasks + checkins",
    ))

    # Constraints — deterministic: derive from any monthly_money_commitments
    # and time_commitments that mention this target (currently only tracked
    # via metadata on tasks; we surface counts only).
    facts.append(_fact(
        "constraints",
        {
            "time_commitments_count": len(snapshot["portfolio"]["time_commitments"]),
            "monthly_money_commitments_count": len(snapshot["portfolio"]["monthly_money_commitments"]),
            "active_goals_count": len(snapshot["portfolio"]["active_goals"]),
            "active_projects_count": len(snapshot["portfolio"]["active_projects"]),
        },
        evidence="verified_structured_field", confidence="high",
        source="portfolio",
    ))

    # Existing allocations tied to the target
    tied_allocs = _tied_allocations(snapshot)
    facts.append(_fact(
        "existing_allocations",
        {
            "count": len(tied_allocs),
            "time_reserved_minutes": sum(a.get("_minutes", 0) for a in tied_allocs if a.get("resource_type") == "time"),
            "money_reserved_by_currency": _sum_money(tied_allocs),
        },
        evidence="verified_structured_field", confidence="high",
        source="resource_allocations linked to target",
    ))

    # Dependencies — cross-goal / cross-project prerequisites are not modeled
    # in the schema today; surface as unknown so the LLM (and the user) can
    # populate them.
    facts.append(_fact(
        "dependencies", None,
        evidence="none", confidence="low",
        note="Hymn does not model cross-object dependencies yet.",
    ))

    # Required resources — surface budget hints from monthly_money_commitments
    # linked to this domain if any.
    domain_id = t.get("domain_id") or (snapshot.get("linked_goal") or {}).get("domain_id")
    if domain_id:
        related_money = [m for m in snapshot["portfolio"]["monthly_money_commitments"]
                         if m.get("domain_id") == domain_id]
    else:
        related_money = []
    facts.append(_fact(
        "required_resources_hint",
        {"same_domain_monthly_commitments_count": len(related_money)},
        evidence="inference", confidence="low",
        source="monthly_money_commitments filtered by domain",
    ))

    return facts


def _tied_allocations(snapshot: Dict[str, Any]) -> List[dict]:
    """Allocations tied to this target via owner_id or task_id linkage."""
    target_type = snapshot["target_type"]
    target_id = snapshot["target_id"]
    task_ids = {t["id"] for t in snapshot["tasks"]}
    out: List[dict] = []
    for a in snapshot["portfolio"]["resource_allocations"]:
        matched = False
        if a.get("owner_type") in ("goal", "project", "learning_journey"):
            if a.get("owner_id") == target_id:
                matched = True
        if not matched and a.get("owner_type") == "task" and a.get("owner_id") in task_ids:
            matched = True
        if matched:
            # attach a computed minutes value for time
            if a.get("resource_type") == "time" and a.get("start_time") and a.get("end_time"):
                a = dict(a)
                a["_minutes"] = max(0, _hhmm_to_minutes(a["end_time"]) - _hhmm_to_minutes(a["start_time"]))
            out.append(a)
    return out


def _sum_money(allocations: List[dict]) -> Dict[str, str]:
    totals: Dict[str, Decimal] = {}
    for a in allocations:
        if a.get("resource_type") != "money":
            continue
        cur = a.get("currency") or ""
        totals[cur] = totals.get(cur, Decimal(0)) + _decimal_from_stored(a.get("amount"))
    return {c: str(v) for c, v in totals.items()}


# ============================================================================
# Deterministic conflict / cycle / duplicate / date detection
# ============================================================================

def _detect_cycles(tasks: List[dict]) -> List[List[str]]:
    """Return every dependency cycle in a list of task dicts. Each task may
    carry a ``depends_on`` list of task titles (proposal-local) or task IDs."""
    graph: Dict[str, List[str]] = {}
    id_of: Dict[str, str] = {}
    for t in tasks:
        tid = t.get("id") or t.get("title")
        id_of[t.get("title", "")] = tid
        graph[tid] = []
    for t in tasks:
        tid = t.get("id") or t.get("title")
        for d in (t.get("depends_on") or []):
            resolved = id_of.get(d, d)
            if resolved in graph:
                graph[tid].append(resolved)

    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[str, int] = {n: WHITE for n in graph}
    stack: List[str] = []
    cycles: List[List[str]] = []

    def dfs(u: str) -> None:
        color[u] = GRAY
        stack.append(u)
        for v in graph.get(u, []):
            if color.get(v, WHITE) == GRAY:
                # Cycle found — slice stack from first occurrence.
                if v in stack:
                    cycles.append(stack[stack.index(v):] + [v])
            elif color.get(v, WHITE) == WHITE:
                dfs(v)
        color[u] = BLACK
        stack.pop()

    for n in list(graph):
        if color[n] == WHITE:
            dfs(n)
    return cycles


def _detect_duplicates(tasks: List[dict]) -> List[dict]:
    """Return duplicate task pairs by exact title match (case-insensitive)."""
    by_key: Dict[str, List[str]] = {}
    for t in tasks:
        key = (t.get("title") or "").strip().lower()
        if not key:
            continue
        by_key.setdefault(key, []).append(t.get("id") or t.get("title"))
    return [{"title": k, "ids": v} for k, v in by_key.items() if len(v) > 1]


def _detect_impossible_dates(tasks: List[dict], target_deadline: Optional[str]) -> List[dict]:
    """Return tasks whose earliest_start > target_date, or target_date after
    the parent object's deadline. Only compares REAL ISO dates —
    ``unknown``/None/empty values are ignored."""
    problems: List[dict] = []
    def _iso(v: Any) -> Optional[str]:
        if not v or v == "unknown":
            return None
        if isinstance(v, str) and _parse_date(v) is not None:
            return v
        return None

    parent_dl = _iso(target_deadline)
    for t in tasks:
        start = _iso(t.get("earliest_start"))
        due = _iso(t.get("target_date"))
        if start and due and start > due:
            problems.append({"task": t.get("title"), "issue": "earliest_start after target_date",
                             "earliest_start": start, "target_date": due})
        if parent_dl and due and due > parent_dl:
            problems.append({"task": t.get("title"), "issue": "task target_date after parent deadline",
                             "target_date": due, "parent_deadline": parent_dl})
    return problems


def _detect_over_allocation(snapshot: Dict[str, Any], proposed_tasks: List[dict]) -> List[dict]:
    """Compare per-week required minutes and per-currency required money in
    proposed_tasks to the available capacity. Unknown values do not consume."""
    cap = _available_capacity(snapshot)
    total_min_needed = 0
    money_needed: Dict[str, Decimal] = {}
    for t in proposed_tasks:
        req = t.get("required_resources") or {}
        # Time
        tm = req.get("time_minutes")
        if isinstance(tm, (int, float)) and tm > 0:
            total_min_needed += int(tm)
        # Money
        mo = req.get("money") or {}
        amt, cur = mo.get("amount"), mo.get("currency")
        if amt and cur:
            try:
                money_needed[cur] = money_needed.get(cur, Decimal(0)) + Decimal(str(amt))
            except Exception:
                pass

    conflicts: List[dict] = []
    # Weekly average check — we compare against ONE week of headroom (heuristic
    # since proposed_tasks generally span multiple weeks). Deterministic: if
    # total_min_needed > available_weekly * (weeks_until_deadline), flag.
    deadline = snapshot["target"].get("deadline") or snapshot["target"].get("target_end_date") or ""
    weeks = None
    d = _parse_date(deadline) if deadline else None
    today = datetime.now(timezone.utc).date()
    if d and d > today:
        weeks = max(1, ((d - today).days + 6) // 7)
    weekly_avail = cap["time_weekly"]["available_minutes"]
    if weeks is not None and total_min_needed > weekly_avail * weeks:
        conflicts.append({
            "kind": "time_over_allocation",
            "required_minutes": total_min_needed,
            "available_minutes_over_horizon": weekly_avail * weeks,
            "weeks_until_deadline": weeks,
        })
    for cur, needed in money_needed.items():
        available = Decimal(cap["money"]["available_by_currency"].get(cur, "0"))
        if needed > available:
            conflicts.append({
                "kind": "money_over_allocation",
                "currency": cur,
                "required_amount": str(needed),
                "available_amount": str(available),
            })
    return conflicts


# ============================================================================
# LLM interpretation — Claude Sonnet 4.5.
# ============================================================================

_LLM_SYSTEM = (
    "You are Hymn's Planning Interpreter. You NEVER invent facts. If the "
    "provided Hymn snapshot does not contain a piece of information, you "
    "must return the string \"unknown\" and mark the evidence as "
    "\"llm_estimate\" with confidence \"low\". You produce ONLY valid JSON "
    "matching the schema described in the user message. All measurable "
    "outcomes and tasks must have completion conditions grounded in the "
    "snapshot. Do not fabricate durations, costs, dates, priorities, "
    "dependencies, or skills that are not present or inferrable from the "
    "snapshot."
)


_LLM_INSTRUCTIONS_TEMPLATE = """
You will receive a Hymn planning snapshot as JSON. Return a JSON object with
these keys (and nothing else):

{
  "objective_summary": "one sentence, grounded in target.title / target_outcome",
  "measurable_success_criteria": "explicit measurable criterion, or \\"unknown\\"",
  "proposed_outcomes": [
    {
      "title": "...",
      "measurable_end_state": "e.g. body_weight <= 70kg",
      "completion_condition": "...",
      "target_date": "YYYY-MM-DD or unknown",
      "evidence": "verified_structured_field | inference | llm_estimate",
      "confidence": "high | medium | low"
    }
  ],
  "proposed_tasks": [
    {
      "title": "...",
      "action_and_deliverable": "...",
      "completion_condition": "measurable — no 'work on', 'research', 'stay consistent'",
      "owner": "self",
      "depends_on": [],
      "earliest_start": "YYYY-MM-DD or unknown",
      "target_date": "YYYY-MM-DD or unknown",
      "required_resources": {
        "time_minutes": 30,
        "money": {"amount": null, "currency": null},
        "energy": "low | medium | high | unknown",
        "attention": "low | medium | high | unknown"
      },
      "evidence": "inference | llm_estimate",
      "confidence": "high | medium | low",
      "evidence_basis": "cite the snapshot field or say 'llm_estimate'"
    }
  ],
  "proposed_check_ins": [
    {"cadence": "daily | weekly | monthly | manual", "linked_to": "outcome | task",
     "evidence": "inference"}
  ],
  "blocking_questions": [
    {"field": "target_date | success_criteria | ...", "question": "specific yes/no or short answer question",
     "why_blocking": "..."}
  ],
  "assumptions": ["explicit assumption strings the model made"],
  "external_estimates": [
    {"topic": "...", "source": "public knowledge | none", "range": "...", "confidence": "low"}
  ],
  "risks": ["short risk descriptions"]
}

RULES:
1. Do not create tasks such as "research X", "work on Y", "make progress",
   "stay consistent" unless they carry a MEASURABLE completion_condition.
2. If any required field cannot be grounded in the snapshot, emit the string
   "unknown" (not null).
3. All monetary and time estimates are optional — leave time_minutes null and
   money.amount null when unknown.
4. Never override existing values from the snapshot; only propose additions
   or corrections through blocking_questions.
5. Every proposed task MUST include a measurable completion_condition.

Snapshot follows below.
"""


def _extract_json(text: str) -> Optional[dict]:
    """Extract the first JSON object from a possibly-noisy LLM response."""
    if not text:
        return None
    # Strip markdown fences.
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        candidate = m.group(1)
    else:
        # Find first { … } block with balanced braces (naive but effective).
        start = text.find("{")
        if start == -1:
            return None
        depth = 0
        end = -1
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end == -1:
            return None
        candidate = text[start:end]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


async def _llm_interpret(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Ask the LLM to interpret the target and propose outcomes/tasks.

    Failure modes are non-fatal: on any error we return an empty proposal
    with a synthetic risk item so the pipeline still emits a proposal the
    user can complete manually.
    """
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        return {
            "objective_summary": snapshot["target"].get("title") or "unknown",
            "measurable_success_criteria": "unknown",
            "proposed_outcomes": [],
            "proposed_tasks": [],
            "proposed_check_ins": [],
            "blocking_questions": [],
            "assumptions": ["LLM key not configured; running deterministic-only mode."],
            "external_estimates": [],
            "risks": ["LLM interpretation skipped — planning surface reduced to deterministic facts."],
        }

    try:
        # Import inside the function so a missing package never breaks startup.
        from emergentintegrations.llm.chat import LlmChat, UserMessage  # noqa: WPS433
    except Exception as exc:  # pragma: no cover
        logger.warning("planning: emergentintegrations import failed: %s", exc)
        return {
            "objective_summary": snapshot["target"].get("title") or "unknown",
            "measurable_success_criteria": "unknown",
            "proposed_outcomes": [],
            "proposed_tasks": [],
            "proposed_check_ins": [],
            "blocking_questions": [],
            "assumptions": [],
            "external_estimates": [],
            "risks": [f"LLM library unavailable: {type(exc).__name__}"],
        }

    session_id = f"planning-{snapshot['target_type']}-{snapshot['target_id']}"
    chat = LlmChat(
        api_key=api_key,
        session_id=session_id,
        system_message=_LLM_SYSTEM,
    ).with_model("anthropic", "claude-sonnet-4-6")

    prompt = _LLM_INSTRUCTIONS_TEMPLATE + "\n\nSNAPSHOT:\n" + _stable_json(snapshot)

    try:
        # Non-streaming send — the caller awaits the full JSON reply.
        response = await chat.send_message(UserMessage(text=prompt))
    except Exception as exc:  # pragma: no cover
        logger.warning("planning: LLM call failed: %s", exc)
        return {
            "objective_summary": snapshot["target"].get("title") or "unknown",
            "measurable_success_criteria": "unknown",
            "proposed_outcomes": [],
            "proposed_tasks": [],
            "proposed_check_ins": [],
            "blocking_questions": [],
            "assumptions": [],
            "external_estimates": [],
            "risks": [f"LLM call failed: {type(exc).__name__}"],
        }

    text = response if isinstance(response, str) else str(response)
    parsed = _extract_json(text)
    if not parsed or not isinstance(parsed, dict):
        return {
            "objective_summary": snapshot["target"].get("title") or "unknown",
            "measurable_success_criteria": "unknown",
            "proposed_outcomes": [],
            "proposed_tasks": [],
            "proposed_check_ins": [],
            "blocking_questions": [],
            "assumptions": [],
            "external_estimates": [],
            "risks": ["LLM returned unparseable output — surfaced deterministic view only."],
        }

    # Normalise: ensure every proposed_task has an id (used for deps/commit).
    tasks = parsed.get("proposed_tasks") or []
    for t in tasks:
        t.setdefault("id", _uuid())
    outcomes = parsed.get("proposed_outcomes") or []
    for o in outcomes:
        o.setdefault("id", _uuid())
    parsed["proposed_tasks"] = tasks
    parsed["proposed_outcomes"] = outcomes
    return parsed


# ============================================================================
# Feasibility
# ============================================================================

def _feasibility(
    snapshot: Dict[str, Any], proposed_tasks: List[dict], conflicts: List[dict],
) -> Dict[str, Any]:
    """Deterministic feasibility verdict (§5).

    * ``unknown`` if any required resource on any proposed task is unknown OR
      any required cost / duration / dependency / success criterion is unknown.
    * ``feasible`` if no conflicts and no unknowns.
    * ``feasible_with_tradeoffs`` if conflicts exist but each has an
      auto-derived alternative (e.g. postponing lower-priority items).
    * ``not_currently_feasible`` if a hard resource shortfall has no known
      alternative.
    """
    unknowns: List[str] = []
    for t in proposed_tasks:
        req = t.get("required_resources") or {}
        if not t.get("completion_condition") or t.get("completion_condition") == "unknown":
            unknowns.append(f"task '{t.get('title')}' missing completion_condition")
        if req.get("time_minutes") in (None, "unknown"):
            unknowns.append(f"task '{t.get('title')}' has unknown time_minutes")
    target_dl = snapshot["target"].get("deadline") or snapshot["target"].get("target_end_date") or ""
    if not target_dl:
        unknowns.append("target has no deadline / target_end_date")

    if unknowns:
        return {"status": "unknown", "reasons": unknowns, "tradeoffs": [], "alternatives": []}
    if not conflicts:
        return {"status": "feasible", "reasons": [], "tradeoffs": [], "alternatives": []}

    # Conflicts exist. Derive alternatives per-conflict.
    alternatives: List[dict] = []
    hard = False
    for c in conflicts:
        if c["kind"] == "time_over_allocation":
            alternatives.append({
                "conflict": c,
                "options": [
                    {"action": "extend_deadline", "delta_weeks": 2,
                     "rationale": "brings weekly load under available capacity"},
                    {"action": "reduce_scope", "rationale": "cut lowest-priority proposed_tasks"},
                    {"action": "reallocate_time_from_lower_priority_goal",
                     "rationale": "requires explicit user approval"},
                ],
            })
        elif c["kind"] == "money_over_allocation":
            hard = True
            alternatives.append({
                "conflict": c,
                "options": [
                    {"action": "wait_for_income", "rationale": "cannot spend beyond liquid+available"},
                    {"action": "reduce_scope", "rationale": "cut cost-bearing tasks"},
                    {"action": "reallocate_from_lower_priority_reservation",
                     "rationale": "requires explicit user approval"},
                ],
            })
    return {
        "status": "not_currently_feasible" if hard else "feasible_with_tradeoffs",
        "reasons": [c["kind"] for c in conflicts],
        "tradeoffs": [c["kind"] for c in conflicts],
        "alternatives": alternatives,
    }


# ============================================================================
# Validation — enforce every rule in the "VALIDATION" section.
# ============================================================================

def _validate(proposal: Dict[str, Any]) -> List[str]:
    """Return a list of validation errors. Empty list = valid."""
    errors: List[str] = []

    # 1. Every fact needs evidence + assumption.
    for f in proposal.get("current_state", []):
        if not f.get("evidence"):
            errors.append(f"current_state fact '{f.get('field')}' missing evidence")

    # 2. Every task has a measurable completion_condition
    for t in proposal.get("proposed_tasks", []):
        if not t.get("completion_condition") or t.get("completion_condition") == "unknown":
            errors.append(f"task '{t.get('title')}' missing measurable completion_condition")

    # 3. Every allocation has amount, unit, period
    for r in proposal.get("resource_requirements", []):
        if r.get("kind") == "money":
            if not r.get("amount") or not r.get("currency"):
                errors.append("resource_requirement money entry lacks amount/currency")
        if r.get("kind") == "time":
            if not r.get("minutes"):
                errors.append("resource_requirement time entry lacks minutes")
        if not r.get("period"):
            errors.append(f"resource_requirement {r.get('kind')} entry lacks period")

    # 4. Feasibility 'feasible' while an unknown required resource exists
    feas = proposal.get("feasibility", {}).get("status") or ""
    if feas == "feasible":
        for t in proposal.get("proposed_tasks", []):
            req = t.get("required_resources") or {}
            if req.get("time_minutes") in (None, "unknown"):
                errors.append(f"feasibility=feasible but task '{t.get('title')}' has unknown time_minutes")

    # 5. Cycles / duplicates / impossible dates surfaced via portfolio_conflicts
    for c in proposal.get("portfolio_conflicts", []):
        if c.get("kind") == "dependency_cycle":
            errors.append(f"dependency cycle: {c.get('cycle')}")
        if c.get("kind") == "duplicate_task":
            errors.append(f"duplicate task titles: {c.get('title')}")
        if c.get("kind") == "impossible_date":
            errors.append(f"impossible date: {c.get('detail')}")

    # 6. External estimate must have a source
    for e in proposal.get("external_estimates", []):
        if not e.get("source"):
            errors.append("external estimate missing source")

    return errors


# ============================================================================
# Proposal build
# ============================================================================

async def _build_proposal(
    db, user_id: str, target_type: str, target_id: str,
    prior_confirmations: Optional[Dict[str, dict]] = None,
) -> Dict[str, Any]:
    """Assemble a full proposal document.

    ``prior_confirmations`` (optional) is a dict keyed by field name carrying
    user-confirmed values from a previous round; those override the inferred
    state when the evidence rank is stronger.
    """
    snapshot = await _read_snapshot(db, user_id, target_type, target_id)
    snap_hash = _snapshot_hash(snapshot)

    current_state = _infer_current_state(snapshot)
    # Apply prior confirmations — user-confirmed values are the strongest
    # evidence (explicit_user_confirmation).
    if prior_confirmations:
        for fact in current_state:
            conf = prior_confirmations.get(fact["field"])
            if not conf:
                continue
            candidate = _fact(
                fact["field"],
                conf.get("value"),
                evidence="explicit_user_confirmation",
                confidence="high",
                source="user",
                note=conf.get("note"),
            )
            merged = _pick_stronger_evidence(fact, candidate)
            fact.update(merged)

    llm_out = await _llm_interpret(snapshot)

    proposed_outcomes = llm_out.get("proposed_outcomes") or []
    proposed_tasks = llm_out.get("proposed_tasks") or []
    proposed_check_ins = llm_out.get("proposed_check_ins") or []

    # Deterministic conflict detection on the LLM output.
    cycles = _detect_cycles(proposed_tasks)
    dups = _detect_duplicates(proposed_tasks)
    target_dl = snapshot["target"].get("deadline") or snapshot["target"].get("target_end_date") or ""
    bad_dates = _detect_impossible_dates(proposed_tasks, target_dl or None)
    over_alloc = _detect_over_allocation(snapshot, proposed_tasks)

    portfolio_conflicts: List[dict] = []
    for cyc in cycles:
        portfolio_conflicts.append({"kind": "dependency_cycle", "cycle": cyc})
    for d in dups:
        portfolio_conflicts.append({"kind": "duplicate_task", "title": d["title"], "ids": d["ids"]})
    for bd in bad_dates:
        portfolio_conflicts.append({"kind": "impossible_date", "detail": bd})
    for o in over_alloc:
        portfolio_conflicts.append({"kind": o["kind"], "detail": o})

    # Visual phases — group tasks by earliest_start month (never persisted).
    visual_phases: List[dict] = []
    by_month: Dict[str, List[str]] = {}
    for t in proposed_tasks:
        m = (t.get("earliest_start") or "")[:7] or "unknown"
        by_month.setdefault(m, []).append(t.get("title") or t.get("id"))
    for month, titles in sorted(by_month.items()):
        visual_phases.append({"label": f"Phase {month}", "tasks": titles})

    # Resource requirements roll-up.
    resource_requirements: List[dict] = []
    total_minutes = 0
    money_by_cur: Dict[str, Decimal] = {}
    for t in proposed_tasks:
        req = t.get("required_resources") or {}
        tm = req.get("time_minutes")
        if isinstance(tm, (int, float)) and tm > 0:
            total_minutes += int(tm)
        mo = req.get("money") or {}
        if mo.get("amount") and mo.get("currency"):
            try:
                money_by_cur[mo["currency"]] = money_by_cur.get(mo["currency"], Decimal(0)) + Decimal(str(mo["amount"]))
            except Exception:
                pass
    if total_minutes > 0:
        resource_requirements.append({"kind": "time", "minutes": total_minutes,
                                       "period": "over_horizon", "confidence": "medium"})
    for cur, amt in money_by_cur.items():
        resource_requirements.append({"kind": "money", "amount": str(amt), "currency": cur,
                                       "period": "over_horizon", "confidence": "medium"})

    feasibility = _feasibility(snapshot, proposed_tasks, over_alloc)

    # Evidence map — every non-null current_state fact + every proposed task
    # with its evidence line.
    evidence_map: List[dict] = []
    for f in current_state:
        evidence_map.append({"field": f["field"], "evidence": f["evidence"],
                              "confidence": f["confidence"], "source": f.get("source")})
    for t in proposed_tasks:
        evidence_map.append({
            "field": f"task:{t.get('title')}",
            "evidence": t.get("evidence") or "llm_estimate",
            "confidence": t.get("confidence") or "low",
            "source": t.get("evidence_basis"),
        })

    # Approval actions — the exact live-write plan.
    approval_actions: List[dict] = []
    for o in proposed_outcomes:
        approval_actions.append({
            "action": "create_expected_outcome",
            "payload": {
                "title": o.get("title"),
                "target_value": o.get("measurable_end_state") or "",
                "current_value": "",
                "unit": "",
                "deadline": o.get("target_date") if o.get("target_date") != "unknown" else "",
                "status": "active",
                "outcome_type": "generic",
            },
            "proposal_ref": o.get("id"),
        })
    for t in proposed_tasks:
        approval_actions.append({
            "action": "create_task",
            "payload": {
                "title": t.get("title"),
                "due_date": t.get("target_date") if t.get("target_date") != "unknown" else "",
                "priority": "medium",
                "status": "todo",
                "notes": (t.get("action_and_deliverable") or "") + "\n\n"
                         + "Completion: " + (t.get("completion_condition") or "unknown"),
                "origin": "expected_outcome" if target_type in ("goal", "journey") else "project",
                "expected_outcome_id": None,
                "project_id": target_id if target_type == "project" else None,
            },
            "proposal_ref": t.get("id"),
            "depends_on_proposal_refs": t.get("depends_on") or [],
        })
    # Time reservations (attached to created tasks). Only when task carries a
    # scheduling rule with day_of_week + start/end time.
    for t in proposed_tasks:
        req = t.get("required_resources") or {}
        sched = t.get("schedule") or {}
        if sched.get("day_of_week") and sched.get("start_time") and sched.get("end_time"):
            approval_actions.append({
                "action": "create_time_allocation",
                "payload": {
                    "resource_type": "time",
                    "owner_type": "task",
                    "owner_id": None,  # linked at commit time to newly created task
                    "allocation_mode": sched.get("mode") or "recurring_weekly",
                    "day_of_week": sched.get("day_of_week"),
                    "start_time": sched.get("start_time"),
                    "end_time": sched.get("end_time"),
                    "status": "reserved",
                    "fixed_or_flexible": "flexible",
                    "unit": "minutes",
                },
                "proposal_ref": t.get("id"),
                "attach_task_owner": True,
            })
        # Optional money reservation on the task.
        money = req.get("money") or {}
        if money.get("amount") and money.get("currency"):
            approval_actions.append({
                "action": "create_money_reservation",
                "payload": {
                    "amount": str(money["amount"]),
                    "currency": money["currency"],
                    "due_date": t.get("target_date") if t.get("target_date") not in (None, "unknown") else _today_iso(),
                    "priority": "medium",
                    "title": f"Reserve for: {t.get('title')}",
                    "description": t.get("action_and_deliverable") or "",
                },
                "proposal_ref": t.get("id"),
                "attach_task_owner": True,
            })

    # Build the composite proposal.
    proposal = {
        "id": _uuid(),
        "user_id": user_id,
        "target_type": target_type,
        "target_id": target_id,
        "snapshot_hash": snap_hash,
        "snapshot": snapshot,
        "version": 1,
        "status": "confirmation_required",
        "current_state": current_state,
        "confirmation_items": [
            {"field": f["field"], "value": f["value"], "evidence": f["evidence"],
             "confidence": f["confidence"], "source": f.get("source"), "note": f.get("note")}
            for f in current_state
        ],
        "blocking_questions": llm_out.get("blocking_questions") or [],
        "proposed_outcomes": proposed_outcomes,
        "proposed_tasks": proposed_tasks,
        "proposed_check_ins": proposed_check_ins,
        "visual_phases": visual_phases,
        "resource_requirements": resource_requirements,
        "portfolio_conflicts": portfolio_conflicts,
        "assumptions": llm_out.get("assumptions") or [],
        "external_estimates": llm_out.get("external_estimates") or [],
        "risks": llm_out.get("risks") or [],
        "feasibility": feasibility,
        "approval_actions": approval_actions,
        "evidence_map": evidence_map,
        "validation_errors": [],
        "objective_summary": llm_out.get("objective_summary") or (snapshot["target"].get("title") or "unknown"),
        "measurable_success_criteria": llm_out.get("measurable_success_criteria") or "unknown",
        "created_at": _now(),
        "updated_at": _now(),
    }

    errs = _validate(proposal)
    proposal["validation_errors"] = errs
    if errs:
        # If invalid but blocking questions exist, hand back for input.
        if proposal["blocking_questions"]:
            proposal["status"] = "blocking_input_required"
        else:
            proposal["status"] = "infeasible"
    elif feasibility["status"] == "not_currently_feasible":
        proposal["status"] = "infeasible"
    elif feasibility["status"] == "unknown" or proposal["blocking_questions"]:
        proposal["status"] = "blocking_input_required"
    else:
        proposal["status"] = "proposal_ready"

    return proposal


# ============================================================================
# API models
# ============================================================================

class AnalyzeRequest(BaseModel):
    target_type: str
    target_id: str


class ConfirmationEntry(BaseModel):
    field: str
    action: str = Field(..., description="confirm | edit | reject | mark_unknown")
    value: Any = None
    note: Optional[str] = None


class ConfirmRequest(BaseModel):
    confirmations: List[ConfirmationEntry]


class PauseRequest(BaseModel):
    future_allocations: str = Field(..., description="retain | reduce | release")


# ============================================================================
# Endpoints
# ============================================================================

@planning_router.post("/analyze")
async def analyze(body: AnalyzeRequest, current_user: dict = Depends(get_current_user)):
    """Read the target and produce the full planning JSON. Persists a
    versioned proposal in ``plan_proposals``. Never modifies live data."""
    db = get_db()
    _require_in(body.target_type, TARGET_TYPES, "target_type")
    proposal = await _build_proposal(db, current_user["id"], body.target_type, body.target_id)

    # Version bump if prior proposals exist.
    existing = await db.plan_proposals.count_documents(
        {"user_id": current_user["id"], "target_type": body.target_type, "target_id": body.target_id},
    )
    proposal["version"] = existing + 1
    await db.plan_proposals.insert_one(dict(proposal))
    # Return a slim payload — drop the snapshot from the API response.
    slim = dict(proposal)
    slim.pop("snapshot", None)
    return slim


@planning_router.get("/proposals/{proposal_id}")
async def get_proposal(proposal_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    doc = await db.plan_proposals.find_one(
        {"id": proposal_id, "user_id": current_user["id"]}, {"_id": 0, "snapshot": 0},
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return doc


@planning_router.get("/proposals")
async def list_proposals(
    target_type: Optional[str] = Query(None),
    target_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    q: dict = {"user_id": current_user["id"]}
    if target_type:
        _require_in(target_type, TARGET_TYPES, "target_type")
        q["target_type"] = target_type
    if target_id:
        q["target_id"] = target_id
    docs = await db.plan_proposals.find(q, {"_id": 0, "snapshot": 0}).sort([("created_at", -1)]).to_list(length=200)
    return docs


@planning_router.post("/proposals/{proposal_id}/confirm")
async def confirm_proposal(
    proposal_id: str, body: ConfirmRequest, current_user: dict = Depends(get_current_user),
):
    """User records confirmations / edits / rejections / mark-unknown for
    inferred fields. Builds a NEW proposal version using the strengthened
    evidence — the prior version is retained for audit."""
    db = get_db()
    prior = await db.plan_proposals.find_one(
        {"id": proposal_id, "user_id": current_user["id"]}, {"_id": 0},
    )
    if not prior:
        raise HTTPException(status_code=404, detail="Proposal not found")
    _require(
        prior.get("status") not in ("approved", "rejected", "abandoned"),
        f"Cannot confirm — proposal is {prior.get('status')}",
    )

    confirmations: Dict[str, dict] = {}
    for c in body.confirmations:
        _require_in(c.action, ("confirm", "edit", "reject", "mark_unknown"), "action")
        if c.action == "confirm":
            # Use the previously inferred value.
            prev = next((f for f in prior["current_state"] if f["field"] == c.field), None)
            if prev is None:
                continue
            confirmations[c.field] = {"value": prev["value"], "note": c.note}
        elif c.action == "edit":
            confirmations[c.field] = {"value": c.value, "note": c.note}
        elif c.action == "reject":
            confirmations[c.field] = {"value": None, "note": (c.note or "user_rejected")}
        elif c.action == "mark_unknown":
            confirmations[c.field] = {"value": None, "note": "unknown"}

    new_proposal = await _build_proposal(
        db, current_user["id"], prior["target_type"], prior["target_id"],
        prior_confirmations=confirmations,
    )
    new_proposal["version"] = (prior.get("version") or 1) + 1
    await db.plan_proposals.insert_one(dict(new_proposal))
    slim = dict(new_proposal)
    slim.pop("snapshot", None)
    return slim


@planning_router.post("/proposals/{proposal_id}/approve")
async def approve_proposal(proposal_id: str, current_user: dict = Depends(get_current_user)):
    """Atomically apply every approval_action. If ANY action fails, roll back
    all previously applied actions from this run. Verifies the portfolio
    snapshot hash has not changed since proposal generation."""
    db = get_db()
    proposal = await db.plan_proposals.find_one(
        {"id": proposal_id, "user_id": current_user["id"]}, {"_id": 0},
    )
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    _require(
        proposal.get("status") in ("proposal_ready", "confirmation_required", "blocking_input_required"),
        f"Cannot approve — proposal is {proposal.get('status')}",
    )

    # Snapshot-drift check FIRST — a stale proposal must be re-analyzed even
    # if the stored copy has validation errors.
    live_snapshot = await _read_snapshot(
        db, current_user["id"], proposal["target_type"], proposal["target_id"],
    )
    live_hash = _snapshot_hash(live_snapshot)
    if live_hash != proposal.get("snapshot_hash"):
        raise HTTPException(
            status_code=409,
            detail="Portfolio changed since proposal was generated. Please re-analyze.",
        )

    _require(not proposal.get("validation_errors"),
             f"Cannot approve — validation_errors: {proposal.get('validation_errors')}")

    # Feasibility must still be feasible / feasible_with_tradeoffs.
    fs = proposal.get("feasibility", {}).get("status")
    _require(fs in ("feasible", "feasible_with_tradeoffs"),
             f"Cannot approve — feasibility={fs}")

    # Atomic commit: track everything we've written, so we can roll back on
    # failure. Idempotency: an "action_key" is generated per action from
    # (proposal_id, action, proposal_ref) and stored in plan_action_log.
    now = _now()
    log_entries: List[dict] = []
    task_id_by_ref: Dict[str, str] = {}
    eo_id_by_ref: Dict[str, str] = {}

    async def _rollback():
        for entry in reversed(log_entries):
            try:
                if entry["kind"] == "expected_outcome":
                    await db.expected_outcomes.delete_one({"id": entry["created_id"]})
                elif entry["kind"] == "task":
                    await db.tasks.delete_one({"id": entry["created_id"]})
                elif entry["kind"] == "resource_allocation":
                    await db.resource_allocations.delete_one({"id": entry["created_id"]})
                await db.plan_action_log.delete_one({"action_key": entry["action_key"]})
            except Exception:
                pass

    try:
        for act in proposal.get("approval_actions", []):
            action = act.get("action")
            payload = act.get("payload") or {}
            proposal_ref = act.get("proposal_ref")
            action_key = f"{proposal_id}:{action}:{proposal_ref or ''}"

            # Idempotency check.
            existing_log = await db.plan_action_log.find_one({"action_key": action_key})
            if existing_log:
                # Already applied — reuse the created id.
                if action == "create_expected_outcome":
                    eo_id_by_ref[proposal_ref] = existing_log["created_id"]
                elif action == "create_task":
                    task_id_by_ref[proposal_ref] = existing_log["created_id"]
                continue

            if action == "create_expected_outcome":
                if proposal["target_type"] not in ("goal", "journey"):
                    continue
                goal_id = (proposal["target_id"] if proposal["target_type"] == "goal"
                            else (live_snapshot.get("linked_goal") or {}).get("id"))
                if not goal_id:
                    continue
                eo_id = _uuid()
                await db.expected_outcomes.insert_one({
                    "id": eo_id,
                    "user_id": current_user["id"],
                    "goal_id": goal_id,
                    "title": payload["title"],
                    "target_value": payload.get("target_value", ""),
                    "current_value": payload.get("current_value", ""),
                    "unit": payload.get("unit", ""),
                    "deadline": payload.get("deadline", ""),
                    "status": "active",
                    "notes": "",
                    "outcome_type": payload.get("outcome_type", "generic"),
                    "created_at": now,
                    "updated_at": now,
                })
                eo_id_by_ref[proposal_ref] = eo_id
                entry = {"kind": "expected_outcome", "created_id": eo_id,
                         "action_key": action_key, "proposal_ref": proposal_ref}
                log_entries.append(entry)
                await db.plan_action_log.insert_one({
                    "action_key": action_key, "proposal_id": proposal_id,
                    "kind": "expected_outcome", "created_id": eo_id,
                    "user_id": current_user["id"], "created_at": now,
                })
            elif action == "create_task":
                task_id = _uuid()
                # Resolve expected_outcome_id from prior refs (LLM used titles or ids in depends_on).
                eo_ref = None
                # For goal/journey, attach to the FIRST created outcome if any; otherwise leave null.
                if proposal["target_type"] in ("goal", "journey") and eo_id_by_ref:
                    eo_ref = next(iter(eo_id_by_ref.values()))
                doc = {
                    "id": task_id,
                    "user_id": current_user["id"],
                    "title": payload["title"],
                    "due_date": payload.get("due_date", ""),
                    "priority": payload.get("priority", "medium"),
                    "status": "todo",
                    "notes": payload.get("notes", ""),
                    "origin": payload.get("origin", "standalone"),
                    "expected_outcome_id": eo_ref,
                    "project_id": payload.get("project_id"),
                    "component_id": None,
                    "assigned_to_type": "self",
                    "assigned_to_name": "",
                    "assigned_to_phone": "",
                    "deferred_until": None,
                    "original_due_date": None,
                    "defer_count": 0,
                    "created_at": now,
                    "updated_at": now,
                }
                await db.tasks.insert_one(doc)
                task_id_by_ref[proposal_ref] = task_id
                entry = {"kind": "task", "created_id": task_id,
                         "action_key": action_key, "proposal_ref": proposal_ref}
                log_entries.append(entry)
                await db.plan_action_log.insert_one({
                    "action_key": action_key, "proposal_id": proposal_id,
                    "kind": "task", "created_id": task_id,
                    "user_id": current_user["id"], "created_at": now,
                })
            elif action == "create_time_allocation":
                alloc_id = _uuid()
                owner_task_id = task_id_by_ref.get(act.get("proposal_ref"))
                if not owner_task_id and act.get("attach_task_owner"):
                    # Skip if the owner task wasn't created (defensive).
                    continue
                await db.resource_allocations.insert_one({
                    "id": alloc_id,
                    "user_id": current_user["id"],
                    "resource_type": "time",
                    "owner_type": "task",
                    "owner_id": owner_task_id,
                    "allocation_mode": payload.get("allocation_mode", "recurring_weekly"),
                    "date": None,
                    "day_of_week": payload.get("day_of_week"),
                    "start_time": payload.get("start_time"),
                    "end_time": payload.get("end_time"),
                    "quantity": None,
                    "unit": "minutes",
                    "currency": None,
                    "status": "reserved",
                    "fixed_or_flexible": "flexible",
                    "created_at": now,
                    "updated_at": now,
                })
                entry = {"kind": "resource_allocation", "created_id": alloc_id,
                         "action_key": action_key, "proposal_ref": proposal_ref}
                log_entries.append(entry)
                await db.plan_action_log.insert_one({
                    "action_key": action_key, "proposal_id": proposal_id,
                    "kind": "resource_allocation", "created_id": alloc_id,
                    "user_id": current_user["id"], "created_at": now,
                })
            elif action == "create_money_reservation":
                alloc_id = _uuid()
                fc_id = _uuid()
                owner_task_id = task_id_by_ref.get(act.get("proposal_ref"))
                amt_str = payload.get("amount") or "0"
                amount = Decimal128(Decimal(amt_str))
                # Insert directly into resource_allocations — the sole owner
                # of Financial Commitments per the previous migration.
                await db.resource_allocations.insert_one({
                    "id": alloc_id,
                    "user_id": current_user["id"],
                    "resource_type": "money",
                    "owner_type": "task" if owner_task_id else "standalone",
                    "owner_id": owner_task_id,
                    "allocation_mode": "one_time",
                    "date": payload["due_date"],
                    "day_of_week": None,
                    "start_time": None,
                    "end_time": None,
                    "quantity": amount,
                    "unit": "currency",
                    "currency": payload["currency"],
                    "status": "reserved",
                    "fixed_or_flexible": "fixed",
                    "financial_commitment_id": fc_id,
                    "state": "reserved",
                    "title": payload.get("title", ""),
                    "description": payload.get("description", ""),
                    "amount": amount,
                    "due_date": payload["due_date"],
                    "original_due_date": payload["due_date"],
                    "priority": payload.get("priority", "medium"),
                    "domain_id": None,
                    "goal_id": (proposal["target_id"] if proposal["target_type"] == "goal" else None),
                    "project_id": (proposal["target_id"] if proposal["target_type"] == "project" else None),
                    "task_id": owner_task_id,
                    "resource_allocation_id": alloc_id,
                    "actual_amount": None,
                    "variance": None,
                    "unused_reservation": None,
                    "overrun_amount": None,
                    "completed_at": None,
                    "cancelled_at": None,
                    "postpone_count": 0,
                    "last_reviewed_at": None,
                    "next_review_date": None,
                    "source": "planning_engine",
                    "created_at": now,
                    "updated_at": now,
                })
                entry = {"kind": "resource_allocation", "created_id": alloc_id,
                         "action_key": action_key, "proposal_ref": proposal_ref}
                log_entries.append(entry)
                await db.plan_action_log.insert_one({
                    "action_key": action_key, "proposal_id": proposal_id,
                    "kind": "resource_allocation", "created_id": alloc_id,
                    "user_id": current_user["id"], "created_at": now,
                })
            # Unknown actions are silently skipped — never a partial commit.
    except Exception as exc:
        await _rollback()
        raise HTTPException(status_code=500, detail=f"Approval failed: {type(exc).__name__}: {exc}")

    await db.plan_proposals.update_one(
        {"id": proposal_id},
        {"$set": {
            "status": "approved",
            "approved_at": now,
            "updated_at": now,
            "committed_action_ids": [e["created_id"] for e in log_entries],
        }},
    )
    return {
        "status": "approved",
        "committed_actions": len(log_entries),
        "created_expected_outcomes": list(eo_id_by_ref.values()),
        "created_tasks": list(task_id_by_ref.values()),
    }


@planning_router.post("/proposals/{proposal_id}/reject")
async def reject_proposal(proposal_id: str, current_user: dict = Depends(get_current_user)):
    """User rejects the proposal. Releases every future allocation that this
    proposal had earmarked (planning_engine-sourced reservations)."""
    db = get_db()
    proposal = await db.plan_proposals.find_one(
        {"id": proposal_id, "user_id": current_user["id"]}, {"_id": 0},
    )
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    _require(
        proposal.get("status") not in ("approved", "rejected", "abandoned"),
        f"Cannot reject — proposal is {proposal.get('status')}",
    )
    now = _now()
    await db.plan_proposals.update_one(
        {"id": proposal_id},
        {"$set": {"status": "rejected", "rejected_at": now, "updated_at": now}},
    )
    return {"status": "rejected"}


@planning_router.post("/proposals/{proposal_id}/pause")
async def pause_proposal(
    proposal_id: str, body: PauseRequest, current_user: dict = Depends(get_current_user),
):
    """User pauses the plan and decides what to do with future allocations."""
    db = get_db()
    proposal = await db.plan_proposals.find_one(
        {"id": proposal_id, "user_id": current_user["id"]}, {"_id": 0},
    )
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    _require_in(body.future_allocations, ("retain", "reduce", "release"), "future_allocations")

    committed = proposal.get("committed_action_ids") or []
    if body.future_allocations == "release" and committed:
        # Release any resource_allocations tied to this proposal that are
        # still in the future.
        today = _today_iso()
        await db.resource_allocations.update_many(
            {"id": {"$in": committed},
             "$or": [{"date": {"$gte": today}}, {"due_date": {"$gte": today}}]},
            {"$set": {"status": "released", "state": "cancelled", "updated_at": _now()}},
        )
    # 'reduce' is intentionally deterministic — halve the reserved amount for
    # money allocations, leave time allocations untouched.
    elif body.future_allocations == "reduce" and committed:
        for alloc_id in committed:
            alloc = await db.resource_allocations.find_one({"id": alloc_id}, {"_id": 0})
            if not alloc:
                continue
            if alloc.get("resource_type") == "money":
                current_qty = _decimal_from_stored(alloc.get("quantity"))
                new_qty = current_qty / 2
                await db.resource_allocations.update_one(
                    {"id": alloc_id},
                    {"$set": {"quantity": Decimal128(new_qty), "amount": Decimal128(new_qty),
                              "updated_at": _now()}},
                )

    now = _now()
    await db.plan_proposals.update_one(
        {"id": proposal_id},
        {"$set": {"status": "paused", "updated_at": now,
                  "pause_policy": body.future_allocations}},
    )
    return {"status": "paused", "future_allocations": body.future_allocations}


@planning_router.post("/reassess")
async def reassess(body: AnalyzeRequest, current_user: dict = Depends(get_current_user)):
    """Trigger a reassessment on demand (also called by scheduled jobs every
    15 days or when target date / priority / scope changes)."""
    return await analyze(body, current_user)


# ============================================================================
# Index bootstrap
# ============================================================================

async def ensure_planning_indexes(database) -> None:
    await database.plan_proposals.create_index("id", unique=True)
    await database.plan_proposals.create_index("user_id")
    await database.plan_proposals.create_index([("user_id", 1), ("target_type", 1), ("target_id", 1)])
    await database.plan_proposals.create_index([("user_id", 1), ("created_at", -1)])
    await database.plan_action_log.create_index("action_key", unique=True)
    await database.plan_action_log.create_index([("user_id", 1), ("proposal_id", 1)])
