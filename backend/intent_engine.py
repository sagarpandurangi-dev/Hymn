"""Provider-neutral universal intent analysis and persistence.

The Foundation v1 strategy supports purchase intentions. Analysis is entirely
deterministic and stateless: nothing is written until the user confirms a
reviewed option. Confirmed purchase commitments reuse Finance's canonical
``resource_allocations`` ownership path.
"""

from __future__ import annotations

import re
import uuid
from calendar import monthrange
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from bson.decimal128 import Decimal128
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from deps import get_current_user, get_db
from finance_manager import (
    ASSET_ACCOUNT_TYPES,
    FinancialCommitmentCreate,
    ISO_4217_CURRENCIES,
    create_commitment,
)


intent_router = APIRouter(prefix="/intents", tags=["intents"])

INTENT_SCHEMA_VERSION = 1
PURCHASE_ASSESSMENT_VERSION = "purchase-assessment-v2"
SUPPORTED_INTENT_TYPES = ("purchase",)

_PURCHASE_ACTION_RE = re.compile(
    r"^(?:please\s+)?"
    r"(?:(?:i\s+)?(?:want|need|plan)\s+to\s+|i\s+(?:would|'d)\s+like\s+to\s+)?"
    r"(?P<verb>buy|purchase|order|acquire)\b",
    re.IGNORECASE,
)
_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_SLASH_DATE_RE = re.compile(
    r"\b(?P<date>(?P<first>\d{1,2})/(?P<second>\d{1,2})/(?P<year>\d{4}))\b"
)
_CURRENCY_TOKEN = r"(?:₹|\$|€|£|INR|USD|EUR|GBP)"
_AMOUNT_CANDIDATE = r"\d[\d,]*(?:\.\d+)?"
_PREFIX_AMOUNT_RE = re.compile(
    rf"(?P<currency>{_CURRENCY_TOKEN})\s*(?P<amount>{_AMOUNT_CANDIDATE})",
    re.IGNORECASE,
)
_SUFFIX_AMOUNT_RE = re.compile(
    rf"(?P<amount>{_AMOUNT_CANDIDATE})\s*(?P<currency>INR|USD|EUR|GBP)\b",
    re.IGNORECASE,
)
_BARE_PRICE_RE = re.compile(
    rf"\bfor\s+(?P<amount>{_AMOUNT_CANDIDATE})(?!\s*(?:INR|USD|EUR|GBP)\b)",
    re.IGNORECASE,
)
_STRICT_AMOUNT_RE = re.compile(
    r"^(?:\d+(?:\.\d{1,2})?|\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?)$"
)
_SYMBOL_CURRENCY = {"₹": "INR", "$": "USD", "€": "EUR", "£": "GBP"}
_MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}
_MONTH_TOKEN = (
    r"January|Jan|February|Feb|March|Mar|April|Apr|May|June|Jun|July|Jul|"
    r"August|Aug|September|Sept?|October|Oct|November|Nov|December|Dec"
)
_MONTH_DAY_RE = re.compile(
    rf"\b(?P<month>{_MONTH_TOKEN})\.?\s+(?P<day>\d{{1,2}})"
    r"(?:st|nd|rd|th)?(?:,\s*|\s+)?(?P<year>\d{4})?\b",
    re.IGNORECASE,
)
_DAY_MONTH_RE = re.compile(
    rf"\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+"
    rf"(?P<month>{_MONTH_TOKEN})\.?(?:,\s*|\s+)?(?P<year>\d{{4}})?\b",
    re.IGNORECASE,
)
_NEXT_MONTH_RE = re.compile(r"\bnext\s+month\b", re.IGNORECASE)


class PurchaseInputs(BaseModel):
    expected_price: Optional[str] = None
    currency: Optional[str] = None
    desired_date: Optional[str] = None
    price_unknown: bool = False
    timing_unknown: bool = False


class IntentAnalyzeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    purchase: PurchaseInputs = Field(default_factory=PurchaseInputs)
    reference_date: Optional[str] = None


class IntentConfirmRequest(IntentAnalyzeRequest):
    selected_option_id: str = Field(min_length=1, max_length=80)
    idempotency_key: str = Field(min_length=8, max_length=120)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _money(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


def _decimal_from_stored(value: Any) -> Decimal:
    if isinstance(value, Decimal128):
        return value.to_decimal()
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value or 0))


def _parse_amount(value: Any, field: str) -> Decimal:
    raw = str(value).strip()
    if not _STRICT_AMOUNT_RE.fullmatch(raw):
        raise HTTPException(
            status_code=400,
            detail=f"{field} must be a positive number with at most two decimal places",
        )
    try:
        amount = Decimal(raw.replace(",", ""))
    except InvalidOperation as exc:
        raise HTTPException(status_code=400, detail=f"{field} is invalid") from exc
    if not amount.is_finite() or amount <= 0:
        raise HTTPException(status_code=400, detail=f"{field} must be greater than zero")
    return amount


