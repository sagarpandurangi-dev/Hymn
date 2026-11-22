"""What people use and what the AI costs: counted on the server, never content.

- Requests: each API call is counted per person, day and feature (the first
  part of the route, e.g. "food", "plan-chat"), in memory, and written to
  ``usage_daily`` once a minute (``flush``). 5xx answers are logged to
  ``errors`` (route and status only). ``usage_totals`` keeps the same counts
  with no person attached, so totals survive account deletion.
- AI: every Claude call goes through ``claude_client``'s metered client, which
  calls ``guard`` first (feature switched off? monthly budget used up?) and
  ``record_ai`` after: tokens, web searches, model, cost in $ and ₹ per call
  (``ai_calls``, per person) and per day/feature/model (``ai_daily``, no person).
- Settings (budget, rate, switches, beta) live in ``admin_settings`` and are
  changed from the admin page.
"""
from __future__ import annotations

import logging
import os
import time as _time
from collections import defaultdict
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_actor: ContextVar[dict] = ContextVar("hymn_actor", default={})


def set_actor(user_id: Optional[str], feature: Optional[str]):
    return _actor.set({"user_id": user_id, "feature": feature})


def actor() -> dict:
    return _actor.get()


# ---------------------------------------------------------------------------
# Features and areas
# ---------------------------------------------------------------------------

# Finer names for a few routes whose first part is shared.
_FEATURE_PREFIXES = [
    ("/api/health/labs", "labs"), ("/api/health/sync", "watch-sync"), ("/api/health/checkups", "checkups"),
    ("/api/work/payslips", "payslips"), ("/api/reports/time", "time-statements"),
    ("/api/investments/cas", "investments"), ("/api/screens/finance", "finance"),
]
AREAS = {
    "money": {"finance", "portfolio", "ledger", "statements", "planned-money", "reports", "life-objects",
              "investments", "family"},
    "health": {"health", "food", "habits", "care", "labs", "watch-sync", "checkups"},
    "family": {"people"},
    "learning": {"learning"},
    "work": {"work", "payslips"},
    "plans": {"plan-chat", "life-plans", "planning", "planning-space", "plan-templates", "goals",
              "expected-outcomes", "time-statements"},
    "everyday": {"tasks", "checkins", "projects", "domains", "inbox", "nudges", "whatsapp"},
    "account": {"auth", "account", "hymn-id", "invites"},
}
AREA_OF = {f: a for a, fs in AREAS.items() for f in fs}
# The ones that call the AI (each can be switched off on the admin page).
AI_FEATURES = ["plan-chat", "planning", "goals", "life-plans", "learning", "inbox", "statements", "payslips",
               "food", "labs", "whatsapp"]


def feature_of(path: Optional[str]) -> Optional[str]:
    """'/api/food/day' → 'food'. None for the admin page, the health check and non-API paths."""
    if not path or not path.startswith("/api/") or path.startswith("/api/admin"):
        return None
    for prefix, name in _FEATURE_PREFIXES:
        if path.startswith(prefix):
            return name
    part = path[len("/api/"):].split("/", 1)[0]
    return part or None


def area_of(feature: str) -> str:
    return AREA_OF.get(feature, "other")


# ---------------------------------------------------------------------------
# Request counting
# ---------------------------------------------------------------------------

_counts: Dict[Tuple[str, str, str], list] = defaultdict(lambda: [0, 0])
_seen: Dict[str, str] = {}
_versions: Dict[str, str] = {}


