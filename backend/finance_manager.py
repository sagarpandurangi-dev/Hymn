"""Finance Engine — dashboard, forecasting, and decision layer for Hymn.

This module owns every financial calculation for the Finance tab. It reads
from Portfolio-owned sources (`financial_accounts`, `monthly_money_commitments`,
`resource_allocations`) and money-aware Check-ins (`checkins.money_spent`),
and it never duplicates those records into a Finance-only copy.

Finance-owned collections:

* ``resource_allocations`` (``resource_type='money'``) — the SINGLE source
  of truth for every Financial Commitment. Every state — draft, reserved,
  expired, completed, cancelled — lives on a single allocation row keyed by
  ``financial_commitment_id``. Ledger status (``proposed``/``reserved``/
  ``consumed``/``released``/``cancelled``) is co-located with lifecycle
  state on the same row.
* ``financial_commitments`` — LEGACY. No writes go here anymore. The
  collection is retained solely so pre-migration rows remain queryable for
  verification. All reads and writes flow through ``resource_allocations``.
* ``financial_events`` — normalized Actual Financial Events flowing
  through the Event Pipeline (from check-ins, SMS, statements, …). Only
  ``confirmation_status='confirmed'`` events affect Finance calculations.
* ``financial_audit`` — complete append-only audit trail for every
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

COMMITMENT_STATES = ("draft", "reserved", "partial", "completed", "cancelled", "expired")
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
DEDUPE_STATUSES = ("pending", "resolving", "confirmed_same", "rejected")

# Batch 2A: explicit lifecycle statuses for financial events. The
# authoritative money service (money_service.py) applies inflows/outflows
# to an account's snapshot only when the event carries an APPLIED status.
LIFECYCLE_STATUS_PENDING_ACCOUNT = "pending_account_assignment"
LIFECYCLE_STATUS_PENDING_DEDUPE = "pending_deduplication"
LIFECYCLE_STATUS_AWAITING_RECON = "awaiting_reconciliation"
LIFECYCLE_STATUS_MATCHED = "matched"
LIFECYCLE_STATUS_RESOLVED_UNPLANNED = "resolved_unplanned"
LIFECYCLE_STATUS_VOID = "void"
LIFECYCLE_STATUSES = (
    LIFECYCLE_STATUS_PENDING_ACCOUNT,
    LIFECYCLE_STATUS_PENDING_DEDUPE,
    LIFECYCLE_STATUS_AWAITING_RECON,
    LIFECYCLE_STATUS_MATCHED,
    LIFECYCLE_STATUS_RESOLVED_UNPLANNED,
    LIFECYCLE_STATUS_VOID,
)
APPLIED_LIFECYCLE_STATUSES = frozenset({
    LIFECYCLE_STATUS_AWAITING_RECON,
    LIFECYCLE_STATUS_MATCHED,
    LIFECYCLE_STATUS_RESOLVED_UNPLANNED,
})

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


# ---------------------------------------------------------------------------
# Batch 2A: account-linkage validation and lifecycle-status backfill.
# ---------------------------------------------------------------------------

async def _resolve_event_account(
    db, user_id: str, account_id: Optional[str], currency: str,
) -> Optional[dict]:
    """Validate that ``account_id`` (if given) belongs to ``user_id``,
    is in the same currency as the event, and is an ASSET account.

    Batch 2A Correction 1: the current financial-event pipeline does
    NOT support liability-account accounting (no credit-card ledger,
    no negative-balance semantics). Liability account IDs are rejected
    here so a caller cannot silently create a bank/credit event that
    would corrupt the available-money math.

    Rejects:
      * missing account (404)
      * cross-user account (404)
      * currency mismatch (400)
      * liability account_type (400)

    Returns the account document or ``None`` when ``account_id`` is
    null (caller decides what to do)."""
    if not account_id:
        return None
    acct = await db.financial_accounts.find_one(
        {"id": account_id}, {"_id": 0},
    )
    if not acct or acct.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Financial account not found")
    if acct.get("currency") != currency:
        raise HTTPException(
            status_code=400,
            detail=(
                "account_id currency mismatch: account is "
                f"{acct.get('currency')}, event is {currency}"
            ),
        )
    # ASSET_ACCOUNT_TYPES is redeclared inside portfolio_manager. Import
    # locally to avoid a module-import cycle.
    from portfolio_manager import ASSET_ACCOUNT_TYPES as _PM_ASSET
    if acct.get("account_type") not in _PM_ASSET:
        raise HTTPException(
            status_code=400,
            detail=(
                "account_id must reference an ASSET account. Liability "
                "accounts are not supported in the current financial-event "
                "pipeline."
            ),
        )
    return acct


def _default_lifecycle_status(*, direction: str, account_id: Optional[str], commitment_id: Optional[str]) -> str:
    """Compute the initial lifecycle_status for a new event.

    * commitment_id set already => ``matched`` (created via a completion
      flow).
    * account_id present => ``awaiting_reconciliation``.
    * no account_id => ``pending_account_assignment`` (financially
      unapplied until the user assigns an account).
    """
    if commitment_id:
        return LIFECYCLE_STATUS_MATCHED
    if not account_id:
        return LIFECYCLE_STATUS_PENDING_ACCOUNT
    return LIFECYCLE_STATUS_AWAITING_RECON


def _normalise_occurred_at(v: Any) -> Optional[str]:
    """Return an ISO-8601 UTC timestamp string, or ``None`` when the
    caller did not supply a tz-aware datetime we can safely normalise.

    Batch 2A Correction 1: ``occurred_at`` is the ONLY authoritative
    "when did this transaction happen" field. It MUST NOT be silently
    derived from ``created_at`` (that is only when the DB row was
    written). Callers that cannot compute a tz-aware timestamp pass
    ``None`` and the event stays visibly unapplied.
    """
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        if v.tzinfo is None:
            return None
        return v.astimezone(timezone.utc).isoformat()
    if not isinstance(v, str):
        return None
    s = v.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc).isoformat()




# ---------------------------------------------------------------------
# Correction 3 — allocation helpers.
#
# ``financial_events.allocations`` is an embedded array of allocation
# dicts. Each classifies a slice of the parent event to a commitment
# or expected-income record. Allocations NEVER move the account
# balance; the parent event is the sole account-affecting movement.
# ---------------------------------------------------------------------


def _allocation_shape(*, target_type: str, target_id: str, amount_stored: Decimal128,
                       currency: str) -> dict:
    now = _now()
    return {
        "id": _uuid(),
        "target_type": target_type,
        "target_id": target_id,
        "amount": amount_stored,
        "currency": currency,
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }


def _sum_active_allocations(allocations: Any) -> Decimal:
    total = Decimal(0)
    if not isinstance(allocations, list):
        return total
    for a in allocations:
        if a and a.get("status") == "active":
            total += _decimal_from_stored(a.get("amount"))
    return total


def _project_event(ev: dict) -> dict:
    """Public projection of a financial_event — never returns Decimal128
    internals. Sums allocations for allocated/unallocated derived
    fields."""
    out = dict(ev)
    amt_dec = _decimal_from_stored(out.get("amount"))
    out["amount"] = _money_from_stored(out.get("amount"))
    allocated = _sum_active_allocations(out.get("allocations"))
    out["allocated_amount"] = _quantize_out(allocated)
    out["unallocated_amount"] = _quantize_out(amt_dec - allocated)
    projected_allocs: list = []
    for a in out.get("allocations") or []:
        projected_allocs.append({
            **a,
            "amount": _money_from_stored(a.get("amount")),
        })
    out["allocations"] = projected_allocs
    out.setdefault("account_id", None)
    out.setdefault("lifecycle_status", LIFECYCLE_STATUS_PENDING_ACCOUNT)
    out.setdefault("occurred_at", None)
    out.setdefault("occurred_at_precision", None)
    out.setdefault("occurred_at_offset_minutes", None)
    return out


async def _validate_allocation_target(
    db, user_id: str, target_type: str, target_id: str, currency: str,
    direction: str,
) -> dict:
    """Ensure the allocation target belongs to the caller, matches the
    parent event currency, is compatible with the event direction and
    is in an allocatable lifecycle state. Returns the target document.

    Correction 3 rules:
      * ``commitment`` target must be draft/reserved/expired/partial —
        completed/cancelled commitments refuse further allocation.
      * ``expected_income`` target must be not fully received.
    """
    _require_in(target_type, ("commitment", "expected_income"), "target_type")
    if target_type == "commitment":
        if direction != "outflow":
            raise HTTPException(status_code=400, detail="Only outflow events can allocate to commitments")
        doc = await _read_commitment_by_id(db, user_id, target_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Commitment not found")
        state = doc.get("state")
        if state in ("cancelled", "completed"):
            raise HTTPException(
                status_code=409,
                detail=f"Commitment is {state} and cannot receive further allocations",
            )
    else:
        if direction != "inflow":
            raise HTTPException(status_code=400, detail="Only inflow events can allocate to expected income")
        doc = await db.expected_incomes.find_one(
            {"id": target_id, "user_id": user_id}, {"_id": 0},
        )
        if not doc:
            raise HTTPException(status_code=404, detail="Expected income not found")
        if doc.get("received") is True:
            raise HTTPException(
                status_code=409,
                detail="Expected income is fully received and cannot receive further allocations",
            )
    if doc.get("currency") != currency:
        raise HTTPException(status_code=400, detail="Allocation currency must match target currency")
    return doc


ALLOCATABLE_EVENT_LIFECYCLES = frozenset({
    LIFECYCLE_STATUS_AWAITING_RECON,
    LIFECYCLE_STATUS_MATCHED,
    LIFECYCLE_STATUS_RESOLVED_UNPLANNED,
})


async def _load_allocatable_event(db, user_id: str, event_id: str) -> dict:
    """Load an event AND enforce the shared allocation preconditions:
       * ownership
       * confirmed + APPLIED lifecycle (has account, tz-aware occurred_at)
       * not void
    Raises HTTP errors on failure. Returns the raw event document.
    """
    ev = await db.financial_events.find_one(
        {"id": event_id, "user_id": user_id}, {"_id": 0},
    )
    if not ev:
        raise HTTPException(status_code=404, detail="Financial Event not found")
    if ev.get("confirmation_status") != "confirmed":
        raise HTTPException(
            status_code=409,
            detail="Event must be confirmed before allocating",
        )
    if ev.get("lifecycle_status") not in ALLOCATABLE_EVENT_LIFECYCLES:
        raise HTTPException(
            status_code=409,
            detail=(
                "Event lifecycle does not allow allocations "
                f"(current: {ev.get('lifecycle_status')})."
            ),
        )
    if not ev.get("account_id"):
        raise HTTPException(
            status_code=400,
            detail="Event must have an asset account before allocating",
        )
    # Enforce trustworthy timestamp — allocations must not depend on
    # a naive/missing occurred_at.
    from money_service import parse_utc as _parse_utc
    if _parse_utc(ev.get("occurred_at")) is None:
        raise HTTPException(
            status_code=400,
            detail="Event must have a timezone-aware occurred_at before allocating",
        )
    return ev


async def _conditional_push_allocation(
    db, user_id: str, event_id: str, allocation: dict, amount: Decimal,
) -> dict:
    """Conditionally append an allocation to ``financial_events``,
    enforcing that active allocations never exceed the event amount.

    Uses a filter that matches the exact allocations array we read.
    If a concurrent write has changed the array we retry a small
    number of times before failing with 409 so the client can retry
    idempotently.
    """
    for _ in range(5):
        ev = await db.financial_events.find_one({"id": event_id, "user_id": user_id}, {"_id": 0})
        if not ev:
            raise HTTPException(status_code=404, detail="Financial Event not found")
        allocs = ev.get("allocations") or []
        current_active = _sum_active_allocations(allocs)
        event_amount = _decimal_from_stored(ev.get("amount"))
        if current_active + amount > event_amount:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Allocation exceeds unallocated event amount. "
                    f"Unallocated remaining: {_quantize_out(event_amount - current_active)}"
                ),
            )
        # Conditional push — filter by exact allocations array so a
        # concurrent write invalidates our attempt and forces a retry.
        result = await db.financial_events.update_one(
            {"id": event_id, "user_id": user_id, "allocations": allocs},
            {"$push": {"allocations": allocation}, "$set": {"updated_at": _now()}},
        )
        if result.modified_count == 1:
            return allocation
    raise HTTPException(status_code=409, detail="Concurrent allocation conflict; retry")


async def _conditional_update_allocation(
    db, user_id: str, event_id: str, allocation_id: str, new_amount: Decimal,
) -> dict:
    """Update an existing allocation's amount atomically without allowing
    the resulting active-allocation total to exceed the parent event's
    ``amount``. Idempotent: writing the same amount is a no-op and the
    current allocation is returned.
    """
    for _ in range(5):
        ev = await db.financial_events.find_one({"id": event_id, "user_id": user_id}, {"_id": 0})
        if not ev:
            raise HTTPException(status_code=404, detail="Financial Event not found")
        allocs = ev.get("allocations") or []
        target = next((a for a in allocs if a.get("id") == allocation_id), None)
        if not target:
            raise HTTPException(status_code=404, detail="Allocation not found")
        if target.get("status") != "active":
            raise HTTPException(status_code=409, detail="Cannot update a voided allocation")
        current_active = _sum_active_allocations(allocs)
        target_active_amount = _decimal_from_stored(target.get("amount"))
        event_amount = _decimal_from_stored(ev.get("amount"))
        prospective = current_active - target_active_amount + new_amount
        if prospective > event_amount:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Allocation update exceeds event amount. "
                    f"Unallocated remaining: {_quantize_out(event_amount - (current_active - target_active_amount))}"
                ),
            )
        if new_amount == target_active_amount:
            # Idempotent no-op.
            return target
        # Build the new allocations array with the target rewritten.
        new_allocs = []
        for a in allocs:
            if a.get("id") == allocation_id:
                new_allocs.append({**a, "amount": Decimal128(new_amount), "updated_at": _now()})
            else:
                new_allocs.append(a)
        result = await db.financial_events.update_one(
            {"id": event_id, "user_id": user_id, "allocations": allocs},
            {"$set": {"allocations": new_allocs, "updated_at": _now()}},
        )
        if result.modified_count == 1:
            return new_allocs[[a.get("id") for a in new_allocs].index(allocation_id)]
    raise HTTPException(status_code=409, detail="Concurrent allocation conflict; retry")


async def _conditional_void_allocation(
    db, user_id: str, event_id: str, allocation_id: str,
) -> dict:
    """Void an allocation. Idempotent: voiding an already-voided
    allocation returns the current shape without another mutation.
    """
    for _ in range(5):
        ev = await db.financial_events.find_one({"id": event_id, "user_id": user_id}, {"_id": 0})
        if not ev:
            raise HTTPException(status_code=404, detail="Financial Event not found")
        allocs = ev.get("allocations") or []
        target = next((a for a in allocs if a.get("id") == allocation_id), None)
        if not target:
            raise HTTPException(status_code=404, detail="Allocation not found")
        if target.get("status") == "void":
            return target
        new_allocs = []
        for a in allocs:
            if a.get("id") == allocation_id:
                new_allocs.append({**a, "status": "void", "voided_at": _now(), "updated_at": _now()})
            else:
                new_allocs.append(a)
        result = await db.financial_events.update_one(
            {"id": event_id, "user_id": user_id, "allocations": allocs},
            {"$set": {"allocations": new_allocs, "updated_at": _now()}},
        )
        if result.modified_count == 1:
            return new_allocs[[a.get("id") for a in new_allocs].index(allocation_id)]
    raise HTTPException(status_code=409, detail="Concurrent allocation conflict; retry")


async def _aggregate_allocations_for_target(
    db, user_id: str, target_type: str, target_id: str, currency: str,
) -> Decimal:
    """Sum the currently-active allocation amounts across ALL events
    targeting a single commitment/expected_income row (N-to-1). Only
    counts allocations whose parent event is currently APPLIED (not
    void/rejected).
    """
    rows = await db.financial_events.find(
        {
            "user_id": user_id,
            "confirmation_status": "confirmed",
            "lifecycle_status": {"$in": list(APPLIED_LIFECYCLE_STATUSES)},
            "allocations": {"$elemMatch": {
                "target_type": target_type,
                "target_id": target_id,
                "status": "active",
            }},
        },
        {"_id": 0, "allocations": 1, "currency": 1},
    ).to_list(length=5000)
    total = Decimal(0)
    for r in rows:
        if r.get("currency") != currency:
            continue
        for a in r.get("allocations") or []:
            if (
                a.get("status") == "active"
                and a.get("target_type") == target_type
                and a.get("target_id") == target_id
            ):
                total += _decimal_from_stored(a.get("amount"))
    return total



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
    # Correction 3 — derived from ACTIVE allocations across every
    # APPLIED event pointing at this commitment.
    paid_amount: str = "0"
    remaining_amount: str = "0"
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
    # Batch 2A Correction 1: the paying asset account MUST be
    # identifiable. Callers supply EITHER ``actual_event_id`` (an
    # existing account-linked event) OR ``account_id`` (the account
    # that will hold the auto-created completion event). Liability
    # account IDs are rejected.
    account_id: Optional[str] = None
    occurred_at: Optional[str] = None


class PostponePayload(BaseModel):
    new_due_date: str


class ReviewPayload(BaseModel):
    decision: str  # keep | complete | cancel | postpone
    new_due_date: Optional[str] = None
    actual_amount: Optional[Any] = None
    actual_event_id: Optional[str] = None
    account_id: Optional[str] = None
    occurred_at: Optional[str] = None


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
    account_id: Optional[str] = None
    occurred_at: Optional[str] = None
    # Correction 3: precision explicitly declared by the caller. When
    # omitted we infer from the presence of a tz-aware occurred_at.
    occurred_at_precision: Optional[str] = None  # 'exact' | 'date_only'
    occurred_at_offset_minutes: Optional[int] = None


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
    account_id: Optional[str] = None
    lifecycle_status: str
    occurred_at: Optional[str] = None
    occurred_at_precision: Optional[str] = None
    occurred_at_offset_minutes: Optional[int] = None
    # Correction 3: embedded allocations + derived aggregates so
    # callers see multi-payment reality on a single wire trip.
    allocations: List[Any] = []
    allocated_amount: str = "0"
    unallocated_amount: str = "0"
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
    # Batch 2A: net-worth position now derives asset totals from
    # authoritative *effective* balances (snapshot + post-snapshot
    # confirmed events) so the "Current Financial Position" screen and
    # the availability calculation both share ONE canonical number per
    # account. Legacy raw ``current_value`` is only used for liabilities
    # (which do not participate in the event pipeline yet).
    from money_service import summarise_effective_balances, APPLIED_LIFECYCLE_STATUSES

    docs = await db.financial_accounts.find({"user_id": user_id}, {"_id": 0}).to_list(length=5000)
    events = await db.financial_events.find(
        {"user_id": user_id,
         "confirmation_status": "confirmed",
         "lifecycle_status": {"$in": list(APPLIED_LIFECYCLE_STATUSES)}},
        {"_id": 0},
    ).to_list(length=50000)
    eff_rows = summarise_effective_balances(docs, events)
    eff_by_id = {r["account_id"]: r for r in eff_rows}

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
        is_asset = d.get("account_type") in ASSET_ACCOUNT_TYPES
        # Assets use effective balance; liabilities continue on snapshot
        # value until the event pipeline models negative-account
        # transactions (out of Batch 2A scope).
        if is_asset:
            eff = eff_by_id.get(d.get("id"), {})
            amt = eff.get("effective_current_balance", _decimal_from_stored(d.get("current_value")))
        else:
            amt = _decimal_from_stored(d.get("current_value"))
        row = {
            "id": d["id"],
            "name": d.get("name") or "",
            "account_type": d.get("account_type"),
            "current_value": _quantize_out(amt),
            "liquidity_type": d.get("liquidity_type"),
            "balance_as_of": d.get("balance_as_of"),
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
    # Correction 3 — allocation-derived aggregates. Both fields default
    # to "0" so the UI can render deterministic partial-payment
    # progress even for commitments that never received an allocation.
    if doc.get("paid_amount") is not None:
        doc["paid_amount"] = _money_from_stored(doc.get("paid_amount"))
    else:
        doc["paid_amount"] = "0"
    if doc.get("remaining_amount") is not None:
        doc["remaining_amount"] = _money_from_stored(doc.get("remaining_amount"))
    else:
        try:
            planned = Decimal(str(doc.get("amount") or 0))
            paid = Decimal(str(doc.get("paid_amount") or 0))
            doc["remaining_amount"] = _quantize_out(planned - paid if planned - paid > 0 else Decimal(0))
        except Exception:
            doc["remaining_amount"] = "0"
    # Derived overdue marker
    doc["is_overdue"] = (
        doc.get("state") in _OVERDUE_STATES and
        doc.get("due_date") is not None and
        doc["due_date"] < _today_iso() and
        doc.get("state") != "cancelled" and
        doc.get("state") != "completed"
    )
    return doc


async def _insert_commitment_allocation(
    db, user_id: str, commitment_id: str, fc_state: str, alloc_status: str, doc: dict,
) -> str:
    """Insert a new ``resource_allocations`` row that owns the full lifecycle
    of a Financial Commitment. ``resource_allocations`` is the single source
    of truth for every commitment state — draft included.

    ``doc`` supplies the commitment payload (``amount``, ``currency``,
    ``due_date``, ``priority``, task/goal/project/domain links, ``source``…).
    ``fc_state`` is the Finance lifecycle state (draft/reserved/expired/…)
    and ``alloc_status`` is the ledger status (proposed/reserved/consumed/…).
    """
    alloc_id = _uuid()
    now = _now()
    await db.resource_allocations.insert_one({
        # --- ledger fields (owned by resource_allocations) ---
        "id": alloc_id,
        "user_id": user_id,
        "resource_type": "money",
        "owner_type": "task" if doc.get("task_id") else "standalone",
        "owner_id": doc.get("task_id"),
        "allocation_mode": "one_time",
        "date": doc["due_date"],
        "day_of_week": None,
        "start_time": None,
        "end_time": None,
        "quantity": doc["amount"],
        "unit": "currency",
        "currency": doc["currency"],
        "status": alloc_status,
        "fixed_or_flexible": "fixed",
        # --- Finance lifecycle fields (canonical from here on) ---
        "financial_commitment_id": commitment_id,
        "state": fc_state,
        "title": doc.get("title"),
        "description": doc.get("description") or "",
        "amount": doc["amount"],
        "due_date": doc["due_date"],
        "original_due_date": doc.get("original_due_date") or doc["due_date"],
        "priority": doc.get("priority"),
        "domain_id": doc.get("domain_id"),
        "goal_id": doc.get("goal_id"),
        "project_id": doc.get("project_id"),
        "task_id": doc.get("task_id"),
        "resource_allocation_id": alloc_id,
        "actual_amount": None,
        "variance": None,
        "unused_reservation": None,
        "overrun_amount": None,
        "completed_at": None,
        "cancelled_at": None,
        "postpone_count": 0,
        "last_reviewed_at": None,
        "next_review_date": (
            _add_days(_today_iso(), REVIEW_INTERVAL_DAYS) if fc_state == "reserved" else None
        ),
        "source": doc.get("source") or "manual",
        "created_at": now,
        "updated_at": now,
    })
    return alloc_id


async def _promote_draft_to_reserved(db, user_id: str, commitment_id: str) -> str:
    """Transition an existing draft commitment row to Reserved. Returns the
    allocation id. No new row is inserted — the row was created at commitment
    creation time. Ledger status flips from ``proposed`` to ``reserved`` and
    lifecycle state flips from ``draft`` to ``reserved``."""
    alloc = await db.resource_allocations.find_one(
        {"user_id": user_id, "resource_type": "money",
         "financial_commitment_id": commitment_id}, {"_id": 0},
    )
    if not alloc:
        raise HTTPException(status_code=404, detail="Financial Commitment not found")
    now = _now()
    await db.resource_allocations.update_one(
        {"id": alloc["id"]},
        {"$set": {
            "state": "reserved",
            "status": "reserved",
            "next_review_date": _add_days(_today_iso(), REVIEW_INTERVAL_DAYS),
            "updated_at": now,
        }},
    )
    await _audit(
        db, user_id, "resource_allocation", alloc["id"], "reservation_created",
        source="manual",
        new_value={"amount": _money_from_stored(alloc.get("amount")),
                   "currency": alloc.get("currency")},
    )
    return alloc["id"]


async def _update_lifecycle(db, commitment_id: str, fields: dict) -> None:
    """Write a lifecycle update onto the allocation row identified by
    ``financial_commitment_id``. This is the ONLY write path for
    commitments — ``financial_commitments`` is never touched."""
    payload = dict(fields)
    payload["updated_at"] = _now()
    await db.resource_allocations.update_one(
        {"resource_type": "money", "financial_commitment_id": commitment_id},
        {"$set": payload},
    )


# ============================================================================
# Read model — resource_allocations is the ONLY source of truth for reads.
#
# There is no fallback to ``financial_commitments`` and no mirror. Every
# commitment — draft included — lives as a single ``resource_allocations``
# row with ``resource_type='money'`` and a ``financial_commitment_id``.
# ============================================================================

_COMMITMENT_FIELDS = (
    "title", "description", "amount", "currency",
    "due_date", "original_due_date", "priority", "state",
    "domain_id", "goal_id", "project_id", "task_id",
    "resource_allocation_id",
    "actual_amount", "variance", "unused_reservation", "overrun_amount",
    # Correction 3 — allocation-derived aggregates.
    "paid_amount", "remaining_amount",
    "completed_at", "cancelled_at",
    "postpone_count", "last_reviewed_at", "next_review_date",
    "source",
)


def _alloc_to_commitment_view(a: dict) -> Optional[dict]:
    """Reshape a ``resource_allocations`` row into the commitment view
    consumed by the existing API contract. Returns None if the row is not a
    commitment (missing ``financial_commitment_id``).

    Ledger-only fields (``quantity``, ``status``, ``date``, ``unit``,
    ``consumed_amount``, ``released_amount``, ``allocation_mode``, …) are
    dropped so downstream JSON serialization never sees stray ``Decimal128``
    values that don't belong to the commitment surface.
    """
    if not a.get("financial_commitment_id"):
        return None
    KEEP = _COMMITMENT_FIELDS + ("created_at", "updated_at", "user_id")
    view: dict = {k: a.get(k) for k in KEEP if k in a}
    view["id"] = a["financial_commitment_id"]
    view["resource_allocation_id"] = a.get("id")
    return view


async def _find_commitment_allocations(db, extras: Optional[dict] = None) -> List[dict]:
    """Return commitment views from ``resource_allocations``."""
    q: dict = {"resource_type": "money", "financial_commitment_id": {"$ne": None}}
    if extras:
        q.update(extras)
    rows = await db.resource_allocations.find(q, {"_id": 0}).to_list(length=5000)
    out: List[dict] = []
    for a in rows:
        v = _alloc_to_commitment_view(a)
        if v is not None:
            out.append(v)
    return out


async def _read_all_commitments(
    db, user_id: str,
    state: Optional[str] = None,
    currency: Optional[str] = None,
    include_terminal: bool = True,
    task_id: Optional[str] = None,
) -> List[dict]:
    """Full commitment list — every state, sourced exclusively from
    ``resource_allocations``."""
    extras: dict = {"user_id": user_id}
    if currency:
        extras["currency"] = currency
    if task_id:
        extras["task_id"] = task_id
    if state:
        extras["state"] = state
    elif not include_terminal:
        extras["state"] = {"$in": ["draft", "reserved", "partial", "expired"]}
    return await _find_commitment_allocations(db, extras)


async def _read_commitment_by_id(db, user_id: str, commitment_id: str) -> Optional[dict]:
    """Fetch a single commitment from ``resource_allocations``. Returns None
    if the commitment does not exist."""
    row = await db.resource_allocations.find_one(
        {"user_id": user_id, "resource_type": "money", "financial_commitment_id": commitment_id},
        {"_id": 0},
    )
    return _alloc_to_commitment_view(row) if row else None


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
    must call ``/reserve`` after presenting the decision assessment. Every
    commitment — draft included — is stored as a single row in
    ``resource_allocations``. ``financial_commitments`` is never written to."""
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
        "domain_id": body.domain_id,
        "goal_id": body.goal_id,
        "project_id": body.project_id,
        "task_id": task_id,
        "source": "manual",
    }
    # Insert the draft into resource_allocations. Ledger status="proposed"
    # keeps this row out of the reserved-money aggregates until /reserve
    # promotes it.
    await _insert_commitment_allocation(
        db, current_user["id"], commitment_id,
        fc_state="draft", alloc_status="proposed", doc=doc,
    )

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
    fresh = await _read_commitment_by_id(db, current_user["id"], commitment_id)
    return _project_commitment(fresh or {})


