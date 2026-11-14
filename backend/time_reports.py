"""The three time statements, weekly (168 hours = 10,080 minutes).

* **Statement of Time Commitments** (like Net Worth): what the week is
  already committed to (fixed blocks, flexible blocks, time set aside for
  tasks) and the free time that's left; below it, *time assets*: hours this
  year per area.
* **Time Spent** (like Income & Expenditure): per area, planned vs actual vs
  gap, opening into lines (blocks by title, check-ins by goal). Actual =
  check-ins (with their duration) + fixed blocks taken as kept (sleep, work
  hours) until the watch and calendar can confirm them. Whatever isn't
  accounted for is **Soul**, shown only above 30% of the week.
* **Time Flow** (like Cash Flow): planned free time − overruns + skipped
  plans = untracked time.

Sleep counts under Health (owner decision).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date as date_type, timedelta
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query

import time_service
from deps import get_current_user, get_db

time_reports_router = APIRouter(prefix="/reports/time", tags=["reports"])

WEEK = 7 * 24 * 60
SOUL_SHOW_AT = 0.30
AREAS = [("work", "Work"), ("health", "Health"), ("family", "Family & Relationships"), ("learning", "Learning"),
         ("money", "Money"), ("commute", "Commute"), ("home", "Home & chores"), ("personal", "Personal"),
         ("other", "Other")]
AREA_LABEL = dict(AREAS)

# Time-block types → (area, line label).
BLOCK_AREA = {"sleep": ("health", "Sleep"), "work": ("work", "Work"), "commute": ("commute", "Commute"),
              "study": ("learning", "Study"), "meal": ("health", "Meals"), "caregiving": ("family", "Caregiving"),
              "household": ("home", "Household"), "health": ("health", "Health"), "personal": ("personal", "Personal"),
              "other": ("other", "Other")}


def area_of_domain(name: str) -> str:
    n = (name or "").lower()
    for key, words in (("work", ("work", "career", "job", "office")), ("health", ("health", "fitness")),
                       ("family", ("family", "relation", "friends")), ("learning", ("learn", "knowledge", "study")),
                       ("money", ("money", "finance", "wealth"))):
        if any(w in n for w in words):
            return key
    return "other"


def _hours(minutes: float) -> str:
    return f"{minutes / 60:.1f}"


def _block_minutes_on(block: dict, day: date_type) -> int:
    """Minutes this weekly block starts on ``day`` (the whole block, also the
    part after midnight)."""
    if block.get("day_of_week") != time_service._weekday_name(day):
        return 0
    iso = day.isoformat()
    if (block.get("effective_from") or "") > iso or (block.get("effective_until") and block["effective_until"] < iso):
        return 0
    try:
        start = time_service.hhmm_to_minutes(block["start_time"])
        end = time_service.hhmm_to_minutes(block["end_time"])
    except (KeyError, ValueError):
        return 0
    return end - start if end > start else 1440 - start + end


def planned(blocks: List[dict], reservations: List[dict], week: List[date_type]) -> dict:
    """{area: {line: minutes}} planned, and which lines are fixed."""
    out: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    fixed: Dict[Tuple[str, str], int] = defaultdict(int)
    for b in blocks:
        mins = sum(_block_minutes_on(b, d) for d in week)
        if not mins:
            continue
        area, label = BLOCK_AREA.get(b.get("commitment_type") or "other", ("other", "Other"))
        line = b.get("title") or label
        out[area][line] += mins
        if b.get("flexibility") == "fixed":
            fixed[(area, line)] += mins
    days = {d.isoformat() for d in week}
    names = {time_service._weekday_name(d) for d in week}
    for r in reservations:
        if r.get("allocation_mode") == "one_time" and r.get("date") not in days:
            continue
        if r.get("allocation_mode") == "recurring" and r.get("day_of_week") not in names:
            continue
        try:
            mins = time_service.hhmm_to_minutes(r["end_time"]) - time_service.hhmm_to_minutes(r["start_time"])
        except (KeyError, ValueError):
            continue
        if mins > 0:
            out[r.get("_area", "other")][r.get("_label") or "Time set aside"] += mins
    return {"lines": out, "fixed": fixed}


def actual(plan: dict, checkins: List[dict]) -> Dict[str, Dict[str, int]]:
    """Fixed blocks taken as kept, plus check-ins with their duration."""
    out: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for (area, line), mins in plan["fixed"].items():
        out[area][line] += mins
    for c in checkins:
        mins = int(c.get("duration_minutes") or 0)
        if mins:
            out[c["_area"]][c["_label"]] += mins
    return out


def build(plan: dict, done: Dict[str, Dict[str, int]]) -> dict:
    """Time Spent and Time Flow from planned and actual minutes."""
    rows, flow_over, flow_skip = [], 0, 0
    total_planned = total_actual = 0
    kept = 0
    for key, label in AREAS:
        p_lines, a_lines = plan["lines"].get(key, {}), done.get(key, {})
        p, a = sum(p_lines.values()), sum(a_lines.values())
        if not p and not a:
            continue
        total_planned += p
        total_actual += a
        if a > p:
            flow_over += a - p
        else:
            flow_skip += p - a
        # Waking hours spent as planned (sleep isn't waking time).
        kept += min(p, a) - (min(p_lines.get("Sleep", 0), a_lines.get("Sleep", 0)) if key == "health" else 0)
        lines = sorted(set(p_lines) | set(a_lines))
        rows.append({"area": key, "label": label, "planned_hours": _hours(p), "actual_hours": _hours(a),
                     "gap_hours": _hours(a - p),
                     "lines": [{"label": n, "planned_hours": _hours(p_lines.get(n, 0)),
                                "actual_hours": _hours(a_lines.get(n, 0))} for n in lines]})
    untracked = max(WEEK - total_actual, 0)
    sleep = done.get("health", {}).get("Sleep", 0)
    waking = max(WEEK - sleep, 1)
    planned_free = WEEK - total_planned
    return {
        "spent": {"areas": rows, "planned_hours": _hours(total_planned), "actual_hours": _hours(total_actual),
                  "soul_hours": _hours(untracked), "soul_share_percent": f"{untracked / WEEK * 100:.0f}",
                  "show_soul": untracked / WEEK > SOUL_SHOW_AT,
                  "waking_hours_as_planned_percent": f"{kept / waking * 100:.0f}"},
        "flow": {"planned_free_hours": _hours(planned_free), "overruns_hours": _hours(-flow_over),
                 "skipped_plans_hours": _hours(flow_skip), "untracked_hours": _hours(untracked),
                 "adds_up": planned_free - flow_over + flow_skip == untracked},
    }


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

async def _areas_for_goals(db, user_id: str) -> Dict[str, Tuple[str, str]]:
    domains = {d["id"]: d.get("name", "") for d in await db.domains.find(
        {"user_id": user_id}, {"_id": 0, "id": 1, "name": 1}).to_list(length=None)}
    return {g["id"]: (area_of_domain(domains.get(g.get("domain_id"), "")), g.get("title") or "")
            for g in await db.goals.find({"user_id": user_id}, {"_id": 0, "id": 1, "domain_id": 1, "title": 1})
            .to_list(length=None)}


@time_reports_router.get("")
async def time_statements(week_start: Optional[str] = Query(None, description="Monday, YYYY-MM-DD"),
                          current_user: dict = Depends(get_current_user)):
    """All three time statements for one week, in one call."""
    db, uid = get_db(), current_user["id"]
    try:
        monday = date_type.fromisoformat(week_start) if week_start else date_type.today()
    except ValueError:
        raise HTTPException(status_code=400, detail="week_start must be YYYY-MM-DD")
    monday -= timedelta(days=monday.weekday())
    week = [monday + timedelta(days=i) for i in range(7)]
    first, last = week[0].isoformat(), week[-1].isoformat()

    goals = await _areas_for_goals(db, uid)
    blocks = await db.time_commitments.find({"user_id": uid}, {"_id": 0}).to_list(length=None)
    reservations = await db.resource_allocations.find(
        {"user_id": uid, "resource_type": "time", "status": {"$in": ["reserved", "consumed"]}},
        {"_id": 0}).to_list(length=None)
    plan = planned(blocks, reservations, week)

    def tag(c):
        area, title = goals.get(c.get("goal_id"), ("other", ""))
        return {**c, "_area": area, "_label": title or c.get("title") or "Check-ins"}

    week_checkins = [tag(c) for c in await db.checkins.find(
        {"user_id": uid, "date": {"$gte": first, "$lte": last}},
        {"_id": 0, "goal_id": 1, "title": 1, "duration_minutes": 1}).to_list(length=None)]
    done = actual(plan, week_checkins)
    stmts = build(plan, done)

    fixed_total = sum(plan["fixed"].values())
    planned_total = sum(sum(v.values()) for v in plan["lines"].values())
    year_checkins = [tag(c) for c in await db.checkins.find(
        {"user_id": uid, "date": {"$gte": f"{monday.year}-01-01", "$lte": last}, "duration_minutes": {"$gt": 0}},
        {"_id": 0, "goal_id": 1, "title": 1, "duration_minutes": 1}).to_list(length=None)]
    assets: Dict[str, int] = defaultdict(int)
    for c in year_checkins:
        assets[c["_area"]] += int(c["duration_minutes"])
    return {
        "week_start": first, "week_end": last, "total_hours": "168.0",
        "commitments": {
            "fixed_hours": _hours(fixed_total),
            "flexible_and_set_aside_hours": _hours(planned_total - fixed_total),
            "free_hours": _hours(WEEK - planned_total),
            "total_hours": "168.0",
            "time_assets_this_year": [{"area": a, "label": AREA_LABEL.get(a, a), "hours": _hours(m)}
                                      for a, m in sorted(assets.items(), key=lambda kv: -kv[1])],
        },
        **stmts,
        "untimed_checkins": sum(1 for c in week_checkins if not c.get("duration_minutes")),
    }