def _day(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y-%m-%d")


def count_request(user_id: Optional[str], feature: Optional[str], status: int, now: Optional[datetime] = None,
                  app_version: Optional[str] = None) -> None:
    if not feature:
        return
    now = now or datetime.now(timezone.utc)
    c = _counts[(_day(now), user_id or "", feature)]
    c[0] += 1
    if status >= 500:
        c[1] += 1
    if user_id:
        _seen[user_id] = now.isoformat()
        if app_version:
            _versions[user_id] = app_version[:20]


async def flush(db) -> int:
    """Write the counted requests (called every minute, and by tests)."""
    if not _counts and not _seen:
        return 0
    counts, seen, versions = dict(_counts), dict(_seen), dict(_versions)
    _counts.clear()
    _seen.clear()
    _versions.clear()
    for (day, uid, feature), (calls, errors) in counts.items():
        inc = {"calls": calls, "errors": errors}
        if uid:
            await db.usage_daily.update_one({"day": day, "user_id": uid, "feature": feature},
                                            {"$inc": inc, "$set": {"area": area_of(feature)}}, upsert=True)
        await db.usage_totals.update_one({"day": day, "feature": feature},
                                         {"$inc": inc, "$set": {"area": area_of(feature)}},
                                         upsert=True)
    for uid, at in seen.items():
        await db.users.update_one({"id": uid, "$or": [{"last_active_at": None}, {"last_active_at": {"$lt": at}}]},
                                  {"$set": {"last_active_at": at}})
    for uid, v in versions.items():
        await db.users.update_one({"id": uid}, {"$set": {"app_version": v}})
    return len(counts)


async def record_error(db, method: str, route: Optional[str], status: int, user_id: Optional[str]) -> None:
    now = datetime.now(timezone.utc)
    try:
        await db.errors.insert_one({"at": now.isoformat(), "day": _day(now), "method": method,
                                    "route": route or "(unmatched)", "status": status, "user_id": user_id})
    except Exception:
        logger.exception("metering: could not log an error")


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

DEFAULT_SETTINGS = {
    "ai_warn_inr": 5000,          # monthly AI spend: warning
    "ai_stop_inr": 10000,         # monthly AI spend: every AI feature pauses until the 1st
    "usd_inr": 88.0,              # exchange rate used for ₹ figures
    "ai_off": [],                 # AI features switched off
    "invite_only": False,         # switch on once the app's sign-up has an invite box
    "beta_cap": 200,              # most accounts while invite-only
    "invites_per_person": 5,      # each person's invite link works this many times
    # Premium (see billing.py and plans.py)
    "price_monthly_inr": 199,
    "price_yearly_inr": 1499,
    "price_founding_yearly_inr": 999,   # first year for founding members (beta testers)
    "trial_days": int(os.environ.get("HYMN_TRIAL_DAYS", "14") or 14),   # Premium for new people, no card
    "grace_days": 7,                    # Premium continues this long after a failed payment
    "beta_premium_until": None,         # "YYYY-MM-DD": everyone who signs up before then gets Premium + founding
    "razorpay_plan_monthly": "",        # Razorpay plan ids (not secret); create a new plan when the price changes
    "razorpay_plan_yearly": "",
    "razorpay_plan_founding": "",
    "premium_only": None,               # None = plans.DEFAULT_PREMIUM_ONLY
    "limits": None,                     # only the limits changed on the admin page; see plans.default_limits()
    # Demand reports for local sellers (demand.py): off until a lawyer has reviewed sharing.
    "demand_sharing_on": False,
    "demand_min_count": 20,             # sellers only see groups of at least this many people
}
_cache: dict = {}


def reset_cache() -> None:
    _cache.clear()


async def get_settings(db) -> dict:
    hit = _cache.get("settings")
    if hit and _time.monotonic() - hit[0] < 30:
        return hit[1]
    doc = await db.admin_settings.find_one({"_id": "global"}) or {}
    merged = {**DEFAULT_SETTINGS, **{k: v for k, v in doc.items() if k in DEFAULT_SETTINGS}}
    import plans
    if merged.get("premium_only") is None:
        merged["premium_only"] = list(plans.DEFAULT_PREMIUM_ONLY)
    merged["limits_overrides"] = dict(merged.get("limits") or {})
    merged["limits"] = {**plans.default_limits(), **merged["limits_overrides"]}
    plans.mirror(merged)
    _cache["settings"] = (_time.monotonic(), merged)
    return merged


async def save_settings(db, changes: dict) -> dict:
    await db.admin_settings.update_one({"_id": "global"}, {"$set": changes}, upsert=True)
    reset_cache()
    return await get_settings(db)


# ---------------------------------------------------------------------------
# AI cost
# ---------------------------------------------------------------------------

# US$ per million tokens: input, output, cache read, cache write (5-minute).
# Haiku 5.5: prompts above 100K tokens cost $0.50 / $2.50 (rare here; not modelled).
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
    "claude-sonnet-5-5": (2.00, 10.00, 0.10, 2.50),
    "claude-opus-5-5": (4.00, 20.00, 0.20, 5.00),
    "claude-opus-5": (5.00, 25.00, 0.50, 6.25),
    "claude-fable-5-2": (8.00, 40.00, 0.20, 10.00),
    "claude-fable-5-1": (10.00, 50.00, 1.00, 12.50),
}
FALLBACK_PRICE = PRICES["claude-opus-5-5"]     # unknown model: count it at Opus prices, never at zero
WEB_SEARCH_USD = 0.01                           # per search ($10 per 1,000)


