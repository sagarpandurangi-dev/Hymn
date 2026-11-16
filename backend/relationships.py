"""Family & Relationships: the people who matter, their days, time together.

* **People** — name, relation, circle (inner / close / wider), birthday and
  other days that come round each year (anniversary, a parent's death
  anniversary…), an optional "keep in touch every N days", private notes,
  and an optional link to a care profile (``care``) for someone whose health
  you look after.
* **Moments** — a call, a visit, a meal, help given… with whom, when, and
  for how long (optional). One moment can include several people.
* **What it gives back** — when you last connected with each person; who
  might like to hear from you (gently: never "overdue", never a streak);
  the days coming up, with the age someone turns; hours with your inner
  circle this month; and, with the health consent, the week's hours with
  people go into Health ("Time with people you care about").
* A day can carry a **gift budget**: a yearly item in planned money in that
  month, so it's in the forecast.

Nudges (``nudges`` setting ``people``): the day before and the morning of
each day that matters; and at most once a week, one inner-circle person
it's been a while with.
"""
from __future__ import annotations

import uuid
from datetime import date as date_type, datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List, Literal, Optional

from bson.decimal128 import Decimal128
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from deps import get_current_user, get_db

people_router = APIRouter(prefix="/people", tags=["relationships"])

RELATIONS = ("mother", "father", "spouse", "partner", "child", "sibling", "grandparent", "grandchild",
             "parent_in_law", "relative", "friend", "mentor", "colleague", "neighbour", "other")
CIRCLES = ("inner", "close", "wider")
DEFAULT_TOUCH_DAYS = {"inner": 7, "close": 30, "wider": None}
MOMENT_KINDS = ("call", "video_call", "visit", "meal", "outing", "message", "help", "celebration", "other")
MAX_PEOPLE = 300


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Dates (pure)
# ---------------------------------------------------------------------------

def parse_day(v: str) -> tuple:
    """"MM-DD" or "YYYY-MM-DD" → (year or None, month, day). Raises ValueError."""
    v = (v or "").strip()
    if len(v) == 5:
        m, d = int(v[:2]), int(v[3:])
        date_type(2024, m, d)                     # a leap year accepts 29 Feb
        return None, m, d
    full = date_type.fromisoformat(v)
    return full.year, full.month, full.day


def next_occurrence(v: str, today: date_type) -> date_type:
    """The next time this day comes round (today counts). 29 Feb → 28 Feb
    in other years."""
    _, m, d = parse_day(v)
    for year in (today.year, today.year + 1):
        try:
            when = date_type(year, m, d)
        except ValueError:
            when = date_type(year, 2, 28)
        if when >= today:
            return when
    raise ValueError(v)


def days_coming(person: dict, today: date_type, within: int) -> List[dict]:
    out = []
    items = ([{"label": "Birthday", "date": person["birthday"], "gift_budget": person.get("birthday_gift")}]
             if person.get("birthday") else []) + list(person.get("occasions") or [])
    for o in items:
        when = next_occurrence(o["date"], today)
        gap = (when - today).days
        if gap > within:
            continue
        year = parse_day(o["date"])[0]
        item = {"person_id": person["id"], "name": person["name"], "label": o["label"], "on": when.isoformat(),
                "in_days": gap}
        if year:
            n = when.year - year
            item["years"] = n            # turns n (birthday) / n years (anniversary)
        if o.get("gift_budget"):
            item["gift_budget"] = o["gift_budget"]
        out.append(item)
    return out


def touch_status(person: dict, last: Optional[str], today: date_type) -> dict:
    every = person.get("keep_in_touch_days")
    since = (today - date_type.fromisoformat(last)).days if last else None
    might_like = bool(every and (since is None or since >= every))
    return {"last_together": last, "days_since": since, "keep_in_touch_days": every,
            "might_like_to_hear_from_you": might_like}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

class Occasion(BaseModel):
    label: str = Field(min_length=1, max_length=60)          # "Anniversary", "Appa's remembrance day"
    date: str                                                 # MM-DD or YYYY-MM-DD
    gift_budget: Optional[float] = Field(default=None, gt=0, le=10_000_000)


class PersonIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    relation: Literal[RELATIONS]
    circle: Literal[CIRCLES] = "close"
    birthday: Optional[str] = None                            # MM-DD or YYYY-MM-DD
    birthday_gift: Optional[float] = Field(default=None, gt=0, le=10_000_000)
    occasions: List[Occasion] = Field(default_factory=list, max_length=10)
    keep_in_touch_days: Optional[int] = Field(default=None, ge=1, le=365)   # default from the circle
    notes: str = Field(default="", max_length=2000)           # private, only you see them
    care_id: Optional[str] = None                             # a care profile you look after


class PersonPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=60)
    relation: Optional[Literal[RELATIONS]] = None
    circle: Optional[Literal[CIRCLES]] = None
    birthday: Optional[str] = None
    birthday_gift: Optional[float] = Field(default=None, gt=0, le=10_000_000)
    occasions: Optional[List[Occasion]] = Field(default=None, max_length=10)
    keep_in_touch_days: Optional[int] = Field(default=None, ge=0, le=365)   # 0 = don't remind
    notes: Optional[str] = Field(default=None, max_length=2000)
    care_id: Optional[str] = None


def _check_dates(p: dict) -> None:
    for v in [p.get("birthday")] + [o["date"] for o in p.get("occasions") or []]:
        if not v:
            continue
        try:
            parse_day(v)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"{v} isn't a date (use MM-DD or YYYY-MM-DD).")


async def _check_care(db, user_id: str, care_id: Optional[str]) -> None:
    if care_id and not await db.care_profiles.find_one({"id": care_id, "owner_id": user_id}, {"_id": 1}):
        raise HTTPException(status_code=400, detail="That care profile wasn't found.")


async def _gift_items(db, user_id: str, person: dict, today: date_type) -> None:
    """One yearly planned-money item per day with a gift budget (replaced on
    every save, so edits and deletions follow)."""
    await db.planned_money.delete_many({"user_id": user_id, "person_id": person["id"]})
    days = ([{"label": "Birthday", "date": person["birthday"], "gift_budget": person.get("birthday_gift")}]
            if person.get("birthday") else []) + list(person.get("occasions") or [])
    docs = []
    for o in days:
        if not o.get("gift_budget"):
            continue
        when = next_occurrence(o["date"], today)
        docs.append({"id": str(uuid.uuid4()), "user_id": user_id, "title": f"{o['label']}: {person['name']}",
                     "direction": "out", "purpose": "spend", "amount": Decimal128(Decimal(str(o["gift_budget"]))),
                     "currency": "INR", "repeat": "yearly", "date": None, "start_month": when.isoformat()[:7],
                     "end_month": None, "certainty": "sure", "set_aside": False, "category": "expense:gifts",
                     "account_id": None, "goal_id": None, "notes": "From People", "status": "active",
                     "done_amount": Decimal128(Decimal(0)), "person_id": person["id"],
                     "created_at": _now(), "updated_at": _now()})
    if docs:
        await db.planned_money.insert_many(docs)


async def _last_together(db, user_id: str) -> Dict[str, str]:
    last: Dict[str, str] = {}
    async for m in db.people_moments.find({"user_id": user_id}, {"_id": 0, "person_ids": 1, "date": 1}):
        for pid in m["person_ids"]:
            if m["date"] > last.get(pid, ""):
                last[pid] = m["date"]
    return last


def _view(p: dict, last: Optional[str], today: date_type) -> dict:
    out = {k: v for k, v in p.items() if k not in ("_id", "user_id")}
    out.update(touch_status(p, last, today))
    coming = days_coming(p, today, 366)
    out["next_day"] = min(coming, key=lambda c: c["in_days"]) if coming else None
    return out


