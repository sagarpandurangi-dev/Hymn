"""
Recurrence helper — Hymn task & check-in cadence engine.

Single source of truth for the extended cadence vocabulary:

    daily · alternate_day · weekly · fortnightly · monthly
    · quarterly · half_yearly · yearly · manual

The `daily/weekly/monthly/manual` values are legacy check-in cadences that
predate this module; they continue to be accepted by the goal check-in
scheduler for backward compatibility. The other five extend the semantics
uniformly across tasks and check-ins.

Design invariants
-----------------
1. Presentational (labels, orderings) live in the frontend theme file. This
   module is pure calendar math — no I/O, no user context.
2. All cadence math is anchor-based: given an anchor date and a cadence,
   compute the next scheduled date strictly greater than `from_date`.
3. Nothing here mutates the database. Callers own persistence.
4. Month arithmetic clamps day-of-month to the last valid day of the target
   month (e.g. anchor 2026-01-31 quarterly → 2026-04-30 not 2026-05-01).
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date as _date, datetime, timedelta
from typing import Any, Iterable, Optional

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------
# Full extended set — accepted by task.recurrence and (for future goal
# recurrence rewrites) by goal.checkin_cadence.
RECURRENCE_CADENCES: frozenset = frozenset({
    "daily",
    "alternate_day",
    "weekly",
    "fortnightly",
    "monthly",
    "quarterly",
    "half_yearly",
    "yearly",
})

# Legacy set (kept identical to the pre-recurrence server.py constant so we
# do not break existing goal writes). "manual" is *not* a recurrence — it
# means the user drives cadence themselves.
LEGACY_CHECKIN_CADENCES: frozenset = frozenset({"daily", "weekly", "monthly", "manual"})

# Superset used by goal.checkin_cadence validation going forward. Empty
# string is still allowed at the goal level (no cadence configured).
EXTENDED_CHECKIN_CADENCES: frozenset = frozenset(RECURRENCE_CADENCES | {"manual"})

END_TYPES: frozenset = frozenset({"never", "until", "count"})


# ---------------------------------------------------------------------------
# Date parsing & clamping
# ---------------------------------------------------------------------------
def parse_iso_date(s: str) -> _date:
    """Parse YYYY-MM-DD → datetime.date. Raises ValueError on any deviation."""
    if not s or len(s) != 10 or s[4] != "-" or s[7] != "-":
        raise ValueError(f"Expected YYYY-MM-DD, got {s!r}")
    y, m, d = int(s[0:4]), int(s[5:7]), int(s[8:10])
    return _date(y, m, d)


def _fmt(d: _date) -> str:
    return d.isoformat()


def _clamp_day(year: int, month: int, day: int) -> _date:
    """Return a valid date, clamping `day` to the last day of the target month."""
    last = monthrange(year, month)[1]
    return _date(year, month, min(day, last))


def _add_months(d: _date, months: int) -> _date:
    total = d.month - 1 + months
    y = d.year + total // 12
    m = total % 12 + 1
    return _clamp_day(y, m, d.day)


# ---------------------------------------------------------------------------
# Step sizes
# ---------------------------------------------------------------------------
_DAY_STEPS = {
    "daily": 1,
    "alternate_day": 2,
    "weekly": 7,
    "fortnightly": 14,
}
_MONTH_STEPS = {
    "monthly": 1,
    "quarterly": 3,
    "half_yearly": 6,
    "yearly": 12,
}


def step(from_date: _date, cadence: str) -> _date:
    """One cadence step forward from `from_date`. Raises on unknown cadence."""
    if cadence in _DAY_STEPS:
        return from_date + timedelta(days=_DAY_STEPS[cadence])
    if cadence in _MONTH_STEPS:
        return _add_months(from_date, _MONTH_STEPS[cadence])
    raise ValueError(f"Unsupported cadence for recurrence: {cadence!r}")


# ---------------------------------------------------------------------------
# Next-occurrence math
# ---------------------------------------------------------------------------
def next_occurrence(anchor: _date, cadence: str, after: Optional[_date] = None) -> _date:
    """Return the first cadence occurrence strictly after `after`.

    If `after` is None, returns the first occurrence on-or-after today. This
    is intentionally deterministic and independent of the current time: two
    calls with the same anchor + cadence + after produce the same date.
    """
    if cadence not in RECURRENCE_CADENCES:
        raise ValueError(f"Unsupported cadence: {cadence!r}")
    ref = after if after is not None else _date.today()
    # Fast path: if anchor is already in the future of ref, that is the next.
    if anchor > ref:
        return anchor
    if cadence in _DAY_STEPS:
        s = _DAY_STEPS[cadence]
        # Number of full steps between anchor and ref; the next is that + 1.
        delta_days = (ref - anchor).days
        n = (delta_days // s) + 1
        return anchor + timedelta(days=s * n)
    # Month-based cadences: walk forward until we pass ref.
    n = 1
    while True:
        candidate = _add_months(anchor, _MONTH_STEPS[cadence] * n)
        if candidate > ref:
            return candidate
        n += 1


def occurrences_between(
    anchor: _date,
    cadence: str,
    start: _date,
    end: _date,
    limit: int = 366,
) -> list:
    """Enumerate cadence occurrences in [start, end] (inclusive).

    `limit` guards against pathological configurations returning huge lists.
    Returns a list of `date` objects. Empty when the window contains none.
    """
    if cadence not in RECURRENCE_CADENCES:
        raise ValueError(f"Unsupported cadence: {cadence!r}")
    if end < start:
        return []
    # Start walking from the anchor. Skip forward to `start` cheaply.
    if anchor >= start:
        cursor = anchor
    else:
        # Land the cursor on the first occurrence >= start.
        cursor = next_occurrence(anchor, cadence, after=start - timedelta(days=1))
    out: list = []
    while cursor <= end and len(out) < limit:
        out.append(cursor)
        cursor = step(cursor, cadence)
    return out


# ---------------------------------------------------------------------------
# Period membership for the /checkins/required scheduler
# ---------------------------------------------------------------------------
def is_active_period(anchor: _date, cadence: str, on_date: _date) -> tuple[bool, _date, _date]:
    """For a given cadence + anchor, return (active, period_start, period_end)
    describing the period that contains `on_date`.

    * daily / alternate_day / weekly / fortnightly — a single day/period of
      length equal to the cadence step, aligned to the anchor.
    * monthly / quarterly / half_yearly / yearly — a calendar-based period
      aligned to the anchor's month & day-of-month.
    * `active=False` when `on_date` falls before the anchor.
    """
    if cadence not in RECURRENCE_CADENCES:
        raise ValueError(f"Unsupported cadence: {cadence!r}")
    if on_date < anchor:
        return (False, anchor, anchor)

    if cadence in _DAY_STEPS:
        s = _DAY_STEPS[cadence]
        # Which N-day bucket contains on_date, counting from anchor?
        n = (on_date - anchor).days // s
        period_start = anchor + timedelta(days=s * n)
        period_end = period_start + timedelta(days=s - 1)
        return (True, period_start, period_end)

    # Month-based: count months between anchor and on_date, then snap.
    months_between = (on_date.year - anchor.year) * 12 + (on_date.month - anchor.month)
    m_step = _MONTH_STEPS[cadence]
    n = months_between // m_step
    period_start = _add_months(anchor, m_step * n)
    # Adjust if on_date is before period_start.day (e.g. anchor 2026-01-31,
    # on_date 2026-02-05 with monthly cadence: months_between=1, n=1,
    # period_start=2026-02-28 → we're actually inside the previous period).
    if on_date < period_start:
        n -= 1
        period_start = _add_months(anchor, m_step * n)
    period_end = _add_months(anchor, m_step * (n + 1)) - timedelta(days=1)
    return (True, period_start, period_end)


# ---------------------------------------------------------------------------
# Recurrence spec (serialised into task.recurrence)
# ---------------------------------------------------------------------------
def normalise_recurrence(spec: dict, *, fallback_anchor: Optional[str] = None) -> dict:
    """Validate + canonicalise a raw recurrence dict from the client.

    Fields returned:
        cadence                (str, in RECURRENCE_CADENCES)
        anchor_date            (str YYYY-MM-DD)
        end_type               ("never" | "until" | "count")
        end_date               (str or None)
        occurrences_remaining  (int or None)
        series_id              (uuid-ish str, caller-provided or new)
        pre_generate_count     (int 0..12, optional pre-gen window; 0 = A)

    Raises ValueError with a human-friendly message on any invalid field.
    """
    if not isinstance(spec, dict):
        raise ValueError("recurrence must be an object")
    cadence = str(spec.get("cadence") or "").strip()
    if cadence not in RECURRENCE_CADENCES:
        raise ValueError(f"cadence must be one of {sorted(RECURRENCE_CADENCES)}")
    anchor_raw = str(spec.get("anchor_date") or fallback_anchor or "").strip()
    if not anchor_raw:
        raise ValueError("anchor_date is required (YYYY-MM-DD)")
    anchor = parse_iso_date(anchor_raw)

    end_type = str(spec.get("end_type") or "never").strip()
    if end_type not in END_TYPES:
        raise ValueError(f"end_type must be one of {sorted(END_TYPES)}")

    end_date: Optional[str] = None
    occurrences_remaining: Optional[int] = None
    if end_type == "until":
        end_raw = str(spec.get("end_date") or "").strip()
        if not end_raw:
            raise ValueError("end_date is required when end_type='until'")
        end_d = parse_iso_date(end_raw)
        if end_d < anchor:
            raise ValueError("end_date must be on or after anchor_date")
        end_date = _fmt(end_d)
    elif end_type == "count":
        raw = spec.get("occurrences_remaining")
        if raw is None:
            raw = spec.get("count")
        try:
            n = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("occurrences_remaining must be a positive integer") from exc
        if n <= 0:
            raise ValueError("occurrences_remaining must be at least 1")
        occurrences_remaining = n

    pre_raw = spec.get("pre_generate_count")
    try:
        pre_generate_count = int(pre_raw) if pre_raw is not None else 0
    except (TypeError, ValueError):
        pre_generate_count = 0
    pre_generate_count = max(0, min(12, pre_generate_count))

    series_id = str(spec.get("series_id") or "").strip() or None

    return {
        "cadence": cadence,
        "anchor_date": _fmt(anchor),
        "end_type": end_type,
        "end_date": end_date,
        "occurrences_remaining": occurrences_remaining,
        "series_id": series_id,
        "pre_generate_count": pre_generate_count,
    }


def should_spawn_next(rec: dict) -> bool:
    """Given a normalised recurrence spec, return whether a *further*
    occurrence should be spawned when the current one completes.

    Note: this does NOT check the calendar — the caller must also verify
    that `next_occurrence(...)` is <= `end_date`.
    """
    if not rec:
        return False
    et = rec.get("end_type") or "never"
    if et == "never":
        return True
    if et == "count":
        n = rec.get("occurrences_remaining")
        try:
            return int(n) > 1
        except (TypeError, ValueError):
            return False
    if et == "until":
        return True  # end_date check deferred to caller
    return False


def next_date_str(current_due: str, rec: dict, *, today: Optional[_date] = None) -> Optional[str]:
    """Return the next occurrence's YYYY-MM-DD after `current_due`, or None
    if the series has reached its end.

    The next date is `step(current_due)`; if the result violates the end
    condition (past `end_date`), return None.
    """
    if not rec:
        return None
    cadence = rec.get("cadence")
    if cadence not in RECURRENCE_CADENCES:
        return None
    try:
        cur = parse_iso_date(current_due)
    except ValueError:
        # If the current task has no valid due_date, fall back to anchor+step
        anchor_raw = rec.get("anchor_date") or ""
        try:
            cur = parse_iso_date(anchor_raw)
        except ValueError:
            return None
    nxt = step(cur, cadence)
    et = rec.get("end_type") or "never"
    if et == "until":
        end_raw = rec.get("end_date")
        if end_raw:
            try:
                end_d = parse_iso_date(end_raw)
                if nxt > end_d:
                    return None
            except ValueError:
                pass
    return _fmt(nxt)


__all__ = [
    "RECURRENCE_CADENCES",
    "LEGACY_CHECKIN_CADENCES",
    "EXTENDED_CHECKIN_CADENCES",
    "END_TYPES",
    "parse_iso_date",
    "step",
    "next_occurrence",
    "occurrences_between",
    "is_active_period",
    "normalise_recurrence",
    "should_spawn_next",
    "next_date_str",
]
