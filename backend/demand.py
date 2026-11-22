"""What people are planning, counted anonymously, for local sellers (through Pamphlet).

Every plan gets an ``intent``: what it is (property, car, wedding…), its form
(3 BHK, SUV…), budget, where (city, area, pincode) and when (the plan's target
date). The planner fills it while talking; ``classify`` fills what it can from
the title and template for the rest; the person can correct it.

Two audiences:
- **The owner (admin page)**: counts across all plans. Groups under 5 show as
  "fewer than 5".
- **Sellers (Pamphlet)**: only people who switched on "Help local sellers
  understand what people are planning" (off by default), only groups of at
  least ``demand_min_count`` (20), never names, contact details, notes or
  single plans, never health or family-planning plans, and only while the owner's
  ``demand_sharing_on`` switch is on (off until a lawyer has reviewed it). Every
  pull is logged.

Individual leads (a person asking to be contacted by a seller) are a separate,
later feature with its own per-plan consent.
"""
from __future__ import annotations

import hmac
import os
import re
import statistics
from collections import Counter
from datetime import date as date_type, datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

import display
import metering
from admin import require_admin
from deps import get_current_user, get_db

demand_router = APIRouter(prefix="/demand", tags=["demand"])
demand_admin_router = APIRouter(prefix="/admin/demand", tags=["admin"])
partner_router = APIRouter(prefix="/partner", tags=["partner"])

CONSENT_VERSION = "2026-11-22"
CONSENT_TEXT = ("Help local sellers understand what people are planning. Hymn counts your plans anonymously — "
                "what it is, its size, budget range, area and when — in reports to sellers near you, only in "
                "groups of many people. Never your name, number or anything else. You can turn this off any time.")

CATEGORIES = {
    "property": {"label": "a home", "verb": "buy", "forms": ["1 BHK", "2 BHK", "3 BHK", "4 BHK+", "Villa", "Plot",
                                                          "Commercial"]},
    "car": {"label": "a car", "verb": "buy", "forms": ["Hatchback", "Sedan", "SUV", "Electric", "Used"]},
    "two_wheeler": {"label": "a two-wheeler", "verb": "buy", "forms": ["Scooter", "Motorcycle", "Electric"]},
    "wedding": {"label": "a wedding", "verb": "plan", "forms": []},
    "education": {"label": "a course", "verb": "join", "forms": []},
    "travel": {"label": "a trip", "verb": "take", "forms": ["Domestic", "International"]},
    "gadget": {"label": "a gadget", "verb": "buy", "forms": ["Phone", "Laptop", "TV", "Appliance"]},
    "renovation": {"label": "a home renovation", "verb": "do", "forms": ["Interiors", "Kitchen", "Repairs"]},
    "business": {"label": "a business", "verb": "start", "forms": []},
    "health": {"label": "a health goal", "verb": "reach", "forms": []},
    "child": {"label": "a child", "verb": "plan for", "forms": []},
    "other": {"label": "something else", "verb": "do", "forms": []},
}
NEVER_SHARED = {"health", "child", "other"}       # sensitive or meaningless to sellers
ADMIN_MIN = 5

