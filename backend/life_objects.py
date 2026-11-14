"""Life objects and their lifetime cost (LTC). Premium.

Everything a person owns, owes, keeps doing or runs is a *life object*:

* **asset**: house, car, phone, jewellery…
* **liability**: credit card, home / car / personal loan…
* **habit**: smoking, gym, daily coffee…
* **venture**: a side business or freelancing.

Each one is a project underneath (created automatically), so check-ins
(fuel fill, gym visit, EMI paid) and tasks (insurance renewal) attach to it
the usual way. Money entries in the ledger count towards it when tagged to
it, or automatically when their category is one the object owns (fuel → the
car) and no other active object claims that category.

LTC = cost to get it + cost to keep it + cost of the money (interest, fees,
penalties) + value lost (straight-line depreciation) − what comes back
(cashback, resale, a venture's income). Shown to date, projected over its
life, per month and per unit (per km, per visit…), with hours from
check-ins. No opportunity cost: comparing a car with a mutual fund only
induces guilt (owner decision).
"""
from __future__ import annotations

import re
import uuid
from collections import defaultdict
from datetime import date as date_type, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Literal, Optional

from bson.decimal128 import Decimal128
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import categories
import ledger
from deps import get_current_user, get_db
from plans import require_feature

life_objects_router = APIRouter(prefix="/life-objects", tags=["life-objects"])

ZERO = Decimal(0)
CENT = Decimal("0.01")
TYPES = ("asset", "liability", "habit", "venture")

# What each kind owns by default (categories of the two-level tree).
DEFAULT_CATEGORIES: Dict[str, List[str]] = {
    "car": ["fuel", "car_upkeep", "parking_tolls", "vehicle_insurance"],
    "bike": ["fuel", "car_upkeep", "parking_tolls", "vehicle_insurance"],
    "house": ["maintenance", "property_tax", "repairs"],
}
DEFAULT_UNIT = {"car": "km", "bike": "km", "habit": "day", "gym": "visit"}

_PENALTY = re.compile(r"LATE|PENAL|OVER ?LIMIT|BOUNCE|RETURN CHARGE", re.I)
_ANNUAL = re.compile(r"ANNUAL|JOINING|RENEWAL FEE|MEMBERSHIP FEE", re.I)


def _dec(v: Any) -> Decimal:
    if v in (None, ""):
        return ZERO
    if isinstance(v, Decimal128):
        return v.to_decimal()
    try:
        return Decimal(str(v))
    except InvalidOperation:
        return ZERO


def _out(d: Decimal) -> str:
    return format(d.quantize(CENT), "f")


def _months_between(start: str, end: str) -> Decimal:
    a, b = date_type.fromisoformat(start), date_type.fromisoformat(end)
    return max(Decimal((b - a).days) / Decimal("30.4375"), ZERO)


def _category_of(tx: dict) -> Optional[str]:
    for p in tx["postings"]:
        if p["account_id"].startswith(("expense:", "income:")):
            return p["account_id"]
    return None


def _spent(tx: dict) -> Decimal:
    """Expense side of an entry (what it cost)."""
    return sum((p["amount"] for p in tx["postings"] if p["account_id"].startswith("expense:")), ZERO)


def _received(tx: dict) -> Decimal:
    return sum((-p["amount"] for p in tx["postings"] if p["account_id"].startswith("income:")), ZERO)


def belongs(obj: dict, tx: dict, claimed: Dict[str, int], today: str) -> bool:
    """Does this ledger entry count towards this object?"""
    if obj["id"] in (tx.get("object_ids") or []):
        return True
    if tx.get("object_ids"):
        return False  # tagged to something else
    end = obj.get("ended_on") or today
    if not (obj["started_on"] <= tx["date"] <= end):
        return False
    acct = obj.get("account_id")
    if acct and any(p["account_id"] == acct for p in tx["postings"]) and tx["kind"] in ("expense", "refund", "income", "loan_payment"):
        cat = _category_of(tx) or ""
        # On a card or loan, only what the borrowing itself costs (or gives back).
        return cat in ("expense:interest", "expense:fees") or cat.startswith("income:") or tx["kind"] == "refund"
    cat = (_category_of(tx) or "").partition(":")[2]
    if cat and cat in (obj.get("categories") or []) and claimed.get(cat, 0) == 1:
        return True
    words = obj.get("match_words") or []
    return any(w.upper() in (tx.get("description") or "").upper() for w in words if w)


