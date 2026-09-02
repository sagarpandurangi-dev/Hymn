from fastapi import FastAPI, APIRouter, Depends, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import re
import uuid
from pathlib import Path
from pydantic import BaseModel, EmailStr, Field
from typing import Any, List, Optional
from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from passlib.context import CryptContext
import httpx

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

# ---------- Config ----------
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
# JWT secret is resolved through the runtime module which enforces the
# per-mode policy (preview/production must supply JWT_SECRET; test may
# fall back to a deterministic secret that is never returned in any
# other mode). See backend/runtime.py.
from runtime import get_jwt_secret  # noqa: E402
JWT_SECRET = get_jwt_secret()
JWT_ALG = "HS256"
# Long-lived token; client-side logout controls session end.
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 30  # 30 days

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

app = FastAPI(title="Hymn API")
api_router = APIRouter(prefix="/api")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


# ---------- Models ----------
class SignUpRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    security_question: str = Field(min_length=1)
    security_answer: str = Field(min_length=1)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr
    security_answer: str
    new_password: str = Field(min_length=6)


class GoogleSessionRequest(BaseModel):
    session_token: str


class SecurityQuestionResponse(BaseModel):
    security_question: str


POST_CREATION_DECOMPOSITION_PREFERENCES = ("always_ask", "always_decompose", "always_skip")


class UserResponse(BaseModel):
    id: str
    email: EmailStr
    portfolio_setup_completed_at: Optional[str] = None
    portfolio_reporting_currency: Optional[str] = None
    post_creation_decomposition_preference: str = "always_ask"


class PostCreationDecompositionPreferenceUpdate(BaseModel):
    preference: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class DomainCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class DomainUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class DomainResponse(BaseModel):
    id: str
    name: str
    is_default: bool
    created_at: str


GOAL_STATUSES = {"active", "paused", "completed", "abandoned"}
DEFAULT_DOMAIN_NAMES = ["Knowledge", "Health", "Money", "Soul"]
# Legacy check-in cadence set retained for backward compatibility. The full
# recurrence vocabulary (adding alternate_day, fortnightly, quarterly,
# half_yearly, yearly) lives in `backend.recurrence` and is imported below.
CHECKIN_CADENCES = {"daily", "weekly", "monthly", "manual"}
from recurrence import (  # noqa: E402  (import kept next to constants for locality)
    EXTENDED_CHECKIN_CADENCES,
    RECURRENCE_CADENCES,
    END_TYPES,
    parse_iso_date as _parse_iso_date,
    next_date_str as _next_date_str,
    normalise_recurrence as _normalise_recurrence,
    should_spawn_next as _should_spawn_next,
    is_active_period as _is_active_period,
)
KNOWLEDGE_DOMAIN_NAME = "Knowledge"
COMMITMENT_TYPES = {"postponable", "exclusive"}


class GoalCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    domain_id: str
    target_outcome: str = ""
    deadline: str = ""  # YYYY-MM-DD (optional)
    status: str = "active"
    notes: str = ""
    # Extended cadence vocabulary (see backend/recurrence.py). Empty string
    # keeps a goal without a scheduled check-in.
    checkin_cadence: str = ""
    # Anchor day the cadence is computed from (YYYY-MM-DD). Optional; when
    # empty, the goal's creation date is used at read time.
    checkin_anchor_date: str = ""
    journey_type: str = ""  # optional tag surfaced in Knowledge domain UIs
    commitment_type: str = "postponable"  # postponable | exclusive


class GoalUpdate(BaseModel):
    title: Optional[str] = None
    domain_id: Optional[str] = None
    target_outcome: Optional[str] = None
    deadline: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    checkin_cadence: Optional[str] = None
    checkin_anchor_date: Optional[str] = None
    journey_type: Optional[str] = None
    commitment_type: Optional[str] = None


class GoalResponse(BaseModel):
    id: str
    title: str
    domain_id: str
    domain_name: str
    target_outcome: str
    deadline: str
    status: str
    notes: str
    checkin_cadence: str
    checkin_anchor_date: str = ""
    journey_type: str = ""
    commitment_type: str = "postponable"
    created_at: str
    updated_at: str
    expected_outcomes_total: int = 0
    expected_outcomes_completed: int = 0
    completion_pct: float = 0.0


# ---------- Expected Outcome ----------
EXPECTED_OUTCOME_STATUSES = {"active", "paused", "completed", "abandoned"}
MAX_EXPECTED_OUTCOMES_PER_GOAL = 7


# ---------- Outcome Type Registry ----------
# Metadata-driven definition of Expected Outcome types. Each type declares which
# fields appear on a Check-in linked to an Expected Outcome of that type, what
# units are supported, and how progress is calculated. Adding a new type is a
# data change here, not a schema change to Check-ins or Expected Outcomes.
OUTCOME_TYPE_REGISTRY: dict = {
    "generic": {
        "label": "Generic",
        "description": "Free-form outcome with manual progress.",
        "checkin_fields": [
            {"key": "note", "label": "Note", "type": "textarea", "required": False},
        ],
        "units": [],
        "progress": "manual",
    },
    "weight": {
        "label": "Weight",
        "description": "Body weight or any single measurable value.",
        "checkin_fields": [
            {"key": "value", "label": "Value", "type": "number", "required": True},
            {"key": "unit", "label": "Unit", "type": "select", "options": ["kg", "lb"], "required": True},
        ],
        "units": ["kg", "lb"],
        "progress": "value_vs_target",
    },
    "study": {
        "label": "Study",
        "description": "Time spent learning a topic.",
        "checkin_fields": [
            {"key": "duration_minutes", "label": "Duration (minutes)", "type": "number", "required": True},
            {"key": "topic", "label": "Topic", "type": "text", "required": False},
        ],
        "units": ["minutes", "hours"],
        "progress": "sum",
    },
    "revenue": {
        "label": "Revenue",
        "description": "Money earned or received.",
        "checkin_fields": [
            {"key": "amount", "label": "Amount", "type": "number", "required": True},
            {"key": "currency", "label": "Currency", "type": "select", "options": ["USD", "INR", "EUR", "GBP"], "required": True},
        ],
        "units": ["USD", "INR", "EUR", "GBP"],
        "progress": "sum",
    },
    "project_milestone": {
        "label": "Project Milestone",
        "description": "Status update on a milestone.",
        "checkin_fields": [
            {"key": "status_update", "label": "Status Update", "type": "textarea", "required": True},
            {"key": "blocker", "label": "Blocker", "type": "text", "required": False},
        ],
        "units": [],
        "progress": "manual",
    },
    "count": {
        "label": "Count",
        "description": "Counted occurrences (reps, sessions, tasks).",
        "checkin_fields": [
            {"key": "count", "label": "Count", "type": "number", "required": True},
        ],
        "units": [],
        "progress": "sum",
    },
}
VALID_OUTCOME_TYPES = set(OUTCOME_TYPE_REGISTRY.keys())


# ---------- Task assignment ----------
TASK_ASSIGNMENT_TYPES = {"self", "external"}
# Kept extensible on purpose: adding e.g. "hymn_user" later requires no schema change,
# only registry / validation update.


# ---------- Check-in source ----------
CHECKIN_SOURCES = {"manual", "share", "whatsapp", "email", "statement", "system"}


class ExpectedOutcomeCreate(BaseModel):
    goal_id: str
    title: str = Field(min_length=1, max_length=200)
    target_value: str = ""
    current_value: str = ""
    unit: str = ""
    deadline: str = ""
    status: str = "active"
    notes: str = ""
    outcome_type: str = "generic"


class ExpectedOutcomeUpdate(BaseModel):
    title: Optional[str] = None
    target_value: Optional[str] = None
    current_value: Optional[str] = None
    unit: Optional[str] = None
    deadline: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    outcome_type: Optional[str] = None


class ExpectedOutcomeResponse(BaseModel):
    id: str
    goal_id: str
    title: str
    target_value: str
    current_value: str
    unit: str
    deadline: str
    status: str
    notes: str
    outcome_type: str
    created_at: str
    updated_at: str


# ---------- Project ----------
PROJECT_STATUSES = {"active", "paused", "completed", "abandoned"}


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    status: str = "active"
    start_date: str = ""
    target_end_date: str = ""
    notes: str = ""
    commitment_type: str = "postponable"


class ProjectUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    start_date: Optional[str] = None
    target_end_date: Optional[str] = None
    notes: Optional[str] = None
    commitment_type: Optional[str] = None


class ProjectResponse(BaseModel):
    id: str
    title: str
    description: str
    status: str
    start_date: str
    target_end_date: str
    notes: str
    commitment_type: str = "postponable"
    created_at: str
    updated_at: str


# ---------- Task ----------
TASK_STATUSES = {"todo", "done", "deferred"}
TASK_PRIORITIES = {"low", "medium", "high"}
TASK_ORIGINS = {"expected_outcome", "project", "standalone"}


class TaskRecurrenceSpec(BaseModel):
    """Recurrence attached to a single task.

    Fields mirror `recurrence.normalise_recurrence` output. Kept on the
    task document as a nested object; when set, completing the task auto-
    spawns the next occurrence per §recurrence-engine (option A, default).
    An optional `pre_generate_count` fans out N future occurrences at once
    (option B).
    """
    # `cadence` is Optional at the Pydantic level so the endpoint can emit a
    # 400 with a friendly message (via `_normalise_recurrence`) rather than
    # Pydantic's 422 when the field is missing. `normalise_recurrence` still
    # rejects it with 400.
    cadence: Optional[str] = None
    anchor_date: Optional[str] = None
    end_type: str = "never"
    end_date: Optional[str] = None
    occurrences_remaining: Optional[int] = None
    series_id: Optional[str] = None
    pre_generate_count: int = 0


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    due_date: str = ""
    priority: str = "medium"
    status: str = "todo"
    notes: str = ""
    origin: str = "standalone"
    expected_outcome_id: Optional[str] = None
    project_id: Optional[str] = None
    component_id: Optional[str] = None  # Optional link to a Knowledge Component
    assigned_to_type: str = "self"
    assigned_to_name: str = ""
    assigned_to_phone: str = ""
    commitment_type: str = "postponable"
    recurrence: Optional[TaskRecurrenceSpec] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    due_date: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    component_id: Optional[str] = None
    assigned_to_type: Optional[str] = None
    assigned_to_name: Optional[str] = None
    assigned_to_phone: Optional[str] = None
    commitment_type: Optional[str] = None
    # Set recurrence via PUT — pass null (or DELETE the recurrence endpoint)
    # to remove it. `set_recurrence` is a discriminator on the wire so we can
    # tell "leave alone" (field omitted) from "clear" (`set_recurrence=True`
    # with `recurrence=None`).
    recurrence: Optional[TaskRecurrenceSpec] = None
    set_recurrence: Optional[bool] = None


class TaskDefer(BaseModel):
    """Payload for POST /tasks/{id}/defer.

    Task deferment cap (spec: option 1c) — both rules apply together:
        1. Max 3 defers total per task.
        2. deferred_until must be <= (original_due_date OR first-defer baseline)
           + 14 days.
    """
    deferred_until: str  # YYYY-MM-DD (must be strictly in the future)


class TaskResponse(BaseModel):
    id: str
    title: str
    due_date: str
    priority: str
    status: str
    notes: str
    origin: str
    expected_outcome_id: Optional[str] = None
    project_id: Optional[str] = None
    component_id: Optional[str] = None
    assigned_to_type: str
    assigned_to_name: str
    assigned_to_phone: str
    commitment_type: str = "postponable"
    # Deferment fields — nullable / zero on newly created tasks. `original_due_date`
    # is captured on the FIRST defer (or seeded from due_date if present) so the
    # 14-day cap can be applied consistently across subsequent defers.
    deferred_until: Optional[str] = None
    original_due_date: Optional[str] = None
    defer_count: int = 0
    # Recurrence — full spec when the task is part of a series, else None.
    # `series_id` groups sibling occurrences; `occurrence_index` is 1-based
    # for the current instance and is set at spawn-time.
    recurrence: Optional[TaskRecurrenceSpec] = None
    series_id: Optional[str] = None
    occurrence_index: int = 1
    created_at: str
    updated_at: str


# ---------- Check-in ----------
CHECKIN_TYPES = {"goal", "project", "life"}