_RULES = [
    ("property", r"\b(house|home|flat|apartment|villa|plot|property|bhk|land)\b"),
    ("car", r"\b(car|suv|sedan|hatchback)\b"),
    ("two_wheeler", r"\b(bike|scooter|motorcycle|two.?wheeler|activa|bullet)\b"),
    ("wedding", r"\b(wedding|marriage|shaadi)\b"),
    ("education", r"\b(mba|degree|course|college|admission|masters|school fees|cfa|ca final|coaching)\b"),
    ("travel", r"\b(trip|travel|vacation|holiday|tour|europe|goa)\b"),
    ("gadget", r"\b(iphone|phone|laptop|macbook|tv|fridge|washing machine|camera)\b"),
    ("renovation", r"\b(renovat\w*|interior\w*|kitchen|repaint|repair)\b"),
    ("business", r"\b(business|startup|shop|cafe|restaurant|franchise)\b"),
    ("child", r"\b(baby|child|pregnan\w*|kid)\b"),
    ("health", r"\b(weight|fitness|marathon|steps|sleep|diabetes|bp)\b"),
]
_FORM_RULES = {
    "property": [("1 BHK", r"\b1\s?bhk\b"), ("2 BHK", r"\b2\s?bhk\b"), ("3 BHK", r"\b3\s?bhk\b"),
                 ("4 BHK+", r"\b[4-9]\s?bhk\b"), ("Villa", r"\bvilla\b"), ("Plot", r"\b(plot|land)\b")],
    "car": [("SUV", r"\bsuv\b"), ("Sedan", r"\bsedan\b"), ("Hatchback", r"\bhatchback\b"),
            ("Electric", r"\b(ev|electric)\b"), ("Used", r"\b(used|second.?hand|pre.?owned)\b")],
    "two_wheeler": [("Electric", r"\b(ev|electric)\b"), ("Scooter", r"\bscooter\b"), ("Motorcycle", r"\b(motorcycle|bike)\b")],
}
_TEMPLATE_CATEGORY = {"house": "property", "wedding": "wedding", "first_child": "child"}
_AMOUNT = re.compile(r"(?:₹|rs\.?|inr)?\s*(\d+(?:\.\d+)?)\s*(cr|crore|crores|l|lakh|lakhs|lac|k)\b", re.I)


def _amount_in(text: str) -> Optional[int]:
    m = _AMOUNT.search(text or "")
    if not m:
        return None
    n, unit = float(m.group(1)), m.group(2).lower()
    mult = 10_000_000 if unit.startswith("cr") else 1_000 if unit == "k" else 100_000
    return int(n * mult)


def _title_case(s: Optional[str]) -> str:
    return " ".join(w.capitalize() if w.islower() else w for w in (s or "").strip().split())[:60]


def classify(plan: dict) -> dict:
    """Best guess from the plan itself (used when the planner or the person gave nothing)."""
    text = f"{plan.get('title', '')} {plan.get('for_what', '')}".lower()
    category = _TEMPLATE_CATEGORY.get(plan.get("template") or "")
    if not category:
        category = next((c for c, rx in _RULES if re.search(rx, text)), "other")
    form = next((f for f, rx in _FORM_RULES.get(category, []) if re.search(rx, text)), "")
    return {"category": category, "form": form, "budget_inr": _amount_in(text), "source": "guess"}


def clean_intent(plan: dict, given: Optional[dict]) -> dict:
    """The intent to store: what the planner / person said, filled in from the guess."""
    guess = classify(plan)
    g = given or {}
    category = g.get("category") if g.get("category") in CATEGORIES else guess["category"]
    form = (g.get("form") or "").strip()[:30] or (guess["form"] if category == guess["category"] else "")
    try:
        budget = int(float(g["budget_inr"])) if g.get("budget_inr") not in (None, "") else guess["budget_inr"]
    except (TypeError, ValueError):
        budget = guess["budget_inr"]
    pin = re.sub(r"\D", "", str(g.get("pincode") or ""))
    return {"category": category, "form": form, "budget_inr": budget if budget and budget > 0 else None,
            "city": _title_case(g.get("city")), "area": _title_case(g.get("area")),
            "pincode": pin if len(pin) == 6 else "", "source": "planner" if given else "guess"}


def intent_of(plan: dict) -> dict:
    return plan.get("intent") or clean_intent(plan, None)


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------

def _days_until(target: Optional[str], today: date_type) -> Optional[int]:
    try:
        return (date_type.fromisoformat(str(target)[:10]) - today).days
    except (TypeError, ValueError):
        return None


BUDGET_BANDS = [(0, 500_000), (500_000, 1_000_000), (1_000_000, 2_500_000), (2_500_000, 5_000_000),
                (5_000_000, 10_000_000), (10_000_000, 20_000_000), (20_000_000, None)]


