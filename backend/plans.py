"""Subscription plans: which features a user's plan includes.

There is no billing yet. A user's plan is, in order:
1. ``users.plan`` when set (``free`` or ``premium``);
2. ``premium`` when their email is in ``HYMN_PREMIUM_EMAILS``
   (comma-separated; how the owner and beta testers get Premium);
3. ``HYMN_DEFAULT_PLAN`` (default ``free``).

Free users enter opening balances by hand; reading statements (and the
spending history and analysis built from them) is Premium.
"""
from __future__ import annotations

import os

from fastapi import HTTPException

PLANS = ("free", "premium")
PREMIUM_FEATURES = frozenset({"statements"})


def user_plan(user: dict) -> str:
    stored = user.get("plan")
    if stored in PLANS:
        return stored
    premium_emails = {
        e.strip().lower() for e in os.environ.get("HYMN_PREMIUM_EMAILS", "").split(",") if e.strip()
    }
    if (user.get("email") or "").lower() in premium_emails:
        return "premium"
    default = (os.environ.get("HYMN_DEFAULT_PLAN") or "free").strip().lower()
    return default if default in PLANS else "free"


def has_feature(user: dict, feature: str) -> bool:
    return feature not in PREMIUM_FEATURES or user_plan(user) == "premium"


def require_feature(user: dict, feature: str, message: str) -> None:
    if not has_feature(user, feature):
        raise HTTPException(status_code=403, detail=message)
