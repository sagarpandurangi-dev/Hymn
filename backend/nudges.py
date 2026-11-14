"""Nudges: timely push notifications that adapt to the user.

Kinds
-----
* ``daily_review``    — "time for your 2-minute review". Sent once a day at
  the user's time, skipped if there is nothing to review or they already
  reviewed today, and never during quiet hours.
* ``reminder``        — an inbox reminder whose ``remind_at`` has arrived.
  The user picked that exact time, so quiet hours don't apply.
* ``weekly_patterns`` — the weekly analysis, generated on the user's day
  and time, with its summary as the message.

Learning
--------
With ``daily_review.adaptive`` on, the nudge moves to just before the time
the user actually tends to review: the median local time of their reviews
over the last 21 days, minus a small lead. It needs a few reviews before it
kicks in, and stays within a few hours of the time the user chose.
``GET /nudges/settings`` explains what was learned. Opens are recorded too.

Delivery
--------
Every nudge is stored in ``nudges`` (an in-app feed that works without a
phone build) under a unique ``(user_id, key)``, so a restart or a second
worker can't send it twice. Phones registered via ``POST /nudges/devices``
get it through Expo's push service.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import statistics
import uuid
from datetime import datetime, time, timedelta, timezone
from typing import List, Literal, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

import inbox
from deps import get_current_user, get_db

logger = logging.getLogger(__name__)

nudges_router = APIRouter(prefix="/nudges", tags=["nudges"])

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
TICK_SECONDS = 60
# A nudge whose time passed while the server was down is still sent within
# this window; after that it is skipped rather than arriving late.
CATCH_UP = timedelta(hours=2)
# Learning: reviews considered, minimum needed, lead before the usual time,
# and how far the learned time may drift from the user's chosen time.
LEARN_WINDOW = timedelta(days=21)
LEARN_MIN_REVIEWS = 5
LEARN_LEAD_MINUTES = 10
LEARN_MAX_SHIFT_MINUTES = 180

DEFAULT_SETTINGS = {
    "daily_review": {"enabled": True, "time": "20:30", "adaptive": True},
    "weekly_patterns": {"enabled": True, "weekday": 6, "time": "18:00"},  # Sunday
    "reminders": {"enabled": True},
    "quiet_hours": {"start": "22:00", "end": "07:00"},
}

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def hhmm_to_minute(value: str) -> int:
    return int(value[:2]) * 60 + int(value[3:])


def minute_to_hhmm(minute: int) -> str:
    minute %= 1440
    return f"{minute // 60:02d}:{minute % 60:02d}"


def in_quiet_hours(minute: int, start: str, end: str) -> bool:
    s, e = hhmm_to_minute(start), hhmm_to_minute(end)
    if s == e:
        return False
    if s < e:
        return s <= minute < e
    return minute >= s or minute < e


def learned_review_minute(review_minutes: List[int], preferred: int) -> Optional[int]:
    """Just before the user's usual review time, kept near their choice."""
    if len(review_minutes) < LEARN_MIN_REVIEWS:
        return None
    target = int(statistics.median(review_minutes)) - LEARN_LEAD_MINUTES
    low, high = preferred - LEARN_MAX_SHIFT_MINUTES, preferred + LEARN_MAX_SHIFT_MINUTES
    return max(low, min(high, target)) % 1440


def merge_settings(stored: Optional[dict]) -> dict:
    merged = {k: dict(v) for k, v in DEFAULT_SETTINGS.items()}
    for section, values in (stored or {}).items():
        if section in merged and isinstance(values, dict):
            merged[section].update(values)
    return merged


