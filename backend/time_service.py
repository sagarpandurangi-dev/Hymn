"""Canonical time-capacity service.

Batch 2B2 — single backend source of truth for time capacity.

Three consumers used to compute weekly / daily availability
independently (portfolio, planning, goal merge) and disagreed with
each other. This module owns the calculation:

* ``hhmm_to_minutes`` — strict parser.
* ``compute_time_union_and_overlap`` — union + overlap over
  [start, end) minute intervals.
* ``load_day_time_capacity`` — recorded commitments + active
  reservations for one date.
* ``load_week_time_capacity`` — the same for seven days starting on
  a Monday.

Rules baked in:

* Money allocations never affect time capacity.
* ``resource_allocations`` count only when
  ``resource_type == 'time'`` AND ``status in {'reserved', 'consumed'}``.
* Baseline and reservation intervals are combined in ONE union so a
  minute that appears in both is occupied exactly once.
* Results describe *recorded uncommitted time*, not guaranteed free
  time — hence ``is_estimate=True`` at the weekly level.

Deliberately importless of FastAPI / routers / planning code so the
service can be reused from anywhere.
"""

from __future__ import annotations

from datetime import date as _date, datetime, timedelta, timezone
from typing import Any, Iterable

__all__ = [
    "hhmm_to_minutes",
    "compute_time_union_and_overlap",
    "load_day_time_capacity",
    "load_week_time_capacity",
]


_DAY_OF_WEEK = (
    "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday",
)


def hhmm_to_minutes(value: str) -> int:
    """Parse ``HH:MM`` into minutes since midnight.

    Accepts ``00:00..23:59`` and, as a boundary sentinel only,
    ``24:00`` (=> 1440). Everything else raises ``ValueError``.
    """
    if not isinstance(value, str):
        raise ValueError(f"time must be a string, got {type(value).__name__}")
    parts = value.split(":")
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        raise ValueError(f"time '{value}' must match HH:MM")
    if len(parts[0]) != 2 or len(parts[1]) != 2:
        raise ValueError(f"time '{value}' must use two-digit HH and MM")
    h = int(parts[0])
    m = int(parts[1])
    if h == 24 and m == 0:
        return 1440
    if not (0 <= h <= 23) or not (0 <= m <= 59):
        raise ValueError(f"time '{value}' out of range (00:00..23:59 or 24:00)")
    return h * 60 + m


def compute_time_union_and_overlap(intervals):
    """Given a list of ``[start, end)`` minute intervals return
    ``(union_minutes, overlap_minutes)``.

    Adjacency (``end == start``) is NOT overlap. All intervals must
    satisfy ``0 <= start < end <= 1440`` — otherwise ``ValueError``.
    """
    if not intervals:
        return 0, 0
    normalised = []
    for iv in intervals:
        if not isinstance(iv, (list, tuple)) or len(iv) != 2:
            raise ValueError(f"interval {iv!r} must be a (start, end) pair")
        s = int(iv[0])
        e = int(iv[1])
        if not (0 <= s < e <= 1440):
            raise ValueError(
                f"interval [{s}, {e}) must satisfy 0 <= start < end <= 1440"
            )
        normalised.append((s, e))
    total = sum(e - s for s, e in normalised)
    normalised.sort()
    merged = [[normalised[0][0], normalised[0][1]]]
    for s, e in normalised[1:]:
        if s < merged[-1][1]:
            if e > merged[-1][1]:
                merged[-1][1] = e
        else:
            merged.append([s, e])
    union = sum(e - s for s, e in merged)
    overlap = total - union
    return union, overlap


def _parse_iso_date(day: str) -> _date:
    if not isinstance(day, str) or len(day) != 10 or day[4] != "-" or day[7] != "-":
        raise ValueError(f"date '{day}' must match YYYY-MM-DD")
    y, m, d = day[:4], day[5:7], day[8:10]
    if not (y.isdigit() and m.isdigit() and d.isdigit()):
        raise ValueError(f"date '{day}' must match YYYY-MM-DD")
    return _date(int(y), int(m), int(d))


def _weekday_name(d: _date) -> str:
    return _DAY_OF_WEEK[d.weekday()]


