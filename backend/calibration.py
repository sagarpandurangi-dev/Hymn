"""
Behavioural calibration — turn override history into learning signals.

Concept
-------
Every time a user proceeds through a Finance warning we record an
`override_decisions` document. Left alone these are just an audit trail.
This module reads them into a *calibration profile* and, when asked,
softens future decision-assessments so the assessor's tone reflects the
user's demonstrated appetite for warnings that ended up harmless.

Vindication rule
----------------
An override is *vindicated* when its linked commitment eventually
completes without breaching the reservation (`actual_amount <=
reserved_amount`) — i.e. the warning was theatre. It is *regretted*
when the commitment overruns, gets expired, or is cancelled with a
shortfall event recorded against the user in the following 45 days.

Softening threshold
-------------------
For each (axis, value) bucket we compute:
    vindicated / (vindicated + regretted)
When the ratio is ≥ 0.70 and count ≥ 3, we soften the next matching
assessment by one level (severe → warning, warning → safe). Below
these bounds no softening is applied.

Design invariants
-----------------
* Pure function of a list of override docs + assessment context; no DB
  writes here. All persistence lives in `finance_advanced.py`.
* Reads only fields already stored on override_decisions today so
  legacy overrides (before this module existed) still contribute.
* Never *escalates* — calibration only reduces tone. This is by design:
  the safety mechanism is the assessor's own math; calibration just
  changes how loudly it speaks.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SOFTEN_MIN_COUNT: int = 3
SOFTEN_MIN_RATIO: float = 0.70
CLASSIFICATION_ORDER = ["safe", "warning", "severe_risk"]
CLASSIFICATION_SOFTEN = {"severe_risk": "warning", "warning": "safe", "safe": "safe"}
AXES = ("classification", "priority", "domain", "currency")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        # Handle both `Z` and offset suffixes.
        clean = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(clean)
    except (ValueError, TypeError):
        return None


def _within_days(ts: Optional[str], days: int) -> bool:
    dt = _parse_ts(ts)
    if not dt:
        return False
    return (_now_utc() - dt) <= timedelta(days=days)


def _override_axis_values(o: dict) -> dict:
    """Extract the four axis values from an override doc. Missing values fall
    back to a sentinel so buckets don't drop them."""
    fs = o.get("forecast_snapshot") or {}
    # The record_override payload doesn't ship priority/domain/currency
    # directly, so we harvest them from the snapshot (§23 assessment output)
    # and from `affected_commitments[0]` as a proxy when needed.
    priority = fs.get("priority") or fs.get("proposed_priority") or ""
    currency = fs.get("currency") or ""
    if not currency:
        affected = o.get("affected_commitments") or []
        if affected:
            currency = affected[0].get("currency", "") or ""
    domain = fs.get("domain") or o.get("domain") or ""
    return {
        "classification": o.get("warning_classification") or "warning",
        "priority": priority or "unknown",
        "domain": domain or "unknown",
        "currency": currency or "unknown",
    }