@finance_router.post("/commitments/{commitment_id}/reserve", response_model=FinancialCommitmentResponse)
async def reserve_commitment(commitment_id: str, current_user: dict = Depends(get_current_user)):
    """Confirm a Draft commitment — transitions state=draft→reserved on the
    existing allocation row (no new row is created)."""
    db = get_db()
    c = await _read_commitment_by_id(db, current_user["id"], commitment_id)
    if not c:
        raise HTTPException(status_code=404, detail="Financial Commitment not found")
    _require(c.get("state") == "draft", f"Cannot reserve a commitment in state '{c.get('state')}'")

    alloc_id = await _promote_draft_to_reserved(db, current_user["id"], commitment_id)
    await _audit(
        db, current_user["id"], "financial_commitment", commitment_id, "reservation_created",
        source="manual", new_value={"state": "reserved", "allocation_id": alloc_id},
    )
    doc = await _read_commitment_by_id(db, current_user["id"], commitment_id)
    return _project_commitment(doc or {})


@finance_router.get("/commitments", response_model=List[FinancialCommitmentResponse])
async def list_commitments(
    state: Optional[str] = Query(None),
    currency: Optional[str] = Query(None),
    include_terminal: bool = Query(True),
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    if state:
        _require_in(state, COMMITMENT_STATES, "state")
    if currency:
        _require_currency(currency, "currency")
    # Auto-expire reserved commitments whose due date has passed — writes
    # target ``resource_allocations``, the single source of truth.
    today = _today_iso()
    await db.resource_allocations.update_many(
        {"user_id": current_user["id"], "resource_type": "money",
         "financial_commitment_id": {"$ne": None},
         "state": "reserved", "due_date": {"$lt": today}},
        {"$set": {"state": "expired", "updated_at": _now(), "fc_mirrored_at": _now()}},
    )
    docs = await _read_all_commitments(
        db, current_user["id"], state=state, currency=currency, include_terminal=include_terminal,
    )
    docs.sort(key=lambda d: (d.get("due_date") or "", d.get("created_at") or ""))
    return [_project_commitment(d) for d in docs]


@finance_router.get("/commitments/{commitment_id}", response_model=FinancialCommitmentResponse)
async def get_commitment(commitment_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    doc = await _read_commitment_by_id(db, current_user["id"], commitment_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Financial Commitment not found")
    # Lazy auto-expiration — write goes to the allocation row only.
    if doc.get("state") == "reserved" and (doc.get("due_date") or "") < _today_iso():
        await _update_lifecycle(db, commitment_id, {"state": "expired"})
        await _audit(
            db, current_user["id"], "financial_commitment", commitment_id, "expired",
            source="system", new_value={"state": "expired"},
        )
        doc = await _read_commitment_by_id(db, current_user["id"], commitment_id) or doc
    return _project_commitment(doc)


@finance_router.put("/commitments/{commitment_id}", response_model=FinancialCommitmentResponse)
async def update_commitment(commitment_id: str, body: FinancialCommitmentUpdate, current_user: dict = Depends(get_current_user)):
    """Edit a Draft or Reserved commitment. Terminal states (completed/
    cancelled/expired) are frozen. Every edit — draft included — writes
    to ``resource_allocations``."""
    db = get_db()
    c = await _read_commitment_by_id(db, current_user["id"], commitment_id)
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

    # Keep the ledger fields (quantity, date, currency) in sync with the
    # commitment fields written on the same row.
    alloc_update = dict(update)
    if "amount" in alloc_update:
        alloc_update["quantity"] = alloc_update["amount"]
    if "due_date" in alloc_update:
        alloc_update["date"] = alloc_update["due_date"]
    await _update_lifecycle(db, commitment_id, alloc_update)

    await _audit(
        db, current_user["id"], "financial_commitment", commitment_id, "updated",
        source="manual", previous_value=prev,
        new_value={k: (v if not isinstance(v, Decimal128) else _money_from_stored(v)) for k, v in update.items()},
    )
    doc = await _read_commitment_by_id(db, current_user["id"], commitment_id)
    return _project_commitment(doc or {})


async def _apply_complete(
    db, user_id: str, c: dict, actual_amount_raw: Any, event_id: Optional[str], event_date_iso: Optional[str],
    *, paying_account_id: Optional[str] = None, occurred_at_raw: Optional[str] = None,
) -> dict:
    """Shared completion path used by /complete, /expired /complete branch,
    and the linked-task completion prompt. Returns the refreshed commitment.

    Batch 2A Correction 1: completion MUST identify a paying ASSET
    account so the reservation release lands on real money. Callers
    supply EITHER an existing ``event_id`` that already carries an
    account of the commitment currency, OR ``paying_account_id`` (an
    asset account of the commitment currency) which the auto-created
    event will adopt.

    Ordering guarantee: the ledger reservation is never consumed /
    released unless the financial event insert AND the commitment
    lifecycle transition both succeed. On any failure the auto-created
    event is deleted to keep the ledger and history consistent.
    """
    reserved = _decimal_from_stored(c.get("amount"))
    linked_event: Optional[dict] = None
    auto_created_event_id: Optional[str] = None
    if event_id:
        linked_event = await db.financial_events.find_one(
            {"id": event_id, "user_id": user_id}, {"_id": 0},
        )
        if not linked_event:
            raise HTTPException(status_code=404, detail="Actual Financial Event not found")
        _require(linked_event.get("currency") == c.get("currency"),
                 "Event currency must match the commitment currency")
        # The linked event MUST already carry a valid asset account —
        # otherwise the reservation cannot be released against a real
        # money source.
        if not linked_event.get("account_id"):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Cannot complete a commitment against an accountless "
                    "event. Assign an asset account to the event first."
                ),
            )
        # Currency + user + asset-type re-validation of the event's
        # already-linked account. Defence-in-depth: if the event was
        # created pre-Correction-1 the check ensures we still refuse
        # liability linkages here.
        await _resolve_event_account(db, user_id, linked_event["account_id"], linked_event["currency"])
        # Confirmed events only.
        _require(linked_event.get("confirmation_status") == "confirmed",
                 "Linked event must be confirmed before completing a commitment")
        actual = _decimal_from_stored(linked_event.get("amount"))
    else:
        if actual_amount_raw is None or actual_amount_raw == "":
            raise HTTPException(status_code=400, detail="actual_amount is required when no matching event is linked")
        if not paying_account_id:
            raise HTTPException(
                status_code=400,
                detail=(
                    "account_id is required to complete a commitment. "
                    "Pick the asset account the money came out of."
                ),
            )
        # Validate the paying account (asset + same currency + user
        # ownership). Raises 400/404 on mismatch.
        await _resolve_event_account(db, user_id, paying_account_id, c.get("currency") or "")
        actual_stored = _money_to_stored(actual_amount_raw, "actual_amount")
        actual = _decimal_from_stored(actual_stored)
        # Persist an auto-created event so the actual is counted exactly
        # once and appears in Recent Actual Financial Events. Do NOT
        # transition the reservation yet — we roll back if the ledger
        # update fails.
        occurred_at = _normalise_occurred_at(occurred_at_raw)
        if not occurred_at:
            # Correction 2: never silently substitute "now" for a
            # missing/naive timestamp. The client MUST supply an
            # explicit tz-aware ``occurred_at`` when completing a
            # commitment; otherwise refuse the completion so the actual
            # spend is never placed at an incorrect moment.
            raise HTTPException(
                status_code=400,
                detail=(
                    "occurred_at is required when completing a commitment "
                    "without an existing event. Send a timezone-aware "
                    "ISO 8601 timestamp."
                ),
            )
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
            "account_id": paying_account_id,
            "lifecycle_status": LIFECYCLE_STATUS_MATCHED,
            "occurred_at": occurred_at,
            "created_at": _now(),
        }
        await db.financial_events.insert_one(dict(linked_event))
        auto_created_event_id = linked_event["id"]
        await _audit(
            db, user_id, "financial_event", linked_event["id"], "created",
            source="manual", new_value={"amount": _quantize_out(actual),
                                         "currency": c["currency"], "commitment_id": c["id"],
                                         "account_id": paying_account_id,
                                         "lifecycle_status": LIFECYCLE_STATUS_MATCHED},
        )

    variance = reserved - actual
    unused = variance if variance > 0 else Decimal(0)
    overrun = -variance if variance < 0 else Decimal(0)

    consumed = actual if actual <= reserved else reserved
    released = unused

    # Correction 2: single conditional update on the canonical
    # ``resource_allocations`` row. Only ONE request may transition
    # ``state`` from reserved/expired to completed AND write the
    # consumption + completion fields together. If we lose the race
    # (state was already completed / cancelled / etc.) we roll back the
    # auto-created event and return the current commitment.
    now = _now()
    ledger_update = {
        # Ledger consumption fields
        "status": "consumed",
        "consumed_amount": Decimal128(consumed),
        "released_amount": Decimal128(released),
        # Commitment lifecycle fields
        "state": "completed",
        "actual_amount": Decimal128(actual),
        "variance": Decimal128(variance),
        "unused_reservation": Decimal128(unused),
        "overrun_amount": Decimal128(overrun),
        "completed_at": now,
        "next_review_date": None,
        "updated_at": now,
    }
    try:
        transitioned = await db.resource_allocations.find_one_and_update(
            {"resource_type": "money",
             "financial_commitment_id": c["id"],
             "user_id": user_id,
             "state": {"$in": ["reserved", "expired"]}},
            {"$set": ledger_update},
            return_document=False,
        )
    except Exception:
        # DB error during the conditional update — roll the auto-created
        # event and its audit back so no orphan lingers.
        if auto_created_event_id:
            await db.financial_events.delete_one({"id": auto_created_event_id, "user_id": user_id})
            await db.financial_audit.delete_many({
                "record_type": "financial_event",
                "record_id": auto_created_event_id,
                "user_id": user_id,
            })
        raise
    if transitioned is None:
        # We lost the race. Remove any auto-created event and audit so
        # we never leave: (a) a commitment in a mixed state, (b) two
        # completion events, or (c) audits that reference a deleted
        # event. Then return the current commitment idempotently.
        if auto_created_event_id:
            await db.financial_events.delete_one({"id": auto_created_event_id, "user_id": user_id})
            await db.financial_audit.delete_many({
                "record_type": "financial_event",
                "record_id": auto_created_event_id,
                "user_id": user_id,
            })
        fresh = await _read_commitment_by_id(db, user_id, c["id"])
        if fresh and fresh.get("state") == "completed":
            return fresh
        raise HTTPException(
            status_code=409,
            detail="Commitment state changed concurrently; refresh and try again.",
        )
    await _audit(
        db, user_id, "resource_allocation", c.get("resource_allocation_id"),
        "reservation_consumed", source="manual",
        new_value={"consumed": _quantize_out(consumed),
                   "released": _quantize_out(released)},
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
    fresh = await _read_commitment_by_id(db, user_id, c["id"])
    return fresh


@finance_router.post("/commitments/{commitment_id}/complete", response_model=FinancialCommitmentResponse)
async def complete_commitment(
    commitment_id: str,
    body: CompletePayload = Body(default_factory=CompletePayload),
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    c = await _read_commitment_by_id(db, current_user["id"], commitment_id)
    if not c:
        raise HTTPException(status_code=404, detail="Financial Commitment not found")
    _require(
        c.get("state") in ("reserved", "expired"),
        f"Only Reserved or Expired commitments can be completed (state={c.get('state')})",
    )
    updated = await _apply_complete(
        db, current_user["id"], c, body.actual_amount, body.actual_event_id, body.event_date,
        paying_account_id=body.account_id, occurred_at_raw=body.occurred_at,
    )
    # Behavioural-calibration hook: when a completed commitment had an
    # override recorded against it, tag that override as vindicated
    # (actual outflow within the reserved envelope) or regretted
    # (overrun). Silently no-ops when there was no override.
    try:
        actual = _decimal_from_stored(updated.get("actual_amount"))
        reserved = _decimal_from_stored(c.get("amount"))
        outcome = "regretted" if actual > reserved else "vindicated"
        await db.override_decisions.update_many(
            {"user_id": current_user["id"], "commitment_id": commitment_id, "actual_outcome": None},
            {"$set": {
                "actual_outcome": outcome,
                "user_or_hymn_correct": "user" if outcome == "vindicated" else "hymn",
            }},
        )
    except Exception:  # noqa: BLE001 — best-effort; do not fail completion
        pass
    return _project_commitment(updated)


@finance_router.post("/commitments/{commitment_id}/cancel", response_model=FinancialCommitmentResponse)
async def cancel_commitment(commitment_id: str, current_user: dict = Depends(get_current_user)):
    """Cancel a Draft/Reserved/Expired commitment. All cancellations write
    to ``resource_allocations`` — the single owner of the commitment row.

    * Draft cancellations skip reservation release (nothing was reserved) but
      still flip lifecycle ``state`` to cancelled on the allocation row.
    * Reserved/Expired cancellations release the reservation first.
    """
    db = get_db()
    c = await _read_commitment_by_id(db, current_user["id"], commitment_id)
    if not c:
        raise HTTPException(status_code=404, detail="Financial Commitment not found")
    _require(
        c.get("state") in ("draft", "reserved", "expired"),
        f"Cannot cancel a commitment in state '{c.get('state')}'",
    )
    now = _now()
    released_amt = _money_from_stored(c.get("amount"))
    alloc_id = c.get("resource_allocation_id")

    if c.get("state") in ("reserved", "expired") and alloc_id:
        released = _decimal_from_stored(c.get("amount"))
        await _release_reservation(db, current_user["id"], alloc_id, released)

    await _update_lifecycle(db, commitment_id, {
        "state": "cancelled",
        "status": "cancelled",
        "cancelled_at": now,
        "next_review_date": None,
    })
    await _audit(
        db, current_user["id"], "financial_commitment", commitment_id, "cancelled",
        source="manual",
        new_value={"state": "cancelled", "released_amount": released_amt},
    )
    # Calibration hook: cancelling after an override → regretted.
    if c.get("state") in ("reserved", "expired"):
        try:
            await db.override_decisions.update_many(
                {"user_id": current_user["id"], "commitment_id": commitment_id, "actual_outcome": None},
                {"$set": {"actual_outcome": "regretted", "user_or_hymn_correct": "hymn"}},
            )
        except Exception:  # noqa: BLE001
            pass
    doc = await _read_commitment_by_id(db, current_user["id"], commitment_id)
    return _project_commitment(doc or {})


@finance_router.post("/commitments/{commitment_id}/postpone", response_model=FinancialCommitmentResponse)
async def postpone_commitment(
    commitment_id: str, body: PostponePayload, current_user: dict = Depends(get_current_user),
):
    db = get_db()
    c = await _read_commitment_by_id(db, current_user["id"], commitment_id)
    if not c:
        raise HTTPException(status_code=404, detail="Financial Commitment not found")
    _require(
        c.get("state") in ("reserved", "expired"),
        f"Cannot postpone a commitment in state '{c.get('state')}'",
    )
    _require_date_str(body.new_due_date, "new_due_date")
    _require(body.new_due_date > _today_iso(), "new_due_date must be in the future")
    prev_due = c.get("due_date")
    # Post-reservation lifecycle write — allocation is the sole owner. The
    # ledger-only ``date`` and ``status`` fields are updated in the same call
    # so the reservation row stays coherent.
    await _update_lifecycle(db, commitment_id, {
        "state": "reserved",  # postpone always returns to Reserved
        "status": "reserved",
        "due_date": body.new_due_date,
        "date": body.new_due_date,
        "postpone_count": (c.get("postpone_count") or 0) + 1,
        "next_review_date": _add_days(_today_iso(), REVIEW_INTERVAL_DAYS),
    })
    await _audit(
        db, current_user["id"], "financial_commitment", commitment_id, "postponed",
        source="manual",
        previous_value={"due_date": prev_due},
        new_value={"due_date": body.new_due_date},
    )
    doc = await _read_commitment_by_id(db, current_user["id"], commitment_id)
    return _project_commitment(doc or {})


@finance_router.post("/commitments/{commitment_id}/keep-active", response_model=FinancialCommitmentResponse)
async def keep_active_commitment(commitment_id: str, current_user: dict = Depends(get_current_user)):
    """Applies to Expired commitments — user chooses to keep the lien alive
    and be asked again next review cycle. The commitment stays in ``expired``
    with an overdue marker; the reservation is preserved."""
    db = get_db()
    c = await _read_commitment_by_id(db, current_user["id"], commitment_id)
    if not c:
        raise HTTPException(status_code=404, detail="Financial Commitment not found")
    _require(c.get("state") == "expired", "Keep-active applies only to Expired commitments")
    now = _now()
    # Post-reservation write — target the allocation exclusively.
    await _update_lifecycle(db, commitment_id, {
        "last_reviewed_at": now,
        "next_review_date": _add_days(_today_iso(), REVIEW_INTERVAL_DAYS),
    })
    await _audit(
        db, current_user["id"], "financial_commitment", commitment_id, "kept_active",
        source="manual", new_value={"state": "expired"},
    )
    doc = await _read_commitment_by_id(db, current_user["id"], commitment_id)
    return _project_commitment(doc or {})


@finance_router.post("/commitments/{commitment_id}/review", response_model=FinancialCommitmentResponse)
async def review_commitment(
    commitment_id: str, body: ReviewPayload, current_user: dict = Depends(get_current_user),
):
    """15-day review cycle (§11). Records the review and takes the requested
    branch — keep / complete / cancel / postpone."""
    db = get_db()
    c = await _read_commitment_by_id(db, current_user["id"], commitment_id)
    if not c:
        raise HTTPException(status_code=404, detail="Financial Commitment not found")
    _require_in(body.decision, ("keep", "complete", "cancel", "postpone"), "decision")

    if body.decision == "keep":
        _require(c.get("state") == "reserved", "Only Reserved commitments can be kept")
        now = _now()
        # Post-reservation write — allocation is the sole owner.
        await _update_lifecycle(db, commitment_id, {
            "last_reviewed_at": now,
            "next_review_date": _add_days(_today_iso(), REVIEW_INTERVAL_DAYS),
        })
        await _audit(
            db, current_user["id"], "financial_commitment", commitment_id, "reviewed",
            source="manual", new_value={"decision": "keep"},
        )
    elif body.decision == "complete":
        await _apply_complete(
            db, current_user["id"], c, body.actual_amount, body.actual_event_id, None,
            paying_account_id=body.account_id, occurred_at_raw=body.occurred_at,
        )
    elif body.decision == "cancel":
        # Delegate to cancel handler logic
        return await cancel_commitment(commitment_id, current_user=current_user)
    elif body.decision == "postpone":
        return await postpone_commitment(
            commitment_id, PostponePayload(new_due_date=body.new_due_date or ""), current_user=current_user,
        )
    doc = await _read_commitment_by_id(db, current_user["id"], commitment_id)
    return _project_commitment(doc or {})


@finance_router.get("/commitments-due-for-review", response_model=List[FinancialCommitmentResponse])
async def commitments_due_for_review(current_user: dict = Depends(get_current_user)):
    db = get_db()
    today = _today_iso()
    rows = await db.resource_allocations.find(
        {
            "user_id": current_user["id"],
            "resource_type": "money",
            "financial_commitment_id": {"$ne": None},
            "state": "reserved",
            "$or": [
                {"next_review_date": None},
                {"next_review_date": {"$lte": today}},
            ],
        }, {"_id": 0},
    ).to_list(length=1000)
    return [_project_commitment(_alloc_to_commitment_view(a) or {}) for a in rows]


# ============================================================================
# Reserved money aggregate (per currency)
# ============================================================================

async def _reserved_totals(db, user_id: str) -> dict:
    """Return per-currency reserved-money totals and the commitments causing
    the lien. Reads from the allocation read model — only ``state='reserved'``,
    ``'partial'`` or ``'expired'`` count (Draft doesn't reserve;
    completed/cancelled have already released).

    Correction 3: partial commitments retain their reservation for the
    unpaid remainder — we count ``remaining_amount`` when present,
    otherwise fall back to the full amount for reserved/expired rows.
    """
    rows = await db.resource_allocations.find(
        {"user_id": user_id, "resource_type": "money",
         "financial_commitment_id": {"$ne": None},
         "state": {"$in": ["reserved", "partial", "expired"]}},
        {"_id": 0},
    ).to_list(length=5000)
    per_currency: dict = {}
    for a in rows:
        d = _alloc_to_commitment_view(a)
        if not d:
            continue
        cur = d.get("currency") or ""
        b = per_currency.setdefault(cur, {"reserved": Decimal(0), "items": []})
        if d.get("state") == "partial":
            remaining = _decimal_from_stored(d.get("remaining_amount"))
            b["reserved"] += remaining if remaining > 0 else Decimal(0)
        else:
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


# NOTE: `GET /finance/reserved` (dead route) removed per finance audit — the
# same data ships in `GET /finance/dashboard`. The `_reserved_totals` helper
# above is still used internally by the dashboard and available-liquidity
# computations and MUST stay.


# ============================================================================
# Available liquid money (per currency)
# ============================================================================

async def _available_liquidity(db, user_id: str) -> list:
    """Authoritative available-liquidity per currency.

    Batch 2A rewrites this helper on top of ``money_service.load_availability``.
    The old implementation subtracted month-to-date confirmed outflows AT
    THE AGGREGATE, which double-counted outflows already reflected in the
    account snapshots via the effective-balance calculation. The new
    formula is::

        available_unreserved = sum(effective liquid asset balances)
                             - active reserved commitments

    Draft, completed, and cancelled commitments do NOT reduce the total
    (they don't hold a reservation). Reserved and expired commitments do.
    """
    from money_service import load_availability  # local import for cycles

    availability = await load_availability(db, user_id)
    out = []
    # Also carry per-account transparency so downstream surfaces can
    # show WHY the number is what it is (snapshot vs post-snapshot events).
    accounts_by_cur: dict = {}
    for r in availability["accounts"]:
        cur = r.get("currency") or ""
        accounts_by_cur.setdefault(cur, []).append({
            "account_id": r.get("account_id"),
            "name": r.get("name"),
            "account_type": r.get("account_type"),
            "liquidity_type": r.get("liquidity_type"),
            "snapshot_current_value": _quantize_out(r.get("snapshot_current_value", Decimal(0))),
            "snapshot_balance_as_of": r.get("snapshot_balance_as_of"),
            "post_snapshot_inflows": _quantize_out(r.get("post_snapshot_inflows", Decimal(0))),
            "post_snapshot_outflows": _quantize_out(r.get("post_snapshot_outflows", Decimal(0))),
            "effective_current_balance": _quantize_out(r.get("effective_current_balance", Decimal(0))),
        })
    pending_events = availability.get("pending_events", []) or []
    for cur, buckets in sorted(availability["by_currency"].items()):
        effective = buckets["liquid_effective"]
        reserved = buckets["reserved"]
        available = buckets["available_unreserved"]
        out.append({
            "currency": cur,
            # Transparency fields required by Batch 2A spec:
            "liquid_effective": _quantize_out(effective),
            "reserved": _quantize_out(reserved),
            "available_unreserved": _quantize_out(available),
            # Back-compat aliases so legacy Finance frontend keeps working
            # until the client migrates to the new field names.
            "liquid_assets": _quantize_out(effective),
            "month_to_date_outflow": "0.00",
            "accounts": accounts_by_cur.get(cur, []),
            "pending_account_events": [
                {
                    "event_id": e.get("id"),
                    "amount": _money_from_stored(e.get("amount")),
                    "currency": e.get("currency"),
                    "direction": e.get("direction"),
                    "event_date": e.get("event_date"),
                    "description": e.get("description") or "",
                    "checkin_id": e.get("checkin_id"),
                }
                for e in pending_events if (e.get("currency") == cur)
            ],
        })
    return out


# NOTE: `GET /finance/available-liquidity` (dead route) removed per finance
# audit — the same data ships in `GET /finance/dashboard`. The
# `_available_liquidity` helper stays because it is invoked by the dashboard.


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

    # Reserved commitments per (currency, due_month) — read from allocation model
    reserved_docs = await _find_commitment_allocations(
        db, {"user_id": user_id, "state": {"$in": ["reserved", "partial", "expired"]}},
    )

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
# NOTE: `POST /finance/scenarios` (in-place one-shot scenario) removed per
# finance audit. Superseded by the persistent scenario flow in
# `finance_advanced.py`: `POST /finance/scenarios/save`,
# `PUT /finance/scenarios/detail/{id}`,
# `POST /finance/scenarios/detail/{id}/evaluate`.
# ============================================================================


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

    # Batch 2A: account linkage validation (asset + user + currency).
    # Batch 2A Correction 1: liabilities are rejected inside the helper.
    await _resolve_event_account(db, current_user["id"], body.account_id, body.currency)

    # Correction 3: normalise precision. If caller provides
    # ``occurred_at_precision`` we trust it; otherwise infer from the
    # presence of a tz-aware ``occurred_at``.
    occurred_at = _normalise_occurred_at(body.occurred_at)
    precision = (body.occurred_at_precision or "").lower() or None
    if precision not in (None, "exact", "date_only"):
        raise HTTPException(status_code=400, detail="occurred_at_precision must be 'exact' or 'date_only'")
    if precision is None:
        precision = "exact" if occurred_at else "date_only"

    lifecycle_status = _default_lifecycle_status(
        direction=body.direction,
        account_id=body.account_id,
        commitment_id=body.commitment_id,
    )

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
        "account_id": body.account_id,
        "lifecycle_status": lifecycle_status,
        "occurred_at": occurred_at,
        "occurred_at_precision": precision,
        "occurred_at_offset_minutes": body.occurred_at_offset_minutes,
        # Correction 3: allocations start empty; the caller may
        # explicitly allocate after creation, or migration/completion
        # flow can push in a single allocation.
        "allocations": [],
        "created_at": _now(),
    }

    # Deduplication: probable duplicates are persisted as
    # ``confirmation_status='pending'``. Correction 2: the lifecycle
    # status depends on whether the incoming event already carries an
    # account — dedupe-with-account rows go to
    # ``pending_deduplication``, dedupe-without-account rows go to
    # ``pending_account_assignment`` (so the "Pending account" warning
    # still surfaces them). Both statuses are unapplied.
    dup_id = await _dedupe_check(db, current_user["id"], ev)
    if dup_id:
        ev["confirmation_status"] = "pending"
        ev["lifecycle_status"] = (
            LIFECYCLE_STATUS_PENDING_DEDUPE if body.account_id
            else LIFECYCLE_STATUS_PENDING_ACCOUNT
        )
        await db.financial_events.insert_one(dict(ev))
        try:
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
                source=body.source, new_value={"pending_dedupe_with": dup_id,
                                                "lifecycle_status": ev["lifecycle_status"]},
            )
        except Exception:
            # Rollback the event so no orphan sits in financial_events.
            await db.financial_events.delete_one({"id": ev["id"]})
            raise
    else:
        await db.financial_events.insert_one(dict(ev))
        try:
            await _audit(
                db, current_user["id"], "financial_event", ev["id"], "created",
                source=body.source,
                new_value={"amount": _money_from_stored(stored_amt), "currency": body.currency,
                           "direction": body.direction, "event_date": body.event_date,
                           "account_id": body.account_id, "occurred_at": occurred_at,
                           "lifecycle_status": lifecycle_status},
            )
        except Exception:
            await db.financial_events.delete_one({"id": ev["id"]})
            raise
    ev["amount"] = _money_from_stored(stored_amt)
    return _project_event(ev)


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
    return [_project_event(d) for d in docs]