def _parse_date(
    value: str,
    field: str,
    not_before: Optional[date] = None,
) -> str:
    raw = value.strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        raise HTTPException(status_code=400, detail=f"{field} must use YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{field} is not a valid date") from exc
    if parsed < (not_before or date.today()):
        raise HTTPException(status_code=400, detail=f"{field} cannot be in the past")
    return parsed.isoformat()


def _parse_currency(value: str) -> str:
    currency = value.strip().upper()
    if currency not in ISO_4217_CURRENCIES:
        raise HTTPException(status_code=400, detail="currency must be a supported ISO 4217 code")
    return currency


def _reference_date(value: Optional[str | date]) -> date:
    if isinstance(value, date):
        return value
    if value is None:
        return date.today()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="reference_date must be a valid YYYY-MM-DD date",
        ) from exc


def _unsupported_classification() -> dict:
    return {
        "intent_type": "unsupported",
        "confidence": "deterministic",
        "item": None,
        "extracted_price": None,
        "extracted_currency": None,
        "extracted_date": None,
        "extracted_timing_text": None,
        "timing_precision": None,
        "timing_resolution": None,
        "timing_ambiguity_reason": None,
        "ambiguities": [],
    }


def _extract_price(cleaned: str) -> dict:
    matches: list[dict] = []
    occupied: list[tuple[int, int]] = []
    for pattern in (_PREFIX_AMOUNT_RE, _SUFFIX_AMOUNT_RE):
        for match in pattern.finditer(cleaned):
            span = match.span()
            if any(span[0] < end and span[1] > start for start, end in occupied):
                continue
            amount = _money(_parse_amount(match.group("amount"), "expected_price"))
            raw_currency = match.group("currency")
            currency = _SYMBOL_CURRENCY.get(raw_currency, raw_currency.upper())
            matches.append({
                "amount": amount,
                "currency": currency,
                "start": span[0],
                "end": span[1],
                "text": match.group(0),
            })
            occupied.append(span)

    if not matches:
        for match in _BARE_PRICE_RE.finditer(cleaned):
            amount = _money(_parse_amount(match.group("amount"), "expected_price"))
            matches.append({
                "amount": amount,
                "currency": None,
                "start": match.start("amount"),
                "end": match.end("amount"),
                "text": match.group("amount"),
            })

    if len(matches) != 1:
        return {
            "amount": None,
            "currency": None,
            "match": min(matches, key=lambda row: row["start"]) if matches else None,
            "ambiguous": len(matches) > 1,
        }
    return {
        "amount": matches[0]["amount"],
        "currency": matches[0]["currency"],
        "match": matches[0],
        "ambiguous": False,
    }


def _calendar_date(
    month_name: str,
    day_value: str,
    year_value: Optional[str],
    reference: date,
) -> tuple[date, str]:
    month = _MONTHS[month_name.rstrip(".").lower()]
    day_number = int(day_value)
    year = int(year_value) if year_value else reference.year
    try:
        resolved = date(year, month, day_number)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="desired_date is not a valid date") from exc
    if not year_value and resolved < reference:
        resolved = date(year + 1, month, day_number)
    if resolved < reference:
        raise HTTPException(status_code=400, detail="desired_date cannot be in the past")
    resolution = (
        "Explicit calendar date"
        if year_value
        else f"Year resolved from the reference date {reference.isoformat()}"
    )
    return resolved, resolution


def _next_month_date(reference: date) -> date:
    year = reference.year + (1 if reference.month == 12 else 0)
    month = 1 if reference.month == 12 else reference.month + 1
    day_number = min(reference.day, monthrange(year, month)[1])
    return date(year, month, day_number)


