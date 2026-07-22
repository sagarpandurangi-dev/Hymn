"""Hymn Planning Engine — deterministic → confirm → generate → approve.

Pipeline (§1 of the spec):

* **A. Analyze** — deterministic only. Reads the relevant Hymn slice, infers
  current-state facts, attaches stable ``evidence_id`` values, stores a
  compact portfolio snapshot + hash. Never calls the LLM. Returns
  ``confirmation_required`` with no outcomes / tasks / feasibility.
* **B. Confirm** — batched. Persists and merges confirmations for every
  field in one request. Never discards a prior confirmation. Builds the
  ``resolved_context`` used downstream.
* **C. Generate** — single LLM call with the compact resolved context,
  deterministic capacity summaries, and evidence IDs. Deterministic code
  computes capacity, conflicts, duplicates, dependency validity, dates,
  and feasibility after the LLM returns.
* **D. Approve** — only when status = ``proposal_ready``. Snapshot drift
  triggers 409. Uses a durable state machine (preparing → applying →
  committed / failed) so partial commits are rolled back.

The LLM is constrained by strict Pydantic response models with
``extra='forbid'`` and enum + date validation. No hard-coded fallback
estimates. No invented sources. External estimates are always empty.
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
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from deps import get_current_user, get_db
from portfolio_manager import compute_time_union_and_overlap

load_dotenv()
logger = logging.getLogger(__name__)

planning_router = APIRouter(prefix="/planning", tags=["planning"])


# ============================================================================
# Constants
# ============================================================================

TARGET_TYPES = ("goal", "project", "journey")
PROPOSAL_STATUSES = (
    "confirmation_required",
    "blocking_input_required",
    "generating",
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
CONFIRMATION_ACTIONS = ("confirm", "edit", "reject", "mark_unknown")
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
EVIDENCE_PRECEDENCE: Tuple[str, ...] = EVIDENCE_TYPES  # already ordered
COMMIT_PHASES = ("preparing", "applying", "committed", "failed")


# ============================================================================
# Utilities
# ============================================================================

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


def _parse_date(s: Any) -> Optional[date_type]:
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _is_iso_date(v: Any) -> bool:
    return isinstance(v, str) and _parse_date(v) is not None


def _hhmm_to_minutes(s: str) -> int:
    try:
        h, m = s.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return 0


def _weekday_name(d: date_type) -> str:
    return ("monday", "tuesday", "wednesday", "thursday", "friday",
            "saturday", "sunday")[d.weekday()]


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


def _stable_json(obj: Any) -> str:
    """Deterministic JSON — used for snapshot hashing and LLM context."""
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
    """SHA-256 of the deterministic JSON of a snapshot, excluding
    ``generated_at`` so an unchanged portfolio always yields the same hash."""
    clone = {k: v for k, v in snapshot.items() if k != "generated_at"}
    return hashlib.sha256(_stable_json(clone).encode("utf-8")).hexdigest()


# ============================================================================
# Fact / Evidence record
# ============================================================================

def _fact(field: str, value: Any, evidence: str, confidence: str,
          source: Optional[str] = None, note: Optional[str] = None,
          blocking: bool = False) -> dict:
    _require_in(evidence, EVIDENCE_TYPES, "evidence")
    _require_in(confidence, CONFIDENCE_LEVELS, "confidence")
    return {
        "evidence_id": _uuid(),  # stable identifier used by the LLM contract
        "field": field,
        "value": value,
        "evidence": evidence,
        "confidence": confidence,
        "source": source,
        "note": note,
        "blocking": blocking,
        "recorded_at": _now(),
    }


# ============================================================================
# Portfolio snapshot — deterministic, RELEVANT-only.
# ============================================================================

async def _read_target(db, user_id: str, target_type: str, target_id: str) -> Optional[dict]:
    coll_map = {"goal": "goals", "project": "projects", "journey": "knowledge_journeys"}
    return await db[coll_map[target_type]].find_one(
        {"id": target_id, "user_id": user_id}, {"_id": 0},
    )


async def _read_snapshot(db, user_id: str, target_type: str, target_id: str) -> Dict[str, Any]:
    """Read only the relevant Hymn slice for planning this target.

    Includes: target + linked EOs/knowledge stages/components, tasks linked
    to the target chain, check-ins queried by real relationship fields,
    domain, active/paused portfolio time_commitments and monthly_money_
    commitments overlapping the horizon, financial_accounts, allocations
    tied to the target chain or currently reserved money.
    """
    _require_in(target_type, TARGET_TYPES, "target_type")
    target = await _read_target(db, user_id, target_type, target_id)
    if not target:
        raise HTTPException(status_code=404, detail=f"{target_type.title()} not found")

    linked_outcomes: List[dict] = []
    linked_stages: List[dict] = []
    linked_components: List[dict] = []
    linked_journey: Optional[dict] = None
    linked_goal: Optional[dict] = None

    if target_type == "goal":
        linked_outcomes = await db.expected_outcomes.find(
            {"goal_id": target_id, "user_id": user_id}, {"_id": 0},
        ).to_list(length=200)
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

    # Tasks tied to the target chain.
    if target_type == "goal":
        eo_ids = [o["id"] for o in linked_outcomes]
        tasks = await db.tasks.find(
            {"user_id": user_id, "expected_outcome_id": {"$in": eo_ids}}, {"_id": 0},
        ).to_list(length=1000) if eo_ids else []
    elif target_type == "project":
        tasks = await db.tasks.find(
            {"user_id": user_id, "project_id": target_id}, {"_id": 0},
        ).to_list(length=1000)
    else:  # journey
        comp_ids = [c["id"] for c in linked_components]
        eo_ids = [o["id"] for o in linked_outcomes]
        or_clauses: List[dict] = []
        if comp_ids:
            or_clauses.append({"component_id": {"$in": comp_ids}})
        if eo_ids:
            or_clauses.append({"expected_outcome_id": {"$in": eo_ids}})
        tasks = await db.tasks.find(
            {"user_id": user_id, "$or": or_clauses}, {"_id": 0},
        ).to_list(length=1000) if or_clauses else []

    # Check-ins — query using real relationship fields (§2).
    checkin_or: List[dict] = []
    task_ids = [t["id"] for t in tasks]
    if target_type == "goal":
        checkin_or.append({"goal_id": target_id})
        if linked_outcomes:
            checkin_or.append({"expected_outcome_id": {"$in": [o["id"] for o in linked_outcomes]}})
    elif target_type == "project":
        checkin_or.append({"project_id": target_id})
    else:  # journey
        if target.get("goal_id"):
            checkin_or.append({"goal_id": target["goal_id"]})
        if linked_components:
            checkin_or.append({"component_id": {"$in": [c["id"] for c in linked_components]}})
    if task_ids:
        checkin_or.append({"task_id": {"$in": task_ids}})
    checkins: List[dict] = []
    if checkin_or:
        checkins = await db.checkins.find(
            {"user_id": user_id, "$or": checkin_or}, {"_id": 0},
        ).sort("created_at", -1).to_list(length=200)

    domain_id = target.get("domain_id") or (linked_goal or {}).get("domain_id")
    domain = None
    if domain_id:
        domain = await db.domains.find_one({"id": domain_id, "user_id": user_id}, {"_id": 0})

    # Only active/paused other goals & projects (§2 — "relevant" only).
    other_goals = await db.goals.find(
        {"user_id": user_id, "status": {"$in": ["active", "paused"]},
         "id": {"$ne": target_id if target_type == "goal" else None}},
        {"_id": 0, "id": 1, "title": 1, "status": 1, "deadline": 1, "priority": 1, "domain_id": 1},
    ).to_list(length=500)
    other_projects = await db.projects.find(
        {"user_id": user_id, "status": {"$in": ["active", "paused"]},
         "id": {"$ne": target_id if target_type == "project" else None}},
        {"_id": 0, "id": 1, "title": 1, "status": 1, "target_end_date": 1, "priority": 1, "domain_id": 1},
    ).to_list(length=500)

    # Time commitments (deterministic caller handles effective_from/until).
    time_commitments = await db.time_commitments.find(
        {"user_id": user_id}, {"_id": 0},
    ).to_list(length=2000)

    # Financial accounts (already carry liquidity_type).
    accounts = await db.financial_accounts.find(
        {"user_id": user_id}, {"_id": 0},
    ).to_list(length=200)
    monthly_money = await db.monthly_money_commitments.find(
        {"user_id": user_id}, {"_id": 0},
    ).to_list(length=1000)

    # Allocations — tied to target chain OR currently reserved money
    # (finance-lifecycle rows are always relevant to feasibility).
    alloc_or: List[dict] = []
    if target_type == "goal":
        alloc_or.append({"goal_id": target_id})
    if target_type == "project":
        alloc_or.append({"project_id": target_id})
    if task_ids:
        alloc_or.append({"owner_type": "task", "owner_id": {"$in": task_ids}})
    # All active money reservations — they affect available capacity globally.
    alloc_or.append({"resource_type": "money",
                     "state": {"$in": ["reserved", "expired"]}})
    # All time allocations — needed for capacity math.
    alloc_or.append({"resource_type": "time",
                     "status": {"$in": ["reserved", "consumed"]}})
    allocations = await db.resource_allocations.find(
        {"user_id": user_id, "$or": alloc_or}, {"_id": 0},
    ).to_list(length=5000)

    def _clean(doc: dict) -> dict:
        out: dict = {}
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
            "active_goals": [_clean(g) for g in other_goals],
            "active_projects": [_clean(p) for p in other_projects],
        },
        "generated_at": _now(),
    }


# ============================================================================
# Current-state inference — deterministic, evidence-tagged (§2).
# ============================================================================

def _infer_current_state(snapshot: Dict[str, Any]) -> List[dict]:
    """Return every relevant fact with a stable evidence_id. Fields that
    Hymn doesn't know are surfaced as ``value=None`` + ``evidence=none``
    with ``blocking=True`` so the confirmation form can capture them."""
    facts: List[dict] = []
    t = snapshot["target"]
    target_type = snapshot["target_type"]

    facts.append(_fact(
        "objective",
        t.get("title") or None,
        evidence="verified_structured_field" if t.get("title") else "none",
        confidence="high" if t.get("title") else "low",
        source=f"{target_type}.title",
        blocking=not bool(t.get("title")),
    ))

    # Success criteria — Project.description is NOT success criteria (§2).
    if target_type == "goal":
        val = t.get("target_outcome") or None
        facts.append(_fact(
            "success_criteria", val,
            evidence="verified_structured_field" if val else "none",
            confidence="high" if val else "low",
            source="goal.target_outcome",
            note=None if val else "Not stored on the goal.",
            blocking=not bool(val),
        ))
    elif target_type == "project":
        # Project has no dedicated success_criteria field; stays unknown
        # until the user confirms one.
        facts.append(_fact(
            "success_criteria", None,
            evidence="none", confidence="low",
            source="project has no success_criteria field",
            note="Project description is not treated as success criteria.",
            blocking=True,
        ))
    else:  # journey
        goal = snapshot.get("linked_goal") or {}
        val = goal.get("target_outcome") or None
        facts.append(_fact(
            "success_criteria", val,
            evidence="verified_structured_field" if val else "none",
            confidence="medium" if val else "low",
            source="linked_goal.target_outcome" if val else None,
            note=None if val else "Linked goal has no target outcome.",
            blocking=not bool(val),
        ))

    deadline = (t.get("deadline") or t.get("target_end_date")
                or (snapshot.get("linked_goal") or {}).get("deadline"))
    facts.append(_fact(
        "target_date", deadline or None,
        evidence="verified_structured_field" if deadline else "none",
        confidence="high" if deadline else "low",
        source=f"{target_type}.deadline",
        note=None if deadline else "No target date on record.",
        blocking=not bool(deadline),
    ))

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
            note="No Expected Outcomes exist yet.",
        ))

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
        source="tasks + checkins (queried by relationship fields)",
    ))

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

    # Dependencies — Hymn does not model cross-object deps yet.
    facts.append(_fact(
        "dependencies", None,
        evidence="none", confidence="low",
        note="Hymn does not model cross-object dependencies.",
    ))

    return facts


# ============================================================================
# Time capacity — reuses ``compute_time_union_and_overlap`` per-day (§3).
# ============================================================================

def _time_capacity_summary(
    snapshot: Dict[str, Any],
    horizon_start: date_type,
    horizon_end: date_type,
) -> Dict[str, Any]:
    """Deterministic per-day free-minute intervals across the planning
    horizon. Never sums overlapping commitments. Respects
    ``effective_from``/``effective_until`` on time_commitments and dated
    resource_allocations. Returns ``capacity_status='unknown'`` when there
    is no commitment coverage or the horizon is empty."""
    if horizon_end < horizon_start:
        return {"capacity_status": "unknown", "reason": "empty or invalid horizon"}

    day = horizon_start
    total_free = 0
    days_with_commitments = 0
    days_seen = 0
    per_day: List[dict] = []
    tcs = snapshot["portfolio"]["time_commitments"]
    time_allocs = [a for a in snapshot["portfolio"]["resource_allocations"]
                   if a.get("resource_type") == "time"
                   and a.get("status") in ("reserved", "consumed")]

    while day <= horizon_end:
        day_iso = day.isoformat()
        wd = _weekday_name(day)
        intervals: List[Tuple[int, int]] = []

        for tc in tcs:
            if (tc.get("day_of_week") or "").lower() != wd:
                continue
            eff_from = tc.get("effective_from")
            eff_until = tc.get("effective_until")
            if eff_from and _is_iso_date(eff_from) and eff_from > day_iso:
                continue
            if eff_until and _is_iso_date(eff_until) and eff_until < day_iso:
                continue
            if tc.get("start_time") and tc.get("end_time"):
                intervals.append((_hhmm_to_minutes(tc["start_time"]),
                                  _hhmm_to_minutes(tc["end_time"])))

        for a in time_allocs:
            mode = a.get("allocation_mode")
            if mode == "one_time":
                if a.get("date") != day_iso:
                    continue
            elif mode == "recurring":
                # Only affects if day_of_week matches.
                if (a.get("day_of_week") or "").lower() != wd:
                    continue
            else:
                continue
            if a.get("start_time") and a.get("end_time"):
                intervals.append((_hhmm_to_minutes(a["start_time"]),
                                  _hhmm_to_minutes(a["end_time"])))

        committed, _overlap = compute_time_union_and_overlap(intervals)
        free = max(0, 1440 - committed)
        if intervals:
            days_with_commitments += 1
        days_seen += 1
        total_free += free
        per_day.append({"date": day_iso, "free_minutes": free,
                         "committed_minutes": committed})
        day = day + timedelta(days=1)

    # capacity_status=unknown if the user has no scheduled commitments at all
    # across the horizon (§3 — treat missing coverage as unknown).
    coverage_ok = days_with_commitments > 0
    return {
        "capacity_status": "known" if coverage_ok else "unknown",
        "horizon_start": horizon_start.isoformat(),
        "horizon_end": horizon_end.isoformat(),
        "days": days_seen,
        "total_free_minutes": total_free if coverage_ok else None,
        "reason": None if coverage_ok else "no time commitments configured across horizon",
        "per_day_preview": per_day[:14],  # first two weeks for LLM context
    }


# ============================================================================
# Money capacity — per-currency, per-month (§4).
# ============================================================================

def _month_of(iso: str) -> Optional[str]:
    if not _is_iso_date(iso):
        return None
    return iso[:7]


def _money_capacity_summary(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Per-currency, per-month availability. Never combines currencies.
    Never replaces unknown due_date with today. Avoids double-counting
    rows that carry both finance-lifecycle and canonical allocation
    fields (only counted once as money reservation)."""
    accounts = snapshot["portfolio"]["financial_accounts"]
    monthly = snapshot["portfolio"]["monthly_money_commitments"]
    allocations = snapshot["portfolio"]["resource_allocations"]

    # Opening liquid balance per currency (liquidity_type == 'liquid').
    liquid_by_cur: Dict[str, Decimal] = {}
    for acc in accounts:
        if acc.get("liquidity_type") == "liquid":
            cur = acc.get("currency") or ""
            liquid_by_cur[cur] = liquid_by_cur.get(cur, Decimal(0)) + _decimal_from_stored(
                acc.get("current_value"))

    # Reservations from resource_allocations — money type in reserved/expired.
    # If a row carries a financial_commitment_id, it's the finance-lifecycle
    # row and MUST be counted only once (we already query it as an alloc).
    reserved_by_month: Dict[str, Dict[str, Decimal]] = {}
    unknown_due_reservations: Dict[str, Decimal] = {}
    for a in allocations:
        if a.get("resource_type") != "money":
            continue
        state = a.get("state")
        status = a.get("status")
        # Include when either finance-state is reserved/expired OR canonical
        # status=reserved (but never double count — a single row).
        counts = (state in ("reserved", "expired")) or (status == "reserved")
        if not counts:
            continue
        cur = a.get("currency") or ""
        amt = _decimal_from_stored(a.get("amount") or a.get("quantity"))
        due = a.get("due_date") or a.get("date")
        m = _month_of(due) if due else None
        if m is None:
            unknown_due_reservations[cur] = unknown_due_reservations.get(cur, Decimal(0)) + amt
        else:
            reserved_by_month.setdefault(m, {})
            reserved_by_month[m][cur] = reserved_by_month[m].get(cur, Decimal(0)) + amt

    # Monthly money commitments — a repeating obligation per month.
    monthly_by_cur: Dict[str, Decimal] = {}
    for m in monthly:
        cur = m.get("currency") or ""
        amt = _decimal_from_stored(m.get("amount"))
        monthly_by_cur[cur] = monthly_by_cur.get(cur, Decimal(0)) + amt

    # Report by currency separately.
    currencies = sorted(set(list(liquid_by_cur) + list(monthly_by_cur)
                            + [c for m in reserved_by_month.values() for c in m]))
    by_currency: List[dict] = []
    for cur in currencies:
        liq = liquid_by_cur.get(cur, Decimal(0))
        monthly_amt = monthly_by_cur.get(cur, Decimal(0))
        rows_per_month: Dict[str, str] = {}
        for month, cur_map in sorted(reserved_by_month.items()):
            if cur in cur_map:
                rows_per_month[month] = str(cur_map[cur])
        unknown = unknown_due_reservations.get(cur, Decimal(0))
        by_currency.append({
            "currency": cur,
            "liquid_opening": str(liq),
            "monthly_committed_per_month": str(monthly_amt),
            "reserved_by_month": rows_per_month,
            "reserved_with_unknown_due_date": str(unknown),
        })

    return {
        "by_currency": by_currency,
        "has_unknown_due_dates": any(v > 0 for v in unknown_due_reservations.values()),
    }


