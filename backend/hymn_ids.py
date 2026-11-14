"""Hymn IDs: one short ID per person, shared with Pamphlet later.

Every ID is exactly 7 characters.

* **Real ID**: one letter + six digits, e.g. ``S482915``. Everyone gets a
  free random one; it never changes. Letters I and O are never used (they
  look like 1 and 0). 24 × 1,000,000 = 24 million possible IDs; a second
  letter can be added later without touching existing ones.
* **Alias**: seven letters and digits with at least two letters, e.g.
  ``PRIYA88`` or ``SAGAR77``. It points to a real ID and costs more. It can
  never have the real-ID shape, so the two never clash.

Special real IDs (``S777777``, ``S123456``, birthdays like ``S150890``,
numbers like 786 and 1008) are graded and **reserved**: the free random
generator never hands them out. Aliases and special IDs can't be claimed
until the shop opens (payments). One registry (``hymn_ids``) holds every
ID; look-alike characters are treated as the same (O=0, I=1), so nobody
can take a confusing copy of someone else's ID.
"""
from __future__ import annotations

import re
import secrets
import time
from collections import defaultdict, deque
from datetime import date as date_type, datetime, timezone
from typing import Deque, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pymongo.errors import DuplicateKeyError

from deps import get_current_user, get_db

hymn_id_router = APIRouter(prefix="/hymn-id", tags=["hymn-id"])

LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"  # 24: no I, no O
REAL_ID = re.compile(rf"^[{LETTERS}]\d{{6}}$")
ALIAS = re.compile(r"^[A-Z0-9]{7}$")

# Numbers people pay for (religious, auspicious); kept small and explicit.
SACRED = {"000786", "786786", "000108", "108108", "001008", "000999", "999999", "000420"}

# Words an alias may not contain (abuse, brands, government). A starting
# list; extend before the shop opens.
BLOCKED_WORDS = (
    "FUCK", "SHIT", "BITCH", "CHUT", "LUND", "RANDI", "MADAR", "BHENCH", "GANDU", "SEX", "PORN",
    "RBI", "SEBI", "GOVT", "POLICE", "ADMIN", "HYMN", "PAMPH", "SUPPORT",
    "TATA", "INFOSYS", "WIPRO", "RELIANCE", "AMAZON", "GOOGLE", "PAYTM", "PHONEPE", "ZOMATO", "SWIGGY",
)

# Grades, cheapest first. The shop will price them; until then only
# "standard" real IDs are handed out.
GRADES = ("standard", "pattern", "birthday", "special", "alias")


def canonical(value: str) -> str:
    """The form used for uniqueness: upper case, O→0, I→1."""
    return (value or "").strip().upper().replace("O", "0").replace("I", "1")


def _is_birthday(digits: str) -> bool:
    dd, mm, yy = int(digits[:2]), int(digits[2:4]), int(digits[4:])
    for century in (1900, 2000):
        try:
            date_type(century + yy, mm, dd)
            return True
        except ValueError:
            continue
    return False


def grade(value: str) -> Optional[str]:
    """The grade of a valid ID, or None if it isn't a valid ID at all."""
    v = (value or "").strip().upper()
    if REAL_ID.match(v):
        d = v[1:]
        if len(set(d)) == 1 or d in SACRED:
            return "special"
        steps = {int(d[i + 1]) - int(d[i]) for i in range(5)}
        if (len(steps) == 1 and steps <= {1, -1}) or d == d[::-1] \
                or d[:2] * 3 == d or d[:3] * 2 == d:
            return "pattern"
        if _is_birthday(d):
            return "birthday"
        return "standard"
    if ALIAS.match(v) and sum(c.isalpha() for c in v) >= 2 and not REAL_ID.match(canonical(v)):
        return "alias"
    return None