def _band(n: int) -> str:
    for lo, hi in BUDGET_BANDS:
        if n >= lo and (hi is None or n < hi):
            return f"{display.money(lo)}–{display.money(hi)}" if hi else f"{display.money(lo)}+"
    return ""


async def _rows(db, today: date_type, shareable_only: bool) -> List[dict]:
    consent = None
    if shareable_only:
        consent = {u["id"] async for u in db.users.find({"demand_sharing.on": True}, {"_id": 0, "id": 1})}
    out = []
    async for p in db.life_plans.find({"status": "active"}, {"_id": 0}):
        if consent is not None and p["user_id"] not in consent:
            continue
        it = intent_of(p)
        if shareable_only and it["category"] in NEVER_SHARED:
            continue
        days = _days_until(p.get("target_date"), today)
        if days is None or days < 0:
            continue
        out.append({**it, "user_id": p["user_id"], "days": days})
    return out


def _match(rows: List[dict], category: Optional[str], city: Optional[str], area: Optional[str],
           form: Optional[str], within_days: Optional[int]) -> List[dict]:
    def eq(a, b):
        return not b or (a or "").lower() == b.strip().lower()
    return [r for r in rows if eq(r["category"], category) and eq(r["city"], city) and eq(r["area"], area)
            and eq(r["form"], form) and (within_days is None or r["days"] <= within_days)]


def summarise(rows: List[dict], min_count: int, within_days: Optional[int] = None) -> dict:
    """One group: how many people (each counted once), when, budget, forms, areas. Small groups are hidden."""
    people = {r["user_id"] for r in rows}
    n = len(people)
    if n < min_count:
        return {"people": None, "hidden": True, "note": f"fewer than {min_count}"}
    budgets = [r["budget_inr"] for r in rows if r.get("budget_inr")]
    forms = Counter(r["form"] for r in rows if r.get("form"))
    areas = Counter((r["area"] or r["city"]) for r in rows if r.get("area") or r.get("city"))
    when = Counter("within 100 days" if r["days"] <= 100 else "within 6 months" if r["days"] <= 183
                   else "within a year" if r["days"] <= 366 else "later" for r in rows)
    out = {"people": n, "hidden": False,
           "when": {k: when.get(k, 0) for k in ("within 100 days", "within 6 months", "within a year", "later")},
           "budget": None, "forms": [], "areas": []}
    if len(budgets) >= min(3, min_count):
        avg = sum(budgets) / len(budgets)
        out["budget"] = {"average_inr": int(avg), "average": display.money(avg), "median": display.money(statistics.median(budgets)),
                         "most_common_range": Counter(_band(b) for b in budgets).most_common(1)[0][0],
                         "with_budget": len(budgets)}
    total_forms = sum(forms.values())
    out["forms"] = [{"form": f, "share": round(100 * c / total_forms)} for f, c in forms.most_common(4)]
    # Areas only when that area alone is a big enough group.
    out["areas"] = [{"area": a, "people": c} for a, c in areas.most_common(10) if c >= min_count]
    return out


def report_text(category: str, where: str, within_days: Optional[int], s: dict) -> str:
    """'120 people would like to buy a home in Whitefield, Bengaluru within 100 days. Average budget ₹1 Cr. …'"""
    if s.get("hidden"):
        return ""
    c = CATEGORIES.get(category, CATEGORIES["other"])
    when = f" within {within_days} days" if within_days else ""
    place = f" in {where}" if where else ""
    lines = [f"{s['people']} people would like to {c['verb']} {c['label']}{place}{when}."]
    if s.get("budget"):
        lines.append(f"Average budget: {s['budget']['average']}; most are in the {s['budget']['most_common_range']} range.")
    if s.get("forms"):
        top = s["forms"][0]
        lines.append(f"Most want {top['form']} ({top['share']}%).")
        focus = top["form"] + (f" around {s['budget']['most_common_range']}" if s.get("budget") else "")
        lines.append(f"Focus on {focus} to get the most from your time and effort.")
    return " ".join(lines)


