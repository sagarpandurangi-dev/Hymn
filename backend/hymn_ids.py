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

import os
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


_TO_LETTER = str.maketrans({"0": "O", "1": "I", "L": "I", "2": "Z", "5": "S", "6": "G", "8": "B"})
_TO_DIGIT = str.maketrans({"O": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "G": "6", "B": "8"})


def skeleton(value: str) -> str:
    """How an alias *looks*: 5/S, 8/B, 2/Z, 6/G, 0/O and 1/I/L read alike,
    so SAGAR77 and 5AGAR77 have the same skeleton and can't both exist."""
    return (value or "").strip().upper().translate(_TO_LETTER)


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
    if REAL_ID.match(canonical(v)) or REAL_ID.match(v[0] + v[1:].translate(_TO_DIGIT)):
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


def alias_grants() -> Dict[str, str]:
    """Aliases the owner hands out before the shop opens, set on the
    server as HYMN_ALIAS_GRANTS="email=ALIAS,email=ALIAS" (never in code)."""
    out = {}
    for pair in os.environ.get("HYMN_ALIAS_GRANTS", "").split(","):
        email, _, alias = pair.partition("=")
        if email.strip() and alias.strip():
            out[email.strip().lower()] = alias.strip().upper()
    return out


async def grant_alias(db, user: dict, alias: str) -> Optional[str]:
    """Give ``user`` this alias if it's valid and free. Returns the alias
    the user ends up with (None if it couldn't be given)."""
    if user.get("hymn_alias") or alias_problem(alias) or grade(alias) != "alias":
        return user.get("hymn_alias")
    lookalike = await db.hymn_ids.find_one({"kind": "alias", "skeleton": skeleton(alias)}, {"owner_user_id": 1})
    if lookalike and lookalike.get("owner_user_id") != user["id"]:
        return None  # someone has an alias that reads the same
    try:
        await db.hymn_ids.insert_one({"_id": canonical(alias), "display": alias, "kind": "alias",
                                      "skeleton": skeleton(alias),
                                      "grade": "alias", "owner_user_id": user["id"], "status": "assigned",
                                      "granted_by": "owner", "created_at": _now()})
    except DuplicateKeyError:
        row = await db.hymn_ids.find_one({"_id": canonical(alias)}, {"owner_user_id": 1})
        if not row or row.get("owner_user_id") != user["id"]:
            return None  # someone else has it
    await db.users.update_one({"id": user["id"]}, {"$set": {"hymn_alias": alias}})
    user["hymn_alias"] = alias
    return alias


async def ensure_hymn_id(db, user: dict) -> dict:
    """Existing users get their ID the first time they're seen, plus any
    alias the owner granted them."""
    if not user.get("hymn_id"):
        user["hymn_id"] = await assign_real_id(db, user["id"])
    granted = alias_grants().get((user.get("email") or "").lower())
    if granted and not user.get("hymn_alias"):
        await grant_alias(db, user, granted)
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


# ---------------------------------------------------------------------------
# Dynamic pricing: nobody sets prices by hand
# ---------------------------------------------------------------------------
#
# price = base for the grade
#         × rarity within the grade (all-same digits, very short patterns)
#         × demand: how many *different* people looked this ID up in the
#           last 30 days (each extra searcher adds less than the one before)
#         × name popularity for aliases (how many Hymn users share the name)
# rounded to a familiar price point. Past the top price point, or when many
# people want the same ID at once, it goes to auction instead.
# The bases are the only numbers anyone sets, once; HYMN_ID_BASE_PRICES can
# override them ("pattern=199,birthday=299,...").

DEFAULT_BASE_PRICES = {"pattern": 199, "birthday": 299, "special": 999, "alias": 2999}
PRICE_POINTS = (99, 149, 199, 249, 299, 399, 499, 699, 799, 999, 1499, 1999, 2499, 2999,
                3999, 4999, 6999, 7999, 9999)
AUCTION_ABOVE = 9999
AUCTION_SEARCHERS = 10      # this many different people in 30 days → auction
DEMAND_WINDOW_DAYS = 30


