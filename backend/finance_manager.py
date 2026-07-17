"""Finance Engine — dashboard, forecasting, and decision layer for Hymn.

This module owns every financial calculation for the Finance tab. It reads
from Portfolio-owned sources (`financial_accounts`, `monthly_money_commitments`,
`resource_allocations`) and money-aware Check-ins (`checkins.money_spent`),
and it never duplicates those records into a Finance-only copy.

Finance-owned collections (new):

* ``financial_commitments`` — user-facing Financial Commitment records with
  extended metadata (title, priority, linked task, actual/variance, review
  cadence, state machine). Every Reserved commitment has a matching money
  ``resource_allocation`` row acting as the reservation ledger.
* ``financial_events``     — normalized Actual Financial Events flowing
  through the Event Pipeline (from check-ins, SMS, statements, …). Only
  ``confirmation_status='confirmed'`` events affect Finance calculations.
* ``financial_audit``       — complete append-only audit trail for every
  financial source record and Financial Commitment change.
* ``financial_dedupe_candidates`` — pending user decisions for probable
  duplicate events.

The backend exclusively owns all derived math; frontends must only render
the values this module returns.
"""

from __future__ import annotations

import re
import uuid
from datetime import date as date_type, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, List, Optional

from bson.decimal128 import Decimal128
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from deps import get_current_user, get_db


# ============================================================================
# Router
# ============================================================================
finance_router = APIRouter(prefix="/finance", tags=["finance"])


# ============================================================================
# Constants
# ============================================================================

COMMITMENT_STATES = ("draft", "reserved", "completed", "cancelled", "expired")
PRIORITIES = ("low", "medium", "high", "critical")
CHANGE_SOURCES = (
    "manual", "checkin", "sms", "bank_statement", "credit_card_statement",
    "bank_connection", "system", "reconciliation",
)
AUDIT_ACTIONS = (
    "created", "updated", "cancelled", "completed", "expired", "postponed",
    "reconciled", "reservation_created", "reservation_consumed",
    "reservation_released", "reviewed", "kept_active", "reopened",
)
AUDIT_RECORD_TYPES = (
    "financial_commitment", "financial_account", "monthly_money_commitment",
    "financial_event", "resource_allocation",
)
EVENT_SOURCES = (
    "checkin", "sms", "bank_statement", "credit_card_statement",
    "bank_connection", "manual", "future_integration",
)
EVENT_DIRECTIONS = ("outflow", "inflow")
CONFIRMATION_STATUSES = ("pending", "confirmed", "rejected")
DEDUPE_STATUSES = ("pending", "confirmed_same", "rejected")

# Reserved reasons the backend derives (not user-visible states):
_OVERDUE_STATES = {"reserved", "expired"}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")

_ISO_4217 = frozenset({
    "AED", "AFN", "ALL", "AMD", "ANG", "AOA", "ARS", "AUD", "AWG", "AZN",
    "BAM", "BBD", "BDT", "BGN", "BHD", "BIF", "BMD", "BND", "BOB", "BRL",
    "BSD", "BTN", "BWP", "BYN", "BZD", "CAD", "CDF", "CHF", "CLP", "CNY",
    "COP", "CRC", "CUP", "CVE", "CZK", "DJF", "DKK", "DOP", "DZD", "EGP",
    "ERN", "ETB", "EUR", "FJD", "FKP", "GBP", "GEL", "GHS", "GIP", "GMD",
    "GNF", "GTQ", "GYD", "HKD", "HNL", "HTG", "HUF", "IDR", "ILS", "INR",
    "IQD", "IRR", "ISK", "JMD", "JOD", "JPY", "KES", "KGS", "KHR", "KMF",
    "KPW", "KRW", "KWD", "KYD", "KZT", "LAK", "LBP", "LKR", "LRD", "LSL",
    "LYD", "MAD", "MDL", "MGA", "MKD", "MMK", "MNT", "MOP", "MRU", "MUR",
    "MVR", "MWK", "MXN", "MYR", "MZN", "NAD", "NGN", "NIO", "NOK", "NPR",
    "NZD", "OMR", "PAB", "PEN", "PGK", "PHP", "PKR", "PLN", "PYG", "QAR",
    "RON", "RSD", "RUB", "RWF", "SAR", "SBD", "SCR", "SDG", "SEK", "SGD",
    "SHP", "SLE", "SOS", "SRD", "SSP", "STN", "SVC", "SYP", "SZL", "THB",
    "TJS", "TMT", "TND", "TOP", "TRY", "TTD", "TWD", "TZS", "UAH", "UGX",
    "USD", "UYU", "UZS", "VES", "VND", "VUV", "WST", "XAF", "XCD", "XOF",
    "XPF", "YER", "ZAR", "ZMW", "ZWG",
})

_MONEY_OUT_Q = Decimal("0.01")

# Liquidity buckets — must match Portfolio-defined presets.
LIQUID = "liquid"
SEMI_LIQUID = "semi_liquid"
ILLIQUID = "illiquid"

ASSET_ACCOUNT_TYPES = frozenset({
    "cash", "bank", "fixed_deposit", "recurring_deposit", "mutual_fund",
    "stock", "bond", "crypto", "gold", "real_estate", "other_asset",
})

REVIEW_INTERVAL_DAYS = 15


# ============================================================================
# Helpers
# ============================================================================

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


def _require(cond, msg: str) -> None:
    if not cond:
        raise HTTPException(status_code=400, detail=msg)


def _require_currency(s: Optional[str], field: str = "currency") -> None:
    _require(s and _CURRENCY_RE.match(s), f"{field} must be an ISO 4217 code")
    _require(s in _ISO_4217, f"{field} must be a supported ISO 4217 code")


def _require_date_str(s: Optional[str], field: str) -> None:
    _require(s and _DATE_RE.match(s), f"{field} must be YYYY-MM-DD")
    try:
        _parse_date(s)  # type: ignore[arg-type]
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"{field} is not a valid date") from e


def _require_month_str(s: Optional[str], field: str) -> None:
    _require(s and _MONTH_RE.match(s), f"{field} must be YYYY-MM")


def _parse_date(s: str) -> date_type:
    y, m, d = s.split("-")
    return date_type(int(y), int(m), int(d))


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _add_days(iso: str, days: int) -> str:
    return (_parse_date(iso) + timedelta(days=days)).isoformat()


def _month_of(iso: str) -> str:
    return iso[:7]


def _next_month(month: str) -> str:
    y, m = month.split("-")
    yi, mi = int(y), int(m)
    mi += 1
    if mi > 12:
        mi = 1
        yi += 1
    return f"{yi:04d}-{mi:02d}"


def _decimal_from_stored(v: Any) -> Decimal:
    if v is None:
        return Decimal(0)
    if isinstance(v, Decimal128):
        return v.to_decimal()
    if isinstance(v, Decimal):
        return v
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return Decimal(0)


def _money_from_stored(v: Any) -> str:
    if v is None:
        return "0"
    d = _decimal_from_stored(v)
    return format(d, "f")


def _quantize_out(d: Decimal) -> str:
    q = d.quantize(_MONEY_OUT_Q)
    return format(q, "f")


def _money_to_stored(v: Any, field: str) -> Decimal128:
    if v is None or v == "":
        raise HTTPException(status_code=400, detail=f"{field} is required")
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"{field} must be a decimal number") from e
    if not d.is_finite():
        raise HTTPException(status_code=400, detail=f"{field} must be a finite number")
    if d < 0:
        raise HTTPException(status_code=400, detail=f"{field} must be zero or positive")
    return Decimal128(d)


def _require_in(v: Any, choices, field: str) -> None:
    _require(v in choices, f"{field} must be one of {list(choices)}")


# ============================================================================
# Pydantic models
# ============================================================================

class FinancialCommitmentCreate(BaseModel):
    title: str
    description: Optional[str] = ""
    amount: Any
    currency: str
    due_date: str
    priority: str
    domain_id: Optional[str] = None
    goal_id: Optional[str] = None
    project_id: Optional[str] = None
    create_task: bool = False
    task_title: Optional[str] = None
    task_due_date: Optional[str] = None


class FinancialCommitmentUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    amount: Optional[Any] = None
    currency: Optional[str] = None
    due_date: Optional[str] = None
    priority: Optional[str] = None