def _num(obj, name) -> int:
    v = getattr(obj, name, None) if not isinstance(obj, dict) else obj.get(name)
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def usage_numbers(usage) -> dict:
    if usage is None:
        return {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "searches": 0}
    stu = getattr(usage, "server_tool_use", None) if not isinstance(usage, dict) else usage.get("server_tool_use")
    return {"input": _num(usage, "input_tokens"), "output": _num(usage, "output_tokens"),
            "cache_read": _num(usage, "cache_read_input_tokens"),
            "cache_write": _num(usage, "cache_creation_input_tokens"),
            "searches": _num(stu, "web_search_requests") if stu is not None else 0}


def cost_usd(model: Optional[str], n: dict) -> float:
    pi, po, pr, pw = PRICES.get(model or "", FALLBACK_PRICE)
    return (n["input"] * pi + n["output"] * po + n["cache_read"] * pr + n["cache_write"] * pw) / 1e6 \
        + n["searches"] * WEB_SEARCH_USD


def _month(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y-%m")


async def month_spend_inr(db, now: Optional[datetime] = None, fresh: bool = False) -> float:
    now = now or datetime.now(timezone.utc)
    key = ("month", _month(now))
    hit = _cache.get(key)
    if hit and not fresh and _time.monotonic() - hit[0] < 30:
        return hit[1]
    rows = await db.ai_daily.find({"month": _month(now)}, {"_id": 0, "cost_inr": 1}).to_list(length=None)
    total = round(sum(r.get("cost_inr", 0) for r in rows), 2)
    _cache[key] = (_time.monotonic(), total)
    return total


class Paused(Exception):
    """An AI feature is switched off or the month's budget is used up."""


async def guard(db, feature: Optional[str], now: Optional[datetime] = None) -> None:
    s = await get_settings(db)
    if feature and feature in (s.get("ai_off") or []):
        raise Paused(f"{feature} is switched off")
    spent = await month_spend_inr(db, now)
    if spent >= float(s["ai_stop_inr"]):
        raise Paused("monthly AI budget used up")


async def record_ai(db, model: Optional[str], usage, ok: bool, ms: int, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    who = actor()
    feature = who.get("feature") or "other"
    n = usage_numbers(usage)
    usd = cost_usd(model, n) if ok or any(n.values()) else 0.0
    s = await get_settings(db)
    inr = round(usd * float(s["usd_inr"]), 4)
    doc = {"at": now.isoformat(), "day": _day(now), "month": _month(now), "user_id": who.get("user_id"),
           "feature": feature, "model": model or "unknown", **n, "cost_usd": round(usd, 6), "cost_inr": inr,
           "ok": ok, "ms": ms}
    await db.ai_calls.insert_one(dict(doc))
    await db.ai_daily.update_one(
        {"day": doc["day"], "feature": feature, "model": doc["model"]},
        {"$inc": {"calls": 1, "failed": 0 if ok else 1, "cost_usd": doc["cost_usd"], "cost_inr": inr,
                  "input": n["input"], "output": n["output"], "searches": n["searches"]},
         "$set": {"month": doc["month"]}}, upsert=True)
    _cache.pop(("month", doc["month"]), None)
    total = await month_spend_inr(db, now, fresh=True)
    if total >= float(s["ai_warn_inr"]) and not _cache.get(("warned", doc["month"])):
        _cache[("warned", doc["month"])] = True
        logger.warning("AI spend this month is ₹%.0f (warning at ₹%s, stop at ₹%s)",
                       total, s["ai_warn_inr"], s["ai_stop_inr"])
    return doc


async def purge(db, now: Optional[datetime] = None) -> None:
    """Per-call AI rows and error rows go after 90 / 30 days; daily totals stay."""
    now = now or datetime.now(timezone.utc)
    await db.ai_calls.delete_many({"at": {"$lt": (now - timedelta(days=90)).isoformat()}})
    await db.errors.delete_many({"at": {"$lt": (now - timedelta(days=30)).isoformat()}})


async def ensure_metering_indexes(db) -> None:
    await db.usage_daily.create_index([("day", 1), ("user_id", 1), ("feature", 1)], unique=True)
    await db.usage_daily.create_index("user_id")
    await db.usage_totals.create_index([("day", 1), ("feature", 1)], unique=True)
    await db.ai_calls.create_index([("month", 1), ("user_id", 1)])
    await db.ai_calls.create_index("at")
    await db.ai_daily.create_index([("day", 1), ("feature", 1), ("model", 1)], unique=True)
    await db.ai_daily.create_index("month")
    await db.errors.create_index("at")
    await db.users.create_index("last_active_at")