# ---------------------------------------------------------------------------
# The person's side: consent and correcting a plan's details
# ---------------------------------------------------------------------------

class Consent(BaseModel):
    on: bool


class IntentIn(BaseModel):
    category: Optional[str] = None
    form: Optional[str] = Field(default=None, max_length=30)
    budget_inr: Optional[float] = Field(default=None, ge=0, le=10_000_000_000)
    city: Optional[str] = Field(default=None, max_length=60)
    area: Optional[str] = Field(default=None, max_length=60)
    pincode: Optional[str] = Field(default=None, max_length=10)


@demand_router.get("/consent")
async def get_consent(current_user: dict = Depends(get_current_user)):
    c = current_user.get("demand_sharing") or {}
    return {"on": bool(c.get("on")), "since": c.get("at"), "text": CONSENT_TEXT, "version": CONSENT_VERSION}


@demand_router.put("/consent")
async def set_consent(body: Consent, current_user: dict = Depends(get_current_user)):
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()
    await db.users.update_one({"id": current_user["id"]}, {"$set": {"demand_sharing": {
        "on": body.on, "at": now, "version": CONSENT_VERSION}}})
    await db.consent_log.insert_one({"user_id": current_user["id"], "kind": "demand_sharing", "on": body.on,
                                     "consent_text_version": CONSENT_VERSION, "created_at": now})
    return {"on": body.on, "since": now, "text": CONSENT_TEXT, "version": CONSENT_VERSION}


@demand_router.get("/options")
async def options():
    return {"categories": [{"key": k, "label": v["label"], "forms": v["forms"]} for k, v in CATEGORIES.items()]}


@demand_router.patch("/plans/{plan_id}")
async def set_plan_intent(plan_id: str, body: IntentIn, current_user: dict = Depends(get_current_user)):
    """Correct what a plan is, its size, budget and where (e.g. 3 BHK, ₹1 Cr, Whitefield, Bengaluru)."""
    db = get_db()
    plan = await db.life_plans.find_one({"id": plan_id, "user_id": current_user["id"]}, {"_id": 0})
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    if body.category and body.category not in CATEGORIES:
        raise HTTPException(status_code=400, detail=f"category must be one of {sorted(CATEGORIES)}")
    merged = {**intent_of(plan), **body.model_dump(exclude_none=True)}
    intent = {**clean_intent(plan, merged), "source": "person"}
    await db.life_plans.update_one({"id": plan_id}, {"$set": {"intent": intent}})
    return {"plan_id": plan_id, "intent": intent}


# ---------------------------------------------------------------------------
# The owner's view
# ---------------------------------------------------------------------------

