"""Family net worth: a household of people, some with their own Hymn
account, some added by hand (kids, parents).

* Members with an account are invited by Pamphlet ID or alias and must
  accept. Each of them decides what the family sees: just their total
  ("total") or the breakdown by group ("full"); they can change it or leave
  any time. Nothing of theirs is visible before they accept.
* Members without an account are notional: whoever adds them enters their
  assets and debts (a child's PPF, an FD in a parent's name). Only the
  person who added an entry can change it.
* Joint things (a house or home loan in two names) are entered once with
  ownership shares and counted once in the family total.

The family statement uses the same groups as the Statement of Net Worth,
with a column per person and a family total.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date as date_type, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import hymn_ids
import reports
from deps import get_current_user, get_db

family_router = APIRouter(prefix="/family", tags=["family"])

ZERO = Decimal(0)
ASSET_GROUPS = [g for g, _, _ in reports.ASSET_GROUPS]
LIABILITY_GROUPS = [g for g, _, _ in reports.LIABILITY_GROUPS]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _out(d: Decimal) -> str:
    return reports._out(d)


class InviteRequest(BaseModel):
    pamphlet_id: str = Field(min_length=7, max_length=7)
    relation: str = Field(default="", max_length=40)


class AcceptRequest(BaseModel):
    share: Literal["total", "full"] = "total"


class NotionalMember(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    relation: str = Field(default="", max_length=40)


class ItemCreate(BaseModel):
    side: Literal["asset", "liability"]
    group: str
    name: str = Field(min_length=1, max_length=120)
    amount: Any
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")
    # {member id: percent}; one member at 100 for a single owner.
    shares: Dict[str, Any] = Field(min_length=1)


async def _my_household(db, user_id: str) -> Optional[dict]:
    me = await db.household_members.find_one({"user_id": user_id, "status": "active"}, {"_id": 0})
    if not me:
        return None
    return await db.households.find_one({"id": me["household_id"]}, {"_id": 0})


async def _require_household(db, user_id: str) -> dict:
    h = await _my_household(db, user_id)
    if not h:
        raise HTTPException(status_code=404, detail="Create your family first.")
    return h


@family_router.post("", status_code=201)
async def create_family(current_user: dict = Depends(get_current_user)):
    db = get_db()
    if await _my_household(db, current_user["id"]):
        raise HTTPException(status_code=409, detail="You're already in a family.")
    h = {"id": str(uuid.uuid4()), "owner_user_id": current_user["id"], "created_at": _now()}
    await db.households.insert_one(dict(h))
    await db.household_members.insert_one({
        "id": str(uuid.uuid4()), "household_id": h["id"], "kind": "user", "user_id": current_user["id"],
        "name": current_user.get("name") or "Me", "relation": "self", "status": "active", "share": "full",
        "created_at": _now()})
    h.pop("_id", None)
    return h


@family_router.get("")
async def get_family(current_user: dict = Depends(get_current_user)):
    db = get_db()
    h = await _my_household(db, current_user["id"])
    invites = await db.household_members.find(
        {"user_id": current_user["id"], "status": "invited"}, {"_id": 0}).to_list(length=None)
    members = await db.household_members.find(
        {"household_id": h["id"], "status": {"$in": ["active", "invited"]}}, {"_id": 0}).to_list(length=None) if h else []
    return {"family": h, "members": [{k: v for k, v in m.items() if k != "user_id"} for m in members],
            "invites_for_me": invites}


@family_router.post("/invite", status_code=201)
async def invite(body: InviteRequest, current_user: dict = Depends(get_current_user)):
    db = get_db()
    h = await _require_household(db, current_user["id"])
    target = await hymn_ids.resolve(db, body.pamphlet_id.upper())
    if not target:
        raise HTTPException(status_code=404, detail="No one has that Pamphlet ID.")
    if target == current_user["id"]:
        raise HTTPException(status_code=400, detail="That's your own ID.")
    if await db.household_members.find_one({"household_id": h["id"], "user_id": target,
                                            "status": {"$in": ["active", "invited"]}}):
        raise HTTPException(status_code=409, detail="Already in or invited to your family.")
    person = await db.users.find_one({"id": target}, {"_id": 0, "name": 1})
    m = {"id": str(uuid.uuid4()), "household_id": h["id"], "kind": "user", "user_id": target,
         "name": ((person or {}).get("name") or "").split(" ")[0], "relation": body.relation,
         "status": "invited", "share": None, "invited_by": current_user["id"], "created_at": _now()}
    await db.household_members.insert_one(dict(m))
    return {k: v for k, v in m.items() if k not in ("_id", "user_id")}


async def _my_invite(db, user_id: str, member_id: str) -> dict:
    m = await db.household_members.find_one({"id": member_id, "user_id": user_id, "status": "invited"}, {"_id": 0})
    if not m:
        raise HTTPException(status_code=404, detail="Invite not found")
    return m


@family_router.post("/invites/{member_id}/accept")
async def accept(member_id: str, body: AcceptRequest, current_user: dict = Depends(get_current_user)):
    db = get_db()
    m = await _my_invite(db, current_user["id"], member_id)
    if await _my_household(db, current_user["id"]):
        raise HTTPException(status_code=409, detail="Leave your current family first.")
    await db.household_members.update_one({"id": m["id"]}, {"$set": {"status": "active", "share": body.share,
                                                                    "joined_at": _now()}})
    return {"detail": "Joined", "share": body.share}


@family_router.post("/invites/{member_id}/decline")
async def decline(member_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    m = await _my_invite(db, current_user["id"], member_id)
    await db.household_members.update_one({"id": m["id"]}, {"$set": {"status": "declined"}})
    return {"detail": "Declined"}


@family_router.patch("/me")
async def change_sharing(body: AcceptRequest, current_user: dict = Depends(get_current_user)):
    db = get_db()
    r = await db.household_members.update_one({"user_id": current_user["id"], "status": "active"},
                                              {"$set": {"share": body.share}})
    if not r.matched_count:
        raise HTTPException(status_code=404, detail="You're not in a family.")
    return {"share": body.share}


@family_router.post("/leave")
async def leave(current_user: dict = Depends(get_current_user)):
    db = get_db()
    r = await db.household_members.update_one({"user_id": current_user["id"], "status": "active"},
                                              {"$set": {"status": "left", "left_at": _now()}})
    if not r.matched_count:
        raise HTTPException(status_code=404, detail="You're not in a family.")
    return {"detail": "Left"}


@family_router.post("/members", status_code=201)
async def add_notional(body: NotionalMember, current_user: dict = Depends(get_current_user)):
    db = get_db()
    h = await _require_household(db, current_user["id"])
    m = {"id": str(uuid.uuid4()), "household_id": h["id"], "kind": "notional", "user_id": None,
         "name": body.name.strip(), "relation": body.relation, "status": "active", "share": "full",
         "created_by": current_user["id"], "created_at": _now()}
    await db.household_members.insert_one(dict(m))
    return {k: v for k, v in m.items() if k not in ("_id", "user_id")}


@family_router.post("/items", status_code=201)
async def add_item(body: ItemCreate, current_user: dict = Depends(get_current_user)):
    db = get_db()
    h = await _require_household(db, current_user["id"])
    groups = ASSET_GROUPS if body.side == "asset" else LIABILITY_GROUPS
    if body.group not in groups:
        raise HTTPException(status_code=400, detail=f"group must be one of {', '.join(groups)}")
    try:
        amount = Decimal(str(body.amount))
        shares = {k: Decimal(str(v)) for k, v in body.shares.items()}
    except InvalidOperation:
        raise HTTPException(status_code=400, detail="Amounts and shares must be numbers.")
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be more than zero.")
    if sum(shares.values()) != 100 or any(v <= 0 for v in shares.values()):
        raise HTTPException(status_code=400, detail="Ownership shares must add up to 100.")
    members = {m["id"] for m in await db.household_members.find(
        {"household_id": h["id"], "status": "active"}, {"id": 1}).to_list(length=None)}
    if not set(shares) <= members:
        raise HTTPException(status_code=400, detail="Shares must name members of your family.")
    item = {"id": str(uuid.uuid4()), "household_id": h["id"], "side": body.side, "group": body.group,
            "name": body.name.strip(), "amount": str(amount), "currency": body.currency,
            "shares": {k: str(v) for k, v in shares.items()}, "created_by": current_user["id"], "created_at": _now()}
    await db.household_items.insert_one(dict(item))
    item.pop("_id", None)
    return item


@family_router.delete("/items/{item_id}")
async def delete_item(item_id: str, current_user: dict = Depends(get_current_user)):
    r = await get_db().household_items.delete_one({"id": item_id, "created_by": current_user["id"]})
    if not r.deleted_count:
        raise HTTPException(status_code=404, detail="Not found (only whoever added an entry can remove it).")
    return {"detail": "Deleted"}


@family_router.get("/net-worth")
async def family_net_worth(currency: str = "INR", as_of: Optional[str] = None,
                           current_user: dict = Depends(get_current_user)):
    """Family Statement of Net Worth: a column per person, a family total.
    People who share only their total show just that."""
    db = get_db()
    h = await _require_household(db, current_user["id"])
    day = reports._valid(as_of, "as_of") if as_of else date_type.today().isoformat()
    members = await db.household_members.find({"household_id": h["id"], "status": "active"},
                                              {"_id": 0}).to_list(length=None)
    items = await db.household_items.find({"household_id": h["id"], "currency": currency},
                                          {"_id": 0}).to_list(length=None)
    columns, family = [], {"assets": defaultdict(Decimal), "liabilities": defaultdict(Decimal)}
    family_assets = family_liabilities = ZERO
    for m in members:
        col = {"member_id": m["id"], "name": m["name"], "relation": m.get("relation", ""),
               "kind": m["kind"], "share": m["share"]}
        assets: Dict[str, Decimal] = defaultdict(Decimal)
        liabilities: Dict[str, Decimal] = defaultdict(Decimal)
        if m["kind"] == "user":
            own = await reports.net_worth_summary(db, m["user_id"], day, currency)
            for g, v in own["assets"].items():
                assets[g] += v
            for g, v in own["liabilities"].items():
                liabilities[g] += v
        for it in items:
            pct = Decimal(it["shares"].get(m["id"], "0"))
            if pct:
                part = Decimal(it["amount"]) * pct / 100
                (assets if it["side"] == "asset" else liabilities)[it["group"]] += part
        ta, tl = sum(assets.values(), ZERO), sum(liabilities.values(), ZERO)
        family_assets += ta
        family_liabilities += tl
        if m["share"] == "full":  # someone sharing only a total never shows up in the group lines
            for g, v in assets.items():
                family["assets"][g] += v
            for g, v in liabilities.items():
                family["liabilities"][g] += v
        col["net_worth"] = _out(ta - tl)
        if m["share"] == "full":
            col.update(total_assets=_out(ta), total_liabilities=_out(tl),
                       assets={g: _out(v) for g, v in assets.items() if v},
                       liabilities={g: _out(v) for g, v in liabilities.items() if v})
        columns.append(col)
    fa, fl = family_assets, family_liabilities
    return {"as_of": day, "currency": currency, "members": columns,
            "family": {"total_assets": _out(fa), "total_liabilities": _out(fl), "net_worth": _out(fa - fl),
                       # Group lines cover only members who share in full, so they can add up to
                       # less than the totals.
                       "assets": {g: _out(v) for g, v in family["assets"].items() if v},
                       "liabilities": {g: _out(v) for g, v in family["liabilities"].items() if v}},
            "notes": "Joint things are counted once, split by ownership share."}


async def ensure_family_indexes(db) -> None:
    await db.households.create_index("id", unique=True)
    await db.household_members.create_index([("household_id", 1), ("status", 1)])
    await db.household_members.create_index([("user_id", 1), ("status", 1)])
    await db.household_items.create_index([("household_id", 1), ("currency", 1)])
