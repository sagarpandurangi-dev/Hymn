"""Food log: search Hymn's food list or snap a photo, confirm, save the meal.

* Photo → the AI names the foods and servings (it never gives calories) →
  the person confirms or fixes each line → the meal is saved. Numbers come
  from the food list in code (``food_catalog``) or the person's own foods.
* Calories are shown as a rough range, never as a precise count; portions
  (vegetables & fruit, protein, sweets, outside / fried meals) come first and
  feed Health's daily log and suggestions.
* People with a history of eating disorders (health profile) see portions
  only, never calories or grams.
* Food is health data: it needs the health consent and is removed by
  "delete all my health data". Photos are never stored.
* Photos cost an AI call, so each plan has a monthly allowance
  (``HYMN_FOOD_PHOTOS_FREE``, default 30; ``HYMN_FOOD_PHOTOS_PREMIUM``,
  default 300). Searching and typing are free and unlimited.
"""
from __future__ import annotations

import base64
import binascii
import os
import uuid
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import food_ai
import food_catalog
from claude_client import AssistantUnavailable
from deps import get_current_user, get_db
from food_catalog import FOODS
from health import METRICS, _date, _profile, _store
from plans import user_plan

food_router = APIRouter(prefix="/food", tags=["food"])

MEALS = ("breakfast", "lunch", "dinner", "snack")
MAX_PHOTO_BYTES = 5 * 1024 * 1024
FOOD_METRICS = ("veg_fruit_portions", "protein_servings", "sugary_items", "outside_meals")
FOOD_LOG_NOTE = "from food log"
CALORIE_NOTE = ("Calories are a rough range: home cooking varies a lot (oil, ghee, sugar, bowl size). "
                "Use them to spot patterns, not to count every bite.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _r10(x: Decimal) -> int:
    return int((x / 10).quantize(Decimal(1), rounding=ROUND_HALF_UP)) * 10


def _r1(x: Decimal) -> float:
    return float(x.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def photo_allowance(user: dict) -> int:
    key, default = (("HYMN_FOOD_PHOTOS_PREMIUM", 300) if user_plan(user) == "premium"
                    else ("HYMN_FOOD_PHOTOS_FREE", 30))
    try:
        return max(0, int(os.environ.get(key, default)))
    except ValueError:
        return default


async def _my_foods(db, user_id: str) -> List[dict]:
    return await db.food_custom.find({"user_id": user_id}, {"_id": 0, "user_id": 0}).to_list(length=500)


async def _food(db, user_id: str, food_id: str) -> Optional[dict]:
    if food_id in FOODS:
        return FOODS[food_id]
    if food_id.startswith("my_"):
        return await db.food_custom.find_one({"id": food_id, "user_id": user_id}, {"_id": 0, "user_id": 0})
    return None


def _line_view(n: dict, hide_numbers: bool) -> dict:
    out = {k: _r1(n[k]) for k in ("veg_fruit_portions", "protein_servings", "sugary_items")}
    if not hide_numbers:
        out |= {"kcal": _r10(n["kcal"]), "kcal_low": _r10(n["kcal_low"]), "kcal_high": _r10(n["kcal_high"]),
                "protein_g": _r1(n["protein_g"]), "carbs_g": _r1(n["carbs_g"]), "fat_g": _r1(n["fat_g"]),
                "fibre_g": _r1(n["fibre_g"])}
    return out


def _zero() -> Dict[str, Decimal]:
    keys = ("kcal", "kcal_low", "kcal_high", "protein_g", "carbs_g", "fat_g", "fibre_g", "fried") + FOOD_METRICS[:3]
    return {k: Decimal(0) for k in keys}


def day_totals(meals: List[dict], hide_numbers: bool) -> dict:
    t = _zero()
    outside = 0
    for m in meals:
        fried = False
        for item in m["items"]:
            for k in t:
                t[k] += Decimal(str(item["nutrition"].get(k, 0)))
            fried = fried or Decimal(str(item["nutrition"].get("fried", 0))) > 0
        outside += 1 if (m.get("outside") or fried) else 0
    portions = {k: _r1(t[k]) for k in FOOD_METRICS[:3]} | {"outside_meals": outside}
    out = {"portions": portions}
    if hide_numbers:
        out["calories"] = None
    else:
        out["calories"] = {"estimate": _r10(t["kcal"]), "low": _r10(t["kcal_low"]), "high": _r10(t["kcal_high"]),
                           "note": CALORIE_NOTE}
        out["protein_g"], out["carbs_g"], out["fat_g"], out["fibre_g"] = (
            _r1(t["protein_g"]), _r1(t["carbs_g"]), _r1(t["fat_g"]), _r1(t["fibre_g"]))
    return out


async def _sync_day(db, user_id: str, day: str) -> None:
    """Write the day's portions into Health's daily log (what suggestions
    read). The food log is the truth for these metrics on days it is used;
    a later manual tap in the daily log replaces it until the next meal."""
    meals = await db.food_meals.find({"user_id": user_id, "date": day}, {"_id": 0}).to_list(length=None)
    await db.health_measurements.delete_many({"user_id": user_id, "taken_on": day, "source": "you",
                                              "metric": {"$in": list(FOOD_METRICS)}})
    if not meals:
        return
    portions = day_totals(meals, True)["portions"]
    rows = [{"metric": k, "value": min(float(v), METRICS[k][3]), "taken_on": day, "source": "you",
             "note": FOOD_LOG_NOTE} for k, v in portions.items()]
    await _store(db, user_id, rows)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@food_router.get("/search")
async def search(q: str = "", current_user: dict = Depends(get_current_user)):
    mine = [f | {"custom": True} for f in await _my_foods(get_db(), current_user["id"])]
    return [food_catalog.public(f) for f in food_catalog.search(q, mine)]


class Photo(BaseModel):
    image_base64: str
    media_type: Literal["image/jpeg", "image/png", "image/webp"] = "image/jpeg"


@food_router.post("/photo")
async def photo(body: Photo, current_user: dict = Depends(get_current_user)):
    """Read a food photo into draft lines for the person to confirm. Nothing
    is saved and the photo is not kept."""
    db = get_db()
    profile = await _profile(db, current_user["id"])
    hide = bool(profile.get("eating_disorder_history"))
    try:
        image = base64.b64decode(body.image_base64.split(",")[-1], validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="That photo couldn't be read. Please try again.")
    if not image or len(image) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=400, detail="Please use a photo under 5 MB.")
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    allowance = photo_allowance(current_user)
    used = await db.food_photo_uses.find_one({"user_id": current_user["id"], "month": month}) or {}
    if used.get("count", 0) >= allowance:
        raise HTTPException(status_code=429, detail="You've used this month's food photos. You can still search "
                                                    "and add foods by name.")
    try:
        reading = await food_ai.read_photo(image, body.media_type)
    except AssistantUnavailable:
        raise HTTPException(status_code=503, detail="Hymn couldn't read the photo right now. "
                                                    "Please add the food by name.")
    await db.food_photo_uses.update_one({"user_id": current_user["id"], "month": month}, {"$inc": {"count": 1}},
                                        upsert=True)
    left = max(0, allowance - used.get("count", 0) - 1)
    if reading.kind == "not_food":
        return {"kind": "not_food", "items": [], "label": None, "photos_left": left}
    if reading.kind == "label":
        return {"kind": "label", "items": [], "label": reading.label.model_dump(), "photos_left": left,
                "next": "Check the numbers, then save it as one of your foods (POST /api/food/my-foods)."}
    mine = [f | {"custom": True} for f in await _my_foods(db, current_user["id"])]
    items = []
    for it in reading.items:
        food = FOODS.get(it.food_id)
        options = food_catalog.search(it.name or (food or {}).get("name", ""), mine, limit=4)
        if food is None and options:
            food = options[0]
        amount = (Decimal(str(it.amount)) * 2).quantize(Decimal(1), rounding=ROUND_HALF_UP) / 2   # halves
        amount = max(amount, Decimal("0.5"))
        line = {"seen_as": it.name or (food or {}).get("name", ""), "amount": float(amount),
                "confidence": it.confidence, "food": food_catalog.public(food) if food else None,
                "alternatives": [food_catalog.public(o) for o in options if not food or o["id"] != food["id"]][:3]}
        if food:
            line["nutrition"] = _line_view(food_catalog.nutrition(food, amount), hide)
        items.append(line)
    return {"kind": "plate", "items": items, "label": None, "photos_left": left,
            "note": "Check each line and fix anything Hymn got wrong before saving."}


class MealItem(BaseModel):
    food_id: Optional[str] = None            # from the food list or your own foods ("my_…")
    name: Optional[str] = None               # anything not in the list
    amount: float = Field(default=1, gt=0, le=20)


class Meal(BaseModel):
    date: str
    meal: Literal["breakfast", "lunch", "dinner", "snack"]
    items: List[MealItem] = Field(min_length=1, max_length=30)
    outside: bool = False                    # eaten out or ordered in
    from_photo: bool = False


@food_router.post("/meals", status_code=201)
async def add_meal(body: Meal, current_user: dict = Depends(get_current_user)):
    db = get_db()
    profile = await _profile(db, current_user["id"])
    day = _date(body.date)
    items = []
    for it in body.items:
        amount = Decimal(str(it.amount))
        if it.food_id:
            food = await _food(db, current_user["id"], it.food_id)
            if not food:
                raise HTTPException(status_code=400, detail=f"Unknown food: {it.food_id}")
            n = food_catalog.nutrition(food, amount)
            items.append({"food_id": food["id"], "name": food["name"], "unit": food["unit"], "amount": float(amount),
                          "nutrition": {k: str(v) for k, v in n.items()}})
        elif (it.name or "").strip():
            # Not in the list: kept by name, counted in no totals.
            items.append({"food_id": None, "name": it.name.strip()[:80], "unit": "", "amount": float(amount),
                          "nutrition": {}, "not_counted": True})
        else:
            raise HTTPException(status_code=400, detail="Each item needs a food or a name.")
    doc = {"id": str(uuid.uuid4()), "user_id": current_user["id"], "date": day, "meal": body.meal,
           "outside": body.outside, "from_photo": body.from_photo, "items": items, "created_at": _now()}
    await db.food_meals.insert_one(dict(doc))
    await _sync_day(db, current_user["id"], day)
    return _meal_view(doc, bool(profile.get("eating_disorder_history")))


def _meal_view(m: dict, hide: bool) -> dict:
    items = []
    for it in m["items"]:
        n = {k: Decimal(v) for k, v in it["nutrition"].items()}
        items.append({"food_id": it["food_id"], "name": it["name"], "unit": it["unit"], "amount": it["amount"],
                      "not_counted": it.get("not_counted", False),
                      **({"nutrition": _line_view(n, hide)} if n else {})})
    return {"id": m["id"], "date": m["date"], "meal": m["meal"], "outside": m["outside"],
            "from_photo": m.get("from_photo", False), "items": items,
            "totals": day_totals([m], hide)}


@food_router.get("/day")
async def get_day(date: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    profile = await _profile(db, current_user["id"])
    hide = bool(profile.get("eating_disorder_history"))
    day = _date(date)
    meals = await db.food_meals.find({"user_id": current_user["id"], "date": day}, {"_id": 0}) \
        .sort("created_at", 1).to_list(length=None)
    meals.sort(key=lambda m: MEALS.index(m["meal"]))
    return {"date": day, "meals": [_meal_view(m, hide) for m in meals], "totals": day_totals(meals, hide),
            "values_reviewed": food_catalog.VALUES_REVIEWED}


@food_router.delete("/meals/{meal_id}")
async def delete_meal(meal_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    m = await db.food_meals.find_one({"id": meal_id, "user_id": current_user["id"]})
    if not m:
        raise HTTPException(status_code=404, detail="Meal not found")
    await db.food_meals.delete_one({"id": meal_id})
    await _sync_day(db, current_user["id"], m["date"])
    return {"detail": "Deleted"}


class MyFood(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    unit: str = Field(default="serving", max_length=30)
    kcal: float = Field(ge=0, le=3000)
    protein_g: float = Field(default=0, ge=0, le=300)
    carbs_g: float = Field(default=0, ge=0, le=500)
    fat_g: float = Field(default=0, ge=0, le=300)
    fibre_g: float = Field(default=0, ge=0, le=100)
    veg_fruit_portions: float = Field(default=0, ge=0, le=5)
    protein_servings: float = Field(default=0, ge=0, le=5)
    sugary: bool = False
    fried: bool = False


@food_router.post("/my-foods", status_code=201)
async def add_my_food(body: MyFood, current_user: dict = Depends(get_current_user)):
    """Your own foods: a family recipe, or a packaged food from its label."""
    db = get_db()
    await _profile(db, current_user["id"])
    doc = {"id": f"my_{uuid.uuid4().hex[:12]}", "user_id": current_user["id"], "name": body.name.strip(),
           "aliases": [], "unit": body.unit, "kcal": body.kcal, "protein_g": body.protein_g,
           "carbs_g": body.carbs_g, "fat_g": body.fat_g, "fibre_g": body.fibre_g,
           "counts": {"veg_fruit_portions": body.veg_fruit_portions, "protein_servings": body.protein_servings,
                      "sugary_items": 1 if body.sugary else 0},
           # Label figures are printed per serving: a narrow range.
           "fried": body.fried, "kind": "simple", "group": "mine", "custom": True, "created_at": _now()}
    await db.food_custom.insert_one(dict(doc))
    return food_catalog.public(doc)


@food_router.get("/my-foods")
async def list_my_foods(current_user: dict = Depends(get_current_user)):
    return [food_catalog.public(f) for f in await _my_foods(get_db(), current_user["id"])]


@food_router.delete("/my-foods/{food_id}")
async def delete_my_food(food_id: str, current_user: dict = Depends(get_current_user)):
    r = await get_db().food_custom.delete_one({"id": food_id, "user_id": current_user["id"]})
    if not r.deleted_count:
        raise HTTPException(status_code=404, detail="Food not found")
    return {"detail": "Deleted"}


async def ensure_food_indexes(db) -> None:
    await db.food_meals.create_index([("user_id", 1), ("date", 1)])
    await db.food_custom.create_index([("user_id", 1), ("id", 1)], unique=True)
    await db.food_photo_uses.create_index([("user_id", 1), ("month", 1)], unique=True)
