"""Planning engine: what must go right, what may stop it, and does it fit.

One engine for any ask, from "45 minutes of guitar this week" to "house at
29, wedding at 30, a child by 32". A plan has a target date **T** and:

* **must go right**: requirements. Each is a *time* need (minutes, inside a
  window of hours and days), a *money* need (an amount by a date) or a
  *condition* (something only the person can confirm: "partner agrees",
  "credit score 750+").
* **may stop it**: risks, each with an early-warning sign Hymn can watch and
  a way to soften it.

Every requirement is benchmarked, by code and never by the AI, against
(a) **what's available now** and (b) **what can be built up by T−1** (the
period just before the date):

* time: free time in the person's real week between now and the needed-by
  date (time blocks and booked time taken out); time can't be saved, so (b)
  is the free time still to come before then;
* money: (a) money available to spend today (liquid, minus what's set
  aside), (b) that plus month-by-month planned income, bills, savings
  moves, set-aside spends and usual everyday spending up to the month
  before;
* condition: what the person answered (yes / no / not yet).

Status per requirement: ``now`` (covered today), ``by_then`` (covered by
T−1), ``short`` (with the gap) or ``unknown``. The verdict is the worst of
them. Templates for big life events, the AI conversation and money tools
build on this.
"""
from __future__ import annotations

import uuid
from datetime import date as date_type, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import time_service
from deps import get_current_user, get_db

life_plans_router = APIRouter(prefix="/life-plans", tags=["life-plans"])

AREAS = ("money", "health", "family", "learning", "work", "time")
ZERO = Decimal(0)
DEFAULT_EARLIEST, DEFAULT_LATEST = "06:00", "22:30"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


# ---------------------------------------------------------------------------
# Find time
# ---------------------------------------------------------------------------

def busy_intervals(day: date_type, blocks: List[dict], bookings: List[dict]) -> List[tuple]:
    """Busy minutes of one day: weekly blocks (with last night's overnight
    spill) and booked time."""
    iso, name = day.isoformat(), time_service._weekday_name(day)
    prev = day - timedelta(days=1)
    prev_iso, prev_name = prev.isoformat(), time_service._weekday_name(prev)
    out = []
    for b in blocks:
        def active(on: str) -> bool:
            return (b.get("effective_from") or "") <= on and not (b.get("effective_until") and b["effective_until"] < on)
        try:
            if b.get("day_of_week") == name and active(iso):
                out.append(time_service.commitment_interval(b))
            if b.get("day_of_week") == prev_name and active(prev_iso) and time_service.is_overnight(b):
                out.append((0, time_service.hhmm_to_minutes(b["end_time"])))
        except (RuntimeError, ValueError, KeyError):
            continue
    for r in bookings:
        if (r.get("allocation_mode") == "one_time" and r.get("date") == iso) or \
                (r.get("allocation_mode") == "recurring" and r.get("day_of_week") == name):
            try:
                out.append((time_service.hhmm_to_minutes(r["start_time"]), time_service.hhmm_to_minutes(r["end_time"])))
            except (ValueError, KeyError):
                continue
    return out


def free_slots(days: List[date_type], blocks: List[dict], bookings: List[dict], earliest: str, latest: str,
               min_block: int, now: Optional[datetime] = None, weekdays: Optional[List[str]] = None) -> List[dict]:
    """Free windows of at least ``min_block`` minutes, inside earliest–latest
    on each day (and not in the past)."""
    lo, hi = time_service.hhmm_to_minutes(earliest), time_service.hhmm_to_minutes(latest)
    slots = []
    for day in days:
        if weekdays and time_service._weekday_name(day) not in weekdays:
            continue
        start = lo
        if now and day == now.date():
            start = max(start, now.hour * 60 + now.minute + 15)  # a little notice
        busy = sorted(i for i in busy_intervals(day, blocks, bookings) if i[1] > start and i[0] < hi)
        cursor = start
        for s, e in busy + [(hi, hi)]:
            if s - cursor >= min_block:
                slots.append({"date": day.isoformat(), "start": _hm(cursor), "end": _hm(min(s, hi)),
                              "minutes": min(s, hi) - cursor})
            cursor = max(cursor, e)
            if cursor >= hi:
                break
    return slots