class FinancialCommitmentResponse(BaseModel):
    id: str
    user_id: str
    title: str
    description: str
    amount: str
    currency: str
    due_date: str
    original_due_date: str
    priority: str
    state: str  # draft | reserved | completed | cancelled | expired
    is_overdue: bool
    domain_id: Optional[str]
    goal_id: Optional[str]
    project_id: Optional[str]
    task_id: Optional[str]
    resource_allocation_id: Optional[str]
    actual_amount: Optional[str] = None
    variance: Optional[str] = None
    unused_reservation: Optional[str] = None
    overrun_amount: Optional[str] = None
    completed_at: Optional[str] = None
    cancelled_at: Optional[str] = None
    postpone_count: int
    last_reviewed_at: Optional[str] = None
    next_review_date: Optional[str] = None
    source: str
    created_at: str
    updated_at: str


class CompletePayload(BaseModel):
    actual_amount: Optional[Any] = None
    actual_event_id: Optional[str] = None
    event_date: Optional[str] = None


class PostponePayload(BaseModel):
    new_due_date: str


class ReviewPayload(BaseModel):
    decision: str  # keep | complete | cancel | postpone
    new_due_date: Optional[str] = None
    actual_amount: Optional[Any] = None
    actual_event_id: Optional[str] = None


class FinancialEventCreate(BaseModel):
    amount: Any
    currency: str
    direction: str  # outflow | inflow
    event_date: str
    description: Optional[str] = ""
    source: str = "manual"
    source_reference: Optional[str] = None
    confirmation_status: str = "confirmed"  # manual entries default to confirmed
    checkin_id: Optional[str] = None
    commitment_id: Optional[str] = None


class FinancialEventResponse(BaseModel):
    id: str
    user_id: str
    amount: str
    currency: str
    direction: str
    event_date: str
    description: str
    source: str
    source_reference: Optional[str] = None
    confirmation_status: str
    checkin_id: Optional[str] = None
    commitment_id: Optional[str] = None
    created_at: str


class DedupeResolvePayload(BaseModel):
    resolution: str  # same | different
    canonical_event_id: Optional[str] = None  # required when same


# ============================================================================
# Audit trail
# ============================================================================

async def _audit(
    db,
    user_id: str,
    record_type: str,
    record_id: str,
    action: str,
    *,
    source: str = "manual",
    previous_value: Any = None,
    new_value: Any = None,
    related_checkin_id: Optional[str] = None,
    related_task_id: Optional[str] = None,
    related_event_id: Optional[str] = None,
    related_import_id: Optional[str] = None,
    notes: str = "",
) -> None:
    _require_in(source, CHANGE_SOURCES, "source")
    _require_in(action, AUDIT_ACTIONS, "action")
    _require_in(record_type, AUDIT_RECORD_TYPES, "record_type")
    await db.financial_audit.insert_one({
        "id": _uuid(),
        "user_id": user_id,
        "record_type": record_type,
        "record_id": record_id,
        "action": action,
        "timestamp": _now(),
        "source": source,
        "previous_value": previous_value,
        "new_value": new_value,
        "related_checkin_id": related_checkin_id,
        "related_task_id": related_task_id,
        "related_event_id": related_event_id,
        "related_import_id": related_import_id,
        "notes": notes,
    })


@finance_router.get("/audit/{record_type}/{record_id}")
async def get_audit_trail(
    record_type: str,
    record_id: str,
    current_user: dict = Depends(get_current_user),
):
    _require_in(record_type, AUDIT_RECORD_TYPES, "record_type")
    db = get_db()
    docs = await db.financial_audit.find(
        {"user_id": current_user["id"], "record_type": record_type, "record_id": record_id},
        {"_id": 0},
    ).sort("timestamp", -1).to_list(length=5000)
    return {"record_type": record_type, "record_id": record_id, "entries": docs}


# ============================================================================
# Current Financial Position
# ============================================================================

async def _current_position(db, user_id: str) -> dict:
    docs = await db.financial_accounts.find({"user_id": user_id}, {"_id": 0}).to_list(length=5000)
    by_currency: dict = {}
    for d in docs:
        cur = d.get("currency") or ""
        b = by_currency.setdefault(cur, {
            "currency": cur,
            "assets": Decimal(0),
            "liabilities": Decimal(0),
            "liquid": Decimal(0),
            "semi_liquid": Decimal(0),
            "illiquid": Decimal(0),
            "accounts_liquid": [],
            "accounts_semi_liquid": [],
            "accounts_illiquid": [],
            "accounts_asset": [],
            "accounts_liability": [],
        })
        amt = _decimal_from_stored(d.get("current_value"))
        is_asset = d.get("account_type") in ASSET_ACCOUNT_TYPES
        row = {
            "id": d["id"],
            "name": d.get("name") or "",
            "account_type": d.get("account_type"),
            "current_value": _money_from_stored(d.get("current_value")),
            "liquidity_type": d.get("liquidity_type"),
        }
        if is_asset:
            b["assets"] += amt
            b["accounts_asset"].append(row)
            liq = d.get("liquidity_type") or LIQUID
            if liq == LIQUID:
                b["liquid"] += amt
                b["accounts_liquid"].append(row)
            elif liq == SEMI_LIQUID:
                b["semi_liquid"] += amt
                b["accounts_semi_liquid"].append(row)
            else:
                b["illiquid"] += amt
                b["accounts_illiquid"].append(row)
        else:
            b["liabilities"] += amt
            b["accounts_liability"].append(row)

    result_currencies = []
    for cur, b in by_currency.items():
        net = b["assets"] - b["liabilities"]
        result_currencies.append({
            "currency": cur,
            "total_assets": _quantize_out(b["assets"]),
            "total_liabilities": _quantize_out(b["liabilities"]),
            "net_worth": _quantize_out(net),
            "liquid_assets": _quantize_out(b["liquid"]),
            "semi_liquid_assets": _quantize_out(b["semi_liquid"]),
            "illiquid_assets": _quantize_out(b["illiquid"]),
            "accounts_asset": b["accounts_asset"],
            "accounts_liability": b["accounts_liability"],
            "accounts_liquid": b["accounts_liquid"],
            "accounts_semi_liquid": b["accounts_semi_liquid"],
            "accounts_illiquid": b["accounts_illiquid"],
        })
    result_currencies.sort(key=lambda x: x["currency"])
    return {
        "currencies": result_currencies,
        "multi_currency": len(by_currency) > 1,
        "notice": (
            "Cross-currency totals are not combined until currency conversion is enabled."
            if len(by_currency) > 1 else None
        ),
    }


@finance_router.get("/position")
async def get_current_position(current_user: dict = Depends(get_current_user)):
    db = get_db()
    return await _current_position(db, current_user["id"])


# ============================================================================
# Monthly Commitments summary (across a rolling window)
# ============================================================================

async def _monthly_summary(db, user_id: str, month: str, currency: str) -> dict:
    _require_month_str(month, "month")
    _require_currency(currency, "currency")
    active = await db.monthly_money_commitments.find(
        {
            "user_id": user_id,
            "currency": currency,
            "start_month": {"$lte": month},
            "$or": [{"end_month": None}, {"end_month": {"$gte": month}}],
        },
        {"_id": 0},
    ).to_list(length=5000)

    buckets = {
        "income": [], "expense": [], "debt_payment": [], "saving": [],
        "investment": [], "other": [],
    }
    totals = {k: Decimal(0) for k in buckets}
    for c in active:
        t = c.get("commitment_type") or "other"
        if t not in buckets:
            buckets["other"].append(c)
            totals["other"] += _decimal_from_stored(c.get("amount"))
            continue
        row = {
            "id": c["id"],
            "title": c.get("title") or "",
            "amount": _money_from_stored(c.get("amount")),
            "commitment_type": t,
            "fixed_or_flexible": c.get("fixed_or_flexible") or "",
            "start_month": c.get("start_month"),
            "end_month": c.get("end_month"),
        }
        buckets[t].append(row)
        totals[t] += _decimal_from_stored(c.get("amount"))

    free_cash = totals["income"] - (
        totals["expense"] + totals["debt_payment"] + totals["saving"] + totals["investment"]
    )

    return {
        "month": month,
        "currency": currency,
        "recurring_income": _quantize_out(totals["income"]),
        "recurring_expenses": _quantize_out(totals["expense"]),
        "debt_payments": _quantize_out(totals["debt_payment"]),
        "savings": _quantize_out(totals["saving"]),
        "investments": _quantize_out(totals["investment"]),
        "monthly_free_cash": _quantize_out(free_cash),
        "income_items": buckets["income"],
        "expense_items": buckets["expense"],
        "debt_payment_items": buckets["debt_payment"],
        "saving_items": buckets["saving"],
        "investment_items": buckets["investment"],
        "other_items": buckets["other"],
    }


