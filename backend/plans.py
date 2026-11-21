"""Plans: who is Premium, what's Premium-only, and each plan's limits.

A person is Premium when (first match wins):
1. ``users.plan`` is set (``premium`` or ``free``): a manual choice from the admin page;
2. their email is in ``HYMN_PREMIUM_EMAILS``;
3. ``users.premium_until`` is in the future: a paid subscription (plus grace), the
   14-day trial at sign-up, the beta pass or a promo code (``billing.refresh``
   keeps it up to date, with ``premium_source``);
4. ``HYMN_DEFAULT_PLAN`` (default ``free``).

What's Premium-only and the limits per plan live in the admin settings
(``premium_only``, ``limits``) and can be changed on the admin page. The
latest settings are mirrored here (``mirror``) so the quick checks below
can stay synchronous.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

PLANS = ("free", "premium")


def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, default)))
    except ValueError:
        return default


# Defaults (the admin page can change them). None means no limit.
DEFAULT_PREMIUM_ONLY = ["statements", "life_objects"]
def default_limits() -> dict:
    """The starting limits (older Railway variables for food photos and lab reads still count)."""
    return {
        "planner_chats_month": {"free": 3, "premium": None},
        "learning_journeys": {"free": 1, "premium": None},
        "care_profiles": {"free": 1, "premium": 5},
        "food_photos_month": {"free": _env_int("HYMN_FOOD_PHOTOS_FREE", 30),
                              "premium": _env_int("HYMN_FOOD_PHOTOS_PREMIUM", 300)},
        "lab_reads_month": {"free": _env_int("HYMN_LAB_READS_FREE", 3),
                            "premium": _env_int("HYMN_LAB_READS_PREMIUM", 20)},
        "whatsapp_tasks_month": {"free": 20, "premium": None},
    }


DEFAULT_LIMITS = default_limits()
LIMIT_NAMES = {
    "planner_chats_month": "planning conversations a month",
    "learning_journeys": "learning journeys at a time",
    "care_profiles": "people you look after",
    "food_photos_month": "food photos a month",
    "lab_reads_month": "lab reports read a month",
    "whatsapp_tasks_month": "WhatsApp tasks a month",
}

_mirror: dict = {"premium_only": list(DEFAULT_PREMIUM_ONLY), "limits": {}}   # limits: only what was changed


def mirror(settings: dict) -> None:
    """Called whenever settings are loaded, so the synchronous checks see the latest."""
    _mirror["premium_only"] = list(settings.get("premium_only") or DEFAULT_PREMIUM_ONLY)
    _mirror["limits"] = dict(settings.get("limits_overrides") or {})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def premium_until_active(user: dict, now: Optional[datetime] = None) -> bool:
    until = user.get("premium_until")
    if not until:
        return False
    try:
        dt = datetime.fromisoformat(until)
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt > (now or _now())


def user_plan(user: dict) -> str:
    stored = user.get("plan")
    if stored in PLANS:
        return stored
    premium_emails = {
        e.strip().lower() for e in os.environ.get("HYMN_PREMIUM_EMAILS", "").split(",") if e.strip()
    }
    if (user.get("email") or "").lower() in premium_emails:
        return "premium"
    if premium_until_active(user):
        return "premium"
    default = (os.environ.get("HYMN_DEFAULT_PLAN") or "free").strip().lower()
    return default if default in PLANS else "free"


def has_feature(user: dict, feature: str) -> bool:
    return feature not in _mirror["premium_only"] or user_plan(user) == "premium"


def require_feature(user: dict, feature: str, message: str) -> None:
    if not has_feature(user, feature):
        raise HTTPException(status_code=403, detail=message)


def limit(user: dict, key: str) -> Optional[int]:
    """This person's limit for ``key`` (None = no limit)."""
    row = {**default_limits(), **_mirror["limits"]}.get(key) or {}
    value = row.get(user_plan(user))
    return None if value is None else max(0, int(value))


def within(user: dict, key: str, used: int) -> bool:
    cap = limit(user, key)
    return cap is None or used < cap


def require_within(user: dict, key: str, used: int) -> None:
    """403 with a friendly line when the plan's limit is reached."""
    if within(user, key, used):
        return
    cap = limit(user, key)
    name = LIMIT_NAMES.get(key, key)
    if user_plan(user) == "premium":
        raise HTTPException(status_code=403, detail=f"You've reached the limit of {cap} {name}.")
    raise HTTPException(status_code=403, detail=f"The free plan includes {cap} {name}. Premium has more — "
                                                "see Me → Premium.")
