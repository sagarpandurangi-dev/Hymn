"""Two health reports, both computed in code (no AI):

* **90-day progress** — the first 30 days from a start date (the baseline)
  against days 61–90 (or the latest 30 days while the 90 days are still
  running), per signal: before, after, change and better / worse / steady.
  Weight change is shown without a verdict (no praise or blame for a number
  on a scale).
* **Doctor summary** — one page to show a doctor: profile, medicines, family
  history, latest readings with date and source, 90-day changes, symptoms
  logged in the last 90 days, habits being worked on (private ones only if
  the person chooses), check-ups due, lab results as printed, and their
  questions. JSON for the app, or plain text to share.
"""
from __future__ import annotations

from datetime import date as date_type, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse

from deps import get_current_user, get_db
from health import (METRICS, RED_FLAG_SYMPTOMS, RULES_REVIEWED, _date, _profile, age_on, one_per_day, person,
                    subject, summarise)
from health_checkups import _calendar

reports_router = APIRouter(prefix="/health", tags=["health"])

HIGHER_BETTER = {"steps", "active_minutes", "strength_session", "veg_fruit_portions", "protein_servings", "mood",
                 "energy", "contentment", "digestion", "bowel", "water_glasses", "hdl", "egfr", "vo2max",
                 "chair_stands_30s", "one_leg_stand_s", "social_hours", "learning_hours"}
LOWER_BETTER = {"sugary_items", "outside_meals", "stress", "screen_hours", "resting_hr", "bp_systolic",
                "bp_diastolic", "fasting_glucose", "hba1c", "ldl", "triglycerides", "uacr", "waist_cm"}
NO_VERDICT = {"weight_kg", "height_cm"}
STEADY_WITHIN = Decimal("0.05")          # under 5% change reads as steady
MIN_POINTS = 3                           # per period, for daily signals


def _avg(vals: List[Decimal]) -> Optional[Decimal]:
    return sum(vals) / len(vals) if vals else None


def _fmt(v: Decimal) -> str:
    return format(v.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP), "f")


def verdict(metric: str, before: Decimal, after: Decimal) -> str:
    if metric in NO_VERDICT:
        return "changed" if before != after else "steady"
    if metric == "sleep_hours":           # closer to 7–9 is better
        def gap(v):
            return Decimal(0) if 7 <= v <= 9 else min(abs(v - 7), abs(v - 9))
        g1, g2 = gap(before), gap(after)
        return "steady" if abs(g1 - g2) < Decimal("0.25") else "better" if g2 < g1 else "worse"
    base = abs(before) or Decimal(1)
    if abs(after - before) / base < STEADY_WITHIN:
        return "steady"
    up = after > before
    if metric in HIGHER_BETTER:
        return "better" if up else "worse"
    if metric in LOWER_BETTER:
        return "worse" if up else "better"
    return "changed"


def progress(rows: List[dict], start: date_type, today: date_type) -> dict:
    rows = one_per_day(rows)
    base_end = start + timedelta(days=29)
    day_n = (today - start).days + 1
    if day_n >= 90:
        after_start, after_end = start + timedelta(days=60), start + timedelta(days=89)
    else:
        after_start, after_end = max(base_end + timedelta(days=1), today - timedelta(days=29)), today
    by_metric: Dict[str, List[dict]] = {}
    for r in rows:
        by_metric.setdefault(r["metric"], []).append(r)
    lines = []
    for metric, items in by_metric.items():
        if metric not in METRICS:
            continue
        before = [Decimal(str(r["value"])) for r in items if start.isoformat() <= r["taken_on"][:10] <= base_end.isoformat()]
        after = [Decimal(str(r["value"])) for r in items
                 if after_start.isoformat() <= r["taken_on"][:10] <= after_end.isoformat()]
        need = MIN_POINTS if metric in {"steps", "active_minutes", "sleep_hours", "mood", "stress", "energy",
                                        "digestion", "bowel", "screen_hours", "veg_fruit_portions",
                                        "protein_servings", "sugary_items", "outside_meals", "water_glasses"} else 1
        if len(before) < need or len(after) < need:
            continue
        b, a = _avg(before), _avg(after)
        lines.append({"metric": metric, "label": METRICS[metric][0], "unit": METRICS[metric][1],
                      "before": _fmt(b), "after": _fmt(a), "change": _fmt(a - b), "verdict": verdict(metric, b, a),
                      "points": [len(before), len(after)]})
    order = {"better": 0, "worse": 1, "changed": 2, "steady": 3}
    lines.sort(key=lambda l: (order[l["verdict"]], l["label"]))
    return {"start": start.isoformat(), "day": min(day_n, 90), "complete": day_n >= 90,
            "baseline": [start.isoformat(), base_end.isoformat()],
            "compared_with": [after_start.isoformat(), after_end.isoformat()] if day_n > 30 else None,
            "lines": lines if day_n > 30 else [],
            "note": None if day_n > 30 else f"Day {day_n} of 90: the comparison starts after the first 30 days."}