def _extract_timing(cleaned: str, reference: date) -> dict:
    candidates: list[dict] = []
    for match in _ISO_DATE_RE.finditer(cleaned):
        resolved = _parse_date(match.group(0), "desired_date", reference)
        candidates.append({
            "date": resolved,
            "text": match.group(0),
            "precision": "exact_date",
            "resolution": "Explicit ISO date",
            "start": match.start(),
            "end": match.end(),
        })
    for match in _SLASH_DATE_RE.finditer(cleaned):
        first = int(match.group("first"))
        second = int(match.group("second"))
        year = int(match.group("year"))
        if first == 0 or second == 0 or first > 31 or second > 31:
            raise HTTPException(status_code=400, detail="desired_date is not a valid date")
        if first > 12 and second <= 12:
            try:
                resolved_date = date(year, second, first)
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail="desired_date is not a valid calendar date",
                ) from exc
            if resolved_date < reference:
                raise HTTPException(status_code=400, detail="desired_date cannot be in the past")
            candidates.append({
                "date": resolved_date.isoformat(),
                "text": match.group("date"),
                "precision": "exact_date",
                "resolution": "Parsed as DD/MM/YYYY because the day is greater than 12",
                "ambiguity_reason": None,
                "start": match.start("date"),
                "end": match.end("date"),
            })
        elif first <= 12:
            candidates.append({
                "date": None,
                "text": match.group("date"),
                "precision": None,
                "resolution": None,
                "ambiguity_reason": (
                    f"The date {match.group('date')} could use day/month/year or "
                    "month/day/year. Choose the intended date below."
                    if second <= 12
                    else
                    f"The date {match.group('date')} looks like month/day/year, "
                    "but Hymn has no confirmed locale for numeric dates. "
                    "Choose the intended date below."
                ),
                "start": match.start("date"),
                "end": match.end("date"),
            })
        else:
            raise HTTPException(status_code=400, detail="desired_date is not a valid date")
    for pattern in (_MONTH_DAY_RE, _DAY_MONTH_RE):
        for match in pattern.finditer(cleaned):
            resolved, resolution = _calendar_date(
                match.group("month"),
                match.group("day"),
                match.group("year"),
                reference,
            )
            candidates.append({
                "date": resolved.isoformat(),
                "text": match.group(0),
                "precision": "exact_date",
                "resolution": resolution,
                "start": match.start(),
                "end": match.end(),
            })
    for match in _NEXT_MONTH_RE.finditer(cleaned):
        resolved = _next_month_date(reference)
        candidates.append({
            "date": resolved.isoformat(),
            "text": match.group(0),
            "precision": "relative_date",
            "resolution": (
                f"Resolved to the same day next month from {reference.isoformat()}, "
                "clamped to month end when needed"
            ),
            "start": match.start(),
            "end": match.end(),
        })

    unique = {
        (row["start"], row["end"], row["date"]): row
        for row in candidates
    }
    candidates = list(unique.values())
    if len(candidates) != 1 or (
        candidates and candidates[0].get("ambiguity_reason")
    ):
        first_candidate = min(candidates, key=lambda row: row["start"]) if candidates else None
        return {
            "date": None,
            "text": first_candidate.get("text") if first_candidate else None,
            "precision": None,
            "resolution": first_candidate.get("resolution") if first_candidate else None,
            "ambiguity_reason": (
                first_candidate.get("ambiguity_reason")
                if len(candidates) == 1 and first_candidate
                else "I found more than one possible date. Choose the intended date below."
                if len(candidates) > 1
                else None
            ),
            "match": first_candidate,
            "ambiguous": bool(candidates),
        }
    return {
        **candidates[0],
        "match": candidates[0],
        "ambiguity_reason": None,
        "ambiguous": False,
    }


def _clean_item(cleaned: str, verb_end: int, cutoffs: list[int]) -> Optional[str]:
    cutoff = min((value for value in cutoffs if value >= verb_end), default=len(cleaned))
    item = cleaned[verb_end:cutoff].strip(" .,!?:;-")
    item = re.sub(r"^(?:a|an|the)\s+", "", item, flags=re.IGNORECASE)
    item = re.sub(
        r"(?:\s+\b(?:for|by|on|around|about|before|after|in)\b)+\s*$",
        "",
        item,
        flags=re.IGNORECASE,
    )
    item = re.sub(r"(?:,\s*)?please$", "", item, flags=re.IGNORECASE)
    item = " ".join(item.split()).strip(" .,!?:;-")
    return item or None


def classify_intent(
    text: str,
    reference_date: Optional[str | date] = None,
) -> dict:
    """Classify and extract only deterministic, traceable purchase facts."""
    cleaned = " ".join(text.strip().split())
    if not cleaned:
        raise HTTPException(status_code=400, detail="Tell Hymn what you want to do")

    action = _PURCHASE_ACTION_RE.search(cleaned)
    if not action:
        return _unsupported_classification()

    reference = _reference_date(reference_date)
    price = _extract_price(cleaned)
    timing = _extract_timing(cleaned, reference)
    cutoffs = [
        row["start"]
        for row in (price.get("match"), timing.get("match"))
        if row
    ]
    item = _clean_item(cleaned, action.end("verb"), cutoffs)
    if (item or "").lower() in {
        "time",
        "some time",
        "more time",
        "into it",
        "order",
    }:
        return _unsupported_classification()

    ambiguities: list[str] = []
    if price["ambiguous"]:
        ambiguities.append("expected_price")
    if timing["ambiguous"]:
        ambiguities.append("desired_date")

    return {
        "intent_type": "purchase",
        "confidence": "deterministic",
        "item": item or None,
        "extracted_price": price["amount"],
        "extracted_currency": price["currency"],
        "extracted_date": timing["date"],
        "extracted_timing_text": timing["text"],
        "timing_precision": timing["precision"],
        "timing_resolution": timing["resolution"],
        "timing_ambiguity_reason": timing["ambiguity_reason"],
        "ambiguities": ambiguities,
    }