async def _own(db, user_id: str, person_id: str) -> dict:
    p = await db.people.find_one({"id": person_id, "user_id": user_id}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Person not found")
    return p


@people_router.post("", status_code=201)
async def add_person(body: PersonIn, current_user: dict = Depends(get_current_user)):
    db = get_db()
    uid = current_user["id"]
    if await db.people.count_documents({"user_id": uid}) >= MAX_PEOPLE:
        raise HTTPException(status_code=400, detail=f"Up to {MAX_PEOPLE} people.")
    doc = body.model_dump()
    _check_dates(doc)
    await _check_care(db, uid, doc.get("care_id"))
    if doc["keep_in_touch_days"] is None:
        doc["keep_in_touch_days"] = DEFAULT_TOUCH_DAYS[doc["circle"]]
    doc.update(id=str(uuid.uuid4()), user_id=uid, name=doc["name"].strip(), created_at=_now(), updated_at=_now())
    await db.people.insert_one(dict(doc))
    await _gift_items(db, uid, doc, date_type.today())
    return _view(doc, None, date_type.today())


@people_router.get("")
async def list_people(current_user: dict = Depends(get_current_user)):
    """Everyone, inner circle first; who might like to hear from you first
    within each circle."""
    db = get_db()
    uid = current_user["id"]
    today = date_type.today()
    last = await _last_together(db, uid)
    people = [_view(p, last.get(p["id"]), today)
              async for p in db.people.find({"user_id": uid}, {"_id": 0})]
    people.sort(key=lambda p: (CIRCLES.index(p["circle"]), not p["might_like_to_hear_from_you"],
                               -(p["days_since"] or 0), p["name"]))
    return people


@people_router.get("/upcoming")
async def upcoming(days: int = Query(30, ge=1, le=366), current_user: dict = Depends(get_current_user)):
    db = get_db()
    today = date_type.today()
    out = []
    async for p in db.people.find({"user_id": current_user["id"]}, {"_id": 0}):
        out += days_coming(p, today, days)
    return sorted(out, key=lambda c: (c["in_days"], c["name"]))


@people_router.get("/summary")
async def summary(current_user: dict = Depends(get_current_user)):
    """The Family & Relationships card: this month's time with your inner
    circle, who might like to hear from you, and the next days that matter."""
    db = get_db()
    uid = current_user["id"]
    today = date_type.today()
    month_start = today.replace(day=1).isoformat()
    people = {p["id"]: p async for p in db.people.find({"user_id": uid}, {"_id": 0})}
    inner = {pid for pid, p in people.items() if p["circle"] == "inner"}
    minutes = moments = 0
    reached = set()
    async for m in db.people_moments.find({"user_id": uid, "date": {"$gte": month_start}}, {"_id": 0}):
        moments += 1
        reached.update(m["person_ids"])
        if inner & set(m["person_ids"]):
            minutes += m.get("minutes") or 0
    last = await _last_together(db, uid)
    hear = [{"person_id": pid, "name": p["name"], **touch_status(p, last.get(pid), today)}
            for pid, p in people.items() if touch_status(p, last.get(pid), today)["might_like_to_hear_from_you"]]
    hear.sort(key=lambda h: (people[h["person_id"]]["circle"] != "inner", -(h["days_since"] or 10_000)))
    coming = sorted((c for p in people.values() for c in days_coming(p, today, 30)), key=lambda c: c["in_days"])
    return {"month": today.isoformat()[:7], "moments_this_month": moments, "people_reached": len(reached),
            "inner_circle_hours": round(minutes / 60, 1), "might_like_to_hear_from_you": hear[:3],
            "coming_up": coming[:5], "people": len(people)}


@people_router.get("/{person_id}")
async def get_person(person_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    p = await _own(db, current_user["id"], person_id)
    moments = await db.people_moments.find({"user_id": current_user["id"], "person_ids": person_id},
                                           {"_id": 0, "user_id": 0}).sort("date", -1).to_list(length=50)
    out = _view(p, moments[0]["date"] if moments else None, date_type.today())
    out["moments"] = moments
    return out


@people_router.patch("/{person_id}")
async def update_person(person_id: str, body: PersonPatch, current_user: dict = Depends(get_current_user)):
    db = get_db()
    uid = current_user["id"]
    p = await _own(db, uid, person_id)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("keep_in_touch_days") == 0:
        changes["keep_in_touch_days"] = None
    merged = {**p, **changes}
    _check_dates(merged)
    await _check_care(db, uid, merged.get("care_id"))
    merged["updated_at"] = _now()
    await db.people.replace_one({"id": person_id, "user_id": uid}, merged)
    await _gift_items(db, uid, merged, date_type.today())
    last = await _last_together(db, uid)
    return _view(merged, last.get(person_id), date_type.today())


@people_router.delete("/{person_id}")
async def delete_person(person_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    uid = current_user["id"]
    await _own(db, uid, person_id)
    await db.people.delete_one({"id": person_id, "user_id": uid})
    await db.people_moments.update_many({"user_id": uid}, {"$pull": {"person_ids": person_id}})
    await db.people_moments.delete_many({"user_id": uid, "person_ids": {"$size": 0}})
    await db.planned_money.delete_many({"user_id": uid, "person_id": person_id})
    return {"detail": "Removed"}


class MomentIn(BaseModel):
    person_ids: List[str] = Field(min_length=1, max_length=30)
    date: str
    kind: Literal[MOMENT_KINDS] = "other"
    minutes: Optional[int] = Field(default=None, ge=1, le=24 * 60)
    note: str = Field(default="", max_length=500)


def _week_start(day: date_type) -> date_type:
    return day - timedelta(days=day.weekday())


async def _sync_health(db, user_id: str, day: date_type) -> None:
    """With the health consent, the week's hours with people become
    Health's "Time with people you care about" (one value per week)."""
    if not await db.health_profiles.find_one({"user_id": user_id, "consent": True}, {"_id": 1}):
        return
    start = _week_start(day)
    end = start + timedelta(days=6)
    minutes = 0
    async for m in db.people_moments.find({"user_id": user_id, "date": {"$gte": start.isoformat(),
                                                                         "$lte": end.isoformat()}}, {"_id": 0}):
        minutes += m.get("minutes") or 0
    await db.health_measurements.delete_many({"user_id": user_id, "metric": "social_hours",
                                              "taken_on": start.isoformat(), "note": "from People"})
    if minutes:
        await db.health_measurements.insert_one({
            "id": str(uuid.uuid4()), "user_id": user_id, "metric": "social_hours",
            "value": min(round(minutes / 60, 1), 100), "unit": "hours/week", "taken_on": start.isoformat(),
            "source": "you", "note": "from People", "created_at": _now()})


@people_router.post("/moments", status_code=201)
async def add_moment(body: MomentIn, current_user: dict = Depends(get_current_user)):
    db = get_db()
    uid = current_user["id"]
    try:
        day = date_type.fromisoformat(body.date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates must be YYYY-MM-DD.")
    if day > date_type.today() + timedelta(days=1):
        raise HTTPException(status_code=400, detail="That date is in the future.")
    ids = list(dict.fromkeys(body.person_ids))
    if await db.people.count_documents({"user_id": uid, "id": {"$in": ids}}) != len(ids):
        raise HTTPException(status_code=400, detail="Pick people from your list.")
    doc = {**body.model_dump(), "person_ids": ids, "id": str(uuid.uuid4()), "user_id": uid, "created_at": _now()}
    await db.people_moments.insert_one(dict(doc))
    await _sync_health(db, uid, day)
    doc.pop("user_id")
    return doc


@people_router.delete("/moments/{moment_id}")
async def delete_moment(moment_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    m = await db.people_moments.find_one({"id": moment_id, "user_id": current_user["id"]}, {"_id": 0})
    if not m:
        raise HTTPException(status_code=404, detail="Moment not found")
    await db.people_moments.delete_one({"id": moment_id})
    await _sync_health(db, current_user["id"], date_type.fromisoformat(m["date"]))
    return {"detail": "Deleted"}


async def ensure_people_indexes(db) -> None:
    await db.people.create_index([("user_id", 1), ("id", 1)], unique=True)
    await db.people_moments.create_index([("user_id", 1), ("date", -1)])
    await db.people_moments.create_index([("user_id", 1), ("person_ids", 1)])


# ---------------------------------------------------------------------------
# Nudges (called by the nudge scheduler)
# ---------------------------------------------------------------------------

TOUCH_NUDGE_GAP_DAYS = 7


async def people_nudges(db, user: dict, settings: dict, now: datetime) -> List[dict]:
    from nudges import _claim, _due, _tz, hhmm_to_minute, in_quiet_hours

    cfg = settings.get("people") or {}
    if not cfg.get("enabled", True):
        return []
    local = now.astimezone(_tz(user.get("timezone")))
    quiet = settings["quiet_hours"]
    if in_quiet_hours(local.hour * 60 + local.minute, quiet["start"], quiet["end"]):
        return []
    at = _due(local, hhmm_to_minute(cfg.get("time") or "09:00"))
    if at is None:
        return []
    today = local.date()
    uid = user["id"]
    people = [p async for p in db.people.find({"user_id": uid}, {"_id": 0})]
    out = []
    for p in people:
        for c in days_coming(p, today, 1):
            when = "Today" if c["in_days"] == 0 else "Tomorrow"
            turns = (f" (turns {c['years']})" if c["label"] == "Birthday" else f" ({c['years']} years)") \
                if c.get("years") else ""
            body = "A good day to reach out." if c["in_days"] == 0 else (
                f"You'd planned ₹{c['gift_budget']:,.0f} for it." if c.get("gift_budget") else "Tomorrow it is.")
            n = await _claim(db, uid, "people_day", f"people_day:{p['id']}:{c['label']}:{c['on']}:{c['in_days']}",
                             f"{when}: {p['name']}'s {c['label'].lower()}{turns}", body,
                             {"screen": "people", "person_id": p["id"]}, at)
            if n:
                out.append(n)
    recent = await db.nudges.find_one({"user_id": uid, "kind": "people_touch",
                                       "created_at": {"$gte": (now - timedelta(days=TOUCH_NUDGE_GAP_DAYS))
                                                      .isoformat()}}, {"_id": 1})
    if not recent:
        last = await _last_together(db, uid)
        due = [(p, touch_status(p, last.get(p["id"]), today)) for p in people if p["circle"] == "inner"]
        due = [(p, s) for p, s in due if s["might_like_to_hear_from_you"] and s["days_since"] is not None]
        if due:
            p, s = max(due, key=lambda x: x[1]["days_since"])
            n = await _claim(db, uid, "people_touch", f"people_touch:{p['id']}:{today.isoformat()}",
                             f"{p['name']} might like to hear from you", f"It's been {s['days_since']} days.",
                             {"screen": "people", "person_id": p["id"]}, at)
            if n:
                out.append(n)
    return out
