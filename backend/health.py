"""Health: healthspan, not just lifespan. Live longer, think clearly, remain
independent.

Six domains (inspired by the breadth of Sushruta's definition of swasthya;
measured with modern evidence):

* cardiovascular  — blood pressure, resting heart rate, waist-to-height
* metabolic       — fasting glucose, HbA1c, lipids, weight / BMI, waist
* cognitive       — known modifiable risks (hearing, isolation, learning,
                    sleep, blood pressure, smoking); no brain-game scores
* physical        — activity minutes, steps, strength days, simple home
                    tests (chair stands, one-leg balance)
* organ_recovery  — kidney (eGFR, urine albumin), sleep
* mind_gut_senses — mood, stress, energy, digestion, bowel regularity,
                    screen time, contentment, social time

Rules (all **draft, pending a doctor's review** — ``RULES_REVIEWED`` stays
False until then):

* every number keeps its source (you / watch / lab / doctor / AI) and date;
  missing is shown as missing, stale as outdated — never as normal;
* thresholds follow Indian / South Asian cut-offs where they differ (waist,
  BMI);
* each domain is rated 0–4 from its worst indicator; there is **no overall
  score**, so a strong domain can never hide a red one;
* red flags (symptoms, very high blood pressure…) come first, telling the
  person to get help now;
* this supports decisions; it never diagnoses, never says to stop
  medicines, never recommends supplements or tests without a reason.

Health data is the most sensitive data a person has: nothing is stored
until they consent, and they can delete all of it.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date as date_type, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from deps import get_current_user, get_db

health_router = APIRouter(prefix="/health", tags=["health"])

RULES_REVIEWED = False  # flips once a doctor signs off the thresholds and red flags
SOURCES = ("you", "watch", "lab", "doctor", "ai")

# metric → (label, unit, plausible min, plausible max, domain, how long it stays current in days)
METRICS: Dict[str, tuple] = {
    "bp_systolic": ("Blood pressure (top)", "mmHg", 60, 260, "cardiovascular", 90),
    "bp_diastolic": ("Blood pressure (bottom)", "mmHg", 30, 160, "cardiovascular", 90),
    "resting_hr": ("Resting heart rate", "bpm", 25, 200, "cardiovascular", 30),
    "waist_cm": ("Waist", "cm", 40, 200, "metabolic", 90),
    "weight_kg": ("Weight", "kg", 20, 300, "metabolic", 30),
    "height_cm": ("Height", "cm", 100, 230, None, 3650),
    "fasting_glucose": ("Fasting glucose", "mg/dL", 30, 600, "metabolic", 450),
    "hba1c": ("HbA1c", "%", 3, 18, "metabolic", 450),
    "ldl": ("LDL cholesterol", "mg/dL", 10, 400, "metabolic", 450),
    "hdl": ("HDL cholesterol", "mg/dL", 5, 150, "metabolic", 450),
    "triglycerides": ("Triglycerides", "mg/dL", 20, 3000, "metabolic", 450),
    "egfr": ("Kidney function (eGFR)", "mL/min/1.73m²", 1, 200, "organ_recovery", 450),
    "uacr": ("Urine albumin (UACR)", "mg/g", 0, 5000, "organ_recovery", 450),
    "sleep_hours": ("Sleep", "hours", 0, 16, "organ_recovery", 14),
    "steps": ("Steps", "steps/day", 0, 80000, "physical", 14),
    "active_minutes": ("Moderate activity", "minutes/day", 0, 600, "physical", 14),
    "strength_session": ("Strength training", "sessions", 0, 3, "physical", 14),
    "chair_stands_30s": ("Chair stands in 30 s", "count", 0, 60, "physical", 365),
    "one_leg_stand_s": ("Standing on one leg", "seconds", 0, 120, "physical", 365),
    "vo2max": ("VO₂max (watch estimate)", "mL/kg/min", 10, 90, "cardiovascular", 180),
    "mood": ("Mood", "1–5", 1, 5, "mind_gut_senses", 14),
    "stress": ("Stress", "1–5", 1, 5, "mind_gut_senses", 14),
    "energy": ("Energy", "1–5", 1, 5, "mind_gut_senses", 14),
    "digestion": ("Digestive comfort", "1–5", 1, 5, "mind_gut_senses", 14),
    "bowel": ("Bowel movement", "0 none · 1 hard · 2 easy", 0, 2, "mind_gut_senses", 14),
    "screen_hours": ("Screen time (leisure)", "hours", 0, 20, "mind_gut_senses", 14),
    "contentment": ("Contentment", "1–5", 1, 5, "mind_gut_senses", 30),
    "social_hours": ("Time with people you care about", "hours/week", 0, 100, "cognitive", 30),
    "learning_hours": ("Learning something new", "hours/week", 0, 100, "cognitive", 30),
}

DOMAINS = [
    ("cardiovascular", "Heart & circulation", "Sama-dosha (balance)"),
    ("metabolic", "Metabolism", "Sama-agni (digestion & metabolism)"),
    ("physical", "Strength & independence", "Sama-dhatu (tissues)"),
    ("organ_recovery", "Organs & recovery", "Mala-kriya (elimination) & rest"),
    ("cognitive", "Mind & memory", "Prasanna manas (clear mind)"),
    ("mind_gut_senses", "Mood, gut & senses", "Prasanna atma & indriya (contented self, clear senses)"),
]

RED_FLAG_SYMPTOMS = {
    "chest_pain": ("Chest pain or pressure", "emergency"),
    "stroke_signs": ("Face drooping, arm weakness or trouble speaking", "emergency"),
    "breathless_at_rest": ("Breathless while resting", "emergency"),
    "fainting": ("Fainting", "doctor_today"),
    "blood_in_stool": ("Blood in stool or black stools", "doctor_soon"),
    "unexplained_weight_loss": ("Losing weight without trying", "doctor_soon"),
    "severe_sudden_headache": ("Sudden, very severe headache", "emergency"),
    "self_harm_thoughts": ("Thoughts of harming yourself", "emergency_mental"),
}
HELP = {
    "emergency": "Call 112 or go to the nearest emergency department now.",
    "emergency_mental": "You don't have to face this alone. Call 112, or Tele-MANAS on 14416 (free, 24×7).",
    "doctor_today": "Please see a doctor today.",
    "doctor_soon": "Please see a doctor in the next few days.",
}

CONDITIONS = ("diabetes", "high_blood_pressure", "heart_disease", "kidney_disease", "thyroid", "asthma_copd",
              "depression_anxiety", "cancer", "other")
FAMILY_HISTORY = ("diabetes", "heart_disease_before_60", "high_blood_pressure", "stroke", "cancer", "dementia")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _d(v: Any) -> Optional[Decimal]:
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Rules (pure)
# ---------------------------------------------------------------------------

def age_on(dob: Optional[str], today: date_type) -> Optional[int]:
    try:
        b = date_type.fromisoformat(dob)
    except (TypeError, ValueError):
        return None
    return today.year - b.year - ((today.month, today.day) < (b.month, b.day))


def screening(profile: dict, latest: Dict[str, dict], today: date_type) -> dict:
    """Who must not get a weight-loss plan from an app (see a doctor instead)."""
    reasons = []
    age = age_on(profile.get("date_of_birth"), today)
    if age is not None and age < 18:
        reasons.append("Under 18")
    if profile.get("pregnant_or_breastfeeding"):
        reasons.append("Pregnant or breastfeeding")
    if profile.get("eating_disorder_history"):
        reasons.append("A history of eating difficulties")
    if profile.get("on_glucose_lowering_medicine"):
        reasons.append("Medicine that lowers blood sugar")
    bmi_ = bmi(latest, profile)
    if bmi_ is not None and bmi_ < Decimal("18.5"):
        reasons.append("Underweight")
    return {"weight_loss_ok": not reasons, "see_doctor_first_because": reasons}


def bmi(latest: Dict[str, dict], profile: dict) -> Optional[Decimal]:
    w = latest.get("weight_kg")
    h = latest.get("height_cm") or ({"value": profile["height_cm"]} if profile.get("height_cm") else None)
    if not w or not h:
        return None
    m = Decimal(str(h["value"])) / 100
    return (Decimal(str(w["value"])) / (m * m)).quantize(Decimal("0.1"))


def rate(metric: str, value: Decimal, profile: dict, age: Optional[int]) -> tuple:
    """(status, why) for one value: green / amber / red, or 'recorded' when
    there's no rule for this person yet. DRAFT thresholds."""
    male = profile.get("sex") == "male"
    if metric == "bp_systolic":
        return ("green", "Under 120") if value < 120 else ("amber", "120–139: raised") if value < 140 \
            else ("red", "140 or more: high")
    if metric == "bp_diastolic":
        return ("green", "Under 80") if value < 80 else ("amber", "80–89: raised") if value < 90 \
            else ("red", "90 or more: high")
    if metric == "resting_hr":
        if value > 100:
            return "red", "Over 100 at rest"
        return ("green", "50–80") if 50 <= value <= 80 else ("amber", "Outside 50–80")
    if metric == "fasting_glucose":
        return ("green", "Under 100") if value < 100 else ("amber", "100–125: prediabetes range") if value < 126 \
            else ("red", "126 or more: diabetes range")
    if metric == "hba1c":
        return ("green", "Under 5.7%") if value < Decimal("5.7") else \
            ("amber", "5.7–6.4%: prediabetes range") if value < Decimal("6.5") else ("red", "6.5% or more: diabetes range")
    if metric == "ldl":
        return ("green", "Under 100") if value < 100 else ("amber", "100–159") if value < 160 else ("red", "160 or more")
    if metric == "hdl":
        low = 40 if male else 50
        return ("green", f"{low} or more") if value >= low else ("amber", f"Under {low}")
    if metric == "triglycerides":
        return ("green", "Under 150") if value < 150 else ("amber", "150–499") if value < 500 else ("red", "500 or more")
    if metric == "waist_cm":
        limit = 90 if male else 80  # South Asian cut-offs
        return ("green", f"Under {limit} cm") if value < limit else ("amber", f"{limit} cm or more")
    if metric == "egfr":
        return ("green", "90 or more") if value >= 90 else ("amber", "60–89") if value >= 60 else ("red", "Under 60")
    if metric == "uacr":
        return ("green", "Under 30") if value < 30 else ("amber", "30–300") if value <= 300 else ("red", "Over 300")
    if metric == "sleep_hours":
        return ("green", "7–9 hours") if 7 <= value <= 9 else ("amber", "6–7 hours") if 6 <= value < 7 \
            else ("red", "Under 6 hours") if value < 6 else ("amber", "Over 9 hours")
    if metric == "steps":
        return ("green", "7,000 or more") if value >= 7000 else ("amber", "4,000–6,999") if value >= 4000 \
            else ("red", "Under 4,000")
    if metric == "active_minutes":  # a day's average; 150/week ≈ 21–22/day
        return ("green", "About 150 min a week or more") if value >= Decimal("21.4") else \
            ("amber", "Under 150 min a week")
    if metric in ("stress",):
        return ("green", "Mostly calm") if value < Decimal("3.5") else ("amber", "Often stressed")
    if metric in ("mood", "contentment", "energy", "digestion"):
        return ("green", "Mostly good") if value >= 3 else ("amber", "Often low")
    if metric == "bowel":
        return ("green", "Regular") if value >= Decimal("1.5") else ("amber", "Often hard or missed")
    if metric == "screen_hours":
        return ("green", "Under 3 hours") if value < 3 else ("amber", "3 hours or more")
    if metric == "one_leg_stand_s" and age is not None and age >= 60:
        return ("green", "10 seconds or more") if value >= 10 else ("amber", "Under 10 seconds")
    if metric == "chair_stands_30s" and age is not None and age >= 60:
        return ("green", "12 or more") if value >= 12 else ("amber", "Under 12")
    return "recorded", "Recorded (no rating for your age yet)"