def _resolved_purchase_inputs(
    parsed: dict,
    supplied: PurchaseInputs,
    reporting_currency: Optional[str],
    reference: date,
) -> tuple[dict, list[dict]]:
    if supplied.price_unknown and supplied.expected_price:
        raise HTTPException(
            status_code=400,
            detail="expected_price cannot be set when price_unknown is true",
        )
    if supplied.timing_unknown and supplied.desired_date:
        raise HTTPException(
            status_code=400,
            detail="desired_date cannot be set when timing_unknown is true",
        )

    evidence: list[dict] = []
    field_sources = {
        "item": "inferred_from_text" if parsed.get("item") else "missing",
        "expected_price": "missing",
        "currency": "missing",
        "desired_date": "missing",
    }
    if parsed.get("item"):
        evidence.append({
            "id": "intent_text:item",
            "kind": "user_provided",
            "source": "inferred_from_text",
            "label": "Item inferred from your words",
            "value": parsed["item"],
        })
    price: Optional[str] = None
    if not supplied.price_unknown:
        if supplied.expected_price is not None:
            price = _money(_parse_amount(supplied.expected_price, "expected_price"))
            field_sources["expected_price"] = "user_edited"
            evidence.append({
                "id": "user_input:expected_price",
                "kind": "user_provided",
                "source": "user_edited",
                "label": "Expected price",
                "value": price,
            })
        elif parsed.get("extracted_price"):
            price = parsed["extracted_price"]
            field_sources["expected_price"] = "inferred_from_text"
            evidence.append({
                "id": "intent_text:expected_price",
                "kind": "user_provided",
                "source": "inferred_from_text",
                "label": "Expected price extracted from your words",
                "value": price,
            })
    elif supplied.price_unknown:
        field_sources["expected_price"] = "marked_unknown"

    desired_date: Optional[str] = None
    if not supplied.timing_unknown:
        if supplied.desired_date:
            desired_date = _parse_date(
                supplied.desired_date,
                "desired_date",
                reference,
            )
            field_sources["desired_date"] = "user_edited"
            evidence.append({
                "id": "user_input:desired_date",
                "kind": "user_provided",
                "source": "user_edited",
                "label": "Desired purchase date",
                "value": desired_date,
            })
        elif parsed.get("extracted_date"):
            desired_date = parsed["extracted_date"]
            field_sources["desired_date"] = "inferred_from_text"
            evidence.append({
                "id": "intent_text:desired_date",
                "kind": "user_provided",
                "source": "inferred_from_text",
                "label": "Purchase date extracted from your words",
                "value": desired_date,
            })
    elif supplied.timing_unknown:
        field_sources["desired_date"] = "marked_unknown"

    currency_raw = supplied.currency or parsed.get("extracted_currency") or reporting_currency
    currency = _parse_currency(currency_raw) if currency_raw else None
    if currency:
        source = (
            "user_edited"
            if supplied.currency
            else "inferred_from_text"
            if parsed.get("extracted_currency")
            else "known_profile"
        )
        field_sources["currency"] = source
        evidence.append({
            "id": f"{source}:currency",
            "kind": "known_fact" if source == "known_profile" else "user_provided",
            "source": source,
            "label": "Currency",
            "value": currency,
        })

    return {
        "item": parsed.get("item"),
        "expected_price": price,
        "currency": currency,
        "desired_date": desired_date,
        "timing_text": (
            parsed.get("extracted_timing_text")
            if field_sources["desired_date"] == "inferred_from_text"
            else None
        ),
        "timing_precision": (
            parsed.get("timing_precision")
            if field_sources["desired_date"] == "inferred_from_text"
            else "exact_date"
            if desired_date
            else None
        ),
        "timing_resolution": (
            parsed.get("timing_resolution")
            if field_sources["desired_date"] == "inferred_from_text"
            else None
        ),
        "field_sources": field_sources,
        "price_unknown": supplied.price_unknown,
        "timing_unknown": supplied.timing_unknown,
    }, evidence


