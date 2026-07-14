"""Portfolio Manager backend service.

Owns CRUD for four collections and exposes derived calculations for time and
money capacity. This module is the SOLE owner of read/write operations for:

    * time_commitments
    * financial_accounts
    * monthly_money_commitments
    * resource_allocations

The Portfolio Manager does not create Portfolio Goals, Portfolio Tasks or any
parallel hierarchy. Existing Domain -> Goal -> Expected Outcome -> Task ->
Check-in architecture remains authoritative. Portfolio rows only *reference*
existing Hymn objects via (owner_type, owner_id) pairs, with owner_type
strictly limited to {task, project, knowledge_journey, standalone}.

This iteration stores facts and computes derived state. It does not schedule,
recommend, warn, or auto-allocate.

Money storage
-------------
All monetary values (`financial_accounts.current_value`,
`monthly_money_commitments.amount`, and `resource_type=money`
`resource_allocations.quantity`) are handled as `decimal.Decimal` end to end
and persisted as MongoDB `Decimal128`. No binary float ever touches the
database or the JSON response — money values are serialised as decimal
strings that preserve the precision supplied by the caller. `NaN`,
`Infinity`, and negative values are rejected with HTTP 400.
"""

from __future__ import annotations

import re
import uuid
from datetime import date as date_type, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, List, Optional, Tuple

from bson.decimal128 import Decimal128
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

# Late import within functions to keep the router module import-cycle safe.
# db and get_current_user come from `deps` — a small proxy module that resolves
# to server.get_current_user at request time, so this file does NOT need to
# import server at module load and can be imported by tests independently.
from deps import get_current_user, get_db  # noqa: E402


class _DBProxy:
    """Lazy proxy to server.db. Resolves on first attribute access."""

    __slots__ = ()

    def __getattr__(self, name: str):
        return getattr(get_db(), name)

    def __getitem__(self, name: str):
        return get_db()[name]


db = _DBProxy()

# ----------------------------------------------------------------------------
# Constants — enums as tuples so we can validate cheaply and reuse in tests.
# ----------------------------------------------------------------------------

DAY_OF_WEEK = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

TIME_COMMITMENT_TYPES = (
    "sleep", "work", "commute", "study", "meal", "caregiving",
    "household", "health", "personal", "other",
)
FLEXIBILITY = ("fixed", "flexible")
COMMITMENT_SOURCE_TYPES = (
    "onboarding", "manual", "task", "project", "knowledge_journey", "system",
)

ASSET_ACCOUNT_TYPES = (
    "cash", "bank", "fixed_deposit", "recurring_deposit", "mutual_fund",
    "stock", "bond", "crypto", "gold", "real_estate", "other_asset",
)
LIABILITY_ACCOUNT_TYPES = (
    "credit_card", "personal_loan", "home_loan", "vehicle_loan", "other_liability",
)
ACCOUNT_TYPES = ASSET_ACCOUNT_TYPES + LIABILITY_ACCOUNT_TYPES
LIQUIDITY_TYPES = ("liquid", "semi_liquid", "illiquid")

MONEY_COMMITMENT_TYPES = ("income", "expense", "saving", "investment", "debt_payment", "other")

RESOURCE_TYPES = ("time", "money")
ALLOCATION_MODES = ("one_time", "recurring")
ALLOCATION_UNITS = ("minutes", "currency")
ALLOCATION_STATUSES = ("proposed", "reserved", "consumed", "released", "cancelled")

OWNER_TYPES = ("task", "project", "knowledge_journey", "standalone")

# Maps every non-standalone owner_type to the Mongo collection that must
# contain a row with matching (id, user_id). Standalone bypasses this check.
_OWNER_COLLECTIONS = {
    "task": "tasks",
    "project": "projects",
    "knowledge_journey": "knowledge_journeys",
}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")

# Quantum used only for serialising *derived* money aggregates so JSON does
# not leak binary floats. Individual stored values keep the exact precision
# supplied by the caller (no rounding).
_MONEY_OUTPUT_QUANTUM = Decimal("0.01")


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hhmm_to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _parse_date(s: str) -> date_type:
    y, m, d = s.split("-")
    return date_type(int(y), int(m), int(d))


def _weekday_name(d: date_type) -> str:
    return DAY_OF_WEEK[d.weekday()]


def _require(condition: bool, msg: str) -> None:
    if not condition:
        raise HTTPException(status_code=400, detail=msg)


def _require_in(value: str, choices: Tuple[str, ...], field: str) -> None:
    if value not in choices:
        raise HTTPException(
            status_code=400,
            detail=f"{field} must be one of {list(choices)}",
        )


def _require_date_str(value: Optional[str], field: str, required: bool = True) -> None:
    if value is None or value == "":
        if required:
            raise HTTPException(status_code=400, detail=f"{field} is required (YYYY-MM-DD)")
        return
    if not _DATE_RE.match(value):
        raise HTTPException(status_code=400, detail=f"{field} must be YYYY-MM-DD")
    try:
        _parse_date(value)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"{field} is not a valid date: {exc}") from exc


def _require_month_str(value: Optional[str], field: str, required: bool = True) -> None:
    if value is None or value == "":
        if required:
            raise HTTPException(status_code=400, detail=f"{field} is required (YYYY-MM)")
        return
    if not _MONTH_RE.match(value):
        raise HTTPException(status_code=400, detail=f"{field} must be YYYY-MM")


def _require_time_str(value: Optional[str], field: str, required: bool = True) -> None:
    if value is None or value == "":
        if required:
            raise HTTPException(status_code=400, detail=f"{field} is required (HH:mm)")
        return
    if not _TIME_RE.match(value):
        raise HTTPException(status_code=400, detail=f"{field} must be HH:mm")


def _require_currency(value: Optional[str], field: str, required: bool = True) -> None:
    if value is None or value == "":
        if required:
            raise HTTPException(status_code=400, detail=f"{field} is required (ISO 4217)")
        return
    if not _CURRENCY_RE.match(value):
        raise HTTPException(status_code=400, detail=f"{field} must be an ISO 4217 3-letter code")


# ---------------- Decimal / money plumbing ----------------

