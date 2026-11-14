"""Planned money: everything a user expects to come in or go out.

One idea replaces three older ones:

* monthly money commitments (salary, rent, SIP, EMI: repeating),
* financial commitments (a trip, a phone: a one-off spend, possibly with
  money set aside for it),
* expected income (a bonus, a refund: a one-off receipt).

New items are stored here (``planned_money``). Items still kept in the
three old collections are shown here too, translated on the fly, so the
older screens keep working while the app moves to this one; they are
read-only through this API until they're moved over.

Actuals live in the ledger; planned money is the future. The forecast
reads planned money.
"""
from __future__ import annotations

import re
import uuid
from datetime import date as date_type, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Literal, Optional

from bson.decimal128 import Decimal128
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from deps import get_current_user, get_db

planned_money_router = APIRouter(prefix="/planned-money", tags=["planned-money"])

ZERO = Decimal(0)
CENT = Decimal("0.01")
DIRECTIONS = ("in", "out")
PURPOSES = ("income", "spend", "saving", "investment", "loan_payment", "other")
REPEATS = ("once", "monthly", "yearly")
_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_CUR = re.compile(r"^[A-Z]{3}$")

# Old monthly commitment types → (direction, purpose).
_MONTHLY_TYPES = {
    "income": ("in", "income"), "expense": ("out", "spend"), "debt_payment": ("out", "loan_payment"),
    "saving": ("out", "saving"), "investment": ("out", "investment"), "other": ("out", "other"),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dec(v: Any) -> Decimal:
    if v is None or v == "":
        return ZERO
    if isinstance(v, Decimal128):
        return v.to_decimal()
    try:
        return Decimal(str(v))
    except InvalidOperation:
        return ZERO


def _out(d: Decimal) -> str:
    return format(d.quantize(CENT), "f")


# ---------------------------------------------------------------------------
# Translating the old records (pure)
# ---------------------------------------------------------------------------

def from_monthly(doc: dict) -> dict:
    direction, purpose = _MONTHLY_TYPES.get(doc.get("commitment_type") or "other", ("out", "other"))
    return {
        "id": doc["id"], "title": doc.get("title") or "", "direction": direction, "purpose": purpose,
        "amount": _dec(doc.get("amount")), "currency": doc.get("currency") or "",
        "repeat": "monthly", "date": None, "start_month": doc.get("start_month"),
        "end_month": doc.get("end_month"), "certainty": "sure", "set_aside": False,
        "status": "active", "done_amount": ZERO, "category": None, "account_id": None,
        "goal_id": None, "notes": doc.get("notes") or "",
        "source": "monthly_commitment", "editable": False,
    }


def from_commitment(doc: dict) -> dict:
    state = doc.get("state")
    amount = _dec(doc.get("amount"))
    paid = _dec(doc.get("paid_amount"))
    return {
        "id": doc["id"], "title": doc.get("title") or "", "direction": "out", "purpose": "spend",
        "amount": amount, "currency": doc.get("currency") or "",
        "repeat": "once", "date": doc.get("due_date"), "start_month": None, "end_month": None,
        # A draft is an idea; reserved / partly paid / overdue money is held for it.
        "certainty": "maybe" if state == "draft" else "sure",
        "set_aside": state in ("reserved", "partial", "expired"),
        "status": {"completed": "done", "cancelled": "cancelled"}.get(state, "active"),
        "done_amount": paid, "category": None, "account_id": None,
        "goal_id": doc.get("goal_id"), "notes": doc.get("description") or "",
        "source": "financial_commitment", "editable": False,
    }


def from_expected_income(doc: dict) -> dict:
    received = _dec(doc.get("received_amount"))
    return {
        "id": doc["id"], "title": doc.get("title") or "", "direction": "in", "purpose": "income",
        "amount": _dec(doc.get("amount")), "currency": doc.get("currency") or "",
        "repeat": "once", "date": doc.get("expected_date"), "start_month": None, "end_month": None,
        "certainty": "sure" if doc.get("included_in_forecast") else "maybe", "set_aside": False,
        "status": "done" if doc.get("received") else "active",
        "done_amount": received, "category": None, "account_id": None,
        "goal_id": None, "notes": doc.get("description") or "",
        "source": "expected_income", "editable": False,
    }


def from_native(doc: dict) -> dict:
    return {**{k: v for k, v in doc.items() if k not in ("_id", "user_id")},
            "amount": _dec(doc.get("amount")), "done_amount": _dec(doc.get("done_amount")),
            "source": "planned", "editable": True}


# ---------------------------------------------------------------------------
# When items fall (pure)
# ---------------------------------------------------------------------------

def _month_of(day: Optional[str]) -> Optional[str]:
    return day[:7] if isinstance(day, str) and len(day) >= 7 and _MONTH.match(day[:7]) else None


def amount_in_month(item: dict, month: str) -> Decimal:
    """What this item still brings in or takes out in ``month`` (0 if
    nothing). One-offs count only what isn't done yet."""
    if item["status"] != "active":
        return ZERO
    if item["repeat"] == "once":
        if _month_of(item.get("date")) != month:
            return ZERO
        return max(item["amount"] - item["done_amount"], ZERO)
    start, end = item.get("start_month"), item.get("end_month")
    if not start or month < start or (end and month > end):
        return ZERO
    if item["repeat"] == "yearly" and month[5:7] != start[5:7]:
        return ZERO
    return item["amount"]


def month_totals(items: List[dict], month: str, currency: str) -> dict:
    """Totals for one month and currency, split the way the forecast needs."""
    t = {k: ZERO for k in ("income", "spend", "moves", "set_aside", "maybe_in", "maybe_out")}
    for it in items:
        if it["currency"] != currency:
            continue
        amt = amount_in_month(it, month)
        if not amt:
            continue
        if it["certainty"] == "maybe":
            t["maybe_in" if it["direction"] == "in" else "maybe_out"] += amt
        elif it["direction"] == "in":
            t["income"] += amt
        elif it["purpose"] in ("saving", "investment"):
            t["moves"] += amt  # money moved to your own savings, not spent
        elif it["repeat"] == "once" and it["set_aside"]:
            t["set_aside"] += amt
        else:
            t["spend"] += amt
    return t


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

async def load_items(db, user_id: str) -> List[dict]:
    import finance_manager

    items = [from_native(d) for d in await db.planned_money.find({"user_id": user_id}).to_list(length=None)]
    items += [from_monthly(d) for d in await db.monthly_money_commitments.find(
        {"user_id": user_id}, {"_id": 0}).to_list(length=None)]
    items += [from_commitment(d) for d in await finance_manager._read_all_commitments(db, user_id)]
    items += [from_expected_income(d) for d in await db.expected_incomes.find(
        {"user_id": user_id}, {"_id": 0}).to_list(length=None)]
    return items


def public(item: dict) -> dict:
    return {**item, "amount": _out(item["amount"]), "done_amount": _out(item["done_amount"]),
            "remaining_amount": _out(max(item["amount"] - item["done_amount"], ZERO))}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

class PlannedMoneyCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    direction: Literal["in", "out"]
    purpose: Literal["income", "spend", "saving", "investment", "loan_payment", "other"]
    amount: Any
    currency: str
    repeat: Literal["once", "monthly", "yearly"] = "once"
    date: Optional[str] = None          # once
    start_month: Optional[str] = None   # monthly / yearly
    end_month: Optional[str] = None
    certainty: Literal["sure", "maybe"] = "sure"
    set_aside: bool = False             # hold money aside for a one-off spend
    category: Optional[str] = None
    account_id: Optional[str] = None
    goal_id: Optional[str] = None
    notes: str = ""


class PlannedMoneyUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    amount: Any = None
    date: Optional[str] = None
    start_month: Optional[str] = None
    end_month: Optional[str] = None
    certainty: Optional[Literal["sure", "maybe"]] = None
    set_aside: Optional[bool] = None
    category: Optional[str] = None
    account_id: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[Literal["active", "done", "cancelled"]] = None
    done_amount: Any = None


def _validate(doc: dict) -> dict:
    def bad(msg):
        raise HTTPException(status_code=400, detail=msg)
    amount = _dec(doc.get("amount"))
    if amount <= 0:
        bad("Amount must be more than zero.")
    if not _CUR.match(doc.get("currency") or ""):
        bad("Currency must be a 3-letter code like INR.")
    if (doc["direction"] == "in") != (doc["purpose"] == "income"):
        bad("Money coming in is income; money going out is spending, saving, investing or a loan payment.")
    if doc["repeat"] == "once":
        try:
            date_type.fromisoformat(doc.get("date") or "")
        except ValueError:
            bad("A one-off needs a date (YYYY-MM-DD).")
        doc["start_month"] = doc["end_month"] = None
    else:
        if not _MONTH.match(doc.get("start_month") or ""):
            bad("A repeating item needs a start month (YYYY-MM).")
        if doc.get("end_month") and (not _MONTH.match(doc["end_month"]) or doc["end_month"] < doc["start_month"]):
            bad("End month must be YYYY-MM and not before the start month.")
        doc["date"] = None
    if doc.get("set_aside") and (doc["repeat"] != "once" or doc["direction"] != "out"):
        bad("Only a one-off spend can have money set aside.")
    done = _dec(doc.get("done_amount"))
    if done < 0:
        bad("Done amount can't be negative.")
    doc["amount"] = Decimal128(amount)
    doc["done_amount"] = Decimal128(done)
    return doc


@planned_money_router.post("", status_code=201)
async def create_item(body: PlannedMoneyCreate, current_user: dict = Depends(get_current_user)):
    doc = _validate({**body.dict(), "id": str(uuid.uuid4()), "user_id": current_user["id"],
                     "status": "active", "done_amount": "0", "created_at": _now(), "updated_at": _now()})
    await get_db().planned_money.insert_one(dict(doc))
    return public(from_native(doc))


@planned_money_router.get("")
async def list_items(include_done: bool = False, current_user: dict = Depends(get_current_user)):
    items = await load_items(get_db(), current_user["id"])
    if not include_done:
        items = [i for i in items if i["status"] == "active"]
    items.sort(key=lambda i: (i.get("date") or (i.get("start_month") or "") + "-00", i["title"]))
    return [public(i) for i in items]


@planned_money_router.get("/months")
async def months(start: Optional[str] = None, count: int = Query(12, ge=1, le=36),
                 current_user: dict = Depends(get_current_user)):
    """Per month and currency: planned income, spending, money moved to
    savings, set-aside spends, and the 'maybe' amounts kept apart."""
    month = start or date_type.today().isoformat()[:7]
    if not _MONTH.match(month):
        raise HTTPException(status_code=400, detail="start must be YYYY-MM")
    items = await load_items(get_db(), current_user["id"])
    currencies = sorted({i["currency"] for i in items if i["currency"]})
    out = []
    for _ in range(count):
        for cur in currencies:
            t = month_totals(items, month, cur)
            out.append({"month": month, "currency": cur, **{k: _out(v) for k, v in t.items()}})
        y, m = int(month[:4]), int(month[5:7])
        month = f"{y + 1}-01" if m == 12 else f"{y}-{m + 1:02d}"
    return out


async def _native(db, user_id: str, item_id: str) -> dict:
    doc = await db.planned_money.find_one({"id": item_id, "user_id": user_id}, {"_id": 0})
    if doc:
        return doc
    if any(i["id"] == item_id for i in await load_items(db, user_id)):
        raise HTTPException(status_code=409, detail="This item comes from an older screen; edit it there for now.")
    raise HTTPException(status_code=404, detail="Not found")


@planned_money_router.patch("/{item_id}")
async def update_item(item_id: str, body: PlannedMoneyUpdate, current_user: dict = Depends(get_current_user)):
    db = get_db()
    doc = await _native(db, current_user["id"], item_id)
    doc = _validate({**doc, **body.dict(exclude_unset=True), "updated_at": _now()})
    await db.planned_money.replace_one({"id": item_id, "user_id": current_user["id"]}, {**doc})
    return public(from_native(doc))


@planned_money_router.delete("/{item_id}")
async def delete_item(item_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    await _native(db, current_user["id"], item_id)
    await db.planned_money.delete_one({"id": item_id, "user_id": current_user["id"]})
    return {"detail": "Deleted"}


async def ensure_planned_money_indexes(db) -> None:
    await db.planned_money.create_index("id", unique=True)
    await db.planned_money.create_index([("user_id", 1), ("status", 1)])