class FollowUpTask(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    due_date: str = ""
    priority: str = "medium"
    notes: str = ""
    assigned_to_type: str = "self"
    assigned_to_name: str = ""
    assigned_to_phone: str = ""


class CheckInCreate(BaseModel):
    type: str  # goal | project | life
    title: str = Field(min_length=1, max_length=200)
    date: str  # YYYY-MM-DD
    time: str  # HH:MM
    notes: str = ""
    attachment: str = ""
    expected_outcome_id: Optional[str] = None
    project_id: Optional[str] = None
    task_id: Optional[str] = None
    component_id: Optional[str] = None  # Optional link to a Knowledge Component
    follow_up_task: Optional[FollowUpTask] = None
    source: str = "manual"
    data: dict = Field(default_factory=dict)  # type-specific dynamic fields
    # Money spent while performing the check-in. Optional. When present it
    # is counted as an *actual* expense flowing through the finance event
    # pipeline. Batch 2A: money-bearing check-ins carry an ``account_id``
    # so the resulting financial event is linked to the authoritative
    # account snapshot. If no account is supplied but the user has valid
    # accounts, the event is created in ``pending_account_assignment`` so
    # balances are never silently mutated.
    money_spent: Optional[Any] = None
    money_currency: Optional[str] = None
    account_id: Optional[str] = None
    # Batch 2A Correction 1: authoritative transaction timestamp
    # (tz-aware ISO 8601). If the client cannot supply this we derive
    # from ``date`` + ``time`` treated as UTC (documented fallback) —
    # the resulting occurred_at is used only when the check-in has an
    # account. Legacy backdated entries entered today MUST NOT be
    # silently placed after the current snapshot.
    occurred_at: Optional[str] = None
    # If true and task_id is set, the linked task is marked done atomically
    # with the check-in write. Otherwise the task is only updated
    # (`updated_at` bumped) but its status is preserved — a check-in on a
    # task is an *update*, not necessarily a completion.
    complete_task: bool = False


class CheckInUpdate(BaseModel):
    title: Optional[str] = None
    date: Optional[str] = None
    time: Optional[str] = None
    notes: Optional[str] = None
    attachment: Optional[str] = None
    component_id: Optional[str] = None
    data: Optional[dict] = None
    money_spent: Optional[Any] = None
    money_currency: Optional[str] = None
    account_id: Optional[str] = None
    occurred_at: Optional[str] = None


class CheckInResponse(BaseModel):
    id: str
    type: str
    title: str
    date: str
    time: str
    notes: str
    attachment: str
    expected_outcome_id: Optional[str] = None
    goal_id: Optional[str] = None
    project_id: Optional[str] = None
    task_id: Optional[str] = None
    component_id: Optional[str] = None
    follow_up_task_id: Optional[str] = None
    source: str
    outcome_type: Optional[str] = None
    data: dict
    money_spent: Optional[str] = None
    money_currency: Optional[str] = None
    # Batch 2A: authoritative account linkage for money-bearing check-ins.
    account_id: Optional[str] = None
    created_at: str
    updated_at: str


# ---------- Helpers ----------
def hash_password(p: str) -> str:
    return pwd_context.hash(p)


def verify_password(p: str, h: str) -> bool:
    return pwd_context.verify(p, h)


def create_access_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = {"sub": subject, "exp": expire}
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALG)


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    # Try session_token (Google) first — cheap DB lookup.
    session = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
    if session:
        expires_at = session.get("expires_at")
        if isinstance(expires_at, datetime):
            exp = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
            if exp < datetime.now(timezone.utc):
                raise credentials_exc
        user = await db.users.find_one({"id": session["user_id"]})
        if not user:
            raise credentials_exc
        return user
    # Fallback: JWT (email/password flow).
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
        user_id: str = payload.get("sub")
        if not user_id:
            raise credentials_exc
    except JWTError:
        raise credentials_exc
    user = await db.users.find_one({"id": user_id})
    if not user:
        raise credentials_exc
    return user


def user_to_response(u: dict) -> UserResponse:
    return UserResponse(
        id=u["id"],
        email=u["email"],
        portfolio_setup_completed_at=u.get("portfolio_setup_completed_at"),
        portfolio_reporting_currency=u.get("portfolio_reporting_currency"),
        post_creation_decomposition_preference=u.get(
            "post_creation_decomposition_preference", "always_ask",
        ),
    )


def domain_to_response(d: dict) -> DomainResponse:
    return DomainResponse(
        id=d["id"],
        name=d.get("name", ""),
        is_default=bool(d.get("is_default", False)),
        created_at=d.get("created_at", ""),
    )


def goal_to_response(g: dict, domain_name: str, stats: Optional[dict] = None) -> GoalResponse:
    st = stats or {"total": 0, "completed": 0}
    total = int(st.get("total", 0))
    completed = int(st.get("completed", 0))
    pct = round((completed / total) * 100, 1) if total > 0 else 0.0
    return GoalResponse(
        id=g["id"],
        title=g.get("title", ""),
        domain_id=g.get("domain_id", ""),
        domain_name=domain_name,
        target_outcome=g.get("target_outcome", "") or "",
        deadline=g.get("deadline", "") or "",
        status=g.get("status", "active"),
        notes=g.get("notes", "") or "",
        checkin_cadence=g.get("checkin_cadence", "") or "",
        checkin_anchor_date=g.get("checkin_anchor_date", "") or "",
        journey_type=g.get("journey_type", "") or "",
        commitment_type=g.get("commitment_type", "postponable") or "postponable",
        created_at=g.get("created_at", ""),
        updated_at=g.get("updated_at", ""),
        expected_outcomes_total=total,
        expected_outcomes_completed=completed,
        completion_pct=pct,
    )


async def compute_goal_stats(user_id: str, goal_id: str) -> dict:
    total = await db.expected_outcomes.count_documents({"user_id": user_id, "goal_id": goal_id})
    completed = await db.expected_outcomes.count_documents({
        "user_id": user_id, "goal_id": goal_id, "status": "completed",
    })
    return {"total": total, "completed": completed}


def expected_outcome_to_response(eo: dict) -> ExpectedOutcomeResponse:
    return ExpectedOutcomeResponse(
        id=eo["id"],
        goal_id=eo.get("goal_id", ""),
        title=eo.get("title", ""),
        target_value=eo.get("target_value", "") or "",
        current_value=eo.get("current_value", "") or "",
        unit=eo.get("unit", "") or "",
        deadline=eo.get("deadline", "") or "",
        status=eo.get("status", "active"),
        notes=eo.get("notes", "") or "",
        outcome_type=eo.get("outcome_type", "generic"),
        created_at=eo.get("created_at", ""),
        updated_at=eo.get("updated_at", ""),
    )


def project_to_response(p: dict) -> ProjectResponse:
    return ProjectResponse(
        id=p["id"],
        title=p.get("title", ""),
        description=p.get("description", "") or "",
        status=p.get("status", "active"),
        start_date=p.get("start_date", "") or "",
        target_end_date=p.get("target_end_date", "") or "",
        notes=p.get("notes", "") or "",
        commitment_type=p.get("commitment_type", "postponable") or "postponable",
        created_at=p.get("created_at", ""),
        updated_at=p.get("updated_at", ""),
    )


def task_to_response(t: dict) -> TaskResponse:
    rec_raw = t.get("recurrence")
    rec_spec: Optional[TaskRecurrenceSpec] = None
    if isinstance(rec_raw, dict) and rec_raw.get("cadence"):
        rec_spec = TaskRecurrenceSpec(
            cadence=rec_raw.get("cadence", ""),
            anchor_date=rec_raw.get("anchor_date", "") or "",
            end_type=rec_raw.get("end_type", "never") or "never",
            end_date=rec_raw.get("end_date"),
            occurrences_remaining=rec_raw.get("occurrences_remaining"),
            series_id=rec_raw.get("series_id"),
            pre_generate_count=int(rec_raw.get("pre_generate_count") or 0),
        )
    return TaskResponse(
        id=t["id"],
        title=t.get("title", ""),
        due_date=t.get("due_date", "") or "",
        priority=t.get("priority", "medium"),
        status=t.get("status", "todo"),
        notes=t.get("notes", "") or "",
        origin=t.get("origin", "standalone"),
        expected_outcome_id=t.get("expected_outcome_id"),
        project_id=t.get("project_id"),
        component_id=t.get("component_id"),
        assigned_to_type=t.get("assigned_to_type", "self"),
        assigned_to_name=t.get("assigned_to_name", "") or "",
        assigned_to_phone=t.get("assigned_to_phone", "") or "",
        commitment_type=t.get("commitment_type", "postponable") or "postponable",
        deferred_until=t.get("deferred_until"),
        original_due_date=t.get("original_due_date"),
        defer_count=int(t.get("defer_count") or 0),
        recurrence=rec_spec,
        series_id=t.get("series_id"),
        occurrence_index=int(t.get("occurrence_index") or 1),
        created_at=t.get("created_at", ""),
        updated_at=t.get("updated_at", ""),
    )


def _money_str(v) -> Optional[str]:
    """Cast a stored money value (Decimal128 / str / float) to a decimal string."""
    if v is None:
        return None
    try:
        from bson.decimal128 import Decimal128 as _D128  # local import — bson is available server-wide
        if isinstance(v, _D128):
            return str(v.to_decimal())
    except Exception:  # noqa: BLE001
        pass
    return str(v)


def checkin_to_response(c: dict) -> CheckInResponse:
    return CheckInResponse(
        id=c["id"],
        type=c.get("type", "life"),
        title=c.get("title", ""),
        date=c.get("date", ""),
        time=c.get("time", ""),
        notes=c.get("notes", "") or "",
        attachment=c.get("attachment", "") or "",
        expected_outcome_id=c.get("expected_outcome_id"),
        goal_id=c.get("goal_id"),
        project_id=c.get("project_id"),
        task_id=c.get("task_id"),
        component_id=c.get("component_id"),
        follow_up_task_id=c.get("follow_up_task_id"),
        source=c.get("source", "manual"),
        outcome_type=c.get("outcome_type"),
        data=c.get("data") or {},
        money_spent=_money_str(c.get("money_spent")),
        money_currency=c.get("money_currency"),
        account_id=c.get("account_id"),
        created_at=c.get("created_at", ""),
        updated_at=c.get("updated_at", ""),
    )


async def ensure_default_domains(user_id: str) -> None:
    """Idempotently ensure every default domain exists for the user.

    This is safe to call on every login / auth check. Adds only missing defaults
    so existing users get newly-added default domains (like "Knowledge") without
    a manual migration, and users who have already customised their domains
    keep their edits.
    """
    existing_names = {
        d.get("name")
        for d in await db.domains.find(
            {"user_id": user_id}, {"_id": 0, "name": 1}
        ).to_list(length=1000)
    }
    missing = [n for n in DEFAULT_DOMAIN_NAMES if n not in existing_names]
    if not missing:
        return
    now = datetime.now(timezone.utc).isoformat()
    docs = [
        {"id": str(uuid.uuid4()), "user_id": user_id, "name": name, "is_default": True, "created_at": now}
        for name in missing
    ]
    await db.domains.insert_many(docs)


# ---------- Auth Routes ----------
@api_router.get("/")
async def root():
    return {"message": "Hymn API"}