async def _financial_context(
    db,
    user_id: str,
    purchase: dict,
) -> tuple[dict, list[dict], list[dict], list[str]]:
    currency = purchase.get("currency")
    desired_date = purchase.get("desired_date")
    evidence: list[dict] = []
    impacted: list[dict] = []
    queried: list[str] = []

    empty = {
        "currency": currency,
        "purchase_month": desired_date[:7] if desired_date else None,
        "liquid_assets": None,
        "planned_income": None,
        "planned_outflows": None,
        "planned_savings_and_investments": None,
        "actual_spending": None,
        "reserved_commitments_due": None,
        "available_before_purchase": None,
        "projected_after_purchase": None,
        "calculation": None,
        "has_financial_data": False,
        "has_liquid_balance": False,
    }
    if not currency:
        return empty, evidence, impacted, queried

    queried.append("financial_accounts")
    accounts = await db.financial_accounts.find(
        {"user_id": user_id, "currency": currency},
        {"_id": 0},
    ).to_list(length=5000)
    liquid_assets = Decimal(0)
    liquid_account_count = 0
    for account in accounts:
        if (
            account.get("account_type") in ASSET_ACCOUNT_TYPES
            and account.get("liquidity_type") == "liquid"
        ):
            liquid_account_count += 1
            amount = _decimal_from_stored(account.get("current_value"))
            liquid_assets += amount
            evidence.append({
                "id": f"financial_account:{account['id']}",
                "kind": "known_fact",
                "label": account.get("name") or "Liquid account",
                "value": _money(amount),
                "source": "financial_accounts",
            })

    if not desired_date:
        empty.update({
            "liquid_assets": _money(liquid_assets),
            "has_financial_data": bool(liquid_account_count),
            "has_liquid_balance": bool(liquid_account_count),
        })
        return empty, evidence, impacted, queried

    month = desired_date[:7]
    queried.extend([
        "monthly_money_commitments",
        "checkins",
        "resource_allocations",
    ])
    monthly = await db.monthly_money_commitments.find(
        {
            "user_id": user_id,
            "currency": currency,
            "start_month": {"$lte": month},
            "$or": [{"end_month": None}, {"end_month": {"$gte": month}}],
        },
        {"_id": 0},
    ).to_list(length=5000)

    income = Decimal(0)
    outflows = Decimal(0)
    savings_investments = Decimal(0)
    for row in monthly:
        amount = _decimal_from_stored(row.get("amount"))
        kind = row.get("commitment_type")
        if kind == "income":
            income += amount
        elif kind in {"expense", "debt_payment"}:
            outflows += amount
        elif kind in {"saving", "investment"}:
            savings_investments += amount
        evidence.append({
            "id": f"monthly_money_commitment:{row['id']}",
            "kind": "known_fact",
            "label": row.get("title") or "Monthly money commitment",
            "value": _money(amount),
            "source": "monthly_money_commitments",
        })

    spending_docs = await db.checkins.find(
        {
            "user_id": user_id,
            "money_currency": currency,
            "money_spent": {"$ne": None},
            "date": {"$regex": f"^{re.escape(month)}-"},
        },
        {"_id": 0, "id": 1, "title": 1, "money_spent": 1},
    ).to_list(length=20000)
    actual_spending = sum(
        (_decimal_from_stored(row.get("money_spent")) for row in spending_docs),
        Decimal(0),
    )
    for row in spending_docs:
        evidence.append({
            "id": f"checkin:{row['id']}",
            "kind": "known_fact",
            "label": row.get("title") or "Recorded spending",
            "value": _money(_decimal_from_stored(row.get("money_spent"))),
            "source": "checkins",
        })

    reserved = await db.resource_allocations.find(
        {
            "user_id": user_id,
            "resource_type": "money",
            "currency": currency,
            "status": "reserved",
            "date": {"$lte": desired_date},
        },
        {"_id": 0},
    ).to_list(length=5000)
    reserved_total = sum(
        (_decimal_from_stored(row.get("quantity")) for row in reserved),
        Decimal(0),
    )
    for row in reserved:
        evidence.append({
            "id": f"resource_allocation:{row['id']}",
            "kind": "known_fact",
            "label": row.get("title") or "Reserved money commitment",
            "value": _money(_decimal_from_stored(row.get("quantity"))),
            "source": "resource_allocations",
        })

    goal_ids = {row.get("goal_id") for row in reserved if row.get("goal_id")}
    project_ids = {row.get("project_id") for row in reserved if row.get("project_id")}
    goals = {
        row["id"]: row
        for row in await db.goals.find(
            {"user_id": user_id, "id": {"$in": list(goal_ids)}},
            {"_id": 0, "id": 1, "title": 1},
        ).to_list(length=5000)
    } if goal_ids else {}
    if goal_ids:
        queried.append("goals")
    projects = {
        row["id"]: row
        for row in await db.projects.find(
            {"user_id": user_id, "id": {"$in": list(project_ids)}},
            {"_id": 0, "id": 1, "title": 1},
        ).to_list(length=5000)
    } if project_ids else {}
    if project_ids:
        queried.append("projects")
    for row in reserved:
        goal = goals.get(row.get("goal_id"))
        project = projects.get(row.get("project_id"))
        if goal or project:
            impacted.append({
                "type": "goal" if goal else "project",
                "id": (goal or project)["id"],
                "title": (goal or project).get("title") or "Untitled",
                "reason": "It has a recorded money commitment due by the purchase date.",
                "evidence_id": f"resource_allocation:{row['id']}",
            })

    available = (
        liquid_assets
        + income
        - outflows
        - savings_investments
        - actual_spending
        - reserved_total
    )
    price = Decimal(purchase["expected_price"]) if purchase.get("expected_price") else None
    projected = available - price if price is not None else None
    has_data = bool(liquid_account_count or monthly or spending_docs or reserved)
    snapshot = {
        "currency": currency,
        "purchase_month": month,
        "liquid_assets": _money(liquid_assets),
        "planned_income": _money(income),
        "planned_outflows": _money(outflows),
        "planned_savings_and_investments": _money(savings_investments),
        "actual_spending": _money(actual_spending),
        "reserved_commitments_due": _money(reserved_total),
        "available_before_purchase": _money(available),
        "projected_after_purchase": _money(projected) if projected is not None else None,
        "calculation": (
            "liquid assets + planned income - planned outflows - planned savings "
            "- planned investments - recorded spending - reserved commitments"
        ),
        "has_financial_data": has_data,
        "has_liquid_balance": bool(liquid_account_count),
    }
    return snapshot, evidence, impacted, queried