def _parse_money_input(value: Any, field: str) -> Decimal:
    """Parse an incoming JSON numeric or string into a non-negative finite Decimal.

    - Booleans are rejected outright (JSON booleans are never a valid amount).
    - Floats/ints are converted via `str(...)` so we never route through a
      binary float representation twice.
    - Strings must parse cleanly. Whitespace is stripped.
    - NaN, Infinity, and negative values are rejected with HTTP 400.
    """
    if value is None:
        raise HTTPException(status_code=400, detail=f"{field} is required")
    if isinstance(value, bool):
        raise HTTPException(status_code=400, detail=f"{field} must be a decimal number")
    if isinstance(value, Decimal):
        d = value
    elif isinstance(value, Decimal128):
        d = value.to_decimal()
    elif isinstance(value, (int, float)):
        d = Decimal(str(value))
    elif isinstance(value, str):
        s = value.strip()
        if not s:
            raise HTTPException(status_code=400, detail=f"{field} is required")
        try:
            d = Decimal(s)
        except (InvalidOperation, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"{field} must be a valid decimal") from exc
    else:
        raise HTTPException(status_code=400, detail=f"{field} must be a decimal number")

    if d.is_nan() or d.is_infinite():
        raise HTTPException(status_code=400, detail=f"{field} must be a finite number")
    if d < 0:
        raise HTTPException(status_code=400, detail=f"{field} must be zero or positive")
    return d


def _dec_to_str(d: Decimal) -> str:
    """Serialise a Decimal without scientific notation while preserving precision."""
    # Decimal.__str__ can produce scientific notation for tiny/huge exponents.
    # Format with 'f' to guarantee plain decimal notation, but only when the
    # exponent is negative (fractional). For integer Decimals, keep the plain
    # form so `Decimal("100")` -> "100" (not "100.0").
    if d == d.to_integral_value() and d.as_tuple().exponent >= 0:
        return format(d, "f")
    return format(d.normalize() if False else d, "f")


def _money_to_stored(value: Any, field: str) -> Decimal128:
    """Parse an incoming money value and return the Decimal128 to persist."""
    d = _parse_money_input(value, field)
    return Decimal128(d)


def _money_from_stored(value: Any) -> str:
    """Convert any stored money representation into a JSON-safe decimal string.

    Handles Decimal128 (canonical), Decimal (in-memory), int/float (legacy
    docs written before this iteration), and None (returned as "0").
    """
    if value is None:
        return "0"
    if isinstance(value, Decimal128):
        return _dec_to_str(value.to_decimal())
    if isinstance(value, Decimal):
        return _dec_to_str(value)
    if isinstance(value, bool):
        # Should never happen for money, but guard against it explicitly.
        return _dec_to_str(Decimal(int(value)))
    if isinstance(value, (int, float)):
        return _dec_to_str(Decimal(str(value)))
    if isinstance(value, str):
        try:
            return _dec_to_str(Decimal(value))
        except (InvalidOperation, ValueError):
            return "0"
    return "0"


def _decimal_from_stored(value: Any) -> Decimal:
    """Return the stored value as a Decimal for arithmetic. Never yields float."""
    if value is None:
        return Decimal(0)
    if isinstance(value, Decimal128):
        return value.to_decimal()
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value)
        except (InvalidOperation, ValueError):
            return Decimal(0)
    return Decimal(0)


def _quantize_out(d: Decimal) -> str:
    """Serialise a derived aggregate money value to two-decimal-place string."""
    return _dec_to_str(d.quantize(_MONEY_OUTPUT_QUANTUM))


def compute_time_union_and_overlap(intervals: List[Tuple[int, int]]) -> Tuple[int, int]:
    """Return (union_minutes, overlap_minutes) for a list of [start, end) minute intervals.

    overlap_minutes is the sum of individual lengths minus the union length —
    i.e. the total minutes that get double-counted when intervals overlap. It
    is NOT the length of the intersection.
    """
    if not intervals:
        return 0, 0
    ivs = [(int(s), int(e)) for s, e in intervals if int(e) > int(s)]
    if not ivs:
        return 0, 0
    total = sum(e - s for s, e in ivs)
    ivs.sort()
    merged: List[List[int]] = [[ivs[0][0], ivs[0][1]]]
    for s, e in ivs[1:]:
        if s <= merged[-1][1]:
            if e > merged[-1][1]:
                merged[-1][1] = e
        else:
            merged.append([s, e])
    union = sum(e - s for s, e in merged)
    overlap = total - union
    return union, overlap


# ============================================================================
# Pydantic models
# ============================================================================

# -- Time commitments --------------------------------------------------------
class TimeCommitmentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    day_of_week: str
    start_time: str
    end_time: str
    commitment_type: str
    flexibility: str
    effective_from: str
    effective_until: Optional[str] = None
    source_type: str = "manual"
    source_id: Optional[str] = None
    notes: str = ""


class TimeCommitmentUpdate(BaseModel):
    title: Optional[str] = None
    day_of_week: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    commitment_type: Optional[str] = None
    flexibility: Optional[str] = None
    effective_from: Optional[str] = None
    effective_until: Optional[str] = None
    source_type: Optional[str] = None
    source_id: Optional[str] = None
    notes: Optional[str] = None


class TimeCommitmentResponse(BaseModel):
    id: str
    user_id: str
    title: str
    day_of_week: str
    start_time: str
    end_time: str
    commitment_type: str
    flexibility: str
    effective_from: str
    effective_until: Optional[str] = None
    source_type: str
    source_id: Optional[str] = None
    notes: str
    created_at: str
    updated_at: str


# -- Financial accounts ------------------------------------------------------
# Money-carrying fields are typed loosely as `Any` at the Pydantic layer so
# JSON numbers, JSON strings, and JSON nulls all reach `_parse_money_input`
# unchanged. Strict validation happens in `_validate_financial_account`.
class FinancialAccountCreate(BaseModel):
    account_type: str
    name: str = Field(min_length=1, max_length=200)
    currency: str
    current_value: Any
    liquidity_type: str
    fixed_or_flexible: str
    notes: str = ""


class FinancialAccountUpdate(BaseModel):
    account_type: Optional[str] = None
    name: Optional[str] = None
    currency: Optional[str] = None
    current_value: Optional[Any] = None
    liquidity_type: Optional[str] = None
    fixed_or_flexible: Optional[str] = None
    notes: Optional[str] = None


class FinancialAccountResponse(BaseModel):
    id: str
    user_id: str
    account_type: str
    name: str
    currency: str
    current_value: str  # decimal string; never a binary float
    liquidity_type: str
    fixed_or_flexible: str
    notes: str
    created_at: str
    updated_at: str


# -- Monthly money commitments -----------------------------------------------
class MonthlyMoneyCommitmentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    currency: str
    amount: Any
    commitment_type: str
    fixed_or_flexible: str
    start_month: str
    end_month: Optional[str] = None
    source_type: str = "manual"
    source_id: Optional[str] = None
    notes: str = ""


class MonthlyMoneyCommitmentUpdate(BaseModel):
    title: Optional[str] = None
    currency: Optional[str] = None
    amount: Optional[Any] = None
    commitment_type: Optional[str] = None
    fixed_or_flexible: Optional[str] = None
    start_month: Optional[str] = None
    end_month: Optional[str] = None
    source_type: Optional[str] = None
    source_id: Optional[str] = None
    notes: Optional[str] = None