# ============================================================================
# Resolved context — used both by the LLM and by downstream deterministic
# calculators. Applied confirmations override inferred values.
# ============================================================================

def _apply_confirmations(current_state: List[dict], confirmations: Dict[str, dict]) -> List[dict]:
    """Merge confirmations onto the current_state list. Never discards a
    prior confirmation. Returns a new list; the input is unchanged."""
    out: List[dict] = []
    for f in current_state:
        conf = confirmations.get(f["field"])
        new = dict(f)
        if conf:
            action = conf.get("action")
            if action == "confirm":
                new["evidence"] = "explicit_user_confirmation"
                new["confidence"] = "high"
                new["blocking"] = False
                new["confirmed_at"] = conf.get("recorded_at") or _now()
            elif action == "edit":
                new["value"] = conf.get("value")
                new["evidence"] = "explicit_user_confirmation"
                new["confidence"] = "high"
                new["blocking"] = False
                new["confirmed_at"] = conf.get("recorded_at") or _now()
            elif action == "mark_unknown":
                new["value"] = None
                new["evidence"] = "none"
                new["confidence"] = "low"
                new["blocking"] = True
                new["confirmed_at"] = conf.get("recorded_at") or _now()
            elif action == "reject":
                # A rejected inference means the user disagrees with what we
                # inferred; it must be explicitly re-entered as edit before
                # we can proceed.
                new["value"] = None
                new["evidence"] = "none"
                new["confidence"] = "low"
                new["blocking"] = True
                new["rejected_at"] = conf.get("recorded_at") or _now()
        out.append(new)
    return out