@reports_router.get("/progress")
async def get_progress(start: Optional[str] = None, current_user: dict = Depends(get_current_user),
        for_: Optional[str] = Query(default=None, alias="for")):
    """Before vs after over 90 days from ``start`` (default: the first day
    anything was logged)."""
    uid = await subject(get_db(), current_user, for_)
    db = get_db()
    await _profile(db, uid)
    rows = await db.health_measurements.find({"user_id": uid}, {"_id": 0}).to_list(length=None)
    today = date_type.today()
    if start:
        s = date_type.fromisoformat(_date(start))
    elif rows:
        s = date_type.fromisoformat(min(r["taken_on"][:10] for r in rows))
        s = max(s, today - timedelta(days=89))      # the most recent 90-day window
    else:
        return {"start": None, "lines": [], "note": "Log for a few weeks to see how things change."}
    return progress(rows, s, today)


async def summary(db, user: dict, include_private: bool) -> dict:
    uid = user["id"]
    profile = await _profile(db, uid)
    today = date_type.today()
    rows = await db.health_measurements.find({"user_id": uid}, {"_id": 0}).to_list(length=None)
    latest = summarise(rows, today)
    readings = []
    for metric, (label, unit, *_rest) in METRICS.items():
        got = latest.get(metric)
        if got:
            readings.append({"metric": metric, "label": label, "value": _fmt(got["value"]), "unit": unit,
                             "date": got["taken_on"][:10], "source": got["source"], "based_on": got["based_on"]})
    since = (today - timedelta(days=89)).isoformat()
    symptoms = [{"date": s["date"], "what": RED_FLAG_SYMPTOMS.get(s["symptom"], (s["symptom"],))[0]}
                async for s in db.health_symptoms.find({"user_id": uid, "date": {"$gte": since}}, {"_id": 0})]
    symptoms.sort(key=lambda s: s["date"], reverse=True)
    habits = []
    async for h in db.habits.find({"user_id": uid, "status": "active"}, {"_id": 0}):
        if h.get("private") and not include_private:
            continue
        habits.append({"habit": h.get("label") or h["kind"].replace("_", " "), "goal": h["goal"],
                       "since": h["started_on"]})
    first = min((r["taken_on"][:10] for r in rows), default=None)
    trend = progress(rows, max(date_type.fromisoformat(first), today - timedelta(days=89)), today) if first else None
    checkups = (await _calendar(db, user))["checks"]
    labs = await db.health_lab_reports.find({"user_id": uid}, {"_id": 0, "user_id": 0}) \
        .sort("report_date", -1).to_list(length=1)
    return {
        "name": user.get("name", ""), "prepared_on": today.isoformat(),
        "age": age_on(profile.get("date_of_birth"), today), "sex": profile.get("sex"),
        "conditions": profile.get("conditions", []), "medicines": profile.get("medicines", []),
        "family_history": profile.get("family_history", []), "smoking": profile.get("smoking"),
        "alcohol_drinks_per_week": profile.get("alcohol_drinks_per_week"),
        "pregnant_or_breastfeeding": profile.get("pregnant_or_breastfeeding", False),
        "readings": readings,
        "changes_90_days": [l for l in (trend or {}).get("lines", []) if l["verdict"] != "steady"],
        "symptoms_90_days": symptoms, "habits": habits,
        "checkups_due": [c for c in checkups if c["status"] in ("overdue", "never", "due_soon")],
        "latest_lab_report": labs[0] if labs else None,
        "questions": profile.get("doctor_questions", []),
        "rules_reviewed": RULES_REVIEWED,
        "note": "Prepared by the Hymn app from what the person logged, synced or uploaded. Each value shows its "
                "date and source (you / watch / lab / doctor). It is not a diagnosis.",
    }