def _tz(name: Optional[str]) -> ZoneInfo:
    try:
        return ZoneInfo(name) if name else ZoneInfo("UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Learning
# ---------------------------------------------------------------------------

async def _review_minutes(db, user_id: str, tz: ZoneInfo, now: datetime) -> List[int]:
    since = (now - LEARN_WINDOW).isoformat()
    reviews = await db.inbox_reviews.find(
        {"user_id": user_id, "created_at": {"$gte": since}}, {"_id": 0, "created_at": 1},
    ).to_list(length=500)
    minutes = []
    for r in reviews:
        try:
            local = datetime.fromisoformat(r["created_at"]).astimezone(tz)
        except (KeyError, TypeError, ValueError):
            continue
        minutes.append(local.hour * 60 + local.minute)
    return minutes


async def review_plan(db, user: dict, settings: dict, now: datetime) -> dict:
    """When today's review nudge is due, and why."""
    tz = _tz(user.get("timezone"))
    daily = settings["daily_review"]
    preferred = hhmm_to_minute(daily["time"])
    minutes = await _review_minutes(db, user["id"], tz, now)
    learned = learned_review_minute(minutes, preferred) if daily.get("adaptive") else None
    quiet = settings["quiet_hours"]
    use_learned = learned is not None and not in_quiet_hours(learned, quiet["start"], quiet["end"])
    minute = learned if use_learned else preferred
    if use_learned:
        usual = minute_to_hhmm(int(statistics.median(minutes)))
        explanation = (
            f"You usually review around {usual}, so Hymn nudges you at {minute_to_hhmm(minute)}."
        )
    elif daily.get("adaptive"):
        explanation = (
            f"Hymn nudges you at {daily['time']} and will adjust once it has seen "
            f"{LEARN_MIN_REVIEWS} reviews (so far {len(minutes)})."
        )
    else:
        explanation = f"Hymn nudges you at {daily['time']}, as you set."
    return {
        "minute": minute,
        "time": minute_to_hhmm(minute),
        "learned": use_learned,
        "reviews_considered": len(minutes),
        "explanation": explanation,
    }


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------

def send_expo_messages(messages: List[dict]) -> List[dict]:
    """POST to Expo's push service; returns one ticket per message."""
    response = requests.post(EXPO_PUSH_URL, json=messages, timeout=20)
    response.raise_for_status()
    return response.json().get("data") or []


async def _deliver(db, nudge: dict) -> None:
    tokens = await db.push_tokens.find(
        {"user_id": nudge["user_id"]}, {"_id": 0, "token": 1},
    ).to_list(length=20)
    if not tokens:
        logger.info("nudge %s: no registered device; kept in the in-app feed", nudge["id"])
        await db.nudges.update_one({"id": nudge["id"]}, {"$set": {"status": "no_device"}})
        return
    messages = [
        {"to": t["token"], "title": nudge["title"], "body": nudge["body"],
         "data": nudge["data"], "sound": "default"}
        for t in tokens
    ]
    try:
        tickets = await asyncio.to_thread(send_expo_messages, messages)
    except (requests.RequestException, ValueError) as exc:
        logger.warning("nudge %s: push failed: %s", nudge["id"], exc)
        await db.nudges.update_one(
            {"id": nudge["id"]}, {"$set": {"status": "failed", "error": str(exc)[:300]}},
        )
        return
    delivered = 0
    for token, ticket in zip(tokens, tickets):
        if ticket.get("status") == "ok":
            delivered += 1
        elif (ticket.get("details") or {}).get("error") == "DeviceNotRegistered":
            await db.push_tokens.delete_one({"token": token["token"]})
    status = "sent" if delivered else "failed"
    logger.info("nudge %s: %s to %d of %d devices", nudge["id"], status, delivered, len(tokens))
    await db.nudges.update_one(
        {"id": nudge["id"]},
        {"$set": {"status": status, "sent_at": _now().isoformat()}},
    )


async def _claim(db, user_id: str, kind: str, key: str, title: str, body: str,
                 data: dict, scheduled_for: datetime) -> Optional[dict]:
    """Store the nudge once per key; None if it already exists."""
    nudge = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "kind": kind,
        "key": key,
        "title": title,
        "body": body,
        "data": data,
        "scheduled_for": scheduled_for.isoformat(),
        "status": "pending",
        "sent_at": None,
        "opened_at": None,
        "error": None,
        "created_at": _now().isoformat(),
    }
    try:
        await db.nudges.insert_one(nudge)
    except DuplicateKeyError:
        return None
    nudge.pop("_id", None)
    logger.info("nudge created: %s for user %s (%s)", kind, user_id, key)
    return nudge


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

