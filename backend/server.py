from fastapi import FastAPI, APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
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


class GoalCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    domain_id: str
    target_outcome: str = ""
    deadline: str = ""  # YYYY-MM-DD (optional)
    status: str = "active"
    notes: str = ""


class GoalUpdate(BaseModel):
    title: Optional[str] = None
    domain_id: Optional[str] = None
    target_outcome: Optional[str] = None
    deadline: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class GoalResponse(BaseModel):
    id: str
    title: str
    domain_id: str
    domain_name: str
    target_outcome: str
    deadline: str
    status: str
    notes: str
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
    assigned_to_type: str = "self"
    assigned_to_name: str = ""
    assigned_to_phone: str = ""


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    due_date: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
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
    follow_up_task: Optional[FollowUpTask] = None
    source: str = "manual"
    data: dict = Field(default_factory=dict)  # type-specific dynamic fields


class CheckInUpdate(BaseModel):
    title: Optional[str] = None
    date: Optional[str] = None
    time: Optional[str] = None
    notes: Optional[str] = None
    attachment: Optional[str] = None
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
        follow_up_task_id=c.get("follow_up_task_id"),
        source=c.get("source", "manual"),
        outcome_type=c.get("outcome_type"),
        data=c.get("data") or {},
        created_at=c.get("created_at", ""),
        updated_at=c.get("updated_at", ""),
    )


async def ensure_default_domains(user_id: str) -> None:
    existing = await db.domains.count_documents({"user_id": user_id})
    if existing > 0:
        return
    now = datetime.now(timezone.utc).isoformat()
    docs = [
        {"id": str(uuid.uuid4()), "user_id": user_id, "name": name, "is_default": True, "created_at": now}
        for name in DEFAULT_DOMAIN_NAMES
    ]
    if docs:
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
    if "domain_id" in updates:
        d = await db.domains.find_one({"id": updates["domain_id"], "user_id": current_user["id"]})
        if not d:
            raise HTTPException(status_code=400, detail="Invalid domain")
    for k in ("title", "target_outcome", "deadline", "notes"):
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
async def list_tasks(current_user: dict = Depends(get_current_user)):
    q: dict = {"user_id": current_user["id"]}
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
async def list_checkins(current_user: dict = Depends(get_current_user)):
    cursor = db.checkins.find({"user_id": current_user["id"]}, {"_id": 0})
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


# ---------- Learning Journey ----------
LEARNING_JOURNEY_STATUSES = {"active", "archived"}


class LearningJourneyCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    target_completion_date: str = ""  # YYYY-MM-DD (optional)


class LearningJourneyUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    target_completion_date: Optional[str] = None
    status: Optional[str] = None


class LearningJourneyResponse(BaseModel):
    id: str
    title: str
    description: str
    target_completion_date: str
    status: str
    created_at: str
    updated_at: str


def learning_journey_to_response(j: dict) -> LearningJourneyResponse:
    return LearningJourneyResponse(
        id=j["id"],
        title=j.get("title", ""),
        description=j.get("description", "") or "",
        target_completion_date=j.get("target_completion_date", "") or "",
        status=j.get("status", "active"),
        created_at=j.get("created_at", ""),
        updated_at=j.get("updated_at", ""),
    )


# ---------- Outcome Type Registry Endpoint ----------
@api_router.get("/outcome-types")
async def get_outcome_types():
    """Returns the metadata-driven Expected Outcome type registry."""
    return {"types": OUTCOME_TYPE_REGISTRY}


# ---------- Learning Journey Routes ----------
@api_router.get("/learning-journeys", response_model=List[LearningJourneyResponse])
async def list_learning_journeys(current_user: dict = Depends(get_current_user)):
    cursor = db.learning_journeys.find({"user_id": current_user["id"]}, {"_id": 0})
    docs = await cursor.to_list(length=1000)
    docs.sort(key=lambda j: j.get("created_at", ""), reverse=True)
    return [learning_journey_to_response(d) for d in docs]


@api_router.post("/learning-journeys", response_model=LearningJourneyResponse, status_code=201)
async def create_learning_journey(body: LearningJourneyCreate, current_user: dict = Depends(get_current_user)):
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": current_user["id"],
        "title": body.title.strip(),
        "description": (body.description or "").strip(),
        "target_completion_date": (body.target_completion_date or "").strip(),
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }
    await db.learning_journeys.insert_one(doc)
    doc.pop("_id", None)
    return learning_journey_to_response(doc)


@api_router.get("/learning-journeys/{journey_id}", response_model=LearningJourneyResponse)
async def get_learning_journey(journey_id: str, current_user: dict = Depends(get_current_user)):
    doc = await db.learning_journeys.find_one({"id": journey_id, "user_id": current_user["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Learning journey not found")
    return learning_journey_to_response(doc)


@api_router.put("/learning-journeys/{journey_id}", response_model=LearningJourneyResponse)
async def update_learning_journey(journey_id: str, body: LearningJourneyUpdate, current_user: dict = Depends(get_current_user)):
    j = await db.learning_journeys.find_one({"id": journey_id, "user_id": current_user["id"]})
    if not j:
        raise HTTPException(status_code=404, detail="Learning journey not found")
    updates = {k: v for k, v in body.dict(exclude_unset=True).items() if v is not None}
    if "status" in updates and updates["status"] not in LEARNING_JOURNEY_STATUSES:
        raise HTTPException(status_code=400, detail=f"Status must be one of {sorted(LEARNING_JOURNEY_STATUSES)}")
    for k in ("title", "description", "target_completion_date"):
        if k in updates and isinstance(updates[k], str):
            updates[k] = updates[k].strip()
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.learning_journeys.update_one({"id": journey_id, "user_id": current_user["id"]}, {"$set": updates})
    updated = await db.learning_journeys.find_one({"id": journey_id}, {"_id": 0})
    return learning_journey_to_response(updated)


@api_router.delete("/learning-journeys/{journey_id}", status_code=200)
async def delete_learning_journey(journey_id: str, current_user: dict = Depends(get_current_user)):
    result = await db.learning_journeys.delete_one({"id": journey_id, "user_id": current_user["id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Learning journey not found")
    return {"detail": "Learning journey deleted"}


# ---------- App wiring ----------
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


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