DAILY_AVERAGED = {"sleep_hours", "steps", "active_minutes", "mood", "stress", "energy", "digestion", "bowel",
                  "screen_hours"}


def summarise(rows: List[dict], today: date_type) -> Dict[str, dict]:
    """Latest value per metric; daily signals use their 7-day average."""
    by_metric: Dict[str, List[dict]] = defaultdict(list)
    for r in rows:
        by_metric[r["metric"]].append(r)
    out = {}
    week_ago = (today - timedelta(days=6)).isoformat()
    for metric, items in by_metric.items():
        items.sort(key=lambda r: r["taken_on"])
        last = items[-1]
        if metric in DAILY_AVERAGED:
            recent = [Decimal(str(r["value"])) for r in items if r["taken_on"] >= week_ago]
            if recent:
                out[metric] = {"value": sum(recent) / len(recent), "taken_on": last["taken_on"],
                               "source": last["source"], "based_on": f"{len(recent)}-day average"}
                continue
        out[metric] = {"value": Decimal(str(last["value"])), "taken_on": last["taken_on"], "source": last["source"],
                       "based_on": "latest"}
    return out


def dashboard(profile: dict, rows: List[dict], today: date_type) -> dict:
    latest = summarise(rows, today)
    age = age_on(profile.get("date_of_birth"), today)
    domains, risks, missing = [], [], []
    for key, label, lens in DOMAINS:
        indicators = []
        for metric, (mlabel, unit, _lo, _hi, dom, fresh_days) in METRICS.items():
            if dom != key:
                continue
            got = latest.get(metric)
            if got is None:
                indicators.append({"metric": metric, "label": mlabel, "status": "missing"})
                continue
            stale = (today - date_type.fromisoformat(got["taken_on"][:10])).days > fresh_days
            status, why = rate(metric, got["value"], profile, age)
            if stale:
                status, why = "outdated", f"Last measured {got['taken_on'][:10]}"
            indicators.append({"metric": metric, "label": mlabel, "unit": unit,
                               "value": format(got["value"].quantize(Decimal("0.1")), "f"),
                               "taken_on": got["taken_on"][:10], "source": got["source"],
                               "based_on": got["based_on"], "status": status, "why": why})
        # Lifestyle facts from the profile that matter as much as numbers.
        if key == "cardiovascular" and profile.get("smoking") == "current":
            indicators.append({"metric": "smoking", "label": "Smoking", "status": "red",
                               "why": "Smoking now", "source": "you"})
        if key == "metabolic":
            b = bmi(latest, profile)
            if b is not None:
                s = ("green", "18.5–22.9") if Decimal("18.5") <= b < 23 else ("amber", "23–27.4 (Asian cut-offs)") \
                    if Decimal("23") <= b < Decimal("27.5") else ("red", "27.5 or more") if b >= Decimal("27.5") \
                    else ("amber", "Under 18.5")
                indicators.append({"metric": "bmi", "label": "BMI", "value": format(b, "f"), "status": s[0],
                                   "why": s[1], "source": "calculated"})
        if key == "cognitive" and profile.get("hearing_difficulty"):
            indicators.append({"metric": "hearing", "label": "Hearing", "status": "amber",
                               "why": "Hearing difficulty: worth a check (protects memory too)", "source": "you"})
        rated = [i for i in indicators if i["status"] in ("green", "amber", "red")]
        if not rated:
            score = None
        elif any(i["status"] == "red" for i in rated):
            score = 1
        elif any(i["status"] == "amber" for i in rated):
            score = 2
        elif any(i["status"] in ("missing", "outdated") for i in indicators):
            score = 3
        else:
            score = 4
        colour = {None: "missing", 1: "red", 2: "amber", 3: "green", 4: "green"}[score]
        domains.append({"domain": key, "label": label, "lens": lens, "rating": score, "colour": colour,
                        "indicators": indicators})
        risks += [{"domain": label, **i} for i in indicators if i["status"] == "red"]
        missing += [{"domain": label, "metric": i["metric"], "label": i["label"]}
                    for i in indicators if i["status"] in ("missing", "outdated")]
    flags = []
    s, dia = latest.get("bp_systolic"), latest.get("bp_diastolic")
    if (s and s["value"] >= 180) or (dia and dia["value"] >= 120):
        flags.append({"what": "Very high blood pressure", "level": "doctor_today", "action": HELP["doctor_today"]})
    return {"rules_reviewed": RULES_REVIEWED, "domains": domains, "risks": risks, "missing": missing,
            "red_flags": flags, "screening": screening(profile, latest, today), "age": age,
            "note": "This supports your decisions with your doctor; it doesn't diagnose anything."}


