"""Health nudges: gentle, rare, never guilt.

At the person's health time (default 09:30 local), at most **one** health
nudge a day for them and one for each person they look after, the first
that applies of:

1. the 90-day report is ready (once per 90-day run);
2. a check-up is overdue or due within 30 days (once per check per due
   date, and at most one check-up nudge a week per person);
3. (themselves only) they've logged before but not for 3 days — "no catching
   up needed" (at most once a week).

Plus, for habits with urges logged at a regular time (3+ in the last 21
days), a short check-in with their own reason 15 minutes before that time.

Nothing is sent during quiet hours, and nothing without the health consent.
"""
from __future__ import annotations

import statistics
from datetime import datetime, time, timedelta, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo

HEALTH_KINDS = ("health_report", "health_checkup", "health_log")
LOG_GAP_DAYS = 3
CHECKUP_GAP_DAYS = 7
LOG_REMINDER_GAP_DAYS = 7
URGE_WINDOW_DAYS = 21
URGE_MIN = 3
URGE_LEAD_MINUTES = 15
URGE_SEND_WINDOW = timedelta(minutes=30)


def usual_urge_minute(times: List[str], tz: ZoneInfo, now: datetime) -> Optional[int]:
    """Median local minute of the day of recent urges, if there are enough."""
    since = now - timedelta(days=URGE_WINDOW_DAYS)
    minutes = []
    for t in times:
        try:
            at = datetime.fromisoformat(t)
        except ValueError:
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        if at >= since:
            local = at.astimezone(tz)
            minutes.append(local.hour * 60 + local.minute)
    if len(minutes) < URGE_MIN:
        return None
    return int(statistics.median(minutes))


async def _recent(db, user_id: str, kind: str, for_id: Optional[str], since: datetime) -> bool:
    return bool(await db.nudges.find_one({"user_id": user_id, "kind": kind, "data.for": for_id,
                                          "created_at": {"$gte": since.isoformat()}}, {"_id": 1}))


async def _for_person(db, user: dict, who: dict, local: datetime, at: datetime) -> Optional[dict]:
    from health_checkups import _calendar
    from nudges import _claim

    uid, pid = user["id"], who["id"]
    for_id = None if who["self"] else pid
    if not await db.health_profiles.find_one({"user_id": pid, "consent": True}, {"_id": 1}):
        return None
    # One health nudge a day per person.
    if await db.nudges.find_one({"user_id": uid, "kind": {"$in": list(HEALTH_KINDS)}, "data.for": for_id,
                                 "scheduled_for": at.isoformat()}, {"_id": 1}):
        return None
    today = local.date()
    now_utc = local.astimezone(timezone.utc)
    whose = "Your" if who["self"] else f"{who['name']}'s"
    data = {"screen": "health", "for": for_id}
    first = await db.health_measurements.find({"user_id": pid}, {"_id": 0, "taken_on": 1}) \
        .sort("taken_on", 1).to_list(length=1)
    if first:
        start = first[0]["taken_on"][:10]
        if (today - datetime.fromisoformat(start).date()).days >= 89:
            n = await _claim(db, uid, "health_report", f"health_report:{pid}:{start}",
                             f"{whose} 90-day health report is ready",
                             "See what changed since the first month.", {**data, "screen": "health/progress"}, at)
            if n:
                return n
    if not await _recent(db, uid, "health_checkup", for_id, now_utc - timedelta(days=CHECKUP_GAP_DAYS)):
        cal = await _calendar(db, who)
        for c in cal["checks"]:
            if c["status"] not in ("overdue", "due_soon"):
                continue
            label = c["label"][0].lower() + c["label"][1:]
            title = f"Time for a {label}" if who["self"] else f"{who['name']}: {label} is due"
            n = await _claim(db, uid, "health_checkup", f"health_checkup:{pid}:{c['key']}:{c['next_due']}",
                             title, c["why"], {**data, "screen": "health/checkups", "check": c["key"]}, at)
            if n:
                return n
    if who["self"] and not await _recent(db, uid, "health_log", None,
                                         now_utc - timedelta(days=LOG_REMINDER_GAP_DAYS)):
        month_ago = (today - timedelta(days=30)).isoformat()
        gap_from = (today - timedelta(days=LOG_GAP_DAYS - 1)).isoformat()
        logged_before = await db.health_measurements.find_one(
            {"user_id": pid, "taken_on": {"$gte": month_ago, "$lt": gap_from}}, {"_id": 1})
        logged_lately = await db.health_measurements.find_one(
            {"user_id": pid, "taken_on": {"$gte": gap_from}}, {"_id": 1})
        if logged_before and not logged_lately:
            return await _claim(db, uid, "health_log", f"health_log:{today.isoformat()}",
                                "30 seconds for you today?", "No catching up needed — today counts.",
                                {**data, "screen": "health/daily"}, at)
    return None


async def _urge_checkins(db, user: dict, local: datetime) -> List[dict]:
    from habits import KINDS
    from nudges import _claim

    out = []
    async for h in db.habits.find({"user_id": user["id"], "status": "active"}, {"_id": 0}):
        times = [t for log in await db.habit_logs.find({"habit_id": h["id"]}, {"_id": 0, "urge_times": 1})
                 .to_list(length=None) for t in log.get("urge_times", [])]
        m = usual_urge_minute(times, local.tzinfo, local)
        if m is None:
            continue
        m = (m - URGE_LEAD_MINUTES) % 1440
        at = datetime.combine(local.date(), time(m // 60, m % 60), tzinfo=local.tzinfo)
        if not (at <= local <= at + URGE_SEND_WINDOW):
            continue
        reason = h.get("for_what") or ""
        if not reason and h.get("serves_plan_id"):
            plan = await db.life_plans.find_one({"id": h["serves_plan_id"]}, {"_id": 0, "title": 1})
            reason = (plan or {}).get("title", "")
        tip = KINDS[h["kind"]]["help"][0]
        n = await _claim(db, user["id"], "habit_urge", f"habit_urge:{h['id']}:{local.date().isoformat()}",
                         f"For {reason}" if reason else "This moment will pass",
                         f"Urges often come around now. {tip}.",
                         {"screen": "habits", "habit_id": h["id"]}, at)
        if n:
            out.append(n)
    return out


async def health_nudges(db, user: dict, settings: dict, now: datetime) -> List[dict]:
    from nudges import _due, _tz, hhmm_to_minute, in_quiet_hours

    cfg = settings["health"]
    if not cfg["enabled"]:
        return []
    tz = _tz(user.get("timezone"))
    local = now.astimezone(tz)
    quiet = settings["quiet_hours"]
    if in_quiet_hours(local.hour * 60 + local.minute, quiet["start"], quiet["end"]):
        return []
    out = []
    at = _due(local, hhmm_to_minute(cfg["time"]))
    if at is not None:
        people = [{"id": user["id"], "name": "", "self": True}] + [
            {"id": cp["id"], "name": cp["name"], "self": False}
            async for cp in db.care_profiles.find({"owner_id": user["id"]}, {"_id": 0})]
        for who in people:
            n = await _for_person(db, user, who, local, at)
            if n:
                out.append(n)
    return out + await _urge_checkins(db, user, local)