class MonthlyMoneyCommitmentResponse(BaseModel):
    id: str
    user_id: str
    title: str
    currency: str
    amount: str  # decimal string; never a binary float
    commitment_type: str
    fixed_or_flexible: str
    start_month: str
    end_month: Optional[str] = None
    source_type: str
    source_id: Optional[str] = None
    notes: str
    created_at: str
    updated_at: str


# -- Resource allocations ----------------------------------------------------
class ResourceAllocationCreate(BaseModel):
    resource_type: str
    owner_type: str
    owner_id: Optional[str] = None
    allocation_mode: str
    date: Optional[str] = None
    day_of_week: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    quantity: Any
    unit: str
    currency: Optional[str] = None
    status: str = "proposed"
    fixed_or_flexible: str = "flexible"


class ResourceAllocationUpdate(BaseModel):
    resource_type: Optional[str] = None
    owner_type: Optional[str] = None
    owner_id: Optional[str] = None
    allocation_mode: Optional[str] = None
    date: Optional[str] = None
    day_of_week: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    quantity: Optional[Any] = None
    unit: Optional[str] = None
    currency: Optional[str] = None
    status: Optional[str] = None
    fixed_or_flexible: Optional[str] = None


class ResourceAllocationResponse(BaseModel):
    id: str
    user_id: str
    resource_type: str
    owner_type: str
    owner_id: Optional[str] = None
    allocation_mode: str
    date: Optional[str] = None
    day_of_week: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    # For resource_type=time this is the integer number of minutes serialised
    # as a string ("60"). For resource_type=money it is a decimal string
    # preserving the exact precision supplied by the caller.
    quantity: str
    unit: str
    currency: Optional[str] = None
    status: str
    fixed_or_flexible: str
    created_at: str
    updated_at: str


# -- Derived calculation responses -------------------------------------------
class DailyCommitmentSummary(BaseModel):
    id: str
    title: str
    start_time: str
    end_time: str
    commitment_type: str
    flexibility: str


class DailyTimeCapacityResponse(BaseModel):
    date: str
    day_of_week: str
    total_minutes: int
    committed_minutes: int
    available_minutes: int
    overlapping_minutes: int
    commitments: List[DailyCommitmentSummary]


class WeeklyTimeCapacityResponse(BaseModel):
    week_start_date: str
    days: List[DailyTimeCapacityResponse]


class MonthlyMoneyPositionResponse(BaseModel):
    month: str
    currency: str
    # All money fields are decimal strings (two-decimal-place quantised).
    opening_liquid_assets: str
    planned_income: str
    fixed_outflows: str
    flexible_outflows: str
    planned_savings: str
    planned_investments: str
    # Actual money spent this month in `currency`, summed from checkins with
    # money_spent populated. Subtracted from `available_for_flexible_spending`.
    actual_spending: str
    available_for_flexible_spending: str


# ============================================================================
# Ownership integrity — the referenced object must exist AND belong to the user.
# ============================================================================

async def _validate_owner_reference(user_id: str, owner_type: str, owner_id: Optional[str]) -> None:
    """Ensure the (owner_type, owner_id) pair resolves to a live row owned by user_id.

    * `standalone` -> owner_id must be null. Caller has already normalised it.
    * `task | project | knowledge_journey` -> the row must exist in the
      corresponding collection with matching `user_id`. A missing row and a
      foreign-user row are both rejected with HTTP 400 and an explicit message.
    """
    if owner_type == "standalone":
        # Standalone rows carry no owner_id — nothing to look up.
        return
    coll_name = _OWNER_COLLECTIONS.get(owner_type)
    if coll_name is None:  # Defensive: should never happen post-enum validation.
        raise HTTPException(status_code=400, detail=f"owner_type={owner_type} is not supported")
    if not owner_id:
        raise HTTPException(
            status_code=400,
            detail=f"owner_type={owner_type} requires owner_id",
        )
    row = await db[coll_name].find_one({"id": owner_id, "user_id": user_id}, {"_id": 0, "id": 1})
    if not row:
        raise HTTPException(
            status_code=400,
            detail=(
                f"owner_type={owner_type} references owner_id={owner_id!r}, but no "
                f"matching row exists for this user in '{coll_name}'"
            ),
        )


# ============================================================================
# Validators — enforce the strict rules from the spec.
# ============================================================================

def _validate_time_commitment(body, *, is_create: bool, existing: dict | None = None) -> dict:
    """Return the field patch to persist. Raises HTTPException on any violation."""
    merged = dict(existing or {})
    for k, v in body.dict(exclude_unset=True).items():
        merged[k] = v

    if is_create:
        for req in ("title", "day_of_week", "start_time", "end_time",
                    "commitment_type", "flexibility", "effective_from"):
            _require(merged.get(req) not in (None, ""), f"{req} is required")

    _require_in(merged["day_of_week"], DAY_OF_WEEK, "day_of_week")
    _require_time_str(merged["start_time"], "start_time")
    _require_time_str(merged["end_time"], "end_time")
    _require_in(merged["commitment_type"], TIME_COMMITMENT_TYPES, "commitment_type")
    _require_in(merged["flexibility"], FLEXIBILITY, "flexibility")
    _require_date_str(merged["effective_from"], "effective_from")

    if merged.get("effective_until"):
        _require_date_str(merged["effective_until"], "effective_until", required=False)
        _require(
            _parse_date(merged["effective_until"]) >= _parse_date(merged["effective_from"]),
            "effective_until must be null or on/after effective_from",
        )
    else:
        merged["effective_until"] = None

    start_m = _hhmm_to_minutes(merged["start_time"])
    end_m = _hhmm_to_minutes(merged["end_time"])
    _require(end_m > start_m, "end_time must be later than start_time")
    _require(end_m <= 24 * 60, "commitment may not cross midnight; split into two records instead")

    _require_in(merged.get("source_type", "manual"), COMMITMENT_SOURCE_TYPES, "source_type")
    merged["source_id"] = merged.get("source_id") or None
    merged["notes"] = merged.get("notes") or ""

    return merged


def _validate_financial_account(body, *, is_create: bool, existing: dict | None = None) -> dict:
    merged = dict(existing or {})
    incoming = body.dict(exclude_unset=True)
    for k, v in incoming.items():
        merged[k] = v

    if is_create:
        for req in ("account_type", "name", "currency", "current_value",
                    "liquidity_type", "fixed_or_flexible"):
            _require(merged.get(req) is not None and merged.get(req) != "", f"{req} is required")

    _require_in(merged["account_type"], ACCOUNT_TYPES, "account_type")
    _require_currency(merged["currency"], "currency")
    _require_in(merged["liquidity_type"], LIQUIDITY_TYPES, "liquidity_type")
    _require_in(merged["fixed_or_flexible"], FLEXIBILITY, "fixed_or_flexible")

    # Only touch current_value if the caller sent one (or we're creating).
    # On updates that omit current_value we keep the existing Decimal128.
    if is_create or "current_value" in incoming:
        merged["current_value"] = _money_to_stored(merged.get("current_value"), "current_value")
    merged["notes"] = merged.get("notes") or ""
    return merged