def as_text(s: dict) -> str:
    out = [f"Health summary — {s['name']}".strip(" —"), f"Prepared {s['prepared_on']} with the Hymn app", ""]
    who = ", ".join(x for x in (f"{s['age']} years" if s["age"] is not None else "", s["sex"] or "") if x)
    if who:
        out.append(f"About: {who}")
    for title, key in (("Conditions", "conditions"), ("Medicines", "medicines"), ("Family history", "family_history")):
        out.append(f"{title}: {', '.join(v.replace('_', ' ') for v in s[key]) or 'none recorded'}")
    out.append(f"Smoking: {s['smoking'] or 'not recorded'}"
               + (f" · Alcohol: {s['alcohol_drinks_per_week']} drinks/week"
                  if s["alcohol_drinks_per_week"] is not None else ""))
    if s["pregnant_or_breastfeeding"]:
        out.append("Pregnant or breastfeeding")
    out += ["", "Latest readings (value · date · source):"]
    out += [f"- {r['label']}: {r['value']} {r['unit']} · {r['date']} · {r['source']}"
            + (f" ({r['based_on']})" if r["based_on"] != "latest" else "") for r in s["readings"]] or ["- none"]
    if s["changes_90_days"]:
        out += ["", "Changes over the last 90 days (first 30 days vs latest):"]
        out += [f"- {c['label']}: {c['before']} → {c['after']} {c['unit']}" for c in s["changes_90_days"]]
    if s["symptoms_90_days"]:
        out += ["", "Symptoms logged (last 90 days):"] + [f"- {x['date']}: {x['what']}" for x in s["symptoms_90_days"]]
    if s["habits"]:
        out += ["", "Working on:"] + [f"- {h['habit']} ({h['goal'].replace('_', ' ')}, since {h['since']})"
                                      for h in s["habits"]]
    if s["checkups_due"]:
        out += ["", "Check-ups due:"] + [f"- {c['label']}" + (f" (last {c['last_done']})" if c["last_done"] else "")
                                         for c in s["checkups_due"]]
    lab = s["latest_lab_report"]
    if lab:
        out += ["", f"Latest lab report ({lab['report_date']}{', ' + lab['lab'] if lab.get('lab') else ''}), as printed:"]
        out += [f"- {r['test_name']}: {r['value']} {r['unit']}".rstrip()
                + (f" (ref {r['reference_range']})" if r.get("reference_range") else "")
                + (f" {r['flag']}" if r.get("flag") else "") for r in lab["results"]]
    if s["questions"]:
        out += ["", "My questions:"] + [f"- {q}" for q in s["questions"]]
    out += ["", s["note"]]
    return "\n".join(out)


@reports_router.get("/doctor-summary")
async def doctor_summary(format: str = "json", include_private: bool = False,
                         current_user: dict = Depends(get_current_user),
        for_: Optional[str] = Query(default=None, alias="for")):
    s = await summary(get_db(), await person(get_db(), current_user, for_), include_private)
    return PlainTextResponse(as_text(s)) if format == "text" else s
