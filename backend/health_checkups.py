"""Check-up calendar: which routine checks are due, for this person.

Built from age, sex, conditions, family history and tobacco use, following
India's national screening programme for adults 30+ (blood pressure,
diabetes, oral, breast and cervical cancer) and widely used intervals for the
rest. DRAFT until a doctor reviews it (``health.RULES_REVIEWED``); always
"ask your doctor" for what's right for you.

A check counts as done when a matching value is logged (a BP reading, an
HbA1c from a lab report…) or the person marks it done.
"""
from __future__ import annotations

import calendar
from datetime import date as date_type, datetime, timezone
from typing import Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from deps import get_current_user, get_db
from health import RULES_REVIEWED, _date, _profile, age_on, summarise

checkups_router = APIRouter(prefix="/health/checkups", tags=["health"])


def _has(p: dict, condition: str) -> bool:
    return condition in (p.get("conditions") or [])


def _fam(p: dict, item: str) -> bool:
    return item in (p.get("family_history") or [])


class Check:
    def __init__(self, key: str, label: str, why: str, applies: Callable[[dict, Optional[int], dict], bool],
                 months: Callable[[dict, Optional[int], dict], int], metrics: tuple = (), ask_doctor: bool = False):
        self.key, self.label, self.why = key, label, why
        self.applies, self.months, self.metrics, self.ask_doctor = applies, months, metrics, ask_doctor


def _raised(latest: dict, metric: str, limit: float) -> bool:
    got = latest.get(metric)
    return bool(got and float(got["value"]) >= limit)


CHECKS: List[Check] = [
    Check("blood_pressure", "Blood pressure check", "High BP has no symptoms and is the biggest risk for heart "
          "attack and stroke.",
          lambda p, a, l: a is None or a >= 18,
          lambda p, a, l: 6 if (_has(p, "high_blood_pressure") or _has(p, "diabetes")
                                or _raised(l, "bp_systolic", 130) or _raised(l, "bp_diastolic", 80)) else 12,
          ("bp_systolic", "bp_diastolic")),
    Check("diabetes", "Blood sugar test (fasting glucose or HbA1c)", "Type 2 diabetes starts younger in South "
          "Asians and is silent for years.",
          lambda p, a, l: not _has(p, "diabetes") and a is not None and (a >= 30 or (a >= 25 and _fam(p, "diabetes"))),
          lambda p, a, l: 12 if (_fam(p, "diabetes") or _raised(l, "fasting_glucose", 100)
                                 or _raised(l, "hba1c", 5.7) or _raised(l, "waist_cm", 80)) else 36,
          ("fasting_glucose", "hba1c")),
    Check("diabetes_review", "HbA1c (diabetes review)", "Shows how well sugar has been controlled over 3 months.",
          lambda p, a, l: _has(p, "diabetes"), lambda p, a, l: 3, ("hba1c",), ask_doctor=True),
    Check("lipids", "Cholesterol test (lipid profile)", "Cholesterol builds up silently in the arteries.",
          lambda p, a, l: a is not None and a >= 20,
          lambda p, a, l: 12 if (_has(p, "diabetes") or _has(p, "heart_disease") or _has(p, "high_blood_pressure")
                                 or _fam(p, "heart_disease_before_60")) else 60,
          ("ldl", "hdl", "triglycerides")),
    Check("kidney", "Kidney tests (eGFR and urine albumin)", "Diabetes and high BP can quietly harm the kidneys.",
          lambda p, a, l: _has(p, "diabetes") or _has(p, "high_blood_pressure") or _has(p, "kidney_disease"),
          lambda p, a, l: 12, ("egfr", "uacr")),
    Check("diabetic_eye", "Eye check for diabetes (retina)", "Diabetes can damage the retina before vision changes.",
          lambda p, a, l: _has(p, "diabetes"), lambda p, a, l: 12),
    Check("eyes", "Eye check", "Near vision, glaucoma and cataract become common after 40.",
          lambda p, a, l: not _has(p, "diabetes") and a is not None and a >= 40, lambda p, a, l: 24),
    Check("dental", "Dental check", "Gum disease is common, painless early and linked to heart health.",
          lambda p, a, l: True, lambda p, a, l: 12),
    Check("oral_cancer", "Mouth check (oral cancer screening)", "Tobacco makes mouth cancer much more likely; "
          "early patches are easy to treat.",
          lambda p, a, l: p.get("smoking") == "current" or p.get("_tobacco") or (a is not None and a >= 30),
          lambda p, a, l: 12 if (p.get("smoking") == "current" or p.get("_tobacco")) else 60),
    Check("breast", "Breast check", "Breast cancer found early is very treatable.",
          lambda p, a, l: p.get("sex") == "female" and a is not None and a >= 30,
          lambda p, a, l: 12 if _fam(p, "cancer") else 60, ask_doctor=True),
    Check("cervical", "Cervical screening (HPV test or VIA)", "Cervical cancer is preventable with screening.",
          lambda p, a, l: p.get("sex") == "female" and a is not None and 30 <= a <= 65, lambda p, a, l: 60),
    Check("bowel", "Bowel cancer check (ask your doctor)", "Worth discussing from 50, sooner with family history.",
          lambda p, a, l: a is not None and (a >= 50 or (a >= 40 and _fam(p, "cancer"))), lambda p, a, l: 60,
          ask_doctor=True),
    Check("hearing", "Hearing check", "Treating hearing loss protects memory and independence.",
          lambda p, a, l: bool(p.get("hearing_difficulty")) or (a is not None and a >= 60), lambda p, a, l: 24),
    Check("bones", "Bone density (DEXA)", "Weak bones lead to fractures that cost independence.",
          lambda p, a, l: p.get("sex") == "female" and a is not None and a >= 65, lambda p, a, l: 24,
          ask_doctor=True),
    Check("thyroid", "Thyroid test (TSH)", "Keeps thyroid medicine at the right dose.",
          lambda p, a, l: _has(p, "thyroid"), lambda p, a, l: 12, ask_doctor=True),
    Check("weight_waist", "Weight and waist (at home)", "Waist size is an early sign of metabolic risk.",
          lambda p, a, l: a is None or a >= 18, lambda p, a, l: 3, ("weight_kg", "waist_cm")),
]