def _validate_money_commitment(body, *, is_create: bool, existing: dict | None = None) -> dict:
    merged = dict(existing or {})
    incoming = body.dict(exclude_unset=True)
    for k, v in incoming.items():
        merged[k] = v

    if is_create:
        for req in ("title", "currency", "amount", "commitment_type",
                    "fixed_or_flexible", "start_month"):
            _require(merged.get(req) is not None and merged.get(req) != "", f"{req} is required")

    _require_currency(merged["currency"], "currency")
    _require_in(merged["commitment_type"], MONEY_COMMITMENT_TYPES, "commitment_type")
    _require_in(merged["fixed_or_flexible"], FLEXIBILITY, "fixed_or_flexible")
    _require_month_str(merged["start_month"], "start_month")
    if merged.get("end_month"):
        _require_month_str(merged["end_month"], "end_month", required=False)
        _require(
            merged["end_month"] >= merged["start_month"],
            "end_month must be null or on/after start_month",
        )
    else:
        merged["end_month"] = None

    if is_create or "amount" in incoming:
        merged["amount"] = _money_to_stored(merged.get("amount"), "amount")
    _require_in(merged.get("source_type", "manual"), COMMITMENT_SOURCE_TYPES, "source_type")
    merged["source_id"] = merged.get("source_id") or None
    merged["notes"] = merged.get("notes") or ""
    return merged


def _validate_allocation(body, *, is_create: bool, existing: dict | None = None) -> dict:
    merged = dict(existing or {})
    incoming = body.dict(exclude_unset=True)
    for k, v in incoming.items():
        merged[k] = v

    if is_create:
        for req in ("resource_type", "owner_type", "allocation_mode",
                    "quantity", "unit", "status", "fixed_or_flexible"):
            _require(merged.get(req) is not None and merged.get(req) != "", f"{req} is required")

    _require_in(merged["resource_type"], RESOURCE_TYPES, "resource_type")
    _require_in(merged["owner_type"], OWNER_TYPES, "owner_type")
    _require_in(merged["allocation_mode"], ALLOCATION_MODES, "allocation_mode")
    _require_in(merged["unit"], ALLOCATION_UNITS, "unit")
    _require_in(merged["status"], ALLOCATION_STATUSES, "status")
    _require_in(merged["fixed_or_flexible"], FLEXIBILITY, "fixed_or_flexible")

    # Standalone: owner_id must be explicitly null. Non-standalone: presence
    # is required here; existence + ownership is checked async in the endpoint.
    if merged["owner_type"] == "standalone":
        _require(merged.get("owner_id") in (None, ""), "owner_type=standalone requires owner_id=null")
        merged["owner_id"] = None
    else:
        _require(merged.get("owner_id"), f"owner_type={merged['owner_type']} requires owner_id")

    # Resource-type-specific rules
    if merged["resource_type"] == "time":
        _require(merged["unit"] == "minutes", "resource_type=time requires unit=minutes")
        _require(merged.get("currency") in (None, ""), "resource_type=time requires currency=null")
        merged["currency"] = None
        _require_time_str(merged.get("start_time"), "start_time")
        _require_time_str(merged.get("end_time"), "end_time")
        s = _hhmm_to_minutes(merged["start_time"])
        e = _hhmm_to_minutes(merged["end_time"])
        _require(e > s, "end_time must be later than start_time")
        expected_qty = e - s
        try:
            qty_int = int(merged["quantity"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="quantity must be numeric")
        _require(
            qty_int == expected_qty,
            f"quantity must equal duration in minutes (expected {expected_qty})",
        )
        merged["quantity"] = qty_int  # stored as int minutes
        if merged["allocation_mode"] == "one_time":
            _require_date_str(merged.get("date"), "date")
            _require(merged.get("day_of_week") in (None, ""), "one_time time allocation requires day_of_week=null")
            merged["day_of_week"] = None
        else:  # recurring
            _require(merged.get("date") in (None, ""), "recurring time allocation requires date=null")
            merged["date"] = None
            _require(merged.get("day_of_week"), "recurring time allocation requires day_of_week")
            _require_in(merged["day_of_week"], DAY_OF_WEEK, "day_of_week")
    else:  # money
        _require(merged["unit"] == "currency", "resource_type=money requires unit=currency")
        _require_currency(merged.get("currency"), "currency")
        _require(merged.get("start_time") in (None, ""), "resource_type=money requires start_time=null")
        _require(merged.get("end_time") in (None, ""), "resource_type=money requires end_time=null")
        merged["start_time"] = None
        merged["end_time"] = None
        # Money quantity: Decimal128 with full validation.
        if is_create or "quantity" in incoming:
            merged["quantity"] = _money_to_stored(merged.get("quantity"), "quantity")
        if merged["allocation_mode"] == "one_time":
            _require_date_str(merged.get("date"), "date")
        else:  # recurring — date may be null
            if merged.get("date"):
                _require_date_str(merged["date"], "date")
        if merged.get("day_of_week"):
            _require_in(merged["day_of_week"], DAY_OF_WEEK, "day_of_week")
        else:
            merged["day_of_week"] = None

    return merged


# ============================================================================
# Response projection helpers — convert stored Decimal128 to strings.
# ============================================================================

def _project_account(doc: dict) -> dict:
    doc = dict(doc)
    doc["current_value"] = _money_from_stored(doc.get("current_value"))
    return doc


def _project_money_commitment(doc: dict) -> dict:
    doc = dict(doc)
    doc["amount"] = _money_from_stored(doc.get("amount"))
    return doc


def _project_allocation(doc: dict) -> dict:
    doc = dict(doc)
    q = doc.get("quantity")
    if doc.get("resource_type") == "money":
        doc["quantity"] = _money_from_stored(q)
    else:
        # Time allocations: integer minutes stored as int; return as string
        # so the response schema stays uniform.
        if isinstance(q, Decimal128):
            doc["quantity"] = _dec_to_str(q.to_decimal())
        elif isinstance(q, Decimal):
            doc["quantity"] = _dec_to_str(q)
        elif q is None:
            doc["quantity"] = "0"
        else:
            doc["quantity"] = str(int(q))
    return doc


# ============================================================================
# Router — every route lives under /api/portfolio.
# ============================================================================

portfolio_router = APIRouter(prefix="/portfolio", tags=["portfolio"])


# ---------------- Time commitments ----------------
@portfolio_router.post("/time-commitments", response_model=TimeCommitmentResponse, status_code=201)
async def create_time_commitment(body: TimeCommitmentCreate, current_user: dict = Depends(get_current_user)):
    payload = _validate_time_commitment(body, is_create=True)
    now = _now()
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": current_user["id"],
        "title": payload["title"].strip(),
        "day_of_week": payload["day_of_week"],
        "start_time": payload["start_time"],
        "end_time": payload["end_time"],
        "commitment_type": payload["commitment_type"],
        "flexibility": payload["flexibility"],
        "effective_from": payload["effective_from"],
        "effective_until": payload.get("effective_until"),
        "source_type": payload.get("source_type", "manual"),
        "source_id": payload.get("source_id"),
        "notes": payload.get("notes", ""),
        "created_at": now,
        "updated_at": now,
    }
    await db.time_commitments.insert_one(doc)
    doc.pop("_id", None)
    return doc


