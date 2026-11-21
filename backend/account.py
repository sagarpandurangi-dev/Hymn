"""Your account and your data: a first-time setup checklist, a full export,
and deleting the account.

* ``GET /api/account/setup`` — what's set up across the five areas and the
  one next step, for a new person (and for the Me screen later).
* ``GET /api/account/export`` — everything Hymn holds for you as one JSON
  file (password and security-answer hashes, push tokens and uploaded
  files' raw bytes left out).
* ``DELETE /api/account`` — with your password: deletes every record of
  yours, the people you look after and their health data, your family
  membership (a household you own goes with it if you're its only member
  with an account), and signs out every device. Your Pamphlet ID is retired,
  never given to someone else.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson.decimal128 import Decimal128
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from deps import get_current_user, get_db

account_router = APIRouter(prefix="/account", tags=["account"])

# Collections that are not the person's own records.
SHARED = {"users", "hymn_ids", "households", "household_members", "household_items", "auth_attempts",
          "care_profiles"}
EXPORT_SKIP = {"push_tokens", "user_sessions", "auth_attempts", "ai_usage", "statement_files"}
SECRET_FIELDS = {"hashed_password", "hashed_security_answer", "_id"}


def _plain(v: Any) -> Any:
    if isinstance(v, Decimal128):
        return str(v.to_decimal())
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, bytes):
        return f"<{len(v)} bytes>"
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items() if k not in SECRET_FIELDS}
    if isinstance(v, list):
        return [_plain(x) for x in v]
    return v


async def _care_ids(db, uid: str) -> list:
    return [c["id"] async for c in db.care_profiles.find({"owner_id": uid}, {"_id": 0, "id": 1})]


@account_router.get("/export")
async def export(current_user: dict = Depends(get_current_user)):
    db = get_db()
    uid = current_user["id"]
    ids = [uid] + await _care_ids(db, uid)
    out = {"exported_at": datetime.now(timezone.utc).isoformat(), "account": _plain(dict(current_user)), "data": {}}
    for name in sorted(await db.list_collection_names()):
        if name in SHARED or name in EXPORT_SKIP:
            continue
        rows = await db[name].find({"user_id": {"$in": ids}}).to_list(length=None)
        if rows:
            out["data"][name] = _plain(rows)
    out["data"]["care_profiles"] = _plain(await db.care_profiles.find({"owner_id": uid}).to_list(length=None))
    out["data"]["family_membership"] = _plain(await db.household_members.find({"user_id": uid}).to_list(length=None))
    out["data"]["family_items_you_added"] = _plain(await db.household_items.find({"created_by": uid})
                                                   .to_list(length=None))
    return out


class DeleteAccount(BaseModel):
    password: str = Field(min_length=1, max_length=200)
    confirm: str                                   # must be the word DELETE


@account_router.delete("")
async def delete_account(body: DeleteAccount, current_user: dict = Depends(get_current_user)):
    from server import verify_password

    db = get_db()
    if body.confirm != "DELETE":
        raise HTTPException(status_code=400, detail='Type DELETE to confirm.')
    hashed = current_user.get("hashed_password")
    if not isinstance(hashed, str) or not verify_password(body.password, hashed):
        raise HTTPException(status_code=400, detail="That password isn't right.")
    removed = await erase_user(db, current_user)
    return {"detail": "Your account and data have been deleted.", "records_removed": removed}


async def erase_user(db, current_user: dict) -> int:
    """Delete everything a person has (also used by the admin page for test accounts)."""
    uid = current_user["id"]
    import billing
    if billing.razorpay_ready():
        await billing.cancel_on_delete(db, uid)
    ids = [uid] + await _care_ids(db, uid)
    removed = 0
    for name in await db.list_collection_names():
        if name in SHARED:
            continue
        removed += (await db[name].delete_many({"user_id": {"$in": ids}})).deleted_count
    await db.care_profiles.delete_many({"owner_id": uid})
    # Family: leave; a household with no other account holders goes too.
    mine = await db.household_members.find({"user_id": uid}, {"_id": 0}).to_list(length=None)
    for m in mine:
        hid = m["household_id"]
        await db.household_members.delete_one({"id": m["id"]})
        others = await db.household_members.count_documents({"household_id": hid, "user_id": {"$nin": [None, uid]},
                                                             "status": "active"})
        if not others:
            await db.household_members.delete_many({"household_id": hid})
            await db.household_items.delete_many({"household_id": hid})
            await db.households.delete_one({"id": hid})
        else:
            await db.household_members.delete_many({"household_id": hid, "created_by": uid, "user_id": None})
            await db.household_items.delete_many({"household_id": hid, "created_by": uid})
    # The Pamphlet ID is retired, never reissued.
    await db.hymn_ids.update_many({"owner_user_id": uid}, {"$set": {"owner_user_id": None, "status": "retired"}})
    await db.auth_attempts.delete_many({"subject": f"email:{current_user.get('email', '')}"})
    await db.invites.delete_many({"created_by": uid})
    await db.users.delete_one({"id": uid})
    return removed


# ---------------------------------------------------------------------------
# First-time setup
# ---------------------------------------------------------------------------

@account_router.get("/setup")
async def setup(current_user: dict = Depends(get_current_user)):
    db = get_db()
    uid = current_user["id"]

    async def has(coll: str, extra: dict | None = None) -> bool:
        return bool(await db[coll].find_one({"user_id": uid, **(extra or {})}, {"_id": 1}))

    steps = [
        {"key": "timezone", "area": "you", "title": "Set your time zone",
         "why": "So reminders arrive at the right time.", "screen": "settings",
         "done": bool(current_user.get("timezone"))},
        {"key": "accounts", "area": "money", "title": "Add your bank account and cards",
         "why": "The starting point for your money book.", "screen": "portfolio/setup",
         "done": await has("financial_accounts")},
        {"key": "time", "area": "work", "title": "Add your work hours and sleep",
         "why": "So Hymn knows your real free time.", "screen": "work",
         "done": await has("work_roles") or await has("time_commitments")},
        {"key": "people", "area": "family", "title": "Add the people who matter most",
         "why": "Birthdays, and a nudge when it's been a while.", "screen": "people", "done": await has("people")},
        {"key": "first_plan", "area": "plans", "title": "Tell Hymn one thing you want",
         "why": "Hymn checks it against your real time and money.", "screen": "plan-chat",
         "done": await has("life_plans") or await has("learning_journeys") or await has("goals")},
        {"key": "health", "area": "health", "title": "Switch on Health (optional)",
         "why": "A 30-second daily log; you can delete it all any time.", "screen": "health", "optional": True,
         "done": await has("health_profiles", {"consent": True})},
        {"key": "brain_dump", "area": "you", "title": "Empty your head once",
         "why": "Type everything on your mind; Hymn sorts it.", "screen": "inbox/dump",
         "done": await has("inbox_dumps")},
    ]
    required = [s for s in steps if not s.get("optional")]
    done = sum(1 for s in required if s["done"])
    nxt = next((s for s in steps if not s["done"] and not s.get("optional")), None)
    return {"steps": steps, "done": done, "of": len(required), "complete": done == len(required),
            "next": nxt, "money_book_switched": bool(await db.ledger_transactions.find_one(
                {"user_id": uid, "provenance": "conversion"}, {"_id": 1}))}