# ---------------------------------------------------------------------------
# Benchmarks
# ---------------------------------------------------------------------------

def _dec(v: Any) -> Decimal:
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError):
        return ZERO


def _month_add(month: str, n: int) -> str:
    y, m = int(month[:4]), int(month[5:7]) - 1 + n
    return f"{y + m // 12}-{m % 12 + 1:02d}"


async def money_by(db, user_id: str, currency: str, by: str, plan_id: Optional[str] = None) -> Dict[str, Decimal]:
    """Money available today, and projected for the end of the month before
    ``by`` (T−1): planned money in and out, savings moves, set-aside spends
    and usual everyday spending, month by month (the forecast's rules)."""
    import finance_manager
    import planned_money
    from money_service import load_availability, monthly_actual_spending

    avail = (await load_availability(db, user_id))["by_currency"].get(currency, {})
    now_amount = Decimal(avail.get("available_unreserved", 0))
    # A plan's own savings are money kept for it, not money gone.
    items = [i for i in await planned_money.load_items(db, user_id)
             if not (plan_id and i.get("life_plan_id") == plan_id)]
    this_month = finance_manager._today_iso()[:7]
    past, m = [], this_month
    for _ in range(finance_manager.FORECAST_HISTORY_MONTHS):
        m = _month_add(m, -1)
        past.append(await monthly_actual_spending(db, user_id, m, currency))
    with_data = [x for x in past if x > 0]
    usual = sum(with_data, ZERO) / len(with_data) if with_data else ZERO
    last = _month_add(by[:7], -1)
    amount, month = now_amount, this_month
    while month <= last:
        t = planned_money.month_totals(items, month, currency)
        everyday = max(usual - t["spend"], ZERO)
        if month == this_month:
            everyday *= finance_manager._rest_of_month_share()
        amount += t["income"] - t["spend"] - t["set_aside"] - t["moves"] - everyday
        month = _month_add(month, 1)
    return {"now": now_amount, "by_then": amount}


async def benchmark(db, user_id: str, plan: dict, today: date_type, now: datetime) -> dict:
    """Fill in available-now / built-up-by-T−1 / status for every requirement."""
    blocks = bookings = None
    out = []
    for r in plan.get("requirements", []):
        r = dict(r)
        if r["kind"] == "time":
            if blocks is None:
                blocks = await db.time_commitments.find({"user_id": user_id}, {"_id": 0}).to_list(length=None)
                bookings = await db.resource_allocations.find(
                    {"user_id": user_id, "resource_type": "time", "status": {"$in": ["reserved", "consumed"]}},
                    {"_id": 0}).to_list(length=None)
            by = date_type.fromisoformat(r.get("needed_by") or plan["target_date"])
            days = [today + timedelta(days=i) for i in range((by - today).days + 1)]
            slots = free_slots(days, blocks, bookings, r.get("earliest") or DEFAULT_EARLIEST,
                               r.get("latest") or DEFAULT_LATEST, int(r.get("min_block") or r["amount"]), now,
                               r.get("weekdays"))
            booked = sum(int(b.get("quantity") or 0) for b in bookings
                         if b.get("life_plan_id") == plan["id"] and b.get("requirement_id") == r["id"])
            free = sum(s["minutes"] for s in slots)
            r.update(available_now=booked, built_up_by_then=booked + free,
                     slots=slots[:5], unit="minutes")
            need = int(r["amount"])
            r["status"] = "now" if booked >= need else "by_then" if slots else "short"
            r["gap"] = 0 if r["status"] != "short" else need - booked
        elif r["kind"] == "money":
            by = r.get("needed_by") or plan["target_date"]
            m = await money_by(db, user_id, r.get("currency") or "INR", by, plan_id=plan.get("id"))
            need = _dec(r["amount"])
            r.update(available_now=format(m["now"].quantize(Decimal("0.01")), "f"),
                     built_up_by_then=format(m["by_then"].quantize(Decimal("0.01")), "f"), unit=r.get("currency") or "INR")
            r["status"] = "now" if m["now"] >= need else "by_then" if m["by_then"] >= need else "short"
            r["gap"] = "0" if r["status"] != "short" else format((need - max(m["by_then"], m["now"])).quantize(
                Decimal("0.01")), "f")
        else:
            answer = r.get("answer")
            r["status"] = {"yes": "now", "no": "short"}.get(answer, "unknown")
        out.append(r)
    order = {"short": 3, "unknown": 2, "by_then": 1, "now": 0}
    worst = max((order[r["status"]] for r in out), default=0)
    verdict = {3: "doesnt_fit", 2: "needs_answers", 1: "fits_by_then", 0: "fits_now"}[worst]
    # Drift: what was on track when the plan was accepted and isn't any more.
    at_accept = plan.get("accepted_statuses") or {}
    drift = [{"requirement_id": r["id"], "what": r["what"], "was": at_accept[r["id"]], "now": r["status"],
              "gap": r.get("gap")}
             for r in out if r["id"] in at_accept and r["status"] == "short" and at_accept[r["id"]] != "short"]
    return {**plan, "requirements": out, "verdict": verdict, "drift": drift}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