def symptom_flags(symptoms: List[str]) -> List[dict]:
    out = []
    for s in symptoms:
        if s in RED_FLAG_SYMPTOMS:
            what, level = RED_FLAG_SYMPTOMS[s]
            out.append({"what": what, "level": level, "action": HELP[level]})
    order = {"emergency": 0, "emergency_mental": 0, "doctor_today": 1, "doctor_soon": 2}
    return sorted(out, key=lambda f: order[f["level"]])


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

class Profile(BaseModel):
    consent: bool                                           # explicit consent to store health data
    date_of_birth: Optional[str] = None
    sex: Optional[Literal["male", "female", "other"]] = None
    height_cm: Optional[float] = Field(default=None, ge=100, le=230)
    conditions: List[str] = Field(default_factory=list)
    medicines: List[str] = Field(default_factory=list)      # names only; Hymn never advises changing them
    family_history: List[str] = Field(default_factory=list)
    smoking: Literal["never", "former", "current"] = "never"
    alcohol_drinks_per_week: Optional[int] = Field(default=None, ge=0, le=200)
    pregnant_or_breastfeeding: bool = False
    eating_disorder_history: bool = False
    on_glucose_lowering_medicine: bool = False
    hearing_difficulty: bool = False


class Measurement(BaseModel):
    metric: str
    value: float
    taken_on: str                                           # YYYY-MM-DD (or full timestamp)
    source: Literal["you", "watch", "lab", "doctor", "ai"] = "you"
    note: str = ""