def base_prices() -> Dict[str, int]:
    prices = dict(DEFAULT_BASE_PRICES)
    for pair in os.environ.get("HYMN_ID_BASE_PRICES", "").split(","):
        g, _, amount = pair.partition("=")
        if g.strip() in prices and amount.strip().isdigit():
            prices[g.strip()] = int(amount.strip())
    return prices


def rarity(value: str, g: str) -> float:
    v = value.upper()
    if g == "special" and len(set(v[1:])) == 1:
        return 3.0          # S777777: only 240 exist
    if g == "alias":
        letters = sum(c.isalpha() for c in v)
        digits = 7 - letters
        # SAGAR77 (a name and a short lucky number) is what people want most.
        return 1.5 if digits <= 2 else 1.0
    return 1.0


def _nice(amount: float) -> int:
    return next((p for p in PRICE_POINTS if p >= amount), PRICE_POINTS[-1])


def quote(value: str, g: str, searchers: int, name_users: int = 0) -> dict:
    """Pure: the price (or auction) for an ID right now."""
    if g == "standard":
        return {"price_inr": 0, "how": "free"}
    import math
    raw = base_prices()[g] * rarity(value, g) * (1 + math.log2(1 + max(searchers, 0)) / 2)
    if g == "alias":
        raw *= 1 + math.log10(1 + max(name_users, 0)) / 2
    if raw > AUCTION_ABOVE or searchers >= AUCTION_SEARCHERS:
        return {"price_inr": None, "how": "auction", "reserve_inr": _nice(min(raw, AUCTION_ABOVE))}
    return {"price_inr": _nice(raw), "how": "fixed"}


async def _record_interest(db, value: str, user_id: str) -> None:
    day = datetime.now(timezone.utc).date().isoformat()
    await db.hymn_id_interest.update_one(
        {"_id": f"{canonical(value)}|{user_id}|{day}"},
        {"$set": {"id": canonical(value), "user_id": user_id, "day": day}}, upsert=True)


async def _searchers(db, value: str) -> int:
    since = (datetime.now(timezone.utc).date().toordinal() - DEMAND_WINDOW_DAYS)
    since_day = date_type.fromordinal(since).isoformat()
    users = await db.hymn_id_interest.distinct("user_id", {"id": canonical(value), "day": {"$gte": since_day}})
    return len(users)


async def _name_users(db, value: str) -> int:
    name = re.match(r"^[A-Z]+", value.upper())
    if not name or len(name.group()) < 3:
        return 0
    return await db.users.count_documents({"name": {"$regex": f"^{name.group()}\\b", "$options": "i"}})


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
    db = get_db()
    taken = await db.hymn_ids.find_one({"_id": canonical(v)}, {"_id": 1})
    if taken is None and g == "alias":
        taken = await db.hymn_ids.find_one({"kind": "alias", "skeleton": skeleton(v)}, {"_id": 1})
    price: dict = {}
    if taken is None and g != "standard":
        await _record_interest(db, v, current_user["id"])
        price = quote(v, g, await _searchers(db, v), await _name_users(db, v) if g == "alias" else 0)
    return {"value": v, "valid": True, "kind": "alias" if g == "alias" else "real", "grade": g,
            "available": taken is None, **price,
            # The shop isn't open: only free standard IDs are handed out.
            "can_claim_now": False}


@hymn_id_router.get("/find/{value}")
async def find(value: str, current_user: dict = Depends(get_current_user)):
    """Find a person by real ID or alias. Returns only what an invite
    needs: their IDs and first name."""
    _rate_limit(current_user["id"])
    row = await get_db().hymn_ids.find_one({"_id": canonical(value), "status": "assigned"})
    if not row and grade(value) == "alias":  # 5AGAR77 finds SAGAR77
        row = await get_db().hymn_ids.find_one({"kind": "alias", "skeleton": skeleton(value), "status": "assigned"})
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
    await db.hymn_id_interest.create_index([("id", 1), ("day", 1)])
    await db.hymn_ids.create_index([("kind", 1), ("skeleton", 1)])
    async for row in db.hymn_ids.find({"kind": "alias", "skeleton": {"$exists": False}}, {"display": 1}):
        await db.hymn_ids.update_one({"_id": row["_id"]}, {"$set": {"skeleton": skeleton(row["display"])}})