@api_router.post("/auth/signup", response_model=TokenResponse, status_code=201)
async def signup(body: SignUpRequest):
    email = body.email.lower().strip()
    existing = await db.users.find_one({"email": email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    user_doc = {
        "id": user_id,
        "email": email,
        "hashed_password": hash_password(body.password),
        "security_question": body.security_question.strip(),
        "hashed_security_answer": hash_password(body.security_answer.strip().lower()),
        "created_at": now,
        "updated_at": now,
    }
    await db.users.insert_one(user_doc)
    token = create_access_token(user_id)
    return TokenResponse(
        access_token=token,
        user=UserResponse(id=user_id, email=email),
    )


@api_router.post("/auth/login", response_model=TokenResponse)
async def login(body: LoginRequest):
    email = body.email.lower().strip()
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(body.password, user["hashed_password"]):
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    token = create_access_token(user["id"])
    return TokenResponse(access_token=token, user=user_to_response(user))


@api_router.post("/auth/security-question", response_model=SecurityQuestionResponse)
async def get_security_question(payload: dict):
    email = (payload.get("email") or "").lower().strip()
    if not email:
        raise HTTPException(status_code=400, detail="Email required")
    user = await db.users.find_one({"email": email})
    if not user:
        # Do not reveal whether email exists; return a generic prompt.
        return SecurityQuestionResponse(security_question="Answer your security question to continue")
    return SecurityQuestionResponse(security_question=user.get("security_question", ""))


@api_router.post("/auth/forgot-password")
async def forgot_password(body: ForgotPasswordRequest):
    email = body.email.lower().strip()
    user = await db.users.find_one({"email": email})
    if not user:
        raise HTTPException(status_code=400, detail="Invalid email or security answer")
    if not verify_password(body.security_answer.strip().lower(), user["hashed_security_answer"]):
        raise HTTPException(status_code=400, detail="Invalid email or security answer")
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {
            "hashed_password": hash_password(body.new_password),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
    )
    return {"detail": "Password updated"}


@api_router.get("/auth/me", response_model=UserResponse)
async def me(current_user: dict = Depends(get_current_user)):
    return user_to_response(current_user)


@api_router.patch("/auth/preferences/post-creation-decomposition", response_model=UserResponse)
async def update_post_creation_decomposition_preference(
    body: PostCreationDecompositionPreferenceUpdate,
    current_user: dict = Depends(get_current_user),
):
    if body.preference not in POST_CREATION_DECOMPOSITION_PREFERENCES:
        raise HTTPException(
            status_code=400,
            detail=f"preference must be one of {list(POST_CREATION_DECOMPOSITION_PREFERENCES)}",
        )
    now = datetime.now(timezone.utc).isoformat()
    await db.users.update_one(
        {"id": current_user["id"]},
        {"$set": {
            "post_creation_decomposition_preference": body.preference,
            "updated_at": now,
        }},
    )
    updated = await db.users.find_one({"id": current_user["id"]}, {"_id": 0})
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    return user_to_response(updated)


@api_router.post("/auth/logout")
async def logout(current_user: dict = Depends(get_current_user), token: str = Depends(oauth2_scheme)):
    # Stateless JWT for email/password users. For Google users, delete their session row.
    await db.user_sessions.delete_one({"session_token": token})
    return {"detail": "Logged out"}


@api_router.post("/auth/google-session", response_model=TokenResponse)
async def google_session(body: GoogleSessionRequest):
    """Verify session_token with Emergent auth service, upsert user, persist session."""
    session_token = body.session_token.strip()
    if not session_token:
        raise HTTPException(status_code=400, detail="Missing session token")
    async with httpx.AsyncClient(timeout=10.0) as http_client:
        try:
            resp = await http_client.get(
                "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data",
                headers={"X-Session-ID": session_token},
            )
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Auth service unreachable: {e}")
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid Google session")
    data = resp.json()
    email = (data.get("email") or "").lower().strip()
    if not email:
        raise HTTPException(status_code=401, detail="Google session missing email")
    verified_token = data.get("session_token") or session_token

    now = datetime.now(timezone.utc)
    existing = await db.users.find_one({"email": email})
    if existing:
        user_id = existing["id"]
        await db.users.update_one(
            {"id": user_id},
            {"$set": {"updated_at": now.isoformat(), "google_name": data.get("name"), "google_picture": data.get("picture")}},
        )
    else:
        user_id = str(uuid.uuid4())
        await db.users.insert_one({
            "id": user_id,
            "email": email,
            "hashed_password": None,
            "security_question": None,
            "hashed_security_answer": None,
            "auth_provider": "google",
            "google_name": data.get("name"),
            "google_picture": data.get("picture"),
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        })

    await db.user_sessions.update_one(
        {"session_token": verified_token},
        {"$set": {
            "session_token": verified_token,
            "user_id": user_id,
            "expires_at": now + timedelta(days=7),
            "created_at": now,
        }},
        upsert=True,
    )
    return TokenResponse(access_token=verified_token, user=UserResponse(id=user_id, email=email))


# ---------- Domain Routes ----------
@api_router.get("/domains", response_model=List[DomainResponse])
async def list_domains(current_user: dict = Depends(get_current_user)):
    await ensure_default_domains(current_user["id"])
    cursor = db.domains.find({"user_id": current_user["id"]}, {"_id": 0})
    docs = await cursor.to_list(length=1000)
    docs.sort(key=lambda d: (not d.get("is_default", False), d.get("name", "").lower()))
    return [domain_to_response(d) for d in docs]


@api_router.post("/domains", response_model=DomainResponse, status_code=201)
async def create_domain(body: DomainCreate, current_user: dict = Depends(get_current_user)):
    await ensure_default_domains(current_user["id"])
    name = body.name.strip()
    existing = await db.domains.find_one({"user_id": current_user["id"], "name": {"$regex": f"^{name}$", "$options": "i"}})
    if existing:
        raise HTTPException(status_code=400, detail="A domain with this name already exists")
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": current_user["id"],
        "name": name,
        "is_default": False,
        "created_at": now,
    }
    await db.domains.insert_one(doc)
    doc.pop("_id", None)
    return domain_to_response(doc)


@api_router.put("/domains/{domain_id}", response_model=DomainResponse)
async def update_domain(domain_id: str, body: DomainUpdate, current_user: dict = Depends(get_current_user)):
    doc = await db.domains.find_one({"id": domain_id, "user_id": current_user["id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Domain not found")
    name = body.name.strip()
    dup = await db.domains.find_one({
        "user_id": current_user["id"],
        "name": {"$regex": f"^{name}$", "$options": "i"},
        "id": {"$ne": domain_id},
    })
    if dup:
        raise HTTPException(status_code=400, detail="A domain with this name already exists")
    await db.domains.update_one(
        {"id": domain_id, "user_id": current_user["id"]},
        {"$set": {"name": name}},
    )
    updated = await db.domains.find_one({"id": domain_id}, {"_id": 0})
    return domain_to_response(updated)


@api_router.delete("/domains/{domain_id}", status_code=200)
async def delete_domain(domain_id: str, current_user: dict = Depends(get_current_user)):
    doc = await db.domains.find_one({"id": domain_id, "user_id": current_user["id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Domain not found")
    linked = await db.goals.count_documents({"user_id": current_user["id"], "domain_id": domain_id})
    if linked > 0:
        raise HTTPException(status_code=400, detail=f"Cannot delete: {linked} goal(s) linked to this domain")
    await db.domains.delete_one({"id": domain_id, "user_id": current_user["id"]})
    return {"detail": "Domain deleted"}


# ---------- Goal Routes ----------
async def _resolve_domain_name(user_id: str, domain_id: str) -> str:
    d = await db.domains.find_one({"id": domain_id, "user_id": user_id}, {"_id": 0, "name": 1})
    return d.get("name", "") if d else ""


@api_router.get("/goals", response_model=List[GoalResponse])
async def list_goals(current_user: dict = Depends(get_current_user)):
    cursor = db.goals.find({"user_id": current_user["id"]}, {"_id": 0})
    goals = await cursor.to_list(length=1000)
    dcursor = db.domains.find({"user_id": current_user["id"]}, {"_id": 0, "id": 1, "name": 1})
    domain_map = {d["id"]: d["name"] for d in await dcursor.to_list(length=1000)}
    goals.sort(key=lambda g: g.get("created_at", ""), reverse=True)
    result = []
    for g in goals:
        stats = await compute_goal_stats(current_user["id"], g["id"])
        result.append(goal_to_response(g, domain_map.get(g.get("domain_id", ""), ""), stats))
    return result


@api_router.post("/goals", response_model=GoalResponse, status_code=201)
async def create_goal(body: GoalCreate, current_user: dict = Depends(get_current_user)):
    if body.commitment_type not in COMMITMENT_TYPES:
        raise HTTPException(status_code=400, detail=f"commitment_type must be one of {sorted(COMMITMENT_TYPES)}")
    if body.status not in GOAL_STATUSES:
        raise HTTPException(status_code=400, detail=f"Status must be one of {sorted(GOAL_STATUSES)}")
    if body.checkin_cadence and body.checkin_cadence not in EXTENDED_CHECKIN_CADENCES:
        raise HTTPException(status_code=400, detail=f"checkin_cadence must be one of {sorted(EXTENDED_CHECKIN_CADENCES)} or empty")
    # Optional anchor date — validated when a non-manual cadence is set. When
    # the caller does not supply one we fall back to the goal's creation date
    # at read time (see list_required_checkins). This keeps the field purely
    # additive and back-compat with existing rows.
    if body.checkin_anchor_date:
        try:
            _parse_iso_date(body.checkin_anchor_date)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"checkin_anchor_date must be YYYY-MM-DD: {exc}") from exc
    domain = await db.domains.find_one({"id": body.domain_id, "user_id": current_user["id"]})
    if not domain:
        raise HTTPException(status_code=400, detail="Invalid domain")
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": current_user["id"],
        "title": body.title.strip(),
        "domain_id": body.domain_id,
        "target_outcome": (body.target_outcome or "").strip(),
        "deadline": (body.deadline or "").strip(),
        "status": body.status,
        "notes": (body.notes or "").strip(),
        "checkin_cadence": (body.checkin_cadence or "").strip(),
        "checkin_anchor_date": (body.checkin_anchor_date or "").strip(),
        "journey_type": (body.journey_type or "").strip(),
        "commitment_type": body.commitment_type if body.commitment_type in COMMITMENT_TYPES else "postponable",
        "created_at": now,
        "updated_at": now,
    }
    await db.goals.insert_one(doc)
    doc.pop("_id", None)
    return goal_to_response(doc, domain.get("name", ""), {"total": 0, "completed": 0})


@api_router.get("/goals/{goal_id}", response_model=GoalResponse)
async def get_goal(goal_id: str, current_user: dict = Depends(get_current_user)):
    g = await db.goals.find_one({"id": goal_id, "user_id": current_user["id"]}, {"_id": 0})
    if not g:
        raise HTTPException(status_code=404, detail="Goal not found")
    name = await _resolve_domain_name(current_user["id"], g.get("domain_id", ""))
    stats = await compute_goal_stats(current_user["id"], goal_id)
    return goal_to_response(g, name, stats)


@api_router.put("/goals/{goal_id}", response_model=GoalResponse)
async def update_goal(goal_id: str, body: GoalUpdate, current_user: dict = Depends(get_current_user)):
    g = await db.goals.find_one({"id": goal_id, "user_id": current_user["id"]})
    if not g:
        raise HTTPException(status_code=404, detail="Goal not found")
    updates = {k: v for k, v in body.dict(exclude_unset=True).items() if v is not None}
    if "status" in updates and updates["status"] not in GOAL_STATUSES:
        raise HTTPException(status_code=400, detail=f"Status must be one of {sorted(GOAL_STATUSES)}")
    if "checkin_cadence" in updates and updates["checkin_cadence"] and updates["checkin_cadence"] not in EXTENDED_CHECKIN_CADENCES:
        raise HTTPException(status_code=400, detail=f"checkin_cadence must be one of {sorted(EXTENDED_CHECKIN_CADENCES)} or empty")
    if "checkin_anchor_date" in updates and updates["checkin_anchor_date"]:
        try:
            _parse_iso_date(updates["checkin_anchor_date"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"checkin_anchor_date must be YYYY-MM-DD: {exc}") from exc
    if "commitment_type" in updates and updates["commitment_type"] not in COMMITMENT_TYPES:
        raise HTTPException(status_code=400, detail=f"commitment_type must be one of {sorted(COMMITMENT_TYPES)}")
    if "domain_id" in updates:
        d = await db.domains.find_one({"id": updates["domain_id"], "user_id": current_user["id"]})
        if not d:
            raise HTTPException(status_code=400, detail="Invalid domain")
    for k in ("title", "target_outcome", "deadline", "notes", "checkin_cadence", "checkin_anchor_date", "journey_type"):
        if k in updates and isinstance(updates[k], str):
            updates[k] = updates[k].strip()
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.goals.update_one({"id": goal_id, "user_id": current_user["id"]}, {"$set": updates})
    updated = await db.goals.find_one({"id": goal_id}, {"_id": 0})
    name = await _resolve_domain_name(current_user["id"], updated.get("domain_id", ""))
    stats = await compute_goal_stats(current_user["id"], goal_id)
    return goal_to_response(updated, name, stats)


@api_router.delete("/goals/{goal_id}", status_code=200)
async def delete_goal(goal_id: str, current_user: dict = Depends(get_current_user)):
    result = await db.goals.delete_one({"id": goal_id, "user_id": current_user["id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Goal not found")
    # Cascade cleanup — expected outcomes belong to the goal.
    await db.expected_outcomes.delete_many({"user_id": current_user["id"], "goal_id": goal_id})
    return {"detail": "Goal deleted"}


# ---------- Expected Outcome Routes ----------
@api_router.get("/goals/{goal_id}/expected-outcomes", response_model=List[ExpectedOutcomeResponse])
async def list_expected_outcomes(goal_id: str, current_user: dict = Depends(get_current_user)):
    g = await db.goals.find_one({"id": goal_id, "user_id": current_user["id"]})
    if not g:
        raise HTTPException(status_code=404, detail="Goal not found")
    cursor = db.expected_outcomes.find({"user_id": current_user["id"], "goal_id": goal_id}, {"_id": 0})
    docs = await cursor.to_list(length=100)
    docs.sort(key=lambda x: x.get("created_at", ""))
    return [expected_outcome_to_response(d) for d in docs]


@api_router.post("/expected-outcomes", response_model=ExpectedOutcomeResponse, status_code=201)
async def create_expected_outcome(body: ExpectedOutcomeCreate, current_user: dict = Depends(get_current_user)):
    if body.status not in EXPECTED_OUTCOME_STATUSES:
        raise HTTPException(status_code=400, detail=f"Status must be one of {sorted(EXPECTED_OUTCOME_STATUSES)}")
    if body.outcome_type not in VALID_OUTCOME_TYPES:
        raise HTTPException(status_code=400, detail=f"Outcome type must be one of {sorted(VALID_OUTCOME_TYPES)}")
    g = await db.goals.find_one({"id": body.goal_id, "user_id": current_user["id"]})
    if not g:
        raise HTTPException(status_code=400, detail="Invalid goal")
    existing = await db.expected_outcomes.count_documents({"user_id": current_user["id"], "goal_id": body.goal_id})
    if existing >= MAX_EXPECTED_OUTCOMES_PER_GOAL:
        raise HTTPException(status_code=400, detail=f"A goal can have at most {MAX_EXPECTED_OUTCOMES_PER_GOAL} expected outcomes")
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": current_user["id"],
        "goal_id": body.goal_id,
        "title": body.title.strip(),
        "target_value": (body.target_value or "").strip(),
        "current_value": (body.current_value or "").strip(),
        "unit": (body.unit or "").strip(),
        "deadline": (body.deadline or "").strip(),
        "status": body.status,
        "notes": (body.notes or "").strip(),
        "outcome_type": body.outcome_type,
        "created_at": now,
        "updated_at": now,
    }
    await db.expected_outcomes.insert_one(doc)
    doc.pop("_id", None)
    return expected_outcome_to_response(doc)


@api_router.get("/expected-outcomes/{eo_id}", response_model=ExpectedOutcomeResponse)
async def get_expected_outcome(eo_id: str, current_user: dict = Depends(get_current_user)):
    eo = await db.expected_outcomes.find_one({"id": eo_id, "user_id": current_user["id"]}, {"_id": 0})
    if not eo:
        raise HTTPException(status_code=404, detail="Expected outcome not found")
    return expected_outcome_to_response(eo)


@api_router.put("/expected-outcomes/{eo_id}", response_model=ExpectedOutcomeResponse)
async def update_expected_outcome(eo_id: str, body: ExpectedOutcomeUpdate, current_user: dict = Depends(get_current_user)):
    eo = await db.expected_outcomes.find_one({"id": eo_id, "user_id": current_user["id"]})
    if not eo:
        raise HTTPException(status_code=404, detail="Expected outcome not found")
    updates = {k: v for k, v in body.dict(exclude_unset=True).items() if v is not None}
    if "status" in updates and updates["status"] not in EXPECTED_OUTCOME_STATUSES:
        raise HTTPException(status_code=400, detail=f"Status must be one of {sorted(EXPECTED_OUTCOME_STATUSES)}")
    if "outcome_type" in updates and updates["outcome_type"] not in VALID_OUTCOME_TYPES:
        raise HTTPException(status_code=400, detail=f"Outcome type must be one of {sorted(VALID_OUTCOME_TYPES)}")
    for k in ("title", "target_value", "current_value", "unit", "deadline", "notes"):
        if k in updates and isinstance(updates[k], str):
            updates[k] = updates[k].strip()
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.expected_outcomes.update_one({"id": eo_id, "user_id": current_user["id"]}, {"$set": updates})
    updated = await db.expected_outcomes.find_one({"id": eo_id}, {"_id": 0})
    return expected_outcome_to_response(updated)


@api_router.delete("/expected-outcomes/{eo_id}", status_code=200)
async def delete_expected_outcome(eo_id: str, current_user: dict = Depends(get_current_user)):
    result = await db.expected_outcomes.delete_one({"id": eo_id, "user_id": current_user["id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Expected outcome not found")
    return {"detail": "Expected outcome deleted"}


# ---------- Project Routes ----------
@api_router.get("/projects", response_model=List[ProjectResponse])
async def list_projects(current_user: dict = Depends(get_current_user)):
    cursor = db.projects.find({"user_id": current_user["id"]}, {"_id": 0})
    docs = await cursor.to_list(length=1000)
    docs.sort(key=lambda p: p.get("created_at", ""), reverse=True)
    return [project_to_response(d) for d in docs]


@api_router.post("/projects", response_model=ProjectResponse, status_code=201)
async def create_project(body: ProjectCreate, current_user: dict = Depends(get_current_user)):
    if body.status not in PROJECT_STATUSES:
        raise HTTPException(status_code=400, detail=f"Status must be one of {sorted(PROJECT_STATUSES)}")
    if body.commitment_type not in COMMITMENT_TYPES:
        raise HTTPException(status_code=400, detail=f"commitment_type must be one of {sorted(COMMITMENT_TYPES)}")
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": current_user["id"],
        "title": body.title.strip(),
        "description": (body.description or "").strip(),
        "status": body.status,
        "start_date": (body.start_date or "").strip(),
        "target_end_date": (body.target_end_date or "").strip(),
        "notes": (body.notes or "").strip(),
        "commitment_type": body.commitment_type if body.commitment_type in COMMITMENT_TYPES else "postponable",
        "created_at": now,
        "updated_at": now,
    }
    await db.projects.insert_one(doc)
    doc.pop("_id", None)
    return project_to_response(doc)


@api_router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str, current_user: dict = Depends(get_current_user)):
    doc = await db.projects.find_one({"id": project_id, "user_id": current_user["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Project not found")
    return project_to_response(doc)


@api_router.put("/projects/{project_id}", response_model=ProjectResponse)
async def update_project(project_id: str, body: ProjectUpdate, current_user: dict = Depends(get_current_user)):
    p = await db.projects.find_one({"id": project_id, "user_id": current_user["id"]})
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    updates = {k: v for k, v in body.dict(exclude_unset=True).items() if v is not None}
    if "status" in updates and updates["status"] not in PROJECT_STATUSES:
        raise HTTPException(status_code=400, detail=f"Status must be one of {sorted(PROJECT_STATUSES)}")
    if "commitment_type" in updates and updates["commitment_type"] not in COMMITMENT_TYPES:
        raise HTTPException(status_code=400, detail=f"commitment_type must be one of {sorted(COMMITMENT_TYPES)}")
    for k in ("title", "description", "start_date", "target_end_date", "notes"):
        if k in updates and isinstance(updates[k], str):
            updates[k] = updates[k].strip()
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.projects.update_one({"id": project_id, "user_id": current_user["id"]}, {"$set": updates})
    updated = await db.projects.find_one({"id": project_id}, {"_id": 0})
    return project_to_response(updated)


@api_router.delete("/projects/{project_id}", status_code=200)
async def delete_project(project_id: str, current_user: dict = Depends(get_current_user)):
    result = await db.projects.delete_one({"id": project_id, "user_id": current_user["id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"detail": "Project deleted"}


# ---------- Task Routes ----------
async def _validate_task_origin(user_id: str, origin: str, eo_id: Optional[str], project_id: Optional[str]):
    if origin not in TASK_ORIGINS:
        raise HTTPException(status_code=400, detail=f"Origin must be one of {sorted(TASK_ORIGINS)}")
    if origin == "expected_outcome":
        if not eo_id:
            raise HTTPException(status_code=400, detail="expected_outcome_id required")
        eo = await db.expected_outcomes.find_one({"id": eo_id, "user_id": user_id})
        if not eo:
            raise HTTPException(status_code=400, detail="Invalid expected outcome")
    elif origin == "project":
        if not project_id:
            raise HTTPException(status_code=400, detail="project_id required")
        p = await db.projects.find_one({"id": project_id, "user_id": user_id})
        if not p:
            raise HTTPException(status_code=400, detail="Invalid project")


@api_router.get("/tasks", response_model=List[TaskResponse])
async def list_tasks(
    current_user: dict = Depends(get_current_user),
    goal_id: Optional[str] = None,
    component_id: Optional[str] = None,
    project_id: Optional[str] = None,
    include_completed: bool = True,
):
    q: dict = {"user_id": current_user["id"]}
    if not include_completed:
        # "done" and "cancelled" are considered completed for list purposes —
        # neither should surface on the tasks homepage after the user has
        # already closed them out.
        q["status"] = {"$nin": ["done", "cancelled"]}
    if component_id:
        q["component_id"] = component_id
    if project_id:
        q["project_id"] = project_id
    if goal_id:
        # Tasks whose Expected Outcome belongs to this goal.
        eo_ids = [
            eo["id"]
            for eo in await db.expected_outcomes.find(
                {"user_id": current_user["id"], "goal_id": goal_id}, {"_id": 0, "id": 1}
            ).to_list(length=1000)
        ]
        if not eo_ids and not component_id:
            return []
        # If both goal_id and component_id are provided, match either.
        if component_id:
            q.pop("expected_outcome_id", None)
            q["$or"] = [
                {"expected_outcome_id": {"$in": eo_ids}} if eo_ids else {"_impossible": True},
                {"component_id": component_id},
            ]
            q.pop("component_id", None)
        else:
            q["expected_outcome_id"] = {"$in": eo_ids}
    cursor = db.tasks.find(q, {"_id": 0})
    docs = await cursor.to_list(length=1000)
    docs.sort(key=lambda t: t.get("created_at", ""), reverse=True)
    return [task_to_response(d) for d in docs]


@api_router.post("/tasks", response_model=TaskResponse, status_code=201)
async def create_task(body: TaskCreate, current_user: dict = Depends(get_current_user)):
    if body.status not in TASK_STATUSES:
        raise HTTPException(status_code=400, detail=f"Status must be one of {sorted(TASK_STATUSES)}")
    if body.priority not in TASK_PRIORITIES:
        raise HTTPException(status_code=400, detail=f"Priority must be one of {sorted(TASK_PRIORITIES)}")
    if body.assigned_to_type not in TASK_ASSIGNMENT_TYPES:
        raise HTTPException(status_code=400, detail=f"assigned_to_type must be one of {sorted(TASK_ASSIGNMENT_TYPES)}")
    if body.assigned_to_type == "external" and not (body.assigned_to_name or body.assigned_to_phone):
        raise HTTPException(status_code=400, detail="External assignment requires assigned_to_name or assigned_to_phone")
    if body.commitment_type not in COMMITMENT_TYPES:
        raise HTTPException(status_code=400, detail=f"commitment_type must be one of {sorted(COMMITMENT_TYPES)}")
    await _validate_task_origin(current_user["id"], body.origin, body.expected_outcome_id, body.project_id)
    # component_id is deprecated — always null after the Decomposition Engine reform.
    validated_component_id: Optional[str] = None
    now = datetime.now(timezone.utc).isoformat()
    task_id = str(uuid.uuid4())

    # Recurrence — validate up-front; when set we assign this task the head
    # of a new series (series_id + occurrence_index=1). Pre-generation of
    # additional occurrences happens after insert.
    rec_dict: Optional[dict] = None
    series_id: Optional[str] = None
    if body.recurrence is not None:
        try:
            rec_dict = _normalise_recurrence(
                body.recurrence.dict(),
                fallback_anchor=(body.due_date or "").strip() or None,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"recurrence: {exc}") from exc
        series_id = rec_dict.get("series_id") or str(uuid.uuid4())
        rec_dict["series_id"] = series_id

    doc = {
        "id": task_id,
        "user_id": current_user["id"],
        "title": body.title.strip(),
        "due_date": (body.due_date or "").strip(),
        "priority": body.priority,
        "status": body.status,
        "notes": (body.notes or "").strip(),
        "origin": body.origin,
        "expected_outcome_id": body.expected_outcome_id if body.origin == "expected_outcome" else None,
        "project_id": body.project_id if body.origin == "project" else None,
        "component_id": validated_component_id,
        "assigned_to_type": body.assigned_to_type,
        "assigned_to_name": (body.assigned_to_name or "").strip() if body.assigned_to_type == "external" else "",
        "assigned_to_phone": (body.assigned_to_phone or "").strip() if body.assigned_to_type == "external" else "",
        "commitment_type": body.commitment_type if body.commitment_type in COMMITMENT_TYPES else "postponable",
        # Deferment state. `original_due_date` is seeded from the initial
        # `due_date` (if present) so subsequent defers compare against the
        # user's original intent, not the last-deferred date. `defer_count`
        # is the total number of defers performed against this task.
        "deferred_until": None,
        "original_due_date": (body.due_date or "").strip() or None,
        "defer_count": 0,
        "recurrence": rec_dict,
        "series_id": series_id,
        "occurrence_index": 1 if rec_dict else 1,
        "created_at": now,
        "updated_at": now,
    }
    await db.tasks.insert_one(doc)

    # Pre-generate upcoming occurrences when the user requested option B
    # (up to 12 to bound the write burst). Each future task is a full clone
    # with its own id, due_date walked forward, and occurrence_index bumped.
    if rec_dict and int(rec_dict.get("pre_generate_count") or 0) > 0:
        await _pre_generate_series(
            base_task=doc,
            count=int(rec_dict["pre_generate_count"]),
        )

    doc.pop("_id", None)
    return task_to_response(doc)


# ---------------------------------------------------------------------------
# Recurrence helpers — series expansion & auto-spawn on completion.
# ---------------------------------------------------------------------------
_RECURRENCE_MAX_SPAWN = 12


async def _pre_generate_series(*, base_task: dict, count: int) -> list:
    """Materialise up to `count` future occurrences of `base_task`.

    The base task remains occurrence 1. Each spawned task inherits every
    scalar field, gets a new `id`, `due_date` advanced by one cadence step
    per iteration, `occurrence_index` incremented, and its own `recurrence`
    copy (with pre_generate_count zeroed so it doesn't recursively fan out).

    Returns the list of inserted task dicts. Silently stops early when the
    series reaches its end condition.
    """
    if count <= 0 or not base_task.get("recurrence"):
        return []
    count = min(count, _RECURRENCE_MAX_SPAWN)
    now = datetime.now(timezone.utc).isoformat()
    rec = dict(base_task["recurrence"])
    rec["pre_generate_count"] = 0  # child occurrences don't re-fan
    remaining = rec.get("occurrences_remaining")
    cursor_due = base_task.get("due_date") or rec.get("anchor_date") or ""
    spawned: list = []
    for i in range(count):
        # End-condition checks BEFORE spawning the next.
        if rec.get("end_type") == "count":
            try:
                if int(remaining or 0) <= 1:
                    break
            except (TypeError, ValueError):
                break
        next_due = _next_date_str(cursor_due, rec)
        if not next_due:
            break
        # Idempotency guard: if a sibling in this series already has the
        # target due_date, do not create a duplicate. This lets callers
        # invoke `/recurrence/generate` repeatedly without piling up.
        if base_task.get("series_id"):
            dupe = await db.tasks.find_one(
                {
                    "user_id": base_task["user_id"],
                    "series_id": base_task["series_id"],
                    "due_date": next_due,
                },
                {"_id": 0, "id": 1},
            )
            if dupe:
                cursor_due = next_due
                continue
        if remaining is not None:
            try:
                remaining = int(remaining) - 1
            except (TypeError, ValueError):
                remaining = None
        child_rec = dict(rec)
        child_rec["occurrences_remaining"] = remaining
        new_task = {
            **{k: v for k, v in base_task.items() if k not in {"_id"}},
            "id": str(uuid.uuid4()),
            "due_date": next_due,
            "status": "todo",
            "original_due_date": next_due,
            "defer_count": 0,
            "deferred_until": None,
            "recurrence": child_rec,
            "series_id": base_task.get("series_id"),
            "occurrence_index": int(base_task.get("occurrence_index") or 1) + i + 1,
            "created_at": now,
            "updated_at": now,
        }
        await db.tasks.insert_one(new_task)
        spawned.append(new_task)
        cursor_due = next_due
    return spawned


async def _maybe_spawn_next_occurrence(task_doc: dict) -> Optional[dict]:
    """When a recurring task transitions to done, spawn the next occurrence.

    Returns the spawned task dict, or None when no spawn happened (either
    the task has no recurrence, the end condition has been reached, or the
    next occurrence has already been pre-generated in the same series).
    """
    rec = task_doc.get("recurrence") or {}
    if not rec.get("cadence"):
        return None
    if not _should_spawn_next(rec):
        return None
    next_due = _next_date_str(task_doc.get("due_date") or "", rec)
    if not next_due:
        return None
    # If a sibling occurrence already exists in this series with the same
    # due_date, do not spawn again — the pre-generation path has us covered.
    if task_doc.get("series_id"):
        existing = await db.tasks.find_one(
            {
                "user_id": task_doc["user_id"],
                "series_id": task_doc["series_id"],
                "due_date": next_due,
            },
            {"_id": 0, "id": 1},
        )
        if existing:
            return None
    child_rec = dict(rec)
    child_rec["pre_generate_count"] = 0
    if rec.get("end_type") == "count":
        try:
            child_rec["occurrences_remaining"] = int(rec.get("occurrences_remaining") or 0) - 1
        except (TypeError, ValueError):
            child_rec["occurrences_remaining"] = None
    now = datetime.now(timezone.utc).isoformat()
    new_task = {
        **{k: v for k, v in task_doc.items() if k not in {"_id"}},
        "id": str(uuid.uuid4()),
        "due_date": next_due,
        "status": "todo",
        "original_due_date": next_due,
        "defer_count": 0,
        "deferred_until": None,
        "recurrence": child_rec,
        "series_id": task_doc.get("series_id"),
        "occurrence_index": int(task_doc.get("occurrence_index") or 1) + 1,
        "created_at": now,
        "updated_at": now,
    }
    await db.tasks.insert_one(new_task)
    return new_task


# --- Task deferment ---------------------------------------------------------
_MAX_DEFERS = 3
_MAX_DEFER_DAYS = 14


@api_router.post("/tasks/{task_id}/defer", response_model=TaskResponse)
async def defer_task(task_id: str, body: TaskDefer, current_user: dict = Depends(get_current_user)):
    """Defer a task to a strictly-future date, subject to two caps:

        * At most 3 defers per task (defer_count).
        * The new deferred_until date must be within 14 days of the task's
          original due date (or, when no due date was ever set, within 14
          days of today).

    Returning HTTP 400 with an explicit message on cap breach — the frontend
    surfaces this so users understand why they can no longer defer.
    """
    t = await db.tasks.find_one({"id": task_id, "user_id": current_user["id"]})
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    if t.get("status") in ("done", "cancelled"):
        raise HTTPException(status_code=400, detail="Completed or cancelled tasks cannot be deferred")

    target = (body.deferred_until or "").strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", target):
        raise HTTPException(status_code=400, detail="deferred_until must be YYYY-MM-DD")
    try:
        y, m, d = (int(p) for p in target.split("-"))
        target_date = datetime(y, m, d).date()
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"deferred_until is not a valid calendar date: {exc}") from exc

    today = datetime.now(timezone.utc).date()
    if target_date <= today:
        raise HTTPException(status_code=400, detail="deferred_until must be strictly in the future")

    defer_count = int(t.get("defer_count") or 0)
    if defer_count >= _MAX_DEFERS:
        raise HTTPException(
            status_code=400,
            detail=f"This task has already been deferred {_MAX_DEFERS} times and cannot be deferred again",
        )

    # Baseline for the +14 day cap: the ORIGINAL due date if we have one, else
    # today. Once fixed, this baseline never moves so users cannot walk the
    # cap forward one defer at a time.
    baseline_raw = t.get("original_due_date") or t.get("due_date") or today.isoformat()
    if isinstance(baseline_raw, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", baseline_raw):
        by, bm, bd = (int(p) for p in baseline_raw.split("-"))
        baseline = datetime(by, bm, bd).date()
    else:
        baseline = today
    from datetime import timedelta as _td
    max_allowed = baseline + _td(days=_MAX_DEFER_DAYS)
    if target_date > max_allowed:
        raise HTTPException(
            status_code=400,
            detail=(
                f"deferred_until cannot be more than {_MAX_DEFER_DAYS} days "
                f"past the original due date ({baseline.isoformat()})"
            ),
        )

    updates = {
        "deferred_until": target,
        "defer_count": defer_count + 1,
        # Freeze the baseline the first time we defer so subsequent defers
        # keep comparing against the same anchor.
        "original_due_date": baseline.isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.tasks.update_one({"id": task_id, "user_id": current_user["id"]}, {"$set": updates})
    updated = await db.tasks.find_one({"id": task_id}, {"_id": 0})
    return task_to_response(updated)


@api_router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str, current_user: dict = Depends(get_current_user)):
    doc = await db.tasks.find_one({"id": task_id, "user_id": current_user["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Task not found")
    return task_to_response(doc)


@api_router.put("/tasks/{task_id}", response_model=TaskResponse)
async def update_task(task_id: str, body: TaskUpdate, current_user: dict = Depends(get_current_user)):
    t = await db.tasks.find_one({"id": task_id, "user_id": current_user["id"]})
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    raw_updates = body.dict(exclude_unset=True)
    updates = {k: v for k, v in raw_updates.items() if v is not None}

    # ---- Recurrence handling (accept via PUT for simplicity) ------------
    # `set_recurrence` is the discriminator: if it is True and `recurrence`
    # is None, we CLEAR the recurrence. If `recurrence` is a dict, we set/
    # replace it. Absent field means "no change".
    should_touch_rec = ("set_recurrence" in raw_updates) or ("recurrence" in raw_updates)
    rec_dict: Optional[dict] = None
    clear_rec = False
    if should_touch_rec:
        rec_incoming = raw_updates.get("recurrence")
        set_flag = raw_updates.get("set_recurrence")
        if rec_incoming is None and (set_flag is True):
            clear_rec = True
        elif isinstance(rec_incoming, dict):
            try:
                rec_dict = _normalise_recurrence(
                    rec_incoming,
                    fallback_anchor=(updates.get("due_date") or t.get("due_date") or "") or None,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=f"recurrence: {exc}") from exc
            # Preserve existing series_id when the caller didn't supply one.
            existing_series = t.get("series_id") or (t.get("recurrence") or {}).get("series_id")
            rec_dict["series_id"] = rec_dict.get("series_id") or existing_series or str(uuid.uuid4())
    # Strip from updates dict so we don't try to $set a Pydantic model.
    updates.pop("recurrence", None)
    updates.pop("set_recurrence", None)

    if "status" in updates and updates["status"] not in TASK_STATUSES:
        raise HTTPException(status_code=400, detail=f"Status must be one of {sorted(TASK_STATUSES)}")
    if "priority" in updates and updates["priority"] not in TASK_PRIORITIES:
        raise HTTPException(status_code=400, detail=f"Priority must be one of {sorted(TASK_PRIORITIES)}")
    if "assigned_to_type" in updates and updates["assigned_to_type"] not in TASK_ASSIGNMENT_TYPES:
        raise HTTPException(status_code=400, detail=f"assigned_to_type must be one of {sorted(TASK_ASSIGNMENT_TYPES)}")
    if "commitment_type" in updates and updates["commitment_type"] not in COMMITMENT_TYPES:
        raise HTTPException(status_code=400, detail=f"commitment_type must be one of {sorted(COMMITMENT_TYPES)}")
    if updates.get("assigned_to_type") == "self":
        # Clear external contact when switching back to self.
        updates["assigned_to_name"] = ""
        updates["assigned_to_phone"] = ""
    for k in ("title", "due_date", "notes", "assigned_to_name", "assigned_to_phone"):
        if k in updates and isinstance(updates[k], str):
            updates[k] = updates[k].strip()

    # Apply recurrence mutation.
    if clear_rec:
        updates["recurrence"] = None
        updates["series_id"] = None
        updates["occurrence_index"] = 1
    elif rec_dict is not None:
        updates["recurrence"] = rec_dict
        updates["series_id"] = rec_dict["series_id"]
        if not t.get("occurrence_index"):
            updates["occurrence_index"] = 1

    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.tasks.update_one({"id": task_id, "user_id": current_user["id"]}, {"$set": updates})
    updated = await db.tasks.find_one({"id": task_id}, {"_id": 0})

    # Auto-spawn next occurrence on completion (option A). This runs after
    # the update commits so the just-completed task remains as history.
    prev_status = t.get("status", "todo")
    new_status = updates.get("status", prev_status)
    if prev_status != "done" and new_status == "done":
        try:
            await _maybe_spawn_next_occurrence(updated)
        except Exception:  # noqa: BLE001 — best-effort; do not break the PUT.
            pass

    # If pre_generate_count was set on this PUT (via a fresh recurrence),
    # materialise siblings now.
    if rec_dict and int(rec_dict.get("pre_generate_count") or 0) > 0:
        try:
            await _pre_generate_series(base_task=updated, count=int(rec_dict["pre_generate_count"]))
        except Exception:  # noqa: BLE001
            pass

    return task_to_response(updated)


# ---------------------------------------------------------------------------
# Dedicated recurrence endpoints
# ---------------------------------------------------------------------------
class RecurrenceSetBody(BaseModel):
    """Payload for POST /tasks/{id}/recurrence — a fully-specified spec."""
    cadence: str
    anchor_date: Optional[str] = None
    end_type: str = "never"
    end_date: Optional[str] = None
    occurrences_remaining: Optional[int] = None
    pre_generate_count: int = 0


@api_router.post("/tasks/{task_id}/recurrence", response_model=TaskResponse)
async def set_task_recurrence(task_id: str, body: RecurrenceSetBody, current_user: dict = Depends(get_current_user)):
    """Attach or replace the recurrence configuration on a task.

    When `pre_generate_count > 0` we materialise that many upcoming siblings
    (option B). Otherwise the task will auto-spawn the next occurrence at
    completion (option A).
    """
    t = await db.tasks.find_one({"id": task_id, "user_id": current_user["id"]})
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    try:
        rec = _normalise_recurrence(
            body.dict(),
            fallback_anchor=(t.get("due_date") or "").strip() or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"recurrence: {exc}") from exc
    rec["series_id"] = rec.get("series_id") or t.get("series_id") or str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    await db.tasks.update_one(
        {"id": task_id, "user_id": current_user["id"]},
        {"$set": {
            "recurrence": rec,
            "series_id": rec["series_id"],
            "occurrence_index": int(t.get("occurrence_index") or 1),
            "updated_at": now,
        }},
    )
    updated = await db.tasks.find_one({"id": task_id}, {"_id": 0})
    if int(rec.get("pre_generate_count") or 0) > 0:
        try:
            await _pre_generate_series(base_task=updated, count=int(rec["pre_generate_count"]))
        except Exception:  # noqa: BLE001
            pass
    return task_to_response(updated)


@api_router.delete("/tasks/{task_id}/recurrence", response_model=TaskResponse)
async def clear_task_recurrence(task_id: str, current_user: dict = Depends(get_current_user)):
    """Remove recurrence from a task. Sibling occurrences remain untouched
    (delete them individually if desired). The current task loses its
    `recurrence`, `series_id` and resets `occurrence_index=1`.
    """
    t = await db.tasks.find_one({"id": task_id, "user_id": current_user["id"]})
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    await db.tasks.update_one(
        {"id": task_id, "user_id": current_user["id"]},
        {"$set": {
            "recurrence": None,
            "series_id": None,
            "occurrence_index": 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
    )
    updated = await db.tasks.find_one({"id": task_id}, {"_id": 0})
    return task_to_response(updated)


class RecurrenceGenerateBody(BaseModel):
    """Payload for POST /tasks/{id}/recurrence/generate — walk N forward."""
    count: int = 1


@api_router.post("/tasks/{task_id}/recurrence/generate", response_model=List[TaskResponse])
async def generate_upcoming_occurrences(
    task_id: str,
    body: RecurrenceGenerateBody,
    current_user: dict = Depends(get_current_user),
):
    """Fan out the next `count` occurrences of a recurring task (option B).

    Existing siblings on the same due_date are NOT duplicated. Returns the
    newly created tasks (empty list when the series has reached its end).
    """
    t = await db.tasks.find_one({"id": task_id, "user_id": current_user["id"]})
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    if not (t.get("recurrence") or {}).get("cadence"):
        raise HTTPException(status_code=400, detail="Task has no recurrence configured")
    count = max(1, min(int(body.count or 1), _RECURRENCE_MAX_SPAWN))
    spawned = await _pre_generate_series(base_task=t, count=count)
    return [task_to_response(s) for s in spawned]


@api_router.delete("/tasks/{task_id}", status_code=200)
async def delete_task(task_id: str, current_user: dict = Depends(get_current_user)):
    result = await db.tasks.delete_one({"id": task_id, "user_id": current_user["id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"detail": "Task deleted"}


# ---------- Check-in Routes ----------
async def _create_follow_up_task(user_id: str, ft: FollowUpTask, checkin_type: str, eo_id: Optional[str], project_id: Optional[str]) -> str:
    if ft.priority not in TASK_PRIORITIES:
        raise HTTPException(status_code=400, detail=f"Follow-up priority must be one of {sorted(TASK_PRIORITIES)}")
    if ft.assigned_to_type not in TASK_ASSIGNMENT_TYPES:
        raise HTTPException(status_code=400, detail=f"Follow-up assigned_to_type must be one of {sorted(TASK_ASSIGNMENT_TYPES)}")
    if checkin_type == "goal" and eo_id:
        origin = "expected_outcome"
    elif checkin_type == "project" and project_id:
        origin = "project"
    else:
        origin = "standalone"
    now = datetime.now(timezone.utc).isoformat()
    task_id = str(uuid.uuid4())
    await db.tasks.insert_one({
        "id": task_id,
        "user_id": user_id,
        "title": ft.title.strip(),
        "due_date": (ft.due_date or "").strip(),
        "priority": ft.priority,
        "status": "todo",
        "notes": (ft.notes or "").strip(),
        "origin": origin,
        "expected_outcome_id": eo_id if origin == "expected_outcome" else None,
        "project_id": project_id if origin == "project" else None,
        "assigned_to_type": ft.assigned_to_type,
        "assigned_to_name": (ft.assigned_to_name or "").strip() if ft.assigned_to_type == "external" else "",
        "assigned_to_phone": (ft.assigned_to_phone or "").strip() if ft.assigned_to_type == "external" else "",
        "created_at": now,
        "updated_at": now,
    })
    return task_id


@api_router.get("/checkins", response_model=List[CheckInResponse])
async def list_checkins(
    current_user: dict = Depends(get_current_user),
    goal_id: Optional[str] = None,
    component_id: Optional[str] = None,
    project_id: Optional[str] = None,
    q: Optional[str] = Query(None, description="Case-insensitive search across title and notes"),
    limit: int = Query(1000, ge=1, le=5000),
):
    """List the authenticated user's check-ins.

    When ``q`` is present, filter to check-ins whose ``title`` or ``notes``
    match the query case-insensitively. Search is user-scoped by construction
    — the ``user_id`` filter is always the first predicate, so we never see
    another user's rows regardless of the query string. Results remain
    date/time descending so Timeline sees the latest matches first.
    """
    query: dict = {"user_id": current_user["id"]}
    if goal_id:
        query["goal_id"] = goal_id
    if component_id:
        query["component_id"] = component_id
    if project_id:
        query["project_id"] = project_id
    if q and q.strip():
        # Anchor the search on user_id first so the query planner never scans
        # rows outside the authenticated user's collection, then apply an
        # $or across searchable text fields with a case-insensitive regex.
        # `re.escape` neutralises any regex meta-characters the user typed
        # (e.g. ".", "*") so the search behaves like a literal substring.
        needle = re.escape(q.strip())
        query["$or"] = [
            {"title": {"$regex": needle, "$options": "i"}},
            {"notes": {"$regex": needle, "$options": "i"}},
        ]
    cursor = db.checkins.find(query, {"_id": 0})
    docs = await cursor.to_list(length=limit)
    docs.sort(key=lambda c: (c.get("date", ""), c.get("time", "")), reverse=True)
    return [checkin_to_response(d) for d in docs]


@api_router.post("/checkins", response_model=CheckInResponse, status_code=201)
async def create_checkin(body: CheckInCreate, current_user: dict = Depends(get_current_user)):
    if body.type not in CHECKIN_TYPES:
        raise HTTPException(status_code=400, detail=f"Type must be one of {sorted(CHECKIN_TYPES)}")
    if body.source not in CHECKIN_SOURCES:
        raise HTTPException(status_code=400, detail=f"Source must be one of {sorted(CHECKIN_SOURCES)}")
    goal_id: Optional[str] = None
    expected_outcome_id: Optional[str] = None
    project_id: Optional[str] = None
    task_id: Optional[str] = None
    outcome_type: Optional[str] = None

    if body.type == "goal":
        if not body.expected_outcome_id:
            raise HTTPException(status_code=400, detail="Goal check-in requires expected_outcome_id")
        eo = await db.expected_outcomes.find_one({"id": body.expected_outcome_id, "user_id": current_user["id"]})
        if not eo:
            raise HTTPException(status_code=400, detail="Invalid expected outcome")
        expected_outcome_id = eo["id"]
        goal_id = eo["goal_id"]
        outcome_type = eo.get("outcome_type", "generic")
        # Contextual validation: required fields for this outcome type must be present.
        schema = OUTCOME_TYPE_REGISTRY.get(outcome_type, OUTCOME_TYPE_REGISTRY["generic"])
        payload_data = body.data or {}
        missing = [
            f["key"] for f in schema.get("checkin_fields", [])
            if f.get("required") and (payload_data.get(f["key"]) in (None, "", []))
        ]
        if missing:
            raise HTTPException(status_code=400, detail=f"Missing required fields for outcome type '{outcome_type}': {missing}")
        # Optional task link — must live under this Expected Outcome.
        if body.task_id:
            t = await db.tasks.find_one(
                {"id": body.task_id, "user_id": current_user["id"], "expected_outcome_id": expected_outcome_id},
                {"_id": 0, "id": 1},
            )
            if not t:
                raise HTTPException(status_code=400, detail="Invalid task for this expected outcome")
            task_id = t["id"]
    elif body.type == "project":
        if not body.project_id:
            raise HTTPException(status_code=400, detail="Project check-in requires project_id")
        p = await db.projects.find_one({"id": body.project_id, "user_id": current_user["id"]})
        if not p:
            raise HTTPException(status_code=400, detail="Invalid project")
        project_id = p["id"]
        if body.task_id:
            t = await db.tasks.find_one({"id": body.task_id, "user_id": current_user["id"], "project_id": project_id})
            if not t:
                raise HTTPException(status_code=400, detail="Invalid task for this project")
            task_id = t["id"]
    else:
        # Life check-ins have no owning entity, but users may still attach an
        # arbitrary task to record incidental progress or completion. The
        # only ownership check here is user_id — a Life check-in can point
        # at any of the user's tasks.
        if body.task_id:
            t = await db.tasks.find_one(
                {"id": body.task_id, "user_id": current_user["id"]},
                {"_id": 0, "id": 1},
            )
            if not t:
                raise HTTPException(status_code=400, detail="Invalid task")
            task_id = t["id"]

    validated_component_id: Optional[str] = None

    # Money spent — optional. Validated as a non-negative finite Decimal and
    # stored as Decimal128. Requires currency when present. `available_for_
    # flexible_spending` in the money-position endpoint subtracts the sum of
    # these values for the same month + currency.
    from bson.decimal128 import Decimal128 as _D128
    from decimal import Decimal as _Dec, InvalidOperation as _InvOp
    stored_money_spent = None
    stored_money_currency: Optional[str] = None
    resolved_account_id: Optional[str] = None
    if body.money_spent is not None and body.money_spent != "":
        raw = body.money_spent
        if isinstance(raw, bool):
            raise HTTPException(status_code=400, detail="money_spent must be a decimal number")
        try:
            d = _Dec(str(raw))
        except (_InvOp, ValueError, TypeError) as _e:
            raise HTTPException(status_code=400, detail=f"money_spent must be a valid decimal: {_e}") from _e
        if d.is_nan() or d.is_infinite():
            raise HTTPException(status_code=400, detail="money_spent must be a finite number")
        if d < 0:
            raise HTTPException(status_code=400, detail="money_spent must be zero or positive")
        if not body.money_currency or not re.match(r"^[A-Z]{3}$", body.money_currency):
            raise HTTPException(status_code=400, detail="money_currency must be an ISO 4217 code when money_spent is set")
        stored_money_spent = _D128(d)
        stored_money_currency = body.money_currency
        # Batch 2A + Correction 1: account linkage for money-bearing
        # check-ins. Uses the finance_manager helper so liability
        # accounts are rejected too. Raises 400/404 on cross-user,
        # currency mismatch, or liability.
        if body.account_id:
            from finance_manager import _resolve_event_account  # noqa: WPS433
            await _resolve_event_account(db, current_user["id"], body.account_id, stored_money_currency)
            resolved_account_id = body.account_id

    follow_up_task_id: Optional[str] = None
    if body.follow_up_task:
        follow_up_task_id = await _create_follow_up_task(
            current_user["id"], body.follow_up_task, body.type, expected_outcome_id, project_id,
        )

    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": current_user["id"],
        "type": body.type,
        "title": body.title.strip(),
        "date": body.date,
        "time": body.time,
        "notes": (body.notes or "").strip(),
        "attachment": (body.attachment or "").strip(),
        "expected_outcome_id": expected_outcome_id,
        "goal_id": goal_id,
        "project_id": project_id,
        "task_id": task_id,
        "component_id": validated_component_id,
        "follow_up_task_id": follow_up_task_id,
        "source": body.source,
        "outcome_type": outcome_type,
        "data": body.data or {},
        "money_spent": stored_money_spent,
        "money_currency": stored_money_currency,
        # Batch 2A: preserve the account linkage for money-bearing
        # check-ins (may be None; the derived event is then created in
        # pending_account_assignment).
        "account_id": resolved_account_id,
        "created_at": now,
        "updated_at": now,
    }
    await db.checkins.insert_one(doc)

    # Batch 2A: Feed the Finance Event Pipeline with best-effort
    # cross-collection consistency. The database in this environment
    # does NOT guarantee transactional atomicity; instead we roll each
    # document back manually on failure so no orphan lingers. Creating
    # a money-bearing check-in and its financial event succeed or fail
    # together at the endpoint level.
    if stored_money_spent is not None and stored_money_currency:
        _created_event_id: Optional[str] = None
        _created_dedupe_id: Optional[str] = None
        try:
            from finance_manager import (  # noqa: WPS433 local import
                _dedupe_check,
                _now as _fnow,
                _money_from_stored,
                _normalise_occurred_at,
                LIFECYCLE_STATUS_PENDING_ACCOUNT,
                LIFECYCLE_STATUS_AWAITING_RECON,
            )
            lifecycle_status = (
                LIFECYCLE_STATUS_AWAITING_RECON if resolved_account_id
                else LIFECYCLE_STATUS_PENDING_ACCOUNT
            )
            # Batch 2A Correction 1: derive the authoritative
            # ``occurred_at`` for the linked event.
            # 1. Prefer the client's explicit tz-aware ``occurred_at``.
            # 2. Otherwise interpret the check-in ``date+time`` as UTC
            #    (documented fallback — no per-user timezone is stored).
            occurred_at_iso = _normalise_occurred_at(body.occurred_at)
            if not occurred_at_iso and body.date:
                try:
                    _t = body.time or "00:00"
                    _dt = datetime.fromisoformat(f"{body.date}T{_t}:00+00:00")
                    occurred_at_iso = _dt.astimezone(timezone.utc).isoformat()
                except Exception:
                    occurred_at_iso = None
            fev = {
                "id": str(uuid.uuid4()),
                "user_id": current_user["id"],
                "amount": stored_money_spent if isinstance(stored_money_spent, _D128) else _D128(stored_money_spent),
                "currency": stored_money_currency,
                "direction": "outflow",
                "event_date": body.date,
                "description": (body.notes or body.title or "").strip()[:200],
                "source": "checkin",
                "source_reference": f"checkin:{doc['id']}",
                "confirmation_status": "confirmed",
                "checkin_id": doc["id"],
                "commitment_id": None,
                "account_id": resolved_account_id,
                "lifecycle_status": lifecycle_status,
                "occurred_at": occurred_at_iso,
                "created_at": _fnow(),
            }
            dup_id = await _dedupe_check(db, current_user["id"], fev)
            if dup_id:
                # Correction 2: duplicates remain FINANCIALLY UNAPPLIED
                # in a status that reflects their true blocker. If the
                # incoming event carries an account, it is a dedupe
                # candidate (``pending_deduplication``); otherwise it
                # still needs account assignment first
                # (``pending_account_assignment``).
                fev["confirmation_status"] = "pending"
                fev["lifecycle_status"] = (
                    "pending_deduplication" if resolved_account_id
                    else LIFECYCLE_STATUS_PENDING_ACCOUNT
                )
                await db.financial_events.insert_one(dict(fev))
                _created_event_id = fev["id"]
                _dedupe = {
                    "id": str(uuid.uuid4()),
                    "user_id": current_user["id"],
                    "event_a_id": dup_id,
                    "event_b_id": fev["id"],
                    "status": "pending",
                    "created_at": _fnow(),
                    "resolved_at": None,
                }
                await db.financial_dedupe_candidates.insert_one(_dedupe)
                _created_dedupe_id = _dedupe["id"]
            else:
                await db.financial_events.insert_one(dict(fev))
                _created_event_id = fev["id"]
            await db.financial_audit.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": current_user["id"],
                "record_type": "financial_event",
                "record_id": fev["id"],
                "action": "created",
                "timestamp": _fnow(),
                "source": "checkin",
                "previous_value": None,
                "new_value": {
                    "amount": _money_from_stored(fev["amount"]),
                    "currency": fev["currency"],
                    "checkin_id": doc["id"],
                    "account_id": resolved_account_id,
                    "occurred_at": occurred_at_iso,
                    "lifecycle_status": fev["lifecycle_status"],
                    "pending_dedupe_with": dup_id,
                },
                "related_checkin_id": doc["id"],
                "related_task_id": task_id,
                "related_event_id": None,
                "related_import_id": None,
                "notes": "",
            })
        except HTTPException:
            # Best-effort rollback so no orphan lingers. The database
            # does not guarantee cross-collection atomicity in this
            # environment, so we roll back document-by-document.
            if _created_dedupe_id:
                await db.financial_dedupe_candidates.delete_one({"id": _created_dedupe_id})
            if _created_event_id:
                await db.financial_events.delete_one({"id": _created_event_id})
            await db.checkins.delete_one({"id": doc["id"]})
            if follow_up_task_id:
                await db.tasks.delete_one({"id": follow_up_task_id, "user_id": current_user["id"]})
            raise
        except Exception as _fx:
            if _created_dedupe_id:
                await db.financial_dedupe_candidates.delete_one({"id": _created_dedupe_id})
            if _created_event_id:
                await db.financial_events.delete_one({"id": _created_event_id})
            await db.checkins.delete_one({"id": doc["id"]})
            if follow_up_task_id:
                await db.tasks.delete_one({"id": follow_up_task_id, "user_id": current_user["id"]})
            logger.warning("finance-event-hook failed: %s", _fx)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to record the linked financial event: {_fx}",
            ) from _fx

    # A check-in on a task is an "update", not a completion — bump the task's
    # updated_at so the tasks list surfaces recent activity. Only flip status
    # to `done` when the caller explicitly opts in with complete_task=true.
    if task_id:
        task_updates: dict = {"updated_at": now}
        if body.complete_task:
            task_updates["status"] = "done"
        await db.tasks.update_one(
            {"id": task_id, "user_id": current_user["id"]}, {"$set": task_updates},
        )
        # If the check-in completed a recurring task, spawn the next occurrence.
        if body.complete_task:
            try:
                fresh = await db.tasks.find_one({"id": task_id, "user_id": current_user["id"]}, {"_id": 0})
                if fresh and (fresh.get("recurrence") or {}).get("cadence"):
                    await _maybe_spawn_next_occurrence(fresh)
            except Exception as _rx:  # pragma: no cover
                logger.warning("recurrence auto-spawn from checkin failed: %s", _rx)

    doc.pop("_id", None)
    return checkin_to_response(doc)


@api_router.get("/checkins/required")
async def list_required_checkins(
    date: str = Query(..., description="Client's local date, YYYY-MM-DD"),
    current_user: dict = Depends(get_current_user),
):
    """Return Goals that need a check-in for the period containing ``date``.

    Scheduling source: ``Goal.checkin_cadence``. This endpoint does NOT
    materialise any records — it computes the "required" set at read time by
    inspecting the checkins collection for the current period. Cadence rules:

        * ``manual``     -> never required.
        * ``daily``      -> required if no checkin exists for that Goal on
                            the requested local date.
        * ``weekly``     -> required if no checkin exists in that ISO calendar
                            week (Mon..Sun containing ``date``).
        * ``monthly``    -> required if no checkin exists in that calendar
                            month (YYYY-MM prefix of ``date``).

    Goals with status in {completed, paused, abandoned} are never returned.
    A Goal is "completed for the period" if either
        * a checkin exists with ``goal_id`` = this Goal, OR
        * a checkin exists whose ``expected_outcome_id`` belongs to any
          Expected Outcome of this Goal.

    Response fields: goal_id, goal_title, domain_name, checkin_cadence,
    completed_for_period. Sort: daily -> weekly -> monthly -> goal_title.
    """
    # Validate the incoming date string in the same format the rest of the
    # backend uses. This is a stateless computation — the client owns the
    # notion of "today" per its local timezone.
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date or ""):
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    try:
        y, m, d = (int(p) for p in date.split("-"))
        anchor = datetime(y, m, d, tzinfo=timezone.utc).date()
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"date is not a valid calendar date: {exc}") from exc

    # Period bounds (all bounds are inclusive strings comparable lexically).
    day_str = date
    week_start = anchor - timedelta(days=anchor.weekday())  # Monday
    week_end = week_start + timedelta(days=6)               # Sunday
    week_start_str, week_end_str = week_start.isoformat(), week_end.isoformat()
    month_prefix = date[:7]  # YYYY-MM

    user_id = current_user["id"]

    # All goals with a recurrence-based cadence are candidates. "manual" is
    # excluded (user drives it themselves). Empty cadence is excluded too.
    goals = await db.goals.find(
        {
            "user_id": user_id,
            "status": "active",
            "checkin_cadence": {"$in": sorted(RECURRENCE_CADENCES)},
        },
        {"_id": 0, "id": 1, "title": 1, "domain_id": 1, "checkin_cadence": 1,
         "checkin_anchor_date": 1, "created_at": 1},
    ).to_list(length=5000)
    if not goals:
        return []

    goal_ids = [g["id"] for g in goals]

    # Expected-outcome -> goal_id map so we can attribute EO-linked checkins
    # back to their parent Goal.
    eos = await db.expected_outcomes.find(
        {"user_id": user_id, "goal_id": {"$in": goal_ids}},
        {"_id": 0, "id": 1, "goal_id": 1},
    ).to_list(length=10000)
    eo_to_goal = {e["id"]: e["goal_id"] for e in eos}
    all_eo_ids = list(eo_to_goal.keys())

    # Widened lookup window: yearly cadence needs to look back up to 12
    # months. We fetch a full year to keep the query bound small — the
    # per-goal period comparison happens in-process.
    from datetime import timedelta as _td
    lookup_lo = (anchor - _td(days=400)).isoformat()
    lookup_hi = anchor.isoformat()

    checkins = await db.checkins.find(
        {
            "user_id": user_id,
            "date": {"$gte": lookup_lo, "$lte": lookup_hi},
            "$or": [
                {"goal_id": {"$in": goal_ids}},
                {"expected_outcome_id": {"$in": all_eo_ids}} if all_eo_ids else {"goal_id": None},
            ],
        },
        {"_id": 0, "goal_id": 1, "expected_outcome_id": 1, "date": 1},
    ).to_list(length=20000)

    # Build per-goal sets of the dates on which a check-in exists.
    goal_checkin_dates: dict = {gid: [] for gid in goal_ids}
    for c in checkins:
        gid = c.get("goal_id") or eo_to_goal.get(c.get("expected_outcome_id") or "")
        if not gid or gid not in goal_checkin_dates:
            continue
        d_val = c.get("date") or ""
        if d_val:
            goal_checkin_dates[gid].append(d_val)

    # Domain names in one lookup.
    domain_ids = list({g["domain_id"] for g in goals if g.get("domain_id")})
    domain_docs = await db.domains.find(
        {"user_id": user_id, "id": {"$in": domain_ids}}, {"_id": 0, "id": 1, "name": 1},
    ).to_list(length=1000) if domain_ids else []
    domain_name_by_id = {d["id"]: d["name"] for d in domain_docs}

    def _resolve_anchor(g: dict):
        """Anchor priority: explicit checkin_anchor_date > goal.created_at date."""
        raw = (g.get("checkin_anchor_date") or "").strip()
        if raw:
            try:
                return _parse_iso_date(raw)
            except ValueError:
                pass
        created_raw = (g.get("created_at") or "")[:10]
        if created_raw:
            try:
                return _parse_iso_date(created_raw)
            except ValueError:
                pass
        return anchor  # fallback: today

    def _completed(gid: str, cadence: str, g: dict) -> bool:
        dates = goal_checkin_dates.get(gid) or []
        # Legacy fast-paths preserve identical semantics to the pre-recurrence
        # scheduler for the three original cadences.
        if cadence == "daily":
            return day_str in dates
        if cadence == "weekly":
            return any(week_start_str <= x <= week_end_str for x in dates)
        if cadence == "monthly":
            return any((x or "").startswith(month_prefix) for x in dates)
        # Extended cadences: compute the period containing `anchor` and check
        # for any check-in inside it.
        anc = _resolve_anchor(g)
        try:
            active, p_start, p_end = _is_active_period(anc, cadence, anchor)
        except ValueError:
            return False
        if not active:
            # Period hasn't started yet — treat as "not due", so it should not
            # be returned as required either. We express this via `completed`
            # so the caller skips it.
            return True
        ps, pe = p_start.isoformat(), p_end.isoformat()
        return any(ps <= (x or "") <= pe for x in dates)

    cadence_rank = {
        "daily": 0, "alternate_day": 1, "weekly": 2, "fortnightly": 3,
        "monthly": 4, "quarterly": 5, "half_yearly": 6, "yearly": 7,
    }
    result = []
    for g in goals:
        cadence = g.get("checkin_cadence") or ""
        completed = _completed(g["id"], cadence, g)
        if completed:
            # Spec: return only goals that still need a checkin for the period.
            continue
        result.append({
            "goal_id": g["id"],
            "goal_title": g.get("title", ""),
            "domain_name": domain_name_by_id.get(g.get("domain_id", ""), ""),
            "checkin_cadence": cadence,
            "completed_for_period": False,
        })

    result.sort(key=lambda r: (cadence_rank.get(r["checkin_cadence"], 99), r["goal_title"].lower()))
    return result


@api_router.get("/spending")
async def get_spending(
    date: str = Query(..., description="Local YYYY-MM-DD to fetch spending for"),
    current_user: dict = Depends(get_current_user),
):
    """Return check-ins with money_spent for the given local date.

    Response shape::

        {
          "date": "YYYY-MM-DD",
          "groups": [
            { "currency": "USD", "total": "42.50",
              "entries": [ { id, title, time, amount, notes, goal_id, task_id, expected_outcome_id }, ... ] }
          ]
        }

    The Today screen consumes this to render the "Today's Spending" card and
    the /spending detail page groups entries per currency (no FX conversion).
    """
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date or ""):
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")

    docs = await db.checkins.find(
        {
            "user_id": current_user["id"],
            "date": date,
            "money_spent": {"$ne": None},
        },
        {
            "_id": 0, "id": 1, "title": 1, "date": 1, "time": 1,
            "money_spent": 1, "money_currency": 1, "notes": 1,
            "goal_id": 1, "task_id": 1, "expected_outcome_id": 1,
        },
    ).to_list(length=5000)

    from bson.decimal128 import Decimal128 as _D128
    from decimal import Decimal as _Dec

    def _to_dec(v):
        if v is None:
            return _Dec(0)
        if isinstance(v, _D128):
            return v.to_decimal()
        try:
            return _Dec(str(v))
        except Exception:  # noqa: BLE001
            return _Dec(0)

    groups: dict = {}
    for d in docs:
        cur = d.get("money_currency") or ""
        amt = _to_dec(d.get("money_spent"))
        if not cur:
            continue
        g = groups.setdefault(cur, {"currency": cur, "total": _Dec(0), "entries": []})
        g["total"] += amt
        g["entries"].append({
            "id": d.get("id"),
            "title": d.get("title") or "",
            "time": d.get("time") or "",
            "amount": str(amt),
            "notes": d.get("notes") or "",
            "goal_id": d.get("goal_id"),
            "task_id": d.get("task_id"),
            "expected_outcome_id": d.get("expected_outcome_id"),
        })

    payload = {
        "date": date,
        "groups": [
            {
                "currency": g["currency"],
                "total": str(g["total"].quantize(_Dec("0.01"))),
                "entries": sorted(g["entries"], key=lambda e: e.get("time") or ""),
            }
            for g in sorted(groups.values(), key=lambda x: x["currency"])
        ],
    }
    return payload


@api_router.get("/checkins/{checkin_id}", response_model=CheckInResponse)
async def get_checkin(checkin_id: str, current_user: dict = Depends(get_current_user)):
    doc = await db.checkins.find_one({"id": checkin_id, "user_id": current_user["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Check-in not found")
    return checkin_to_response(doc)


@api_router.put("/checkins/{checkin_id}", response_model=CheckInResponse)
async def update_checkin(checkin_id: str, body: CheckInUpdate, current_user: dict = Depends(get_current_user)):
    c = await db.checkins.find_one({"id": checkin_id, "user_id": current_user["id"]})
    if not c:
        raise HTTPException(status_code=404, detail="Check-in not found")

    incoming = body.dict(exclude_unset=True)
    updates = {k: v for k, v in incoming.items() if v is not None}
    for k in ("title", "date", "time", "notes", "attachment"):
        if k in updates and isinstance(updates[k], str):
            updates[k] = updates[k].strip()

    # Batch 2A: reject destructive money edits on a check-in whose event
    # already completed a commitment (lifecycle_status='matched'). The
    # actual has flowed into the reservation ledger; the user must first
    # adjust the reconciliation.
    money_field_touched = any(k in incoming for k in ("money_spent", "money_currency", "account_id", "date", "occurred_at"))
    # Locate the canonical event (may include a previously-voided one so
    # we can reactivate instead of duplicating).
    linked_event_any = await db.financial_events.find_one(
        {"checkin_id": checkin_id, "user_id": current_user["id"]}, {"_id": 0},
        sort=[("created_at", -1)],
    ) if money_field_touched else None
    if linked_event_any and linked_event_any.get("lifecycle_status") == "matched":
        raise HTTPException(
            status_code=409,
            detail=(
                "This check-in's financial event has been reconciled with a commitment. "
                "Reverse the reconciliation before editing money fields."
            ),
        )

    # Batch 2A: validate money-related fields together.
    from bson.decimal128 import Decimal128 as _D128
    from decimal import Decimal as _Dec, InvalidOperation as _InvOp
    from finance_manager import (  # noqa: WPS433 local import
        _now as _fnow,
        _resolve_event_account,
        _normalise_occurred_at,
    )

    resolved_account_id_update = incoming.get("account_id") if "account_id" in incoming else c.get("account_id")
    if "money_spent" in incoming:
        raw = incoming["money_spent"]
        if raw is None or raw == "":
            updates["money_spent"] = None
        else:
            try:
                d = _Dec(str(raw))
            except (_InvOp, ValueError, TypeError) as _e:
                raise HTTPException(status_code=400, detail=f"money_spent must be a valid decimal: {_e}") from _e
            if d.is_nan() or d.is_infinite():
                raise HTTPException(status_code=400, detail="money_spent must be a finite number")
            if d < 0:
                raise HTTPException(status_code=400, detail="money_spent must be zero or positive")
            updates["money_spent"] = _D128(d)
    if "money_currency" in incoming and incoming["money_currency"]:
        if not re.match(r"^[A-Z]{3}$", incoming["money_currency"]):
            raise HTTPException(status_code=400, detail="money_currency must be an ISO 4217 code")
        updates["money_currency"] = incoming["money_currency"]

    effective_amount = updates.get("money_spent") if "money_spent" in updates else c.get("money_spent")
    effective_currency = updates.get("money_currency") if "money_currency" in updates else c.get("money_currency")
    if effective_amount is not None and effective_currency:
        if resolved_account_id_update:
            # Correction 1: reject cross-user, cross-currency AND
            # liability accounts via the shared helper.
            await _resolve_event_account(db, current_user["id"], resolved_account_id_update, effective_currency)
        updates["account_id"] = resolved_account_id_update
    elif "account_id" in incoming:
        updates["account_id"] = incoming["account_id"]

    prev_snapshot = {k: c.get(k) for k in ("money_spent", "money_currency", "account_id", "date", "time")}
    # Correction 2: snapshot the linked event's mutable fields BEFORE
    # any write so we can restore them atomically if a later step
    # fails.
    prev_event_snapshot: Optional[dict] = None
    if linked_event_any:
        prev_event_snapshot = {
            k: linked_event_any.get(k)
            for k in ("amount", "currency", "event_date", "description",
                       "account_id", "occurred_at", "confirmation_status", "lifecycle_status")
        }
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.checkins.update_one({"id": checkin_id, "user_id": current_user["id"]}, {"$set": updates})
    # Track anything we created inside the try/except so we can roll it
    # back on failure.
    _created_new_event_id: Optional[str] = None
    _created_audit_id: Optional[str] = None
    try:
        updated = await db.checkins.find_one({"id": checkin_id}, {"_id": 0})

        if money_field_touched:
            new_amount = updated.get("money_spent")
            new_currency = updated.get("money_currency")
            new_account_id = updated.get("account_id")
            has_money = new_amount is not None and bool(new_currency)

            # Correction 2: never silently interpret naive check-in
            # date+time as UTC. Only accept an explicit tz-aware
            # ``occurred_at`` from the caller; if absent, leave the
            # event unapplied by setting occurred_at to None so the
            # money service refuses to place it.
            occurred_at_iso: Optional[str] = None
            if "occurred_at" in incoming:
                occurred_at_iso = _normalise_occurred_at(incoming.get("occurred_at"))
                if incoming.get("occurred_at") and occurred_at_iso is None:
                    raise HTTPException(
                        status_code=400,
                        detail="occurred_at must be a timezone-aware ISO 8601 timestamp",
                    )
            else:
                # Preserve the previous occurred_at when the caller did
                # not touch it — a description or amount edit shouldn't
                # invalidate the moment we already trusted.
                occurred_at_iso = (linked_event_any or {}).get("occurred_at")

            new_lifecycle = (
                "awaiting_reconciliation"
                if new_account_id and occurred_at_iso
                else "pending_account_assignment"
            )

            if linked_event_any and linked_event_any.get("lifecycle_status") != "void":
                # Sync existing non-void event.
                if not has_money:
                    # Money cleared — void the canonical event.
                    await db.financial_events.update_one(
                        {"id": linked_event_any["id"]},
                        {"$set": {
                            "lifecycle_status": "void",
                            "confirmation_status": "rejected",
                        }},
                    )
                else:
                    await db.financial_events.update_one(
                        {"id": linked_event_any["id"]},
                        {"$set": {
                            "amount": new_amount if isinstance(new_amount, _D128) else _D128(_Dec(str(new_amount))),
                            "currency": new_currency,
                            "event_date": updated.get("date") or linked_event_any.get("event_date"),
                            "description": (updated.get("notes") or updated.get("title") or "").strip()[:200],
                            "account_id": new_account_id,
                            "occurred_at": occurred_at_iso,
                            "lifecycle_status": new_lifecycle,
                        }},
                    )
            elif linked_event_any and linked_event_any.get("lifecycle_status") == "void" and has_money:
                # Correction 1: money re-added after a prior void —
                # reactivate the existing canonical event in place so no
                # duplicate is created and the unique index remains
                # satisfied.
                await db.financial_events.update_one(
                    {"id": linked_event_any["id"]},
                    {"$set": {
                        "amount": new_amount if isinstance(new_amount, _D128) else _D128(_Dec(str(new_amount))),
                        "currency": new_currency,
                        "event_date": updated.get("date") or linked_event_any.get("event_date"),
                        "description": (updated.get("notes") or updated.get("title") or "").strip()[:200],
                        "account_id": new_account_id,
                        "occurred_at": occurred_at_iso,
                        "confirmation_status": "confirmed",
                        "lifecycle_status": new_lifecycle,
                    }},
                )
            elif not linked_event_any and has_money:
                # Correction 1: money added to a check-in that had no
                # canonical event — create it now so Finance reflects
                # the spend exactly once.
                fev_id = str(uuid.uuid4())
                fev = {
                    "id": fev_id,
                    "user_id": current_user["id"],
                    "amount": new_amount if isinstance(new_amount, _D128) else _D128(_Dec(str(new_amount))),
                    "currency": new_currency,
                    "direction": "outflow",
                    "event_date": updated.get("date") or "",
                    "description": (updated.get("notes") or updated.get("title") or "").strip()[:200],
                    "source": "checkin",
                    "source_reference": f"checkin:{checkin_id}",
                    "confirmation_status": "confirmed",
                    "checkin_id": checkin_id,
                    "commitment_id": None,
                    "account_id": new_account_id,
                    "lifecycle_status": new_lifecycle,
                    "occurred_at": occurred_at_iso,
                    "created_at": _fnow(),
                }
                await db.financial_events.insert_one(dict(fev))
                _created_new_event_id = fev_id

            # Audit trail (append-only). Correction 2: reference the
            # newly-created event ID when we created one, otherwise the
            # existing event's ID.
            _audit_id = str(uuid.uuid4())
            _audit_record_id = (
                _created_new_event_id or (linked_event_any or {}).get("id")
            )
            await db.financial_audit.insert_one({
                "id": _audit_id,
                "user_id": current_user["id"],
                "record_type": "financial_event",
                "record_id": _audit_record_id,
                "action": "updated" if linked_event_any else "created",
                "timestamp": _fnow(),
                "source": "checkin",
                "previous_value": {**prev_snapshot, "event": prev_event_snapshot},
                "new_value": {
                    "money_spent": new_amount if isinstance(new_amount, (str, type(None))) else str(new_amount),
                    "money_currency": new_currency,
                    "account_id": new_account_id,
                    "occurred_at": occurred_at_iso,
                    "has_money": has_money,
                    "lifecycle_status": (
                        "void" if (linked_event_any and not has_money)
                        else new_lifecycle if has_money else None
                    ),
                },
                "related_checkin_id": checkin_id,
                "related_task_id": c.get("task_id"),
                "related_event_id": _audit_record_id,
                "related_import_id": None,
                "notes": "",
            })
            _created_audit_id = _audit_id
    except Exception:
        # Correction 2: complete rollback. Restore the check-in AND
        # the linked event's previous state, remove anything we
        # created solely for this failed operation.
        await db.checkins.update_one(
            {"id": checkin_id, "user_id": current_user["id"]},
            {"$set": {**prev_snapshot, "updated_at": c.get("updated_at")}},
        )
        if _created_new_event_id:
            await db.financial_events.delete_one({"id": _created_new_event_id, "user_id": current_user["id"]})
        elif linked_event_any and prev_event_snapshot is not None:
            await db.financial_events.update_one(
                {"id": linked_event_any["id"], "user_id": current_user["id"]},
                {"$set": prev_event_snapshot},
            )
        if _created_audit_id:
            await db.financial_audit.delete_one({"id": _created_audit_id})
        raise

    return checkin_to_response(updated)


@api_router.delete("/checkins/{checkin_id}", status_code=200)
async def delete_checkin(checkin_id: str, current_user: dict = Depends(get_current_user)):
    # Batch 2A: preserve audit history by reversing/rejecting the linked
    # event instead of deleting it. If the event has already been matched
    # to a commitment we refuse the delete so reconciliation ledger stays
    # coherent — the user is told to reverse the reconciliation first.
    from finance_manager import _now as _fnow  # noqa: WPS433 local import
    existing = await db.checkins.find_one({"id": checkin_id, "user_id": current_user["id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Check-in not found")
    linked_event = await db.financial_events.find_one(
        {"checkin_id": checkin_id, "user_id": current_user["id"]}, {"_id": 0},
    )
    if linked_event and linked_event.get("lifecycle_status") == "matched":
        raise HTTPException(
            status_code=409,
            detail=(
                "This check-in's financial event has been reconciled with a commitment. "
                "Reverse the reconciliation before deleting the check-in."
            ),
        )
    if linked_event and linked_event.get("lifecycle_status") not in ("void",):
        # Reverse the event so it no longer counts against the balance.
        await db.financial_events.update_one(
            {"id": linked_event["id"]},
            {"$set": {"lifecycle_status": "void", "confirmation_status": "rejected"}},
        )
        await db.financial_audit.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": current_user["id"],
            "record_type": "financial_event",
            "record_id": linked_event["id"],
            "action": "updated",
            "timestamp": _fnow(),
            "source": "checkin",
            "previous_value": {"lifecycle_status": linked_event.get("lifecycle_status")},
            "new_value": {"lifecycle_status": "void", "reason": "checkin_deleted"},
            "related_checkin_id": checkin_id,
            "related_task_id": existing.get("task_id"),
            "related_event_id": linked_event["id"],
            "related_import_id": None,
            "notes": "",
        })

    result = await db.checkins.delete_one({"id": checkin_id, "user_id": current_user["id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Check-in not found")
    return {"detail": "Check-in deleted"}


# ---------- Outcome Type Registry Endpoint ----------
@api_router.get("/outcome-types")
async def get_outcome_types():
    """Returns the metadata-driven Expected Outcome type registry."""
    return {"types": OUTCOME_TYPE_REGISTRY}


# ---------- App wiring ----------
# Portfolio Manager — imported here (after db/get_current_user are defined) to
# avoid a circular import. It owns CRUD for its four collections and exposes
# derived time/money calculations under /api/portfolio/*.
from portfolio_manager import portfolio_router, ensure_portfolio_indexes  # noqa: E402
from finance_manager import (
    finance_router,
    ensure_finance_indexes,
    backfill_fc_into_allocations,
)  # noqa: E402
from finance_advanced import advanced_router as finance_advanced_router, ensure_finance_advanced_indexes  # noqa: E402
from planning_engine import planning_router, ensure_planning_indexes  # noqa: E402
import goal_merge  # noqa: F401,E402  (registers merge endpoints on planning_router)

api_router.include_router(portfolio_router)
api_router.include_router(finance_router)
api_router.include_router(finance_advanced_router)
api_router.include_router(planning_router)
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@app.on_event("startup")
async def startup_indexes():
    await db.users.create_index("email", unique=True)
    await db.users.create_index("id", unique=True)
    await db.user_sessions.create_index("session_token", unique=True)
    await db.user_sessions.create_index("user_id")
    await db.user_sessions.create_index("expires_at", expireAfterSeconds=0)
    await ensure_portfolio_indexes(db)
    await ensure_finance_indexes(db)
    await ensure_finance_advanced_indexes(db)
    await ensure_planning_indexes(db)
    try:
        touched = await backfill_fc_into_allocations(db)
        if touched:
            logger.info("finance migration: backfilled %d financial_commitments into resource_allocations", touched)
    except Exception as _bfx:  # pragma: no cover — never fail startup
        logger.warning("finance backfill skipped: %s", _bfx)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