class Daily(BaseModel):
    date: str
    energy: Optional[int] = Field(default=None, ge=1, le=5)
    mood: Optional[int] = Field(default=None, ge=1, le=5)
    stress: Optional[int] = Field(default=None, ge=1, le=5)
    digestion: Optional[int] = Field(default=None, ge=1, le=5)
    bowel: Optional[int] = Field(default=None, ge=0, le=2)
    sleep_hours: Optional[float] = Field(default=None, ge=0, le=16)
    steps: Optional[int] = Field(default=None, ge=0, le=80000)
    active_minutes: Optional[int] = Field(default=None, ge=0, le=600)
    symptoms: List[str] = Field(default_factory=list)


async def _profile(db, user_id: str) -> dict:
    p = await db.health_profiles.find_one({"user_id": user_id}, {"_id": 0})
    if not p or not p.get("consent"):
        raise HTTPException(status_code=403, detail="Please agree to store your health data first.")
    return p


def _date(v: str) -> str:
    try:
        return date_type.fromisoformat(v[:10]).isoformat()
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Dates must be YYYY-MM-DD.")


@health_router.put("/profile")
async def put_profile(body: Profile, current_user: dict = Depends(get_current_user)):
    if not body.consent:
        raise HTTPException(status_code=400, detail="Hymn stores health data only with your consent.")
    if body.date_of_birth:
        _date(body.date_of_birth)
    bad = [c for c in body.conditions if c not in CONDITIONS] + \
        [f for f in body.family_history if f not in FAMILY_HISTORY]
    if bad:
        raise HTTPException(status_code=400, detail=f"Unknown: {', '.join(bad)}")
    doc = {**body.model_dump(), "user_id": current_user["id"], "consented_at": _now(), "updated_at": _now()}
    await get_db().health_profiles.replace_one({"user_id": current_user["id"]}, doc, upsert=True)
    doc.pop("user_id")
    return doc


