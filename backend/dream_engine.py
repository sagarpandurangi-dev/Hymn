"""Universal Dream Engine and editable Plan Map.

This module is Hymn's provider-neutral planning control plane.  The v1
implementation is deterministic and local; optional future providers can only
return schema-validated suggestions through :mod:`dream_providers`.

No Goal, Project, Outcome, Task, phase, or required check-in is created before
the authenticated owner applies a reviewed proposal revision.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from typing import Any, Dict, Iterable, List, Literal, Optional
import uuid

from bson.decimal128 import Decimal128
from fastapi import APIRouter, Depends, HTTPException, Query
from pymongo.errors import DuplicateKeyError
from pydantic import BaseModel, ConfigDict, Field

from dream_providers import (
    EvidenceItem,
    ExtractedFact,
    IntentInterpretationRequest,
    IntentInterpretationResult,
    InterpretationCandidate,
    PlanNodeSuggestion,
    PlanSynthesisRequest,
    PlanSynthesisResult,
    ProviderUnavailableError,
    ResearchQuestion,
)
from deps import get_current_user, get_db
from intent_engine import classify_intent


dream_router = APIRouter(prefix="/dreams", tags=["dreams"])

DREAM_SCHEMA_VERSION = 1
INTERPRETATION_VERSION = 1
SCALE_VERSION = 1
PLAN_MAP_VERSION = 1
RANK_STEP = 1024

SOURCE_TYPES = ("intent", "learning", "goal", "project", "journey")
NODE_KINDS = ("phase", "milestone", "task", "checkin_requirement")
NODE_ORIGINS = ("hymn", "user")
DECISION_STATES = ("proposed", "accepted", "modified", "rejected", "deferred")
RESEARCH_STATES = (
    "research_not_needed",
    "research_recommended",
    "research_in_progress",
    "research_ready",
    "research_stale",
    "research_failed",
    "manual_input_required",
)
PLANNING_DEPTHS = ("light", "moderate", "major", "transformational")
CHECKIN_SCHEDULE_TYPES = (
    "one_time",
    "recurring",
    "milestone_triggered",
    "manual",
)

JOURNEY_SHAPES = [
    {
        "id": "professional_qualification",
        "label": "Attain a professional qualification",
        "description": "Work toward a recognised credential or licence.",
        "keywords": (
            "qualification", "certification", "certified", "chartered",
            "licence", "license", "exam", "ca ", "cfa", "acca",
        ),
    },
    {
        "id": "learn_skill",
        "label": "Learn a skill",
        "description": "Build practical ability through practice.",
        "keywords": ("learn to", "skill", "practice", "speak ", "play "),
    },
    {
        "id": "complete_course",
        "label": "Complete a course",
        "description": "Finish a defined programme of study.",
        "keywords": ("course", "class", "programme", "program", "bootcamp"),
    },
    {
        "id": "learn_subject",
        "label": "Learn a subject",
        "description": "Understand a topic or field more deeply.",
        "keywords": ("study", "understand", "learn about", "subject"),
    },
    {
        "id": "read_book",
        "label": "Read a book",
        "description": "Read and, if useful, reflect on a book.",
        "keywords": ("read ", "book", "novel"),
    },
    {
        "id": "purchase",
        "label": "Make a purchase",
        "description": "Consider affordability, timing, and trade-offs.",
        "keywords": ("buy ", "purchase ", "get a ", "get an ", "price", "cost"),
    },
    {
        "id": "trip",
        "label": "Plan a trip",
        "description": "Clarify destination, timing, money, and commitments.",
        "keywords": ("trip", "travel", "holiday", "vacation", "visit "),
    },
    {
        "id": "meeting_event",
        "label": "Arrange a meeting/event",
        "description": "Bring people, timing, and purpose together.",
        "keywords": ("meeting", "event", "party", "wedding", "arrange", "organise", "organize"),
    },
    {
        "id": "financial_target",
        "label": "Reach a financial target",
        "description": "Define a money result and assess the recorded gap.",
        "keywords": ("save ", "bank by", "net worth", "financial target", "pay off", "million"),
    },
    {
        "id": "health_wellbeing",
        "label": "Improve health/wellbeing",
        "description": "Plan carefully around health or wellbeing context.",
        "keywords": ("health", "fitness", "wellbeing", "well-being", "sleep", "exercise", "weight"),
    },
    {
        "id": "custom",
        "label": "Build a custom journey",
        "description": "Start from your own words without forcing a template.",
        "keywords": (),
    },
]
SHAPE_BY_ID = {shape["id"]: shape for shape in JOURNEY_SHAPES}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


def _stable_apply_uuid(proposal_id: str, revision: int, action_id: str) -> str:
    return str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"hymn:dream-apply:{proposal_id}:{revision}:{action_id}",
    ))


def _require(condition: bool, detail: str, status_code: int = 400) -> None:
    if not condition:
        raise HTTPException(status_code=status_code, detail=detail)


def _normal_text(value: str) -> str:
    return " ".join((value or "").strip().split())


def _decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        if isinstance(value, Decimal128):
            return value.to_decimal()
        result = Decimal(str(value).replace(",", ""))
        return result if result.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def _money(value: Decimal) -> str:
    return f"{value:.2f}"


def _shape_score(text: str, shape: dict) -> int:
    lowered = f" {text.lower()} "
    score = 0
    for keyword in shape["keywords"]:
        if keyword in lowered:
            score += 5 if keyword.strip() in {"buy", "purchase", "read", "trip"} else 3
    label_words = {
        word for word in re.findall(r"[a-z]+", shape["label"].lower())
        if len(word) > 3
        and word not in {
            "make", "plan", "learn", "reach", "complete", "arrange",
            "attain", "build", "improve",
        }
    }
    score += sum(1 for word in label_words if word in lowered)
    return score


def rank_journey_shapes(text: str, limit: int = 11) -> List[dict]:
    """Rank all lenses deterministically while always keeping custom available."""
    query = _normal_text(text)
    scored = [
        ({k: v for k, v in shape.items() if k != "keywords"}, _shape_score(query, shape))
        for shape in JOURNEY_SHAPES
    ]
    scored.sort(
        key=lambda row: (
            row[0]["id"] == "custom",
            -row[1],
            next(i for i, shape in enumerate(JOURNEY_SHAPES) if shape["id"] == row[0]["id"]),
        )
    )
    rows = [
        {**shape, "match_score": score}
        for shape, score in scored[: max(1, min(limit, len(scored)))]
    ]
    if not any(row["id"] == "custom" for row in rows):
        custom = next(row for row in scored if row[0]["id"] == "custom")
        rows[-1] = {**custom[0], "match_score": custom[1]}
    return rows


def _candidate(shape_id: str, score: int, top_score: int) -> InterpretationCandidate:
    shape = SHAPE_BY_ID[shape_id]
    if score <= 0:
        confidence: Literal["clear", "likely", "ambiguous"] = "ambiguous"
        reason = "Your words do not match a supported journey clearly yet."
    elif score == top_score and score >= 6:
        confidence = "clear"
        reason = "The action and subject in your words strongly match this journey."
    elif score == top_score:
        confidence = "likely"
        reason = "This is the closest supported journey to the words you used."
    else:
        confidence = "ambiguous"
        reason = "This is another reasonable way to shape the same dream."
    return InterpretationCandidate(
        journey_shape=shape_id,
        label=shape["label"],
        reason=reason,
        confidence=confidence,
    )


def _general_money_fact(text: str) -> tuple[Optional[str], Optional[str]]:
    patterns = [
        r"(?P<symbol>₹|\$)\s*(?P<amount>\d[\d,]*(?:\.\d{1,2})?)",
        r"(?P<code>INR|USD|EUR|GBP)\s*(?P<amount>\d[\d,]*(?:\.\d{1,2})?)",
        r"(?P<amount>\d[\d,]*(?:\.\d{1,2})?)\s*(?P<code>INR|USD|EUR|GBP)",
    ]
    matches: List[tuple[str, str]] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            amount = _decimal(match.group("amount"))
            if amount is None or amount <= 0:
                continue
            code = match.groupdict().get("code")
            symbol = match.groupdict().get("symbol")
            currency = (code or {"₹": "INR", "$": "USD"}.get(symbol or "", "")).upper()
            matches.append((_money(amount), currency))
    unique = list(dict.fromkeys(matches))
    scaled = re.search(
        r"(?P<symbol>₹|\$|INR|USD|EUR|GBP)\s*"
        r"(?P<amount>\d+(?:\.\d+)?)\s*"
        r"(?P<scale>thousand|million|billion|lakh|crore)\b",
        text,
        flags=re.IGNORECASE,
    )
    if scaled:
        multiplier = {
            "thousand": Decimal("1000"),
            "million": Decimal("1000000"),
            "billion": Decimal("1000000000"),
            "lakh": Decimal("100000"),
            "crore": Decimal("10000000"),
        }[scaled.group("scale").lower()]
        amount = _decimal(scaled.group("amount"))
        symbol = scaled.group("symbol").upper()
        currency = {"₹": "INR", "$": "USD"}.get(symbol, symbol)
        if amount is not None:
            return _money(amount * multiplier), currency
    return unique[0] if len(unique) == 1 else (None, None)


def _general_date_fact(text: str) -> tuple[Optional[str], Optional[str]]:
    """Extract only calendar dates whose interpretation is unambiguous."""
    iso = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    if iso:
        try:
            return date.fromisoformat(iso.group(1)).isoformat(), None
        except ValueError:
            return None, "The date in your words is not a real calendar date."

    numeric = re.search(r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b", text)
    if numeric:
        day_value, month_value, year_value = map(int, numeric.groups())
        if day_value <= 12 and month_value <= 12:
            return None, (
                f"{numeric.group(0)} could mean day/month or month/day. "
                "Choose a date explicitly."
            )
        if day_value <= 12 < month_value:
            return None, (
                f"{numeric.group(0)} looks month/day, but Hymn has no reliable "
                "locale rule for that format. Choose a date explicitly."
            )
        try:
            return date(year_value, month_value, day_value).isoformat(), None
        except ValueError:
            return None, "The date in your words is not a real calendar date."

    month_names = {
        "jan": 1, "january": 1, "feb": 2, "february": 2,
        "mar": 3, "march": 3, "apr": 4, "april": 4, "may": 5,
        "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8,
        "august": 8, "sep": 9, "sept": 9, "september": 9,
        "oct": 10, "october": 10, "nov": 11, "november": 11,
        "dec": 12, "december": 12,
    }
    written = re.search(
        r"\b(?:(?P<day_first>\d{1,2})\s+(?P<month_first>[A-Za-z]+)"
        r"|(?P<month_second>[A-Za-z]+)\s+(?P<day_second>\d{1,2}))"
        r"(?:,)?\s+(?P<year>20\d{2})\b",
        text,
        flags=re.IGNORECASE,
    )
    if written:
        month_word = (
            written.group("month_first") or written.group("month_second") or ""
        ).lower()
        month_value = month_names.get(month_word)
        if month_value:
            day_value = int(written.group("day_first") or written.group("day_second"))
            try:
                return date(int(written.group("year")), month_value, day_value).isoformat(), None
            except ValueError:
                return None, "The date in your words is not a real calendar date."
    return None, None


def _general_subject(text: str, shape_id: str) -> Optional[str]:
    patterns = {
        "learn_skill": r"\b(?:learn to|learn|practice)\s+(.+?)(?:\s+by\b|\s+before\b|$)",
        "learn_subject": r"\b(?:learn about|study|understand)\s+(.+?)(?:\s+by\b|\s+before\b|$)",
        "complete_course": r"\b(?:complete|finish)\s+(.+?\b(?:course|class|bootcamp|program|programme))",
        "read_book": r"\bread\s+(.+?)(?:\s+by\b|\s+before\b|$)",
        "trip": r"\b(?:trip|travel|holiday|vacation|visit)\s+(?:to\s+)?(.+?)(?:\s+by\b|\s+on\b|\s+before\b|$)",
    }
    pattern = patterns.get(shape_id)
    if not pattern:
        return None
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    value = _normal_text(match.group(1)).strip(" ,.;")
    return value[:240] if value else None


def deterministic_interpretation(
    text: str,
    reference_date: str,
    selected_shape: Optional[str] = None,
) -> IntentInterpretationResult:
    """Return a conservative typed interpretation with no network access."""
    original = _normal_text(text)
    _require(bool(original), "Tell Hymn what you want to do.")
    if selected_shape is not None:
        _require(selected_shape in SHAPE_BY_ID, "Unknown journey shape")

    ranked = rank_journey_shapes(original)
    top_score = ranked[0]["match_score"]
    inferred_shape = ranked[0]["id"] if top_score > 0 else "custom"
    shape_id = selected_shape or inferred_shape
    primary_score = next(
        row["match_score"] for row in ranked if row["id"] == shape_id
    )
    primary = _candidate(shape_id, primary_score, max(top_score, primary_score))
    if selected_shape:
        primary = primary.model_copy(update={
            "confidence": "clear",
            "reason": "You chose this journey shape, so Hymn will use it.",
        })

    alternatives = [
        _candidate(row["id"], row["match_score"], top_score)
        for row in ranked
        if row["id"] != shape_id and (row["match_score"] > 0 or row["id"] == "custom")
    ][:3]
    evidence = [
        EvidenceItem(
            id="dream-text",
            kind="user_fact",
            label="Your words",
            summary=original,
        )
    ]
    facts: List[ExtractedFact] = [
        ExtractedFact(
            key="desired_outcome",
            value=original,
            value_type="text",
            origin="user_provided",
            evidence_ids=["dream-text"],
        ),
        ExtractedFact(
            key="journey_shape",
            value=shape_id,
            value_type="choice",
            origin="user_corrected" if selected_shape else "inferred",
            evidence_ids=["dream-text"],
        ),
    ]
    uncertainties: List[str] = []

    if shape_id == "purchase":
        purchase = classify_intent(original, reference_date)
        mappings = [
            ("desired_object", purchase.get("item"), "text"),
            ("amount", purchase.get("extracted_price"), "money"),
            ("currency", purchase.get("extracted_currency"), "choice"),
            ("deadline", purchase.get("extracted_date"), "date"),
        ]
        for key, value, value_type in mappings:
            if value is not None:
                facts.append(ExtractedFact(
                    key=key,
                    value=value,
                    value_type=value_type,
                    origin="inferred",
                    evidence_ids=["dream-text"],
                ))
        if not purchase.get("item"):
            uncertainties.append("What are you considering buying?")
        if not purchase.get("extracted_price"):
            uncertainties.append("What price should Hymn use?")
        if purchase.get("extracted_price") and not purchase.get("extracted_currency"):
            uncertainties.append("Which currency is the price in?")
        if not purchase.get("extracted_date"):
            uncertainties.append("When would you like to make the purchase?")
        for ambiguity in purchase.get("ambiguities") or []:
            uncertainties.append(f"Please clarify {ambiguity.replace('_', ' ')}.")
    else:
        amount, currency = _general_money_fact(original)
        if amount:
            facts.extend([
                ExtractedFact(
                    key="amount",
                    value=amount,
                    value_type="money",
                    origin="inferred",
                    evidence_ids=["dream-text"],
                ),
                ExtractedFact(
                    key="currency",
                    value=currency,
                    value_type="choice",
                    origin="inferred",
                    evidence_ids=["dream-text"],
                ),
            ])
        deadline, date_uncertainty = _general_date_fact(original)
        if deadline:
            facts.append(ExtractedFact(
                key="deadline",
                value=deadline,
                value_type="date",
                origin="inferred",
                evidence_ids=["dream-text"],
            ))
        if date_uncertainty:
            uncertainties.append(date_uncertainty)
        subject = _general_subject(original, shape_id)
        if subject:
            facts.append(ExtractedFact(
                key="desired_object",
                value=subject,
                value_type="text",
                origin="inferred",
                evidence_ids=["dream-text"],
            ))

    beneficiary = re.search(
        r"\bfor my (son|daughter|mother|father|wife|husband|partner|team|child|children|friend)\b",
        original,
        flags=re.IGNORECASE,
    )
    if beneficiary:
        facts.append(ExtractedFact(
            key="beneficiary",
            value=f"my {beneficiary.group(1).lower()}",
            value_type="person",
            origin="inferred",
            evidence_ids=["dream-text"],
        ))
    starting = re.search(
        r"\b(?:i am currently|i'm currently|currently|i already|i've already)\s+([^.;]+)",
        original,
        flags=re.IGNORECASE,
    )
    if starting:
        facts.append(ExtractedFact(
            key="starting_point",
            value=_normal_text(starting.group(0)),
            value_type="text",
            origin="inferred",
            evidence_ids=["dream-text"],
        ))
    constraint = re.search(
        r"\b((?:without|must not|cannot|can't|within a budget of)\s+[^.;]+)",
        original,
        flags=re.IGNORECASE,
    )
    if constraint:
        facts.append(ExtractedFact(
            key="constraints",
            value=_normal_text(constraint.group(1)),
            value_type="text",
            origin="inferred",
            evidence_ids=["dream-text"],
        ))
    preference = re.search(
        r"\b((?:i prefer|preferably|ideally)\s+[^.;]+)",
        original,
        flags=re.IGNORECASE,
    )
    if preference:
        facts.append(ExtractedFact(
            key="preferences",
            value=_normal_text(preference.group(1)),
            value_type="text",
            origin="inferred",
            evidence_ids=["dream-text"],
        ))

    if shape_id in {"professional_qualification", "trip"}:
        uncertainties.append(
            "Current external requirements may need authoritative research or your own source."
        )
    return IntentInterpretationResult(
        provider_kind="deterministic",
        primary=primary,
        alternatives=alternatives,
        facts=facts,
        uncertainties=list(dict.fromkeys(uncertainties)),
        evidence=evidence,
    )


def _facts_by_key(interpretation: dict) -> Dict[str, dict]:
    return {fact["key"]: fact for fact in interpretation.get("facts") or []}


def _refresh_interpretation_uncertainties(interpretation: dict) -> None:
    """Keep clarification needs aligned with authoritative corrections."""
    facts = _facts_by_key(interpretation)
    unknown = set(interpretation.get("unknown_fact_keys") or [])
    shape = interpretation["primary"]["journey_shape"]
    if shape == "purchase":
        uncertainties: List[str] = []
        if not (facts.get("desired_object") or {}).get("value") and "desired_object" not in unknown:
            uncertainties.append("What are you considering buying?")
        if (
            not (facts.get("amount") or {}).get("value")
            or not (facts.get("currency") or {}).get("value")
        ) and not {"amount", "currency"}.intersection(unknown):
            uncertainties.append("What price range are you considering?")
        if not (facts.get("deadline") or {}).get("value") and "deadline" not in unknown:
            uncertainties.append("When would you like to buy?")
        interpretation["uncertainties"] = uncertainties


def apply_fact_corrections(
    interpretation: dict,
    selected_shape: Optional[str],
    corrections: Dict[str, Any],
    not_sure_fields: Optional[List[str]] = None,
) -> dict:
    """Preserve inferred facts while making explicit user corrections authoritative."""
    result = deepcopy(interpretation)
    by_key = _facts_by_key(result)
    if selected_shape is not None:
        _require(selected_shape in SHAPE_BY_ID, "Unknown journey shape")
        shape = SHAPE_BY_ID[selected_shape]
        result["primary"] = {
            "journey_shape": selected_shape,
            "label": shape["label"],
            "reason": "You chose this journey shape, so Hymn will use it.",
            "confidence": "clear",
        }
        corrections = {**corrections, "journey_shape": selected_shape}
    allowed = {
        "desired_outcome": "text",
        "desired_object": "text",
        "beneficiary": "person",
        "amount": "money",
        "currency": "choice",
        "deadline": "date",
        "starting_point": "text",
        "constraints": "text",
        "preferences": "text",
        "journey_shape": "choice",
    }
    unknown = set(result.get("unknown_fact_keys") or [])
    not_sure = set(not_sure_fields or [])
    _require(not_sure.issubset(allowed), "Unsupported not-sure field")
    for key, value in corrections.items():
        _require(key in allowed, f"Unsupported fact correction: {key}")
        if key == "deadline" and value:
            try:
                date.fromisoformat(str(value))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Deadline must be a real YYYY-MM-DD date") from exc
        if key == "amount" and value not in (None, ""):
            amount = _decimal(value)
            _require(amount is not None and amount > 0, "Amount must be greater than zero")
            value = _money(amount)
        if key == "currency" and value not in (None, ""):
            value = str(value).upper()
            _require(bool(re.fullmatch(r"[A-Z]{3}", value)), "Currency must be a three-letter code")
        row = {
            "key": key,
            "value": value,
            "value_type": allowed[key],
            "origin": "user_corrected",
            "evidence_ids": ["user-correction"],
            "uncertainty": None,
        }
        if key in by_key:
            result["facts"] = [
                row if fact["key"] == key else fact
                for fact in result["facts"]
            ]
        else:
            result.setdefault("facts", []).append(row)
        by_key[key] = row
        if value not in (None, ""):
            unknown.discard(key)
    for key in not_sure:
        row = {
            "key": key,
            "value": None,
            "value_type": allowed[key],
            "origin": "user_corrected",
            "evidence_ids": ["user-correction"],
            "uncertainty": "You chose to leave this open for now.",
        }
        if key in by_key:
            result["facts"] = [
                row if fact["key"] == key else fact
                for fact in result["facts"]
            ]
        else:
            result.setdefault("facts", []).append(row)
        by_key[key] = row
        unknown.add(key)
    result["unknown_fact_keys"] = sorted(unknown)
    _refresh_interpretation_uncertainties(result)
    result.setdefault("evidence", []).append({
        "id": "user-correction",
        "kind": "user_fact",
        "label": "Your corrections",
        "summary": "Values edited during review are authoritative.",
        "source_record_type": None,
        "source_record_id": None,
        "url": None,
        "title": None,
        "publisher": None,
        "retrieved_at": None,
        "effective_date": None,
        "expires_at": None,
    })
    return result


async def _owned_target(db, user_id: str, source_type: str, source_id: Optional[str]) -> Optional[dict]:
    if source_type in {"intent", "learning"} and not source_id:
        return None
    if source_type == "goal":
        return await db.goals.find_one({"id": source_id, "user_id": user_id}, {"_id": 0})
    if source_type == "project":
        return await db.projects.find_one({"id": source_id, "user_id": user_id}, {"_id": 0})
    if source_type == "journey":
        journey = await db.knowledge_journeys.find_one(
            {"id": source_id, "user_id": user_id}, {"_id": 0},
        )
        if not journey:
            return None
        goal = await db.goals.find_one(
            {"id": journey["goal_id"], "user_id": user_id}, {"_id": 0},
        )
        return {**journey, "title": (goal or {}).get("title", ""), "goal": goal}
    return None


def _target_text(source_type: str, target: Optional[dict], supplied_text: str) -> str:
    if supplied_text.strip():
        return _normal_text(supplied_text)
    if source_type == "goal" and target:
        return _normal_text(
            " ".join(filter(None, [target.get("title"), target.get("target_outcome")]))
        )
    if source_type == "project" and target:
        return _normal_text(
            " ".join(filter(None, [target.get("title"), target.get("description")]))
        )
    if source_type == "journey" and target:
        return _normal_text((target.get("goal") or {}).get("title") or target.get("title") or "")
    return ""


async def _owned_context(
    db,
    user_id: str,
    source_type: str,
    source_id: Optional[str],
    target: Optional[dict],
    interpretation: dict,
    profile_currency: Optional[str] = None,
) -> dict:
    facts = _facts_by_key(interpretation)
    currency = (facts.get("currency") or {}).get("value")
    evidence: List[dict] = []
    queried: List[str] = []

    context_currency = currency or profile_currency
    account_query: dict = {"user_id": user_id}
    if context_currency:
        account_query["currency"] = context_currency
    queried.append("financial_accounts")
    accounts = (
        await db.financial_accounts.find(account_query, {"_id": 0}).to_list(length=5000)
        if context_currency
        else []
    )
    liquid = Decimal(0)
    liquid_count = 0
    compatible_accounts = []
    for account in accounts:
        if (
            account.get("account_type") in {
                "bank", "cash", "savings", "current_account", "checking"
            }
            and account.get("liquidity_type") == "liquid"
        ):
            value = _decimal(account.get("current_value"))
            if value is not None:
                liquid += value
                liquid_count += 1
                compatible_accounts.append({
                    "id": account["id"],
                    "name": account.get("name") or "Recorded liquid account",
                    "currency": account.get("currency"),
                    "recorded_value": _money(value),
                    "updated_at": account.get("updated_at"),
                })
                evidence.append({
                    "id": f"financial_account:{account['id']}",
                    "kind": "hymn_owned_context",
                    "label": account.get("name") or "Recorded liquid account",
                    "summary": (
                        f"Recorded balance {account.get('currency')} {_money(value)}"
                    ),
                    "source_record_type": "financial_account",
                    "source_record_id": account["id"],
                })

    queried.append("financial_events")
    events = await db.financial_events.find(
        {
            "user_id": user_id,
            "confirmation_status": "confirmed",
            "amount": {"$ne": None},
            "$or": [
                {"reconciliation_status": {"$in": [
                    "awaiting_reconciliation", "unmatched", "resolved_unplanned",
                ]}},
                {"reconciliation_status": {"$exists": False}},
            ],
            "account_id": {"$exists": False},
        },
        {"_id": 0},
    ).to_list(length=5000)
    unresolved_by_currency: Dict[str, Decimal] = {}
    for event in events:
        event_currency = event.get("currency")
        value = _decimal(event.get("amount"))
        if event_currency and value is not None:
            unresolved_by_currency[event_currency] = (
                unresolved_by_currency.get(event_currency, Decimal(0)) + abs(value)
            )

    queried.extend(["goals", "projects", "tasks", "checkins"])
    active_goals = await db.goals.find(
        {
            "user_id": user_id,
            "status": "active",
            **({"id": {"$ne": source_id}} if source_type == "goal" and source_id else {}),
        },
        {"_id": 0, "id": 1, "title": 1, "deadline": 1},
    ).to_list(length=1000)
    active_projects = await db.projects.find(
        {
            "user_id": user_id,
            "status": "active",
            **({"id": {"$ne": source_id}} if source_type == "project" and source_id else {}),
        },
        {"_id": 0, "id": 1, "title": 1, "target_end_date": 1},
    ).to_list(length=1000)
    open_tasks = await db.tasks.count_documents({
        "user_id": user_id,
        "status": {"$in": ["todo", "deferred"]},
    })
    recent_checkins = await db.checkins.count_documents({"user_id": user_id})

    source_summary = None
    if target:
        source_summary = {
            "type": source_type,
            "id": source_id,
            "title": target.get("title") or (target.get("goal") or {}).get("title"),
            "deadline": (
                target.get("deadline")
                or target.get("target_end_date")
                or (target.get("goal") or {}).get("deadline")
            ),
        }
        evidence.append({
            "id": f"{source_type}:{source_id}",
            "kind": "hymn_owned_context",
            "label": f"Recorded {source_type}",
            "summary": source_summary["title"] or "Untitled",
            "source_record_type": source_type,
            "source_record_id": source_id,
        })

    return {
        "source": source_summary,
        "finance": {
            "requested_currency": currency,
            "profile_currency": profile_currency,
            "recorded_currency": context_currency,
            "compatible_liquid_accounts": compatible_accounts,
            "recorded_liquid_total": _money(liquid) if liquid_count else None,
            "recorded_liquid_account_count": liquid_count,
            "unresolved_movements": {
                code: _money(value) for code, value in unresolved_by_currency.items()
            },
            "balance_label": "Recorded liquid balance",
            "freshness_warning": (
                "Recorded balances may be stale because some spending has not been "
                "linked to an account."
                if unresolved_by_currency else None
            ),
        },
        "commitments": {
            "other_active_goals": [
                {"id": row["id"], "title": row.get("title")}
                for row in active_goals
            ],
            "other_active_projects": [
                {"id": row["id"], "title": row.get("title")}
                for row in active_projects
            ],
            "open_task_count": open_tasks,
            "recorded_checkin_count": recent_checkins,
        },
        "domains_queried": queried,
        "domains_with_data": [
            domain for domain, has_data in [
                ("money", bool(accounts)),
                ("commitments", bool(active_goals or active_projects or open_tasks)),
                ("progress", bool(recent_checkins)),
            ] if has_data
        ],
        "evidence": evidence,
    }


def relative_scale(interpretation: dict, context: dict, reference_date: str) -> dict:
    """Explain planning depth across independent, user-relative axes."""
    facts = _facts_by_key(interpretation)
    amount = _decimal((facts.get("amount") or {}).get("value"))
    currency = (facts.get("currency") or {}).get("value")
    deadline_text = (facts.get("deadline") or {}).get("value")
    finance = context.get("finance") or {}
    liquid = _decimal(finance.get("recorded_liquid_total"))
    requested_currency = finance.get("requested_currency")
    unresolved = finance.get("unresolved_movements") or {}
    shape = interpretation["primary"]["journey_shape"]

    financial_level: Optional[str] = None
    financial_summary: str
    calculations: List[dict] = []
    if amount is None:
        financial_summary = "No confirmed amount is available, so financial burden is not classified."
    elif not currency:
        financial_summary = "The amount has no confirmed currency, so Hymn cannot compare it."
    elif requested_currency != currency or liquid is None:
        financial_summary = (
            f"No compatible recorded liquid balance is available in {currency}; "
            "no currency conversion is assumed."
        )
    else:
        ratio = amount / liquid if liquid > 0 else None
        gap = liquid - amount
        calculations.extend([
            {
                "label": "Confirmed amount",
                "value": f"{currency} {_money(amount)}",
                "evidence_kind": "user_fact",
            },
            {
                "label": "Compatible recorded liquid resources",
                "value": f"{currency} {_money(liquid)}",
                "evidence_kind": "hymn_owned_context",
            },
            {
                "label": "Recorded gap after amount",
                "value": f"{currency} {_money(gap)}",
                "evidence_kind": "deterministic_calculation",
            },
        ])
        if liquid <= 0 or amount > liquid:
            financial_level = "transformational" if liquid <= 0 or amount > liquid * 5 else "major"
            financial_summary = "The confirmed amount exceeds compatible recorded liquid resources."
        elif ratio is not None and ratio <= Decimal("0.01"):
            financial_level = "light"
            financial_summary = "The amount is at most 1% of compatible recorded liquid resources."
        elif ratio is not None and ratio <= Decimal("0.10"):
            financial_level = "moderate"
            financial_summary = "The amount is between 1% and 10% of compatible recorded liquid resources."
        elif ratio is not None and ratio <= Decimal("0.50"):
            financial_level = "major"
            financial_summary = "The amount uses a substantial share of compatible recorded liquid resources."
        else:
            financial_level = "transformational"
            financial_summary = "The amount uses more than half of compatible recorded liquid resources."
        if currency in unresolved:
            financial_summary += (
                f" {currency} {unresolved[currency]} of recorded money movement is "
                "not reflected in an account, so this comparison is less certain."
            )

    duration_level: Optional[str] = None
    duration_summary = "No confirmed deadline is available."
    if deadline_text:
        try:
            start = date.fromisoformat(reference_date)
            end = date.fromisoformat(str(deadline_text))
            days = (end - start).days
            if days < 0:
                duration_summary = "The confirmed deadline is in the past and needs correction."
            else:
                duration_level = (
                    "light" if days <= 30
                    else "moderate" if days <= 180
                    else "major" if days <= 1095
                    else "transformational"
                )
                duration_summary = f"The recorded horizon is {days} days."
                calculations.append({
                    "label": "Time remaining",
                    "value": f"{days} days",
                    "evidence_kind": "deterministic_calculation",
                })
        except ValueError:
            duration_summary = "The deadline is not a valid calendar date."

    dependency_level = (
        "major" if shape in {"professional_qualification", "trip", "meeting_event"}
        else "moderate" if shape in {"complete_course", "financial_target", "health_wellbeing"}
        else "light"
    )
    uncertainty_count = len(interpretation.get("uncertainties") or [])
    uncertainty_level = (
        "light" if uncertainty_count == 0
        else "moderate" if uncertainty_count <= 2
        else "major"
    )
    conflict_count = (
        len((context.get("commitments") or {}).get("other_active_goals") or [])
        + len((context.get("commitments") or {}).get("other_active_projects") or [])
    )
    conflict_level = "light" if conflict_count == 0 else "moderate" if conflict_count <= 3 else "major"

    levels = [financial_level, duration_level, dependency_level, uncertainty_level, conflict_level]
    order = {name: index for index, name in enumerate(PLANNING_DEPTHS)}
    recommended = max((level for level in levels if level), key=order.get, default="moderate")
    return {
        "version": SCALE_VERSION,
        "recommended_depth": recommended,
        "user_selected_depth": None,
        "summary": (
            f"Hymn recommends {recommended} planning depth for the recorded burden "
            "and uncertainty. This describes planning effort, not the dream's importance."
        ),
        "axes": [
            {"id": "financial", "level": financial_level, "summary": financial_summary},
            {"id": "time", "level": None, "summary": "No declared or trusted effort estimate is available."},
            {"id": "duration", "level": duration_level, "summary": duration_summary},
            {
                "id": "dependencies",
                "level": dependency_level,
                "summary": "This is a cautious structural estimate; specific dependencies remain editable.",
            },
            {
                "id": "uncertainty",
                "level": uncertainty_level,
                "summary": f"{uncertainty_count} clarification point(s) remain.",
            },
            {
                "id": "conflicts",
                "level": conflict_level,
                "summary": f"{conflict_count} other active goal/project commitment(s) were found.",
            },
            {
                "id": "health_energy",
                "level": None,
                "summary": "Hymn did not use health or energy data because no relevant owned evidence was queried.",
            },
        ],
        "calculations": calculations,
        "missing": [
            axis["id"] for axis in [
                {"id": "financial", "level": financial_level},
                {"id": "time", "level": None},
                {"id": "duration", "level": duration_level},
            ] if axis["level"] is None
        ],
    }


def _node(
    kind: str,
    title: str,
    *,
    parent_id: Optional[str] = None,
    rank: int = 0,
    description: str = "",
    origin: str = "hymn",
    timing: Optional[dict] = None,
    dependencies: Optional[List[str]] = None,
    evidence_ids: Optional[List[str]] = None,
    assumptions: Optional[List[str]] = None,
    checkin: Optional[dict] = None,
) -> dict:
    return {
        "id": _uuid(),
        "kind": kind,
        "parent_id": parent_id,
        "rank": rank,
        "title": title,
        "description": description,
        "origin": origin,
        "decision_state": "proposed" if origin == "hymn" else "accepted",
        "timing": timing,
        "dependencies": dependencies or [],
        "evidence_ids": evidence_ids or [],
        "assumptions": assumptions or [],
        "checkin": checkin,
        "revision": 1,
        "created_at": _now(),
        "updated_at": _now(),
    }


def deterministic_plan(
    interpretation: dict,
    context: dict,
    scale: dict,
    user_nodes: Optional[List[dict]] = None,
) -> List[dict]:
    """Suggest a deliberately compact tree; never pad or invent domain phases."""
    nodes = deepcopy(user_nodes or [])
    for node in nodes:
        node["origin"] = "user"
        node["decision_state"] = node.get("decision_state") or "accepted"
    facts = _facts_by_key(interpretation)
    shape = interpretation["primary"]["journey_shape"]
    outcome = (facts.get("desired_outcome") or {}).get("value") or "Your dream"
    object_name = (facts.get("desired_object") or {}).get("value")
    deadline = (facts.get("deadline") or {}).get("value")

    if nodes:
        return validate_plan_tree(nodes)

    if shape == "purchase":
        label = object_name or "the purchase"
        milestone = _node(
            "milestone",
            f"Make a well-informed decision about {label}",
            rank=RANK_STEP,
            description="Review the known facts and decide whether, when, and how to proceed.",
            evidence_ids=["dream-text"],
            timing={"target_date": deadline} if deadline else None,
        )
        nodes.append(milestone)
        tasks = []
        if not (facts.get("amount") and facts.get("currency")):
            tasks.append(("Confirm the expected price and currency", "Record a price you trust or mark it unknown."))
        tasks.extend([
            ("Review affordability and trade-offs", "Use only the recorded context shown by Hymn."),
            ("Choose whether to proceed, wait, or change the target", "The final decision remains yours."),
        ])
        for index, (title, description) in enumerate(tasks, start=1):
            task = _node(
                "task", title, parent_id=milestone["id"], rank=index * RANK_STEP,
                description=description,
            )
            nodes.append(task)
            if index == len(tasks):
                nodes.append(_node(
                    "checkin_requirement",
                    "Decision review",
                    parent_id=task["id"],
                    rank=RANK_STEP,
                    description="Record the choice and the evidence that changed it.",
                    checkin={
                        "schedule_type": "manual",
                        "question": "What did you decide, and what evidence mattered?",
                        "evidence_type": "note",
                    },
                ))
        return validate_plan_tree(nodes)

    if shape in {"professional_qualification", "trip"}:
        milestone = _node(
            "milestone",
            "Confirm the authoritative requirements",
            rank=RANK_STEP,
            description=(
                "Use an official source or enter the requirements yourself. "
                "Hymn will not invent changing external rules."
            ),
        )
        nodes.append(milestone)
        nodes.append(_node(
            "task",
            "Add the confirmed requirements and starting point",
            parent_id=milestone["id"],
            rank=RANK_STEP,
            description="Your wording remains authoritative and editable.",
        ))
        return validate_plan_tree(nodes)

    depth = scale.get("user_selected_depth") or scale.get("recommended_depth")
    long_plan = depth in {"major", "transformational"}
    if long_plan:
        phases = [
            ("Clarify the route", "Confirm the desired outcome, starting point, and important constraints."),
            ("Build the first workable stage", "Choose the first measurable result without inventing specialist steps."),
            ("Review and adapt", "Use recorded evidence to decide the next revision."),
        ]
        for phase_index, (title, description) in enumerate(phases, start=1):
            phase = _node("phase", title, rank=phase_index * RANK_STEP, description=description)
            nodes.append(phase)
            milestone = _node(
                "milestone",
                f"{title} is complete",
                parent_id=phase["id"],
                rank=RANK_STEP,
                description=description,
            )
            nodes.append(milestone)
            task = _node(
                "task",
                title,
                parent_id=milestone["id"],
                rank=RANK_STEP,
                description="Edit this task so its completion condition is specific to your situation.",
            )
            nodes.append(task)
            nodes.append(_node(
                "checkin_requirement",
                "Stage review",
                parent_id=task["id"],
                rank=RANK_STEP,
                description="Pause and decide whether the map still fits.",
                checkin={
                    "schedule_type": "milestone_triggered",
                    "question": "What changed, what evidence do you have, and should the plan be revised?",
                    "evidence_type": "note",
                },
            ))
    else:
        milestone = _node(
            "milestone",
            f"Reach: {outcome[:180]}",
            rank=RANK_STEP,
            description="This uses your own words as the desired result.",
            timing={"target_date": deadline} if deadline else None,
            evidence_ids=["dream-text"],
        )
        nodes.append(milestone)
        nodes.append(_node(
            "task",
            "Define the next observable step",
            parent_id=milestone["id"],
            rank=RANK_STEP,
            description="Replace this suggestion with your own step if you already know it.",
        ))
    return validate_plan_tree(nodes)


class DeterministicIntentInterpretationProvider:
    """Offline interpretation adapter implementing the provider contract."""

    async def interpret(
        self,
        request: IntentInterpretationRequest,
    ) -> IntentInterpretationResult:
        return deterministic_interpretation(
            request.original_text,
            request.reference_date,
            request.user_selected_shape,
        )


class DeterministicPlanSynthesisProvider:
    """Offline synthesis adapter with no database or network capability."""

    async def synthesize(
        self,
        request: PlanSynthesisRequest,
    ) -> PlanSynthesisResult:
        summary = request.approved_context_summary
        suggested = deterministic_plan(
            request.interpretation.model_dump(),
            summary.get("context") or {},
            summary.get("scale") or {
                "recommended_depth": "moderate",
                "user_selected_depth": None,
            },
            [node.model_dump() for node in request.user_plan_nodes],
        )
        nodes = [
            PlanNodeSuggestion.model_validate({
                key: value for key, value in node.items()
                if key in PlanNodeSuggestion.model_fields
            })
            for node in suggested
        ]
        return PlanSynthesisResult(
            provider_kind="deterministic",
            nodes=nodes,
            assumptions=[],
            warnings=[
                "Local synthesis is conservative and does not invent specialist requirements."
            ],
        )


def _allowed_parent(kind: str, parent_kind: Optional[str]) -> bool:
    return {
        "phase": parent_kind is None,
        "milestone": parent_kind in {None, "phase"},
        "task": parent_kind in {None, "phase", "milestone"},
        "checkin_requirement": parent_kind == "task",
    }[kind]


def _siblings(nodes: List[dict], parent_id: Optional[str]) -> List[dict]:
    return sorted(
        [node for node in nodes if node.get("parent_id") == parent_id],
        key=lambda node: (int(node.get("rank", 0)), node["id"]),
    )


def _descendant_ids(nodes: List[dict], root_id: str) -> set[str]:
    result: set[str] = set()
    frontier = [root_id]
    while frontier:
        parent = frontier.pop()
        children = [node["id"] for node in nodes if node.get("parent_id") == parent]
        for child in children:
            if child not in result:
                result.add(child)
                frontier.append(child)
    return result


def _normalize_ranks(nodes: List[dict]) -> List[dict]:
    result = deepcopy(nodes)
    parents = {node.get("parent_id") for node in result}
    for parent_id in parents:
        for index, sibling in enumerate(_siblings(result, parent_id), start=1):
            target = next(node for node in result if node["id"] == sibling["id"])
            target["rank"] = index * RANK_STEP
    return result


def validate_plan_tree(nodes: Iterable[dict]) -> List[dict]:
    """Return a normalized tree or reject malformed/cyclic hierarchy."""
    rows = [deepcopy(node) for node in nodes]
    _require(len(rows) <= 500, "A plan map can contain at most 500 nodes")
    ids = [node.get("id") for node in rows]
    _require(all(isinstance(node_id, str) and node_id for node_id in ids), "Every node needs a stable id")
    _require(len(ids) == len(set(ids)), "Plan node ids must be unique")
    by_id = {node["id"]: node for node in rows}
    for node in rows:
        _require(node.get("kind") in NODE_KINDS, f"Unsupported node kind: {node.get('kind')}")
        _require(node.get("origin") in NODE_ORIGINS, "Node origin must be hymn or user")
        _require(node.get("decision_state") in DECISION_STATES, "Invalid node decision state")
        title = _normal_text(str(node.get("title") or ""))
        _require(bool(title), "Every plan node needs a title")
        _require(len(title) <= 240, "Plan node titles must be at most 240 characters")
        node["title"] = title
        node["description"] = str(node.get("description") or "").strip()[:4000]
        parent_id = node.get("parent_id")
        _require(parent_id != node["id"], "A node cannot be its own parent")
        parent = by_id.get(parent_id) if parent_id else None
        _require(parent_id is None or parent is not None, f"Node {node['id']} has an unknown parent")
        _require(
            _allowed_parent(node["kind"], parent.get("kind") if parent else None),
            f"{node['kind']} cannot be placed under {parent.get('kind') if parent else 'the plan root'}",
        )
        dependencies = node.get("dependencies") or []
        _require(len(dependencies) == len(set(dependencies)), "Node dependencies must be unique")
        for dependency in dependencies:
            _require(dependency in by_id, f"Node {node['id']} has an unknown dependency")
            _require(dependency != node["id"], "A node cannot depend on itself")
        if node["kind"] == "checkin_requirement":
            checkin = node.get("checkin") or {}
            _require(
                checkin.get("schedule_type") in CHECKIN_SCHEDULE_TYPES,
                "Required check-in needs a supported schedule type",
            )
            _require(
                bool(_normal_text(checkin.get("question") or "")),
                "Required check-in needs a plain-language question",
            )
            schedule_type = checkin["schedule_type"]
            if schedule_type == "one_time":
                due_date = checkin.get("due_date")
                try:
                    date.fromisoformat(str(due_date))
                except (TypeError, ValueError) as exc:
                    raise HTTPException(
                        status_code=400,
                        detail="A one-time required check-in needs a real YYYY-MM-DD due date",
                    ) from exc
            if schedule_type == "recurring":
                _require(
                    checkin.get("cadence") in {"daily", "weekly", "monthly"},
                    "A recurring required check-in needs a daily, weekly, or monthly cadence",
                )
            if schedule_type == "milestone_triggered" and not checkin.get("trigger_node_id"):
                parent = by_id.get(node.get("parent_id"))
                while parent and parent.get("kind") != "milestone":
                    parent = by_id.get(parent.get("parent_id"))
                _require(
                    parent is not None,
                    "A milestone-triggered check-in needs an ancestor milestone",
                )
                checkin["trigger_node_id"] = parent["id"]
            if checkin.get("trigger_node_id"):
                trigger = by_id.get(checkin["trigger_node_id"])
                _require(
                    trigger is not None and trigger.get("kind") == "milestone",
                    "A required check-in trigger must reference a milestone in this map",
                )
            node["checkin"] = checkin
        elif node.get("checkin") is not None:
            _require(False, "Only required check-in nodes may contain check-in settings")

    # Parent cycles.
    for node in rows:
        seen = {node["id"]}
        current = node
        while current.get("parent_id"):
            parent_id = current["parent_id"]
            _require(parent_id not in seen, "Plan hierarchy cannot contain a cycle")
            seen.add(parent_id)
            current = by_id[parent_id]

    # Dependency cycles.
    state: Dict[str, int] = {}

    def visit(node_id: str) -> None:
        if state.get(node_id) == 1:
            raise HTTPException(status_code=400, detail="Plan dependencies cannot contain a cycle")
        if state.get(node_id) == 2:
            return
        state[node_id] = 1
        for dependency in by_id[node_id].get("dependencies") or []:
            visit(dependency)
        state[node_id] = 2

    for node_id in by_id:
        visit(node_id)
    return _normalize_ranks(rows)


def display_plan_tree(nodes: List[dict]) -> List[dict]:
    """Derive human numbering from order without changing stable identities."""
    valid = validate_plan_tree(nodes)
    result: List[dict] = []

    def walk(parent_id: Optional[str], prefix: str = "") -> None:
        children = _siblings(valid, parent_id)
        for index, node in enumerate(children, start=1):
            number = f"{prefix}.{index}" if prefix else str(index)
            result.append({**node, "display_number": number})
            walk(node["id"], number)

    walk(None)
    return result


def _public_nodes(nodes: List[dict]) -> List[dict]:
    """Expose editable structure without technical provenance/timestamps."""
    allowed = {
        "id", "kind", "parent_id", "rank", "display_number", "title",
        "description", "origin", "decision_state", "timing", "dependencies",
        "assumptions", "checkin", "revision",
    }
    return [
        {key: value for key, value in node.items() if key in allowed}
        for node in display_plan_tree(nodes)
    ]


def _insert_position(
    nodes: List[dict],
    parent_id: Optional[str],
    relative_id: Optional[str],
    placement: str,
) -> int:
    siblings = _siblings(nodes, parent_id)
    if placement == "inside_end" or not relative_id:
        return len(siblings)
    index = next((i for i, row in enumerate(siblings) if row["id"] == relative_id), -1)
    _require(index >= 0, "The relative node is not a sibling")
    return index if placement == "before" else index + 1


def apply_tree_operation(nodes: List[dict], operation: dict) -> List[dict]:
    """Apply one explicit edit and verify the entire resulting tree."""
    rows = validate_plan_tree(nodes)
    op = operation.get("type")
    by_id = {node["id"]: node for node in rows}
    now = _now()

    if op == "accept_all":
        for node in rows:
            if node["decision_state"] == "proposed":
                node["decision_state"] = "accepted"
                node["updated_at"] = now
        return validate_plan_tree(rows)

    if op == "add":
        incoming = deepcopy(operation.get("node") or {})
        incoming.setdefault("id", _uuid())
        incoming.setdefault("origin", "user")
        incoming.setdefault("decision_state", "accepted")
        incoming.setdefault("description", "")
        incoming.setdefault("dependencies", [])
        incoming.setdefault("evidence_ids", [])
        incoming.setdefault("assumptions", [])
        incoming.setdefault("timing", None)
        incoming.setdefault("checkin", None)
        incoming.setdefault("revision", 1)
        incoming.setdefault("created_at", now)
        incoming["updated_at"] = now
        parent_id = operation.get("parent_id")
        incoming["parent_id"] = parent_id
        index = _insert_position(
            rows,
            parent_id,
            operation.get("relative_id"),
            operation.get("placement") or "inside_end",
        )
        siblings = _siblings(rows, parent_id)
        siblings.insert(index, incoming)
        rows.append(incoming)
        for position, sibling in enumerate(siblings, start=1):
            next_node = incoming if sibling["id"] == incoming["id"] else by_id[sibling["id"]]
            next_node["rank"] = position * RANK_STEP
        return validate_plan_tree(rows)

    node_id = operation.get("node_id")
    _require(node_id in by_id, "Plan node not found", 404)
    target = by_id[node_id]

    if op == "update":
        patch = deepcopy(operation.get("patch") or {})
        protected = {"id", "kind", "parent_id", "rank", "origin", "created_at"}
        _require(not protected.intersection(patch), "Use a move operation for hierarchy changes")
        for key in (
            "title", "description", "timing", "dependencies", "evidence_ids",
            "assumptions", "checkin",
        ):
            if key in patch:
                target[key] = patch[key]
        target["decision_state"] = (
            "modified" if target["origin"] == "hymn" else "accepted"
        )
        target["revision"] = int(target.get("revision") or 1) + 1
        target["updated_at"] = now
        return validate_plan_tree(rows)

    if op == "decide":
        state = operation.get("decision_state")
        _require(state in DECISION_STATES, "Invalid decision state")
        target["decision_state"] = state
        target["updated_at"] = now
        return validate_plan_tree(rows)

    if op == "move":
        parent_id = operation.get("parent_id")
        _require(parent_id != node_id, "A node cannot be moved inside itself")
        _require(parent_id not in _descendant_ids(rows, node_id), "A subtree cannot move inside its descendant")
        old_parent = target.get("parent_id")
        target["parent_id"] = parent_id
        target["updated_at"] = now
        rows = _normalize_ranks(rows)
        by_id = {node["id"]: node for node in rows}
        target = by_id[node_id]
        index = _insert_position(
            rows,
            parent_id,
            operation.get("relative_id"),
            operation.get("placement") or "inside_end",
        )
        siblings = [row for row in _siblings(rows, parent_id) if row["id"] != node_id]
        siblings.insert(index, target)
        for position, sibling in enumerate(siblings, start=1):
            by_id[sibling["id"]]["rank"] = position * RANK_STEP
        if old_parent != parent_id:
            rows = _normalize_ranks(rows)
        return validate_plan_tree(rows)

    if op == "delete":
        mode = operation.get("delete_mode")
        descendants = _descendant_ids(rows, node_id)
        if descendants and mode == "reparent_children":
            destination = operation.get("destination_parent_id")
            direct_children = [row for row in rows if row.get("parent_id") == node_id]
            for child in direct_children:
                child["parent_id"] = destination
            rows = [row for row in rows if row["id"] != node_id]
        elif not descendants or mode == "remove_subtree":
            removing = descendants | {node_id}
            rows = [row for row in rows if row["id"] not in removing]
            for row in rows:
                row["dependencies"] = [
                    dep for dep in row.get("dependencies") or [] if dep not in removing
                ]
        else:
            raise HTTPException(
                status_code=409,
                detail=(
                    "This node has children. Choose to remove the whole subtree "
                    "or move its children to a valid destination."
                ),
            )
        return validate_plan_tree(rows)

    if op == "duplicate":
        descendants = _descendant_ids(rows, node_id)
        subtree = [row for row in display_plan_tree(rows) if row["id"] in descendants | {node_id}]
        id_map = {row["id"]: _uuid() for row in subtree}
        parent_id = operation.get("parent_id", target.get("parent_id"))
        copies = []
        for row in subtree:
            copied = {key: value for key, value in row.items() if key != "display_number"}
            copied["id"] = id_map[row["id"]]
            copied["parent_id"] = (
                parent_id if row["id"] == node_id
                else id_map.get(row.get("parent_id"))
            )
            copied["dependencies"] = [
                id_map.get(dep, dep) for dep in row.get("dependencies") or []
            ]
            copied["origin"] = "user"
            copied["decision_state"] = "accepted"
            copied["revision"] = 1
            copied["created_at"] = now
            copied["updated_at"] = now
            copies.append(copied)
        rows.extend(copies)
        return validate_plan_tree(rows)

    raise HTTPException(status_code=400, detail=f"Unsupported tree operation: {op}")


def preserve_user_nodes(existing_nodes: List[dict], suggested_nodes: List[dict]) -> List[dict]:
    """Never overwrite user-created or user-modified nodes during recomputation."""
    protected = [
        deepcopy(node) for node in existing_nodes
        if node.get("origin") == "user" or node.get("decision_state") == "modified"
    ]
    protected_ids = {node["id"] for node in protected}
    return validate_plan_tree([
        *protected,
        *[node for node in suggested_nodes if node["id"] not in protected_ids],
    ])


def research_state_for(interpretation: dict) -> dict:
    shape = interpretation["primary"]["journey_shape"]
    if shape in {"professional_qualification", "trip"}:
        questions = [
            ResearchQuestion(
                id="official-requirements",
                question="What current official requirements and stages apply?",
                why_needed="Requirements may change and Hymn will not invent them.",
                preferred_publishers=["Official governing or issuing body"],
            ).model_dump()
        ]
        return {
            "state": "research_recommended",
            "message": (
                "Authoritative research could improve this map. No research provider "
                "is enabled, so you can add an official source or enter the facts manually."
            ),
            "questions": questions,
            "evidence": [],
            "provider_enabled": False,
        }
    return {
        "state": "research_not_needed",
        "message": "No public-web research is required for the current local proposal.",
        "questions": [],
        "evidence": [],
        "provider_enabled": False,
    }


def _source_return(source_type: str, source_id: Optional[str], proposal_id: str) -> dict:
    if source_type == "goal" and source_id:
        return {
            "route": f"/goals/{source_id}", "label": "Return to goal",
            "target_type": "goal", "target_id": source_id,
        }
    if source_type == "project" and source_id:
        return {
            "route": f"/projects/{source_id}", "label": "Return to project",
            "target_type": "project", "target_id": source_id,
        }
    if source_type == "journey" and source_id:
        return {
            "route": f"/knowledge/{source_id}", "label": "Return to learning journey",
            "target_type": "journey", "target_id": source_id,
        }
    if source_type == "learning":
        return {
            "route": f"/dreams/{proposal_id}", "label": "View learning plan",
            "target_type": "learning", "target_id": proposal_id,
        }
    return {
        "route": f"/dreams/{proposal_id}", "label": "View this intention",
        "target_type": "intent", "target_id": proposal_id,
    }


def _snapshot_hash(target: Optional[dict], context: dict) -> str:
    stable = {
        "target": target,
        "finance": context.get("finance"),
        "commitments": context.get("commitments"),
    }
    return hashlib.sha256(
        json.dumps(stable, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _clarification_questions(interpretation: dict) -> List[dict]:
    facts = _facts_by_key(interpretation)
    unknown = set(interpretation.get("unknown_fact_keys") or [])
    if interpretation["primary"]["journey_shape"] != "purchase":
        return [
            {
                "id": f"question-{index}",
                "kind": "text",
                "prompt": question,
                "why": "This would make the plan more specific, but you can continue without it.",
                "fact_keys": [],
                "status": "missing",
                "value": None,
            }
            for index, question in enumerate(interpretation.get("uncertainties") or [])
        ]

    amount = (facts.get("amount") or {}).get("value")
    currency = (facts.get("currency") or {}).get("value")
    deadline = (facts.get("deadline") or {}).get("value")
    price_unknown = bool({"amount", "currency"}.intersection(unknown))
    deadline_unknown = "deadline" in unknown
    return [
        {
            "id": "purchase-price",
            "kind": "money",
            "prompt": "What price range are you considering?",
            "why": (
                "A price and currency let Hymn compare the purchase with compatible "
                "recorded resources. No currency conversion is assumed."
            ),
            "fact_keys": ["amount", "currency"],
            "status": "unknown" if price_unknown else "answered" if amount and currency else "missing",
            "value": {"amount": amount, "currency": currency},
        },
        {
            "id": "purchase-timing",
            "kind": "date",
            "prompt": "When would you like to buy?",
            "why": "Timing changes the available preparation time and which commitments may overlap.",
            "fact_keys": ["deadline"],
            "status": "unknown" if deadline_unknown else "answered" if deadline else "missing",
            "value": deadline,
        },
    ]


def public_proposal(proposal: dict) -> dict:
    """Return the typed UI contract without raw owned records or provenance codes."""
    interpretation = proposal["interpretation"]
    context = proposal["context"]
    facts = [
        {
            "key": fact["key"],
            "value": fact.get("value"),
            "value_type": fact["value_type"],
            "origin": fact["origin"],
            "uncertainty": fact.get("uncertainty"),
        }
        for fact in interpretation.get("facts") or []
    ]
    return {
        "id": proposal["id"],
        "schema_version": proposal["schema_version"],
        "source": proposal["source"],
        "status": proposal["status"],
        "revision": proposal["revision"],
        "original_text": proposal["original_text"],
        "interpretation": {
            "version": proposal["interpretation_version"],
            "primary": interpretation["primary"],
            "alternatives": interpretation.get("alternatives") or [],
            "facts": facts,
            "uncertainties": interpretation.get("uncertainties") or [],
            "questions": _clarification_questions(interpretation),
            "why": {
                "summary": interpretation["primary"]["reason"],
                "evidence": [
                    item["summary"] for item in interpretation.get("evidence") or []
                ],
            },
        },
        "context": {
            "source": context.get("source"),
            "finance": context.get("finance"),
            "commitments": context.get("commitments"),
            "domains_queried": context.get("domains_queried") or [],
            "domains_with_data": context.get("domains_with_data") or [],
            "honesty": (
                "Hymn used only the recorded domains listed here. Missing domains "
                "were not treated as checked."
            ),
            "why": {
                "evidence": [
                    row["summary"] for row in context.get("evidence") or []
                ]
            },
        },
        "scale": proposal["scale"],
        "research": proposal["research"],
        "map": {
            "version": PLAN_MAP_VERSION,
            "revision": proposal["map"]["revision"],
            "nodes": _public_nodes(proposal["map"]["nodes"]),
            "can_undo": bool(proposal["map"].get("history")),
        },
        "creation_preview": proposal.get("creation_preview") or {},
        "applied_plan": proposal.get("applied_plan"),
        "return_to": proposal["return_to"],
        "updated_at": proposal["updated_at"],
    }


class DreamAnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: Literal["intent", "learning", "goal", "project", "journey"]
    source_id: Optional[str] = None
    text: str = Field(default="", max_length=4000)
    selected_shape: Optional[str] = None
    reference_date: Optional[str] = None
    user_plan_nodes: List[PlanNodeSuggestion] = Field(default_factory=list)


class DreamCorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    selected_shape: Optional[str] = None
    fact_corrections: Dict[str, Any] = Field(default_factory=dict)
    not_sure_fields: List[str] = Field(default_factory=list)
    planning_depth: Optional[Literal["light", "moderate", "major", "transformational"]] = None


class DreamTreeOperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    operation: Dict[str, Any]


class DreamTreeReplaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    nodes: List[Dict[str, Any]]


class DreamApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    accepted_node_ids: List[str]


async def _load_owned_proposal(db, user_id: str, proposal_id: str) -> dict:
    proposal = await db.dream_proposals.find_one(
        {"id": proposal_id, "user_id": user_id}, {"_id": 0},
    )
    if not proposal:
        raise HTTPException(status_code=404, detail="Dream proposal not found")
    return proposal


async def _save_revision(
    db,
    proposal: dict,
    expected_revision: int,
    *,
    old_nodes: Optional[List[dict]] = None,
) -> dict:
    _require(
        proposal["revision"] == expected_revision,
        "This dream changed in another tab. Refresh before saving.",
        409,
    )
    if old_nodes is not None:
        history = proposal["map"].setdefault("history", [])
        history.append({
            "map_revision": proposal["map"]["revision"],
            "nodes": old_nodes,
            "recorded_at": _now(),
        })
        proposal["map"]["history"] = history[-20:]
        proposal["map"]["revision"] += 1
    proposal["revision"] += 1
    proposal["updated_at"] = _now()
    result = await db.dream_proposals.replace_one(
        {
            "id": proposal["id"],
            "user_id": proposal["user_id"],
            "revision": expected_revision,
        },
        proposal,
    )
    _require(
        result.matched_count == 1,
        "This dream changed in another tab. Refresh before saving.",
        409,
    )
    return proposal


def _creation_preview(proposal: dict) -> dict:
    included = [
        node for node in proposal["map"]["nodes"]
        if node["decision_state"] in {"accepted", "modified"}
    ]
    counts = {kind: sum(node["kind"] == kind for node in included) for kind in NODE_KINDS}
    return {
        "summary": (
            "Nothing has been created yet. Applying this revision will create "
            "only the accepted items listed below."
        ),
        "counts": counts,
        "source_effect": (
            "Attach to the existing target"
            if proposal["source"]["type"] in {"goal", "project", "journey"}
            else "Create one owned active Dream plan"
        ),
    }


@dream_router.get("/journey-shapes")
async def journey_shapes(q: str = Query(default="", max_length=4000)):
    return {
        "shapes": rank_journey_shapes(q),
        "reduced_motion_contract": {
            "effect": "materialize_text",
            "duration_ms": 180,
            "reduced_motion_duration_ms": 0,
            "interaction_delay_ms": 0,
        },
    }


@dream_router.post("/analyze")
async def analyze_dream(
    body: DreamAnalyzeRequest,
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    _require(body.source_type in SOURCE_TYPES, "Unsupported Dream source")
    target = await _owned_target(
        db, current_user["id"], body.source_type, body.source_id,
    )
    if body.source_type in {"goal", "project", "journey"}:
        _require(target is not None, f"{body.source_type.title()} not found", 404)
    text = _target_text(body.source_type, target, body.text)
    _require(bool(text), "Tell Hymn what you want to do.")
    reference = body.reference_date or date.today().isoformat()
    try:
        date.fromisoformat(reference)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="reference_date must be YYYY-MM-DD") from exc

    interpretation = deterministic_interpretation(
        text, reference, body.selected_shape,
    ).model_dump()
    context = await _owned_context(
        db,
        current_user["id"],
        body.source_type,
        body.source_id,
        target,
        interpretation,
        current_user.get("portfolio_reporting_currency"),
    )
    scale = relative_scale(interpretation, context, reference)
    user_nodes = [node.model_dump() for node in body.user_plan_nodes]
    suggested = deterministic_plan(interpretation, context, scale, user_nodes)
    proposal_id = _uuid()
    now = _now()
    proposal = {
        "id": proposal_id,
        "user_id": current_user["id"],
        "schema_version": DREAM_SCHEMA_VERSION,
        "source": {
            "type": body.source_type,
            "id": body.source_id,
            "title": (target or {}).get("title") or text[:200],
        },
        "original_text": text,
        "reference_date": reference,
        "interpretation_version": INTERPRETATION_VERSION,
        "interpretation": interpretation,
        "context": context,
        "context_snapshot_hash": _snapshot_hash(target, context),
        "scale": scale,
        "research": research_state_for(interpretation),
        "map": {"revision": 1, "nodes": suggested, "history": []},
        "status": "review",
        "revision": 1,
        "creation_preview": {},
        "applied_plan": None,
        "decision_history": [],
        "return_to": _source_return(body.source_type, body.source_id, proposal_id),
        "created_at": now,
        "updated_at": now,
    }
    proposal["creation_preview"] = _creation_preview(proposal)
    await db.dream_proposals.insert_one(proposal)
    proposal.pop("_id", None)
    return public_proposal(proposal)


@dream_router.get("/{proposal_id}")
async def get_dream(
    proposal_id: str,
    current_user: dict = Depends(get_current_user),
):
    proposal = await _load_owned_proposal(get_db(), current_user["id"], proposal_id)
    return public_proposal(proposal)


@dream_router.patch("/{proposal_id}/interpretation")
async def correct_dream(
    proposal_id: str,
    body: DreamCorrectionRequest,
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    proposal = await _load_owned_proposal(db, current_user["id"], proposal_id)
    _require(not proposal.get("applied_plan"), "An applied plan needs a new proposal revision", 409)
    original_interpretation = deepcopy(proposal["interpretation"])
    proposal["interpretation"] = apply_fact_corrections(
        proposal["interpretation"],
        body.selected_shape,
        body.fact_corrections,
        body.not_sure_fields,
    )
    target = await _owned_target(
        db,
        current_user["id"],
        proposal["source"]["type"],
        proposal["source"].get("id"),
    )
    proposal["context"] = await _owned_context(
        db,
        current_user["id"],
        proposal["source"]["type"],
        proposal["source"].get("id"),
        target,
        proposal["interpretation"],
        current_user.get("portfolio_reporting_currency"),
    )
    proposal["context_snapshot_hash"] = _snapshot_hash(target, proposal["context"])
    if body.planning_depth:
        proposal["scale"]["user_selected_depth"] = body.planning_depth
        proposal["scale"]["summary"] = (
            f"You chose {body.planning_depth} planning depth. "
            "This controls map detail, not the dream's importance."
        )
    proposal["scale"] = {
        **relative_scale(
            proposal["interpretation"], proposal["context"], proposal["reference_date"],
        ),
        "user_selected_depth": body.planning_depth or proposal["scale"].get("user_selected_depth"),
    }
    suggested = deterministic_plan(
        proposal["interpretation"], proposal["context"], proposal["scale"],
    )
    old_nodes = deepcopy(proposal["map"]["nodes"])
    proposal["map"]["nodes"] = preserve_user_nodes(old_nodes, suggested)
    proposal["research"] = research_state_for(proposal["interpretation"])
    proposal["decision_history"].append({
        "type": "interpretation_corrected",
        "before": original_interpretation["primary"],
        "after": proposal["interpretation"]["primary"],
        "recorded_at": _now(),
    })
    proposal["creation_preview"] = _creation_preview(proposal)
    await _save_revision(db, proposal, body.expected_revision, old_nodes=old_nodes)
    return public_proposal(proposal)


@dream_router.post("/{proposal_id}/map/operations")
async def edit_dream_map(
    proposal_id: str,
    body: DreamTreeOperationRequest,
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    proposal = await _load_owned_proposal(db, current_user["id"], proposal_id)
    _require(not proposal.get("applied_plan"), "An applied plan cannot be edited in place", 409)
    old_nodes = deepcopy(proposal["map"]["nodes"])
    if body.operation.get("type") == "undo":
        history = proposal["map"].get("history") or []
        _require(bool(history), "There is no recent map edit to undo", 409)
        previous = history.pop()
        proposal["map"]["nodes"] = validate_plan_tree(previous["nodes"])
        proposal["map"]["history"] = history
    else:
        proposal["map"]["nodes"] = apply_tree_operation(
            proposal["map"]["nodes"], body.operation,
        )
    proposal["decision_history"].append({
        "type": "map_edit",
        "operation": body.operation.get("type"),
        "recorded_at": _now(),
    })
    proposal["creation_preview"] = _creation_preview(proposal)
    await _save_revision(db, proposal, body.expected_revision, old_nodes=old_nodes)
    return public_proposal(proposal)


@dream_router.put("/{proposal_id}/map")
async def replace_dream_map(
    proposal_id: str,
    body: DreamTreeReplaceRequest,
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    proposal = await _load_owned_proposal(db, current_user["id"], proposal_id)
    _require(not proposal.get("applied_plan"), "An applied plan cannot be edited in place", 409)
    old_nodes = deepcopy(proposal["map"]["nodes"])
    proposal["map"]["nodes"] = validate_plan_tree(body.nodes)
    proposal["creation_preview"] = _creation_preview(proposal)
    await _save_revision(db, proposal, body.expected_revision, old_nodes=old_nodes)
    return public_proposal(proposal)


@dream_router.post("/{proposal_id}/research/manual")
async def choose_manual_research_fallback(
    proposal_id: str,
    body: DreamTreeOperationRequest,
    current_user: dict = Depends(get_current_user),
):
    """Choose the usable manual path when no research provider is configured."""
    db = get_db()
    proposal = await _load_owned_proposal(db, current_user["id"], proposal_id)
    proposal["research"] = {
        **proposal["research"],
        "state": "manual_input_required",
        "message": (
            "Add the official requirements you trust. Hymn will preserve your "
            "wording and can still build and apply a plan without a provider."
        ),
    }
    await _save_revision(db, proposal, body.expected_revision)
    return public_proposal(proposal)


def _included_nodes(proposal: dict) -> List[dict]:
    included = [
        deepcopy(node) for node in proposal["map"]["nodes"]
        if node["decision_state"] in {"accepted", "modified"}
    ]
    included_ids = {node["id"] for node in included}
    # A child cannot be applied if its parent was not accepted.
    for node in included:
        _require(
            node.get("parent_id") is None or node["parent_id"] in included_ids,
            f"Accept the parent of {node['title']} before applying",
            409,
        )
    return validate_plan_tree(included)


async def _ensure_knowledge_domain(db, user_id: str, now: str) -> str:
    existing = await db.domains.find_one(
        {"user_id": user_id, "name": "Knowledge"}, {"_id": 0},
    )
    if existing:
        return existing["id"]
    domain_id = _uuid()
    await db.domains.insert_one({
        "id": domain_id,
        "user_id": user_id,
        "name": "Knowledge",
        "is_default": True,
        "created_at": now,
    })
    return domain_id


async def _apply_plan(db, user_id: str, proposal: dict) -> dict:
    """Recoverable, per-node idempotent apply for local single-node Mongo."""
    if proposal.get("applied_plan"):
        return {**proposal["applied_plan"], "already_applied": True}
    included = _included_nodes(proposal)
    _require(bool(included), "Accept at least one plan item before applying", 409)
    now = _now()
    revision = proposal["revision"]
    source_type = proposal["source"]["type"]
    source_id = proposal["source"].get("id")
    proposal["status"] = "applying"
    await db.dream_proposals.replace_one({"id": proposal["id"]}, proposal)

    inserted: List[tuple[Any, dict]] = []
    created: Dict[str, str] = {}
    target_type = source_type
    target_id = source_id
    goal_id: Optional[str] = None
    project_id: Optional[str] = source_id if source_type == "project" else None
    journey_id: Optional[str] = source_id if source_type == "journey" else None

    async def action_once(action_id: str, collection_name: str, build_doc):
        log_filter = {
            "proposal_id": proposal["id"],
            "proposal_revision": revision,
            "action_id": action_id,
        }
        created_id = _stable_apply_uuid(proposal["id"], revision, action_id)
        reservation = await db.dream_apply_log.update_one(
            log_filter,
            {"$setOnInsert": {
                **log_filter,
                "kind": collection_name,
                "created_id": created_id,
                "user_id": user_id,
                "state": "preparing",
                "created_at": now,
            }},
            upsert=True,
        )
        reserved_here = reservation.upserted_id is not None
        doc = await build_doc()
        doc["id"] = created_id
        existing_doc = await db[collection_name].find_one(
            {"id": created_id, "user_id": user_id}, {"_id": 0, "id": 1},
        )
        if not existing_doc:
            try:
                await db[collection_name].insert_one(doc)
                inserted.append((db[collection_name], {"id": created_id, "user_id": user_id}))
            except DuplicateKeyError:
                existing_doc = await db[collection_name].find_one(
                    {"id": created_id, "user_id": user_id}, {"_id": 0, "id": 1},
                )
                _require(existing_doc is not None, "Concurrent plan apply could not be recovered", 409)
        await db.dream_apply_log.update_one(
            log_filter,
            {"$set": {"state": "committed", "committed_at": _now()}},
        )
        if reserved_here:
            inserted.append((db.dream_apply_log, log_filter))
        return created_id

    try:
        if source_type == "goal":
            goal_id = source_id
        elif source_type == "journey":
            journey = await db.knowledge_journeys.find_one(
                {"id": source_id, "user_id": user_id}, {"_id": 0},
            )
            _require(journey is not None, "Learning journey no longer exists", 409)
            goal_id = journey["goal_id"]
        elif source_type == "learning":
            domain_id = await _ensure_knowledge_domain(db, user_id, now)

            async def build_goal():
                return {
                    "id": _uuid(), "user_id": user_id,
                    "title": proposal["original_text"][:200],
                    "domain_id": domain_id,
                    "target_outcome": proposal["original_text"][:500],
                    "deadline": (_facts_by_key(proposal["interpretation"]).get("deadline") or {}).get("value") or "",
                    "status": "active", "notes": "",
                    "checkin_cadence": "",
                    "created_at": now, "updated_at": now,
                }

            goal_id = await action_once("source:goal", "goals", build_goal)

            async def build_journey():
                journey_type = {
                    "professional_qualification": "professional_qualification",
                    "learn_skill": "skill",
                    "complete_course": "course",
                    "learn_subject": "subject",
                    "read_book": "book",
                }.get(
                    proposal["interpretation"]["primary"]["journey_shape"],
                    "custom",
                )
                return {
                    "id": _uuid(), "user_id": user_id, "goal_id": goal_id,
                    "journey_type": journey_type,
                    "has_stages": any(node["kind"] == "phase" for node in included),
                    "created_at": now, "updated_at": now,
                }

            journey_id = await action_once(
                "source:journey", "knowledge_journeys", build_journey,
            )
            target_type = "journey"
            target_id = journey_id
        elif source_type == "intent":
            target_type = "dream"
            target_id = proposal["id"]

        async def build_map():
            return {
                "id": _uuid(),
                "user_id": user_id,
                "proposal_id": proposal["id"],
                "proposal_revision": revision,
                "target_type": target_type,
                "target_id": target_id,
                "original_text": proposal["original_text"],
                "interpretation": proposal["interpretation"],
                "scale": proposal["scale"],
                "nodes": included,
                "version": 1,
                "status": "active",
                "decision_history": proposal.get("decision_history") or [],
                "created_at": now,
                "updated_at": now,
            }

        map_id = await action_once("plan:map", "active_plan_maps", build_map)
        created["plan_map"] = map_id

        outcome_by_node: Dict[str, str] = {}
        task_by_node: Dict[str, str] = {}

        for node in display_plan_tree(included):
            if node["kind"] == "phase":
                async def build_phase(node=node):
                    return {
                        "id": _uuid(), "user_id": user_id, "plan_map_id": map_id,
                        "stable_node_id": node["id"], "title": node["title"],
                        "description": node.get("description") or "",
                        "rank": node["rank"], "status": "active",
                        "created_at": now, "updated_at": now,
                    }
                created_id = await action_once(
                    f"phase:{node['id']}", "plan_phases", build_phase,
                )
                created[node["id"]] = created_id
                if journey_id:
                    async def build_stage(node=node):
                        return {
                            "id": _uuid(), "user_id": user_id,
                            "journey_id": journey_id,
                            "name": node["title"],
                            "sequence": max(0, int(node["rank"]) // RANK_STEP - 1),
                            "plan_map_id": map_id,
                            "plan_node_id": node["id"],
                            "created_at": now, "updated_at": now,
                        }
                    stage_id = await action_once(
                        f"learning-stage:{node['id']}",
                        "knowledge_stages",
                        build_stage,
                    )
                    created[f"learning-stage:{node['id']}"] = stage_id

            elif node["kind"] == "milestone" and goal_id:
                async def build_outcome(node=node):
                    timing = node.get("timing") or {}
                    return {
                        "id": _uuid(), "user_id": user_id, "goal_id": goal_id,
                        "title": node["title"],
                        "target_value": node["title"], "current_value": "", "unit": "",
                        "deadline": timing.get("target_date") or "",
                        "status": "active", "notes": node.get("description") or "",
                        "outcome_type": "generic",
                        "plan_map_id": map_id, "plan_node_id": node["id"],
                        "created_at": now, "updated_at": now,
                    }
                outcome_id = await action_once(
                    f"milestone:{node['id']}", "expected_outcomes", build_outcome,
                )
                outcome_by_node[node["id"]] = outcome_id
                created[node["id"]] = outcome_id

            elif node["kind"] == "task":
                ancestors = []
                parent_id = node.get("parent_id")
                by_node = {row["id"]: row for row in included}
                while parent_id:
                    ancestors.append(parent_id)
                    parent_id = by_node[parent_id].get("parent_id")
                milestone_node = next(
                    (ancestor for ancestor in ancestors if ancestor in outcome_by_node),
                    None,
                )

                async def build_task(node=node, milestone_node=milestone_node):
                    return {
                        "id": _uuid(), "user_id": user_id,
                        "title": node["title"],
                        "due_date": (node.get("timing") or {}).get("target_date") or "",
                        "priority": "medium", "status": "todo",
                        "notes": node.get("description") or "",
                        "origin": (
                            "project" if project_id
                            else "expected_outcome" if milestone_node
                            else "standalone"
                        ),
                        "expected_outcome_id": outcome_by_node.get(milestone_node),
                        "project_id": project_id,
                        "component_id": None,
                        "assigned_to_type": "self",
                        "assigned_to_name": "", "assigned_to_phone": "",
                        "deferred_until": None, "original_due_date": None,
                        "defer_count": 0,
                        "depends_on_task_ids": [],
                        "plan_map_id": map_id, "plan_node_id": node["id"],
                        "created_at": now, "updated_at": now,
                    }
                task_id = await action_once(
                    f"task:{node['id']}", "tasks", build_task,
                )
                task_by_node[node["id"]] = task_id
                created[node["id"]] = task_id

        # Backfill task dependencies only after all task IDs exist.
        for node in included:
            if node["kind"] != "task" or node["id"] not in task_by_node:
                continue
            dependencies = [
                task_by_node[dep] for dep in node.get("dependencies") or []
                if dep in task_by_node
            ]
            if dependencies:
                await db.tasks.update_one(
                    {"id": task_by_node[node["id"]], "user_id": user_id},
                    {"$set": {"depends_on_task_ids": dependencies, "updated_at": now}},
                )

        for node in included:
            if node["kind"] != "checkin_requirement":
                continue
            parent_task_id = task_by_node.get(node.get("parent_id"))
            _require(parent_task_id is not None, "Required check-in needs an accepted task", 409)

            async def build_requirement(node=node, parent_task_id=parent_task_id):
                checkin = node["checkin"]
                return {
                    "id": _uuid(), "user_id": user_id,
                    "plan_map_id": map_id, "plan_node_id": node["id"],
                    "task_id": parent_task_id,
                    "title": node["title"],
                    "description": node.get("description") or "",
                    "schedule_type": checkin["schedule_type"],
                    "due_date": checkin.get("due_date"),
                    "cadence": checkin.get("cadence"),
                    "trigger_node_id": checkin.get("trigger_node_id"),
                    "question": checkin["question"],
                    "evidence_type": checkin.get("evidence_type") or "note",
                    "rank": node["rank"], "status": "active",
                    "created_at": now, "updated_at": now,
                }
            requirement_id = await action_once(
                f"checkin_requirement:{node['id']}",
                "required_checkin_requirements",
                build_requirement,
            )
            created[node["id"]] = requirement_id

        if source_type in {"goal", "project", "journey"}:
            collection = {
                "goal": db.goals,
                "project": db.projects,
                "journey": db.knowledge_journeys,
            }[source_type]
            result = await collection.update_one(
                {"id": source_id, "user_id": user_id},
                {"$set": {
                    "dream_plan_id": map_id,
                    "dream_plan_updated_at": now,
                    "updated_at": now,
                }},
            )
            _require(result.matched_count == 1, "Planning target no longer exists", 409)
        elif source_type == "learning" and journey_id:
            await db.knowledge_journeys.update_one(
                {"id": journey_id, "user_id": user_id},
                {"$set": {"dream_plan_id": map_id, "updated_at": now}},
            )

    except Exception as exc:
        for collection, filter_query in reversed(inserted):
            try:
                await collection.delete_one(filter_query)
            except Exception:
                pass
        proposal["status"] = "review"
        proposal["apply_error"] = f"{type(exc).__name__}: {exc}"
        proposal["updated_at"] = _now()
        await db.dream_proposals.replace_one({"id": proposal["id"]}, proposal)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(
            status_code=500,
            detail="Hymn could not apply the plan safely. Nothing partial was kept; try again.",
        ) from exc

    return_to = _source_return(
        target_type if target_type in SOURCE_TYPES else source_type,
        target_id,
        proposal["id"],
    )
    applied = {
        "plan_map_id": created["plan_map"],
        "proposal_revision": revision,
        "created_records": created,
        "accepted_node_ids": [node["id"] for node in included],
        "created_counts": {
            "plan": 1,
            "phase": sum(node["kind"] == "phase" for node in included),
            "milestone": sum(node["kind"] == "milestone" for node in included),
            "task": sum(node["kind"] == "task" for node in included),
            "checkin_requirement": sum(
                node["kind"] == "checkin_requirement" for node in included
            ),
        },
        "return_to": return_to,
        "applied_at": now,
        "already_applied": False,
    }
    proposal["status"] = "applied"
    proposal["applied_plan"] = applied
    proposal["return_to"] = return_to
    proposal["updated_at"] = now
    await db.dream_proposals.replace_one({"id": proposal["id"]}, proposal)
    return applied


@dream_router.post("/{proposal_id}/apply")
async def apply_dream(
    proposal_id: str,
    body: Optional[DreamApplyRequest] = None,
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    proposal = await _load_owned_proposal(db, current_user["id"], proposal_id)
    if body is not None:
        _require(
            proposal["revision"] == body.expected_revision,
            "This dream changed in another tab. Refresh before applying.",
            409,
        )
        submitted_ids = body.accepted_node_ids
        _require(
            len(submitted_ids) == len(set(submitted_ids)),
            "The apply request contains duplicate plan items.",
        )
        current_ids = {
            node["id"] for node in proposal["map"]["nodes"]
            if node["decision_state"] in {"accepted", "modified"}
        }
        _require(
            set(submitted_ids) == current_ids,
            "Your plan choices changed. Review the latest plan before applying.",
            409,
        )
    if proposal.get("applied_plan"):
        return {**proposal["applied_plan"], "already_applied": True}
    if proposal["source"]["type"] in {"goal", "project", "journey"}:
        live_target = await _owned_target(
            db,
            current_user["id"],
            proposal["source"]["type"],
            proposal["source"].get("id"),
        )
        _require(live_target is not None, "Planning target no longer exists", 409)
        live_context = await _owned_context(
            db,
            current_user["id"],
            proposal["source"]["type"],
            proposal["source"].get("id"),
            live_target,
            proposal["interpretation"],
            current_user.get("portfolio_reporting_currency"),
        )
        _require(
            _snapshot_hash(live_target, live_context) == proposal["context_snapshot_hash"],
            "Your recorded situation changed. Refresh the Dream analysis before applying.",
            409,
        )
    return await _apply_plan(db, current_user["id"], proposal)


@dream_router.get("/targets/{source_type}/{source_id}/active-plan")
async def get_active_plan(
    source_type: str,
    source_id: str,
    current_user: dict = Depends(get_current_user),
):
    _require(source_type in {"goal", "project", "journey"}, "Unsupported target type")
    db = get_db()
    target = await _owned_target(db, current_user["id"], source_type, source_id)
    _require(target is not None, f"{source_type.title()} not found", 404)
    plan = await db.active_plan_maps.find_one(
        {
            "user_id": current_user["id"],
            "target_type": source_type,
            "target_id": source_id,
            "status": "active",
        },
        {"_id": 0},
        sort=[("updated_at", -1)],
    )
    if not plan:
        return {"attached": False, "message": "No Dream plan is attached yet."}
    return {
        "attached": True,
        "id": plan["id"],
        "proposal_id": plan["proposal_id"],
        "version": plan["version"],
        "original_text": plan["original_text"],
        "nodes": _public_nodes(plan["nodes"]),
        "updated_at": plan["updated_at"],
    }


async def ensure_dream_indexes(database) -> None:
    await database.dream_proposals.create_index("id", unique=True)
    await database.dream_proposals.create_index([("user_id", 1), ("updated_at", -1)])
    await database.dream_proposals.create_index(
        [("user_id", 1), ("source.type", 1), ("source.id", 1)]
    )
    await database.active_plan_maps.create_index("id", unique=True)
    await database.active_plan_maps.create_index(
        [("user_id", 1), ("target_type", 1), ("target_id", 1), ("status", 1)]
    )
    await database.plan_phases.create_index("id", unique=True)
    await database.plan_phases.create_index([("user_id", 1), ("plan_map_id", 1)])
    await database.required_checkin_requirements.create_index("id", unique=True)
    await database.required_checkin_requirements.create_index(
        [("user_id", 1), ("task_id", 1), ("status", 1)]
    )
    await database.dream_apply_log.create_index(
        [("proposal_id", 1), ("proposal_revision", 1), ("action_id", 1)],
        unique=True,
    )
    await database.dream_apply_log.create_index([("user_id", 1), ("proposal_id", 1)])