def value_lost_between(obj: dict, start: str, end: str) -> Decimal:
    """Straight-line value an asset lost between two dates (inclusive of
    whole days), 0 for anything else or without a price and life."""
    price, life = _dec(obj.get("purchase_price")), Decimal(obj.get("expected_life_months") or 0)
    if obj.get("type") != "asset" or not price or not life:
        return ZERO
    last = min(end, obj.get("ended_on") or end)
    first = max(start, obj["started_on"])
    if first > last:
        return ZERO
    per_month = (price - _dec(obj.get("residual_value"))) / life
    cap = price - _dec(obj.get("residual_value"))
    before = min(per_month * _months_between(obj["started_on"], first), cap)
    upto = min(per_month * _months_between(obj["started_on"], last), cap)
    return max(upto - before, ZERO)


def book_value(obj: dict, as_of: str) -> Decimal:
    """What an asset is worth on the books on a date (0 once sold)."""
    price = _dec(obj.get("purchase_price"))
    if obj.get("type") != "asset" or not price or obj["started_on"] > as_of:
        return ZERO
    if obj.get("ended_on") and obj["ended_on"] <= as_of:
        return ZERO
    return price - value_lost_between(obj, obj["started_on"], as_of)


def compute_ltc(obj: dict, txs: List[dict], checkins: List[dict], claimed: Dict[str, int], today: str) -> dict:
    """Pure: the lifetime cost of one object."""
    running: Dict[str, Decimal] = defaultdict(Decimal)
    financing = {"interest": ZERO, "fees": ZERO, "penalties": ZERO, "annual_fees": ZERO}
    recovered = ZERO
    entries = []
    for tx in txs:
        if not belongs(obj, tx, claimed, today):
            continue
        cost, got = _spent(tx), _received(tx)
        if cost < 0:  # a refund / cashback reverses spending
            got, cost = got - cost, ZERO
        cat = _category_of(tx) or ""
        if cat == "expense:interest" or "FINANCE CHARGE" in (tx.get("description") or "").upper():
            financing["interest"] += cost
        elif cat == "expense:fees":
            desc = tx.get("description") or ""
            key = "penalties" if _PENALTY.search(desc) else "annual_fees" if _ANNUAL.search(desc) else "fees"
            financing[key] += cost
        elif cost:
            running[categories.describe(cat)["category_label"] if cat else "Other"] += cost
        recovered += got
        entries.append({"id": tx["id"], "date": tx["date"], "description": tx.get("description") or "",
                        "amount": _out(cost or got), "direction": "out" if cost else "in"})

    end = obj.get("ended_on") or today
    months = _months_between(obj["started_on"], end) if obj["started_on"] <= end else ZERO
    price = _dec(obj.get("purchase_price"))
    acquisition = price + _dec(obj.get("acquisition_costs"))
    life = Decimal(obj.get("expected_life_months") or 0)
    residual = _dec(obj.get("residual_value"))
    value_lost = ZERO
    sold = obj.get("sold_for") is not None
    if obj["type"] == "asset" and price and sold:
        value_lost = price - _dec(obj["sold_for"])     # what it really cost to own it
    elif obj["type"] == "asset" and price and life:
        per_month = (price - residual) / life
        value_lost = min(per_month * months, price - residual)
    elif sold:
        recovered += _dec(obj["sold_for"])            # e.g. a venture sold

    running_total = sum(running.values(), ZERO)
    financing_total = sum(financing.values(), ZERO)
    # An asset's price isn't a cost by itself (you still own the thing);
    # what it costs is the value it loses. For everything else the price
    # is simply spent.
    getting = acquisition - price if obj["type"] == "asset" else acquisition
    total = getting + value_lost + running_total + financing_total - recovered

    minutes = sum(_dec((c.get("data") or {}).get("minutes")) for c in checkins)
    usage, unit = None, obj.get("unit")
    if unit == "km":
        readings = sorted(_dec((c.get("data") or {}).get("odometer")) for c in checkins
                          if (c.get("data") or {}).get("odometer") not in (None, ""))
        usage = readings[-1] - readings[0] if len(readings) >= 2 else None
    elif unit in ("visit", "session", "use", "pack"):
        usage = Decimal(len(checkins)) or None
    elif unit == "day":
        usage = Decimal((date_type.fromisoformat(end) - date_type.fromisoformat(obj["started_on"])).days + 1)
    elif unit == "month":
        usage = months or None

    projected = None
    if life and months:
        remaining = max(life - months, ZERO)
        monthly_running = (running_total + financing_total) / months
        projected = total + monthly_running * remaining + (
            (price - residual) - value_lost if obj["type"] == "asset" and price and not sold else ZERO)

    return {
        "to_date": _out(total),
        "breakdown": {
            "getting_it": _out(getting),
            "value_lost": _out(value_lost),
            "keeping_it": {k: _out(v) for k, v in sorted(running.items())},
            "cost_of_money": {k: _out(v) for k, v in financing.items()},
            "came_back": _out(recovered),
        },
        "months": _out(months),
        "per_month": _out(total / months) if months else None,
        "unit": unit,
        "usage": _out(usage) if usage else None,
        "per_unit": _out(total / usage) if usage else None,
        "lifetime_projected": _out(projected) if projected is not None else None,
        "hours": _out(minutes / 60) if minutes else "0.00",
        "check_ins": len(checkins),
        "entries": sorted(entries, key=lambda e: e["date"], reverse=True),
    }