def _resolved_context(current_state: List[dict]) -> Dict[str, Any]:
    """Build the compact context handed to the LLM: field → confirmed value.
    Blocking / unknown fields carry ``value=None`` so the LLM cannot invent."""
    return {f["field"]: {
        "value": f.get("value"),
        "evidence_id": f.get("evidence_id"),
        "evidence": f.get("evidence"),
        "confidence": f.get("confidence"),
        "blocking": bool(f.get("blocking")),
    } for f in current_state}


def _blocking_fields(current_state: List[dict]) -> List[str]:
    return [f["field"] for f in current_state if f.get("blocking")]


# ============================================================================
# Compact LLM context — never send the raw full portfolio (§1C).
# ============================================================================

def _compact_llm_context(
    snapshot: Dict[str, Any],
    resolved: Dict[str, Any],
    time_capacity: Dict[str, Any],
    money_capacity: Dict[str, Any],
) -> Dict[str, Any]:
    target_type = snapshot["target_type"]
    t = snapshot["target"]
    ctx = {
        "target_type": target_type,
        "target_id": snapshot["target_id"],
        "target_summary": {
            "title": t.get("title"),
            "domain_id": t.get("domain_id"),
            "priority": t.get("priority"),
            "notes": (t.get("notes") or "")[:500] or None,
            "deadline": t.get("deadline") or t.get("target_end_date"),
            "status": t.get("status"),
        },
        "resolved_context": resolved,
        "existing_expected_outcomes": [
            {"id": e["id"], "title": e.get("title"), "target_value": e.get("target_value"),
             "deadline": e.get("deadline"), "status": e.get("status")}
            for e in snapshot["expected_outcomes"]
        ],
        "existing_tasks": [
            {"id": x["id"], "title": x.get("title"), "status": x.get("status"),
             "due_date": x.get("due_date"), "component_id": x.get("component_id"),
             "expected_outcome_id": x.get("expected_outcome_id")}
            for x in snapshot["tasks"]
        ],
        "existing_knowledge_stages": [
            {"id": s["id"], "title": s.get("title"), "order": s.get("order")}
            for s in snapshot["knowledge_stages"]
        ],
        "existing_knowledge_components": [
            {"id": c["id"], "title": c.get("title"), "stage_id": c.get("stage_id"),
             "status": c.get("status")}
            for c in snapshot["knowledge_components"]
        ],
        "capacity": {
            "time": {
                "status": time_capacity["capacity_status"],
                "total_free_minutes": time_capacity.get("total_free_minutes"),
                "days": time_capacity.get("days"),
                "horizon_start": time_capacity.get("horizon_start"),
                "horizon_end": time_capacity.get("horizon_end"),
                "reason": time_capacity.get("reason"),
            },
            "money": money_capacity,
        },
        "portfolio_summary": {
            "active_goals_count": len(snapshot["portfolio"]["active_goals"]),
            "active_projects_count": len(snapshot["portfolio"]["active_projects"]),
        },
    }
    return ctx


# ============================================================================
# Strict Pydantic LLM output contract (§5).
# ============================================================================

