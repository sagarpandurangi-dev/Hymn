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


class EventCreate(BaseModel):
    type: str = Field(min_length=1)
    title: str = Field(min_length=1)
    date: str  # YYYY-MM-DD
    time: str  # HH:MM
    notes: Optional[str] = ""


class EventUpdate(BaseModel):
    type: Optional[str] = None
    title: Optional[str] = None
    date: Optional[str] = None
    time: Optional[str] = None
    notes: Optional[str] = None


class EventResponse(BaseModel):
    id: str
    type: str
    title: str
    date: str
    time: str
    notes: str
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


def event_to_response(e: dict) -> EventResponse:
    return EventResponse(
        id=e["id"],
        type=e.get("type", ""),
        title=e.get("title", ""),
        date=e.get("date", ""),
        time=e.get("time", ""),
        notes=e.get("notes", "") or "",
        created_at=e.get("created_at", ""),
        updated_at=e.get("updated_at", ""),
    )


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


# ---------- Event Routes ----------
@api_router.get("/events", response_model=List[EventResponse])
async def list_events(current_user: dict = Depends(get_current_user)):
    cursor = db.events.find({"user_id": current_user["id"]}, {"_id": 0})
    docs = await cursor.to_list(length=1000)
    docs.sort(key=lambda e: (e.get("date", ""), e.get("time", "")), reverse=True)
    return [event_to_response(d) for d in docs]


@api_router.post("/events", response_model=EventResponse, status_code=201)
async def create_event(body: EventCreate, current_user: dict = Depends(get_current_user)):
    now = datetime.now(timezone.utc).isoformat()
    event_id = str(uuid.uuid4())
    doc = {
        "id": event_id,
        "user_id": current_user["id"],
        "type": body.type.strip(),
        "title": body.title.strip(),
        "date": body.date,
        "time": body.time,
        "notes": (body.notes or "").strip(),
        "created_at": now,
        "updated_at": now,
    }
    await db.events.insert_one(doc)
    doc.pop("_id", None)
    return event_to_response(doc)


@api_router.get("/events/{event_id}", response_model=EventResponse)
async def get_event(event_id: str, current_user: dict = Depends(get_current_user)):
    doc = await db.events.find_one({"id": event_id, "user_id": current_user["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Event not found")
    return event_to_response(doc)


@api_router.put("/events/{event_id}", response_model=EventResponse)
async def update_event(event_id: str, body: EventUpdate, current_user: dict = Depends(get_current_user)):
    doc = await db.events.find_one({"id": event_id, "user_id": current_user["id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Event not found")
    updates = {k: v for k, v in body.dict(exclude_unset=True).items() if v is not None}
    if "title" in updates:
        updates["title"] = updates["title"].strip()
    if "type" in updates:
        updates["type"] = updates["type"].strip()
    if "notes" in updates:
        updates["notes"] = updates["notes"].strip()
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.events.update_one({"id": event_id, "user_id": current_user["id"]}, {"$set": updates})
    updated = await db.events.find_one({"id": event_id}, {"_id": 0})
    return event_to_response(updated)


@api_router.delete("/events/{event_id}", status_code=200)
async def delete_event(event_id: str, current_user: dict = Depends(get_current_user)):
    result = await db.events.delete_one({"id": event_id, "user_id": current_user["id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Event not found")
    return {"detail": "Event deleted"}


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
