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
from typing import List, Optional
from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from passlib.context import CryptContext
import httpx

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

# ---------- Config ----------
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
JWT_SECRET = os.environ.get("JWT_SECRET", "hymn-dev-secret-change-in-prod")
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


class UserResponse(BaseModel):
    id: str
    email: EmailStr


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
CHECKIN_CADENCES = {"daily", "weekly", "monthly", "manual"}
KNOWLEDGE_DOMAIN_NAME = "Knowledge"


class GoalCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    domain_id: str
    target_outcome: str = ""
    deadline: str = ""  # YYYY-MM-DD (optional)
    status: str = "active"
    notes: str = ""
    checkin_cadence: str = ""  # "" | daily | weekly | monthly | manual


class GoalUpdate(BaseModel):
    title: Optional[str] = None
    domain_id: Optional[str] = None
    target_outcome: Optional[str] = None
    deadline: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    checkin_cadence: Optional[str] = None


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


class ProjectUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    start_date: Optional[str] = None
    target_end_date: Optional[str] = None
    notes: Optional[str] = None


class ProjectResponse(BaseModel):
    id: str
    title: str
    description: str
    status: str
    start_date: str
    target_end_date: str
    notes: str
    created_at: str
    updated_at: str


# ---------- Task ----------
TASK_STATUSES = {"todo", "done", "deferred"}
TASK_PRIORITIES = {"low", "medium", "high"}
TASK_ORIGINS = {"expected_outcome", "project", "standalone"}


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


class CheckInUpdate(BaseModel):
    title: Optional[str] = None
    date: Optional[str] = None
    time: Optional[str] = None
    notes: Optional[str] = None
    attachment: Optional[str] = None
    component_id: Optional[str] = None
    data: Optional[dict] = None


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
    return UserResponse(id=u["id"], email=u["email"])


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
        created_at=p.get("created_at", ""),
        updated_at=p.get("updated_at", ""),
    )


