"""Backend tests for Google Auth addition and regressions."""
import os
import time
import uuid
import pytest
import requests
from datetime import datetime, timedelta, timezone
from pymongo import MongoClient

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "hymn_database")

TS = int(time.time())
JWT_USER_EMAIL = f"autotest+jwt{TS}@hymn.app"
GOOGLE_USER_EMAIL = f"autotest+google{TS}@hymn.app"
PASSWORD = "TestPass123!"


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def mongo():
    c = MongoClient(MONGO_URL)
    db = c[DB_NAME]
    yield db
    c.close()


@pytest.fixture(scope="module")
def state():
    return {}


# ---------- Google session validation (invalid/empty tokens) ----------
class TestGoogleSessionValidation:
    def test_invalid_session_token_returns_401(self, session):
        r = session.post(f"{API}/auth/google-session", json={"session_token": "definitely-not-a-real-session-xyz-123"})
        assert r.status_code == 401, r.text
        assert "Invalid Google session" in r.json().get("detail", "")

    def test_empty_session_token_returns_400(self, session):
        r = session.post(f"{API}/auth/google-session", json={"session_token": ""})
        assert r.status_code == 400, r.text

    def test_whitespace_session_token_returns_400(self, session):
        r = session.post(f"{API}/auth/google-session", json={"session_token": "   "})
        assert r.status_code == 400, r.text

    def test_missing_session_token_field_returns_422(self, session):
        # Pydantic validation error -> 422
        r = session.post(f"{API}/auth/google-session", json={})
        assert r.status_code == 422, r.text


# ---------- Regression: email/password JWT still works via get_current_user ----------
class TestEmailPasswordRegression:
    def test_signup_and_me(self, session, state):
        r = session.post(f"{API}/auth/signup", json={
            "email": JWT_USER_EMAIL, "password": PASSWORD,
            "security_question": "q?", "security_answer": "a",
        })
        assert r.status_code == 201, r.text
        state["jwt"] = r.json()["access_token"]
        state["jwt_user_id"] = r.json()["user"]["id"]

        r = session.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {state['jwt']}"})
        assert r.status_code == 200
        assert r.json()["email"] == JWT_USER_EMAIL
        assert r.json()["id"] == state["jwt_user_id"]

    def test_events_with_jwt(self, session, state):
        headers = {"Authorization": f"Bearer {state['jwt']}"}
        r = session.post(f"{API}/events", headers=headers, json={
            "type": "Note", "title": "TEST_jwt_regression",
            "date": "2026-01-20", "time": "09:00", "notes": "",
        })
        assert r.status_code == 201, r.text


# ---------- Simulated Google session via direct Mongo insert ----------
class TestSimulatedGoogleSession:
    def test_setup_google_user_and_session(self, mongo, state):
        user_id = str(uuid.uuid4())
        session_token = f"TEST_sess_{uuid.uuid4().hex}"
        now = datetime.now(timezone.utc)
        mongo.users.insert_one({
            "id": user_id,
            "email": GOOGLE_USER_EMAIL,
            "hashed_password": None,
            "security_question": None,
            "hashed_security_answer": None,
            "auth_provider": "google",
            "google_name": "Test Google User",
            "google_picture": None,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        })
        mongo.user_sessions.insert_one({
            "session_token": session_token,
            "user_id": user_id,
            "expires_at": now + timedelta(days=7),
            "created_at": now,
        })
        state["g_user_id"] = user_id
        state["g_token"] = session_token

    def test_me_with_session_token(self, session, state):
        r = session.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {state['g_token']}"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["email"] == GOOGLE_USER_EMAIL
        assert body["id"] == state["g_user_id"]

    def test_create_event_with_session_token(self, session, state):
        headers = {"Authorization": f"Bearer {state['g_token']}"}
        r = session.post(f"{API}/events", headers=headers, json={
            "type": "Meeting", "title": "TEST_google_event",
            "date": "2026-01-21", "time": "11:00", "notes": "via session_token",
        })
        assert r.status_code == 201, r.text
        state["g_event_id"] = r.json()["id"]

    def test_list_events_with_session_token(self, session, state):
        headers = {"Authorization": f"Bearer {state['g_token']}"}
        r = session.get(f"{API}/events", headers=headers)
        assert r.status_code == 200
        ids = [e["id"] for e in r.json()]
        assert state["g_event_id"] in ids

    def test_logout_deletes_session_row(self, session, mongo, state):
        headers = {"Authorization": f"Bearer {state['g_token']}"}
        r = session.post(f"{API}/auth/logout", headers=headers)
        assert r.status_code == 200
        # session row should be gone
        remaining = mongo.user_sessions.find_one({"session_token": state["g_token"]})
        assert remaining is None

    def test_me_after_logout_returns_401(self, session, state):
        r = session.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {state['g_token']}"})
        assert r.status_code == 401

    def test_cleanup(self, mongo, state):
        mongo.events.delete_many({"user_id": state.get("g_user_id")})
        mongo.users.delete_one({"id": state.get("g_user_id")})
        mongo.events.delete_many({"user_id": state.get("jwt_user_id")})
        mongo.users.delete_one({"id": state.get("jwt_user_id")})


# ---------- Startup indexes ----------
class TestStartupIndexes:
    def test_users_email_unique(self, mongo):
        idx = mongo.users.index_information()
        # find an index that covers 'email' and is unique
        found = False
        for name, spec in idx.items():
            keys = [k for k, _ in spec.get("key", [])]
            if "email" in keys and spec.get("unique"):
                found = True
                break
        assert found, f"users.email unique index missing. Got: {idx}"

    def test_user_sessions_session_token_unique(self, mongo):
        idx = mongo.user_sessions.index_information()
        found = False
        for name, spec in idx.items():
            keys = [k for k, _ in spec.get("key", [])]
            if "session_token" in keys and spec.get("unique"):
                found = True
                break
        assert found, f"user_sessions.session_token unique index missing. Got: {idx}"

    def test_user_sessions_ttl_on_expires_at(self, mongo):
        idx = mongo.user_sessions.index_information()
        found = False
        for name, spec in idx.items():
            keys = [k for k, _ in spec.get("key", [])]
            if "expires_at" in keys and "expireAfterSeconds" in spec:
                found = True
                break
        assert found, f"user_sessions TTL index on expires_at missing. Got: {idx}"