@health_router.get("/profile")
async def get_profile(current_user: dict = Depends(get_current_user)):
    p = await get_db().health_profiles.find_one({"user_id": current_user["id"]}, {"_id": 0, "user_id": 0})
    return p or {"consent": False}


async def _store(db, user_id: str, items: List[dict]) -> List[dict]:
    rows = []
    for m in items:
        spec = METRICS.get(m["metric"])
        if not spec:
            raise HTTPException(status_code=400, detail=f"Unknown measurement: {m['metric']}")
        v = _d(m["value"])
        if v is None or not (spec[2] <= v <= spec[3]):
            raise HTTPException(status_code=400, detail=f"{spec[0]} of {m['value']} {spec[1]} doesn't look right.")
        rows.append({"id": str(uuid.uuid4()), "user_id": user_id, "metric": m["metric"], "value": float(v),
                     "unit": spec[1], "taken_on": _date(m["taken_on"]), "source": m.get("source") or "you",
                     "note": m.get("note", ""), "created_at": _now()})
    if rows:
        await db.health_measurements.insert_many([dict(r) for r in rows])
    return rows


@health_router.post("/measurements", status_code=201)
async def add_measurements(body: List[Measurement], current_user: dict = Depends(get_current_user)):
    db = get_db()
    await _profile(db, current_user["id"])
    rows = await _store(db, current_user["id"], [m.model_dump() for m in body])
    return {"saved": len(rows)}


