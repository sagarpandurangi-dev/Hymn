"""Work: keep work in its place — it pays for the life you want, it grows
you, and it doesn't quietly eat everything else.

* **Work roles** — one or more per person (a job and a side business): type
  (salaried, self-employed, business owner, freelancer, articleship /
  intern, looking for work, homemaker), organisation, title, usual days and
  hours, commute. Saving a role creates its fixed time blocks (work, and
  commute before and after), so free time, the planner, learning journeys
  and the time statements all see it. Parts switch on by type: leave and
  appraisals for employed roles, payslips for salaried ones.
* **Work time** — days that ran over or ended early (``POST /work/days``)
  show as overtime in the time statements; the week view says whether work
  stayed in its box, next to family time, sleep and stress (health, with
  consent).
* **Leave** — balances per type for the leave year (entitlement +
  carried forward − taken − planned), days that will expire at year end,
  and ``check_leave`` for the planner.
* **Appraisals and wins** — a one-line wins log; the appraisal pack lists
  wins since the last appraisal and study hours; a nudge three weeks before.
* **Payslips** (Premium) — the AI copies a payslip; code checks the sums and
  sorts deductions. On the money book, the parts of pay that never reach
  the bank are recorded so income shows gross: PF into the EPF account
  (``income:salary_withheld``) and tax / professional tax / employer health
  insurance as costs (``salary_deduction``); other deductions (canteen, loan
  recovery…) as "not yet sorted" for the person to file. Take-home already arrives
  through the bank, so nothing is counted twice.
"""
from __future__ import annotations

import base64
import binascii
import re
import uuid
from collections import defaultdict
from datetime import date as date_type, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from deps import get_current_user, get_db
from plans import require_feature

work_router = APIRouter(prefix="/work", tags=["work"])

TYPES = ("salaried", "self_employed", "business_owner", "freelancer", "articleship", "looking_for_work",
         "homemaker")
EMPLOYED = {"salaried", "articleship"}
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
IN_BOX_MINUTES = 120          # up to 2 hours over the plan in a week still counts as "in its box"
APPRAISAL_NOTICE_DAYS = 21
LEAVE_EXPIRY_NOTICE_DAYS = 30


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _d(v) -> Optional[date_type]:
    try:
        return date_type.fromisoformat(v) if v else None
    except (TypeError, ValueError):
        return None


def _hm(v: str) -> int:
    if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", v or ""):
        raise HTTPException(status_code=400, detail="Times must be HH:MM.")
    return int(v[:2]) * 60 + int(v[3:])


def _fmt(m: int) -> str:
    m %= 1440
    return f"{m // 60:02d}:{m % 60:02d}"


# ---------------------------------------------------------------------------
# Leave (pure)
# ---------------------------------------------------------------------------

def leave_year(reset_mmdd: str, today: date_type) -> tuple:
    """(start, end) of the leave year that contains today."""
    m, d = int(reset_mmdd[:2]), int(reset_mmdd[3:])
    start = date_type(today.year, m, d)
    if start > today:
        start = date_type(today.year - 1, m, d)
    end = date_type(start.year + 1, m, d) - timedelta(days=1)
    return start, end


def leave_days(start: date_type, end: date_type, work_days: List[str], half_day: bool = False) -> float:
    if half_day:
        return 0.5
    n, d = 0, start
    while d <= end:
        if DAYS[d.weekday()] in work_days:
            n += 1
        d += timedelta(days=1)
    return float(n)


def leave_balances(role: dict, leaves: List[dict], today: date_type) -> List[dict]:
    out = []
    for t in (role.get("leave_types") or []):
        start, end = leave_year(t.get("year_starts", "01-01"), today)
        mine = [lv for lv in leaves if lv["type"] == t["key"] and lv["status"] != "cancelled"
                and start.isoformat() <= lv["from"] <= end.isoformat()]
        taken = sum(lv["days"] for lv in mine if lv["from"] <= today.isoformat())
        planned = sum(lv["days"] for lv in mine if lv["from"] > today.isoformat())
        have = float(t.get("per_year", 0)) + float(t.get("carried_forward", 0))
        left = have - taken - planned
        row = {"type": t["key"], "label": t.get("label") or t["key"].replace("_", " ").title(),
               "per_year": float(t.get("per_year", 0)), "carried_forward": float(t.get("carried_forward", 0)),
               "taken": taken, "planned": planned, "left": left, "year_ends": end.isoformat()}
        cap = t.get("carry_forward_max")
        if cap is not None and left > float(cap):
            row["expiring"] = left - float(cap)          # unused beyond the carry-forward limit is lost
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# Work roles
# ---------------------------------------------------------------------------