async def _event_has_pending_dedupe(db, user_id: str, event_id: str) -> bool:
    """Return True when this event is currently referenced by an OPEN
    dedupe candidate (``pending`` or ``resolving`` status). Callers use
    this to refuse generic confirm/reject/assignment paths that would
    silently bypass the dedupe resolution journey.
    """
    row = await db.financial_dedupe_candidates.find_one(
        {"user_id": user_id,
         "$or": [{"event_a_id": event_id}, {"event_b_id": event_id}],
         "status": {"$in": ["pending", "resolving"]}},
        {"_id": 0, "id": 1},
    )
    return bool(row)


@finance_router.post("/events/{event_id}/confirm", response_model=FinancialEventResponse)
async def confirm_event(event_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    ev = await db.financial_events.find_one({"id": event_id, "user_id": current_user["id"]}, {"_id": 0})
    if not ev:
        raise HTTPException(status_code=404, detail="Financial Event not found")
    _require(ev.get("confirmation_status") != "confirmed", "Event is already confirmed")
    # Correction 3: generic confirm MUST NOT bypass an open dedupe case.
    if await _event_has_pending_dedupe(db, current_user["id"], event_id):
        raise HTTPException(
            status_code=409,
            detail=(
                "This event is part of an open deduplication case. "
                "Resolve the dedupe candidate before confirming."
            ),
        )
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
    ev.setdefault("account_id", None)
    ev.setdefault("lifecycle_status", LIFECYCLE_STATUS_AWAITING_RECON if ev.get("account_id") else LIFECYCLE_STATUS_PENDING_ACCOUNT)
    return ev


@finance_router.post("/events/{event_id}/reject", response_model=FinancialEventResponse)
async def reject_event(event_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    ev = await db.financial_events.find_one({"id": event_id, "user_id": current_user["id"]}, {"_id": 0})
    if not ev:
        raise HTTPException(status_code=404, detail="Financial Event not found")
    # Correction 3: generic reject MUST NOT bypass an open dedupe case.
    if await _event_has_pending_dedupe(db, current_user["id"], event_id):
        raise HTTPException(
            status_code=409,
            detail=(
                "This event is part of an open deduplication case. "
                "Resolve the dedupe candidate before rejecting."
            ),
        )
    await db.financial_events.update_one(
        {"id": event_id, "user_id": current_user["id"]},
        {"$set": {"confirmation_status": "rejected", "lifecycle_status": LIFECYCLE_STATUS_VOID}},
    )
    await _audit(
        db, current_user["id"], "financial_event", event_id, "reconciled",
        source="reconciliation", new_value={"confirmation_status": "rejected", "lifecycle_status": LIFECYCLE_STATUS_VOID},
    )
    ev["confirmation_status"] = "rejected"
    ev["lifecycle_status"] = LIFECYCLE_STATUS_VOID
    ev["amount"] = _money_from_stored(ev.get("amount"))
    ev.setdefault("account_id", None)
    return ev


# ---------------------------------------------------------------------
# Correction 2: narrow event-assignment endpoint used by the Finance
# "Pending account" resolution journey. Lets the user fix an unapplied
# event's account_id / occurred_at / event_date without exposing any
# other fields.
# ---------------------------------------------------------------------

class EventAssignmentPayload(BaseModel):
    account_id: Optional[str] = None
    occurred_at: Optional[str] = None
    event_date: Optional[str] = None
    # Correction 3: allow the client to declare precision + device
    # timezone offset without ever inventing a wall-clock time.
    occurred_at_precision: Optional[str] = None  # 'exact' | 'date_only'
    occurred_at_offset_minutes: Optional[int] = None


@finance_router.patch("/events/{event_id}/assignment", response_model=FinancialEventResponse)
async def update_event_assignment(
    event_id: str,
    body: EventAssignmentPayload,
    current_user: dict = Depends(get_current_user),
):
    """Correct an unapplied event's account, occurrence time, or
    reporting date so it can flow into the money service.

    Rules (Correction 2):
    * Only the event owner may call this — user_id filter is applied on
      every query.
    * Matched events cannot be edited via this endpoint.
    * ``account_id``, when supplied, MUST reference a same-currency
      asset account owned by the caller (rejected via the shared
      ``_resolve_event_account`` helper).
    * ``occurred_at``, when supplied, MUST be tz-aware; naive strings
      are refused (the event stays unapplied).
    * ``event_date`` accepts YYYY-MM-DD when the caller explicitly
      corrects the reporting date.
    * After the write, if the event now has both an account_id AND a
      trustworthy occurred_at, its lifecycle_status is promoted:
        - was pending_account_assignment  -> awaiting_reconciliation
        - was pending_deduplication       -> stays pending_deduplication
          (must be resolved via the dedupe candidate flow, not here)
    """
    db = get_db()
    ev = await db.financial_events.find_one(
        {"id": event_id, "user_id": current_user["id"]}, {"_id": 0},
    )
    if not ev:
        raise HTTPException(status_code=404, detail="Financial Event not found")
    if ev.get("lifecycle_status") == LIFECYCLE_STATUS_MATCHED:
        raise HTTPException(
            status_code=409,
            detail="This event has been matched to a commitment. Reverse the reconciliation before editing.",
        )
    if ev.get("lifecycle_status") == LIFECYCLE_STATUS_VOID:
        raise HTTPException(
            status_code=409,
            detail="This event has been voided and cannot be edited.",
        )
    # Correction 3: never let the assignment path silently reopen a
    # ``resolved_unplanned`` event — it was already applied to the
    # balance and its ownership decision is final.
    if ev.get("lifecycle_status") == LIFECYCLE_STATUS_RESOLVED_UNPLANNED:
        raise HTTPException(
            status_code=409,
            detail=(
                "This event was resolved as an unplanned actual. "
                "Reversing the resolution requires a reconciliation flow, not assignment."
            ),
        )

    updates: dict = {}

    if "account_id" in body.dict(exclude_unset=True):
        # ``None`` explicitly clears the account.
        if body.account_id:
            await _resolve_event_account(
                db, current_user["id"], body.account_id, ev.get("currency") or "",
            )
        updates["account_id"] = body.account_id

    if "occurred_at" in body.dict(exclude_unset=True):
        normalised = _normalise_occurred_at(body.occurred_at) if body.occurred_at else None
        if body.occurred_at and normalised is None:
            raise HTTPException(
                status_code=400,
                detail="occurred_at must be a timezone-aware ISO 8601 timestamp",
            )
        updates["occurred_at"] = normalised

    # Correction 3: precision + offset are the trust anchor when
    # ``occurred_at`` is absent. ``date_only`` says we only have a
    # calendar date and money_service must apply it via date rules.
    if "occurred_at_precision" in body.dict(exclude_unset=True):
        prec = (body.occurred_at_precision or "").lower() or None
        if prec not in (None, "exact", "date_only"):
            raise HTTPException(status_code=400, detail="occurred_at_precision must be 'exact' or 'date_only'")
        updates["occurred_at_precision"] = prec
    if "occurred_at_offset_minutes" in body.dict(exclude_unset=True):
        updates["occurred_at_offset_minutes"] = body.occurred_at_offset_minutes

    if "event_date" in body.dict(exclude_unset=True) and body.event_date:
        _require_date_str(body.event_date, "event_date")
        updates["event_date"] = body.event_date

    if not updates:
        # No-op — return the current projection so callers can treat
        # this as idempotent.
        ev["amount"] = _money_from_stored(ev.get("amount"))
        ev.setdefault("account_id", None)
        ev.setdefault("lifecycle_status", LIFECYCLE_STATUS_PENDING_ACCOUNT)
        ev.setdefault("occurred_at", None)
        return ev

    # Compute the resulting lifecycle_status based on the projected
    # state after the write. Correction 3: ``date_only`` precision
    # (with an event_date) is enough to apply an account-linked event
    # via calendar-date rules — same-day ambiguity is surfaced by
    # ``money_service``.
    from money_service import parse_utc as _parse_utc
    proj_account = updates.get("account_id", ev.get("account_id"))
    proj_occ = updates.get("occurred_at", ev.get("occurred_at"))
    proj_prec = updates.get("occurred_at_precision", ev.get("occurred_at_precision"))
    proj_event_date = updates.get("event_date", ev.get("event_date"))
    current_lifecycle = ev.get("lifecycle_status")
    time_trust_ok = _parse_utc(proj_occ) is not None or (
        (proj_prec == "date_only") and isinstance(proj_event_date, str) and len(proj_event_date) >= 10
    )
    if current_lifecycle == LIFECYCLE_STATUS_PENDING_DEDUPE:
        # Do NOT promote — dedupe must be resolved through its own flow.
        new_lifecycle = LIFECYCLE_STATUS_PENDING_DEDUPE
    elif proj_account and time_trust_ok and ev.get("confirmation_status") == "confirmed":
        new_lifecycle = LIFECYCLE_STATUS_AWAITING_RECON
    else:
        new_lifecycle = LIFECYCLE_STATUS_PENDING_ACCOUNT
    updates["lifecycle_status"] = new_lifecycle

    result = await db.financial_events.find_one_and_update(
        {"id": event_id, "user_id": current_user["id"],
         # Guard: refuse to write over a matched/void/resolved event
         # even if a race intervenes between the initial read and this
         # call.
         "lifecycle_status": {"$nin": [
             LIFECYCLE_STATUS_MATCHED,
             LIFECYCLE_STATUS_VOID,
             LIFECYCLE_STATUS_RESOLVED_UNPLANNED,
         ]}},
        {"$set": updates},
        return_document=False,
    )
    if result is None:
        raise HTTPException(
            status_code=409,
            detail="Event lifecycle changed concurrently; refresh and try again.",
        )
    await _audit(
        db, current_user["id"], "financial_event", event_id, "updated",
        source="manual",
        previous_value={
            "account_id": ev.get("account_id"),
            "occurred_at": ev.get("occurred_at"),
            "event_date": ev.get("event_date"),
            "lifecycle_status": ev.get("lifecycle_status"),
        },
        new_value={**updates},
    )
    fresh = await db.financial_events.find_one({"id": event_id, "user_id": current_user["id"]}, {"_id": 0})
    fresh["amount"] = _money_from_stored(fresh.get("amount"))
    fresh.setdefault("account_id", None)
    fresh.setdefault("occurred_at", None)
    return fresh


# ---------------------------------------------------------------------
# Correction 3 — Allocation CRUD endpoints.
#
# Allocations classify a slice of an event's amount to a specific
# commitment or expected-income record. They NEVER change the parent
# account balance — the event is the sole account-affecting movement.
#
# Rules:
#   * The parent event must be owned by the caller, confirmed, applied
#     (has account_id + tz-aware occurred_at + lifecycle in the applied
#     set), and NOT void.
#   * Currency, direction and target lifecycle are validated.
#   * The sum of ACTIVE allocations on the event may never exceed the
#     event's ``amount``. This is enforced via an atomic conditional
#     update on the ``allocations`` array.
#   * All operations are idempotent on retry: same amount → no-op;
#     re-voiding a voided allocation → no-op.
# ---------------------------------------------------------------------

class AllocationCreatePayload(BaseModel):
    target_type: str  # 'commitment' | 'expected_income'
    target_id: str
    amount: Any


class AllocationUpdatePayload(BaseModel):
    amount: Any


@finance_router.post("/events/{event_id}/allocations", response_model=FinancialEventResponse, status_code=201)
async def create_allocation(
    event_id: str,
    body: AllocationCreatePayload,
    current_user: dict = Depends(get_current_user),
):
    """Add an allocation slice on a financial event. The event must be
    applied; the target must be an in-progress commitment (for outflow)
    or a not-yet-received expected income (for inflow). Enforces
    over-allocation atomicity via a conditional update on the array.
    """
    db = get_db()
    ev = await _load_allocatable_event(db, current_user["id"], event_id)
    _require_in(body.target_type, ("commitment", "expected_income"), "target_type")
    target = await _validate_allocation_target(
        db, current_user["id"], body.target_type, body.target_id,
        currency=ev.get("currency") or "", direction=ev.get("direction") or "",
    )
    stored = _money_to_stored(body.amount, "amount")
    amount_dec = _decimal_from_stored(stored)
    if amount_dec <= 0:
        raise HTTPException(status_code=400, detail="Allocation amount must be greater than zero")
    allocation = _allocation_shape(
        target_type=body.target_type, target_id=body.target_id,
        amount_stored=stored, currency=ev.get("currency") or "",
    )
    await _conditional_push_allocation(
        db, current_user["id"], event_id, allocation, amount_dec,
    )
    await _audit(
        db, current_user["id"], "financial_event", event_id, "updated",
        source="manual",
        new_value={
            "allocation_created": {
                "id": allocation["id"],
                "target_type": body.target_type,
                "target_id": body.target_id,
                "amount": _quantize_out(amount_dec),
                "currency": ev.get("currency"),
            },
        },
    )
    # Propagate lifecycle to targets — recompute paid/received state
    # for commitments and expected incomes touched by this allocation.
    await _apply_allocation_effects(
        db, current_user["id"],
        target_type=body.target_type, target_id=body.target_id,
        currency=ev.get("currency") or "",
    )
    fresh = await db.financial_events.find_one({"id": event_id, "user_id": current_user["id"]}, {"_id": 0})
    return _project_event(fresh or ev)


@finance_router.patch("/events/{event_id}/allocations/{allocation_id}", response_model=FinancialEventResponse)
async def update_allocation(
    event_id: str,
    allocation_id: str,
    body: AllocationUpdatePayload,
    current_user: dict = Depends(get_current_user),
):
    """Update an allocation's amount. Idempotent; refuses to exceed the
    parent event's amount.
    """
    db = get_db()
    ev = await _load_allocatable_event(db, current_user["id"], event_id)
    stored = _money_to_stored(body.amount, "amount")
    amount_dec = _decimal_from_stored(stored)
    if amount_dec <= 0:
        raise HTTPException(status_code=400, detail="Allocation amount must be greater than zero")
    updated = await _conditional_update_allocation(
        db, current_user["id"], event_id, allocation_id, amount_dec,
    )
    await _audit(
        db, current_user["id"], "financial_event", event_id, "updated",
        source="manual",
        new_value={"allocation_updated": {"id": allocation_id, "amount": _quantize_out(amount_dec)}},
    )
    await _apply_allocation_effects(
        db, current_user["id"],
        target_type=updated.get("target_type") or "",
        target_id=updated.get("target_id") or "",
        currency=ev.get("currency") or "",
    )
    fresh = await db.financial_events.find_one({"id": event_id, "user_id": current_user["id"]}, {"_id": 0})
    return _project_event(fresh or ev)


@finance_router.post("/events/{event_id}/allocations/{allocation_id}/void", response_model=FinancialEventResponse)
async def void_allocation(
    event_id: str,
    allocation_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Void an allocation. Idempotent."""
    db = get_db()
    ev = await _load_allocatable_event(db, current_user["id"], event_id)
    voided = await _conditional_void_allocation(
        db, current_user["id"], event_id, allocation_id,
    )
    await _audit(
        db, current_user["id"], "financial_event", event_id, "updated",
        source="manual",
        new_value={"allocation_voided": {"id": allocation_id}},
    )
    await _apply_allocation_effects(
        db, current_user["id"],
        target_type=voided.get("target_type") or "",
        target_id=voided.get("target_id") or "",
        currency=ev.get("currency") or "",
    )
    fresh = await db.financial_events.find_one({"id": event_id, "user_id": current_user["id"]}, {"_id": 0})
    return _project_event(fresh or ev)


async def _apply_allocation_effects(
    db, user_id: str, *, target_type: str, target_id: str, currency: str,
) -> None:
    """Derive partial/completed state on the allocation target from the
    sum of ACTIVE allocations across every APPLIED event referencing
    it. Never modifies account balances.

    * ``commitment``: state may transition reserved/expired -> partial
      when paid > 0 and paid < amount, or -> completed when
      paid >= amount. When paid returns to zero (all voided) we return
      to reserved/expired based on due_date. Completion is only reached
      through allocations; the historic ``/complete`` flow still writes
      the completion event exactly once via ``_apply_complete``.
    * ``expected_income``: received=True when received_amount >= amount;
      otherwise received=False with a persisted ``received_amount``.
    """
    if not target_type or not target_id:
        return
    total = await _aggregate_allocations_for_target(
        db, user_id, target_type, target_id, currency,
    )
    if target_type == "commitment":
        c = await _read_commitment_by_id(db, user_id, target_id)
        if not c:
            return
        planned = _decimal_from_stored(c.get("amount"))
        # Compute the target lifecycle state based on paid coverage.
        new_state: Optional[str] = None
        if total <= 0:
            # Revert to reserved (or expired if due date already past).
            if c.get("state") in ("partial",):
                new_state = "expired" if (c.get("due_date") or "") < _today_iso() else "reserved"
        elif total < planned:
            if c.get("state") in ("reserved", "expired"):
                new_state = "partial"
        else:  # total >= planned
            if c.get("state") in ("reserved", "expired", "partial"):
                new_state = "completed"
        updates: dict = {
            "paid_amount": Decimal128(total),
            "remaining_amount": Decimal128(planned - total if planned - total > 0 else Decimal(0)),
        }
        if new_state and new_state != c.get("state"):
            updates["state"] = new_state
            if new_state == "completed":
                updates["completed_at"] = _now()
                updates["actual_amount"] = Decimal128(total)
                variance = planned - total
                updates["variance"] = Decimal128(variance)
                updates["unused_reservation"] = Decimal128(variance if variance > 0 else Decimal(0))
                updates["overrun_amount"] = Decimal128(-variance if variance < 0 else Decimal(0))
                updates["status"] = "consumed"
                updates["consumed_amount"] = Decimal128(total)
                updates["released_amount"] = Decimal128(variance if variance > 0 else Decimal(0))
        await _update_lifecycle(db, target_id, updates)
        if new_state and new_state != c.get("state"):
            await _audit(
                db, user_id, "financial_commitment", target_id,
                "completed" if new_state == "completed" else "updated",
                source="manual",
                new_value={"state": new_state, "paid_amount": _quantize_out(total)},
            )
    else:  # expected_income
        d = await db.expected_incomes.find_one({"id": target_id, "user_id": user_id}, {"_id": 0})
        if not d:
            return
        expected = _decimal_from_stored(d.get("amount"))
        received_flag = total >= expected and expected > 0
        updates: dict = {
            "received_amount": Decimal128(total),
            "remaining_amount": Decimal128(expected - total if expected - total > 0 else Decimal(0)),
            "received": received_flag,
            "updated_at": _now(),
        }
        # Preserve compatibility with older ``received_event_id`` UI —
        # once fully received via allocations we record the LAST event
        # id that pushed us over the threshold. Optional bookkeeping.
        await db.expected_incomes.update_one(
            {"id": target_id, "user_id": user_id},
            {"$set": updates},
        )
        await _audit(
            db, user_id, "financial_event", target_id, "updated",
            source="manual",
            new_value={"kind": "expected_income_allocation_effect",
                       "received_amount": _quantize_out(total),
                       "received": received_flag},
        )


# --------- Deduplication resolution ---------
@finance_router.get("/dedupe-candidates")
async def list_dedupe_candidates(current_user: dict = Depends(get_current_user)):
    db = get_db()
    rows = await db.financial_dedupe_candidates.find(
        {"user_id": current_user["id"], "status": {"$in": ["pending", "resolving"]}}, {"_id": 0},
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
    """Correction 2: security + idempotency hardened.

    * Candidate MUST belong to the caller AND currently be in
      ``status='pending'`` (checked via a conditional
      find_one_and_update on the candidate row).
    * ``canonical_event_id``, when supplied, MUST equal exactly
      ``event_a_id`` or ``event_b_id``.
    * Both referenced events MUST belong to the caller — every
      subsequent read/write filters on ``user_id``.
    * Only the winning request writes an audit or mutates events.
      Repeated requests return the existing terminal result without
      another audit or state mutation.
    """
    db = get_db()

    _require_in(body.resolution, ("same", "different"), "resolution")

    # Locate and inspect the candidate under the caller's user_id.
    row = await db.financial_dedupe_candidates.find_one(
        {"id": candidate_id, "user_id": current_user["id"]}, {"_id": 0},
    )
    if not row:
        raise HTTPException(status_code=404, detail="Deduplication candidate not found")

    terminal_status = "confirmed_same" if body.resolution == "same" else "rejected"

    # Idempotency — repeated call once the candidate is already
    # resolved. Return the same shape as the winning call would.
    if row.get("status") == terminal_status:
        if body.resolution == "different":
            return {"detail": "kept both", "already_resolved": True}
        canonical = row.get("canonical_event_id") or row["event_a_id"]
        other = row["event_b_id"] if canonical == row["event_a_id"] else row["event_a_id"]
        return {"detail": "merged", "canonical_event_id": canonical,
                "retired_event_id": other, "already_resolved": True}
    if row.get("status") not in (None, "pending"):
        # Was resolved via the opposite resolution; refuse to flip.
        raise HTTPException(
            status_code=409,
            detail=f"Candidate already resolved with status '{row.get('status')}'",
        )

    # canonical_event_id, when supplied, MUST match exactly one of the
    # referenced events.
    if body.canonical_event_id and body.canonical_event_id not in (
        row["event_a_id"], row["event_b_id"],
    ):
        raise HTTPException(
            status_code=400,
            detail="canonical_event_id must be event_a_id or event_b_id",
        )

    # Load both events under the caller's user_id — refuse if either
    # is missing.
    ev_a = await db.financial_events.find_one(
        {"id": row["event_a_id"], "user_id": current_user["id"]}, {"_id": 0},
    )
    ev_b = await db.financial_events.find_one(
        {"id": row["event_b_id"], "user_id": current_user["id"]}, {"_id": 0},
    )
    if not ev_a or not ev_b:
        raise HTTPException(status_code=404, detail="Referenced event missing")

    # Correction 3: recoverable + atomic transitions.
    #   pending -> resolving (claim; single winner)
    #   resolving -> terminal (only after event writes succeed)
    #   on any failure inside the event writes we revert
    #   resolving -> pending so a client can safely retry.
    now = _now()
    claimed = await db.financial_dedupe_candidates.find_one_and_update(
        {"id": candidate_id, "user_id": current_user["id"], "status": "pending"},
        {"$set": {"status": "resolving",
                   "resolving_at": now,
                   "resolving_intent": terminal_status}},
        return_document=False,
    )
    if claimed is None:
        # A concurrent request won or the row is already resolved.
        # Re-read to return the winning result idempotently.
        latest = await db.financial_dedupe_candidates.find_one(
            {"id": candidate_id, "user_id": current_user["id"]}, {"_id": 0},
        )
        if not latest:
            raise HTTPException(status_code=404, detail="Deduplication candidate not found")
        if latest.get("status") == "rejected":
            return {"detail": "kept both", "already_resolved": True}
        if latest.get("status") == "confirmed_same":
            canonical = latest.get("canonical_event_id") or row["event_a_id"]
            other = row["event_b_id"] if canonical == row["event_a_id"] else row["event_a_id"]
            return {"detail": "merged", "canonical_event_id": canonical,
                    "retired_event_id": other, "already_resolved": True}
        if latest.get("status") == "resolving":
            # Another writer is mid-flight. Refuse but keep the row
            # recoverable — the winner will still complete or revert.
            raise HTTPException(status_code=409, detail="Candidate is being resolved by another request; retry shortly")
        raise HTTPException(status_code=409, detail=f"Candidate in unexpected state '{latest.get('status')}'")

    try:
        if body.resolution == "different":
            pending_ev = ev_b
            new_lifecycle = (
                LIFECYCLE_STATUS_AWAITING_RECON if pending_ev.get("account_id")
                else LIFECYCLE_STATUS_PENDING_ACCOUNT
            )
            await db.financial_events.update_one(
                {"id": row["event_b_id"], "user_id": current_user["id"]},
                {"$set": {
                    "confirmation_status": "confirmed",
                    "lifecycle_status": new_lifecycle,
                }},
            )
            await _audit(
                db, current_user["id"], "financial_event", row["event_b_id"], "reconciled",
                source="reconciliation",
                new_value={"dedupe_resolution": "different", "lifecycle_status": new_lifecycle},
            )
            # Only NOW flip the candidate to its terminal state.
            await db.financial_dedupe_candidates.update_one(
                {"id": candidate_id, "user_id": current_user["id"], "status": "resolving"},
                {"$set": {"status": terminal_status,
                           "resolved_at": _now(),
                           "canonical_event_id": None}},
            )
            return {"detail": "kept both", "lifecycle_status": new_lifecycle}

        # resolution == 'same' — canonicalise and retire the other.
        canonical = body.canonical_event_id or row["event_a_id"]
        other = row["event_b_id"] if canonical == row["event_a_id"] else row["event_a_id"]
        canonical_doc = ev_a if canonical == row["event_a_id"] else ev_b
        canon_lifecycle = (
            LIFECYCLE_STATUS_AWAITING_RECON if canonical_doc.get("account_id")
            else LIFECYCLE_STATUS_PENDING_ACCOUNT
        )
        await db.financial_events.update_one(
            {"id": canonical, "user_id": current_user["id"]},
            {"$set": {"confirmation_status": "confirmed", "lifecycle_status": canon_lifecycle}},
        )
        await db.financial_events.update_one(
            {"id": other, "user_id": current_user["id"]},
            {"$set": {
                "confirmation_status": "rejected",
                "lifecycle_status": LIFECYCLE_STATUS_VOID,
                "dedup_of": canonical,
            }},
        )
        await _audit(
            db, current_user["id"], "financial_event", canonical, "reconciled",
            source="reconciliation",
            new_value={"dedupe_resolution": "same", "retired_event_id": other,
                       "canonical_lifecycle_status": canon_lifecycle,
                       "retired_lifecycle_status": LIFECYCLE_STATUS_VOID},
        )
        # Flip to terminal only after both event writes succeeded.
        await db.financial_dedupe_candidates.update_one(
            {"id": candidate_id, "user_id": current_user["id"], "status": "resolving"},
            {"$set": {"status": terminal_status,
                       "resolved_at": _now(),
                       "canonical_event_id": canonical}},
        )
        return {"detail": "merged", "canonical_event_id": canonical, "retired_event_id": other}
    except Exception:
        # Revert resolving -> pending so the client can retry.
        try:
            await db.financial_dedupe_candidates.update_one(
                {"id": candidate_id, "user_id": current_user["id"], "status": "resolving"},
                {"$set": {"status": "pending"},
                 "$unset": {"resolving_at": "", "resolving_intent": ""}},
            )
        except Exception:
            pass
        raise


# ============================================================================
# Task-completion prompt — surface the linked Financial Commitment
# ============================================================================

@finance_router.get("/task-linked-commitment/{task_id}", response_model=Optional[FinancialCommitmentResponse])
async def get_task_linked_commitment(task_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    matches = await _read_all_commitments(db, current_user["id"], task_id=task_id)
    if not matches:
        return None
    return _project_commitment(matches[0])


# ============================================================================
# Recent Actual Financial Events (dashboard section)
# ============================================================================

async def _recent_events(db, user_id: str, limit: int = 20) -> list:
    docs = await db.financial_events.find(
        {"user_id": user_id, "confirmation_status": "confirmed"}, {"_id": 0},
    ).sort([("event_date", -1), ("created_at", -1)]).to_list(length=limit)
    for d in docs:
        d["amount"] = _money_from_stored(d.get("amount"))
        d.setdefault("account_id", None)
        d.setdefault("lifecycle_status", LIFECYCLE_STATUS_AWAITING_RECON if d.get("account_id") else LIFECYCLE_STATUS_PENDING_ACCOUNT)
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
    # Auto-expire before we compute anything downstream — writes target
    # ``resource_allocations``, the single source of truth.
    today = _today_iso()
    await db.resource_allocations.update_many(
        {"user_id": user_id, "resource_type": "money",
         "financial_commitment_id": {"$ne": None},
         "state": "reserved", "due_date": {"$lt": today}},
        {"$set": {"state": "expired", "updated_at": _now(), "fc_mirrored_at": _now()}},
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
    # Commitments (active + terminal, capped) — read from allocation model + drafts.
    all_commitments = await _read_all_commitments(db, user_id)
    all_commitments.sort(key=lambda d: (d.get("due_date") or "", d.get("created_at") or ""))
    active_commitments = [
        _project_commitment(d) for d in all_commitments
        if d.get("state") in ("draft", "reserved", "partial", "expired")
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
    # ``financial_commitments`` is intentionally left intact — no writes go to
    # it anymore; the collection is retained solely for migration verification
    # of legacy rows. Indexes are preserved to keep verification queries fast.
    await database.financial_commitments.create_index("id", unique=True)
    await database.financial_commitments.create_index("user_id")
    await database.financial_commitments.create_index([("user_id", 1), ("state", 1)])
    await database.financial_commitments.create_index([("user_id", 1), ("due_date", 1)])
    await database.financial_commitments.create_index([("user_id", 1), ("task_id", 1)])

    # Base indexes on financial_events — safe to create first because
    # they are non-unique and idempotent.
    await database.financial_events.create_index("id", unique=True)
    await database.financial_events.create_index("user_id")
    await database.financial_events.create_index([("user_id", 1), ("event_date", 1)])
    await database.financial_events.create_index([("user_id", 1), ("confirmation_status", 1)])
    await database.financial_events.create_index([("user_id", 1), ("account_id", 1)])
    await database.financial_events.create_index([("user_id", 1), ("lifecycle_status", 1)])
    # occurred_at index — used by monthly actual-spending sums.
    await database.financial_events.create_index([("user_id", 1), ("occurred_at", 1)])

    # -----------------------------------------------------------------
    # Batch 2A + Correction 1 legacy repair — runs BEFORE creating the
    # unique partial index so duplicate rows do not fail the index build.
    # All steps are idempotent and restart-safe. No financial history
    # is deleted — only status fields are updated.
    # -----------------------------------------------------------------

    # 1. Ensure account_id key is present (as null) on every event.
    await database.financial_events.update_many(
        {"account_id": {"$exists": False}},
        {"$set": {"account_id": None}},
    )

    # 2. Ensure occurred_at key is present (as null) on every event.
    await database.financial_events.update_many(
        {"occurred_at": {"$exists": False}},
        {"$set": {"occurred_at": None}},
    )

    # 2b. Correction 3 — ensure the embedded ``allocations`` array is
    #     present on every event so allocation writes never target
    #     schemaless rows. Idempotent.
    await database.financial_events.update_many(
        {"allocations": {"$exists": False}},
        {"$set": {"allocations": []}},
    )

    # 2c. Correction 3 — backfill ``occurred_at_precision``:
    #     * tz-aware ``occurred_at`` present  -> 'exact'
    #     * otherwise                          -> 'date_only'
    #     This does NOT invent a time; it declares that we only trust
    #     the calendar date. Idempotent.
    await database.financial_events.update_many(
        {"occurred_at_precision": {"$exists": False}, "occurred_at": {"$ne": None}},
        {"$set": {"occurred_at_precision": "exact"}},
    )
    await database.financial_events.update_many(
        {"occurred_at_precision": {"$exists": False}},
        {"$set": {"occurred_at_precision": "date_only"}},
    )

    # 2d. Correction 3 — backfill legacy ``commitment_id`` rows into
    #     the new allocations array. If a confirmed event carries a
    #     commitment_id but no matching allocation, insert one covering
    #     the full event amount so read/write paths become consistent.
    #     Idempotent: only rows with an empty allocations array are
    #     touched.
    async for ev in database.financial_events.find(
        {"commitment_id": {"$ne": None},
         "confirmation_status": "confirmed",
         "allocations": []},
        {"_id": 0, "id": 1, "user_id": 1, "commitment_id": 1,
         "amount": 1, "currency": 1, "created_at": 1},
    ):
        alloc = {
            "id": _uuid(),
            "target_type": "commitment",
            "target_id": ev.get("commitment_id"),
            "amount": ev.get("amount"),
            "currency": ev.get("currency"),
            "status": "active",
            "created_at": ev.get("created_at") or _now(),
            "updated_at": _now(),
            "migrated_from_commitment_id": True,
        }
        await database.financial_events.update_one(
            {"id": ev["id"], "user_id": ev.get("user_id"), "allocations": []},
            {"$set": {"allocations": [alloc], "updated_at": _now()}},
        )

    # 3. lifecycle_status backfill — Correction 1 rules:
    #    * rejected                          -> void
    #    * confirmed AND no account_id        -> pending_account_assignment
    #      (accountless events remain visible for account assignment;
    #       they never affect balances silently)
    #    * confirmed AND account_id AND commitment_id -> matched
    #    * confirmed AND account_id AND reconciliation_status='unmatched'
    #                                        -> resolved_unplanned
    #    * confirmed AND account_id (else)   -> awaiting_reconciliation
    #    * everything else                   -> pending_account_assignment
    await database.financial_events.update_many(
        {"lifecycle_status": {"$exists": False}, "confirmation_status": "rejected"},
        {"$set": {"lifecycle_status": LIFECYCLE_STATUS_VOID}},
    )
    await database.financial_events.update_many(
        {"lifecycle_status": {"$exists": False}, "confirmation_status": "confirmed",
         "account_id": None},
        {"$set": {"lifecycle_status": LIFECYCLE_STATUS_PENDING_ACCOUNT}},
    )
    await database.financial_events.update_many(
        {"lifecycle_status": {"$exists": False}, "confirmation_status": "confirmed",
         "account_id": {"$ne": None}, "commitment_id": {"$ne": None}},
        {"$set": {"lifecycle_status": LIFECYCLE_STATUS_MATCHED}},
    )
    await database.financial_events.update_many(
        {"lifecycle_status": {"$exists": False}, "confirmation_status": "confirmed",
         "account_id": {"$ne": None}, "reconciliation_status": "unmatched"},
        {"$set": {"lifecycle_status": LIFECYCLE_STATUS_RESOLVED_UNPLANNED}},
    )
    await database.financial_events.update_many(
        {"lifecycle_status": {"$exists": False}, "confirmation_status": "confirmed",
         "account_id": {"$ne": None}},
        {"$set": {"lifecycle_status": LIFECYCLE_STATUS_AWAITING_RECON}},
    )
    await database.financial_events.update_many(
        {"lifecycle_status": {"$exists": False}},
        {"$set": {"lifecycle_status": LIFECYCLE_STATUS_PENDING_ACCOUNT}},
    )

    # 4. Repair rows created by the previous (over-broad) migration:
    #    a confirmed event with lifecycle_status ``awaiting_reconciliation``
    #    (or matched / resolved_unplanned) but NO account_id is not
    #    actually applied under Correction 1 — pull it back to pending.
    await database.financial_events.update_many(
        {"account_id": None, "lifecycle_status": {"$in": [
            LIFECYCLE_STATUS_AWAITING_RECON,
            LIFECYCLE_STATUS_MATCHED,
            LIFECYCLE_STATUS_RESOLVED_UNPLANNED,
        ]}},
        {"$set": {"lifecycle_status": LIFECYCLE_STATUS_PENDING_ACCOUNT}},
    )
    # Repair rejected rows that were mis-tagged in the previous migration.
    await database.financial_events.update_many(
        {"confirmation_status": "rejected", "lifecycle_status": {"$ne": LIFECYCLE_STATUS_VOID}},
        {"$set": {"lifecycle_status": LIFECYCLE_STATUS_VOID}},
    )

    # 4b. Correction 2: separate dedupe-pending from account-pending.
    # Any event currently in ``pending_account_assignment`` that has a
    # valid ``account_id`` AND is referenced by an OPEN
    # ``financial_dedupe_candidates`` row belongs in
    # ``pending_deduplication`` so it does not clutter the "Pending
    # account" warning. Idempotent — restart-safe.
    open_dedupe_event_ids: set = set()
    async for row in database.financial_dedupe_candidates.find(
        {"status": {"$in": ["pending", "resolving"]}}, {"_id": 0, "event_a_id": 1, "event_b_id": 1},
    ):
        for k in ("event_a_id", "event_b_id"):
            v = row.get(k)
            if isinstance(v, str):
                open_dedupe_event_ids.add(v)
    if open_dedupe_event_ids:
        await database.financial_events.update_many(
            {"id": {"$in": list(open_dedupe_event_ids)},
             "lifecycle_status": LIFECYCLE_STATUS_PENDING_ACCOUNT,
             "account_id": {"$ne": None}},
            {"$set": {"lifecycle_status": LIFECYCLE_STATUS_PENDING_DEDUPE}},
        )

    # 5. Duplicate cleanup — before creating the unique partial index on
    #    (checkin_id) restricted to active lifecycles, void any second-or-
    #    later active event that shares a checkin_id. Keep the earliest
    #    inserted event as the canonical one. This is idempotent — repeat
    #    runs find nothing to void.
    ACTIVE = [
        LIFECYCLE_STATUS_PENDING_ACCOUNT,
        LIFECYCLE_STATUS_PENDING_DEDUPE,
        LIFECYCLE_STATUS_AWAITING_RECON,
        LIFECYCLE_STATUS_MATCHED,
        LIFECYCLE_STATUS_RESOLVED_UNPLANNED,
    ]
    pipeline = [
        {"$match": {"checkin_id": {"$type": "string"}, "lifecycle_status": {"$in": ACTIVE}}},
        {"$group": {"_id": "$checkin_id", "ids": {"$push": {"id": "$id", "created_at": "$created_at"}}}},
        {"$match": {"$expr": {"$gt": [{"$size": "$ids"}, 1]}}},
    ]
    async for row in database.financial_events.aggregate(pipeline):
        ids_sorted = sorted(row["ids"], key=lambda x: x.get("created_at") or "")
        losers = [x["id"] for x in ids_sorted[1:]]
        if not losers:
            continue
        await database.financial_events.update_many(
            {"id": {"$in": losers}},
            {"$set": {"lifecycle_status": LIFECYCLE_STATUS_VOID,
                       "confirmation_status": "rejected"}},
        )

    # 6. Unique partial index — safe now that duplicates were voided
    #    above. MongoDB does not accept ``$ne`` inside partialFilter
    #    expressions so we positively enumerate the active statuses.
    #    Correction 2: the active-status list grew by one
    #    (``pending_deduplication``). If a previous run created the
    #    index with a narrower filter, MongoDB will refuse the create
    #    with IndexKeySpecsConflict — drop the old index in that case
    #    then recreate with the correct filter. Restart-safe.
    try:
        await database.financial_events.create_index(
            [("checkin_id", 1)],
            unique=True,
            partialFilterExpression={
                "checkin_id": {"$type": "string"},
                "lifecycle_status": {"$in": ACTIVE},
            },
            name="one_active_event_per_checkin",
        )
    except Exception as _idx_exc:
        msg = str(_idx_exc).lower()
        if "same name" in msg or "indexkeyspecsconflict" in msg or "index" in msg:
            try:
                await database.financial_events.drop_index("one_active_event_per_checkin")
            except Exception:
                pass
            await database.financial_events.create_index(
                [("checkin_id", 1)],
                unique=True,
                partialFilterExpression={
                    "checkin_id": {"$type": "string"},
                    "lifecycle_status": {"$in": ACTIVE},
                },
                name="one_active_event_per_checkin",
            )
        else:
            raise

    await database.financial_audit.create_index("id", unique=True)
    await database.financial_audit.create_index([("user_id", 1), ("record_type", 1), ("record_id", 1)])
    await database.financial_audit.create_index([("user_id", 1), ("timestamp", -1)])

    await database.financial_dedupe_candidates.create_index("id", unique=True)
    await database.financial_dedupe_candidates.create_index([("user_id", 1), ("status", 1)])


# ============================================================================
# One-time backfill — migrate legacy ``financial_commitments`` rows into
# ``resource_allocations``. Idempotent: only creates allocation rows for FC
# records that don't already have one. Runs at server startup.
# ============================================================================

async def backfill_fc_into_allocations(database) -> int:
    """Backfill every ``financial_commitments`` row into
    ``resource_allocations`` if a matching allocation does not exist.
    Returns the number of allocation rows inserted.
    """
    existing_ids = await database.resource_allocations.distinct(
        "financial_commitment_id", {"resource_type": "money"},
    )
    existing_set = {i for i in (existing_ids or []) if i}
    inserted = 0
    async for doc in database.financial_commitments.find({}, {"_id": 0}):
        cid = doc.get("id")
        if not cid or cid in existing_set:
            continue
        state = doc.get("state") or "draft"
        if state == "draft":
            alloc_status = "proposed"
        elif state == "cancelled":
            alloc_status = "cancelled"
        elif state == "reserved" or state == "expired":
            alloc_status = "reserved"
        elif state == "completed":
            alloc_status = "consumed"
        else:
            alloc_status = "proposed"
        alloc_id = _uuid()
        now = _now()
        await database.resource_allocations.insert_one({
            "id": alloc_id,
            "user_id": doc.get("user_id"),
            "resource_type": "money",
            "owner_type": "task" if doc.get("task_id") else "standalone",
            "owner_id": doc.get("task_id"),
            "allocation_mode": "one_time",
            "date": doc.get("due_date"),
            "day_of_week": None,
            "start_time": None,
            "end_time": None,
            "quantity": doc.get("amount"),
            "unit": "currency",
            "currency": doc.get("currency"),
            "status": alloc_status,
            "fixed_or_flexible": "fixed",
            "financial_commitment_id": cid,
            "state": state,
            "title": doc.get("title"),
            "description": doc.get("description") or "",
            "amount": doc.get("amount"),
            "due_date": doc.get("due_date"),
            "original_due_date": doc.get("original_due_date") or doc.get("due_date"),
            "priority": doc.get("priority"),
            "domain_id": doc.get("domain_id"),
            "goal_id": doc.get("goal_id"),
            "project_id": doc.get("project_id"),
            "task_id": doc.get("task_id"),
            "resource_allocation_id": alloc_id,
            "actual_amount": doc.get("actual_amount"),
            "variance": doc.get("variance"),
            "unused_reservation": doc.get("unused_reservation"),
            "overrun_amount": doc.get("overrun_amount"),
            "completed_at": doc.get("completed_at"),
            "cancelled_at": doc.get("cancelled_at"),
            "postpone_count": doc.get("postpone_count") or 0,
            "last_reviewed_at": doc.get("last_reviewed_at"),
            "next_review_date": doc.get("next_review_date"),
            "source": doc.get("source") or "manual",
            "created_at": doc.get("created_at") or now,
            "updated_at": now,
        })
        inserted += 1
    return inserted