# ---------------------------------------------------------------------------
# Storage and routes
# ---------------------------------------------------------------------------

class LifeObjectCreate(BaseModel):
    type: Literal["asset", "liability", "habit", "venture"]
    kind: str = Field(default="other", max_length=40)          # car, house, credit_card, smoking, gym…
    name: str = Field(min_length=1, max_length=120)
    started_on: str
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")
    purchase_price: Any = None
    acquisition_costs: Any = None       # registration, stamp duty, processing fee…
    expected_life_months: Optional[int] = Field(default=None, ge=1, le=1200)
    residual_value: Any = None
    account_id: Optional[str] = None    # the card / loan / asset account it lives in
    categories: Optional[List[str]] = None
    match_words: List[str] = Field(default_factory=list)
    unit: Optional[Literal["km", "visit", "session", "use", "pack", "day", "month"]] = None
    notes: str = ""


class LifeObjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    purchase_price: Any = None
    acquisition_costs: Any = None
    expected_life_months: Optional[int] = Field(default=None, ge=1, le=1200)
    residual_value: Any = None
    account_id: Optional[str] = None
    categories: Optional[List[str]] = None
    match_words: Optional[List[str]] = None
    unit: Optional[Literal["km", "visit", "session", "use", "pack", "day", "month"]] = None
    ended_on: Optional[str] = None
    sold_for: Any = None
    notes: Optional[str] = None


class TagRequest(BaseModel):
    transaction_ids: List[str] = Field(min_length=1, max_length=500)
    remove: bool = False