class LeaveType(BaseModel):
    key: str = Field(min_length=1, max_length=30)          # earned, casual, sick, other
    label: str = ""
    per_year: float = Field(ge=0, le=365)
    carried_forward: float = Field(default=0, ge=0, le=365)
    carry_forward_max: Optional[float] = Field(default=None, ge=0, le=365)
    year_starts: str = "01-01"                              # MM-DD the leave year starts


class RoleIn(BaseModel):
    type: Literal[TYPES]
    organisation: str = Field(default="", max_length=120)
    title: str = Field(default="", max_length=120)
    started_on: Optional[str] = None
    work_days: List[Literal[DAYS]] = Field(default_factory=lambda: list(DAYS[:5]))
    start_time: Optional[str] = None                        # "09:30"
    end_time: Optional[str] = None                          # "18:30"
    office_days: Optional[List[Literal[DAYS]]] = None       # days you commute (default: all work days)
    commute_minutes: int = Field(default=0, ge=0, le=240)   # each way
    leave_types: List[LeaveType] = Field(default_factory=list, max_length=8)
    next_appraisal: Optional[str] = None
    notes: str = Field(default="", max_length=1000)


def _blocks_for(user_id: str, role: dict) -> List[dict]:
    """Fixed weekly time blocks for the role's hours and commute."""
    if not (role.get("start_time") and role.get("end_time")):
        return []
    start, end = _hm(role["start_time"]), _hm(role["end_time"])
    if start == end:
        raise HTTPException(status_code=400, detail="Start and end time can't be the same.")
    name = role.get("organisation") or role.get("title") or "Work"
    office = role.get("office_days") or role["work_days"]
    common = {"user_id": user_id, "flexibility": "fixed", "effective_from": role.get("started_on") or
              date_type.today().isoformat(), "effective_until": None, "source_type": "system",
              "source_id": role["id"], "notes": "From your work role", "created_at": _now(), "updated_at": _now()}
    out = []
    for day in role["work_days"]:
        out.append({**common, "id": str(uuid.uuid4()), "title": name, "day_of_week": day,
                    "start_time": role["start_time"], "end_time": role["end_time"], "commitment_type": "work"})
        c = role.get("commute_minutes") or 0
        if c and day in office:
            for s, e in ((start - c, start), (end, end + c)):
                out.append({**common, "id": str(uuid.uuid4()), "title": f"Commute ({name})", "day_of_week": day,
                            "start_time": _fmt(s), "end_time": _fmt(e), "commitment_type": "commute"})
    return out


async def _own_role(db, uid: str, rid: str) -> dict:
    r = await db.work_roles.find_one({"id": rid, "user_id": uid}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="Work role not found")
    return r


def _check_role(doc: dict) -> None:
    for f in ("started_on", "next_appraisal"):
        if doc.get(f) and not _d(doc[f]):
            raise HTTPException(status_code=400, detail=f"{f} must be YYYY-MM-DD.")
    for t in doc.get("leave_types") or []:
        if not re.match(r"^\d{2}-\d{2}$", t.get("year_starts") or ""):
            raise HTTPException(status_code=400, detail="Leave year start must be MM-DD.")
    if (doc.get("start_time") is None) != (doc.get("end_time") is None):
        raise HTTPException(status_code=400, detail="Give both a start and an end time.")
    if doc.get("leave_types") and doc["type"] not in EMPLOYED:
        raise HTTPException(status_code=400, detail="Leave is for employed roles; block time off instead.")


async def _save_blocks(db, uid: str, role: dict) -> None:
    await db.time_commitments.delete_many({"user_id": uid, "source_type": "system", "source_id": role["id"]})
    blocks = _blocks_for(uid, role) if role.get("status", "active") == "active" else []
    if blocks:
        await db.time_commitments.insert_many(blocks)