class Requirement(BaseModel):
    area: Literal["money", "health", "family", "learning", "work", "time"]
    what: str = Field(min_length=1, max_length=200)
    kind: Literal["time", "money", "condition"]
    amount: Any = None                      # minutes for time, an amount for money
    currency: Optional[str] = None
    needed_by: Optional[str] = None         # defaults to the plan's date
    earliest: Optional[str] = None          # time window, e.g. "18:00"
    latest: Optional[str] = None
    min_block: Optional[int] = Field(default=None, ge=5, le=1440)
    weekdays: Optional[List[str]] = None


class Risk(BaseModel):
    area: Literal["money", "health", "family", "learning", "work", "time"]
    what: str = Field(min_length=1, max_length=200)
    likelihood: Literal["low", "medium", "high"] = "medium"
    early_warning: str = ""
    mitigation: str = ""


class PlanCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    target_date: str
    requirements: List[Requirement] = Field(min_length=1, max_length=50)
    risks: List[Risk] = Field(default_factory=list, max_length=50)


class QuickTime(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    minutes: int = Field(ge=5, le=1440)
    by: Optional[str] = None                # default: end of this week (Sunday)
    earliest: Optional[str] = None
    latest: Optional[str] = None
    weekdays: Optional[List[str]] = None


class Answer(BaseModel):
    answer: Literal["yes", "no", "unknown"]


class Booking(BaseModel):
    requirement_id: str
    date: str
    start: str
    minutes: int = Field(ge=5, le=1440)


def _date(v: str, field: str) -> date_type:
    try:
        return date_type.fromisoformat(v)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{field} must be YYYY-MM-DD")


def _clean_requirement(r: dict, target: str) -> dict:
    if r["kind"] in ("time", "money"):
        if _dec(r.get("amount")) <= 0:
            raise HTTPException(status_code=400, detail=f"'{r['what']}' needs an amount.")
    if r["kind"] == "time":
        r["amount"] = int(_dec(r["amount"]))
        for f in ("earliest", "latest"):
            if r.get(f):
                try:
                    time_service.hhmm_to_minutes(r[f])
                except ValueError:
                    raise HTTPException(status_code=400, detail=f"{f} must be HH:MM")
    if r["kind"] == "money":
        r["amount"] = format(_dec(r["amount"]), "f")
    if r.get("needed_by"):
        _date(r["needed_by"], "needed_by")
        if r["needed_by"] > target:
            raise HTTPException(status_code=400, detail="A requirement can't be needed after the goal's date.")
    return {**r, "id": str(uuid.uuid4())}


async def _save(db, user_id: str, title: str, target: str, requirements: List[dict], risks: List[dict],
                status: str = "active", chat_id: Optional[str] = None) -> dict:
    _date(target, "target_date")
    plan = {"id": str(uuid.uuid4()), "user_id": user_id, "title": title.strip(), "target_date": target,
            "status": status, "chat_id": chat_id,
            "requirements": [_clean_requirement(r, target) for r in requirements],
            "risks": [{**k, "id": str(uuid.uuid4())} for k in risks], "created_at": _now(), "updated_at": _now()}
    await db.life_plans.insert_one(dict(plan))
    plan.pop("_id", None)
    return plan


def local_now(user: dict) -> datetime:
    """The person's own clock (their saved time zone, else India)."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        tz = ZoneInfo(user.get("timezone") or "Asia/Kolkata")
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo("Asia/Kolkata")
    return datetime.now(tz).replace(tzinfo=None)


async def _evaluated(db, user_id: str, plan: dict) -> dict:
    user = await db.users.find_one({"id": user_id}, {"_id": 0, "timezone": 1}) or {}
    now = local_now(user)
    out = await benchmark(db, user_id, plan, now.date(), now)
    out.pop("user_id", None)
    return out


@life_plans_router.post("", status_code=201)
async def create_plan(body: PlanCreate, current_user: dict = Depends(get_current_user)):
    db = get_db()
    plan = await _save(db, current_user["id"], body.title, body.target_date,
                       [r.model_dump() for r in body.requirements], [k.model_dump() for k in body.risks])
    return await _evaluated(db, current_user["id"], plan)


@life_plans_router.post("/quick-time", status_code=201)
async def quick_time(body: QuickTime, current_user: dict = Depends(get_current_user)):
    """"45 minutes of guitar this week" — one time need, with free slots."""
    today = local_now(current_user).date()
    by = body.by or (today + timedelta(days=6 - today.weekday())).isoformat()
    db = get_db()
    plan = await _save(db, current_user["id"], body.title, by, [{
        "area": "time", "what": body.title, "kind": "time", "amount": body.minutes, "needed_by": by,
        "earliest": body.earliest, "latest": body.latest, "min_block": body.minutes, "weekdays": body.weekdays}], [])
    return await _evaluated(db, current_user["id"], plan)


async def _own(db, user_id: str, plan_id: str) -> dict:
    p = await db.life_plans.find_one({"id": plan_id, "user_id": user_id}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Plan not found")
    return p


@life_plans_router.get("")
async def list_plans(current_user: dict = Depends(get_current_user)):
    db = get_db()
    plans = await db.life_plans.find({"user_id": current_user["id"], "status": "active"}, {"_id": 0}) \
        .sort("target_date", 1).to_list(length=None)
    return [await _evaluated(db, current_user["id"], p) for p in plans]


@life_plans_router.get("/{plan_id}")
async def get_plan(plan_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    return await _evaluated(db, current_user["id"], await _own(db, current_user["id"], plan_id))


@life_plans_router.post("/{plan_id}/requirements/{req_id}/answer")
async def answer(plan_id: str, req_id: str, body: Answer, current_user: dict = Depends(get_current_user)):
    db = get_db()
    plan = await _own(db, current_user["id"], plan_id)
    if not any(r["id"] == req_id and r["kind"] == "condition" for r in plan["requirements"]):
        raise HTTPException(status_code=404, detail="Not a question on this plan")
    await db.life_plans.update_one({"id": plan_id, "requirements.id": req_id},
                                   {"$set": {"requirements.$.answer": body.answer, "updated_at": _now()}})
    return await _evaluated(db, current_user["id"], await _own(db, current_user["id"], plan_id))


@life_plans_router.post("/{plan_id}/book", status_code=201)
async def book(plan_id: str, body: Booking, current_user: dict = Depends(get_current_user)):
    """Book one of the free slots for a time need (it stops being free)."""
    db = get_db()
    plan = await _own(db, current_user["id"], plan_id)
    req = next((r for r in plan["requirements"] if r["id"] == body.requirement_id and r["kind"] == "time"), None)
    if not req:
        raise HTTPException(status_code=404, detail="Not a time need on this plan")
    day = _date(body.date, "date")
    try:
        start = time_service.hhmm_to_minutes(body.start)
    except ValueError:
        raise HTTPException(status_code=400, detail="start must be HH:MM")
    end = start + body.minutes
    if end > 1440:
        raise HTTPException(status_code=400, detail="That runs past midnight; pick an earlier start.")
    blocks = await db.time_commitments.find({"user_id": current_user["id"]}, {"_id": 0}).to_list(length=None)
    bookings = await db.resource_allocations.find(
        {"user_id": current_user["id"], "resource_type": "time", "status": {"$in": ["reserved", "consumed"]}},
        {"_id": 0}).to_list(length=None)
    if any(s < end and start < e for s, e in busy_intervals(day, blocks, bookings)):
        raise HTTPException(status_code=409, detail="That time isn't free any more.")
    doc = {"id": str(uuid.uuid4()), "user_id": current_user["id"], "resource_type": "time",
           "owner_type": "standalone", "owner_id": None, "allocation_mode": "one_time", "date": body.date,
           "day_of_week": None, "start_time": _hm(start), "end_time": _hm(end), "quantity": body.minutes,
           "unit": "minutes", "currency": None, "status": "reserved", "fixed_or_flexible": "flexible",
           "life_plan_id": plan_id, "requirement_id": req["id"], "title": req["what"],
           "created_at": _now(), "updated_at": _now()}
    await db.resource_allocations.insert_one(dict(doc))
    return await _evaluated(db, current_user["id"], await _own(db, current_user["id"], plan_id))


def months_until(today: date_type, by: str) -> int:
    """Whole months from this one to the month before ``by`` (≥ 0)."""
    b = date_type.fromisoformat(by)
    return max((b.year - today.year) * 12 + b.month - today.month, 0)


def _task(user_id: str, plan_id: str, title: str, due: str, notes: str = "") -> dict:
    now = _now()
    return {"id": str(uuid.uuid4()), "user_id": user_id, "title": title[:200], "due_date": due,
            "priority": "medium", "status": "todo", "notes": notes, "origin": "standalone",
            "expected_outcome_id": None, "project_id": None, "component_id": None, "assigned_to_type": "self",
            "assigned_to_name": "", "assigned_to_phone": "", "commitment_type": "postponable",
            "deferred_until": None, "original_due_date": due or None, "defer_count": 0, "recurrence": None,
            "series_id": None, "occurrence_index": 1, "life_plan_id": plan_id, "created_at": now, "updated_at": now}


async def lock_in(db, user_id: str, plan: dict, today: date_type) -> dict:
    """Turn an accepted plan into things that happen:

    * money needed: a monthly saving in planned money until the month
      before it's needed (or, if it's already there, the amount set aside
      for that date);
    * questions not yet answered or answered no: a "find out" / "sort out"
      task;
    * time not yet booked: a "book time" task;
    * risks with a way to soften them: a task to do that.
    """
    from bson.decimal128 import Decimal128

    planned, tasks = [], []
    soon = (today + timedelta(days=14)).isoformat()
    for r in plan["requirements"]:
        by = r.get("needed_by") or plan["target_date"]
        if r["kind"] == "money":
            need, have = _dec(r["amount"]), _dec(r.get("available_now"))
            months = months_until(today, by)
            common = {"id": str(uuid.uuid4()), "user_id": user_id, "currency": r.get("currency") or "INR",
                      "certainty": "sure", "status": "active", "done_amount": Decimal128("0"), "category": None,
                      "account_id": None, "goal_id": None, "life_plan_id": plan["id"], "requirement_id": r["id"],
                      "created_at": _now(), "updated_at": _now()}
            if r["status"] == "now" or months == 0:
                planned.append({**common, "title": f"Set aside: {r['what']}", "direction": "out", "purpose": "spend",
                                "amount": Decimal128(need), "repeat": "once", "date": by, "start_month": None,
                                "end_month": None, "set_aside": True,
                                "notes": f"For your plan: {plan['title']}"})
            else:
                to_save = max(need - have, ZERO)
                monthly = ((to_save / months) / 100).to_integral_value(rounding="ROUND_CEILING") * 100
                if monthly > 0:
                    last = _month_add(by[:7], -1)
                    planned.append({**common, "title": f"Save for: {r['what']}", "direction": "out",
                                    "purpose": "saving", "amount": Decimal128(monthly), "repeat": "monthly",
                                    "date": None, "start_month": today.isoformat()[:7], "end_month": last,
                                    "set_aside": False,
                                    "notes": f"₹{monthly:,.0f} a month for {months} month(s) for: {plan['title']}"})
                tasks.append(_task(user_id, plan["id"], f"Reach ₹{need:,.0f} for {r['what']}", by))
        elif r["kind"] == "condition" and r["status"] != "now":
            verb = "Sort out" if r["status"] == "short" else "Find out"
            tasks.append(_task(user_id, plan["id"], f"{verb}: {r['what']}", min(soon, by)))
        elif r["kind"] == "time" and r["status"] != "now":
            tasks.append(_task(user_id, plan["id"], f"Book time: {r['what']}", by))
    for k in plan.get("risks", []):
        if k.get("mitigation"):
            tasks.append(_task(user_id, plan["id"], f"Reduce a risk: {k['mitigation']}", min(soon, plan["target_date"]),
                               notes=f"Risk: {k['what']}"))
    if planned:
        await db.planned_money.insert_many([dict(p) for p in planned])
    if tasks:
        await db.tasks.insert_many([dict(t) for t in tasks])
    return {"planned_money_ids": [p["id"] for p in planned], "task_ids": [t["id"] for t in tasks]}


@life_plans_router.post("/{plan_id}/accept")
async def accept(plan_id: str, current_user: dict = Depends(get_current_user)):
    """The person picks this plan (e.g. one of the planner's options): it
    becomes active; other drafts from the same conversation are dropped."""
    db = get_db()
    plan = await _own(db, current_user["id"], plan_id)
    if plan.get("locked"):
        return await _evaluated(db, current_user["id"], plan)
    evaluated = await _evaluated(db, current_user["id"], plan)
    locked = await lock_in(db, current_user["id"], evaluated, local_now(current_user).date())
    await db.life_plans.update_one({"id": plan_id}, {"$set": {
        "status": "active", "locked": locked, "updated_at": _now(),
        "accepted_statuses": {r["id"]: r["status"] for r in evaluated["requirements"]}}})
    if plan.get("chat_id"):
        await db.life_plans.update_many(
            {"user_id": current_user["id"], "chat_id": plan["chat_id"], "status": "draft", "id": {"$ne": plan_id}},
            {"$set": {"status": "dropped", "updated_at": _now()}})
    return await _evaluated(db, current_user["id"], await _own(db, current_user["id"], plan_id))


@life_plans_router.delete("/{plan_id}")
async def drop_plan(plan_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    await _own(db, current_user["id"], plan_id)
    await db.life_plans.update_one({"id": plan_id}, {"$set": {"status": "dropped", "updated_at": _now()}})
    await db.planned_money.update_many({"user_id": current_user["id"], "life_plan_id": plan_id},
                                       {"$set": {"status": "cancelled", "updated_at": _now()}})
    await db.tasks.delete_many({"user_id": current_user["id"], "life_plan_id": plan_id, "status": "todo"})
    await db.resource_allocations.update_many({"user_id": current_user["id"], "life_plan_id": plan_id,
                                               "status": "reserved"}, {"$set": {"status": "released"}})
    return {"detail": "Dropped"}


async def ensure_life_plan_indexes(db) -> None:
    await db.life_plans.create_index("id", unique=True)
    await db.life_plans.create_index([("user_id", 1), ("status", 1)])