def _premium(user: dict) -> None:
    require_feature(user, "life_objects", "Lifetime cost of what you own and owe is a Premium feature.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _valid_date(v: Optional[str], field: str) -> None:
    try:
        date_type.fromisoformat(v or "")
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{field} must be a date (YYYY-MM-DD).")


def _clean(doc: dict) -> dict:
    for f in ("purchase_price", "acquisition_costs", "residual_value", "sold_for"):
        if doc.get(f) not in (None, ""):
            amount = _dec(doc[f])
            if amount < 0:
                raise HTTPException(status_code=400, detail=f"{f.replace('_', ' ')} can't be negative.")
            doc[f] = Decimal128(amount)
    bad = [c for c in (doc.get("categories") or []) if c not in categories.EXPENSE]
    if bad:
        raise HTTPException(status_code=400, detail=f"Unknown categories: {', '.join(bad)}")
    return doc


def _public(obj: dict) -> dict:
    out = {k: v for k, v in obj.items() if k not in ("_id", "user_id")}
    for f in ("purchase_price", "acquisition_costs", "residual_value", "sold_for"):
        if out.get(f) is not None:
            out[f] = _out(_dec(out[f]))
    return out


async def _load(db, user_id: str):
    objs = await db.life_objects.find({"user_id": user_id}, {"_id": 0}).to_list(length=None)
    txs = await ledger.load_transactions(db, user_id)
    claimed: Dict[str, int] = defaultdict(int)
    for o in objs:
        if not o.get("ended_on"):
            for c in o.get("categories") or []:
                claimed[c] += 1
    return objs, txs, claimed


async def _checkins(db, user_id: str, obj: dict) -> List[dict]:
    if not obj.get("project_id"):
        return []
    return await db.checkins.find({"user_id": user_id, "project_id": obj["project_id"]},
                                  {"_id": 0, "date": 1, "data": 1}).to_list(length=None)


@life_objects_router.post("", status_code=201)
async def create(body: LifeObjectCreate, current_user: dict = Depends(get_current_user)):
    _premium(current_user)
    _valid_date(body.started_on, "started_on")
    db, now = get_db(), _now()
    project = {"id": str(uuid.uuid4()), "user_id": current_user["id"], "title": body.name.strip(),
               "description": f"Life object ({body.type})", "status": "active", "start_date": body.started_on,
               "target_end_date": "", "notes": "", "commitment_type": "postponable",
               "life_object": True, "created_at": now, "updated_at": now}
    await db.projects.insert_one(dict(project))
    doc = _clean({**body.dict(), "id": str(uuid.uuid4()), "user_id": current_user["id"],
                  "categories": body.categories if body.categories is not None else DEFAULT_CATEGORIES.get(body.kind, []),
                  "unit": body.unit or DEFAULT_UNIT.get(body.kind) or DEFAULT_UNIT.get(body.type),
                  "project_id": project["id"], "ended_on": None, "sold_for": None,
                  "created_at": now, "updated_at": now})
    await db.life_objects.insert_one(dict(doc))
    return _public(doc)


@life_objects_router.get("")
async def list_objects(current_user: dict = Depends(get_current_user)):
    _premium(current_user)
    db = get_db()
    objs, txs, claimed = await _load(db, current_user["id"])
    today = date_type.today().isoformat()
    out = []
    for o in objs:
        ltc = compute_ltc(o, txs, await _checkins(db, current_user["id"], o), claimed, today)
        out.append({**_public(o), "ltc": {k: v for k, v in ltc.items() if k != "entries"}})
    return out


async def _own(db, user_id: str, obj_id: str) -> dict:
    o = await db.life_objects.find_one({"id": obj_id, "user_id": user_id}, {"_id": 0})
    if not o:
        raise HTTPException(status_code=404, detail="Not found")
    return o


@life_objects_router.get("/{obj_id}")
async def detail(obj_id: str, current_user: dict = Depends(get_current_user)):
    _premium(current_user)
    db = get_db()
    o = await _own(db, current_user["id"], obj_id)
    objs, txs, claimed = await _load(db, current_user["id"])
    today = date_type.today().isoformat()
    return {**_public(o), "ltc": compute_ltc(o, txs, await _checkins(db, current_user["id"], o), claimed, today)}


@life_objects_router.patch("/{obj_id}")
async def update(obj_id: str, body: LifeObjectUpdate, current_user: dict = Depends(get_current_user)):
    _premium(current_user)
    db = get_db()
    o = await _own(db, current_user["id"], obj_id)
    changes = body.dict(exclude_unset=True)
    if changes.get("ended_on"):
        _valid_date(changes["ended_on"], "ended_on")
    o = _clean({**o, **changes, "updated_at": _now()})
    await db.life_objects.replace_one({"id": obj_id, "user_id": current_user["id"]}, {**o})
    return _public(o)


@life_objects_router.post("/{obj_id}/tag")
async def tag(obj_id: str, body: TagRequest, current_user: dict = Depends(get_current_user)):
    """Count entries towards this object (or stop counting them)."""
    _premium(current_user)
    db = get_db()
    await _own(db, current_user["id"], obj_id)
    op = {"$pull": {"object_ids": obj_id}} if body.remove else {"$addToSet": {"object_ids": obj_id}}
    r = await db.ledger_transactions.update_many(
        {"user_id": current_user["id"], "id": {"$in": body.transaction_ids}}, {**op, "$set": {"updated_at": _now()}})
    return {"matched": r.matched_count}


@life_objects_router.delete("/{obj_id}")
async def delete(obj_id: str, current_user: dict = Depends(get_current_user)):
    _premium(current_user)
    db = get_db()
    o = await _own(db, current_user["id"], obj_id)
    await db.ledger_transactions.update_many({"user_id": current_user["id"], "object_ids": obj_id},
                                             {"$pull": {"object_ids": obj_id}})
    await db.life_objects.delete_one({"id": obj_id, "user_id": current_user["id"]})
    await db.projects.update_one({"id": o.get("project_id"), "user_id": current_user["id"]},
                                 {"$set": {"status": "completed", "updated_at": _now()}})
    return {"detail": "Deleted"}


async def ensure_life_object_indexes(db) -> None:
    await db.life_objects.create_index("id", unique=True)
    await db.life_objects.create_index("user_id")
    await db.ledger_transactions.create_index([("user_id", 1), ("object_ids", 1)])
