"""Failed-attempt throttle for unauthenticated auth endpoints.

Login and security-question password reset are otherwise open to
unlimited guessing. Every failed attempt is recorded per (action,
subject) in ``auth_attempts``; once a subject reaches the limit for any
window, further attempts get HTTP 429 until older failures age out.

Subjects are keyed by normalised email only. Client IPs are not used:
behind a hosting proxy ``request.client.host`` is the proxy, so an IP
limit would lock out every user at once. Failures for unknown emails are
recorded too, so the response never reveals whether an account exists.

Rows expire through a TTL index sized to the longest window.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

# action -> [(window, max failures within window)]
LIMITS: dict[str, list[tuple[timedelta, int]]] = {
    "login": [(timedelta(minutes=15), 10)],
    "forgot_password": [(timedelta(minutes=15), 5), (timedelta(hours=24), 20)],
}

RETENTION = max(window for rules in LIMITS.values() for window, _ in rules)

TOO_MANY_ATTEMPTS = "Too many failed attempts. Try again later."


def _subject(email: str) -> str:
    return f"email:{email}"


async def ensure_indexes(db) -> None:
    await db.auth_attempts.create_index(
        "at", expireAfterSeconds=int(RETENTION.total_seconds()),
    )
    await db.auth_attempts.create_index([("action", 1), ("subject", 1), ("at", -1)])


async def check(db, action: str, email: str) -> None:
    """Raise 429 when ``email`` has exhausted any window for ``action``."""
    now = datetime.now(timezone.utc)
    for window, limit in LIMITS[action]:
        failures = await db.auth_attempts.count_documents({
            "action": action,
            "subject": _subject(email),
            "at": {"$gte": now - window},
        })
        if failures >= limit:
            raise HTTPException(status_code=429, detail=TOO_MANY_ATTEMPTS)


async def record_failure(db, action: str, email: str) -> None:
    await db.auth_attempts.insert_one({
        "action": action,
        "subject": _subject(email),
        "at": datetime.now(timezone.utc),
    })


async def clear(db, action: str, email: str) -> None:
    await db.auth_attempts.delete_many({"action": action, "subject": _subject(email)})
