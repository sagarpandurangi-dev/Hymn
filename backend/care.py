"""Caregiver mode: look after the health of someone else — a parent, a child,
a grandparent — from your own account.

A care profile is a person you look after. Every Health screen works for
them by adding ``?for=<care id>`` (profile, daily log, readings, dashboard,
suggestions, check-ups, lab reports, 90-day progress, doctor summary), and
their check-ups and reports nudge you. Only you can see or change it.

You confirm they know and agree (or that you are their guardian) before
anything is stored. Removing a care profile deletes all of their data.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from deps import get_current_user, get_db

care_router = APIRouter(prefix="/care", tags=["health"])

MAX_PEOPLE = 10
HEALTH_COLLECTIONS = ("health_measurements", "health_profiles", "health_symptoms", "health_lab_reports",
                      "health_checkups")


class CareCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    relation: Literal["mother", "father", "parent_in_law", "grandparent", "spouse", "child", "sibling", "other"]
    # They know and agree, or you are their parent/guardian.
    their_consent: bool


@care_router.post("", status_code=201)
async def add_person(body: CareCreate, current_user: dict = Depends(get_current_user)):
    db = get_db()
    if not body.their_consent:
        raise HTTPException(status_code=400, detail="Please confirm they know and agree, or that you are their "
                                                    "guardian.")
    if await db.care_profiles.count_documents({"owner_id": current_user["id"]}) >= MAX_PEOPLE:
        raise HTTPException(status_code=400, detail=f"You can look after up to {MAX_PEOPLE} people.")
    doc = {"id": f"care_{uuid.uuid4().hex}", "owner_id": current_user["id"], "name": body.name.strip(),
           "relation": body.relation, "consent_confirmed_at": datetime.now(timezone.utc).isoformat()}
    await db.care_profiles.insert_one(dict(doc))
    doc.pop("owner_id")
    return {**doc, "next": "Fill in their health profile: PUT /api/health/profile?for=" + doc["id"]}


@care_router.get("")
async def list_people(current_user: dict = Depends(get_current_user)):
    """People you look after, each with what needs attention."""
    from health_checkups import _calendar

    db = get_db()
    out = []
    async for cp in db.care_profiles.find({"owner_id": current_user["id"]}, {"_id": 0, "owner_id": 0}):
        item = {**cp, "profile_done": False, "checkups_due": 0, "last_reading": None}
        if await db.health_profiles.find_one({"user_id": cp["id"], "consent": True}, {"_id": 1}):
            item["profile_done"] = True
            cal = await _calendar(db, {"id": cp["id"], "name": cp["name"]})
            item["checkups_due"] = sum(1 for c in cal["checks"] if c["status"] in ("overdue", "never", "due_soon"))
            last = await db.health_measurements.find({"user_id": cp["id"]}, {"_id": 0, "taken_on": 1}) \
                .sort("taken_on", -1).to_list(length=1)
            item["last_reading"] = last[0]["taken_on"] if last else None
        out.append(item)
    return out


class CareRename(BaseModel):
    name: str = Field(min_length=1, max_length=60)


@care_router.patch("/{care_id}")
async def rename(care_id: str, body: CareRename, current_user: dict = Depends(get_current_user)):
    r = await get_db().care_profiles.update_one({"id": care_id, "owner_id": current_user["id"]},
                                                {"$set": {"name": body.name.strip()}})
    if not r.matched_count:
        raise HTTPException(status_code=404, detail="Person not found")
    return {"detail": "Saved"}


@care_router.delete("/{care_id}")
async def remove_person(care_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    r = await db.care_profiles.delete_one({"id": care_id, "owner_id": current_user["id"]})
    if not r.deleted_count:
        raise HTTPException(status_code=404, detail="Person not found")
    for coll in HEALTH_COLLECTIONS:
        await db[coll].delete_many({"user_id": care_id})
    await db.nudges.delete_many({"user_id": current_user["id"], "data.for": care_id})
    return {"detail": "Removed, with all of their health data."}


async def ensure_care_indexes(db) -> None:
    await db.care_profiles.create_index("id", unique=True)
    await db.care_profiles.create_index("owner_id")