# ---------------------------------------------------------------------------
# Profile aggregation
# ---------------------------------------------------------------------------
def compute_profile(overrides: Iterable[dict]) -> dict:
    """Aggregate a list of override docs into a profile.

    Output shape mirrors what the calibration UI renders — clients can
    map it 1:1 to sections. Buckets are sorted deterministically so the
    UI has a stable rendering order.
    """
    total = 0
    by_classification: dict = {"safe": 0, "warning": 0, "severe_risk": 0}
    by_priority: dict = {}
    by_domain: dict = {}
    by_currency: dict = {}
    vindicated = 0
    regretted = 0
    pending = 0
    trend = {"last_90d": 0, "last_180d": 0, "last_365d": 0}

    for o in overrides or []:
        total += 1
        axes = _override_axis_values(o)
        cls = axes["classification"]
        if cls in by_classification:
            by_classification[cls] += 1
        else:
            by_classification[cls] = by_classification.get(cls, 0) + 1

        outcome = (o.get("actual_outcome") or "").lower()
        if outcome == "vindicated":
            vindicated += 1
        elif outcome == "regretted":
            regretted += 1
        else:
            pending += 1

        ts = o.get("decision_timestamp")
        if _within_days(ts, 90):
            trend["last_90d"] += 1
        if _within_days(ts, 180):
            trend["last_180d"] += 1
        if _within_days(ts, 365):
            trend["last_365d"] += 1

        # Per-axis buckets with vindication tallies for the softening rule.
        for axis_name, target in (
            ("priority", by_priority),
            ("domain", by_domain),
            ("currency", by_currency),
        ):
            key = axes[axis_name]
            bucket = target.setdefault(key, {"count": 0, "vindicated": 0, "regretted": 0})
            bucket["count"] += 1
            if outcome == "vindicated":
                bucket["vindicated"] += 1
            elif outcome == "regretted":
                bucket["regretted"] += 1

    return {
        "total": total,
        "by_classification": by_classification,
        "by_priority": _finalise_bucket(by_priority),
        "by_domain": _finalise_bucket(by_domain),
        "by_currency": _finalise_bucket(by_currency),
        "outcomes": {"vindicated": vindicated, "regretted": regretted, "pending": pending},
        "trend": trend,
        "soften_min_count": SOFTEN_MIN_COUNT,
        "soften_min_ratio": SOFTEN_MIN_RATIO,
    }


def _finalise_bucket(raw: dict) -> list:
    """Convert a raw axis dict into a list sorted by count desc, with the
    vindicated ratio and a `softens` flag inline for the UI to render."""
    rows = []
    for key, val in raw.items():
        resolved = int(val["vindicated"]) + int(val["regretted"])
        ratio = (val["vindicated"] / resolved) if resolved > 0 else None
        rows.append({
            "value": key,
            "count": val["count"],
            "vindicated": val["vindicated"],
            "regretted": val["regretted"],
            "vindicated_ratio": round(ratio, 3) if ratio is not None else None,
            "softens": bool(
                val["count"] >= SOFTEN_MIN_COUNT
                and ratio is not None
                and ratio >= SOFTEN_MIN_RATIO
            ),
        })
    rows.sort(key=lambda r: (-r["count"], r["value"]))
    return rows


# ---------------------------------------------------------------------------
# Calibration application
# ---------------------------------------------------------------------------
def calibrate_classification(
    proposal: dict,
    profile: dict,
    *,
    enabled: bool = True,
) -> dict:
    """Given a proposal (dict with `priority`, `currency`, `domain?`,
    `classification`) and a profile, return a small dict describing
    whether calibration softens the classification:

        {
          "applied": bool,
          "original": "warning",
          "calibrated": "safe",
          "reason": "Softened because 5/6 warnings on high-priority
                     items were vindicated in the last 12 months.",
          "matched_axes": ["priority", "currency"],
        }

    If `enabled=False` or the profile has no softening evidence, the
    result marks `applied=False` and `calibrated == original`.
    """
    original = proposal.get("classification") or "safe"
    result = {
        "applied": False,
        "original": original,
        "calibrated": original,
        "reason": None,
        "matched_axes": [],
    }
    if not enabled or original == "safe":
        return result

    matched: list = []
    reasons: list = []

    for axis_name, key, buckets in (
        ("priority", proposal.get("priority") or "", profile.get("by_priority") or []),
        ("currency", proposal.get("currency") or "", profile.get("by_currency") or []),
        ("domain",   proposal.get("domain")   or "", profile.get("by_domain")   or []),
    ):
        row = next((r for r in buckets if r.get("value") == key), None)
        if row and row.get("softens"):
            matched.append(axis_name)
            reasons.append(
                f"{row.get('vindicated', 0)} of {row.get('count', 0)} overrides on "
                f"{axis_name}={key} were vindicated"
            )

    if not matched:
        return result

    calibrated = CLASSIFICATION_SOFTEN.get(original, original)
    result["applied"] = True
    result["calibrated"] = calibrated
    result["matched_axes"] = matched
    result["reason"] = " · ".join(reasons)
    return result


__all__ = [
    "compute_profile",
    "calibrate_classification",
    "SOFTEN_MIN_COUNT",
    "SOFTEN_MIN_RATIO",
    "AXES",
]