@portfolio_router.get("/time-commitments", response_model=List[TimeCommitmentResponse])
async def list_time_commitments(
    current_user: dict = Depends(get_current_user),
    day_of_week: Optional[str] = None,
    commitment_type: Optional[str] = None,
    flexibility: Optional[str] = None,
    source_type: Optional[str] = None,
):
    q: dict = {"user_id": current_user["id"]}
    if day_of_week:
        _require_in(day_of_week, DAY_OF_WEEK, "day_of_week")
        q["day_of_week"] = day_of_week
    if commitment_type:
        _require_in(commitment_type, TIME_COMMITMENT_TYPES, "commitment_type")
        q["commitment_type"] = commitment_type
    if flexibility:
        _require_in(flexibility, FLEXIBILITY, "flexibility")
        q["flexibility"] = flexibility
    if source_type:
        _require_in(source_type, COMMITMENT_SOURCE_TYPES, "source_type")
        q["source_type"] = source_type
    docs = await db.time_commitments.find(q, {"_id": 0}).to_list(length=5000)
    docs.sort(key=lambda d: (d.get("day_of_week", ""), d.get("start_time", "")))
    return docs


@portfolio_router.put("/time-commitments/{commitment_id}", response_model=TimeCommitmentResponse)
async def update_time_commitment(commitment_id: str, body: TimeCommitmentUpdate, current_user: dict = Depends(get_current_user)):
    existing = await db.time_commitments.find_one({"id": commitment_id, "user_id": current_user["id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Time commitment not found")
    merged = _validate_time_commitment(body, is_create=False, existing=existing)
    merged["updated_at"] = _now()
    if isinstance(merged.get("title"), str):
        merged["title"] = merged["title"].strip()
    await db.time_commitments.update_one(
        {"id": commitment_id, "user_id": current_user["id"]}, {"$set": merged},
    )
    updated = await db.time_commitments.find_one({"id": commitment_id}, {"_id": 0})
    return updated


@portfolio_router.delete("/time-commitments/{commitment_id}", status_code=200)
async def delete_time_commitment(commitment_id: str, current_user: dict = Depends(get_current_user)):
    r = await db.time_commitments.delete_one({"id": commitment_id, "user_id": current_user["id"]})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Time commitment not found")
    return {"detail": "Time commitment deleted"}


# ---------------- Time capacity (derived) ----------------
async def _daily_capacity(user_id: str, day: str) -> DailyTimeCapacityResponse:
    _require_date_str(day, "date")
    d = _parse_date(day)
    wd = _weekday_name(d)
    docs = await db.time_commitments.find(
        {
            "user_id": user_id,
            "day_of_week": wd,
            "effective_from": {"$lte": day},
            "$or": [{"effective_until": None}, {"effective_until": {"$gte": day}}],
        },
        {"_id": 0},
    ).to_list(length=5000)
    intervals = [(_hhmm_to_minutes(x["start_time"]), _hhmm_to_minutes(x["end_time"])) for x in docs]
    committed, overlap = compute_time_union_and_overlap(intervals)
    docs.sort(key=lambda x: x.get("start_time", ""))
    return DailyTimeCapacityResponse(
        date=day,
        day_of_week=wd,
        total_minutes=1440,
        committed_minutes=committed,
        available_minutes=1440 - committed,
        overlapping_minutes=overlap,
        commitments=[
            DailyCommitmentSummary(
                id=x["id"], title=x["title"],
                start_time=x["start_time"], end_time=x["end_time"],
                commitment_type=x["commitment_type"], flexibility=x["flexibility"],
            )
            for x in docs
        ],
    )


@portfolio_router.get("/time-capacity/day", response_model=DailyTimeCapacityResponse)
async def get_daily_time_capacity(
    date: str = Query(..., description="YYYY-MM-DD"),
    current_user: dict = Depends(get_current_user),
):
    return await _daily_capacity(current_user["id"], date)


@portfolio_router.get("/time-capacity/week", response_model=WeeklyTimeCapacityResponse)
async def get_weekly_time_capacity(
    week_start_date: str = Query(..., description="Monday, YYYY-MM-DD"),
    current_user: dict = Depends(get_current_user),
):
    _require_date_str(week_start_date, "week_start_date")
    d = _parse_date(week_start_date)
    _require(d.weekday() == 0, "week_start_date must be a Monday")
    days: List[DailyTimeCapacityResponse] = []
    for i in range(7):
        di = d + timedelta(days=i)
        days.append(await _daily_capacity(current_user["id"], di.isoformat()))
    return WeeklyTimeCapacityResponse(week_start_date=week_start_date, days=days)


# ---------------- Financial accounts ----------------
@portfolio_router.post("/financial-accounts", response_model=FinancialAccountResponse, status_code=201)
async def create_financial_account(body: FinancialAccountCreate, current_user: dict = Depends(get_current_user)):
    payload = _validate_financial_account(body, is_create=True)
    now = _now()
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": current_user["id"],
        "account_type": payload["account_type"],
        "name": payload["name"].strip(),
        "currency": payload["currency"],
        "current_value": payload["current_value"],  # Decimal128
        "liquidity_type": payload["liquidity_type"],
        "fixed_or_flexible": payload["fixed_or_flexible"],
        "notes": payload["notes"],
        "created_at": now,
        "updated_at": now,
    }
    await db.financial_accounts.insert_one(doc)
    doc.pop("_id", None)
    return _project_account(doc)


@portfolio_router.get("/financial-accounts", response_model=List[FinancialAccountResponse])
async def list_financial_accounts(
    current_user: dict = Depends(get_current_user),
    account_type: Optional[str] = None,
    currency: Optional[str] = None,
    liquidity_type: Optional[str] = None,
    fixed_or_flexible: Optional[str] = None,
):
    q: dict = {"user_id": current_user["id"]}
    if account_type:
        _require_in(account_type, ACCOUNT_TYPES, "account_type")
        q["account_type"] = account_type
    if currency:
        _require_currency(currency, "currency", required=False)
        q["currency"] = currency
    if liquidity_type:
        _require_in(liquidity_type, LIQUIDITY_TYPES, "liquidity_type")
        q["liquidity_type"] = liquidity_type
    if fixed_or_flexible:
        _require_in(fixed_or_flexible, FLEXIBILITY, "fixed_or_flexible")
        q["fixed_or_flexible"] = fixed_or_flexible
    docs = await db.financial_accounts.find(q, {"_id": 0}).to_list(length=5000)
    docs.sort(key=lambda d: (d.get("account_type", ""), d.get("name", "")))
    return [_project_account(d) for d in docs]


@portfolio_router.put("/financial-accounts/{account_id}", response_model=FinancialAccountResponse)
async def update_financial_account(account_id: str, body: FinancialAccountUpdate, current_user: dict = Depends(get_current_user)):
    existing = await db.financial_accounts.find_one({"id": account_id, "user_id": current_user["id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Financial account not found")
    merged = _validate_financial_account(body, is_create=False, existing=existing)
    merged["updated_at"] = _now()
    if isinstance(merged.get("name"), str):
        merged["name"] = merged["name"].strip()
    await db.financial_accounts.update_one(
        {"id": account_id, "user_id": current_user["id"]}, {"$set": merged},
    )
    updated = await db.financial_accounts.find_one({"id": account_id}, {"_id": 0})
    return _project_account(updated)


@portfolio_router.delete("/financial-accounts/{account_id}", status_code=200)
async def delete_financial_account(account_id: str, current_user: dict = Depends(get_current_user)):
    r = await db.financial_accounts.delete_one({"id": account_id, "user_id": current_user["id"]})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Financial account not found")
    return {"detail": "Financial account deleted"}


# ---------------- Monthly money commitments ----------------
@portfolio_router.post("/monthly-money-commitments", response_model=MonthlyMoneyCommitmentResponse, status_code=201)
async def create_monthly_money_commitment(body: MonthlyMoneyCommitmentCreate, current_user: dict = Depends(get_current_user)):
    payload = _validate_money_commitment(body, is_create=True)
    now = _now()
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": current_user["id"],
        "title": payload["title"].strip(),
        "currency": payload["currency"],
        "amount": payload["amount"],  # Decimal128
        "commitment_type": payload["commitment_type"],
        "fixed_or_flexible": payload["fixed_or_flexible"],
        "start_month": payload["start_month"],
        "end_month": payload.get("end_month"),
        "source_type": payload.get("source_type", "manual"),
        "source_id": payload.get("source_id"),
        "notes": payload.get("notes", ""),
        "created_at": now,
        "updated_at": now,
    }
    await db.monthly_money_commitments.insert_one(doc)
    doc.pop("_id", None)
    return _project_money_commitment(doc)


@portfolio_router.get("/monthly-money-commitments", response_model=List[MonthlyMoneyCommitmentResponse])
async def list_monthly_money_commitments(
    current_user: dict = Depends(get_current_user),
    currency: Optional[str] = None,
    commitment_type: Optional[str] = None,
    fixed_or_flexible: Optional[str] = None,
    source_type: Optional[str] = None,
):
    q: dict = {"user_id": current_user["id"]}
    if currency:
        _require_currency(currency, "currency", required=False)
        q["currency"] = currency
    if commitment_type:
        _require_in(commitment_type, MONEY_COMMITMENT_TYPES, "commitment_type")
        q["commitment_type"] = commitment_type
    if fixed_or_flexible:
        _require_in(fixed_or_flexible, FLEXIBILITY, "fixed_or_flexible")
        q["fixed_or_flexible"] = fixed_or_flexible
    if source_type:
        _require_in(source_type, COMMITMENT_SOURCE_TYPES, "source_type")
        q["source_type"] = source_type
    docs = await db.monthly_money_commitments.find(q, {"_id": 0}).to_list(length=5000)
    docs.sort(key=lambda d: (d.get("start_month", ""), d.get("title", "")))
    return [_project_money_commitment(d) for d in docs]


@portfolio_router.put("/monthly-money-commitments/{commitment_id}", response_model=MonthlyMoneyCommitmentResponse)
async def update_monthly_money_commitment(commitment_id: str, body: MonthlyMoneyCommitmentUpdate, current_user: dict = Depends(get_current_user)):
    existing = await db.monthly_money_commitments.find_one({"id": commitment_id, "user_id": current_user["id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Monthly money commitment not found")
    merged = _validate_money_commitment(body, is_create=False, existing=existing)
    merged["updated_at"] = _now()
    if isinstance(merged.get("title"), str):
        merged["title"] = merged["title"].strip()
    await db.monthly_money_commitments.update_one(
        {"id": commitment_id, "user_id": current_user["id"]}, {"$set": merged},
    )
    updated = await db.monthly_money_commitments.find_one({"id": commitment_id}, {"_id": 0})
    return _project_money_commitment(updated)


@portfolio_router.delete("/monthly-money-commitments/{commitment_id}", status_code=200)
async def delete_monthly_money_commitment(commitment_id: str, current_user: dict = Depends(get_current_user)):
    r = await db.monthly_money_commitments.delete_one({"id": commitment_id, "user_id": current_user["id"]})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Monthly money commitment not found")
    return {"detail": "Monthly money commitment deleted"}


# ---------------- Money position (derived) ----------------
@portfolio_router.get("/money-position", response_model=MonthlyMoneyPositionResponse)
async def get_monthly_money_position(
    month: str = Query(..., description="YYYY-MM"),
    currency: str = Query(..., description="ISO 4217"),
    current_user: dict = Depends(get_current_user),
):
    _require_month_str(month, "month")
    _require_currency(currency, "currency")

    # Opening liquid assets: liquid asset-type accounts in the given currency.
    accounts = await db.financial_accounts.find(
        {
            "user_id": current_user["id"],
            "currency": currency,
            "liquidity_type": "liquid",
            "account_type": {"$in": list(ASSET_ACCOUNT_TYPES)},
        },
        {"_id": 0},
    ).to_list(length=5000)
    opening_liquid_assets = sum(
        (_decimal_from_stored(a.get("current_value")) for a in accounts),
        Decimal(0),
    )

    # Active monthly commitments for the requested month in that currency.
    active = await db.monthly_money_commitments.find(
        {
            "user_id": current_user["id"],
            "currency": currency,
            "start_month": {"$lte": month},
            "$or": [{"end_month": None}, {"end_month": {"$gte": month}}],
        },
        {"_id": 0},
    ).to_list(length=5000)

    planned_income = Decimal(0)
    fixed_outflows = Decimal(0)
    flexible_outflows = Decimal(0)
    planned_savings = Decimal(0)
    planned_investments = Decimal(0)

    for c in active:
        amt = _decimal_from_stored(c.get("amount"))
        t = c.get("commitment_type")
        flex = c.get("fixed_or_flexible")
        if t == "income":
            planned_income += amt
        elif t == "expense":
            if flex == "fixed":
                fixed_outflows += amt
            else:
                flexible_outflows += amt
        elif t == "debt_payment":
            if flex == "fixed":
                fixed_outflows += amt
            else:
                flexible_outflows += amt
        elif t == "saving":
            planned_savings += amt
        elif t == "investment":
            planned_investments += amt
        # "other" contributes to nothing.

    available = (
        opening_liquid_assets
        + planned_income
        - fixed_outflows
        - flexible_outflows
        - planned_savings
        - planned_investments
    )

    # Actual spending: sum of checkin.money_spent for the requested month +
    # currency. This is treated as a real-time deduction from the available
    # pool so the "available for flexible spending" number reflects reality,
    # not just the plan.
    month_prefix = month  # YYYY-MM
    spend_docs = await db.checkins.find(
        {
            "user_id": current_user["id"],
            "money_currency": currency,
            "money_spent": {"$ne": None},
            "date": {"$regex": f"^{re.escape(month_prefix)}-"},
        },
        {"_id": 0, "money_spent": 1},
    ).to_list(length=20000)
    actual_spending = sum(
        (_decimal_from_stored(x.get("money_spent")) for x in spend_docs),
        Decimal(0),
    )
    available = available - actual_spending

    return MonthlyMoneyPositionResponse(
        month=month,
        currency=currency,
        opening_liquid_assets=_quantize_out(opening_liquid_assets),
        planned_income=_quantize_out(planned_income),
        fixed_outflows=_quantize_out(fixed_outflows),
        flexible_outflows=_quantize_out(flexible_outflows),
        planned_savings=_quantize_out(planned_savings),
        planned_investments=_quantize_out(planned_investments),
        actual_spending=_quantize_out(actual_spending),
        available_for_flexible_spending=_quantize_out(available),
    )


# ---------------- Portfolio setup status (per-user completion gate) ----------------
class PortfolioSetupStatusResponse(BaseModel):
    completed: bool
    completed_at: Optional[str] = None
    reporting_currency: Optional[str] = None
    has_time_commitments: bool
    has_financial_accounts: bool
    has_monthly_money_commitments: bool


class PortfolioSetupStatusUpdate(BaseModel):
    reporting_currency: Optional[str] = None
    completed: Optional[bool] = None


async def _setup_status_dict(user: dict) -> dict:
    """Assemble the read-only projection of a user's Portfolio setup state.

    "Has X" is a simple existence probe against the three CRUD collections so
    the frontend gate can decide whether to allow "Complete Setup" without
    listing the collections themselves.
    """
    uid = user["id"]
    # Use estimated_document_count-style existence probes: find_one is cheap
    # and returns a document or None; we only need the boolean.
    tc = await db.time_commitments.find_one({"user_id": uid}, {"_id": 0, "id": 1})
    fa = await db.financial_accounts.find_one({"user_id": uid}, {"_id": 0, "id": 1})
    mm = await db.monthly_money_commitments.find_one({"user_id": uid}, {"_id": 0, "id": 1})
    return {
        "completed": bool(user.get("portfolio_setup_completed_at")),
        "completed_at": user.get("portfolio_setup_completed_at"),
        "reporting_currency": user.get("portfolio_reporting_currency"),
        "has_time_commitments": tc is not None,
        "has_financial_accounts": fa is not None,
        "has_monthly_money_commitments": mm is not None,
    }


@portfolio_router.get("/setup-status", response_model=PortfolioSetupStatusResponse)
async def get_portfolio_setup_status(current_user: dict = Depends(get_current_user)):
    return await _setup_status_dict(current_user)


@portfolio_router.put("/setup-status", response_model=PortfolioSetupStatusResponse)
async def update_portfolio_setup_status(
    body: PortfolioSetupStatusUpdate,
    current_user: dict = Depends(get_current_user),
):
    incoming = body.dict(exclude_unset=True)
    updates: dict = {}

    # Reporting currency: validate ISO 4217 and persist independently of the
    # completion flag so the setup wizard can save it early.
    if "reporting_currency" in incoming:
        rc = incoming.get("reporting_currency")
        if rc is not None and rc != "":
            _require_currency(rc, "reporting_currency")
            updates["portfolio_reporting_currency"] = rc
        else:
            updates["portfolio_reporting_currency"] = None

    # Completion flag: setting True requires reporting_currency AND at least
    # one row in each of the three Portfolio collections. Setting False
    # clears the timestamp but never deletes user data.
    if "completed" in incoming:
        want_complete = bool(incoming["completed"])
        if want_complete:
            effective_rc = updates.get(
                "portfolio_reporting_currency",
                current_user.get("portfolio_reporting_currency"),
            )
            if not effective_rc:
                raise HTTPException(
                    status_code=400,
                    detail="reporting_currency is required before completing setup",
                )
            probe = await _setup_status_dict({**current_user, **updates})
            if not probe["has_time_commitments"]:
                raise HTTPException(
                    status_code=400,
                    detail="at least one time_commitment is required before completing setup",
                )
            if not probe["has_financial_accounts"]:
                raise HTTPException(
                    status_code=400,
                    detail="at least one financial_account is required before completing setup",
                )
            if not probe["has_monthly_money_commitments"]:
                raise HTTPException(
                    status_code=400,
                    detail="at least one monthly_money_commitment is required before completing setup",
                )
            updates["portfolio_setup_completed_at"] = _now()
        else:
            updates["portfolio_setup_completed_at"] = None

    if updates:
        await db.users.update_one({"id": current_user["id"]}, {"$set": updates})

    refreshed = await db.users.find_one({"id": current_user["id"]}, {"_id": 0})
    return await _setup_status_dict(refreshed or current_user)


# ---------------- Resource allocations ----------------
@portfolio_router.post("/resource-allocations", response_model=ResourceAllocationResponse, status_code=201)
async def create_resource_allocation(body: ResourceAllocationCreate, current_user: dict = Depends(get_current_user)):
    payload = _validate_allocation(body, is_create=True)
    # Ownership integrity: the referenced object must exist AND be owned by
    # the authenticated user. Skipped for standalone allocations.
    await _validate_owner_reference(current_user["id"], payload["owner_type"], payload.get("owner_id"))
    now = _now()
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": current_user["id"],
        "resource_type": payload["resource_type"],
        "owner_type": payload["owner_type"],
        "owner_id": payload.get("owner_id"),
        "allocation_mode": payload["allocation_mode"],
        "date": payload.get("date"),
        "day_of_week": payload.get("day_of_week"),
        "start_time": payload.get("start_time"),
        "end_time": payload.get("end_time"),
        "quantity": payload["quantity"],  # int (time) or Decimal128 (money)
        "unit": payload["unit"],
        "currency": payload.get("currency"),
        "status": payload["status"],
        "fixed_or_flexible": payload["fixed_or_flexible"],
        "created_at": now,
        "updated_at": now,
    }
    await db.resource_allocations.insert_one(doc)
    doc.pop("_id", None)
    return _project_allocation(doc)


@portfolio_router.get("/resource-allocations", response_model=List[ResourceAllocationResponse])
async def list_resource_allocations(
    current_user: dict = Depends(get_current_user),
    resource_type: Optional[str] = None,
    owner_type: Optional[str] = None,
    owner_id: Optional[str] = None,
    allocation_mode: Optional[str] = None,
    date: Optional[str] = None,
    day_of_week: Optional[str] = None,
    currency: Optional[str] = None,
    status: Optional[str] = None,
    fixed_or_flexible: Optional[str] = None,
    unit: Optional[str] = None,
):
    q: dict = {"user_id": current_user["id"]}
    if resource_type:
        _require_in(resource_type, RESOURCE_TYPES, "resource_type")
        q["resource_type"] = resource_type
    if owner_type:
        _require_in(owner_type, OWNER_TYPES, "owner_type")
        q["owner_type"] = owner_type
    if owner_id:
        q["owner_id"] = owner_id
    if allocation_mode:
        _require_in(allocation_mode, ALLOCATION_MODES, "allocation_mode")
        q["allocation_mode"] = allocation_mode
    if date:
        _require_date_str(date, "date", required=False)
        q["date"] = date
    if day_of_week:
        _require_in(day_of_week, DAY_OF_WEEK, "day_of_week")
        q["day_of_week"] = day_of_week
    if currency:
        _require_currency(currency, "currency", required=False)
        q["currency"] = currency
    if status:
        _require_in(status, ALLOCATION_STATUSES, "status")
        q["status"] = status
    if fixed_or_flexible:
        _require_in(fixed_or_flexible, FLEXIBILITY, "fixed_or_flexible")
        q["fixed_or_flexible"] = fixed_or_flexible
    if unit:
        _require_in(unit, ALLOCATION_UNITS, "unit")
        q["unit"] = unit
    docs = await db.resource_allocations.find(q, {"_id": 0}).to_list(length=5000)
    docs.sort(key=lambda d: d.get("created_at", ""), reverse=True)
    return [_project_allocation(d) for d in docs]


@portfolio_router.put("/resource-allocations/{allocation_id}", response_model=ResourceAllocationResponse)
async def update_resource_allocation(allocation_id: str, body: ResourceAllocationUpdate, current_user: dict = Depends(get_current_user)):
    existing = await db.resource_allocations.find_one({"id": allocation_id, "user_id": current_user["id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Resource allocation not found")
    incoming = body.dict(exclude_unset=True)
    merged = _validate_allocation(body, is_create=False, existing=existing)
    # If ownership has changed (either owner_type or owner_id in the payload),
    # revalidate that the new reference exists & is owned by the user.
    if "owner_type" in incoming or "owner_id" in incoming:
        await _validate_owner_reference(current_user["id"], merged["owner_type"], merged.get("owner_id"))
    merged["updated_at"] = _now()
    await db.resource_allocations.update_one(
        {"id": allocation_id, "user_id": current_user["id"]}, {"$set": merged},
    )
    updated = await db.resource_allocations.find_one({"id": allocation_id}, {"_id": 0})
    return _project_allocation(updated)


@portfolio_router.delete("/resource-allocations/{allocation_id}", status_code=200)
async def delete_resource_allocation(allocation_id: str, current_user: dict = Depends(get_current_user)):
    r = await db.resource_allocations.delete_one({"id": allocation_id, "user_id": current_user["id"]})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Resource allocation not found")
    return {"detail": "Resource allocation deleted"}


# ============================================================================
# Index bootstrap — idempotent, called from server.startup_indexes.
# ============================================================================

async def ensure_portfolio_indexes(database) -> None:
    """Idempotent index creation. Safe to call on every startup."""
    # time_commitments
    await database.time_commitments.create_index("id", unique=True)
    await database.time_commitments.create_index("user_id")
    await database.time_commitments.create_index([("user_id", 1), ("day_of_week", 1)])
    await database.time_commitments.create_index(
        [("user_id", 1), ("effective_from", 1), ("effective_until", 1)],
    )

    # financial_accounts
    await database.financial_accounts.create_index("id", unique=True)
    await database.financial_accounts.create_index("user_id")
    await database.financial_accounts.create_index([("user_id", 1), ("currency", 1)])
    await database.financial_accounts.create_index([("user_id", 1), ("account_type", 1)])

    # monthly_money_commitments
    await database.monthly_money_commitments.create_index("id", unique=True)
    await database.monthly_money_commitments.create_index("user_id")
    await database.monthly_money_commitments.create_index(
        [("user_id", 1), ("start_month", 1), ("end_month", 1)],
    )
    await database.monthly_money_commitments.create_index(
        [("user_id", 1), ("currency", 1)],
    )

    # resource_allocations
    await database.resource_allocations.create_index("id", unique=True)
    await database.resource_allocations.create_index("user_id")
    await database.resource_allocations.create_index(
        [("user_id", 1), ("owner_type", 1), ("owner_id", 1)],
    )
    await database.resource_allocations.create_index(
        [("user_id", 1), ("resource_type", 1), ("date", 1)],
    )
    await database.resource_allocations.create_index([("user_id", 1), ("status", 1)])


__all__ = [
    "portfolio_router",
    "ensure_portfolio_indexes",
    "compute_time_union_and_overlap",
    "OWNER_TYPES",
    "DAY_OF_WEEK",
    "TIME_COMMITMENT_TYPES",
    "FLEXIBILITY",
    "COMMITMENT_SOURCE_TYPES",
    "ASSET_ACCOUNT_TYPES",
    "LIABILITY_ACCOUNT_TYPES",
    "ACCOUNT_TYPES",
    "LIQUIDITY_TYPES",
    "MONEY_COMMITMENT_TYPES",
    "RESOURCE_TYPES",
    "ALLOCATION_MODES",
    "ALLOCATION_UNITS",
    "ALLOCATION_STATUSES",
]