def _due(local: datetime, minute: int) -> Optional[datetime]:
    """Today's local occurrence of ``minute`` if it passed within CATCH_UP."""
    at = datetime.combine(local.date(), time(minute // 60, minute % 60), tzinfo=local.tzinfo)
    if at <= local <= at + CATCH_UP:
        return at
    return None


async def _daily_review(db, user: dict, settings: dict, now: datetime) -> Optional[dict]:
    if not settings["daily_review"]["enabled"]:
        return None
    tz = _tz(user.get("timezone"))
    local = now.astimezone(tz)
    quiet = settings["quiet_hours"]
    if in_quiet_hours(local.hour * 60 + local.minute, quiet["start"], quiet["end"]):
        return None
    plan = await review_plan(db, user, settings, now)
    at = _due(local, plan["minute"])
    if at is None:
        return None
    midnight = datetime.combine(local.date(), time(0), tzinfo=tz).astimezone(timezone.utc)
    if await db.inbox_reviews.count_documents(
        {"user_id": user["id"], "created_at": {"$gte": midnight.isoformat()}},
    ):
        return None
    open_items = await db.inbox_items.count_documents({"user_id": user["id"], "status": "open"})
    if not open_items:
        return None
    noun = "thing" if open_items == 1 else "things"
    return await _claim(
        db, user["id"], "daily_review", f"daily_review:{local.date().isoformat()}",
        "Time for your 2-minute review", f"{open_items} {noun} waiting in your inbox.",
        {"screen": "inbox/review"}, at,
    )


async def _reminders(db, user: dict, settings: dict, now: datetime) -> List[dict]:
    if not settings["reminders"]["enabled"]:
        return []
    due = await db.inbox_items.find(
        {
            "user_id": user["id"],
            "status": "open",
            "category": "reminder",
            "remind_at": {"$gte": (now - CATCH_UP).isoformat(), "$lte": now.isoformat()},
        },
        {"_id": 0},
    ).to_list(length=50)
    claimed = []
    for item in due:
        nudge = await _claim(
            db, user["id"], "reminder", f"reminder:{item['id']}:{item['remind_at']}",
            "Reminder", item["text"], {"screen": "inbox/review", "item_id": item["id"]},
            datetime.fromisoformat(item["remind_at"]),
        )
        if nudge:
            claimed.append(nudge)
    return claimed


async def _weekly_patterns(db, user: dict, settings: dict, now: datetime) -> Optional[dict]:
    weekly = settings["weekly_patterns"]
    if not weekly["enabled"]:
        return None
    tz = _tz(user.get("timezone"))
    local = now.astimezone(tz)
    if local.weekday() != weekly["weekday"]:
        return None
    quiet = settings["quiet_hours"]
    if in_quiet_hours(local.hour * 60 + local.minute, quiet["start"], quiet["end"]):
        return None
    at = _due(local, hhmm_to_minute(weekly["time"]))
    if at is None:
        return None
    year, week, _ = local.isocalendar()
    nudge = await _claim(
        db, user["id"], "weekly_patterns", f"weekly_patterns:{year}-W{week:02d}",
        "Your week in Hymn", "", {"screen": "inbox/patterns"}, at,
    )
    if nudge is None:
        return None
    insight = await inbox.create_weekly_insight(db, user["id"])
    summary = (insight.get("insight") or {}).get("summary")
    captured = insight["stats"]["captured"]
    body = summary or f"You captured {captured} thing{'s' if captured != 1 else ''} this week."
    await db.nudges.update_one({"id": nudge["id"]}, {"$set": {"body": body}})
    nudge["body"] = body
    return nudge


PLAN_CHECK_TIME = "10:00"  # on the 1st of each month, local time


async def _plan_check(db, user: dict, settings: dict, now: datetime) -> Optional[dict]:
    """Once a month: tell the person if an accepted plan has slipped (something
    that was on track is now short)."""
    import life_plans

    tz = _tz(user.get("timezone"))
    local = now.astimezone(tz)
    if local.day != 1:
        return None
    at = _due(local, hhmm_to_minute(PLAN_CHECK_TIME))
    if at is None:
        return None
    plans = await db.life_plans.find({"user_id": user["id"], "status": "active",
                                      "accepted_statuses": {"$exists": True}}, {"_id": 0}).to_list(length=None)
    for plan in plans:
        evaluated = await life_plans.benchmark(db, user["id"], plan, local.date(), local.replace(tzinfo=None))
        if not evaluated["drift"]:
            continue
        first = evaluated["drift"][0]
        gap = f" — short by ₹{float(first['gap']):,.0f}" if first.get("gap") not in (None, "0", 0) else ""
        body = f"{first['what']} has slipped{gap}. Open the plan to see your options."
        return await _claim(db, user["id"], "plan_drift", f"plan_drift:{plan['id']}:{local.strftime('%Y-%m')}",
                            f"{plan['title']} needs attention", body,
                            {"screen": "plans", "plan_id": plan["id"]}, at)
    return None


async def run_due_nudges(db, now: Optional[datetime] = None) -> List[dict]:
    """One scheduler tick: create and deliver every nudge that is due."""
    now = now or _now()
    sent: List[dict] = []
    users = await db.users.find({}, {"_id": 0, "id": 1, "timezone": 1}).to_list(length=10000)
    for user in users:
        try:
            stored = await db.nudge_settings.find_one({"user_id": user["id"]}, {"_id": 0})
            settings = merge_settings(stored)
            due = await _reminders(db, user, settings, now)
            for job in (_daily_review, _weekly_patterns, _plan_check):
                nudge = await job(db, user, settings, now)
                if nudge:
                    due.append(nudge)
            for nudge in due:
                await _deliver(db, nudge)
            sent.extend(due)
        except Exception:  # one user's failure must not stop the others
            logger.exception("nudges: tick failed for user %s", user.get("id"))
    return sent


async def nudge_loop() -> None:
    while True:
        try:
            await run_due_nudges(get_db())
        except Exception:
            logger.exception("nudges: tick failed")
        await asyncio.sleep(TICK_SECONDS)


def loop_enabled() -> bool:
    return os.environ.get("HYMN_NUDGES", "on").lower() != "off"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

class DailyReviewSettings(BaseModel):
    enabled: Optional[bool] = None
    time: Optional[str] = None
    adaptive: Optional[bool] = None


class WeeklySettings(BaseModel):
    enabled: Optional[bool] = None
    weekday: Optional[int] = Field(default=None, ge=0, le=6)  # 0 = Monday
    time: Optional[str] = None


class ReminderSettings(BaseModel):
    enabled: Optional[bool] = None


class QuietHours(BaseModel):
    start: Optional[str] = None
    end: Optional[str] = None


class SettingsUpdate(BaseModel):
    daily_review: Optional[DailyReviewSettings] = None
    weekly_patterns: Optional[WeeklySettings] = None
    reminders: Optional[ReminderSettings] = None
    quiet_hours: Optional[QuietHours] = None
    timezone: Optional[str] = None


class DeviceRegister(BaseModel):
    token: str = Field(min_length=10, max_length=300)
    platform: Literal["ios", "android", "web"] = "android"


async def _settings_response(db, user: dict) -> dict:
    stored = await db.nudge_settings.find_one({"user_id": user["id"]}, {"_id": 0})
    settings = merge_settings(stored)
    return {
        "settings": settings,
        "timezone": user.get("timezone") or "UTC",
        "daily_review_plan": await review_plan(db, user, settings, _now()),
        "devices": await db.push_tokens.count_documents({"user_id": user["id"]}),
    }


@nudges_router.get("/settings")
async def get_settings(current_user: dict = Depends(get_current_user)):
    return await _settings_response(get_db(), current_user)


@nudges_router.put("/settings")
async def update_settings(body: SettingsUpdate, current_user: dict = Depends(get_current_user)):
    db = get_db()
    updates: dict = {}
    for section in ("daily_review", "weekly_patterns", "reminders", "quiet_hours"):
        values = getattr(body, section)
        if values is None:
            continue
        for field, value in values.model_dump(exclude_none=True).items():
            if field in ("time", "start", "end") and not _HHMM.match(value):
                raise HTTPException(status_code=400, detail=f"{section}.{field} must be HH:MM")
            updates[f"{section}.{field}"] = value
    user = current_user
    if body.timezone:
        try:
            ZoneInfo(body.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise HTTPException(status_code=400, detail=f"Unknown timezone {body.timezone!r}")
        await db.users.update_one({"id": user["id"]}, {"$set": {"timezone": body.timezone}})
        user = {**user, "timezone": body.timezone}
    if updates:
        updates["updated_at"] = _now().isoformat()
        await db.nudge_settings.update_one(
            {"user_id": user["id"]}, {"$set": updates}, upsert=True,
        )
    return await _settings_response(db, user)


@nudges_router.post("/devices", status_code=201)
async def register_device(body: DeviceRegister, current_user: dict = Depends(get_current_user)):
    now = _now().isoformat()
    # A token belongs to one phone; if another account logs in on it, move it.
    await get_db().push_tokens.update_one(
        {"token": body.token},
        {"$set": {"user_id": current_user["id"], "platform": body.platform, "last_seen_at": now},
         "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    return {"detail": "Device registered"}


@nudges_router.delete("/devices")
async def unregister_device(token: str = Query(min_length=10),
                            current_user: dict = Depends(get_current_user)):
    await get_db().push_tokens.delete_one({"token": token, "user_id": current_user["id"]})
    return {"detail": "Device removed"}


@nudges_router.get("")
async def list_nudges(limit: int = Query(default=20, ge=1, le=100),
                      current_user: dict = Depends(get_current_user)):
    return await get_db().nudges.find(
        {"user_id": current_user["id"]}, {"_id": 0},
    ).sort("created_at", -1).limit(limit).to_list(length=limit)


@nudges_router.post("/{nudge_id}/opened")
async def mark_opened(nudge_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    result = await db.nudges.update_one(
        {"id": nudge_id, "user_id": current_user["id"], "opened_at": None},
        {"$set": {"opened_at": _now().isoformat()}},
    )
    if result.matched_count == 0 and not await db.nudges.find_one(
        {"id": nudge_id, "user_id": current_user["id"]},
    ):
        raise HTTPException(status_code=404, detail="Nudge not found")
    return {"detail": "Recorded"}


async def ensure_nudge_indexes(db) -> None:
    await db.nudges.create_index([("user_id", 1), ("key", 1)], unique=True)
    await db.nudges.create_index([("user_id", 1), ("created_at", -1)])
    await db.push_tokens.create_index("token", unique=True)
    await db.push_tokens.create_index("user_id")
    await db.nudge_settings.create_index("user_id", unique=True)
