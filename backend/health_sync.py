"""Watch and phone sync: any watch, any phone, or none.

The phone app reads the phone's health hub and sends the numbers here:

* Android: Health Connect, which Samsung Health, Google Fit, Fitbit and many
  other watch and band apps write into;
* iPhone: Apple Health (Apple Watch and the apps that write into it);
* no watch: the phone's own step counter through the same hub, or the
  30-second daily log by hand.

Hymn doesn't care which brand: every reading is stored with source "watch"
and the app it came from. Re-syncing a day replaces that day's value, and
what the person typed for a day wins over the watch (``health.one_per_day``).
"""
from __future__ import annotations

import re
from datetime import date as date_type, datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from deps import get_current_user, get_db
from health import METRICS, _d, _profile, _store

sync_router = APIRouter(prefix="/health", tags=["health"])

SYNCABLE = ("steps", "active_minutes", "sleep_hours", "resting_hr", "weight_kg", "vo2max", "bp_systolic",
            "bp_diastolic")
HUBS = [
    {"phone": "Android", "hub": "Health Connect",
     "works_with": "Samsung Health, Google Fit, Fitbit and many other watch and band apps that share with "
                   "Health Connect"},
    {"phone": "iPhone", "hub": "Apple Health", "works_with": "Apple Watch and apps that share with Apple Health"},
    {"phone": "Any", "hub": "No watch", "works_with": "Your phone's step counter, or the 30-second daily log"},
]


class Reading(BaseModel):
    metric: str
    value: float
    date: str                                   # the person's local day, YYYY-MM-DD
    unit: Optional[str] = None                  # "lb" for weight is converted; minutes for sleep too


class SyncBody(BaseModel):
    source_app: str = Field(min_length=1, max_length=40)    # "Samsung Health", "Fitbit", "Apple Health"…
    device: str = Field(default="", max_length=60)
    readings: List[Reading] = Field(max_length=2000)


def _convert(r: Reading) -> Optional[Decimal]:
    v = _d(r.value)
    if v is None:
        return None
    unit = (r.unit or "").lower()
    if r.metric == "weight_kg" and unit in ("lb", "lbs", "pound", "pounds"):
        v = v * Decimal("0.45359237")
    if r.metric == "sleep_hours" and unit in ("min", "mins", "minutes"):
        v = v / 60
    return v.quantize(Decimal("0.01"))


@sync_router.post("/sync")
async def sync(body: SyncBody, current_user: dict = Depends(get_current_user)):
    """Store readings from the phone's health hub. Bad or out-of-range
    readings are skipped (and counted), never fail the whole batch."""
    db = get_db()
    uid = current_user["id"]
    await _profile(db, uid)
    today = date_type.today()
    keep, skipped = {}, 0
    for r in body.readings:
        try:
            day = date_type.fromisoformat(r.date[:10])
        except ValueError:
            skipped += 1
            continue
        v = _convert(r)
        spec = METRICS.get(r.metric)
        if (r.metric not in SYNCABLE or v is None or not (spec[2] <= v <= spec[3])
                or day > today + timedelta(days=1) or day < today - timedelta(days=400)):
            skipped += 1
            continue
        keep[(r.metric, day.isoformat())] = v           # the last reading for a day wins
    note = f"{body.source_app}{' · ' + body.device if body.device else ''}"
    for (metric, day), _v in keep.items():
        await db.health_measurements.delete_many({"user_id": uid, "metric": metric, "taken_on": day,
                                                  "source": "watch", "note": _from_app(body.source_app)})
    await _store(db, uid, [{"metric": m, "value": float(v), "taken_on": d, "source": "watch", "note": note}
                           for (m, d), v in keep.items()])
    now = datetime.now(timezone.utc).isoformat()
    await db.health_sync_sources.update_one(
        {"user_id": uid, "source_app": body.source_app},
        {"$set": {"device": body.device, "last_sync": now}, "$inc": {"readings": len(keep)}}, upsert=True)
    return {"saved": len(keep), "skipped": skipped, "last_sync": now}


@sync_router.get("/sync")
async def sync_status(current_user: dict = Depends(get_current_user)):
    sources = await get_db().health_sync_sources.find({"user_id": current_user["id"]},
                                                      {"_id": 0, "user_id": 0}).to_list(length=50)
    return {"sources": sources, "metrics": list(SYNCABLE), "hubs": HUBS,
            "note": "Any watch or band that shares with your phone's health app works. No watch? Your phone's "
                    "step counter or the daily log is enough."}


class Disconnect(BaseModel):
    source_app: str
    delete_data: bool = False


@sync_router.post("/sync/disconnect")
async def disconnect(body: Disconnect, current_user: dict = Depends(get_current_user)):
    db = get_db()
    uid = current_user["id"]
    await db.health_sync_sources.delete_one({"user_id": uid, "source_app": body.source_app})
    removed = 0
    if body.delete_data:
        r = await db.health_measurements.delete_many({"user_id": uid, "source": "watch",
                                                      "note": _from_app(body.source_app)})
        removed = r.deleted_count
    return {"detail": "Disconnected", "readings_deleted": removed}


def _from_app(app: str) -> dict:
    """Readings from this app, whichever device sent them."""
    return {"$regex": f"^{re.escape(app)}( · |$)"}