@finance_router.get("/monthly")
async def get_monthly(
    month: str = Query(...),
    currency: str = Query(...),
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    return await _monthly_summary(db, current_user["id"], month, currency)


# ============================================================================
# Financial Commitments (state machine)
# ============================================================================

def _project_commitment(doc: dict) -> dict:
    doc = dict(doc)
    doc["amount"] = _money_from_stored(doc.get("amount"))
    if doc.get("actual_amount") is not None:
        doc["actual_amount"] = _money_from_stored(doc.get("actual_amount"))
    if doc.get("variance") is not None:
        doc["variance"] = _money_from_stored(doc.get("variance"))
    if doc.get("unused_reservation") is not None:
        doc["unused_reservation"] = _money_from_stored(doc.get("unused_reservation"))
    if doc.get("overrun_amount") is not None:
        doc["overrun_amount"] = _money_from_stored(doc.get("overrun_amount"))
    # Derived overdue marker
    doc["is_overdue"] = (
        doc.get("state") in _OVERDUE_STATES and
        doc.get("due_date") is not None and
        doc["due_date"] < _today_iso() and
        doc.get("state") != "cancelled" and
        doc.get("state") != "completed"
    )
    return doc


async def _create_reservation(db, user_id: str, commitment: dict) -> str:
    """Create the money resource_allocation row that acts as the reservation
    ledger for a Reserved Financial Commitment. Returns the allocation id."""
    alloc_id = _uuid()
    now = _now()
    await db.resource_allocations.insert_one({
        "id": alloc_id,
        "user_id": user_id,
        "resource_type": "money",
        "owner_type": "task" if commitment.get("task_id") else "standalone",
        "owner_id": commitment.get("task_id"),
        "allocation_mode": "one_time",
        "date": commitment["due_date"],
        "day_of_week": None,
        "start_time": None,
        "end_time": None,
        "quantity": commitment["amount"],
        "unit": "currency",
        "currency": commitment["currency"],
        "status": "reserved",
        "fixed_or_flexible": "fixed",
        "created_at": now,
        "updated_at": now,
    })
    await _audit(
        db, user_id, "resource_allocation", alloc_id, "reservation_created",
        source="manual",
        new_value={"amount": _money_from_stored(commitment["amount"]),
                   "currency": commitment["currency"]},
    )
    return alloc_id


# ============================================================================
# Schema preparation \u2014 mirror Finance-owned fields onto resource_allocations.
#
# The plan is to let `resource_allocations` become the canonical Financial
# Commitment model in a later iteration. This helper stages every FC field
# on the linked allocation row so a future switch has zero data migration.
#
# No reads, writes, calculations or API contracts consume these mirrored
# fields today. Existing allocation ledger fields (status, date, quantity,
# consumed_amount, released_amount) are left untouched \u2014 the mirror is
# additive only.
# ============================================================================

_FC_MIRROR_KEYS = (
    "title", "description", "amount", "currency",
    "due_date", "original_due_date", "priority", "state",
    "domain_id", "goal_id", "project_id", "task_id",
    "resource_allocation_id",
    "actual_amount", "variance", "unused_reservation", "overrun_amount",
    "completed_at", "cancelled_at",
    "postpone_count", "last_reviewed_at", "next_review_date",
    "source",
)


async def _mirror_fc_to_allocation(db, commitment: dict) -> None:
    """Copy every Finance-owned field from a ``financial_commitments`` doc
    onto its linked ``resource_allocations`` row. Safe to call repeatedly.

    * Never invoked on draft commitments (they have no allocation yet).
    * Idempotent \u2014 same input always produces the same allocation row
      state, with ``fc_mirrored_at`` refreshed each call.
    * Does not touch ledger-only fields on the allocation row.
    """
    alloc_id = commitment.get("resource_allocation_id")
    if not alloc_id:
        return
    payload = {k: commitment.get(k) for k in _FC_MIRROR_KEYS}
    payload["financial_commitment_id"] = commitment.get("id")
    payload["fc_mirrored_at"] = _now()
    await db.resource_allocations.update_one(
        {"id": alloc_id}, {"$set": payload},
    )


async def backfill_fc_mirror_on_allocations(database) -> int:
    """One-shot idempotent backfill: for every existing financial_commitment
    that already has a ``resource_allocation_id``, copy all Finance-owned
    fields onto that allocation. Called at startup after indexes are built.
    Returns the number of rows touched."""
    count = 0
    cursor = database.financial_commitments.find(
        {"resource_allocation_id": {"$ne": None}}, {"_id": 0},
    )
    async for doc in cursor:
        await _mirror_fc_to_allocation(database, doc)
        count += 1
    return count


async def _refresh_and_mirror(db, commitment_id: str) -> None:
    """Re-read a financial_commitment after any mutation and mirror the
    resulting Finance-owned fields onto its linked allocation. All the
    Finance mutation endpoints call this so the allocation row is always
    in lock-step with the commitment doc it represents."""
    fresh = await db.financial_commitments.find_one({"id": commitment_id}, {"_id": 0})
    if fresh:
        await _mirror_fc_to_allocation(db, fresh)


async def _consume_reservation(
    db, user_id: str, allocation_id: str, consumed_amount: Decimal, released_amount: Decimal,
) -> None:
    now = _now()
    await db.resource_allocations.update_one(
        {"id": allocation_id, "user_id": user_id},
        {"$set": {
            "status": "consumed",
            "consumed_amount": Decimal128(consumed_amount),
            "released_amount": Decimal128(released_amount),
            "updated_at": now,
        }},
    )
    await _audit(
        db, user_id, "resource_allocation", allocation_id, "reservation_consumed",
        source="manual",
        new_value={"consumed": _quantize_out(consumed_amount),
                   "released": _quantize_out(released_amount)},
    )


async def _release_reservation(db, user_id: str, allocation_id: str, released_amount: Decimal) -> None:
    now = _now()
    await db.resource_allocations.update_one(
        {"id": allocation_id, "user_id": user_id},
        {"$set": {
            "status": "released",
            "released_amount": Decimal128(released_amount),
            "updated_at": now,
        }},
    )
    await _audit(
        db, user_id, "resource_allocation", allocation_id, "reservation_released",
        source="manual", new_value={"released": _quantize_out(released_amount)},
    )


async def _maybe_create_task(db, user_id: str, commitment: dict, task_title: Optional[str], task_due_date: Optional[str]) -> Optional[str]:
    if not task_title:
        return None
    task_id = _uuid()
    now = _now()
    await db.tasks.insert_one({
        "id": task_id,
        "user_id": user_id,
        "title": task_title,
        "notes": f"Auto-linked to Financial Commitment: {commitment.get('title', '')}",
        "priority": commitment.get("priority", "medium"),
        "status": "todo",
        "due_date": task_due_date or commitment["due_date"],
        "goal_id": commitment.get("goal_id"),
        "project_id": commitment.get("project_id"),
        "expected_outcome_id": None,
        "domain_id": commitment.get("domain_id"),
        "financial_commitment_id": commitment["id"],
        "created_at": now,
        "updated_at": now,
    })
    return task_id


@finance_router.post("/commitments", response_model=FinancialCommitmentResponse, status_code=201)
async def create_commitment(
    body: FinancialCommitmentCreate,
    current_user: dict = Depends(get_current_user),
):
    """Create a Financial Commitment. Always begins in ``draft`` — the client
    must call ``/reserve`` after presenting the decision assessment."""
    db = get_db()
    _require(body.title.strip(), "title is required")
    _require_currency(body.currency, "currency")
    _require_date_str(body.due_date, "due_date")
    _require_in(body.priority, PRIORITIES, "priority")
    stored_amt = _money_to_stored(body.amount, "amount")
    now = _now()
    commitment_id = _uuid()

    task_id: Optional[str] = None
    if body.create_task:
        # Task created up-front so the commitment can carry the link.
        task_id = _uuid()

    doc = {
        "id": commitment_id,
        "user_id": current_user["id"],
        "title": body.title.strip(),
        "description": (body.description or "").strip(),
        "amount": stored_amt,
        "currency": body.currency,
        "due_date": body.due_date,
        "original_due_date": body.due_date,
        "priority": body.priority,
        "state": "draft",
        "domain_id": body.domain_id,
        "goal_id": body.goal_id,
        "project_id": body.project_id,
        "task_id": task_id,
        "resource_allocation_id": None,
        "actual_amount": None,
        "variance": None,
        "unused_reservation": None,
        "overrun_amount": None,
        "completed_at": None,
        "cancelled_at": None,
        "postpone_count": 0,
        "last_reviewed_at": None,
        "next_review_date": None,
        "source": "manual",
        "created_at": now,
        "updated_at": now,
    }
    await db.financial_commitments.insert_one(doc)

    if body.create_task and task_id:
        await db.tasks.insert_one({
            "id": task_id,
            "user_id": current_user["id"],
            "title": (body.task_title or body.title).strip(),
            "notes": f"Auto-linked to Financial Commitment: {body.title.strip()}",
            "priority": body.priority,
            "status": "todo",
            "due_date": body.task_due_date or body.due_date,
            "goal_id": body.goal_id,
            "project_id": body.project_id,
            "expected_outcome_id": None,
            "domain_id": body.domain_id,
            "financial_commitment_id": commitment_id,
            "created_at": now,
            "updated_at": now,
        })

    await _audit(
        db, current_user["id"], "financial_commitment", commitment_id, "created",
        source="manual",
        new_value={"title": doc["title"], "amount": _money_from_stored(stored_amt),
                   "currency": body.currency, "due_date": body.due_date,
                   "priority": body.priority, "task_id": task_id},
    )
    return _project_commitment(doc)


@finance_router.post("/commitments/{commitment_id}/reserve", response_model=FinancialCommitmentResponse)
async def reserve_commitment(commitment_id: str, current_user: dict = Depends(get_current_user)):
    """Confirm a Draft commitment — creates the reservation ledger row and
    transitions state to ``reserved``. This is the only path from draft."""
    db = get_db()
    c = await db.financial_commitments.find_one({"id": commitment_id, "user_id": current_user["id"]}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Financial Commitment not found")
    _require(c.get("state") == "draft", f"Cannot reserve a commitment in state '{c.get('state')}'")

    alloc_id = await _create_reservation(db, current_user["id"], c)
    now = _now()
    next_review = _add_days(_today_iso(), REVIEW_INTERVAL_DAYS)
    await db.financial_commitments.update_one(
        {"id": commitment_id, "user_id": current_user["id"]},
        {"$set": {
            "state": "reserved",
            "resource_allocation_id": alloc_id,
            "next_review_date": next_review,
            "updated_at": now,
        }},
    )
    await _audit(
        db, current_user["id"], "financial_commitment", commitment_id, "reservation_created",
        source="manual", new_value={"state": "reserved", "allocation_id": alloc_id},
    )
    doc = await db.financial_commitments.find_one({"id": commitment_id}, {"_id": 0})
    # Schema-prep mirror onto the new allocation row.
    await _mirror_fc_to_allocation(db, doc or {})
    return _project_commitment(doc)


@finance_router.get("/commitments", response_model=List[FinancialCommitmentResponse])
async def list_commitments(
    state: Optional[str] = Query(None),
    currency: Optional[str] = Query(None),
    include_terminal: bool = Query(True),
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    q: dict = {"user_id": current_user["id"]}
    if state:
        _require_in(state, COMMITMENT_STATES, "state")
        q["state"] = state
    if currency:
        _require_currency(currency, "currency")
        q["currency"] = currency
    if not include_terminal:
        q["state"] = {"$in": ["draft", "reserved", "expired"]}
    # Auto-expire reserved commitments whose due date has passed and no user
    # decision has been recorded. Expiration is *not* a release — it just
    # flips the state so the UI can prompt the user (§10).
    today = _today_iso()
    expired_ids = [d["id"] for d in await db.financial_commitments.find(
        {"user_id": current_user["id"], "state": "reserved", "due_date": {"$lt": today}},
        {"_id": 0, "id": 1},
    ).to_list(length=5000)]
    if expired_ids:
        await db.financial_commitments.update_many(
            {"id": {"$in": expired_ids}},
            {"$set": {"state": "expired", "updated_at": _now()}},
        )
        # Schema-prep mirror for every row we just expired.
        for _cid in expired_ids:
            await _refresh_and_mirror(db, _cid)
    docs = await db.financial_commitments.find(q, {"_id": 0}).to_list(length=5000)
    docs.sort(key=lambda d: (d.get("due_date") or "", d.get("created_at") or ""))
    return [_project_commitment(d) for d in docs]


@finance_router.get("/commitments/{commitment_id}", response_model=FinancialCommitmentResponse)
async def get_commitment(commitment_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    doc = await db.financial_commitments.find_one({"id": commitment_id, "user_id": current_user["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Financial Commitment not found")
    # Lazy auto-expiration on read too.
    if doc.get("state") == "reserved" and (doc.get("due_date") or "") < _today_iso():
        await db.financial_commitments.update_one(
            {"id": commitment_id}, {"$set": {"state": "expired", "updated_at": _now()}},
        )
        await _audit(
            db, current_user["id"], "financial_commitment", commitment_id, "expired",
            source="system", new_value={"state": "expired"},
        )
        doc["state"] = "expired"
        await _mirror_fc_to_allocation(db, doc)
    return _project_commitment(doc)


@finance_router.put("/commitments/{commitment_id}", response_model=FinancialCommitmentResponse)
async def update_commitment(commitment_id: str, body: FinancialCommitmentUpdate, current_user: dict = Depends(get_current_user)):
    """Edit a Draft or Reserved commitment. Terminal states (completed/
    cancelled/expired) are frozen for auditability."""
    db = get_db()
    c = await db.financial_commitments.find_one({"id": commitment_id, "user_id": current_user["id"]}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Financial Commitment not found")
    _require(
        c.get("state") in ("draft", "reserved"),
        f"Cannot edit a commitment in state '{c.get('state')}'",
    )
    update: dict = {}
    prev = {"amount": _money_from_stored(c.get("amount")),
            "currency": c.get("currency"), "due_date": c.get("due_date"),
            "priority": c.get("priority"), "title": c.get("title")}
    if body.title is not None:
        _require(body.title.strip(), "title cannot be empty")
        update["title"] = body.title.strip()
    if body.description is not None:
        update["description"] = body.description.strip()
    if body.amount is not None:
        update["amount"] = _money_to_stored(body.amount, "amount")
    if body.currency is not None:
        _require_currency(body.currency, "currency")
        update["currency"] = body.currency
    if body.due_date is not None:
        _require_date_str(body.due_date, "due_date")
        update["due_date"] = body.due_date
    if body.priority is not None:
        _require_in(body.priority, PRIORITIES, "priority")
        update["priority"] = body.priority
    if not update:
        return _project_commitment(c)
    update["updated_at"] = _now()
    await db.financial_commitments.update_one(
        {"id": commitment_id, "user_id": current_user["id"]}, {"$set": update},
    )
    # If the reservation exists and money-relevant fields changed, mirror the
    # amount/currency/due_date on the allocation row so the reservation ledger
    # stays in sync.
    if c.get("resource_allocation_id") and (
        "amount" in update or "currency" in update or "due_date" in update
    ):
        alloc_update: dict = {"updated_at": _now()}
        if "amount" in update:
            alloc_update["quantity"] = update["amount"]
        if "currency" in update:
            alloc_update["currency"] = update["currency"]
        if "due_date" in update:
            alloc_update["date"] = update["due_date"]
        await db.resource_allocations.update_one(
            {"id": c["resource_allocation_id"]}, {"$set": alloc_update},
        )
    await _audit(
        db, current_user["id"], "financial_commitment", commitment_id, "updated",
        source="manual", previous_value=prev, new_value={k: (v if not isinstance(v, Decimal128) else _money_from_stored(v)) for k, v in update.items()},
    )
    doc = await db.financial_commitments.find_one({"id": commitment_id}, {"_id": 0})
    await _mirror_fc_to_allocation(db, doc or {})
    return _project_commitment(doc)


async def _apply_complete(
    db, user_id: str, c: dict, actual_amount_raw: Any, event_id: Optional[str], event_date_iso: Optional[str],
) -> dict:
    """Shared completion path used by /complete, /expired /complete branch,
    and the linked-task completion prompt. Returns the refreshed commitment."""
    reserved = _decimal_from_stored(c.get("amount"))
    linked_event: Optional[dict] = None
    if event_id:
        linked_event = await db.financial_events.find_one(
            {"id": event_id, "user_id": user_id}, {"_id": 0},
        )
        if not linked_event:
            raise HTTPException(status_code=404, detail="Actual Financial Event not found")
        _require(linked_event.get("currency") == c.get("currency"),
                 "Event currency must match the commitment currency")
        actual = _decimal_from_stored(linked_event.get("amount"))
    else:
        if actual_amount_raw is None or actual_amount_raw == "":
            raise HTTPException(status_code=400, detail="actual_amount is required when no matching event is linked")
        actual_stored = _money_to_stored(actual_amount_raw, "actual_amount")
        actual = _decimal_from_stored(actual_stored)
        # Persist an auto-created event so the actual is counted exactly once
        # and appears in Recent Actual Financial Events.
        linked_event = {
            "id": _uuid(),
            "user_id": user_id,
            "amount": Decimal128(actual),
            "currency": c["currency"],
            "direction": "outflow",
            "event_date": event_date_iso or _today_iso(),
            "description": f"Completion of: {c.get('title', '')}",
            "source": "manual",
            "source_reference": f"commitment:{c['id']}",
            "confirmation_status": "confirmed",
            "checkin_id": None,
            "commitment_id": c["id"],
            "created_at": _now(),
        }
        await db.financial_events.insert_one(dict(linked_event))
        await _audit(
            db, user_id, "financial_event", linked_event["id"], "created",
            source="manual", new_value={"amount": _quantize_out(actual),
                                         "currency": c["currency"], "commitment_id": c["id"]},
        )

    variance = reserved - actual
    unused = variance if variance > 0 else Decimal(0)
    overrun = -variance if variance < 0 else Decimal(0)

    consumed = actual if actual <= reserved else reserved
    released = unused

    # Ledger transitions
    if c.get("resource_allocation_id"):
        await _consume_reservation(
            db, user_id, c["resource_allocation_id"], consumed, released,
        )

    now = _now()
    await db.financial_commitments.update_one(
        {"id": c["id"], "user_id": user_id},
        {"$set": {
            "state": "completed",
            "actual_amount": Decimal128(actual),
            "variance": Decimal128(variance),
            "unused_reservation": Decimal128(unused),
            "overrun_amount": Decimal128(overrun),
            "completed_at": now,
            "updated_at": now,
            "next_review_date": None,
        }},
    )
    await _audit(
        db, user_id, "financial_commitment", c["id"], "completed",
        source="manual",
        new_value={"actual_amount": _quantize_out(actual),
                   "reserved_amount": _quantize_out(reserved),
                   "variance": _quantize_out(variance),
                   "unused_reservation": _quantize_out(unused),
                   "overrun": _quantize_out(overrun),
                   "linked_event_id": linked_event["id"] if linked_event else None},
        related_event_id=linked_event["id"] if linked_event else None,
    )
    fresh = await db.financial_commitments.find_one({"id": c["id"]}, {"_id": 0})
    await _mirror_fc_to_allocation(db, fresh or {})
    return fresh


@finance_router.post("/commitments/{commitment_id}/complete", response_model=FinancialCommitmentResponse)
async def complete_commitment(
    commitment_id: str,
    body: CompletePayload = Body(default_factory=CompletePayload),
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    c = await db.financial_commitments.find_one({"id": commitment_id, "user_id": current_user["id"]}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Financial Commitment not found")
    _require(
        c.get("state") in ("reserved", "expired"),
        f"Only Reserved or Expired commitments can be completed (state={c.get('state')})",
    )
    updated = await _apply_complete(
        db, current_user["id"], c, body.actual_amount, body.actual_event_id, body.event_date,
    )
    return _project_commitment(updated)


@finance_router.post("/commitments/{commitment_id}/cancel", response_model=FinancialCommitmentResponse)
async def cancel_commitment(commitment_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    c = await db.financial_commitments.find_one({"id": commitment_id, "user_id": current_user["id"]}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Financial Commitment not found")
    _require(
        c.get("state") in ("draft", "reserved", "expired"),
        f"Cannot cancel a commitment in state '{c.get('state')}'",
    )
    # Release the full remaining reservation, if any.
    if c.get("resource_allocation_id"):
        released = _decimal_from_stored(c.get("amount"))
        await _release_reservation(db, current_user["id"], c["resource_allocation_id"], released)
        await db.resource_allocations.update_one(
            {"id": c["resource_allocation_id"]},
            {"$set": {"status": "cancelled", "updated_at": _now()}},
        )
    now = _now()
    await db.financial_commitments.update_one(
        {"id": commitment_id, "user_id": current_user["id"]},
        {"$set": {
            "state": "cancelled",
            "cancelled_at": now,
            "updated_at": now,
            "next_review_date": None,
        }},
    )
    await _audit(
        db, current_user["id"], "financial_commitment", commitment_id, "cancelled",
        source="manual",
        new_value={"state": "cancelled",
                   "released_amount": _money_from_stored(c.get("amount"))},
    )
    doc = await db.financial_commitments.find_one({"id": commitment_id}, {"_id": 0})
    await _mirror_fc_to_allocation(db, doc or {})
    return _project_commitment(doc)


@finance_router.post("/commitments/{commitment_id}/postpone", response_model=FinancialCommitmentResponse)
async def postpone_commitment(
    commitment_id: str, body: PostponePayload, current_user: dict = Depends(get_current_user),
):
    db = get_db()
    c = await db.financial_commitments.find_one({"id": commitment_id, "user_id": current_user["id"]}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Financial Commitment not found")
    _require(
        c.get("state") in ("reserved", "expired"),
        f"Cannot postpone a commitment in state '{c.get('state')}'",
    )
    _require_date_str(body.new_due_date, "new_due_date")
    _require(body.new_due_date > _today_iso(), "new_due_date must be in the future")
    now = _now()
    prev_due = c.get("due_date")
    await db.financial_commitments.update_one(
        {"id": commitment_id, "user_id": current_user["id"]},
        {"$set": {
            "state": "reserved",  # postpone always returns to Reserved
            "due_date": body.new_due_date,
            "postpone_count": (c.get("postpone_count") or 0) + 1,
            "next_review_date": _add_days(_today_iso(), REVIEW_INTERVAL_DAYS),
            "updated_at": now,
        }},
    )
    # Mirror new due_date on the reservation row (kept as one_time on that date).
    if c.get("resource_allocation_id"):
        await db.resource_allocations.update_one(
            {"id": c["resource_allocation_id"]},
            {"$set": {"date": body.new_due_date, "status": "reserved", "updated_at": now}},
        )
    await _audit(
        db, current_user["id"], "financial_commitment", commitment_id, "postponed",
        source="manual",
        previous_value={"due_date": prev_due},
        new_value={"due_date": body.new_due_date},
    )
    doc = await db.financial_commitments.find_one({"id": commitment_id}, {"_id": 0})
    await _mirror_fc_to_allocation(db, doc or {})
    return _project_commitment(doc)


@finance_router.post("/commitments/{commitment_id}/keep-active", response_model=FinancialCommitmentResponse)
async def keep_active_commitment(commitment_id: str, current_user: dict = Depends(get_current_user)):
    """Applies to Expired commitments — user chooses to keep the lien alive
    and be asked again next review cycle. The commitment stays in ``expired``
    with an overdue marker; the reservation is preserved."""
    db = get_db()
    c = await db.financial_commitments.find_one({"id": commitment_id, "user_id": current_user["id"]}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Financial Commitment not found")
    _require(c.get("state") == "expired", "Keep-active applies only to Expired commitments")
    now = _now()
    await db.financial_commitments.update_one(
        {"id": commitment_id, "user_id": current_user["id"]},
        {"$set": {
            "last_reviewed_at": now,
            "next_review_date": _add_days(_today_iso(), REVIEW_INTERVAL_DAYS),
            "updated_at": now,
        }},
    )
    await _audit(
        db, current_user["id"], "financial_commitment", commitment_id, "kept_active",
        source="manual", new_value={"state": "expired"},
    )
    doc = await db.financial_commitments.find_one({"id": commitment_id}, {"_id": 0})
    await _mirror_fc_to_allocation(db, doc or {})
    return _project_commitment(doc)


@finance_router.post("/commitments/{commitment_id}/review", response_model=FinancialCommitmentResponse)
async def review_commitment(
    commitment_id: str, body: ReviewPayload, current_user: dict = Depends(get_current_user),
):
    """15-day review cycle (§11). Records the review and takes the requested
    branch — keep / complete / cancel / postpone."""
    db = get_db()
    c = await db.financial_commitments.find_one({"id": commitment_id, "user_id": current_user["id"]}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Financial Commitment not found")
    _require_in(body.decision, ("keep", "complete", "cancel", "postpone"), "decision")

    if body.decision == "keep":
        _require(c.get("state") == "reserved", "Only Reserved commitments can be kept")
        now = _now()
        await db.financial_commitments.update_one(
            {"id": commitment_id, "user_id": current_user["id"]},
            {"$set": {
                "last_reviewed_at": now,
                "next_review_date": _add_days(_today_iso(), REVIEW_INTERVAL_DAYS),
                "updated_at": now,
            }},
        )
        await _audit(
            db, current_user["id"], "financial_commitment", commitment_id, "reviewed",
            source="manual", new_value={"decision": "keep"},
        )
    elif body.decision == "complete":
        c = await _apply_complete(
            db, current_user["id"], c, body.actual_amount, body.actual_event_id, None,
        )
    elif body.decision == "cancel":
        # Delegate to cancel handler logic
        return await cancel_commitment(commitment_id, current_user=current_user)
    elif body.decision == "postpone":
        return await postpone_commitment(
            commitment_id, PostponePayload(new_due_date=body.new_due_date or ""), current_user=current_user,
        )
    doc = await db.financial_commitments.find_one({"id": commitment_id}, {"_id": 0})
    await _mirror_fc_to_allocation(db, doc or {})
    return _project_commitment(doc)


@finance_router.get("/commitments-due-for-review", response_model=List[FinancialCommitmentResponse])
async def commitments_due_for_review(current_user: dict = Depends(get_current_user)):
    db = get_db()
    today = _today_iso()
    docs = await db.financial_commitments.find(
        {
            "user_id": current_user["id"],
            "state": "reserved",
            "$or": [
                {"next_review_date": None},
                {"next_review_date": {"$lte": today}},
            ],
        }, {"_id": 0},
    ).to_list(length=1000)
    return [_project_commitment(d) for d in docs]


# ============================================================================
# Reserved money aggregate (per currency)
# ============================================================================

async def _reserved_totals(db, user_id: str) -> dict:
    """Return per-currency reserved-money totals and the commitments causing
    the lien. Only ``state='reserved'`` counts (Draft doesn't reserve;
    completed/cancelled have already released). Expired still reserves per §10."""
    docs = await db.financial_commitments.find(
        {"user_id": user_id, "state": {"$in": ["reserved", "expired"]}},
        {"_id": 0},
    ).to_list(length=5000)
    per_currency: dict = {}
    for d in docs:
        cur = d.get("currency") or ""
        b = per_currency.setdefault(cur, {"reserved": Decimal(0), "items": []})
        b["reserved"] += _decimal_from_stored(d.get("amount"))
        b["items"].append(_project_commitment(d))
    out = []
    for cur, b in per_currency.items():
        out.append({
            "currency": cur,
            "reserved_total": _quantize_out(b["reserved"]),
            "commitments": b["items"],
        })
    out.sort(key=lambda x: x["currency"])
    return out


@finance_router.get("/reserved")
async def get_reserved(current_user: dict = Depends(get_current_user)):
    db = get_db()
    return {"by_currency": await _reserved_totals(db, current_user["id"])}


# ============================================================================
# Available liquid money (per currency)
# ============================================================================

async def _available_liquidity(db, user_id: str) -> list:
    """Liquid assets minus reserved money and confirmed month-to-date outflows.
    Returned per currency with the contributing breakdown."""
    pos = await _current_position(db, user_id)
    reserved_rows = await _reserved_totals(db, user_id)
    reserved_by_cur = {r["currency"]: _decimal_from_stored(r["reserved_total"]) for r in reserved_rows}

    # Confirmed outflows this month (from financial_events)
    month = _today_iso()[:7]
    events = await db.financial_events.find(
        {
            "user_id": user_id,
            "confirmation_status": "confirmed",
            "direction": "outflow",
            "event_date": {"$regex": f"^{re.escape(month)}-"},
        },
        {"_id": 0, "amount": 1, "currency": 1},
    ).to_list(length=20000)
    outflow_by_cur: dict = {}
    for e in events:
        c = e.get("currency") or ""
        outflow_by_cur[c] = outflow_by_cur.get(c, Decimal(0)) + _decimal_from_stored(e.get("amount"))

    out = []
    for cur_row in pos["currencies"]:
        cur = cur_row["currency"]
        liquid = _decimal_from_stored(cur_row["liquid_assets"])
        reserved = reserved_by_cur.get(cur, Decimal(0))
        mtd_outflow = outflow_by_cur.get(cur, Decimal(0))
        available = liquid - reserved - mtd_outflow
        out.append({
            "currency": cur,
            "liquid_assets": _quantize_out(liquid),
            "reserved": _quantize_out(reserved),
            "month_to_date_outflow": _quantize_out(mtd_outflow),
            "available_unreserved": _quantize_out(available),
        })
    return out


@finance_router.get("/available-liquidity")
async def get_available_liquidity(current_user: dict = Depends(get_current_user)):
    db = get_db()
    return {"by_currency": await _available_liquidity(db, current_user["id"])}


# ============================================================================
# Twelve-month forecast
# ============================================================================

async def _forecast_12_months(db, user_id: str) -> dict:
    """Build a 12-month cash and net-worth forecast per currency.

    Forecast confidence is heuristic and derived on the fly:
    * 'high' when opening liquidity > sum(fixed_outflows + reservations) for
      the entire horizon, no monthly gap goes negative, and the number of
      reserved commitments falling in the horizon is small (< 8);
    * 'medium' when at least one month is positive but tight (available
      unreserved < 1x fixed_outflows for that month);
    * 'low' when any month goes negative.
    """
    pos = await _current_position(db, user_id)
    liquid_by_cur = {c["currency"]: _decimal_from_stored(c["liquid_assets"]) for c in pos["currencies"]}
    assets_by_cur = {c["currency"]: _decimal_from_stored(c["total_assets"]) for c in pos["currencies"]}
    liab_by_cur = {c["currency"]: _decimal_from_stored(c["total_liabilities"]) for c in pos["currencies"]}

    # Reserved commitments per (currency, due_month)
    reserved_docs = await db.financial_commitments.find(
        {"user_id": user_id, "state": {"$in": ["reserved", "expired"]}},
        {"_id": 0},
    ).to_list(length=5000)

    current_month = _today_iso()[:7]
    months = [current_month]
    for _ in range(11):
        months.append(_next_month(months[-1]))

    per_currency: dict = {}
    all_currencies = set(liquid_by_cur.keys())
    for c in reserved_docs:
        all_currencies.add(c.get("currency") or "")

    for cur in sorted(all_currencies):
        # Bucket reserved commitments by month
        reserved_by_month: dict = {m: [] for m in months}
        for c in reserved_docs:
            if c.get("currency") != cur:
                continue
            due_month = _month_of(c.get("due_date") or "")
            if due_month in reserved_by_month:
                reserved_by_month[due_month].append(_project_commitment(c))

        rolling_liquid = liquid_by_cur.get(cur, Decimal(0))
        rolling_net_worth = assets_by_cur.get(cur, Decimal(0)) - liab_by_cur.get(cur, Decimal(0))

        rows = []
        any_negative = False
        any_tight = False
        for m in months:
            summary = await _monthly_summary(db, user_id, m, cur)
            income = _decimal_from_stored(summary["recurring_income"])
            outflows = (
                _decimal_from_stored(summary["recurring_expenses"])
                + _decimal_from_stored(summary["debt_payments"])
                + _decimal_from_stored(summary["savings"])
                + _decimal_from_stored(summary["investments"])
            )
            reserved_this_month = sum(
                (_decimal_from_stored(x["amount"]) for x in reserved_by_month[m]),
                Decimal(0),
            )
            rolling_liquid = rolling_liquid + income - outflows - reserved_this_month
            rolling_net_worth = rolling_net_worth + income - outflows  # reservations don't change net worth
            if rolling_liquid < 0:
                any_negative = True
            if reserved_this_month > 0 and rolling_liquid < outflows:
                any_tight = True
            rows.append({
                "month": m,
                "recurring_income": summary["recurring_income"],
                "recurring_outflows": _quantize_out(outflows),
                "reserved_commitments_amount": _quantize_out(reserved_this_month),
                "reserved_commitment_ids": [x["id"] for x in reserved_by_month[m]],
                "projected_liquid_end_of_month": _quantize_out(rolling_liquid),
                "projected_net_worth_end_of_month": _quantize_out(rolling_net_worth),
                "shortfall": rolling_liquid < 0,
            })

        if any_negative:
            confidence = "low"
        elif any_tight:
            confidence = "medium"
        else:
            confidence = "high"
        per_currency[cur] = {
            "currency": cur,
            "confidence": confidence,
            "months": rows,
        }

    return {
        "generated_at": _now(),
        "by_currency": list(per_currency.values()),
        "multi_currency": len(per_currency) > 1,
    }


@finance_router.get("/forecast")
async def get_forecast(current_user: dict = Depends(get_current_user)):
    db = get_db()
    return await _forecast_12_months(db, current_user["id"])


# ============================================================================
# Scenarios (light — apply one hypothetical delta and re-run forecast math)
# ============================================================================

class ScenarioPayload(BaseModel):
    currency: str
    # Optional lever knobs — all default no-op.
    additional_monthly_expense: Optional[Any] = None
    additional_monthly_income: Optional[Any] = None
    additional_reservation: Optional[Any] = None
    reservation_due_month: Optional[str] = None


@finance_router.post("/scenarios")
async def evaluate_scenario(
    body: ScenarioPayload, current_user: dict = Depends(get_current_user),
):
    db = get_db()
    _require_currency(body.currency, "currency")
    base = await _forecast_12_months(db, current_user["id"])
    target = next((x for x in base["by_currency"] if x["currency"] == body.currency), None)
    if not target:
        return {"currency": body.currency, "confidence": "high", "months": [], "diff": []}
    extra_exp = _decimal_from_stored(body.additional_monthly_expense or 0)
    extra_inc = _decimal_from_stored(body.additional_monthly_income or 0)
    extra_res = _decimal_from_stored(body.additional_reservation or 0)
    res_month = body.reservation_due_month

    rolling_delta_liquid = Decimal(0)
    rolling_delta_nw = Decimal(0)
    rows = []
    for m in target["months"]:
        month_income_delta = extra_inc
        month_outflow_delta = extra_exp
        month_res_delta = extra_res if (res_month and m["month"] == res_month) else Decimal(0)
        rolling_delta_liquid += month_income_delta - month_outflow_delta - month_res_delta
        rolling_delta_nw += month_income_delta - month_outflow_delta
        rows.append({
            "month": m["month"],
            "original_projected_liquid": m["projected_liquid_end_of_month"],
            "scenario_projected_liquid": _quantize_out(
                _decimal_from_stored(m["projected_liquid_end_of_month"]) + rolling_delta_liquid),
            "original_projected_net_worth": m["projected_net_worth_end_of_month"],
            "scenario_projected_net_worth": _quantize_out(
                _decimal_from_stored(m["projected_net_worth_end_of_month"]) + rolling_delta_nw),
        })
    return {"currency": body.currency, "months": rows}


# ============================================================================
# Actual Financial Events
# ============================================================================

async def _dedupe_check(db, user_id: str, e: dict) -> Optional[str]:
    """Return a probable-duplicate event id if one is found. Compares user,
    currency, direction, amount, event_date, description, source_reference."""
    candidates = await db.financial_events.find(
        {
            "user_id": user_id,
            "currency": e["currency"],
            "direction": e["direction"],
            "amount": e["amount"],
            "event_date": e["event_date"],
        }, {"_id": 0, "id": 1, "description": 1, "source": 1, "source_reference": 1},
    ).to_list(length=20)
    if not candidates:
        return None
    # Same source_reference is an exact match.
    for c in candidates:
        if e.get("source_reference") and c.get("source_reference") == e.get("source_reference"):
            return c["id"]
    # Same description AND different source (cross-source likely dup).
    for c in candidates:
        if e.get("description") and c.get("description") == e.get("description") and c.get("source") != e.get("source"):
            return c["id"]
    return None


@finance_router.post("/events", response_model=FinancialEventResponse, status_code=201)
async def create_event(body: FinancialEventCreate, current_user: dict = Depends(get_current_user)):
    db = get_db()
    _require_currency(body.currency, "currency")
    _require_in(body.direction, EVENT_DIRECTIONS, "direction")
    _require_date_str(body.event_date, "event_date")
    _require_in(body.source, EVENT_SOURCES, "source")
    _require_in(body.confirmation_status, CONFIRMATION_STATUSES, "confirmation_status")
    stored_amt = _money_to_stored(body.amount, "amount")

    ev = {
        "id": _uuid(),
        "user_id": current_user["id"],
        "amount": stored_amt,
        "currency": body.currency,
        "direction": body.direction,
        "event_date": body.event_date,
        "description": (body.description or "").strip(),
        "source": body.source,
        "source_reference": body.source_reference,
        "confirmation_status": body.confirmation_status,
        "checkin_id": body.checkin_id,
        "commitment_id": body.commitment_id,
        "created_at": _now(),
    }

    # Deduplication: only flag when the incoming event is not yet confirmed
    # OR when the incoming event is confirmed but a prior confirmed candidate
    # exists. In both cases we insert as ``pending`` and open a dedupe ticket.
    dup_id = await _dedupe_check(db, current_user["id"], ev)
    if dup_id:
        ev["confirmation_status"] = "pending"
        await db.financial_events.insert_one(dict(ev))
        await db.financial_dedupe_candidates.insert_one({
            "id": _uuid(),
            "user_id": current_user["id"],
            "event_a_id": dup_id,
            "event_b_id": ev["id"],
            "status": "pending",
            "created_at": _now(),
            "resolved_at": None,
        })
        await _audit(
            db, current_user["id"], "financial_event", ev["id"], "created",
            source=body.source, new_value={"pending_dedupe_with": dup_id},
        )
    else:
        await db.financial_events.insert_one(dict(ev))
        await _audit(
            db, current_user["id"], "financial_event", ev["id"], "created",
            source=body.source,
            new_value={"amount": _money_from_stored(stored_amt), "currency": body.currency,
                        "direction": body.direction, "event_date": body.event_date},
        )
    ev["amount"] = _money_from_stored(stored_amt)
    return ev


@finance_router.get("/events", response_model=List[FinancialEventResponse])
async def list_events(
    currency: Optional[str] = Query(None),
    confirmation_status: Optional[str] = Query(None),
    limit: int = Query(50, le=500),
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    q: dict = {"user_id": current_user["id"]}
    if currency:
        _require_currency(currency, "currency")
        q["currency"] = currency
    if confirmation_status:
        _require_in(confirmation_status, CONFIRMATION_STATUSES, "confirmation_status")
        q["confirmation_status"] = confirmation_status
    docs = await db.financial_events.find(q, {"_id": 0}).sort("event_date", -1).to_list(length=limit)
    for d in docs:
        d["amount"] = _money_from_stored(d.get("amount"))
    return docs


@finance_router.post("/events/{event_id}/confirm", response_model=FinancialEventResponse)
async def confirm_event(event_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    ev = await db.financial_events.find_one({"id": event_id, "user_id": current_user["id"]}, {"_id": 0})
    if not ev:
        raise HTTPException(status_code=404, detail="Financial Event not found")
    _require(ev.get("confirmation_status") != "confirmed", "Event is already confirmed")
    await db.financial_events.update_one(
        {"id": event_id, "user_id": current_user["id"]},
        {"$set": {"confirmation_status": "confirmed"}},
    )
    await _audit(
        db, current_user["id"], "financial_event", event_id, "reconciled",
        source="reconciliation", new_value={"confirmation_status": "confirmed"},
    )
    ev["confirmation_status"] = "confirmed"
    ev["amount"] = _money_from_stored(ev.get("amount"))
    return ev


@finance_router.post("/events/{event_id}/reject", response_model=FinancialEventResponse)
async def reject_event(event_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    ev = await db.financial_events.find_one({"id": event_id, "user_id": current_user["id"]}, {"_id": 0})
    if not ev:
        raise HTTPException(status_code=404, detail="Financial Event not found")
    await db.financial_events.update_one(
        {"id": event_id, "user_id": current_user["id"]},
        {"$set": {"confirmation_status": "rejected"}},
    )
    await _audit(
        db, current_user["id"], "financial_event", event_id, "reconciled",
        source="reconciliation", new_value={"confirmation_status": "rejected"},
    )
    ev["confirmation_status"] = "rejected"
    ev["amount"] = _money_from_stored(ev.get("amount"))
    return ev


# --------- Deduplication resolution ---------
@finance_router.get("/dedupe-candidates")
async def list_dedupe_candidates(current_user: dict = Depends(get_current_user)):
    db = get_db()
    rows = await db.financial_dedupe_candidates.find(
        {"user_id": current_user["id"], "status": "pending"}, {"_id": 0},
    ).to_list(length=200)
    # Expand referenced events for the client
    out = []
    for r in rows:
        a = await db.financial_events.find_one({"id": r["event_a_id"]}, {"_id": 0})
        b = await db.financial_events.find_one({"id": r["event_b_id"]}, {"_id": 0})
        if a:
            a["amount"] = _money_from_stored(a.get("amount"))
        if b:
            b["amount"] = _money_from_stored(b.get("amount"))
        r["event_a"] = a
        r["event_b"] = b
        out.append(r)
    return out


@finance_router.post("/dedupe-candidates/{candidate_id}/resolve")
async def resolve_dedupe(
    candidate_id: str,
    body: DedupeResolvePayload,
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    row = await db.financial_dedupe_candidates.find_one(
        {"id": candidate_id, "user_id": current_user["id"]}, {"_id": 0},
    )
    if not row:
        raise HTTPException(status_code=404, detail="Deduplication candidate not found")
    _require_in(body.resolution, ("same", "different"), "resolution")

    if body.resolution == "different":
        # Both events remain independent — confirm the pending one.
        await db.financial_events.update_one(
            {"id": row["event_b_id"]}, {"$set": {"confirmation_status": "confirmed"}},
        )
        await db.financial_dedupe_candidates.update_one(
            {"id": candidate_id}, {"$set": {"status": "rejected", "resolved_at": _now()}},
        )
        await _audit(
            db, current_user["id"], "financial_event", row["event_b_id"], "reconciled",
            source="reconciliation", new_value={"dedupe_resolution": "different"},
        )
        return {"detail": "kept both"}

    # same — pick a canonical, retire the other, wire audit
    canonical = body.canonical_event_id or row["event_a_id"]
    other = row["event_b_id"] if canonical == row["event_a_id"] else row["event_a_id"]
    # Confirm canonical, reject the other, link source_reference.
    canonical_doc = await db.financial_events.find_one({"id": canonical}, {"_id": 0})
    other_doc = await db.financial_events.find_one({"id": other}, {"_id": 0})
    if not canonical_doc or not other_doc:
        raise HTTPException(status_code=404, detail="Referenced event missing")
    await db.financial_events.update_one(
        {"id": canonical}, {"$set": {"confirmation_status": "confirmed"}},
    )
    # Retire duplicate: mark rejected and record deduplication ancestry.
    await db.financial_events.update_one(
        {"id": other},
        {"$set": {
            "confirmation_status": "rejected",
            "dedup_of": canonical,
        }},
    )
    await db.financial_dedupe_candidates.update_one(
        {"id": candidate_id}, {"$set": {"status": "confirmed_same", "resolved_at": _now()}},
    )
    await _audit(
        db, current_user["id"], "financial_event", canonical, "reconciled",
        source="reconciliation",
        new_value={"dedupe_resolution": "same", "retired_event_id": other},
    )
    return {"detail": "merged", "canonical_event_id": canonical, "retired_event_id": other}


# ============================================================================
# Task-completion prompt — surface the linked Financial Commitment
# ============================================================================

@finance_router.get("/task-linked-commitment/{task_id}", response_model=Optional[FinancialCommitmentResponse])
async def get_task_linked_commitment(task_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    doc = await db.financial_commitments.find_one(
        {"user_id": current_user["id"], "task_id": task_id}, {"_id": 0},
    )
    if not doc:
        return None
    return _project_commitment(doc)


# ============================================================================
# Recent Actual Financial Events (dashboard section)
# ============================================================================

async def _recent_events(db, user_id: str, limit: int = 20) -> list:
    docs = await db.financial_events.find(
        {"user_id": user_id, "confirmation_status": "confirmed"}, {"_id": 0},
    ).sort([("event_date", -1), ("created_at", -1)]).to_list(length=limit)
    for d in docs:
        d["amount"] = _money_from_stored(d.get("amount"))
    return docs


# ============================================================================
# Unified dashboard endpoint
# ============================================================================

@finance_router.get("/dashboard")
async def get_dashboard(current_user: dict = Depends(get_current_user)):
    """Single endpoint returning everything the Finance tab renders.

    Frontend must call this once per pull-to-refresh and only render the
    values inside — no math on the client.
    """
    db = get_db()
    user_id = current_user["id"]
    # Auto-expire before we compute anything downstream.
    today = _today_iso()
    await db.financial_commitments.update_many(
        {"user_id": user_id, "state": "reserved", "due_date": {"$lt": today}},
        {"$set": {"state": "expired", "updated_at": _now()}},
    )

    position = await _current_position(db, user_id)
    reserved = await _reserved_totals(db, user_id)
    liquidity = await _available_liquidity(db, user_id)
    # Rolling 12-month positions for the primary currency (first found).
    monthly_windows = []
    for cur_row in position["currencies"]:
        cur = cur_row["currency"]
        month = today[:7]
        window = []
        for _ in range(12):
            window.append(await _monthly_summary(db, user_id, month, cur))
            month = _next_month(month)
        monthly_windows.append({"currency": cur, "months": window})
    forecast = await _forecast_12_months(db, user_id)
    events = await _recent_events(db, user_id, 20)
    # Commitments (active + terminal, capped) — client can drill into detail.
    all_commitments = await db.financial_commitments.find(
        {"user_id": user_id}, {"_id": 0},
    ).sort("due_date", 1).to_list(length=500)
    active_commitments = [
        _project_commitment(d) for d in all_commitments
        if d.get("state") in ("draft", "reserved", "expired")
    ]
    terminal_commitments = [
        _project_commitment(d) for d in all_commitments
        if d.get("state") in ("completed", "cancelled")
    ][-50:]

    due_for_review = [
        c for c in active_commitments
        if c.get("state") == "reserved" and (
            c.get("next_review_date") is None or c["next_review_date"] <= today
        )
    ]

    return {
        "position": position,
        "monthly_windows": monthly_windows,
        "reserved": reserved,
        "available_liquidity": liquidity,
        "forecast": forecast,
        "active_commitments": active_commitments,
        "terminal_commitments": terminal_commitments,
        "commitments_due_for_review": due_for_review,
        "recent_events": events,
        "generated_at": _now(),
    }


# ============================================================================
# Index bootstrap
# ============================================================================

async def ensure_finance_indexes(database) -> None:
    await database.financial_commitments.create_index("id", unique=True)
    await database.financial_commitments.create_index("user_id")
    await database.financial_commitments.create_index([("user_id", 1), ("state", 1)])
    await database.financial_commitments.create_index([("user_id", 1), ("due_date", 1)])
    await database.financial_commitments.create_index([("user_id", 1), ("task_id", 1)])

    await database.financial_events.create_index("id", unique=True)
    await database.financial_events.create_index("user_id")
    await database.financial_events.create_index([("user_id", 1), ("event_date", 1)])
    await database.financial_events.create_index([("user_id", 1), ("confirmation_status", 1)])

    await database.financial_audit.create_index("id", unique=True)
    await database.financial_audit.create_index([("user_id", 1), ("record_type", 1), ("record_id", 1)])
    await database.financial_audit.create_index([("user_id", 1), ("timestamp", -1)])

    await database.financial_dedupe_candidates.create_index("id", unique=True)
    await database.financial_dedupe_candidates.create_index([("user_id", 1), ("status", 1)])