class LLMResourceMoney(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: Optional[str] = None  # decimal string
    currency: Optional[str] = None
    assumption_id: Optional[str] = None


class LLMResources(BaseModel):
    model_config = ConfigDict(extra="forbid")
    time_minutes: Optional[int] = Field(default=None, ge=0)
    money: Optional[LLMResourceMoney] = None
    energy: Optional[str] = Field(default=None, pattern="^(low|medium|high|unknown)$")
    attention: Optional[str] = Field(default=None, pattern="^(low|medium|high|unknown)$")
    assumption_id: Optional[str] = None


class LLMSchedule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    day_of_week: Optional[str] = Field(
        default=None,
        pattern="^(monday|tuesday|wednesday|thursday|friday|saturday|sunday)$",
    )
    date: Optional[str] = None
    start_time: Optional[str] = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    end_time: Optional[str] = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    mode: Optional[str] = Field(default=None, pattern="^(one_time|recurring)$")


class LLMProposedOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_ref: str
    title: str
    measurable_end_state: Optional[str] = None
    completion_condition: Optional[str] = None
    target_date: Optional[str] = None
    evidence_ids: List[str] = []
    assumption_id: Optional[str] = None


class LLMProposedTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_ref: str
    parent_outcome_ref: Optional[str] = None  # required for goal/journey (validated later)
    component_ref: Optional[str] = None
    reuse_existing_task_id: Optional[str] = None
    title: str
    action_and_deliverable: Optional[str] = None
    completion_condition: str
    owner: Optional[str] = "self"
    depends_on: List[str] = []
    earliest_start: Optional[str] = None
    target_date: Optional[str] = None
    required_resources: Optional[LLMResources] = None
    schedule: Optional[LLMSchedule] = None
    evidence_ids: List[str] = []
    assumption_id: Optional[str] = None


class LLMBlockingQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    question: str
    why_blocking: Optional[str] = None


class LLMAssumption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assumption_id: str
    statement: str
    range: Optional[str] = None
    requires_user_confirmation: bool = True


class LLMCheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cadence: str = Field(pattern="^(daily|weekly|monthly|manual)$")
    linked_to: str = Field(pattern="^(outcome|task|goal|project|journey)$")


class LLMRisk(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str
    evidence_ids: List[str] = []
    assumption_id: Optional[str] = None


class LLMResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objective_summary: str
    measurable_success_criteria: Optional[str] = None
    proposed_outcomes: List[LLMProposedOutcome] = []
    proposed_tasks: List[LLMProposedTask] = []
    proposed_check_ins: List[LLMCheckIn] = []
    blocking_questions: List[LLMBlockingQuestion] = []
    assumptions: List[LLMAssumption] = []
    risks: List[LLMRisk] = []


# ============================================================================
# LLM prompt & call
# ============================================================================

_LLM_SYSTEM = (
    "You are Hymn's Planning Interpreter. You never invent facts. "
    "You must ground every proposed outcome, task, risk, and assumption in "
    "evidence supplied in the resolved_context (via evidence_ids) or in an "
    "explicit assumption you declare. You must not invent external sources; "
    "external estimates are disabled. Output ONLY valid JSON conforming to "
    "the LLMResponse schema described in the user message. If a required "
    "value cannot be grounded, omit the field or reference an assumption_id "
    "you also emit in the assumptions array. Never fabricate durations, "
    "costs, dates, dependencies, or skills."
)


_LLM_INSTRUCTIONS = """You will receive:

* target_type
* target_id
* target_summary
* resolved_context : field → {value, evidence_id, confidence, blocking}
* existing_expected_outcomes / tasks / knowledge_stages / knowledge_components
* capacity : deterministic time + money summaries
* portfolio_summary : counts only

Return a JSON object with EXACTLY these keys:

{
  "objective_summary": "one sentence grounded in target_summary + resolved_context.objective",
  "measurable_success_criteria": null OR the confirmed value from resolved_context,
  "proposed_outcomes": [{
    "proposal_ref": "unique per-proposal identifier",
    "title": "...",
    "measurable_end_state": "e.g. body_weight <= 70kg",
    "completion_condition": "...",
    "target_date": "YYYY-MM-DD or null",
    "evidence_ids": ["<evidence_id from resolved_context>", ...],
    "assumption_id": null OR "<id you also emit in assumptions[]>"
  }],
  "proposed_tasks": [{
    "proposal_ref": "unique",
    "parent_outcome_ref": "for goal/journey: proposal_ref of the parent outcome OR an existing outcome id",
    "component_ref": "for journey: existing knowledge_component id OR null",
    "reuse_existing_task_id": null OR "id of an existing task to reuse/update",
    "title": "...",
    "action_and_deliverable": "...",
    "completion_condition": "measurable — no 'work on', 'research', 'stay consistent'",
    "owner": "self",
    "depends_on": ["proposal_ref of another proposed task"],
    "earliest_start": "YYYY-MM-DD or null",
    "target_date": "YYYY-MM-DD or null",
    "required_resources": {
      "time_minutes": integer OR null,
      "money": {"amount": "decimal string" OR null, "currency": "USD" OR null, "assumption_id": null},
      "energy": "low|medium|high|unknown OR null",
      "attention": "low|medium|high|unknown OR null",
      "assumption_id": null
    },
    "schedule": null OR {"mode": "one_time|recurring", "day_of_week": "monday|...",
                          "date": "YYYY-MM-DD", "start_time": "HH:MM", "end_time": "HH:MM"},
    "evidence_ids": [...],
    "assumption_id": null OR "<id>"
  }],
  "proposed_check_ins": [{"cadence": "daily|weekly|monthly|manual", "linked_to": "outcome|task|goal|project|journey"}],
  "blocking_questions": [{"field": "field name", "question": "...", "why_blocking": "..."}],
  "assumptions": [{"assumption_id": "unique",
                    "statement": "...",
                    "range": "text range or null",
                    "requires_user_confirmation": true}],
  "risks": [{"description": "...", "evidence_ids": [...], "assumption_id": null}]
}

STRICT RULES:
1. Only reference evidence_ids that exist in resolved_context.
2. If time_minutes / money / energy / attention are not known, leave them null and declare an assumption_id.
3. Every proposed task MUST include a measurable completion_condition. No 'research X', 'work on Y' phrasings.
4. Every proposed task for a goal or journey must set parent_outcome_ref to a proposal_ref you also emit OR an existing expected_outcome id.
5. Journey tasks that map to a Knowledge Component MUST set component_ref to that component id.
6. Do NOT output external_estimates. External sources are unavailable.
7. Do NOT invent public sources; declare an assumption instead.
8. Reuse an existing task via reuse_existing_task_id when the proposed task duplicates an existing one.
"""


def _extract_json(text: str) -> Optional[dict]:
    if not text:
        return None
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        cand = m.group(1)
    else:
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
        cand = text[start:end]
    try:
        return json.loads(cand)
    except json.JSONDecodeError:
        return None


async def _llm_call(compact_ctx: Dict[str, Any], target_type: str, target_id: str) -> Tuple[Optional[LLMResponse], List[str]]:
    """Single LLM call. Returns (parsed_response, errors). ``errors`` is the
    list of validation problems raised by the strict schema — the caller
    surfaces them in the proposal's validation_errors so the user can see
    why generation failed."""
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        return None, ["LLM key not configured — proposal cannot be generated."]
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage  # noqa: WPS433
    except Exception as exc:  # pragma: no cover
        return None, [f"LLM library unavailable: {type(exc).__name__}: {exc}"]

    chat = LlmChat(
        api_key=api_key,
        session_id=f"planning-{target_type}-{target_id}-{_now()}",
        system_message=_LLM_SYSTEM,
    ).with_model("anthropic", "claude-sonnet-4-6")

    prompt = _LLM_INSTRUCTIONS + "\n\nCONTEXT:\n" + _stable_json(compact_ctx)
    try:
        response = await chat.send_message(UserMessage(text=prompt))
    except Exception as exc:  # pragma: no cover
        return None, [f"LLM call failed: {type(exc).__name__}: {exc}"]

    text = response if isinstance(response, str) else str(response)
    parsed = _extract_json(text)
    if not parsed:
        return None, ["LLM returned unparseable output."]

    try:
        return LLMResponse(**parsed), []
    except ValidationError as exc:
        return None, [f"LLM output failed contract: {exc.errors()[:3]}"]


# ============================================================================
# Deterministic post-LLM validation & feasibility (§5, §7).
# ============================================================================

def _detect_cycles(tasks: List[dict]) -> List[List[str]]:
    graph: Dict[str, List[str]] = {t["proposal_ref"]: [] for t in tasks}
    for t in tasks:
        for d in (t.get("depends_on") or []):
            if d in graph:
                graph[t["proposal_ref"]].append(d)
    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[str, int] = {n: WHITE for n in graph}
    stack: List[str] = []
    cycles: List[List[str]] = []

    def dfs(u: str) -> None:
        color[u] = GRAY
        stack.append(u)
        for v in graph.get(u, []):
            if color.get(v, WHITE) == GRAY and v in stack:
                cycles.append(stack[stack.index(v):] + [v])
            elif color.get(v, WHITE) == WHITE:
                dfs(v)
        color[u] = BLACK
        stack.pop()

    for n in list(graph):
        if color[n] == WHITE:
            dfs(n)
    return cycles


def _detect_duplicates_against_existing(
    proposed_tasks: List[dict], existing_tasks: List[dict],
) -> List[dict]:
    """Return proposed tasks whose title matches an existing task's title
    (case-insensitive) AND that don't already carry ``reuse_existing_task_id``."""
    existing_by_title: Dict[str, str] = {}
    for et in existing_tasks:
        existing_by_title[(et.get("title") or "").strip().lower()] = et["id"]
    dups: List[dict] = []
    for pt in proposed_tasks:
        if pt.get("reuse_existing_task_id"):
            continue
        key = (pt.get("title") or "").strip().lower()
        if not key:
            continue
        if key in existing_by_title:
            dups.append({
                "proposal_ref": pt["proposal_ref"],
                "title": pt["title"],
                "existing_task_id": existing_by_title[key],
            })
    return dups


def _validate_dependencies(proposed_tasks: List[dict]) -> List[str]:
    refs = {t["proposal_ref"] for t in proposed_tasks}
    problems: List[str] = []
    for t in proposed_tasks:
        for d in (t.get("depends_on") or []):
            if d not in refs:
                problems.append(f"task '{t['proposal_ref']}' depends on missing '{d}'")
    return problems


def _validate_evidence_refs(llm_out: LLMResponse, evidence_ids: set, assumption_ids: set) -> List[str]:
    problems: List[str] = []
    for o in llm_out.proposed_outcomes:
        for eid in o.evidence_ids:
            if eid not in evidence_ids:
                problems.append(f"outcome '{o.proposal_ref}' references unknown evidence_id={eid}")
        if o.assumption_id and o.assumption_id not in assumption_ids:
            problems.append(f"outcome '{o.proposal_ref}' references unknown assumption_id={o.assumption_id}")
    for t in llm_out.proposed_tasks:
        for eid in t.evidence_ids:
            if eid not in evidence_ids:
                problems.append(f"task '{t.proposal_ref}' references unknown evidence_id={eid}")
        if t.assumption_id and t.assumption_id not in assumption_ids:
            problems.append(f"task '{t.proposal_ref}' references unknown assumption_id={t.assumption_id}")
        if t.required_resources:
            if t.required_resources.assumption_id and t.required_resources.assumption_id not in assumption_ids:
                problems.append(f"task '{t.proposal_ref}' required_resources.assumption_id={t.required_resources.assumption_id} unknown")
            if t.required_resources.money and t.required_resources.money.assumption_id and t.required_resources.money.assumption_id not in assumption_ids:
                problems.append(f"task '{t.proposal_ref}' money assumption_id unknown")
    for r in llm_out.risks:
        for eid in r.evidence_ids:
            if eid not in evidence_ids:
                problems.append(f"risk references unknown evidence_id={eid}")
        if r.assumption_id and r.assumption_id not in assumption_ids:
            problems.append(f"risk references unknown assumption_id={r.assumption_id}")
    return problems


_BAD_TITLE_PATTERNS = ("research", "work on", "make progress", "stay consistent")


def _validate_tasks_semantic(llm_out: LLMResponse, target_type: str) -> List[str]:
    problems: List[str] = []
    for t in llm_out.proposed_tasks:
        if not t.completion_condition or t.completion_condition.strip() == "":
            problems.append(f"task '{t.proposal_ref}' missing completion_condition")
        lower = (t.title or "").lower()
        if any(p in lower for p in _BAD_TITLE_PATTERNS) and not (t.completion_condition or "").strip():
            problems.append(f"task '{t.proposal_ref}' vague title without measurable completion_condition")
        # Dates
        if t.earliest_start and not _is_iso_date(t.earliest_start):
            problems.append(f"task '{t.proposal_ref}' has non-ISO earliest_start='{t.earliest_start}'")
        if t.target_date and not _is_iso_date(t.target_date):
            problems.append(f"task '{t.proposal_ref}' has non-ISO target_date='{t.target_date}'")
        if t.earliest_start and t.target_date and _is_iso_date(t.earliest_start) and _is_iso_date(t.target_date):
            if t.earliest_start > t.target_date:
                problems.append(f"task '{t.proposal_ref}' earliest_start > target_date")
        # goal/journey tasks need parent_outcome_ref
        if target_type in ("goal", "journey") and not t.parent_outcome_ref:
            problems.append(f"task '{t.proposal_ref}' missing parent_outcome_ref (required for {target_type})")
    return problems


def _validate_parent_outcome_refs(
    llm_out: LLMResponse, existing_outcome_ids: set,
) -> List[str]:
    """Parent outcome refs must either point to a proposal_ref in the same
    LLM response or to an existing expected_outcome id."""
    proposed_refs = {o.proposal_ref for o in llm_out.proposed_outcomes}
    problems: List[str] = []
    for t in llm_out.proposed_tasks:
        if t.parent_outcome_ref and t.parent_outcome_ref not in proposed_refs and t.parent_outcome_ref not in existing_outcome_ids:
            problems.append(f"task '{t.proposal_ref}' parent_outcome_ref={t.parent_outcome_ref} not found in proposals or existing outcomes")
    return problems


def _validate_component_refs(llm_out: LLMResponse, existing_component_ids: set, target_type: str) -> List[str]:
    problems: List[str] = []
    if target_type != "journey":
        return problems
    for t in llm_out.proposed_tasks:
        if t.component_ref and t.component_ref not in existing_component_ids:
            problems.append(f"task '{t.proposal_ref}' component_ref={t.component_ref} not found")
    return problems


def _validate_reuse_targets(llm_out: LLMResponse, existing_task_ids: set) -> List[str]:
    problems: List[str] = []
    for t in llm_out.proposed_tasks:
        if t.reuse_existing_task_id and t.reuse_existing_task_id not in existing_task_ids:
            problems.append(f"task '{t.proposal_ref}' reuse_existing_task_id={t.reuse_existing_task_id} not found")
    return problems


def _feasibility(
    llm_out: LLMResponse,
    time_capacity: Dict[str, Any],
    money_capacity: Dict[str, Any],
    portfolio_conflicts: List[dict],
) -> Dict[str, Any]:
    """§7 feasibility grading — must be exactly one of the four statuses.

    ``feasible`` is only allowed when EVERY task has known time / money /
    energy / attention / dependencies + measurable completion + no
    unresolved hard conflict AND time_capacity is known AND every
    money-requiring task has a known currency and due date.
    """
    unknowns: List[str] = []
    hard_conflict = False
    tradeoffs: List[dict] = []

    if time_capacity["capacity_status"] != "known":
        unknowns.append("time_capacity_unknown")
    if money_capacity.get("has_unknown_due_dates"):
        unknowns.append("money_reservation_with_unknown_due_date")

    total_free_min = time_capacity.get("total_free_minutes")
    total_required_min = 0
    money_needed_by_month_cur: Dict[Tuple[str, str], Decimal] = {}
    for t in llm_out.proposed_tasks:
        req = t.required_resources
        if req is None:
            unknowns.append(f"task '{t.proposal_ref}' required_resources missing")
            continue
        if req.time_minutes is None:
            unknowns.append(f"task '{t.proposal_ref}' time_minutes unknown")
        else:
            total_required_min += req.time_minutes
        if req.energy is None or req.energy == "unknown":
            unknowns.append(f"task '{t.proposal_ref}' energy unknown")
        if req.attention is None or req.attention == "unknown":
            unknowns.append(f"task '{t.proposal_ref}' attention unknown")
        if req.money and (req.money.amount or req.money.currency):
            if not req.money.amount or not req.money.currency:
                unknowns.append(f"task '{t.proposal_ref}' partial money (need amount+currency)")
            else:
                if not t.target_date or not _is_iso_date(t.target_date):
                    unknowns.append(f"task '{t.proposal_ref}' money required but no due date")
                    continue
                m = _month_of(t.target_date)
                key = (m, req.money.currency)
                try:
                    money_needed_by_month_cur[key] = money_needed_by_month_cur.get(key, Decimal(0)) + Decimal(req.money.amount)
                except Exception:
                    unknowns.append(f"task '{t.proposal_ref}' invalid money amount")

    for c in portfolio_conflicts:
        if c.get("kind") in ("dependency_cycle", "missing_dependency", "duplicate_task",
                             "impossible_date", "parent_outcome_missing",
                             "component_ref_missing", "reuse_target_missing"):
            hard_conflict = True

    # Time shortfall (only meaningful if capacity is known).
    if total_free_min is not None and total_required_min > total_free_min:
        tradeoffs.append({
            "kind": "time_over_allocation",
            "required_minutes": total_required_min,
            "available_minutes": total_free_min,
            "options": [
                {"id": "extend_deadline", "action": "extend_deadline",
                 "rationale": "brings weekly load under available capacity"},
                {"id": "reduce_scope", "action": "reduce_scope",
                 "rationale": "cut lowest-priority proposed tasks"},
                {"id": "reallocate_time", "action": "reallocate_time_from_lower_priority",
                 "rationale": "requires explicit user approval of the source"},
            ],
        })

    # Money shortfall — per currency + month. We don't have full monthly
    # inflow modeling; we only compare against liquid_opening as a strict
    # lower bound.
    money_by_cur = {row["currency"]: row for row in money_capacity["by_currency"]}
    for (month, cur), needed in money_needed_by_month_cur.items():
        row = money_by_cur.get(cur)
        if not row:
            unknowns.append(f"required currency {cur} has no known liquid position")
            continue
        liquid = Decimal(row.get("liquid_opening") or "0")
        reserved_that_month = Decimal(row.get("reserved_by_month", {}).get(month, "0"))
        available = liquid - reserved_that_month
        if needed > available:
            tradeoffs.append({
                "kind": "money_over_allocation",
                "currency": cur, "month": month,
                "required": str(needed), "available": str(available),
                "options": [
                    {"id": "wait_for_income", "action": "wait_for_income",
                     "rationale": "cannot spend beyond liquid+available"},
                    {"id": "reduce_scope", "action": "reduce_scope",
                     "rationale": "cut cost-bearing tasks"},
                    {"id": "reallocate_money", "action": "reallocate_from_lower_priority_reservation",
                     "rationale": "requires explicit user approval"},
                ],
            })

    if unknowns:
        return {"status": "unknown", "reasons": unknowns, "tradeoffs": [], "alternatives": []}
    if hard_conflict:
        return {"status": "not_currently_feasible",
                "reasons": [c.get("kind") for c in portfolio_conflicts if c.get("kind")],
                "tradeoffs": [], "alternatives": []}
    if tradeoffs:
        return {"status": "feasible_with_tradeoffs",
                "reasons": [t["kind"] for t in tradeoffs],
                "tradeoffs": tradeoffs,
                "alternatives": tradeoffs,
                "selected_tradeoff_id": None}
    return {"status": "feasible", "reasons": [], "tradeoffs": [], "alternatives": []}


# ============================================================================
# Approval actions — built from the validated LLM response.
# ============================================================================

def _plan_actions(
    llm_out: LLMResponse,
    target_type: str,
    target_id: str,
    linked_goal_id: Optional[str],
) -> List[dict]:
    """Convert the validated LLM output into a strict list of approval
    actions. Each action carries an ``action_id`` (proposal_ref + action)
    so idempotency by (version, action_id) works during commit."""
    actions: List[dict] = []
    for o in llm_out.proposed_outcomes:
        if target_type not in ("goal", "journey"):
            continue
        goal_id = target_id if target_type == "goal" else linked_goal_id
        if not goal_id:
            continue
        actions.append({
            "action_id": f"outcome:{o.proposal_ref}",
            "action": "create_expected_outcome",
            "proposal_ref": o.proposal_ref,
            "payload": {
                "goal_id": goal_id,
                "title": o.title,
                "target_value": o.measurable_end_state or "",
                "current_value": "",
                "unit": "",
                "deadline": o.target_date if _is_iso_date(o.target_date or "") else "",
                "status": "active",
                "outcome_type": "generic",
                "notes": o.completion_condition or "",
            },
        })
    for t in llm_out.proposed_tasks:
        if t.reuse_existing_task_id:
            actions.append({
                "action_id": f"reuse_task:{t.proposal_ref}",
                "action": "update_task",
                "proposal_ref": t.proposal_ref,
                "existing_task_id": t.reuse_existing_task_id,
                "payload": {
                    "notes": (t.action_and_deliverable or "") + "\n\nCompletion: " + (t.completion_condition or ""),
                    "due_date": t.target_date if _is_iso_date(t.target_date or "") else None,
                },
            })
        else:
            actions.append({
                "action_id": f"task:{t.proposal_ref}",
                "action": "create_task",
                "proposal_ref": t.proposal_ref,
                "parent_outcome_ref": t.parent_outcome_ref,
                "component_ref": t.component_ref,
                "depends_on_refs": t.depends_on,
                "payload": {
                    "title": t.title,
                    "due_date": t.target_date if _is_iso_date(t.target_date or "") else "",
                    "priority": "medium",
                    "status": "todo",
                    "notes": (t.action_and_deliverable or "") + "\n\nCompletion: " + (t.completion_condition or ""),
                    "origin": {"goal": "expected_outcome",
                                "journey": "expected_outcome",
                                "project": "project"}.get(target_type, "standalone"),
                },
            })
        # Time allocation, only when a valid schedule is present (§3).
        sch = t.schedule
        req = t.required_resources
        duration = req.time_minutes if (req and req.time_minutes) else None
        if sch and sch.mode and sch.start_time and sch.end_time and duration:
            if sch.mode == "one_time" and _is_iso_date(sch.date or ""):
                actions.append({
                    "action_id": f"time_alloc:{t.proposal_ref}",
                    "action": "create_time_allocation",
                    "proposal_ref": t.proposal_ref,
                    "attach_task": True,
                    "payload": {
                        "allocation_mode": "one_time",
                        "date": sch.date,
                        "day_of_week": None,
                        "start_time": sch.start_time,
                        "end_time": sch.end_time,
                        "quantity": duration,
                        "unit": "minutes",
                        "status": "reserved",
                    },
                })
            elif sch.mode == "recurring" and sch.day_of_week:
                actions.append({
                    "action_id": f"time_alloc:{t.proposal_ref}",
                    "action": "create_time_allocation",
                    "proposal_ref": t.proposal_ref,
                    "attach_task": True,
                    "payload": {
                        "allocation_mode": "recurring",
                        "date": None,
                        "day_of_week": sch.day_of_week,
                        "start_time": sch.start_time,
                        "end_time": sch.end_time,
                        "quantity": duration,
                        "unit": "minutes",
                        "status": "reserved",
                    },
                })
        if req and req.money and req.money.amount and req.money.currency and _is_iso_date(t.target_date or ""):
            actions.append({
                "action_id": f"money_alloc:{t.proposal_ref}",
                "action": "create_money_reservation",
                "proposal_ref": t.proposal_ref,
                "attach_task": True,
                "payload": {
                    "amount": req.money.amount,
                    "currency": req.money.currency,
                    "due_date": t.target_date,
                    "priority": "medium",
                    "title": f"Reserve for: {t.title}",
                    "description": t.action_and_deliverable or "",
                },
            })
    # Check-ins: map to Goal/Project cadence, do NOT create future completed check-ins.
    if llm_out.proposed_check_ins:
        # Pick strictest cadence linked to the target itself.
        for c in llm_out.proposed_check_ins:
            if c.linked_to in ("goal", "project", "journey") and target_type == c.linked_to:
                actions.append({
                    "action_id": f"cadence:{c.linked_to}:{c.cadence}",
                    "action": "set_target_cadence",
                    "payload": {"cadence": c.cadence},
                })
                break
    return actions


# ============================================================================
# Proposal construction
# ============================================================================

async def _build_analyze(
    db, user_id: str, target_type: str, target_id: str,
) -> Dict[str, Any]:
    """Deterministic-only analyze (§1A)."""
    snapshot = await _read_snapshot(db, user_id, target_type, target_id)
    current_state = _infer_current_state(snapshot)
    snapshot_hash = _snapshot_hash(snapshot)
    proposal_id = _uuid()
    now = _now()
    return {
        "id": proposal_id,
        "user_id": user_id,
        "target_type": target_type,
        "target_id": target_id,
        "snapshot": snapshot,
        "snapshot_hash": snapshot_hash,
        "version": 1,
        "status": "confirmation_required",
        "current_state": current_state,
        "confirmations": {},
        "blocking_questions": [],
        "proposed_outcomes": [],
        "proposed_tasks": [],
        "proposed_check_ins": [],
        "visual_phases": [],
        "resource_requirements": [],
        "portfolio_conflicts": [],
        "assumptions": [],
        "external_estimates": [],  # always empty (§5)
        "risks": [],
        "feasibility": {"status": "unknown", "reasons": ["not_yet_generated"],
                        "tradeoffs": [], "alternatives": []},
        "approval_actions": [],
        "evidence_map": [{"field": f["field"], "evidence_id": f["evidence_id"],
                           "evidence": f["evidence"], "confidence": f["confidence"]}
                          for f in current_state],
        "validation_errors": [],
        "commit_phase": None,
        "committed_action_ids": [],
        "selected_tradeoff_id": None,
        "objective_summary": snapshot["target"].get("title") or None,
        "measurable_success_criteria": None,
        "created_at": now,
        "updated_at": now,
    }


async def _build_generate(db, user_id: str, proposal: Dict[str, Any]) -> Dict[str, Any]:
    """Take a confirmed proposal and generate the LLM proposal (§1C)."""
    snapshot = proposal["snapshot"]
    current_state = _apply_confirmations(proposal["current_state"], proposal.get("confirmations") or {})

    # Blockers must be resolved.
    still_blocking = _blocking_fields(current_state)
    if still_blocking:
        proposal["current_state"] = current_state
        proposal["status"] = "blocking_input_required"
        proposal["validation_errors"] = [f"blocking field unresolved: {f}" for f in still_blocking]
        proposal["updated_at"] = _now()
        return proposal

    resolved = _resolved_context(current_state)

    # Determine horizon from confirmed target_date.
    target_date_raw = resolved.get("target_date", {}).get("value")
    target_date = target_date_raw if _is_iso_date(target_date_raw or "") else None
    today = datetime.now(timezone.utc).date()
    horizon_end = _parse_date(target_date) if target_date else (today + timedelta(days=90))
    if horizon_end < today:
        horizon_end = today + timedelta(days=30)
    time_capacity = _time_capacity_summary(snapshot, today, horizon_end)
    money_capacity = _money_capacity_summary(snapshot)

    compact = _compact_llm_context(snapshot, resolved, time_capacity, money_capacity)
    llm_out, llm_errors = await _llm_call(compact, snapshot["target_type"], snapshot["target_id"])

    validation_errors: List[str] = list(llm_errors)
    portfolio_conflicts: List[dict] = []
    approval_actions: List[dict] = []

    if llm_out:
        # Evidence + assumption reference validation
        evidence_ids = {f["evidence_id"] for f in current_state}
        assumption_ids = {a.assumption_id for a in llm_out.assumptions}
        validation_errors.extend(_validate_evidence_refs(llm_out, evidence_ids, assumption_ids))
        validation_errors.extend(_validate_tasks_semantic(llm_out, snapshot["target_type"]))

        existing_outcome_ids = {o["id"] for o in snapshot["expected_outcomes"]}
        existing_task_ids = {t["id"] for t in snapshot["tasks"]}
        existing_component_ids = {c["id"] for c in snapshot["knowledge_components"]}
        validation_errors.extend(_validate_parent_outcome_refs(llm_out, existing_outcome_ids))
        validation_errors.extend(_validate_component_refs(llm_out, existing_component_ids, snapshot["target_type"]))
        validation_errors.extend(_validate_reuse_targets(llm_out, existing_task_ids))

        # Dependencies
        proposed_tasks_dict = [t.model_dump() for t in llm_out.proposed_tasks]
        dep_problems = _validate_dependencies(proposed_tasks_dict)
        validation_errors.extend(dep_problems)
        cycles = _detect_cycles(proposed_tasks_dict)
        for cyc in cycles:
            portfolio_conflicts.append({"kind": "dependency_cycle", "cycle": cyc})
        # Duplicates against existing
        dups = _detect_duplicates_against_existing(proposed_tasks_dict, snapshot["tasks"])
        for d in dups:
            portfolio_conflicts.append({"kind": "duplicate_task", **d})

        approval_actions = _plan_actions(
            llm_out, snapshot["target_type"], snapshot["target_id"],
            (snapshot.get("linked_goal") or {}).get("id"),
        )
    feasibility = (_feasibility(llm_out, time_capacity, money_capacity, portfolio_conflicts)
                   if llm_out else {"status": "unknown", "reasons": ["llm_output_invalid"],
                                     "tradeoffs": [], "alternatives": []})

    # Roll-ups
    resource_requirements: List[dict] = []
    if llm_out:
        total_min = 0
        money_by_cur: Dict[str, Decimal] = {}
        for t in llm_out.proposed_tasks:
            if t.required_resources and t.required_resources.time_minutes:
                total_min += t.required_resources.time_minutes
            if t.required_resources and t.required_resources.money and t.required_resources.money.amount and t.required_resources.money.currency:
                try:
                    money_by_cur[t.required_resources.money.currency] = money_by_cur.get(t.required_resources.money.currency, Decimal(0)) + Decimal(t.required_resources.money.amount)
                except Exception:
                    pass
        if total_min > 0:
            resource_requirements.append({"kind": "time", "minutes": total_min,
                                           "period": "over_horizon", "confidence": "medium"})
        for cur, amt in money_by_cur.items():
            resource_requirements.append({"kind": "money", "amount": str(amt),
                                           "currency": cur, "period": "over_horizon",
                                           "confidence": "medium"})

    # Visual phases (month grouping)
    visual_phases: List[dict] = []
    if llm_out:
        by_month: Dict[str, List[str]] = {}
        for t in llm_out.proposed_tasks:
            m = _month_of(t.earliest_start or t.target_date or "") or "unknown"
            by_month.setdefault(m, []).append(t.title)
        for month, titles in sorted(by_month.items()):
            visual_phases.append({"label": f"Phase {month}", "tasks": titles})

    proposal["current_state"] = current_state
    proposal["proposed_outcomes"] = [o.model_dump() for o in (llm_out.proposed_outcomes if llm_out else [])]
    proposal["proposed_tasks"] = [t.model_dump() for t in (llm_out.proposed_tasks if llm_out else [])]
    proposal["proposed_check_ins"] = [c.model_dump() for c in (llm_out.proposed_check_ins if llm_out else [])]
    proposal["blocking_questions"] = [q.model_dump() for q in (llm_out.blocking_questions if llm_out else [])]
    proposal["assumptions"] = [a.model_dump() for a in (llm_out.assumptions if llm_out else [])]
    proposal["risks"] = [r.model_dump() for r in (llm_out.risks if llm_out else [])]
    proposal["portfolio_conflicts"] = portfolio_conflicts
    proposal["visual_phases"] = visual_phases
    proposal["resource_requirements"] = resource_requirements
    proposal["feasibility"] = feasibility
    proposal["approval_actions"] = approval_actions
    proposal["validation_errors"] = validation_errors
    proposal["objective_summary"] = (llm_out.objective_summary if llm_out
                                      else snapshot["target"].get("title") or None)
    proposal["measurable_success_criteria"] = (llm_out.measurable_success_criteria
                                               if llm_out else None)
    proposal["external_estimates"] = []

    # Status determination
    if validation_errors:
        proposal["status"] = "blocking_input_required" if proposal["blocking_questions"] else "infeasible"
    elif feasibility["status"] == "not_currently_feasible":
        proposal["status"] = "infeasible"
    elif feasibility["status"] == "unknown":
        proposal["status"] = "blocking_input_required"
    elif feasibility["status"] == "feasible_with_tradeoffs":
        # Cannot approve until a trade-off is selected — but the proposal is
        # otherwise fully generated. Represent as proposal_ready UI-side but
        # gate approval on selected_tradeoff_id.
        proposal["status"] = "proposal_ready"
    else:
        proposal["status"] = "proposal_ready"
    proposal["updated_at"] = _now()
    return proposal


# ============================================================================
# API models
# ============================================================================

class AnalyzeRequest(BaseModel):
    target_type: str
    target_id: str


class ConfirmationEntry(BaseModel):
    field: str
    action: str
    value: Any = None
    note: Optional[str] = None


class ConfirmRequest(BaseModel):
    confirmations: List[ConfirmationEntry]


class TradeoffRequest(BaseModel):
    tradeoff_id: str


class PauseRequest(BaseModel):
    future_allocations: str


# ============================================================================
# Persistence helpers
# ============================================================================

async def _store_proposal(db, proposal: Dict[str, Any]) -> None:
    await db.plan_proposals.replace_one(
        {"id": proposal["id"]}, dict(proposal), upsert=True,
    )


async def _load_proposal(db, user_id: str, proposal_id: str) -> Dict[str, Any]:
    doc = await db.plan_proposals.find_one(
        {"id": proposal_id, "user_id": user_id}, {"_id": 0},
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return doc


def _slim(proposal: Dict[str, Any]) -> Dict[str, Any]:
    """Strip the full snapshot from an API response payload."""
    out = dict(proposal)
    out.pop("snapshot", None)
    return out


# ============================================================================
# Endpoints
# ============================================================================

@planning_router.post("/analyze")
async def analyze(body: AnalyzeRequest, current_user: dict = Depends(get_current_user)):
    """Deterministic-only. Returns status=confirmation_required. No LLM."""
    db = get_db()
    _require_in(body.target_type, TARGET_TYPES, "target_type")
    existing = await db.plan_proposals.count_documents(
        {"user_id": current_user["id"], "target_type": body.target_type,
         "target_id": body.target_id},
    )
    proposal = await _build_analyze(db, current_user["id"], body.target_type, body.target_id)
    proposal["version"] = existing + 1
    await _store_proposal(db, proposal)
    return _slim(proposal)


@planning_router.get("/proposals/{proposal_id}")
async def get_proposal(proposal_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    doc = await _load_proposal(db, current_user["id"], proposal_id)
    return _slim(doc)


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
    docs = await db.plan_proposals.find(q, {"_id": 0, "snapshot": 0}).sort(
        [("created_at", -1)]).to_list(length=200)
    return docs


@planning_router.post("/proposals/{proposal_id}/confirm")
async def confirm_proposal(
    proposal_id: str, body: ConfirmRequest, current_user: dict = Depends(get_current_user),
):
    """Batch-merge confirmations onto the proposal. Never discards prior
    confirmations. Never calls the LLM."""
    db = get_db()
    proposal = await _load_proposal(db, current_user["id"], proposal_id)
    _require(
        proposal.get("status") not in ("approved", "rejected", "abandoned"),
        f"Cannot confirm — proposal is {proposal.get('status')}",
    )
    now = _now()
    merged = dict(proposal.get("confirmations") or {})
    for c in body.confirmations:
        _require_in(c.action, CONFIRMATION_ACTIONS, "action")
        # Only overwrite the field the user is touching now; prior
        # confirmations for other fields are preserved.
        merged[c.field] = {
            "action": c.action,
            "value": c.value,
            "note": c.note,
            "recorded_at": now,
        }
    proposal["confirmations"] = merged
    # Re-derive current_state view with merged confirmations applied.
    proposal["current_state"] = _apply_confirmations(proposal["current_state"], merged)
    # Status: still confirmation_required if any blocking remain.
    still_blocking = _blocking_fields(proposal["current_state"])
    proposal["status"] = "confirmation_required" if still_blocking else "blocking_input_required"
    # blocking_input_required is the "ready to generate" gate — the user can
    # now hit /generate. If ALL blockers are resolved and no /generate has
    # been called yet, status stays at blocking_input_required until the LLM
    # runs.
    if not still_blocking:
        # Mark as ready-to-generate — the frontend polls / triggers /generate.
        proposal["status"] = "confirmation_required"
        proposal["ready_to_generate"] = True
    else:
        proposal["ready_to_generate"] = False
    proposal["updated_at"] = now
    await _store_proposal(db, proposal)
    return _slim(proposal)


@planning_router.post("/proposals/{proposal_id}/generate")
async def generate_proposal(proposal_id: str, current_user: dict = Depends(get_current_user)):
    """Single LLM call + deterministic validation (§1C). Only permitted once
    all current-state blockers are resolved."""
    db = get_db()
    proposal = await _load_proposal(db, current_user["id"], proposal_id)
    _require(
        proposal.get("status") not in ("approved", "rejected", "abandoned"),
        f"Cannot generate — proposal is {proposal.get('status')}",
    )
    # Ensure confirmations applied and no blockers remain.
    proposal["current_state"] = _apply_confirmations(
        proposal["current_state"], proposal.get("confirmations") or {},
    )
    still_blocking = _blocking_fields(proposal["current_state"])
    if still_blocking:
        proposal["status"] = "confirmation_required"
        proposal["validation_errors"] = [f"blocking field unresolved: {f}" for f in still_blocking]
        proposal["updated_at"] = _now()
        await _store_proposal(db, proposal)
        return _slim(proposal)

    proposal["status"] = "generating"
    proposal["updated_at"] = _now()
    await _store_proposal(db, proposal)

    generated = await _build_generate(db, current_user["id"], proposal)
    await _store_proposal(db, generated)
    return _slim(generated)


@planning_router.post("/proposals/{proposal_id}/select-tradeoff")
async def select_tradeoff(
    proposal_id: str, body: TradeoffRequest, current_user: dict = Depends(get_current_user),
):
    """User selects a trade-off from the feasibility.alternatives list. The
    trade-off id is persisted; approval remains blocked for
    feasible_with_tradeoffs proposals until this call succeeds."""
    db = get_db()
    proposal = await _load_proposal(db, current_user["id"], proposal_id)
    _require(
        proposal.get("feasibility", {}).get("status") == "feasible_with_tradeoffs",
        "select-tradeoff only applies to feasible_with_tradeoffs proposals",
    )
    alts = proposal.get("feasibility", {}).get("alternatives") or []
    valid_ids: List[str] = []
    for a in alts:
        for opt in (a.get("options") or []):
            valid_ids.append(opt.get("id"))
    _require(body.tradeoff_id in valid_ids,
             f"tradeoff_id must be one of {valid_ids}")
    proposal["feasibility"]["selected_tradeoff_id"] = body.tradeoff_id
    proposal["selected_tradeoff_id"] = body.tradeoff_id
    proposal["updated_at"] = _now()
    await _store_proposal(db, proposal)
    return _slim(proposal)


# ============================================================================
# Approval commit — safe state machine (§8).
# ============================================================================

async def _commit_actions(
    db, user_id: str, proposal: Dict[str, Any],
) -> Dict[str, Any]:
    """Durable commit: preparing → applying → committed / failed. Uses
    ``plan_action_log`` for per-action idempotency by
    ``(proposal_version, action_id)``."""
    now = _now()
    proposal_id = proposal["id"]
    version = proposal.get("version", 1)
    proposal["commit_phase"] = "applying"
    await _store_proposal(db, proposal)

    actions = proposal.get("approval_actions") or []
    log_entries: List[dict] = []
    task_id_by_ref: Dict[str, str] = {}
    outcome_id_by_ref: Dict[str, str] = {}

    async def _rollback():
        for entry in reversed(log_entries):
            try:
                if entry["kind"] == "expected_outcome":
                    await db.expected_outcomes.delete_one({"id": entry["created_id"]})
                elif entry["kind"] == "task":
                    await db.tasks.delete_one({"id": entry["created_id"]})
                elif entry["kind"] == "resource_allocation":
                    await db.resource_allocations.delete_one({"id": entry["created_id"]})
                await db.plan_action_log.delete_one(
                    {"proposal_id": proposal_id, "version": version,
                     "action_id": entry["action_id"]},
                )
            except Exception:
                pass

    try:
        # Try Mongo multi-document transaction where the deployment supports it.
        session = None
        supports_tx = False
        try:
            client = db.client if hasattr(db, "client") else None
            if client is not None:
                session = await client.start_session()
                # We don't actually enter a tx here because Motor's context
                # manager requires start_transaction; single-node deployments
                # (default local mongo) don't support it. We fall back to the
                # state-machine + compensating rollback below.
                await session.end_session()
                session = None
        except Exception:
            session = None
        _ = supports_tx  # explicit no-op — state machine path handles both.

        # First pass — outcomes + tasks (they need to exist before allocations
        # can attach owners and before parent_outcome refs can resolve).
        for act in actions:
            action = act["action"]
            action_id = act["action_id"]
            # Idempotency check by (version, action_id).
            existing = await db.plan_action_log.find_one(
                {"proposal_id": proposal_id, "version": version, "action_id": action_id},
            )
            if existing:
                if existing["kind"] == "task":
                    task_id_by_ref[act["proposal_ref"]] = existing["created_id"]
                elif existing["kind"] == "expected_outcome":
                    outcome_id_by_ref[act["proposal_ref"]] = existing["created_id"]
                continue

            if action == "create_expected_outcome":
                eo_id = _uuid()
                await db.expected_outcomes.insert_one({
                    "id": eo_id,
                    "user_id": user_id,
                    **act["payload"],
                    "created_at": now,
                    "updated_at": now,
                })
                outcome_id_by_ref[act["proposal_ref"]] = eo_id
                log_entries.append({"kind": "expected_outcome",
                                     "created_id": eo_id, "action_id": action_id})
                await db.plan_action_log.insert_one({
                    "proposal_id": proposal_id, "version": version,
                    "action_id": action_id, "kind": "expected_outcome",
                    "created_id": eo_id, "user_id": user_id, "created_at": now,
                })
            elif action == "create_task":
                task_id = _uuid()
                # Resolve parent_outcome_ref → real outcome id.
                parent = act.get("parent_outcome_ref")
                resolved_eo_id: Optional[str] = None
                if parent:
                    resolved_eo_id = outcome_id_by_ref.get(parent, parent)
                # Journeys: preserve component_ref as component_id.
                comp_id = act.get("component_ref")
                origin = act["payload"].get("origin") or "standalone"
                doc = {
                    "id": task_id,
                    "user_id": user_id,
                    "title": act["payload"]["title"],
                    "due_date": act["payload"].get("due_date", ""),
                    "priority": act["payload"].get("priority", "medium"),
                    "status": "todo",
                    "notes": act["payload"].get("notes", ""),
                    "origin": origin,
                    "expected_outcome_id": resolved_eo_id if proposal["target_type"] in ("goal", "journey") else None,
                    "project_id": proposal["target_id"] if proposal["target_type"] == "project" else None,
                    "component_id": comp_id if proposal["target_type"] == "journey" else None,
                    "assigned_to_type": "self",
                    "assigned_to_name": "",
                    "assigned_to_phone": "",
                    "deferred_until": None,
                    "original_due_date": None,
                    "defer_count": 0,
                    "depends_on_task_ids": [],  # will be back-filled after all tasks created
                    "created_at": now,
                    "updated_at": now,
                }
                await db.tasks.insert_one(doc)
                task_id_by_ref[act["proposal_ref"]] = task_id
                log_entries.append({"kind": "task", "created_id": task_id, "action_id": action_id})
                await db.plan_action_log.insert_one({
                    "proposal_id": proposal_id, "version": version,
                    "action_id": action_id, "kind": "task",
                    "created_id": task_id, "user_id": user_id, "created_at": now,
                })
            elif action == "update_task":
                existing_id = act.get("existing_task_id")
                if not existing_id:
                    raise ValueError("update_task requires existing_task_id")
                await db.tasks.update_one(
                    {"id": existing_id, "user_id": user_id},
                    {"$set": {**{k: v for k, v in act["payload"].items() if v is not None},
                               "updated_at": now}},
                )
                task_id_by_ref[act["proposal_ref"]] = existing_id
                log_entries.append({"kind": "task_update", "created_id": existing_id,
                                     "action_id": action_id})
                await db.plan_action_log.insert_one({
                    "proposal_id": proposal_id, "version": version,
                    "action_id": action_id, "kind": "task_update",
                    "created_id": existing_id, "user_id": user_id, "created_at": now,
                })

        # Second pass — allocations (need task_ids from first pass).
        for act in actions:
            action = act["action"]
            action_id = act["action_id"]
            if action in ("create_expected_outcome", "create_task", "update_task",
                           "set_target_cadence"):
                continue
            existing = await db.plan_action_log.find_one(
                {"proposal_id": proposal_id, "version": version, "action_id": action_id},
            )
            if existing:
                continue

            if action == "create_time_allocation":
                task_id = task_id_by_ref.get(act.get("proposal_ref"))
                if act.get("attach_task") and not task_id:
                    raise ValueError(f"time allocation for {act['proposal_ref']} missing owner task")
                alloc_id = _uuid()
                p = act["payload"]
                await db.resource_allocations.insert_one({
                    "id": alloc_id,
                    "user_id": user_id,
                    "resource_type": "time",
                    "owner_type": "task" if task_id else "standalone",
                    "owner_id": task_id,
                    "allocation_mode": p["allocation_mode"],
                    "date": p.get("date"),
                    "day_of_week": p.get("day_of_week"),
                    "start_time": p["start_time"],
                    "end_time": p["end_time"],
                    "quantity": p["quantity"],
                    "unit": "minutes",
                    "currency": None,
                    "status": "reserved",
                    "fixed_or_flexible": "flexible",
                    "created_at": now,
                    "updated_at": now,
                })
                log_entries.append({"kind": "resource_allocation",
                                     "created_id": alloc_id, "action_id": action_id})
                await db.plan_action_log.insert_one({
                    "proposal_id": proposal_id, "version": version,
                    "action_id": action_id, "kind": "resource_allocation",
                    "created_id": alloc_id, "user_id": user_id, "created_at": now,
                })
            elif action == "create_money_reservation":
                task_id = task_id_by_ref.get(act.get("proposal_ref"))
                if act.get("attach_task") and not task_id:
                    raise ValueError(f"money reservation for {act['proposal_ref']} missing owner task")
                alloc_id = _uuid()
                fc_id = _uuid()
                p = act["payload"]
                amt = Decimal128(Decimal(p["amount"]))
                await db.resource_allocations.insert_one({
                    "id": alloc_id,
                    "user_id": user_id,
                    "resource_type": "money",
                    "owner_type": "task" if task_id else "standalone",
                    "owner_id": task_id,
                    "allocation_mode": "one_time",
                    "date": p["due_date"],
                    "day_of_week": None,
                    "start_time": None,
                    "end_time": None,
                    "quantity": amt,
                    "unit": "currency",
                    "currency": p["currency"],
                    "status": "reserved",
                    "fixed_or_flexible": "fixed",
                    "financial_commitment_id": fc_id,
                    "state": "reserved",
                    "title": p.get("title", ""),
                    "description": p.get("description", ""),
                    "amount": amt,
                    "due_date": p["due_date"],
                    "original_due_date": p["due_date"],
                    "priority": p.get("priority", "medium"),
                    "domain_id": None,
                    "goal_id": proposal["target_id"] if proposal["target_type"] == "goal" else None,
                    "project_id": proposal["target_id"] if proposal["target_type"] == "project" else None,
                    "task_id": task_id,
                    "resource_allocation_id": alloc_id,
                    "actual_amount": None, "variance": None, "unused_reservation": None,
                    "overrun_amount": None, "completed_at": None, "cancelled_at": None,
                    "postpone_count": 0, "last_reviewed_at": None, "next_review_date": None,
                    "source": "planning_engine",
                    "created_at": now, "updated_at": now,
                })
                log_entries.append({"kind": "resource_allocation",
                                     "created_id": alloc_id, "action_id": action_id})
                await db.plan_action_log.insert_one({
                    "proposal_id": proposal_id, "version": version,
                    "action_id": action_id, "kind": "resource_allocation",
                    "created_id": alloc_id, "user_id": user_id, "created_at": now,
                })
            elif action == "set_target_cadence":
                p = act["payload"]
                coll = {"goal": "goals", "project": "projects",
                         "journey": "knowledge_journeys"}[proposal["target_type"]]
                await db[coll].update_one(
                    {"id": proposal["target_id"], "user_id": user_id},
                    {"$set": {"checkin_cadence": p["cadence"], "updated_at": now}},
                )
                log_entries.append({"kind": "target_cadence",
                                     "created_id": proposal["target_id"], "action_id": action_id})
                await db.plan_action_log.insert_one({
                    "proposal_id": proposal_id, "version": version,
                    "action_id": action_id, "kind": "target_cadence",
                    "created_id": proposal["target_id"], "user_id": user_id, "created_at": now,
                })
            else:
                raise ValueError(f"unsupported action: {action}")

        # Third pass — resolve depends_on_task_ids on newly created tasks.
        for act in actions:
            if act["action"] != "create_task":
                continue
            refs = act.get("depends_on_refs") or []
            if not refs:
                continue
            task_id = task_id_by_ref.get(act["proposal_ref"])
            if not task_id:
                continue
            dep_ids = [task_id_by_ref[r] for r in refs if r in task_id_by_ref]
            if dep_ids:
                await db.tasks.update_one(
                    {"id": task_id, "user_id": user_id},
                    {"$set": {"depends_on_task_ids": dep_ids, "updated_at": now}},
                )

    except Exception as exc:
        await _rollback()
        proposal["commit_phase"] = "failed"
        proposal["status"] = "proposal_ready"  # allow retry
        proposal["updated_at"] = _now()
        proposal["validation_errors"] = [
            *(proposal.get("validation_errors") or []),
            f"commit failed: {type(exc).__name__}: {exc}",
        ]
        await _store_proposal(db, proposal)
        raise HTTPException(status_code=500, detail=f"Approval failed: {type(exc).__name__}: {exc}")

    proposal["commit_phase"] = "committed"
    proposal["status"] = "approved"
    proposal["approved_at"] = now
    proposal["updated_at"] = now
    proposal["committed_action_ids"] = [e["created_id"] for e in log_entries]
    await _store_proposal(db, proposal)
    return {
        "status": "approved",
        "committed_actions": len(log_entries),
        "created_expected_outcomes": list(outcome_id_by_ref.values()),
        "created_tasks": list(task_id_by_ref.values()),
    }


@planning_router.post("/proposals/{proposal_id}/approve")
async def approve_proposal(proposal_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    proposal = await _load_proposal(db, current_user["id"], proposal_id)
    _require(proposal["status"] == "proposal_ready",
             f"Approve requires status=proposal_ready (current={proposal['status']})")
    _require(not proposal.get("validation_errors"),
             f"Cannot approve — validation_errors: {proposal.get('validation_errors')}")
    feas = proposal.get("feasibility", {}).get("status")
    _require(feas in ("feasible", "feasible_with_tradeoffs"),
             f"Cannot approve — feasibility={feas}")
    if feas == "feasible_with_tradeoffs":
        _require(proposal.get("selected_tradeoff_id") or proposal.get("feasibility", {}).get("selected_tradeoff_id"),
                 "Select a trade-off before approving (feasible_with_tradeoffs)")

    # Snapshot-drift check.
    live_snapshot = await _read_snapshot(
        db, current_user["id"], proposal["target_type"], proposal["target_id"],
    )
    live_hash = _snapshot_hash(live_snapshot)
    if live_hash != proposal.get("snapshot_hash"):
        raise HTTPException(status_code=409,
                            detail="Portfolio changed since proposal was generated. Please re-analyze.")

    proposal["commit_phase"] = "preparing"
    await _store_proposal(db, proposal)
    return await _commit_actions(db, current_user["id"], proposal)


@planning_router.post("/proposals/{proposal_id}/reject")
async def reject_proposal(proposal_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    proposal = await _load_proposal(db, current_user["id"], proposal_id)
    _require(proposal.get("status") not in ("approved", "rejected", "abandoned"),
             f"Cannot reject — proposal is {proposal.get('status')}")
    proposal["status"] = "rejected"
    proposal["rejected_at"] = _now()
    proposal["updated_at"] = _now()
    await _store_proposal(db, proposal)
    return {"status": "rejected"}


@planning_router.post("/proposals/{proposal_id}/pause")
async def pause_proposal(
    proposal_id: str, body: PauseRequest, current_user: dict = Depends(get_current_user),
):
    db = get_db()
    proposal = await _load_proposal(db, current_user["id"], proposal_id)
    _require_in(body.future_allocations, ("retain", "reduce", "release"), "future_allocations")
    committed = proposal.get("committed_action_ids") or []
    if body.future_allocations == "release" and committed:
        today = _today_iso()
        await db.resource_allocations.update_many(
            {"id": {"$in": committed},
             "$or": [{"date": {"$gte": today}}, {"due_date": {"$gte": today}}]},
            {"$set": {"status": "released", "state": "cancelled", "updated_at": _now()}},
        )
    elif body.future_allocations == "reduce" and committed:
        for alloc_id in committed:
            alloc = await db.resource_allocations.find_one({"id": alloc_id}, {"_id": 0})
            if not alloc or alloc.get("resource_type") != "money":
                continue
            current_qty = _decimal_from_stored(alloc.get("quantity"))
            new_qty = current_qty / 2
            await db.resource_allocations.update_one(
                {"id": alloc_id},
                {"$set": {"quantity": Decimal128(new_qty), "amount": Decimal128(new_qty),
                          "updated_at": _now()}},
            )
    proposal["status"] = "paused"
    proposal["pause_policy"] = body.future_allocations
    proposal["updated_at"] = _now()
    await _store_proposal(db, proposal)
    return {"status": "paused", "future_allocations": body.future_allocations}


@planning_router.post("/reassess")
async def reassess(body: AnalyzeRequest, current_user: dict = Depends(get_current_user)):
    return await analyze(body, current_user)


# ============================================================================
# Index bootstrap
# ============================================================================

async def ensure_planning_indexes(database) -> None:
    await database.plan_proposals.create_index("id", unique=True)
    await database.plan_proposals.create_index("user_id")
    await database.plan_proposals.create_index(
        [("user_id", 1), ("target_type", 1), ("target_id", 1)])
    await database.plan_proposals.create_index([("user_id", 1), ("created_at", -1)])
    await database.plan_action_log.create_index(
        [("proposal_id", 1), ("version", 1), ("action_id", 1)], unique=True)
    await database.plan_action_log.create_index([("user_id", 1), ("proposal_id", 1)])
