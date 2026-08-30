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

# Batch 2A: explicit lifecycle statuses for financial events. The
# authoritative money service (money_service.py) applies inflows/outflows
# to an account's snapshot only when the event carries an APPLIED status.
LIFECYCLE_STATUS_PENDING_ACCOUNT = "pending_account_assignment"
LIFECYCLE_STATUS_AWAITING_RECON = "awaiting_reconciliation"
LIFECYCLE_STATUS_MATCHED = "matched"
LIFECYCLE_STATUS_RESOLVED_UNPLANNED = "resolved_unplanned"
LIFECYCLE_STATUS_VOID = "void"
LIFECYCLE_STATUSES = (
    LIFECYCLE_STATUS_PENDING_ACCOUNT,
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
    # Batch 2A: authoritative source-of-truth linkage. Newly confirmed
    # inflows/outflows MUST be tied to a user-owned account of the same
    # currency. Callers that cannot supply one see the event persisted
    # in ``pending_account_assignment`` state so it does NOT affect
    # balances silently.
    account_id: Optional[str] = None
    # Batch 2A Correction 1: authoritative transaction timestamp
    # (tz-aware ISO-8601 UTC). Used by the money service to decide
    # whether the event falls after the account snapshot. When missing
    # or naive the event remains unapplied until reviewed — we NEVER
    # substitute created_at.
    occurred_at: Optional[str] = None


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
        extras["state"] = {"$in": ["draft", "reserved", "expired"]}
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
            # Fall back to "now" (UTC) — completion is a user action
            # happening in real time, so this is safe and monotonic.
            occurred_at = datetime.now(timezone.utc).isoformat()
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

    # Ledger transitions — guarded so that a failure here rolls the
    # auto-created event back so no orphan lands in ``financial_events``.
    try:
        if c.get("resource_allocation_id"):
            await _consume_reservation(
                db, user_id, c["resource_allocation_id"], consumed, released,
            )
        now = _now()
        await _update_lifecycle(db, c["id"], {
            "state": "completed",
            "actual_amount": Decimal128(actual),
            "variance": Decimal128(variance),
            "unused_reservation": Decimal128(unused),
            "overrun_amount": Decimal128(overrun),
            "completed_at": now,
            "next_review_date": None,
        })
    except Exception:
        # Best-effort rollback of the auto-created event. Audits are
        # append-only so they remain as historical breadcrumb — but the
        # event itself is removed so no orphan applies to the balance.
        if auto_created_event_id:
            await db.financial_events.delete_one({"id": auto_created_event_id, "user_id": user_id})
        raise
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
    the lien. Reads from the allocation read model — only ``state='reserved'``
    or ``'expired'`` count (Draft doesn't reserve; completed/cancelled have
    already released)."""
    rows = await db.resource_allocations.find(
        {"user_id": user_id, "resource_type": "money",
         "financial_commitment_id": {"$ne": None},
         "state": {"$in": ["reserved", "expired"]}},
        {"_id": 0},
    ).to_list(length=5000)
    per_currency: dict = {}
    for a in rows:
        d = _alloc_to_commitment_view(a)
        if not d:
            continue
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
        db, {"user_id": user_id, "state": {"$in": ["reserved", "expired"]}},
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

    # Batch 2A Correction 1: normalise the authoritative transaction
    # timestamp. Callers that cannot compute a tz-aware UTC value pass
    # None — the event stays visibly unapplied until reviewed.
    occurred_at = _normalise_occurred_at(body.occurred_at)

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
        "created_at": _now(),
    }

    # Deduplication: probable duplicates are persisted as
    # ``confirmation_status='pending'`` AND kept in ``lifecycle_status
    # 'pending_account_assignment'`` — they MUST remain financially
    # unapplied until the user resolves the dedupe ticket.
    dup_id = await _dedupe_check(db, current_user["id"], ev)
    if dup_id:
        ev["confirmation_status"] = "pending"
        ev["lifecycle_status"] = LIFECYCLE_STATUS_PENDING_ACCOUNT
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
        d.setdefault("account_id", None)
        d.setdefault("lifecycle_status", LIFECYCLE_STATUS_AWAITING_RECON if d.get("confirmation_status") == "confirmed" else LIFECYCLE_STATUS_PENDING_ACCOUNT)
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
    ev.setdefault("account_id", None)
    ev.setdefault("lifecycle_status", LIFECYCLE_STATUS_AWAITING_RECON if ev.get("account_id") else LIFECYCLE_STATUS_PENDING_ACCOUNT)
    return ev


@finance_router.post("/events/{event_id}/reject", response_model=FinancialEventResponse)
async def reject_event(event_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    ev = await db.financial_events.find_one({"id": event_id, "user_id": current_user["id"]}, {"_id": 0})
    if not ev:
        raise HTTPException(status_code=404, detail="Financial Event not found")
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
        # Batch 2A Correction 1: apply the pending event exactly once.
        # It moves from ``pending_account_assignment`` to
        # ``awaiting_reconciliation`` iff it has an account, else it
        # stays pending until the user assigns one.
        pending_ev = await db.financial_events.find_one({"id": row["event_b_id"]}, {"_id": 0})
        if not pending_ev:
            raise HTTPException(status_code=404, detail="Referenced event missing")
        new_lifecycle = (
            LIFECYCLE_STATUS_AWAITING_RECON if pending_ev.get("account_id")
            else LIFECYCLE_STATUS_PENDING_ACCOUNT
        )
        await db.financial_events.update_one(
            {"id": row["event_b_id"]},
            {"$set": {
                "confirmation_status": "confirmed",
                "lifecycle_status": new_lifecycle,
            }},
        )
        await db.financial_dedupe_candidates.update_one(
            {"id": candidate_id}, {"$set": {"status": "rejected", "resolved_at": _now()}},
        )
        await _audit(
            db, current_user["id"], "financial_event", row["event_b_id"], "reconciled",
            source="reconciliation",
            new_value={"dedupe_resolution": "different", "lifecycle_status": new_lifecycle},
        )
        return {"detail": "kept both", "lifecycle_status": new_lifecycle}

    # same — pick a canonical, retire the other, wire audit
    canonical = body.canonical_event_id or row["event_a_id"]
    other = row["event_b_id"] if canonical == row["event_a_id"] else row["event_a_id"]
    canonical_doc = await db.financial_events.find_one({"id": canonical}, {"_id": 0})
    other_doc = await db.financial_events.find_one({"id": other}, {"_id": 0})
    if not canonical_doc or not other_doc:
        raise HTTPException(status_code=404, detail="Referenced event missing")

    # Confirm canonical AND make sure it is applied iff it has an
    # account — otherwise it stays pending until the user assigns one.
    canon_lifecycle = (
        LIFECYCLE_STATUS_AWAITING_RECON if canonical_doc.get("account_id")
        else LIFECYCLE_STATUS_PENDING_ACCOUNT
    )
    await db.financial_events.update_one(
        {"id": canonical},
        {"$set": {"confirmation_status": "confirmed", "lifecycle_status": canon_lifecycle}},
    )
    # Retire the duplicate: reject it AND mark its lifecycle_status
    # ``void`` so the money service never applies it.
    await db.financial_events.update_one(
        {"id": other},
        {"$set": {
            "confirmation_status": "rejected",
            "lifecycle_status": LIFECYCLE_STATUS_VOID,
            "dedup_of": canonical,
        }},
    )
    await db.financial_dedupe_candidates.update_one(
        {"id": candidate_id}, {"$set": {"status": "confirmed_same", "resolved_at": _now()}},
    )
    await _audit(
        db, current_user["id"], "financial_event", canonical, "reconciled",
        source="reconciliation",
        new_value={"dedupe_resolution": "same", "retired_event_id": other,
                   "canonical_lifecycle_status": canon_lifecycle,
                   "retired_lifecycle_status": LIFECYCLE_STATUS_VOID},
    )
    return {"detail": "merged", "canonical_event_id": canonical, "retired_event_id": other}


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

    # 5. Duplicate cleanup — before creating the unique partial index on
    #    (checkin_id) restricted to active lifecycles, void any second-or-
    #    later active event that shares a checkin_id. Keep the earliest
    #    inserted event as the canonical one. This is idempotent — repeat
    #    runs find nothing to void.
    ACTIVE = [
        LIFECYCLE_STATUS_PENDING_ACCOUNT,
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
    await database.financial_events.create_index(
        [("checkin_id", 1)],
        unique=True,
        partialFilterExpression={
            "checkin_id": {"$type": "string"},
            "lifecycle_status": {"$in": ACTIVE},
        },
        name="one_active_event_per_checkin",
    )

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