def alias_problem(value: str) -> Optional[str]:
    """Why this can't be an alias, in plain words; None if it can."""
    v = (value or "").strip().upper()
    if len(v) != 7:
        return "An alias is exactly 7 letters and numbers, like PRIYA88."
    if not ALIAS.match(v):
        return "Use only letters A–Z and numbers 0–9."
    if sum(c.isalpha() for c in v) < 2:
        return "An alias needs at least 2 letters."
    if REAL_ID.match(canonical(v)):
        return "That looks like a real Hymn ID (1 letter + 6 numbers); pick something else."
    if any(w in v or w in canonical(v) for w in BLOCKED_WORDS):
        return "That alias isn't available."
    return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def assign_real_id(db, user_id: str) -> str:
    """Give the user a free random standard ID (once). Special IDs are
    never handed out here."""
    existing = await db.hymn_ids.find_one({"owner_user_id": user_id, "kind": "real"}, {"display": 1})
    if existing:
        return existing["display"]
    for _ in range(50):
        candidate = secrets.choice(LETTERS) + f"{secrets.randbelow(1_000_000):06d}"
        if grade(candidate) != "standard":
            continue
        try:
            await db.hymn_ids.insert_one({"_id": canonical(candidate), "display": candidate, "kind": "real",
                                          "grade": "standard", "owner_user_id": user_id, "status": "assigned",
                                          "created_at": _now()})
            await db.users.update_one({"id": user_id}, {"$set": {"hymn_id": candidate}})
            return candidate
        except DuplicateKeyError:
            continue
    raise RuntimeError("Could not find a free Hymn ID")


async def ensure_hymn_id(db, user: dict) -> dict:
    """Existing users get their ID the first time they're seen."""
    if not user.get("hymn_id"):
        user["hymn_id"] = await assign_real_id(db, user["id"])
    return user


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

_LOOKUPS: Dict[str, Deque[float]] = defaultdict(deque)
LOOKUPS_PER_MINUTE = 20


def _rate_limit(user_id: str) -> None:
    q, now = _LOOKUPS[user_id], time.monotonic()
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= LOOKUPS_PER_MINUTE:
        raise HTTPException(status_code=429, detail="Too many lookups; try again in a minute.")
    q.append(now)


@hymn_id_router.get("/check/{value}")
async def check(value: str, current_user: dict = Depends(get_current_user)):
    """Is this a valid ID, what grade is it, and is it free?"""
    _rate_limit(current_user["id"])
    v = value.strip().upper()
    g = grade(v)
    if g is None:
        return {"value": v, "valid": False, "reason": alias_problem(v) or "Not a valid Hymn ID."}
    if g == "alias" and alias_problem(v):
        return {"value": v, "valid": False, "reason": alias_problem(v)}
    taken = await get_db().hymn_ids.find_one({"_id": canonical(v)}, {"_id": 1})
    return {"value": v, "valid": True, "kind": "alias" if g == "alias" else "real", "grade": g,
            "available": taken is None,
            # The shop isn't open: only free standard IDs are handed out.
            "can_claim_now": False}


@hymn_id_router.get("/find/{value}")
async def find(value: str, current_user: dict = Depends(get_current_user)):
    """Find a person by real ID or alias. Returns only what an invite
    needs: their IDs and first name."""
    _rate_limit(current_user["id"])
    row = await get_db().hymn_ids.find_one({"_id": canonical(value), "status": "assigned"})
    if not row:
        raise HTTPException(status_code=404, detail="No one has that Hymn ID.")
    user = await get_db().users.find_one({"id": row["owner_user_id"]}, {"_id": 0, "name": 1, "hymn_id": 1,
                                                                        "hymn_alias": 1})
    if not user:
        raise HTTPException(status_code=404, detail="No one has that Hymn ID.")
    return {"hymn_id": user.get("hymn_id"), "alias": user.get("hymn_alias"),
            "first_name": ((user.get("name") or "").split() or [""])[0]}


async def ensure_hymn_id_indexes(db) -> None:
    await db.hymn_ids.create_index([("owner_user_id", 1), ("kind", 1)])