def _affordability(
    purchase: dict,
    snapshot: dict,
) -> tuple[str, list[str]]:
    risks: list[str] = []
    if (
        not purchase.get("expected_price")
        or not purchase.get("desired_date")
        or not purchase.get("currency")
        or not snapshot.get("has_financial_data")
        or not snapshot.get("has_liquid_balance")
        or snapshot.get("projected_after_purchase") is None
    ):
        risks.append(
            "Hymn does not have enough recorded information to reach an affordability conclusion."
        )
        return "insufficient_data", risks

    price = Decimal(purchase["expected_price"])
    available = Decimal(snapshot["available_before_purchase"])
    projected = Decimal(snapshot["projected_after_purchase"])
    outflows = Decimal(snapshot["planned_outflows"])
    if projected < 0:
        risks.append(
            "The expected price is greater than the recorded capacity available before the purchase."
        )
        return "not_affordable", risks

    buffer_threshold = max(price * Decimal("0.20"), outflows * Decimal("0.50"))
    if projected <= buffer_threshold or available <= 0:
        risks.append(
            "The purchase fits inside recorded capacity but leaves a limited buffer."
        )
        return "borderline", risks

    risks.append(
        "The result depends on Hymn's recorded accounts and commitments remaining accurate."
    )
    return "affordable", risks


def _options(status: str, missing_data: list[str]) -> tuple[list[dict], str]:
    save = {
        "id": "save_only",
        "title": "Save this decision plan",
        "description": "Keep the intention in Hymn without creating a task, expense, or money commitment.",
        "downstream_effect": "none",
    }
    if status == "affordable":
        return [
            {
                "id": "create_draft_commitment",
                "title": "Create a draft money commitment",
                "description": "Prepare the purchase in Finance. No money is reserved until you confirm it there.",
                "downstream_effect": "draft_financial_commitment",
            },
            save,
            {
                "id": "wait_and_review",
                "title": "Wait and review again",
                "description": "Save the plan and revisit it closer to the desired date.",
                "downstream_effect": "none",
            },
        ], "create_draft_commitment"
    if status == "borderline":
        return [
            save,
            {
                "id": "wait_and_review",
                "title": "Wait and rebuild the buffer",
                "description": "Keep the plan and reassess after balances or commitments change.",
                "downstream_effect": "none",
            },
            {
                "id": "create_draft_commitment",
                "title": "Create a draft commitment for review",
                "description": "Prepare it in Finance without reserving money yet.",
                "downstream_effect": "draft_financial_commitment",
            },
        ], "wait_and_review"
    if status == "not_affordable":
        return [
            save,
            {
                "id": "reduce_price",
                "title": "Set a lower price target",
                "description": "Compare a lower expected price before creating a commitment.",
                "downstream_effect": "none",
            },
            {
                "id": "delay_purchase",
                "title": "Move the purchase later",
                "description": "Choose another date and reassess against later commitments.",
                "downstream_effect": "none",
            },
        ], "reduce_price"
    return [
        save,
        {
            "id": "add_missing_context",
            "title": "Add the missing context",
            "description": "Return with the missing purchase or finance details for a clearer assessment.",
            "downstream_effect": "none",
        },
    ], "add_missing_context" if missing_data else "save_only"