def _record_interval(record: dict, record_kind: str) -> tuple:
    """Correction 2B2.1 — strict interval extractor.

    Refuses to silently exclude a queried baseline commitment or an
    active reservation because its ``start_time`` / ``end_time`` is
    missing or malformed. Overstating available time by dropping such
    rows is worse than surfacing the data-integrity defect, so this
    helper raises ``RuntimeError`` on any invalid value and lets the
    caller propagate the failure.

    ``record_kind`` is a short label used in the error message to
    identify the collection (``"time_commitment"`` or
    ``"resource_allocation"``).
    """
    record_id = record.get("id", "<unknown>") if isinstance(record, dict) else "<unknown>"
    start_raw = record.get("start_time") if isinstance(record, dict) else None
    end_raw = record.get("end_time") if isinstance(record, dict) else None
    if not isinstance(start_raw, str) or not start_raw:
        raise RuntimeError(
            f"{record_kind} {record_id} is missing a start_time"
        )
    if not isinstance(end_raw, str) or not end_raw:
        raise RuntimeError(
            f"{record_kind} {record_id} is missing an end_time"
        )
    try:
        start = hhmm_to_minutes(start_raw)
    except ValueError as ex:
        raise RuntimeError(
            f"{record_kind} {record_id} has invalid start_time '{start_raw}'"
        ) from ex
    try:
        end = hhmm_to_minutes(end_raw)
    except ValueError as ex:
        raise RuntimeError(
            f"{record_kind} {record_id} has invalid end_time '{end_raw}'"
        ) from ex
    if not (0 <= start < end <= 1440):
        raise RuntimeError(
            f"{record_kind} {record_id} has out-of-range interval "
            f"[{start}, {end}) — must satisfy 0 <= start < end <= 1440"
        )
    return start, end


async def load_day_time_capacity(db, user_id: str, day: str) -> dict:
    """Compute recorded time capacity for a single ISO date.

    Baseline commitments and active reservations are combined into a
    single interval union so a minute recorded in both counts once.
    """
    d = _parse_iso_date(day)
    weekday = _weekday_name(d)

    baseline_docs = await db.time_commitments.find(
        {
            "user_id": user_id,
            "day_of_week": weekday,
            "effective_from": {"$lte": day},
            "$or": [
                {"effective_until": None},
                {"effective_until": {"$gte": day}},
            ],
        },
        {"_id": 0},
    ).to_list(length=5000)

    reservation_docs = await db.resource_allocations.find(
        {
            "user_id": user_id,
            "resource_type": "time",
            "status": {"$in": ["reserved", "consumed"]},
            "$or": [
                {"allocation_mode": "one_time", "date": day},
                {"allocation_mode": "recurring", "day_of_week": weekday},
            ],
        },
        {"_id": 0},
    ).to_list(length=5000)

    baseline_intervals = [
        _record_interval(x, "time_commitment") for x in baseline_docs
    ]
    reservation_intervals = [
        _record_interval(x, "resource_allocation") for x in reservation_docs
    ]

    baseline_union, _b_overlap = compute_time_union_and_overlap(baseline_intervals)
    reservation_union, _r_overlap = compute_time_union_and_overlap(reservation_intervals)
    combined_intervals = baseline_intervals + reservation_intervals
    combined_raw = sum(e - s for s, e in combined_intervals)
    combined_union, _c_overlap = compute_time_union_and_overlap(combined_intervals)
    overlapping = combined_raw - combined_union
    available = 1440 - combined_union
    if available < 0:
        available = 0

    baseline_docs.sort(key=lambda x: x.get("start_time", ""))
    reservation_docs.sort(key=lambda x: (x.get("start_time") or "", x.get("id") or ""))

    return {
        "date": day,
        "day_of_week": weekday,
        "total_minutes": 1440,
        "committed_minutes": combined_union,
        "available_minutes": available,
        "overlapping_minutes": overlapping,
        "baseline_committed_minutes": baseline_union,
        "reserved_minutes": reservation_union,
        "commitments": baseline_docs,
        "reservations": reservation_docs,
    }


async def load_week_time_capacity(
    db, user_id: str, week_start_date: str,
) -> dict:
    """Compute recorded time capacity for the Monday-based week."""
    d = _parse_iso_date(week_start_date)
    if d.weekday() != 0:
        raise ValueError(f"week_start_date '{week_start_date}' must be a Monday")
    days: list = []
    for i in range(7):
        di = d + timedelta(days=i)
        days.append(await load_day_time_capacity(db, user_id, di.isoformat()))
    committed = sum(x["committed_minutes"] for x in days)
    available = sum(x["available_minutes"] for x in days)
    overlapping = sum(x["overlapping_minutes"] for x in days)
    baseline = sum(x["baseline_committed_minutes"] for x in days)
    reserved = sum(x["reserved_minutes"] for x in days)
    return {
        "week_start_date": week_start_date,
        "total_minutes": 10080,
        "committed_minutes": committed,
        "available_minutes": available,
        "overlapping_minutes": overlapping,
        "baseline_committed_minutes": baseline,
        "reserved_minutes": reserved,
        "days": days,
        "capacity_basis": "recorded_commitments_and_active_reservations",
        # Always an estimate — unrecorded sleep, meals, obligations
        # may still occupy some of the "available" minutes.
        "is_estimate": True,
    }