@demand_admin_router.get("")
async def admin_demand(category: Optional[str] = None, city: Optional[str] = None, area: Optional[str] = None,
                       form: Optional[str] = None, within_days: Optional[int] = Query(None, ge=1, le=3650),
                       admin: dict = Depends(require_admin)):
    db = get_db()
    today = date_type.today()
    s = await metering.get_settings(db)
    vendor_min = int(s["demand_min_count"])
    everyone = await _rows(db, today, shareable_only=False)
    sharable = await _rows(db, today, shareable_only=True)
    by_cat = []
    for key in CATEGORIES:
        all_n = len({r["user_id"] for r in everyone if r["category"] == key})
        share_n = len({r["user_id"] for r in sharable if r["category"] == key})
        if all_n:
            by_cat.append({"category": key, "label": CATEGORIES[key]["label"],
                           "people": all_n if all_n >= ADMIN_MIN else None, "shareable_people": share_n
                           if share_n >= ADMIN_MIN else None, "never_shared": key in NEVER_SHARED})
    cities = Counter()
    for r in everyone:
        if r["city"] and (not category or r["category"] == category):
            cities[r["city"]] += 1
    picked = _match(everyone, category, city, area, form, within_days)
    picked_share = _match(sharable, category, city, area, form, within_days)
    where = ", ".join(x for x in (area, city) if x)
    vendor = summarise(picked_share, vendor_min, within_days)
    consenting = await db.users.count_documents({"demand_sharing.on": True})
    return {
        "categories": sorted(by_cat, key=lambda x: -(x["people"] or 0)),
        "cities": [{"city": c, "plans": n} for c, n in cities.most_common(15) if n >= ADMIN_MIN],
        "selection": {"category": category, "city": city, "area": area, "form": form, "within_days": within_days},
        "all_plans": summarise(picked, ADMIN_MIN, within_days),
        "for_sellers": vendor,
        "report_preview": report_text(category or "other", where, within_days, vendor) if category else "",
        "people_sharing": consenting,
        "sharing_on": bool(s["demand_sharing_on"]), "vendor_min": vendor_min,
        "categories_never_shared": sorted(NEVER_SHARED),
    }


# ---------------------------------------------------------------------------
# Pamphlet's side
# ---------------------------------------------------------------------------

async def _partner_ok(db, key: Optional[str]) -> dict:
    expected = os.environ.get("HYMN_PARTNER_KEY", "")
    if not expected or not key or not hmac.compare_digest(key.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Not a Hymn partner")
    s = await metering.get_settings(db)
    if not s["demand_sharing_on"]:
        raise HTTPException(status_code=503, detail="Demand reports are switched off")
    return s


@partner_router.get("/demand")
async def partner_demand(category: str = Query(...), city: Optional[str] = None, area: Optional[str] = None,
                         form: Optional[str] = None, within_days: Optional[int] = Query(None, ge=1, le=3650),
                         x_hymn_partner_key: Optional[str] = Header(default=None)):
    """For Pamphlet: one anonymous demand report (only people who agreed, only big enough groups)."""
    db = get_db()
    s = await _partner_ok(db, x_hymn_partner_key)
    if category not in CATEGORIES or category in NEVER_SHARED:
        raise HTTPException(status_code=400, detail="That category isn't shared")
    rows = _match(await _rows(db, date_type.today(), shareable_only=True), category, city, area, form, within_days)
    summary = summarise(rows, int(s["demand_min_count"]), within_days)
    where = ", ".join(x for x in (area, city) if x)
    await db.partner_requests.insert_one({"at": datetime.now(timezone.utc).isoformat(), "category": category,
                                          "city": city, "area": area, "form": form, "within_days": within_days,
                                          "people": summary.get("people")})
    return {"category": category, "city": city, "area": area, "form": form, "within_days": within_days,
            **summary, "text": report_text(category, where, within_days, summary)}


@partner_router.get("/demand/areas")
async def partner_areas(category: str = Query(...), city: Optional[str] = None,
                        within_days: Optional[int] = Query(None, ge=1, le=3650),
                        x_hymn_partner_key: Optional[str] = Header(default=None)):
    """For Pamphlet: where there's enough demand to send a report (areas with at least the minimum)."""
    db = get_db()
    s = await _partner_ok(db, x_hymn_partner_key)
    if category not in CATEGORIES or category in NEVER_SHARED:
        raise HTTPException(status_code=400, detail="That category isn't shared")
    rows = _match(await _rows(db, date_type.today(), shareable_only=True), category, city, None, None, within_days)
    groups: Dict[tuple, set] = {}
    for r in rows:
        if r["city"]:
            groups.setdefault((r["city"], r["area"]), set()).add(r["user_id"])
    vmin = int(s["demand_min_count"])
    return {"category": category, "areas": sorted(
        ({"city": c, "area": a, "people": len(u)} for (c, a), u in groups.items() if len(u) >= vmin),
        key=lambda x: -x["people"])}
