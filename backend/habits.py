"""Habits to change: one engine for anything that costs someone their health.

People change when a habit stops fitting the life they want, not through
willpower or fear. So every habit here is tied to **what life it's for**,
and the engine:

* tracks days on track in the last 28 (a slip never erases progress;
  there are no streaks to break);
* turns an urge into a moment: one tap shows *their* reason and a short
  thing to do instead, and records the trigger;
* welcomes people back after a slip or a gap, without catch-up or blame;
* shows what the change frees up: money (which can go to the dream as a
  monthly saving in planned money) and hours (screens);
* notices when life is stretched (high stress, short sleep) so the plan
  can steady that too;
* points to real help where it matters, and never shames.

Tobacco and betting are quit-only (complete cessation is the goal); other
habits can be quit or cut down. Heavy daily drinkers are told not to stop
suddenly without a doctor. Custom habits are private by default.
"""
from __future__ import annotations

import uuid
from collections import Counter
from datetime import date as date_type, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from deps import get_current_user, get_db

habits_router = APIRouter(prefix="/habits", tags=["habits"])

WINDOW = 28
KINDS: Dict[str, dict] = {
    "tobacco": {"label": "Smoking / tobacco", "goals": ["quit"], "unit": "cigarettes or packets",
                "help": ["Wait it out: urges peak and fade in a few minutes", "Drink a glass of water slowly",
                         "Walk for 5 minutes", "Chew something: gum, saunf, a carrot"],
                "support": "Stop-smoking aids roughly double the chance of success — ask your doctor. India's "
                           "national tobacco quitline: 1800-112-356."},
    "betting": {"label": "Betting / gambling", "goals": ["quit"], "unit": "bets",
                "help": ["Put the phone in another room for 10 minutes", "Call or message someone you trust",
                         "Look at your dream fund instead"],
                "support": "If betting has led to debts or worry, you don't have to carry it alone. Tele-MANAS "
                           "(14416, free) can help."},
    "alcohol": {"label": "Alcohol", "goals": ["quit", "cut_down"], "unit": "drinks",
                "help": ["Switch to a soft drink or nimbu pani for this round", "Eat something first",
                         "Decide your number before you start"],
                "support": "If you drink heavily every day, don't stop suddenly — talk to a doctor first, "
                           "as stopping abruptly can be dangerous."},
    "sugar": {"label": "Sweets & sugary drinks", "goals": ["quit", "cut_down"], "unit": "items",
              "help": ["Have a fruit or a handful of nuts", "Drink water or buttermilk", "Brush your teeth"],
              "support": ""},
    "junk_food": {"label": "Junk / fried food", "goals": ["quit", "cut_down"], "unit": "times",
                  "help": ["Have something home-made ready", "Drink water and wait 10 minutes"], "support": ""},
    "screens": {"label": "Doomscrolling / screens", "goals": ["cut_down"], "unit": "minutes",
                "help": ["Put the phone face-down across the room", "Step outside for 5 minutes",
                         "Do one small thing for your dream"], "support": ""},
    "late_nights": {"label": "Late nights", "goals": ["cut_down"], "unit": "minutes past bedtime",
                    "help": ["Lights low, screens off", "Set tomorrow's first task now"], "support": ""},
    "caffeine": {"label": "Too much caffeine", "goals": ["cut_down"], "unit": "cups",
                 "help": ["Switch this one to water or herbal tea"], "support": ""},
    "other": {"label": "Something else", "goals": ["quit", "cut_down"], "unit": "times",
              "help": ["Pause for 2 minutes and breathe slowly", "Do something for your dream instead"],
              "support": ""},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _d(v: Any, default: str = "0") -> Decimal:
    try:
        return Decimal(str(v)) if v not in (None, "") else Decimal(default)
    except InvalidOperation:
        return Decimal(default)


def _money(d: Decimal) -> str:
    return format(d.quantize(Decimal("1")), "f")


# ---------------------------------------------------------------------------
# Progress (pure)
# ---------------------------------------------------------------------------

def progress(habit: dict, logs: List[dict], today: date_type, health_rows: Optional[List[dict]] = None) -> dict:
    start = max(date_type.fromisoformat(habit["started_on"]), today - timedelta(days=WINDOW - 1))
    target = _d(habit.get("target_per_day"))
    baseline = _d(habit.get("baseline_per_day"))
    cost = _d(habit.get("cost_per_unit"))
    logs = sorted(logs, key=lambda l: l["date"])
    window = [l for l in logs if start.isoformat() <= l["date"] <= today.isoformat()]
    on_track = [l for l in window if _d(l["amount"]) <= target]
    freed_units = sum((max(baseline - _d(l["amount"]), Decimal(0)) for l in logs), Decimal(0))
    triggers = Counter(t for l in logs for t in l.get("triggers", []))
    welcome = None
    if logs:
        last = logs[-1]
        gap = (today - date_type.fromisoformat(last["date"])).days
        earlier = logs[:-1]
        slipped_before = earlier and _d(earlier[-1]["amount"]) > target
        if gap >= 3:
            welcome = "Welcome back. No catching up needed — today counts."
        elif last["date"] == today.isoformat() and _d(last["amount"]) <= target and slipped_before:
            welcome = "Welcome back. A slip is part of changing; this is a good day."
    edge = []
    if health_rows:
        week = (today - timedelta(days=6)).isoformat()
        def avg(m):
            v = [_d(r["value"]) for r in health_rows if r["metric"] == m and r["taken_on"] >= week]
            return sum(v) / len(v) if v else None
        stress, sleep = avg("stress"), avg("sleep_hours")
        if stress is not None and stress >= Decimal("3.5"):
            edge.append("Stress has been high this week — a short walk or slow breathing when urges come can help.")
        if sleep is not None and sleep < 6:
            edge.append("Sleep has been short — urges are stronger when we're tired. An earlier night may help.")
    out = {"days_considered": (today - start).days + 1, "days_logged": len(window),
           "days_on_track": len(on_track), "welcome_back": welcome, "top_triggers": triggers.most_common(3),
           "steady_the_edge": edge}
    if cost:
        out["money_freed"] = _money(freed_units * cost)
    if habit["kind"] == "screens":
        out["hours_freed"] = format((freed_units / 60).quantize(Decimal("0.1")), "f")
    return out


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

class HabitCreate(BaseModel):
    kind: str
    label: Optional[str] = Field(default=None, max_length=80)
    goal: Literal["quit", "cut_down"]
    baseline_per_day: Any                    # how much on a usual day now
    target_per_day: Any = None               # for cut_down
    cost_per_unit: Any = None                # ₹ per cigarette / drink / bet…
    for_what: str = Field(default="", max_length=300)
    serves_plan_id: Optional[str] = None
    private: Optional[bool] = None
    started_on: Optional[str] = None


class HabitLog(BaseModel):
    date: str
    amount: Any                              # 0 = a clean day for a quit habit
    triggers: List[str] = Field(default_factory=list, max_length=10)


class Urge(BaseModel):
    date: str
    trigger: Optional[str] = Field(default=None, max_length=40)


def _date(v: Optional[str]) -> str:
    try:
        return date_type.fromisoformat((v or date_type.today().isoformat())[:10]).isoformat()
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates must be YYYY-MM-DD.")


async def _own(db, user_id: str, habit_id: str) -> dict:
    h = await db.habits.find_one({"id": habit_id, "user_id": user_id}, {"_id": 0})
    if not h:
        raise HTTPException(status_code=404, detail="Habit not found")
    return h


async def _serves(db, user_id: str, habit: dict) -> Optional[dict]:
    if not habit.get("serves_plan_id"):
        return None
    return await db.life_plans.find_one({"id": habit["serves_plan_id"], "user_id": user_id},
                                        {"_id": 0, "id": 1, "title": 1, "target_date": 1})


async def _view(db, user_id: str, habit: dict) -> dict:
    logs = await db.habit_logs.find({"habit_id": habit["id"]}, {"_id": 0}).to_list(length=None)
    health_rows = await db.health_measurements.find(
        {"user_id": user_id, "metric": {"$in": ["stress", "sleep_hours"]}}, {"_id": 0}).to_list(length=None)
    kind = KINDS[habit["kind"]]
    return {**{k: v for k, v in habit.items() if k != "user_id"}, "serves": await _serves(db, user_id, habit),
            "support": kind["support"], "progress": progress(habit, logs, date_type.today(), health_rows)}


@habits_router.get("/kinds")
async def kinds():
    return {k: {"label": v["label"], "goals": v["goals"], "unit": v["unit"]} for k, v in KINDS.items()}


@habits_router.post("", status_code=201)
async def create(body: HabitCreate, current_user: dict = Depends(get_current_user)):
    kind = KINDS.get(body.kind)
    if not kind:
        raise HTTPException(status_code=400, detail="Unknown habit")
    if body.goal not in kind["goals"]:
        raise HTTPException(status_code=400, detail=(
            f"For {kind['label'].lower()}, Hymn supports quitting fully — it's what works best."
            if kind["goals"] == ["quit"] else f"For {kind['label'].lower()}, the goal is cutting down."))
    baseline = _d(body.baseline_per_day)
    target = Decimal(0) if body.goal == "quit" else _d(body.target_per_day, "-1")
    if baseline <= 0:
        raise HTTPException(status_code=400, detail="How much on a usual day now? (more than 0)")
    if body.goal == "cut_down" and not (0 <= target < baseline):
        raise HTTPException(status_code=400, detail="Pick a target below your usual amount.")
    if body.kind == "other" and not body.label:
        raise HTTPException(status_code=400, detail="Give it a name.")
    db = get_db()
    if body.serves_plan_id and not await db.life_plans.find_one(
            {"id": body.serves_plan_id, "user_id": current_user["id"]}, {"_id": 1}):
        raise HTTPException(status_code=400, detail="The plan this serves wasn't found.")
    doc = {"id": str(uuid.uuid4()), "user_id": current_user["id"], "kind": body.kind,
           "label": body.label or kind["label"], "goal": body.goal, "unit": kind["unit"],
           "baseline_per_day": str(baseline), "target_per_day": str(target),
           "cost_per_unit": str(_d(body.cost_per_unit)) if body.cost_per_unit not in (None, "") else None,
           "for_what": body.for_what.strip(), "serves_plan_id": body.serves_plan_id,
           "private": body.private if body.private is not None else body.kind == "other",
           "started_on": _date(body.started_on), "status": "active", "dream_fund_id": None,
           "created_at": _now(), "updated_at": _now()}
    await db.habits.insert_one(dict(doc))
    return await _view(db, current_user["id"], doc)


@habits_router.get("")
async def list_habits(current_user: dict = Depends(get_current_user)):
    db = get_db()
    habits = await db.habits.find({"user_id": current_user["id"], "status": "active"}, {"_id": 0}).to_list(length=None)
    return [await _view(db, current_user["id"], h) for h in habits]


@habits_router.get("/{habit_id}")
async def get_habit(habit_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    return await _view(db, current_user["id"], await _own(db, current_user["id"], habit_id))


@habits_router.post("/{habit_id}/log")
async def log(habit_id: str, body: HabitLog, current_user: dict = Depends(get_current_user)):
    """How much today (0 = clean day for a quit habit). One entry per day."""
    db = get_db()
    habit = await _own(db, current_user["id"], habit_id)
    amount = _d(body.amount, "-1")
    if amount < 0:
        raise HTTPException(status_code=400, detail="Amount can't be negative.")
    day = _date(body.date)
    await db.habit_logs.update_one(
        {"habit_id": habit_id, "date": day},
        {"$set": {"user_id": current_user["id"], "amount": str(amount), "updated_at": _now()},
         "$addToSet": {"triggers": {"$each": [t.strip().lower() for t in body.triggers if t.strip()]}},
         "$setOnInsert": {"id": str(uuid.uuid4()), "urges": 0}}, upsert=True)
    return await _view(db, current_user["id"], habit)


@habits_router.post("/{habit_id}/urge")
async def urge(habit_id: str, body: Urge, current_user: dict = Depends(get_current_user)):
    """An urge right now: their own reason, a short thing to do instead."""
    db = get_db()
    habit = await _own(db, current_user["id"], habit_id)
    day = _date(body.date)
    update: Dict[str, Any] = {"$inc": {"urges": 1}, "$set": {"user_id": current_user["id"], "updated_at": _now()},
                              "$setOnInsert": {"id": str(uuid.uuid4()), "amount": "0"},
                              # When urges come, so a check-in can arrive just before (health_nudges).
                              "$push": {"urge_times": {"$each": [_now()], "$slice": -20}}}
    if body.trigger:
        update["$addToSet"] = {"triggers": body.trigger.strip().lower()}
    await db.habit_logs.update_one({"habit_id": habit_id, "date": day}, update, upsert=True)
    serves = await _serves(db, current_user["id"], habit)
    reason = habit.get("for_what") or (serves or {}).get("title") or ""
    return {"your_reason": reason, "serves": serves, "try_this": KINDS[habit["kind"]]["help"],
            "note": "Urges rise and fall. This one will pass too."}


@habits_router.post("/{habit_id}/dream-fund", status_code=201)
async def dream_fund(habit_id: str, current_user: dict = Depends(get_current_user)):
    """Send what the habit used to cost to the dream, as a monthly saving."""
    from bson.decimal128 import Decimal128

    db = get_db()
    habit = await _own(db, current_user["id"], habit_id)
    if habit.get("dream_fund_id"):
        raise HTTPException(status_code=409, detail="Already going to your dream.")
    if not habit.get("cost_per_unit"):
        raise HTTPException(status_code=400, detail="Add what it costs first.")
    serves = await _serves(db, current_user["id"], habit)
    dream = (serves or {}).get("title") or habit.get("for_what")
    if not dream:
        raise HTTPException(status_code=400, detail="Tell Hymn what life this is for first.")
    per_day = (_d(habit["baseline_per_day"]) - _d(habit["target_per_day"])) * _d(habit["cost_per_unit"])
    monthly = ((per_day * 30) / 100).to_integral_value(rounding="ROUND_CEILING") * 100
    item = {"id": str(uuid.uuid4()), "user_id": current_user["id"], "title": f"From {habit['label'].lower()} → {dream}",
            "direction": "out", "purpose": "saving", "amount": Decimal128(monthly), "currency": "INR",
            "repeat": "monthly", "date": None, "start_month": date_type.today().isoformat()[:7], "end_month": None,
            "certainty": "sure", "set_aside": False, "status": "active", "done_amount": Decimal128("0"),
            "category": None, "account_id": None, "goal_id": None, "habit_id": habit_id,
            "life_plan_id": habit.get("serves_plan_id"), "notes": "What the habit used to cost, now for your dream.",
            "created_at": _now(), "updated_at": _now()}
    await db.planned_money.insert_one(dict(item))
    await db.habits.update_one({"id": habit_id}, {"$set": {"dream_fund_id": item["id"], "updated_at": _now()}})
    return {"monthly": _money(monthly), "goes_to": dream, "planned_money_id": item["id"]}


@habits_router.delete("/{habit_id}")
async def delete(habit_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    await _own(db, current_user["id"], habit_id)
    await db.habit_logs.delete_many({"habit_id": habit_id})
    await db.habits.delete_one({"id": habit_id, "user_id": current_user["id"]})
    return {"detail": "Deleted"}


async def ensure_habit_indexes(db) -> None:
    await db.habits.create_index([("user_id", 1), ("status", 1)])
    await db.habit_logs.create_index([("habit_id", 1), ("date", 1)], unique=True)