@work_router.post("/roles", status_code=201)
async def add_role(body: RoleIn, current_user: dict = Depends(get_current_user)):
    db = get_db()
    uid = current_user["id"]
    doc = body.model_dump()
    _check_role(doc)
    doc.update(id=str(uuid.uuid4()), user_id=uid, status="active", ended_on=None, created_at=_now(),
               updated_at=_now())
    blocks = _blocks_for(uid, doc)                      # validates times before saving anything
    await db.work_roles.insert_one(dict(doc))
    if blocks:
        await db.time_commitments.insert_many(blocks)
    return await _role_view(db, doc)


class RolePatch(BaseModel):
    organisation: Optional[str] = Field(default=None, max_length=120)
    title: Optional[str] = Field(default=None, max_length=120)
    work_days: Optional[List[Literal[DAYS]]] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    office_days: Optional[List[Literal[DAYS]]] = None
    commute_minutes: Optional[int] = Field(default=None, ge=0, le=240)
    leave_types: Optional[List[LeaveType]] = Field(default=None, max_length=8)
    next_appraisal: Optional[str] = None
    notes: Optional[str] = Field(default=None, max_length=1000)
    ended_on: Optional[str] = None                     # the role ended (job left)


@work_router.patch("/roles/{rid}")
async def update_role(rid: str, body: RolePatch, current_user: dict = Depends(get_current_user)):
    db = get_db()
    uid = current_user["id"]
    role = await _own_role(db, uid, rid)
    changes = body.model_dump(exclude_unset=True)
    if "ended_on" in changes and changes["ended_on"]:
        if not _d(changes["ended_on"]):
            raise HTTPException(status_code=400, detail="ended_on must be YYYY-MM-DD.")
        changes["status"] = "ended"
    merged = {**role, **changes, "updated_at": _now()}
    _check_role(merged)
    _blocks_for(uid, merged)
    await db.work_roles.replace_one({"id": rid, "user_id": uid}, merged)
    await _save_blocks(db, uid, merged)
    return await _role_view(db, merged)