def add_months(d: date_type, months: int) -> date_type:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return date_type(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def calendar_for(profile: dict, rows: List[dict], marked: Dict[str, str], today: date_type) -> dict:
    latest = summarise(rows, today)
    age = age_on(profile.get("date_of_birth"), today)
    last_by_metric: Dict[str, str] = {}
    for r in rows:
        if r["metric"] not in last_by_metric or r["taken_on"] > last_by_metric[r["metric"]]:
            last_by_metric[r["metric"]] = r["taken_on"][:10]
    out = []
    for c in CHECKS:
        if not c.applies(profile, age, latest):
            continue
        months = c.months(profile, age, latest)
        dates = [last_by_metric[m] for m in c.metrics if m in last_by_metric] + \
            ([marked[c.key]] if c.key in marked else [])
        last = max(dates) if dates else None
        if last is None:
            status, due = "never", today
        else:
            due = add_months(date_type.fromisoformat(last), months)
            status = "overdue" if due < today else "due_soon" if (due - today).days <= 30 else "ok"
        out.append({"key": c.key, "label": c.label, "why": c.why, "every_months": months, "last_done": last,
                    "next_due": due.isoformat(), "status": status, "ask_doctor": c.ask_doctor})
    order = {"overdue": 0, "never": 1, "due_soon": 2, "ok": 3}
    out.sort(key=lambda x: (order[x["status"]], x["next_due"]))
    return {"rules_reviewed": RULES_REVIEWED, "checks": out,
            "missing_profile": [f for f in ("date_of_birth", "sex") if not profile.get(f)],
            "note": "A starting point to discuss with your doctor, who knows what's right for you."}


async def _calendar(db, user: dict) -> dict:
    uid = user["id"]
    profile = await _profile(db, uid)
    tobacco = await db.habits.find_one({"user_id": uid, "kind": "tobacco", "status": "active"})
    profile = {**profile, "_tobacco": bool(tobacco)}
    rows = await db.health_measurements.find({"user_id": uid}, {"_id": 0}).to_list(length=None)
    marked = {m["key"]: m["date"] async for m in db.health_checkups.find({"user_id": uid}, {"_id": 0})}
    return calendar_for(profile, rows, marked, date_type.today())


@checkups_router.get("")
async def get_calendar(current_user: dict = Depends(get_current_user)):
    return await _calendar(get_db(), current_user)


class Done(BaseModel):
    date: str


@checkups_router.post("/{key}/done")
async def mark_done(key: str, body: Done, current_user: dict = Depends(get_current_user)):
    if key not in {c.key for c in CHECKS}:
        raise HTTPException(status_code=404, detail="Unknown check")
    db = get_db()
    await _profile(db, current_user["id"])
    day = _date(body.date)
    if day > date_type.today().isoformat():
        raise HTTPException(status_code=400, detail="That date is in the future.")
    await db.health_checkups.update_one({"user_id": current_user["id"], "key": key},
                                        {"$set": {"date": day, "updated_at": datetime.now(timezone.utc).isoformat()}},
                                        upsert=True)
    return await _calendar(db, current_user)