async def build_intent_assessment(
    db,
    current_user: dict,
    body: IntentAnalyzeRequest,
) -> dict:
    reference = _reference_date(body.reference_date)
    parsed = classify_intent(body.text, reference)
    if parsed["intent_type"] == "unsupported":
        return {
            "schema_version": INTENT_SCHEMA_VERSION,
            "assessment_version": PURCHASE_ASSESSMENT_VERSION,
            "original_text": " ".join(body.text.strip().split()),
            "reference_date": reference.isoformat(),
            "intent_type": "unsupported",
            "classification": parsed,
            "result_status": "unsupported",
            "supported_intent_types": list(SUPPORTED_INTENT_TYPES),
            "message": (
                "Hymn can currently turn purchase intentions into a decision plan. "
                "Your words are unchanged; try a purchase such as “Buy an iPad.”"
            ),
            "purchase": None,
            "missing_data": [],
            "clarification_questions": [],
            "affordability_status": "insufficient_data",
            "financial_snapshot": None,
            "impacted_goals_or_commitments": [],
            "risks_and_tradeoffs": [],
            "options": [],
            "recommended_option_id": None,
            "recommended_next_action": "Rephrase this as a purchase, or keep the text and return later.",
            "evidence": [],
            "contexts_queried": [],
            "can_confirm": False,
        }

    purchase, input_evidence = _resolved_purchase_inputs(
        parsed,
        body.purchase,
        current_user.get("portfolio_reporting_currency"),
        reference,
    )
    missing_data: list[str] = []
    questions: list[dict] = []
    if not purchase.get("item"):
        missing_data.append("item")
        questions.append({
            "field": "item",
            "question": "What are you considering buying?",
        })
    if not purchase.get("expected_price"):
        missing_data.append("expected_price")
        if not purchase.get("price_unknown"):
            questions.append({
                "field": "expected_price",
                "question": (
                    "I found more than one possible price. Which one should Hymn use?"
                    if "expected_price" in parsed["ambiguities"]
                    else "What price do you expect? You can also choose “I don’t know yet.”"
                ),
            })
    if not purchase.get("desired_date"):
        missing_data.append("desired_date")
        if not purchase.get("timing_unknown"):
            questions.append({
                "field": "desired_date",
                "question": (
                    parsed.get("timing_ambiguity_reason")
                    or "I found more than one possible date. Which one should Hymn use?"
                    if "desired_date" in parsed["ambiguities"]
                    else "When would you like to buy it? You can also choose “I don’t know yet.”"
                ),
            })
    if purchase.get("expected_price") and not purchase.get("currency"):
        missing_data.append("currency")
        questions.append({
            "field": "currency",
            "question": "Which currency is the expected price in?",
        })

    snapshot, finance_evidence, impacted, queried = await _financial_context(
        db,
        current_user["id"],
        purchase,
    )
    if purchase.get("currency") and not snapshot.get("has_liquid_balance"):
        missing_data.append("financial_context")

    affordability, risks = _affordability(purchase, snapshot)
    if impacted:
        risks.append(
            "Recorded goal or project commitments may compete with this purchase for the same money."
        )
    options, recommended_option = _options(affordability, missing_data)
    can_confirm = not questions
    result_status = "review_ready" if can_confirm else "needs_input"
    if not can_confirm:
        recommended_next = "Add the essential missing details, or mark them as unknown."
    elif affordability == "insufficient_data":
        recommended_next = "Save the intention, then add missing finance context before deciding."
    elif affordability == "affordable":
        recommended_next = "Review the evidence and create a draft commitment only if you agree."
    elif affordability == "borderline":
        recommended_next = "Keep a buffer or wait before creating a commitment."
    else:
        recommended_next = "Lower the price target or move the purchase later, then reassess."

    return {
        "schema_version": INTENT_SCHEMA_VERSION,
        "assessment_version": PURCHASE_ASSESSMENT_VERSION,
        "original_text": " ".join(body.text.strip().split()),
        "reference_date": reference.isoformat(),
        "intent_type": "purchase",
        "classification": parsed,
        "result_status": result_status,
        "supported_intent_types": list(SUPPORTED_INTENT_TYPES),
        "message": None,
        "purchase": {
            **purchase,
            "summary": (
                f"Considering {purchase['item']}"
                if purchase.get("item")
                else "Purchase item not yet specified"
            ),
        },
        "missing_data": list(dict.fromkeys(missing_data)),
        "clarification_questions": questions,
        "affordability_status": affordability,
        "financial_snapshot": snapshot,
        "impacted_goals_or_commitments": impacted,
        "risks_and_tradeoffs": risks,
        "options": options,
        "recommended_option_id": recommended_option,
        "recommended_next_action": recommended_next,
        "evidence": input_evidence + finance_evidence,
        "contexts_queried": queried,
        "can_confirm": can_confirm,
        "disclaimer": (
            "This is a planning aid based only on information recorded in Hymn, "
            "not financial advice or a guarantee."
        ),
    }


def _project_intent(doc: dict) -> dict:
    return {
        key: doc.get(key)
        for key in (
            "id",
            "schema_version",
            "assessment_version",
            "intent_type",
            "status",
            "original_text",
            "purchase",
            "assessment",
            "selected_option_id",
            "downstream_records",
            "created_at",
            "updated_at",
        )
    }


@intent_router.post("/analyze")
async def analyze_intent(
    body: IntentAnalyzeRequest,
    current_user: dict = Depends(get_current_user),
):
    return await build_intent_assessment(get_db(), current_user, body)


