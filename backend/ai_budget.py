"""A daily cap on AI calls per person, so one account (or a stolen login)
can't run up the AI bill.

Two buckets: ``strong`` (the planning chat, learning-journey setup, goal
merge: the expensive model, often with web search) and ``light`` (brain
dump sorting, payslip reading, statement uploads: the cheap model).
Features with their own monthly allowance (food photos, lab reports) are
not counted here.

Defaults per day: strong 15 (Premium 60), light 100 (Premium 300). Override
with ``HYMN_AI_STRONG_PER_DAY`` / ``HYMN_AI_STRONG_PER_DAY_PREMIUM`` /
``HYMN_AI_LIGHT_PER_DAY`` / ``HYMN_AI_LIGHT_PER_DAY_PREMIUM``. Attempts are
counted (not only successes): a failed call still costs.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import Depends, HTTPException
from pymongo import ReturnDocument

from deps import get_current_user, get_db
from plans import user_plan

DEFAULTS = {("strong", "free"): 15, ("strong", "premium"): 60, ("light", "free"): 100, ("light", "premium"): 300}
_ENV = {("strong", "free"): "HYMN_AI_STRONG_PER_DAY", ("strong", "premium"): "HYMN_AI_STRONG_PER_DAY_PREMIUM",
        ("light", "free"): "HYMN_AI_LIGHT_PER_DAY", ("light", "premium"): "HYMN_AI_LIGHT_PER_DAY_PREMIUM"}


def limit_for(user: dict, kind: str) -> int:
    key = (kind, user_plan(user))
    try:
        return max(0, int(os.environ.get(_ENV[key], DEFAULTS[key])))
    except ValueError:
        return DEFAULTS[key]


async def spend(db, user: dict, kind: str) -> int:
    """Count one call; raise 429 when today's allowance is used. Returns how many are left."""
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = await db.ai_usage.find_one_and_update(
        {"user_id": user["id"], "day": day, "kind": kind}, {"$inc": {"count": 1}},
        upsert=True, return_document=ReturnDocument.AFTER)
    limit = limit_for(user, kind)
    if row["count"] > limit:
        raise HTTPException(status_code=429, detail="You've reached today's limit for this. It resets tomorrow.")
    return limit - row["count"]


def daily(kind: str):
    async def dependency(current_user: dict = Depends(get_current_user)) -> None:
        await spend(get_db(), current_user, kind)
    return dependency


async def ensure_ai_budget_indexes(db) -> None:
    await db.ai_usage.create_index([("user_id", 1), ("day", 1), ("kind", 1)], unique=True)
    await db.ai_usage.create_index("day")