@health_router.get("/measurements")
async def list_measurements(metric: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    q = {"user_id": current_user["id"], **({"metric": metric} if metric else {})}
    return await get_db().health_measurements.find(q, {"_id": 0, "user_id": 0}).sort("taken_on", -1) \
        .to_list(length=1000)


@health_router.post("/daily")
async def daily(body: Daily, current_user: dict = Depends(get_current_user)):
    """The 30-second daily log. Returns any red flags first."""
    db = get_db()
    await _profile(db, current_user["id"])
    day = _date(body.date)
    bad = [s for s in body.symptoms if s not in RED_FLAG_SYMPTOMS]
    if bad:
        raise HTTPException(status_code=400, detail=f"Unknown symptoms: {', '.join(bad)}")
    values = body.model_dump(exclude={"date", "symptoms"}, exclude_none=True)
    # One entry per metric per day: today's tap replaces an earlier one.
    await db.health_measurements.delete_many({"user_id": current_user["id"], "taken_on": day, "source": "you",
                                              "metric": {"$in": list(values)}})
    await _store(db, current_user["id"], [{"metric": k, "value": v, "taken_on": day, "source": "you"}
                                          for k, v in values.items()])
    return {"saved": len(values), "red_flags": symptom_flags(body.symptoms)}


@health_router.get("/dashboard")
async def get_dashboard(current_user: dict = Depends(get_current_user)):
    db = get_db()
    profile = await _profile(db, current_user["id"])
    rows = await db.health_measurements.find({"user_id": current_user["id"]}, {"_id": 0}).to_list(length=None)
    return dashboard(profile, rows, date_type.today())


@health_router.get("/options")
async def options():
    """Lists for the app's pickers."""
    return {"metrics": {k: {"label": v[0], "unit": v[1], "domain": v[4]} for k, v in METRICS.items()},
            "conditions": CONDITIONS, "family_history": FAMILY_HISTORY,
            "symptoms": {k: v[0] for k, v in RED_FLAG_SYMPTOMS.items()},
            "domains": [{"key": k, "label": l, "lens": s} for k, l, s in DOMAINS]}


@health_router.delete("/all")
async def delete_everything(current_user: dict = Depends(get_current_user)):
    """Delete every piece of health data Hymn holds for this person."""
    db = get_db()
    await db.health_measurements.delete_many({"user_id": current_user["id"]})
    await db.health_profiles.delete_one({"user_id": current_user["id"]})
    return {"detail": "All your health data has been deleted."}


async def ensure_health_indexes(db) -> None:
    await db.health_profiles.create_index("user_id", unique=True)
    await db.health_measurements.create_index([("user_id", 1), ("metric", 1), ("taken_on", 1)])