@intent_router.post("/confirm", status_code=201)
async def confirm_intent(
    body: IntentConfirmRequest,
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    user_id = current_user["id"]
    existing = await db.universal_intents.find_one(
        {"user_id": user_id, "idempotency_key": body.idempotency_key},
        {"_id": 0},
    )
    if existing:
        return _project_intent(existing)

    assessment = await build_intent_assessment(db, current_user, body)
    if assessment["intent_type"] != "purchase":
        raise HTTPException(status_code=400, detail="Only purchase intentions can be confirmed in v1")
    if not assessment["can_confirm"]:
        raise HTTPException(
            status_code=400,
            detail="Resolve the essential questions or mark the values as unknown before confirming",
        )
    available_options = {option["id"]: option for option in assessment["options"]}
    selected = available_options.get(body.selected_option_id)
    if not selected:
        raise HTTPException(status_code=400, detail="Selected option is not available for this assessment")

    now = _now()
    intent_id = str(uuid.uuid4())
    doc = {
        "id": intent_id,
        "user_id": user_id,
        "schema_version": INTENT_SCHEMA_VERSION,
        "assessment_version": PURCHASE_ASSESSMENT_VERSION,
        "intent_type": "purchase",
        "status": "confirming",
        "original_text": assessment["original_text"],
        "purchase": assessment["purchase"],
        "assessment": assessment,
        "selected_option_id": body.selected_option_id,
        "downstream_records": [],
        "idempotency_key": body.idempotency_key,
        "created_at": now,
        "updated_at": now,
    }
    try:
        await db.universal_intents.insert_one(doc)
    except DuplicateKeyError:
        raced = await db.universal_intents.find_one(
            {"user_id": user_id, "idempotency_key": body.idempotency_key},
            {"_id": 0},
        )
        if raced:
            return _project_intent(raced)
        raise

    commitment_id: Optional[str] = None
    try:
        if selected["downstream_effect"] == "draft_financial_commitment":
            purchase = assessment["purchase"]
            if not (
                purchase.get("expected_price")
                and purchase.get("currency")
                and purchase.get("desired_date")
            ):
                raise HTTPException(
                    status_code=400,
                    detail="A draft commitment requires a known price, currency, and date",
                )
            commitment_response = await create_commitment(
                FinancialCommitmentCreate(
                    title=f"Purchase: {purchase['item']}",
                    description=f"Created from confirmed Hymn intention {intent_id}.",
                    amount=purchase["expected_price"],
                    currency=purchase["currency"],
                    due_date=purchase["desired_date"],
                    priority="medium",
                    create_task=False,
                ),
                {"id": user_id},
            )
            commitment = (
                commitment_response.model_dump()
                if hasattr(commitment_response, "model_dump")
                else commitment_response
            )
            commitment_id = commitment["id"]
            await db.resource_allocations.update_one(
                {"user_id": user_id, "financial_commitment_id": commitment_id},
                {"$set": {
                    "source": "universal_intent",
                    "source_intent_id": intent_id,
                }},
            )
            await db.financial_audit.update_many(
                {
                    "user_id": user_id,
                    "record_type": "financial_commitment",
                    "record_id": commitment_id,
                },
                {"$set": {
                    "source": "universal_intent",
                    "new_value.source_intent_id": intent_id,
                }},
            )
            doc["downstream_records"] = [{
                "type": "financial_commitment",
                "id": commitment_id,
                "state": "draft",
            }]

        doc["status"] = "confirmed"
        doc["updated_at"] = _now()
        await db.universal_intents.update_one(
            {"id": intent_id, "user_id": user_id},
            {"$set": {
                "status": doc["status"],
                "downstream_records": doc["downstream_records"],
                "updated_at": doc["updated_at"],
            }},
        )
        doc.pop("_id", None)
        return _project_intent(doc)
    except Exception:
        await db.universal_intents.delete_one({"id": intent_id, "user_id": user_id})
        if commitment_id:
            await db.resource_allocations.delete_one({
                "user_id": user_id,
                "financial_commitment_id": commitment_id,
            })
            await db.financial_audit.delete_many({
                "user_id": user_id,
                "record_type": "financial_commitment",
                "record_id": commitment_id,
            })
        raise


@intent_router.get("")
async def list_intents(current_user: dict = Depends(get_current_user)):
    docs = await get_db().universal_intents.find(
        {"user_id": current_user["id"], "status": {"$ne": "confirming"}},
        {"_id": 0},
    ).sort("updated_at", -1).to_list(length=500)
    return [_project_intent(doc) for doc in docs]


@intent_router.get("/{intent_id}")
async def get_intent(
    intent_id: str,
    current_user: dict = Depends(get_current_user),
):
    doc = await get_db().universal_intents.find_one(
        {"id": intent_id, "user_id": current_user["id"]},
        {"_id": 0},
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Intention not found")
    return _project_intent(doc)


async def ensure_intent_indexes(database) -> None:
    await database.universal_intents.create_index("id", unique=True)
    await database.universal_intents.create_index([("user_id", 1), ("updated_at", -1)])
    await database.universal_intents.create_index(
        [("user_id", 1), ("idempotency_key", 1)],
        unique=True,
    )