def task_to_response(t: dict) -> TaskResponse:
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
        created_at=t.get("created_at", ""),
        updated_at=t.get("updated_at", ""),
    )


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
    if body.status not in GOAL_STATUSES:
        raise HTTPException(status_code=400, detail=f"Status must be one of {sorted(GOAL_STATUSES)}")
    if body.checkin_cadence and body.checkin_cadence not in CHECKIN_CADENCES:
        raise HTTPException(status_code=400, detail=f"checkin_cadence must be one of {sorted(CHECKIN_CADENCES)} or empty")
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
    if "checkin_cadence" in updates and updates["checkin_cadence"] and updates["checkin_cadence"] not in CHECKIN_CADENCES:
        raise HTTPException(status_code=400, detail=f"checkin_cadence must be one of {sorted(CHECKIN_CADENCES)} or empty")
    if "domain_id" in updates:
        d = await db.domains.find_one({"id": updates["domain_id"], "user_id": current_user["id"]})
        if not d:
            raise HTTPException(status_code=400, detail="Invalid domain")
    for k in ("title", "target_outcome", "deadline", "notes", "checkin_cadence"):
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
):
    q: dict = {"user_id": current_user["id"]}
    if component_id:
        q["component_id"] = component_id
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
    await _validate_task_origin(current_user["id"], body.origin, body.expected_outcome_id, body.project_id)
    # Optional Knowledge Component link.
    validated_component_id: Optional[str] = None
    if body.component_id:
        comp = await db.knowledge_components.find_one({"id": body.component_id, "user_id": current_user["id"]})
        if not comp:
            raise HTTPException(status_code=400, detail="Invalid component_id")
        validated_component_id = comp["id"]
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": str(uuid.uuid4()),
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
        "created_at": now,
        "updated_at": now,
    }
    await db.tasks.insert_one(doc)
    doc.pop("_id", None)
    return task_to_response(doc)


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
    updates = {k: v for k, v in body.dict(exclude_unset=True).items() if v is not None}
    if "status" in updates and updates["status"] not in TASK_STATUSES:
        raise HTTPException(status_code=400, detail=f"Status must be one of {sorted(TASK_STATUSES)}")
    if "priority" in updates and updates["priority"] not in TASK_PRIORITIES:
        raise HTTPException(status_code=400, detail=f"Priority must be one of {sorted(TASK_PRIORITIES)}")
    if "assigned_to_type" in updates and updates["assigned_to_type"] not in TASK_ASSIGNMENT_TYPES:
        raise HTTPException(status_code=400, detail=f"assigned_to_type must be one of {sorted(TASK_ASSIGNMENT_TYPES)}")
    if updates.get("assigned_to_type") == "self":
        # Clear external contact when switching back to self.
        updates["assigned_to_name"] = ""
        updates["assigned_to_phone"] = ""
    for k in ("title", "due_date", "notes", "assigned_to_name", "assigned_to_phone"):
        if k in updates and isinstance(updates[k], str):
            updates[k] = updates[k].strip()
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.tasks.update_one({"id": task_id, "user_id": current_user["id"]}, {"$set": updates})
    updated = await db.tasks.find_one({"id": task_id}, {"_id": 0})
    return task_to_response(updated)


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
):
    q: dict = {"user_id": current_user["id"]}
    if goal_id:
        q["goal_id"] = goal_id
    if component_id:
        q["component_id"] = component_id
    cursor = db.checkins.find(q, {"_id": 0})
    docs = await cursor.to_list(length=1000)
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
    # life: no linkage

    validated_component_id: Optional[str] = None
    if body.component_id:
        comp = await db.knowledge_components.find_one({"id": body.component_id, "user_id": current_user["id"]})
        if not comp:
            raise HTTPException(status_code=400, detail="Invalid component_id")
        validated_component_id = comp["id"]

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
        "created_at": now,
        "updated_at": now,
    }
    await db.checkins.insert_one(doc)
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

    # Only active goals that have a schedulable cadence are candidates. We
    # filter out manual up front so the response is compact.
    goals = await db.goals.find(
        {
            "user_id": user_id,
            "status": "active",
            "checkin_cadence": {"$in": ["daily", "weekly", "monthly"]},
        },
        {"_id": 0, "id": 1, "title": 1, "domain_id": 1, "checkin_cadence": 1},
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

    # Pull every relevant checkin for the union of the three periods in one
    # trip. The daily bound is inside the weekly bound, which is inside the
    # month prefix — so a week-bounded date range covers all three.
    checkins = await db.checkins.find(
        {
            "user_id": user_id,
            "date": {"$gte": min(week_start_str, month_prefix + "-01"),
                     "$lte": max(week_end_str, month_prefix + "-31")},
            "$or": [
                {"goal_id": {"$in": goal_ids}},
                {"expected_outcome_id": {"$in": all_eo_ids}} if all_eo_ids else {"goal_id": None},
            ],
        },
        {"_id": 0, "goal_id": 1, "expected_outcome_id": 1, "date": 1},
    ).to_list(length=20000)

    # Build per-goal sets of the dates on which a check-in exists.
    goal_checkin_dates: dict = {gid: set() for gid in goal_ids}
    for c in checkins:
        gid = c.get("goal_id") or eo_to_goal.get(c.get("expected_outcome_id") or "")
        if not gid or gid not in goal_checkin_dates:
            continue
        d_val = c.get("date") or ""
        if d_val:
            goal_checkin_dates[gid].add(d_val)

    # Domain names in one lookup.
    domain_ids = list({g["domain_id"] for g in goals if g.get("domain_id")})
    domain_docs = await db.domains.find(
        {"user_id": user_id, "id": {"$in": domain_ids}}, {"_id": 0, "id": 1, "name": 1},
    ).to_list(length=1000) if domain_ids else []
    domain_name_by_id = {d["id"]: d["name"] for d in domain_docs}

    def _completed(gid: str, cadence: str) -> bool:
        dates = goal_checkin_dates.get(gid) or set()
        if cadence == "daily":
            return day_str in dates
        if cadence == "weekly":
            return any(week_start_str <= x <= week_end_str for x in dates)
        if cadence == "monthly":
            return any((x or "").startswith(month_prefix) for x in dates)
        return False

    cadence_rank = {"daily": 0, "weekly": 1, "monthly": 2}
    result = []
    for g in goals:
        cadence = g.get("checkin_cadence") or ""
        completed = _completed(g["id"], cadence)
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
    updates = {k: v for k, v in body.dict(exclude_unset=True).items() if v is not None}
    for k in ("title", "date", "time", "notes", "attachment"):
        if k in updates and isinstance(updates[k], str):
            updates[k] = updates[k].strip()
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.checkins.update_one({"id": checkin_id, "user_id": current_user["id"]}, {"$set": updates})
    updated = await db.checkins.find_one({"id": checkin_id}, {"_id": 0})
    return checkin_to_response(updated)


@api_router.delete("/checkins/{checkin_id}", status_code=200)
async def delete_checkin(checkin_id: str, current_user: dict = Depends(get_current_user)):
    result = await db.checkins.delete_one({"id": checkin_id, "user_id": current_user["id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Check-in not found")
    return {"detail": "Check-in deleted"}


# ---------- Outcome Type Registry Endpoint ----------
@api_router.get("/outcome-types")
async def get_outcome_types():
    """Returns the metadata-driven Expected Outcome type registry."""
    return {"types": OUTCOME_TYPE_REGISTRY}


# ============================================================================
# Knowledge Engine — Hierarchical (Journey → Stage → Component → …)
# ============================================================================
# The execution engine (Goal → Expected Outcome → Task → Check-in) is untouched
# and remains domain-agnostic. Knowledge-specific state lives in three separate
# collections:
#   * knowledge_journeys   — one row per Learning Journey, points at ONE Goal
#   * knowledge_stages     — optional level groupings inside a Journey
#   * knowledge_components — unlimited-depth tree of learning components
# Tasks and Check-ins may optionally attach to a component via component_id.
# The Goal, Task and Check-in engines gained only nullable foreign-key fields;
# their CRUD semantics did not change.

JOURNEY_TYPES = {
    "professional_qualification",
    "skill",
    "course",
    "subject",
    "book",
    "custom",
}
COMPONENT_STATUSES = {"not_started", "in_progress", "completed", "paused"}


class KnowledgeStageInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class KnowledgeFirstOutcome(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    target_value: str = ""
    unit: str = ""
    outcome_type: str = "generic"


class KnowledgeFirstTask(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    due_date: str = ""
    priority: str = "medium"


class KnowledgeJourneyCreate(BaseModel):
    # --- Knowledge hierarchy (steps 1-4) ---
    journey_type: str  # Step 1
    title: str = Field(min_length=1, max_length=200)  # Step 2
    has_stages: bool = False  # Step 3
    stages: List[KnowledgeStageInput] = Field(default_factory=list)  # Step 4 (if has_stages)
    # --- Execution engine (steps 5-9) ---
    why: str = Field(min_length=1, max_length=2000)  # Step 5
    target_completion_date: str = ""  # Step 6
    first_outcome: KnowledgeFirstOutcome  # Step 7 (required)
    first_task: KnowledgeFirstTask  # Step 8 (required)
    checkin_cadence: str  # Step 9: daily | weekly | monthly | manual


class KnowledgeJourneyUpdate(BaseModel):
    journey_type: Optional[str] = None
    has_stages: Optional[bool] = None


class KnowledgeJourneyResponse(BaseModel):
    id: str
    goal_id: str
    journey_type: str
    has_stages: bool
    # Denormalised, read-only projections from the linked Goal for convenience —
    # the Goal remains the source of truth for execution data.
    title: str
    notes: str
    deadline: str
    status: str
    checkin_cadence: str
    domain_id: str
    domain_name: str
    expected_outcomes_total: int = 0
    expected_outcomes_completed: int = 0
    completion_pct: float = 0.0
    created_at: str
    updated_at: str


class KnowledgeStageCreate(BaseModel):
    journey_id: str
    name: str = Field(min_length=1, max_length=200)


class KnowledgeStageUpdate(BaseModel):
    name: Optional[str] = None


class KnowledgeStageResponse(BaseModel):
    id: str
    journey_id: str
    name: str
    sequence: int
    created_at: str
    updated_at: str


class KnowledgeComponentCreate(BaseModel):
    journey_id: str
    stage_id: Optional[str] = None
    parent_component_id: Optional[str] = None
    name: str = Field(min_length=1, max_length=200)
    type: str = ""  # user-supplied label — never hardcoded
    status: str = "not_started"
    progress: int = 0  # 0..100
    notes: str = ""


class KnowledgeComponentUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = None
    progress: Optional[int] = None
    notes: Optional[str] = None


class KnowledgeComponentResponse(BaseModel):
    id: str
    journey_id: str
    stage_id: Optional[str]
    parent_component_id: Optional[str]
    name: str
    type: str
    sequence: int
    status: str
    progress: int
    notes: str
    created_at: str
    updated_at: str


async def _get_or_create_knowledge_domain(user_id: str) -> dict:
    """Return the Knowledge domain for this user, seeding it if missing."""
    await ensure_default_domains(user_id)
    d = await db.domains.find_one({"user_id": user_id, "name": KNOWLEDGE_DOMAIN_NAME}, {"_id": 0})
    if d:
        return d
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "name": KNOWLEDGE_DOMAIN_NAME,
        "is_default": True,
        "created_at": now,
    }
    await db.domains.insert_one(doc)
    doc.pop("_id", None)
    return doc


async def _backfill_legacy_journeys(user_id: str, knowledge_domain_id: str) -> None:
    """Legacy compatibility.

    Prior Knowledge Journeys were stored as plain Goals in the Knowledge domain
    with no `knowledge_journeys` row. On any read call we lazily upsert a
    default row so those journeys continue to appear. Idempotent.
    """
    goal_ids = {
        g["id"]
        for g in await db.goals.find(
            {"user_id": user_id, "domain_id": knowledge_domain_id}, {"_id": 0, "id": 1}
        ).to_list(length=5000)
    }
    if not goal_ids:
        return
    existing = {
        j["goal_id"]
        for j in await db.knowledge_journeys.find(
            {"user_id": user_id, "goal_id": {"$in": list(goal_ids)}},
            {"_id": 0, "goal_id": 1},
        ).to_list(length=5000)
    }
    missing = [gid for gid in goal_ids if gid not in existing]
    if not missing:
        return
    now = datetime.now(timezone.utc).isoformat()
    docs = [
        {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "goal_id": gid,
            "journey_type": "",
            "has_stages": False,
            "created_at": now,
            "updated_at": now,
        }
        for gid in missing
    ]
    await db.knowledge_journeys.insert_many(docs)


def _journey_to_response(j: dict, goal: dict, domain_name: str, stats: dict) -> KnowledgeJourneyResponse:
    total = int(stats.get("total", 0))
    completed = int(stats.get("completed", 0))
    pct = round((completed / total) * 100, 1) if total > 0 else 0.0
    return KnowledgeJourneyResponse(
        id=j["id"],
        goal_id=j["goal_id"],
        journey_type=j.get("journey_type", "") or "",
        has_stages=bool(j.get("has_stages", False)),
        title=goal.get("title", ""),
        notes=goal.get("notes", "") or "",
        deadline=goal.get("deadline", "") or "",
        status=goal.get("status", "active"),
        checkin_cadence=goal.get("checkin_cadence", "") or "",
        domain_id=goal.get("domain_id", ""),
        domain_name=domain_name,
        expected_outcomes_total=total,
        expected_outcomes_completed=completed,
        completion_pct=pct,
        created_at=j.get("created_at", ""),
        updated_at=j.get("updated_at", ""),
    )


def _stage_to_response(s: dict) -> KnowledgeStageResponse:
    return KnowledgeStageResponse(
        id=s["id"],
        journey_id=s["journey_id"],
        name=s.get("name", ""),
        sequence=int(s.get("sequence", 0)),
        created_at=s.get("created_at", ""),
        updated_at=s.get("updated_at", ""),
    )


def _component_to_response(c: dict) -> KnowledgeComponentResponse:
    return KnowledgeComponentResponse(
        id=c["id"],
        journey_id=c["journey_id"],
        stage_id=c.get("stage_id"),
        parent_component_id=c.get("parent_component_id"),
        name=c.get("name", ""),
        type=c.get("type", "") or "",
        sequence=int(c.get("sequence", 0)),
        status=c.get("status", "not_started"),
        progress=int(c.get("progress", 0)),
        notes=c.get("notes", "") or "",
        created_at=c.get("created_at", ""),
        updated_at=c.get("updated_at", ""),
    )


async def _get_own_journey(user_id: str, journey_id: str) -> dict:
    j = await db.knowledge_journeys.find_one({"id": journey_id, "user_id": user_id}, {"_id": 0})
    if not j:
        raise HTTPException(status_code=404, detail="Knowledge journey not found")
    return j


async def _next_sequence(collection, filter_q: dict) -> int:
    top = await collection.find(filter_q, {"_id": 0, "sequence": 1}).sort("sequence", -1).limit(1).to_list(length=1)
    return (int(top[0]["sequence"]) + 1) if top else 0


async def _cascade_delete_component(user_id: str, component_id: str) -> None:
    """Delete this component and every descendant. Also detaches Tasks/Check-ins."""
    stack = [component_id]
    to_delete: List[str] = []
    while stack:
        current = stack.pop()
        to_delete.append(current)
        children = await db.knowledge_components.find(
            {"user_id": user_id, "parent_component_id": current}, {"_id": 0, "id": 1}
        ).to_list(length=1000)
        stack.extend(c["id"] for c in children)
    if to_delete:
        await db.knowledge_components.delete_many({"user_id": user_id, "id": {"$in": to_delete}})
        # Detach (do NOT delete) linked tasks and check-ins.
        await db.tasks.update_many(
            {"user_id": user_id, "component_id": {"$in": to_delete}},
            {"$set": {"component_id": None}},
        )
        await db.checkins.update_many(
            {"user_id": user_id, "component_id": {"$in": to_delete}},
            {"$set": {"component_id": None}},
        )


# ---------------------- Knowledge Journey Routes ----------------------
@api_router.get("/knowledge/journeys", response_model=List[KnowledgeJourneyResponse])
async def list_knowledge_journeys(current_user: dict = Depends(get_current_user)):
    domain = await _get_or_create_knowledge_domain(current_user["id"])
    await _backfill_legacy_journeys(current_user["id"], domain["id"])
    journeys = await db.knowledge_journeys.find(
        {"user_id": current_user["id"]}, {"_id": 0}
    ).to_list(length=1000)
    if not journeys:
        return []
    goal_ids = [j["goal_id"] for j in journeys]
    goals = {
        g["id"]: g
        for g in await db.goals.find(
            {"user_id": current_user["id"], "id": {"$in": goal_ids}}, {"_id": 0}
        ).to_list(length=1000)
    }
    journeys.sort(key=lambda j: j.get("created_at", ""), reverse=True)
    result = []
    for j in journeys:
        goal = goals.get(j["goal_id"])
        if not goal:
            continue  # Orphan journey — skip silently.
        stats = await compute_goal_stats(current_user["id"], goal["id"])
        result.append(_journey_to_response(j, goal, domain["name"], stats))
    return result


@api_router.post("/knowledge/journeys", response_model=KnowledgeJourneyResponse, status_code=201)
async def create_knowledge_journey(
    body: KnowledgeJourneyCreate, current_user: dict = Depends(get_current_user)
):
    """Atomic wizard: KnowledgeJourney + Goal + optional Stages + first EO + first Task."""
    # -- Validate -----------------------------------------------------------
    if body.journey_type not in JOURNEY_TYPES:
        raise HTTPException(status_code=400, detail=f"journey_type must be one of {sorted(JOURNEY_TYPES)}")
    if body.checkin_cadence not in CHECKIN_CADENCES:
        raise HTTPException(status_code=400, detail=f"checkin_cadence must be one of {sorted(CHECKIN_CADENCES)}")
    outcome_type = body.first_outcome.outcome_type or "generic"
    if outcome_type not in OUTCOME_TYPE_REGISTRY:
        raise HTTPException(status_code=400, detail=f"Invalid outcome_type '{outcome_type}'")
    priority = body.first_task.priority or "medium"
    if priority not in TASK_PRIORITIES:
        raise HTTPException(status_code=400, detail=f"Task priority must be one of {sorted(TASK_PRIORITIES)}")
    if body.has_stages and len(body.stages) == 0:
        raise HTTPException(status_code=400, detail="At least one stage is required when has_stages is true")

    domain = await _get_or_create_knowledge_domain(current_user["id"])
    now = datetime.now(timezone.utc).isoformat()

    # -- Prepare docs (no writes yet) --------------------------------------
    goal_id = str(uuid.uuid4())
    goal_doc = {
        "id": goal_id, "user_id": current_user["id"],
        "title": body.title.strip(), "domain_id": domain["id"],
        "target_outcome": "", "deadline": (body.target_completion_date or "").strip(),
        "status": "active", "notes": body.why.strip(),
        "checkin_cadence": body.checkin_cadence,
        "created_at": now, "updated_at": now,
    }
    journey_id = str(uuid.uuid4())
    journey_doc = {
        "id": journey_id, "user_id": current_user["id"], "goal_id": goal_id,
        "journey_type": body.journey_type, "has_stages": body.has_stages,
        "created_at": now, "updated_at": now,
    }
    stage_docs = [
        {
            "id": str(uuid.uuid4()), "user_id": current_user["id"], "journey_id": journey_id,
            "name": s.name.strip(), "sequence": i,
            "created_at": now, "updated_at": now,
        }
        for i, s in enumerate(body.stages)
    ] if body.has_stages else []
    eo_id = str(uuid.uuid4())
    eo_doc = {
        "id": eo_id, "user_id": current_user["id"], "goal_id": goal_id,
        "title": body.first_outcome.title.strip(),
        "target_value": (body.first_outcome.target_value or "").strip(),
        "current_value": "", "unit": (body.first_outcome.unit or "").strip(),
        "deadline": "", "status": "active", "notes": "",
        "outcome_type": outcome_type,
        "created_at": now, "updated_at": now,
    }
    task_doc = {
        "id": str(uuid.uuid4()), "user_id": current_user["id"],
        "title": body.first_task.title.strip(),
        "due_date": (body.first_task.due_date or "").strip(),
        "priority": priority, "status": "todo", "notes": "",
        "origin": "expected_outcome", "expected_outcome_id": eo_id,
        "project_id": None, "component_id": None,
        "assigned_to_type": "self", "assigned_to_name": "", "assigned_to_phone": "",
        "created_at": now, "updated_at": now,
    }

    # -- Persist with cascading rollback -----------------------------------
    # Track each insertion so we can roll back in reverse order on failure.
    # Each entry is a tuple (collection, filter, is_many).
    inserted: List[tuple] = []
    try:
        await db.goals.insert_one(goal_doc); inserted.append((db.goals, {"id": goal_id}, False))
        await db.knowledge_journeys.insert_one(journey_doc); inserted.append((db.knowledge_journeys, {"id": journey_id}, False))
        if stage_docs:
            await db.knowledge_stages.insert_many(stage_docs)
            inserted.append((db.knowledge_stages, {"id": {"$in": [s["id"] for s in stage_docs]}}, True))
        await db.expected_outcomes.insert_one(eo_doc); inserted.append((db.expected_outcomes, {"id": eo_id}, False))
        await db.tasks.insert_one(task_doc); inserted.append((db.tasks, {"id": task_doc["id"]}, False))
    except Exception:
        for coll, f, is_many in reversed(inserted):
            try:
                if is_many:
                    await coll.delete_many(f)
                else:
                    await coll.delete_one(f)
            except Exception:
                pass
        raise

    journey_doc.pop("_id", None); goal_doc.pop("_id", None)
    return _journey_to_response(journey_doc, goal_doc, domain["name"], {"total": 1, "completed": 0})


@api_router.get("/knowledge/journeys/{journey_id}", response_model=KnowledgeJourneyResponse)
async def get_knowledge_journey(journey_id: str, current_user: dict = Depends(get_current_user)):
    domain = await _get_or_create_knowledge_domain(current_user["id"])
    await _backfill_legacy_journeys(current_user["id"], domain["id"])
    j = await _get_own_journey(current_user["id"], journey_id)
    goal = await db.goals.find_one({"id": j["goal_id"], "user_id": current_user["id"]}, {"_id": 0})
    if not goal:
        raise HTTPException(status_code=404, detail="Underlying goal missing")
    stats = await compute_goal_stats(current_user["id"], goal["id"])
    return _journey_to_response(j, goal, domain["name"], stats)


@api_router.put("/knowledge/journeys/{journey_id}", response_model=KnowledgeJourneyResponse)
async def update_knowledge_journey(
    journey_id: str, body: KnowledgeJourneyUpdate, current_user: dict = Depends(get_current_user)
):
    j = await _get_own_journey(current_user["id"], journey_id)
    updates = {k: v for k, v in body.dict(exclude_unset=True).items() if v is not None}
    if "journey_type" in updates and updates["journey_type"] not in JOURNEY_TYPES:
        raise HTTPException(status_code=400, detail=f"journey_type must be one of {sorted(JOURNEY_TYPES)}")
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.knowledge_journeys.update_one({"id": journey_id, "user_id": current_user["id"]}, {"$set": updates})
    updated = await db.knowledge_journeys.find_one({"id": journey_id}, {"_id": 0})
    goal = await db.goals.find_one({"id": j["goal_id"]}, {"_id": 0})
    domain = await _get_or_create_knowledge_domain(current_user["id"])
    stats = await compute_goal_stats(current_user["id"], goal["id"])
    return _journey_to_response(updated, goal, domain["name"], stats)


@api_router.delete("/knowledge/journeys/{journey_id}", status_code=200)
async def delete_knowledge_journey(journey_id: str, current_user: dict = Depends(get_current_user)):
    j = await _get_own_journey(current_user["id"], journey_id)
    # Cascade: components (which cascades tasks/checkins detach), stages, journey, goal.
    comps = await db.knowledge_components.find(
        {"user_id": current_user["id"], "journey_id": journey_id}, {"_id": 0, "id": 1}
    ).to_list(length=5000)
    if comps:
        comp_ids = [c["id"] for c in comps]
        await db.knowledge_components.delete_many({"user_id": current_user["id"], "id": {"$in": comp_ids}})
        await db.tasks.update_many(
            {"user_id": current_user["id"], "component_id": {"$in": comp_ids}},
            {"$set": {"component_id": None}},
        )
        await db.checkins.update_many(
            {"user_id": current_user["id"], "component_id": {"$in": comp_ids}},
            {"$set": {"component_id": None}},
        )
    await db.knowledge_stages.delete_many({"user_id": current_user["id"], "journey_id": journey_id})
    await db.knowledge_journeys.delete_one({"id": journey_id, "user_id": current_user["id"]})
    # Before deleting the goal + its EOs, detach any tasks/check-ins that referenced them
    # so those rows don't end up with dangling foreign keys.
    eos = await db.expected_outcomes.find(
        {"user_id": current_user["id"], "goal_id": j["goal_id"]}, {"_id": 0, "id": 1}
    ).to_list(length=5000)
    if eos:
        eo_ids = [e["id"] for e in eos]
        await db.tasks.update_many(
            {"user_id": current_user["id"], "expected_outcome_id": {"$in": eo_ids}},
            {"$set": {"expected_outcome_id": None, "origin": "standalone"}},
        )
        await db.checkins.update_many(
            {"user_id": current_user["id"], "expected_outcome_id": {"$in": eo_ids}},
            {"$set": {"expected_outcome_id": None}},
        )
    # Also detach check-ins that referenced the goal directly.
    await db.checkins.update_many(
        {"user_id": current_user["id"], "goal_id": j["goal_id"]},
        {"$set": {"goal_id": None}},
    )
    await db.goals.delete_one({"id": j["goal_id"], "user_id": current_user["id"]})
    await db.expected_outcomes.delete_many({"user_id": current_user["id"], "goal_id": j["goal_id"]})
    return {"detail": "Knowledge journey deleted"}


# ---------------------- Knowledge Stage Routes ----------------------
@api_router.get("/knowledge/journeys/{journey_id}/stages", response_model=List[KnowledgeStageResponse])
async def list_stages(journey_id: str, current_user: dict = Depends(get_current_user)):
    await _get_own_journey(current_user["id"], journey_id)
    docs = await db.knowledge_stages.find(
        {"user_id": current_user["id"], "journey_id": journey_id}, {"_id": 0}
    ).to_list(length=1000)
    docs.sort(key=lambda s: int(s.get("sequence", 0)))
    return [_stage_to_response(d) for d in docs]


@api_router.post("/knowledge/stages", response_model=KnowledgeStageResponse, status_code=201)
async def create_stage(body: KnowledgeStageCreate, current_user: dict = Depends(get_current_user)):
    await _get_own_journey(current_user["id"], body.journey_id)
    now = datetime.now(timezone.utc).isoformat()
    seq = await _next_sequence(db.knowledge_stages, {"user_id": current_user["id"], "journey_id": body.journey_id})
    doc = {
        "id": str(uuid.uuid4()), "user_id": current_user["id"], "journey_id": body.journey_id,
        "name": body.name.strip(), "sequence": seq,
        "created_at": now, "updated_at": now,
    }
    await db.knowledge_stages.insert_one(doc)
    doc.pop("_id", None)
    return _stage_to_response(doc)


@api_router.put("/knowledge/stages/{stage_id}", response_model=KnowledgeStageResponse)
async def update_stage(stage_id: str, body: KnowledgeStageUpdate, current_user: dict = Depends(get_current_user)):
    s = await db.knowledge_stages.find_one({"id": stage_id, "user_id": current_user["id"]})
    if not s:
        raise HTTPException(status_code=404, detail="Stage not found")
    updates = {k: v.strip() if isinstance(v, str) else v for k, v in body.dict(exclude_unset=True).items() if v is not None}
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.knowledge_stages.update_one({"id": stage_id, "user_id": current_user["id"]}, {"$set": updates})
    updated = await db.knowledge_stages.find_one({"id": stage_id}, {"_id": 0})
    return _stage_to_response(updated)


@api_router.delete("/knowledge/stages/{stage_id}", status_code=200)
async def delete_stage(stage_id: str, current_user: dict = Depends(get_current_user)):
    s = await db.knowledge_stages.find_one({"id": stage_id, "user_id": current_user["id"]})
    if not s:
        raise HTTPException(status_code=404, detail="Stage not found")
    # Cascade: delete every component whose stage_id is this stage (and their descendants).
    top_level = await db.knowledge_components.find(
        {"user_id": current_user["id"], "stage_id": stage_id, "parent_component_id": None},
        {"_id": 0, "id": 1},
    ).to_list(length=1000)
    for c in top_level:
        await _cascade_delete_component(current_user["id"], c["id"])
    # Anything still attached (nested rows directly under the stage without top parent) — nuke.
    await db.knowledge_components.delete_many({"user_id": current_user["id"], "stage_id": stage_id})
    await db.knowledge_stages.delete_one({"id": stage_id, "user_id": current_user["id"]})
    return {"detail": "Stage deleted"}


@api_router.post("/knowledge/stages/{stage_id}/move")
async def move_stage(stage_id: str, direction: str, current_user: dict = Depends(get_current_user)):
    if direction not in {"up", "down"}:
        raise HTTPException(status_code=400, detail="direction must be 'up' or 'down'")
    s = await db.knowledge_stages.find_one({"id": stage_id, "user_id": current_user["id"]})
    if not s:
        raise HTTPException(status_code=404, detail="Stage not found")
    siblings = await db.knowledge_stages.find(
        {"user_id": current_user["id"], "journey_id": s["journey_id"]}, {"_id": 0}
    ).to_list(length=1000)
    siblings.sort(key=lambda x: int(x.get("sequence", 0)))
    idx = next((i for i, x in enumerate(siblings) if x["id"] == stage_id), -1)
    swap_idx = idx - 1 if direction == "up" else idx + 1
    if idx < 0 or swap_idx < 0 or swap_idx >= len(siblings):
        return {"detail": "No move"}
    a, b = siblings[idx], siblings[swap_idx]
    now = datetime.now(timezone.utc).isoformat()
    await db.knowledge_stages.update_one({"id": a["id"]}, {"$set": {"sequence": b["sequence"], "updated_at": now}})
    await db.knowledge_stages.update_one({"id": b["id"]}, {"$set": {"sequence": a["sequence"], "updated_at": now}})
    return {"detail": "moved"}


# ---------------------- Knowledge Component Routes ----------------------
@api_router.get("/knowledge/journeys/{journey_id}/components", response_model=List[KnowledgeComponentResponse])
async def list_components(journey_id: str, current_user: dict = Depends(get_current_user)):
    await _get_own_journey(current_user["id"], journey_id)
    docs = await db.knowledge_components.find(
        {"user_id": current_user["id"], "journey_id": journey_id}, {"_id": 0}
    ).to_list(length=5000)
    docs.sort(key=lambda c: int(c.get("sequence", 0)))
    return [_component_to_response(d) for d in docs]


@api_router.post("/knowledge/components", response_model=KnowledgeComponentResponse, status_code=201)
async def create_component(body: KnowledgeComponentCreate, current_user: dict = Depends(get_current_user)):
    await _get_own_journey(current_user["id"], body.journey_id)
    if body.status not in COMPONENT_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {sorted(COMPONENT_STATUSES)}")
    if body.progress < 0 or body.progress > 100:
        raise HTTPException(status_code=400, detail="progress must be between 0 and 100")
    if body.stage_id:
        st = await db.knowledge_stages.find_one({"id": body.stage_id, "user_id": current_user["id"], "journey_id": body.journey_id})
        if not st:
            raise HTTPException(status_code=400, detail="Invalid stage_id")
    if body.parent_component_id:
        pc = await db.knowledge_components.find_one({"id": body.parent_component_id, "user_id": current_user["id"], "journey_id": body.journey_id})
        if not pc:
            raise HTTPException(status_code=400, detail="Invalid parent_component_id")
        # A child inherits the parent's stage_id.
        body.stage_id = pc.get("stage_id")
    seq = await _next_sequence(
        db.knowledge_components,
        {
            "user_id": current_user["id"], "journey_id": body.journey_id,
            "stage_id": body.stage_id, "parent_component_id": body.parent_component_id,
        },
    )
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": str(uuid.uuid4()), "user_id": current_user["id"], "journey_id": body.journey_id,
        "stage_id": body.stage_id, "parent_component_id": body.parent_component_id,
        "name": body.name.strip(), "type": (body.type or "").strip(),
        "sequence": seq, "status": body.status, "progress": int(body.progress),
        "notes": (body.notes or "").strip(),
        "created_at": now, "updated_at": now,
    }
    await db.knowledge_components.insert_one(doc)
    doc.pop("_id", None)
    return _component_to_response(doc)


@api_router.put("/knowledge/components/{component_id}", response_model=KnowledgeComponentResponse)
async def update_component(component_id: str, body: KnowledgeComponentUpdate, current_user: dict = Depends(get_current_user)):
    c = await db.knowledge_components.find_one({"id": component_id, "user_id": current_user["id"]})
    if not c:
        raise HTTPException(status_code=404, detail="Component not found")
    updates = {k: v for k, v in body.dict(exclude_unset=True).items() if v is not None}
    if "status" in updates and updates["status"] not in COMPONENT_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {sorted(COMPONENT_STATUSES)}")
    if "progress" in updates and not (0 <= int(updates["progress"]) <= 100):
        raise HTTPException(status_code=400, detail="progress must be between 0 and 100")
    for k in ("name", "type", "notes"):
        if k in updates and isinstance(updates[k], str):
            updates[k] = updates[k].strip()
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.knowledge_components.update_one({"id": component_id, "user_id": current_user["id"]}, {"$set": updates})
    updated = await db.knowledge_components.find_one({"id": component_id}, {"_id": 0})
    return _component_to_response(updated)


@api_router.delete("/knowledge/components/{component_id}", status_code=200)
async def delete_component(component_id: str, current_user: dict = Depends(get_current_user)):
    c = await db.knowledge_components.find_one({"id": component_id, "user_id": current_user["id"]})
    if not c:
        raise HTTPException(status_code=404, detail="Component not found")
    await _cascade_delete_component(current_user["id"], component_id)
    return {"detail": "Component deleted"}


@api_router.post("/knowledge/components/{component_id}/move")
async def move_component(component_id: str, direction: str, current_user: dict = Depends(get_current_user)):
    if direction not in {"up", "down"}:
        raise HTTPException(status_code=400, detail="direction must be 'up' or 'down'")
    c = await db.knowledge_components.find_one({"id": component_id, "user_id": current_user["id"]})
    if not c:
        raise HTTPException(status_code=404, detail="Component not found")
    siblings = await db.knowledge_components.find(
        {
            "user_id": current_user["id"],
            "journey_id": c["journey_id"],
            "stage_id": c.get("stage_id"),
            "parent_component_id": c.get("parent_component_id"),
        },
        {"_id": 0},
    ).to_list(length=1000)
    siblings.sort(key=lambda x: int(x.get("sequence", 0)))
    idx = next((i for i, x in enumerate(siblings) if x["id"] == component_id), -1)
    swap_idx = idx - 1 if direction == "up" else idx + 1
    if idx < 0 or swap_idx < 0 or swap_idx >= len(siblings):
        return {"detail": "No move"}
    a, b = siblings[idx], siblings[swap_idx]
    now = datetime.now(timezone.utc).isoformat()
    await db.knowledge_components.update_one({"id": a["id"]}, {"$set": {"sequence": b["sequence"], "updated_at": now}})
    await db.knowledge_components.update_one({"id": b["id"]}, {"$set": {"sequence": a["sequence"], "updated_at": now}})
    return {"detail": "moved"}


# ---------- App wiring ----------
# Portfolio Manager — imported here (after db/get_current_user are defined) to
# avoid a circular import. It owns CRUD for its four collections and exposes
# derived time/money calculations under /api/portfolio/*.
from portfolio_manager import portfolio_router, ensure_portfolio_indexes  # noqa: E402

api_router.include_router(portfolio_router)
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


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