@work_router.delete("/roles/{rid}")
async def delete_role(rid: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    uid = current_user["id"]
    await _own_role(db, uid, rid)
    await db.work_roles.delete_one({"id": rid, "user_id": uid})
    await db.time_commitments.delete_many({"user_id": uid, "source_type": "system", "source_id": rid})
    for coll in ("work_leave", "work_wins", "work_days", "payslips"):
        await db[coll].delete_many({"user_id": uid, "role_id": rid})
    return {"detail": "Deleted"}


async def _role_view(db, role: dict) -> dict:
    out = {k: v for k, v in role.items() if k not in ("_id", "user_id")}
    today = date_type.today()
    if role["type"] in EMPLOYED:
        leaves = await db.work_leave.find({"user_id": role["user_id"], "role_id": role["id"]}, {"_id": 0}) \
            .to_list(length=None)
        out["leave"] = leave_balances(role, leaves, today)
    if role.get("start_time") and role.get("end_time"):
        day = (_hm(role["end_time"]) - _hm(role["start_time"])) % 1440
        out["planned_hours_per_week"] = round(day * len(role["work_days"]) / 60, 1)
        out["commute_hours_per_week"] = round(2 * (role.get("commute_minutes") or 0) *
                                              len(role.get("office_days") or role["work_days"]) / 60, 1)
    out["features"] = {"leave": role["type"] in EMPLOYED, "appraisal": role["type"] in EMPLOYED,
                       "payslips": role["type"] == "salaried", "wins": True, "time": True}
    return out


@work_router.get("/roles")
async def list_roles(current_user: dict = Depends(get_current_user)):
    db = get_db()
    return [await _role_view(db, r) async for r in db.work_roles.find({"user_id": current_user["id"]}, {"_id": 0})]


@work_router.get("/roles/{rid}")
async def get_role(rid: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    return await _role_view(db, await _own_role(db, current_user["id"], rid))


# ---------------------------------------------------------------------------
# Work days: ran over / ended early
# ---------------------------------------------------------------------------

class WorkDay(BaseModel):
    role_id: str
    date: str
    extra_minutes: int = Field(ge=-1440, le=1440)          # + stayed late / worked weekend; − left early
    note: str = Field(default="", max_length=200)


@work_router.post("/days", status_code=201)
async def log_day(body: WorkDay, current_user: dict = Depends(get_current_user)):
    """One entry per role per day; a new one replaces it."""
    db = get_db()
    uid = current_user["id"]
    await _own_role(db, uid, body.role_id)
    if not _d(body.date):
        raise HTTPException(status_code=400, detail="Dates must be YYYY-MM-DD.")
    await db.work_days.update_one({"user_id": uid, "role_id": body.role_id, "date": body.date},
                                  {"$set": {"extra_minutes": body.extra_minutes, "note": body.note,
                                            "updated_at": _now()},
                                   "$setOnInsert": {"id": str(uuid.uuid4())}}, upsert=True)
    return {"saved": True}


async def overtime_minutes(db, uid: str, first: str, last: str) -> int:
    total = 0
    async for d in db.work_days.find({"user_id": uid, "date": {"$gte": first, "$lte": last}}, {"_id": 0}):
        total += d["extra_minutes"]
    return total


@work_router.get("/week")
async def week(week_start: Optional[str] = Query(None), current_user: dict = Depends(get_current_user)):
    """Did work stay in its box this week? Work, commute, family time,
    sleep and stress (health, only with consent), against last week."""
    import time_reports

    db, uid = get_db(), current_user["id"]
    monday = _d(week_start) or date_type.today()
    monday -= timedelta(days=monday.weekday())

    async def numbers(mon: date_type) -> dict:
        stmts = await time_reports.week_statements(db, uid, mon)
        areas = {a["area"]: a for a in stmts["spent"]["areas"]}

        def hours(area, f):
            return float(areas.get(area, {}).get(f, 0) or 0)
        return {"work_planned": hours("work", "planned_hours"), "work_actual": hours("work", "actual_hours"),
                "commute": hours("commute", "actual_hours"), "family": hours("family", "actual_hours")}
    this, last = await numbers(monday), await numbers(monday - timedelta(days=7))
    over = round(this["work_actual"] - this["work_planned"], 1)
    out = {"week_start": monday.isoformat(), **this, "over_plan_hours": over,
           "in_its_box": over * 60 <= IN_BOX_MINUTES, "last_week": last,
           "family_change_hours": round(this["family"] - last["family"], 1)}
    if await db.health_profiles.find_one({"user_id": uid, "consent": True}, {"_id": 1}):
        import health
        rows = await db.health_measurements.find({"user_id": uid, "metric": {"$in": ["sleep_hours", "stress"]}},
                                                 {"_id": 0}).to_list(length=None)
        rows = health.one_per_day(rows)

        def avg(metric, mon):
            vals = [r["value"] for r in rows if r["metric"] == metric and
                    mon.isoformat() <= r["taken_on"][:10] <= (mon + timedelta(days=6)).isoformat()]
            return round(sum(vals) / len(vals), 1) if vals else None
        out["sleep_avg"], out["stress_avg"] = avg("sleep_hours", monday), avg("stress", monday)
        out["sleep_avg_last_week"] = avg("sleep_hours", monday - timedelta(days=7))
    if out["in_its_box"]:
        out["summary"] = "Work stayed in its box this week."
    else:
        bits = [f"Work ran {over:g} hours over plan"]
        if out["family_change_hours"] < 0:
            bits.append(f"family time was down {abs(out['family_change_hours']):g} hours")
        if out.get("sleep_avg") is not None and out.get("sleep_avg_last_week") is not None \
                and out["sleep_avg"] < out["sleep_avg_last_week"]:
            bits.append("sleep was shorter")
        out["summary"] = ", ".join(bits) + "."
    return out


# ---------------------------------------------------------------------------
# Leave
# ---------------------------------------------------------------------------

class LeaveIn(BaseModel):
    role_id: str
    type: str
    from_: str = Field(alias="from")
    to: str
    half_day: bool = False
    days: Optional[float] = Field(default=None, gt=0, le=366)   # override (holidays in between…)
    reason: str = Field(default="", max_length=200)
    model_config = {"populate_by_name": True}


@work_router.post("/leave", status_code=201)
async def add_leave(body: LeaveIn, current_user: dict = Depends(get_current_user)):
    db = get_db()
    uid = current_user["id"]
    role = await _own_role(db, uid, body.role_id)
    if role["type"] not in EMPLOYED:
        raise HTTPException(status_code=400, detail="Leave is for employed roles.")
    if body.type not in {t["key"] for t in role.get("leave_types") or []}:
        raise HTTPException(status_code=400, detail="Add this leave type to the role first.")
    start, end = _d(body.from_), _d(body.to)
    if not start or not end or end < start:
        raise HTTPException(status_code=400, detail="Leave needs a from and to date (to on or after from).")
    days = body.days or leave_days(start, end, role["work_days"], body.half_day)
    doc = {"id": str(uuid.uuid4()), "user_id": uid, "role_id": role["id"], "type": body.type, "from": start.isoformat(),
           "to": end.isoformat(), "days": days, "reason": body.reason, "status": "booked", "created_at": _now()}
    await db.work_leave.insert_one(dict(doc))
    doc.pop("user_id")
    left = next((b for b in leave_balances(role, await db.work_leave.find(
        {"user_id": uid, "role_id": role["id"]}, {"_id": 0}).to_list(length=None), date_type.today())
        if b["type"] == body.type), None)
    return {**doc, "balance": left, "warning": "This goes beyond your balance." if left and left["left"] < 0 else None}


@work_router.delete("/leave/{lid}")
async def cancel_leave(lid: str, current_user: dict = Depends(get_current_user)):
    r = await get_db().work_leave.update_one({"id": lid, "user_id": current_user["id"]},
                                             {"$set": {"status": "cancelled"}})
    if not r.matched_count:
        raise HTTPException(status_code=404, detail="Leave not found")
    return {"detail": "Cancelled"}


async def leave_left(db, uid: str, by: Optional[date_type] = None) -> List[dict]:
    """Leave left per role and type (for the planner)."""
    today = date_type.today()
    out = []
    async for role in db.work_roles.find({"user_id": uid, "status": "active", "type": {"$in": list(EMPLOYED)}},
                                         {"_id": 0}):
        leaves = await db.work_leave.find({"user_id": uid, "role_id": role["id"]}, {"_id": 0}).to_list(length=None)
        for b in leave_balances(role, leaves, today):
            out.append({"role": role.get("organisation") or role.get("title") or "Work", **b})
    return out


# ---------------------------------------------------------------------------
# Wins and appraisals
# ---------------------------------------------------------------------------

class WinIn(BaseModel):
    role_id: str
    date: str
    text: str = Field(min_length=1, max_length=500)


@work_router.post("/wins", status_code=201)
async def add_win(body: WinIn, current_user: dict = Depends(get_current_user)):
    db = get_db()
    uid = current_user["id"]
    await _own_role(db, uid, body.role_id)
    if not _d(body.date):
        raise HTTPException(status_code=400, detail="Dates must be YYYY-MM-DD.")
    doc = {"id": str(uuid.uuid4()), "user_id": uid, **body.model_dump(), "created_at": _now()}
    await db.work_wins.insert_one(dict(doc))
    doc.pop("user_id")
    return doc


@work_router.delete("/wins/{wid}")
async def delete_win(wid: str, current_user: dict = Depends(get_current_user)):
    r = await get_db().work_wins.delete_one({"id": wid, "user_id": current_user["id"]})
    if not r.deleted_count:
        raise HTTPException(status_code=404, detail="Win not found")
    return {"detail": "Deleted"}


@work_router.get("/roles/{rid}/appraisal-pack")
async def appraisal_pack(rid: str, since: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    """Everything to bring to an appraisal: wins by month since the last one
    (default: 12 months), and study hours in learning journeys."""
    db = get_db()
    uid = current_user["id"]
    role = await _own_role(db, uid, rid)
    start = _d(since) or (date_type.today() - timedelta(days=365))
    wins = await db.work_wins.find({"user_id": uid, "role_id": rid, "date": {"$gte": start.isoformat()}},
                                   {"_id": 0, "user_id": 0}).sort("date", 1).to_list(length=None)
    by_month: Dict[str, List[str]] = defaultdict(list)
    for w in wins:
        by_month[w["date"][:7]].append(w["text"])
    study = defaultdict(int)
    async for s in db.learning_sessions.find({"user_id": uid, "date": {"$gte": start.isoformat()}}, {"_id": 0}):
        study[s.get("title") or "Study"] += s["minutes"]
    return {"role": role.get("title") or role.get("organisation"), "since": start.isoformat(),
            "next_appraisal": role.get("next_appraisal"), "wins": len(wins),
            "wins_by_month": [{"month": m, "wins": t} for m, t in sorted(by_month.items())],
            "learning": [{"journey": k, "hours": round(v / 60, 1)} for k, v in study.items()]}


# ---------------------------------------------------------------------------
# Payslips (Premium)
# ---------------------------------------------------------------------------

def _money(v) -> Optional[Decimal]:
    try:
        d = Decimal(str(v).replace(",", "").strip())
        return d if d.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def deduction_kind(label: str) -> str:
    """Sort a payslip deduction by its printed label."""
    text = " " + " ".join(re.sub(r"[^a-z ]", " ", label.lower().replace(".", "")).split()) + " "
    words = set(text.split())
    if "provident" in text or words & {"pf", "epf", "vpf"}:
        return "pf"
    if "professional" in text or "prof tax" in text or " p tax " in text or words & {"pt", "ptax"}:
        return "professional_tax"
    if "income tax" in text or words & {"tds", "it"}:
        return "income_tax"
    if any(w in text for w in ("insurance", "mediclaim", "medical premium")) or words & {"gmc", "ghi"}:
        return "health_insurance"
    return "other"


def check_payslip(earnings: List[dict], deductions: List[dict], gross: Optional[Decimal],
                  net: Optional[Decimal]) -> List[str]:
    problems = []
    e = sum((_money(x["amount"]) or Decimal(0) for x in earnings), Decimal(0))
    dd = sum((_money(x["amount"]) or Decimal(0) for x in deductions), Decimal(0))
    if gross is not None and abs(e - gross) > 1:
        problems.append(f"Earnings add up to {e}, but gross is {gross}.")
    if gross is not None and net is not None and abs(gross - dd - net) > 1:
        problems.append(f"Gross {gross} minus deductions {dd} is {gross - dd}, but take-home is {net}.")
    return problems


class PayslipUpload(BaseModel):
    file_base64: str
    media_type: Literal["application/pdf", "image/jpeg", "image/png", "image/webp"] = "application/pdf"
    password: str = Field(default="", max_length=64)          # used in memory only


@work_router.post("/payslips/read")
async def read_payslip(body: PayslipUpload, current_user: dict = Depends(get_current_user)):
    """Read a payslip into numbers to confirm. Nothing is saved; the file
    and password are not kept."""
    import payslip_ai
    import statements
    from claude_client import AssistantUnavailable

    require_feature(current_user, "statements", "Reading payslips is part of Premium.")
    try:
        data = base64.b64decode(body.file_base64.split(",")[-1], validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="That file couldn't be read.")
    if not data or len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Please use a file under 10 MB.")
    if body.media_type == "application/pdf":
        try:
            data = statements.split_pages(statements.open_pdf(data, body.password or None), 50)[0]
        except statements.StatementFileError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    try:
        p = await payslip_ai.read_payslip(data, body.media_type)
    except AssistantUnavailable:
        raise HTTPException(status_code=503, detail="Hymn couldn't read the payslip right now. You can type it in.")
    if not p.is_payslip:
        return {"is_payslip": False}
    earnings = [x.model_dump() for x in p.earnings]
    deductions = [{**x.model_dump(), "kind": deduction_kind(x.label)} for x in p.deductions]
    gross, net = _money(p.gross), _money(p.net)
    return {"is_payslip": True, "month": p.month, "employer": p.employer, "earnings": earnings,
            "deductions": deductions, "gross": p.gross, "net": p.net, "employer_pf": p.employer_pf,
            "problems": check_payslip(earnings, deductions, gross, net),
            "note": "Check these against your payslip before saving."}


class PayLine(BaseModel):
    label: str = Field(max_length=80)
    amount: str
    kind: Optional[Literal["pf", "income_tax", "professional_tax", "health_insurance", "other"]] = None


class PayslipIn(BaseModel):
    role_id: str
    month: str                                               # YYYY-MM
    earnings: List[PayLine] = Field(max_length=40)
    deductions: List[PayLine] = Field(max_length=40)
    gross: str
    net: str
    employer_pf: str = "0"
    pf_account_id: Optional[str] = None                      # your EPF account (money book)


@work_router.post("/payslips", status_code=201)
async def save_payslip(body: PayslipIn, current_user: dict = Depends(get_current_user)):
    import ledger
    import ledger_sync

    db = get_db()
    uid = current_user["id"]
    role = await _own_role(db, uid, body.role_id)
    if role["type"] != "salaried":
        raise HTTPException(status_code=400, detail="Payslips are for salaried roles.")
    if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", body.month):
        raise HTTPException(status_code=400, detail="Month must be YYYY-MM.")
    gross, net, emp_pf = _money(body.gross), _money(body.net), _money(body.employer_pf or "0")
    if gross is None or net is None or emp_pf is None or gross <= 0 or net < 0:
        raise HTTPException(status_code=400, detail="Gross and take-home must be amounts.")
    deductions = [{**d.model_dump(), "kind": d.kind or deduction_kind(d.label)} for d in body.deductions]
    earnings = [e.model_dump() for e in body.earnings]
    if any(_money(x["amount"]) is None for x in earnings + deductions):
        raise HTTPException(status_code=400, detail="Every line needs an amount.")
    problems = check_payslip(earnings, deductions, gross, net)
    if problems:
        raise HTTPException(status_code=400, detail={"message": "These don't add up.", "problems": problems})
    if await db.payslips.find_one({"user_id": uid, "role_id": role["id"], "month": body.month}, {"_id": 1}):
        raise HTTPException(status_code=409, detail="That month's payslip is already saved.")
    totals = defaultdict(Decimal)
    for d in deductions:
        totals[d["kind"]] += _money(d["amount"])
    pid = str(uuid.uuid4())
    recorded = []
    converted = (await ledger_sync.sync(db, uid))["converted"]
    if converted:
        accounts = await ledger.real_accounts_for(db, uid)
        pf_acct = body.pf_account_id
        if pf_acct and accounts.get(pf_acct, {}).get("account_type") != "epf":
            raise HTTPException(status_code=400, detail="Pick your EPF account for PF.")
        y, m = map(int, body.month.split("-"))
        on = (date_type(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).isoformat()
        evidence = [f"payslip:{pid}"]
        pf_total = totals["pf"] + emp_pf
        if pf_acct and pf_total:
            await ledger.record(db, uid, ledger.Draft(kind="income", date=on, currency="INR", amount=str(pf_total),
                                                      to_account_id=pf_acct, category="income:salary_withheld",
                                                      description=f"PF from salary ({body.month})"),
                                provenance="payslip", evidence_ids=evidence)
            recorded.append("pf")
        for kind, cat in (("income_tax", "expense:income_tax"), ("professional_tax", "expense:taxes"),
                          ("health_insurance", "expense:health_insurance"), ("other", "expense:uncategorised")):
            if totals[kind]:
                await ledger.record(db, uid, ledger.Draft(kind="salary_deduction", date=on, currency="INR",
                                                          amount=str(totals[kind]), category=cat,
                                                          description=_deduction_note(kind, deductions, body.month)),
                                    provenance="payslip", evidence_ids=evidence)
                recorded.append(kind)
    doc = {"id": pid, "user_id": uid, "role_id": role["id"], "month": body.month, "gross": str(gross),
           "net": str(net), "employer_pf": str(emp_pf), "earnings": earnings, "deductions": deductions,
           "totals": {k: str(v) for k, v in totals.items()}, "recorded_in_money_book": recorded, "created_at": _now()}
    await db.payslips.insert_one(dict(doc))
    doc.pop("user_id")
    return doc


@work_router.get("/payslips")
async def list_payslips(role_id: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    q = {"user_id": current_user["id"], **({"role_id": role_id} if role_id else {})}
    rows = await get_db().payslips.find(q, {"_id": 0, "user_id": 0}).sort("month", -1).to_list(length=120)
    return rows


def _deduction_note(kind: str, deductions: List[dict], month: str) -> str:
    if kind == "other":   # canteen, loan recovery…: shown as "not yet sorted" for the person to file
        labels = ", ".join(d["label"] for d in deductions if d["kind"] == "other")
        return f"Other deductions from salary ({month}): {labels}"[:200]
    return f"{kind.replace('_', ' ').capitalize()} from salary ({month})"


async def take_home(db, uid: str) -> Optional[Decimal]:
    """Average take-home of the last three payslips (for the planner)."""
    rows = await db.payslips.find({"user_id": uid}, {"_id": 0, "net": 1}).sort("month", -1).to_list(length=3)
    return sum((Decimal(r["net"]) for r in rows), Decimal(0)) / len(rows) if rows else None


# ---------------------------------------------------------------------------
# Nudges (setting ``work``)
# ---------------------------------------------------------------------------

async def work_nudges(db, user: dict, settings: dict, now: datetime) -> List[dict]:
    from nudges import _claim, _due, _tz, hhmm_to_minute, in_quiet_hours

    cfg = settings.get("work") or {}
    if not cfg.get("enabled", True):
        return []
    local = now.astimezone(_tz(user.get("timezone")))
    quiet = settings["quiet_hours"]
    if in_quiet_hours(local.hour * 60 + local.minute, quiet["start"], quiet["end"]):
        return []
    at = _due(local, hhmm_to_minute(cfg.get("time") or "18:30"))
    if at is None:
        return []
    today = local.date()
    uid = user["id"]
    out = []
    roles = [r async for r in db.work_roles.find({"user_id": uid, "status": "active"}, {"_id": 0})]
    for r in roles:
        name = r.get("organisation") or r.get("title") or "work"
        ap = _d(r.get("next_appraisal"))
        if ap and (ap - today).days == APPRAISAL_NOTICE_DAYS:
            wins = await db.work_wins.count_documents({"user_id": uid, "role_id": r["id"]})
            n = await _claim(db, uid, "work_appraisal", f"work_appraisal:{r['id']}:{ap.isoformat()}",
                             f"Appraisal at {name} in 3 weeks",
                             f"You've logged {wins} win{'s' if wins != 1 else ''}. Add any you remember.",
                             {"screen": "work", "role_id": r["id"]}, at)
            if n:
                out.append(n)
        if r["type"] in EMPLOYED:
            leaves = await db.work_leave.find({"user_id": uid, "role_id": r["id"]}, {"_id": 0}).to_list(length=None)
            for b in leave_balances(r, leaves, today):
                ends = _d(b["year_ends"])
                if b.get("expiring") and (ends - today).days == LEAVE_EXPIRY_NOTICE_DAYS:
                    n = await _claim(db, uid, "work_leave", f"work_leave:{r['id']}:{b['type']}:{b['year_ends']}",
                                     f"{b['expiring']:g} {b['label'].lower()} days expire on {b['year_ends']}",
                                     "A good time to plan a break.", {"screen": "work", "role_id": r["id"]}, at)
                    if n:
                        out.append(n)
    if roles and local.weekday() == 4:                       # Friday: the week in its box?
        over = await overtime_minutes(db, uid, (today - timedelta(days=4)).isoformat(), today.isoformat())
        if over > IN_BOX_MINUTES:
            n = await _claim(db, uid, "work_week", f"work_week:{today.isoformat()}",
                             f"Work ran {over / 60:.1f} hours over this week",
                             "The weekend is yours. See how the week went.", {"screen": "work"}, at)
            if n:
                out.append(n)
    return out


async def ensure_work_indexes(db) -> None:
    await db.work_roles.create_index([("user_id", 1), ("id", 1)], unique=True)
    await db.work_days.create_index([("user_id", 1), ("role_id", 1), ("date", 1)], unique=True)
    await db.work_leave.create_index([("user_id", 1), ("role_id", 1)])
    await db.work_wins.create_index([("user_id", 1), ("role_id", 1), ("date", 1)])
    await db.payslips.create_index([("user_id", 1), ("role_id", 1), ("month", 1)], unique=True)
