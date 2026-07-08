"""Backend integration tests for Hymn API - Auth + Events."""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://personal-os-app-8.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

TS = int(time.time())
USER_A_EMAIL = f"autotest+a{TS}@hymn.app"
USER_B_EMAIL = f"autotest+b{TS}@hymn.app"
PASSWORD = "TestPass123!"
NEW_PASSWORD = "NewPass456!"
SEC_Q = "What is your favorite color?"
SEC_A = "blue"


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def state():
    return {}


# ---------- Auth ----------
class TestAuth:
    def test_root(self, session):
        r = session.get(f"{API}/")
        assert r.status_code == 200
        assert "message" in r.json()

    def test_signup_user_a(self, session, state):
        r = session.post(f"{API}/auth/signup", json={
            "email": USER_A_EMAIL, "password": PASSWORD,
            "security_question": SEC_Q, "security_answer": SEC_A,
        })
        assert r.status_code == 201, r.text
        data = r.json()
        assert "access_token" in data and data["token_type"] == "bearer"
        assert data["user"]["email"] == USER_A_EMAIL
        assert data["user"]["id"]
        state["token_a"] = data["access_token"]
        state["user_a_id"] = data["user"]["id"]

    def test_signup_user_b(self, session, state):
        r = session.post(f"{API}/auth/signup", json={
            "email": USER_B_EMAIL, "password": PASSWORD,
            "security_question": SEC_Q, "security_answer": SEC_A,
        })
        assert r.status_code == 201, r.text
        state["token_b"] = r.json()["access_token"]

    def test_signup_duplicate(self, session):
        r = session.post(f"{API}/auth/signup", json={
            "email": USER_A_EMAIL, "password": PASSWORD,
            "security_question": SEC_Q, "security_answer": SEC_A,
        })
        assert r.status_code == 400

    def test_login_correct(self, session, state):
        r = session.post(f"{API}/auth/login", json={"email": USER_A_EMAIL, "password": PASSWORD})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["access_token"]
        assert data["user"]["email"] == USER_A_EMAIL
        state["token_a"] = data["access_token"]

    def test_login_wrong_password(self, session):
        r = session.post(f"{API}/auth/login", json={"email": USER_A_EMAIL, "password": "WrongPass!"})
        assert r.status_code == 400

    def test_me_requires_token(self, session):
        r = session.get(f"{API}/auth/me")
        assert r.status_code == 401

    def test_me_with_token(self, session, state):
        r = session.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {state['token_a']}"})
        assert r.status_code == 200
        assert r.json()["email"] == USER_A_EMAIL

    def test_security_question_existing(self, session):
        r = session.post(f"{API}/auth/security-question", json={"email": USER_A_EMAIL})
        assert r.status_code == 200
        assert r.json()["security_question"] == SEC_Q

    def test_security_question_unknown(self, session):
        r = session.post(f"{API}/auth/security-question", json={"email": f"nope+{TS}@hymn.app"})
        assert r.status_code == 200
        # Generic response, does not leak existence
        assert r.json()["security_question"] and r.json()["security_question"] != SEC_Q

    def test_forgot_password_wrong_answer(self, session):
        r = session.post(f"{API}/auth/forgot-password", json={
            "email": USER_A_EMAIL, "security_answer": "green", "new_password": NEW_PASSWORD,
        })
        assert r.status_code == 400

    def test_forgot_password_correct(self, session):
        r = session.post(f"{API}/auth/forgot-password", json={
            "email": USER_A_EMAIL, "security_answer": SEC_A, "new_password": NEW_PASSWORD,
        })
        assert r.status_code == 200

    def test_login_with_new_password(self, session, state):
        r = session.post(f"{API}/auth/login", json={"email": USER_A_EMAIL, "password": NEW_PASSWORD})
        assert r.status_code == 200
        state["token_a"] = r.json()["access_token"]

    def test_logout(self, session, state):
        r = session.post(f"{API}/auth/logout", headers={"Authorization": f"Bearer {state['token_a']}"})
        assert r.status_code == 200


# ---------- Events CRUD + isolation ----------
class TestEvents:
    def test_create_event(self, session, state):
        headers = {"Authorization": f"Bearer {state['token_a']}"}
        r = session.post(f"{API}/events", headers=headers, json={
            "type": "Meeting", "title": "TEST_Standup",
            "date": "2026-01-20", "time": "10:00", "notes": "hello",
        })
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["title"] == "TEST_Standup"
        assert data["type"] == "Meeting"
        assert data["id"]
        state["event_id"] = data["id"]

    def test_get_event(self, session, state):
        headers = {"Authorization": f"Bearer {state['token_a']}"}
        r = session.get(f"{API}/events/{state['event_id']}", headers=headers)
        assert r.status_code == 200
        assert r.json()["title"] == "TEST_Standup"

    def test_list_events(self, session, state):
        headers = {"Authorization": f"Bearer {state['token_a']}"}
        r = session.get(f"{API}/events", headers=headers)
        assert r.status_code == 200
        ids = [e["id"] for e in r.json()]
        assert state["event_id"] in ids

    def test_update_event(self, session, state):
        headers = {"Authorization": f"Bearer {state['token_a']}"}
        r = session.put(f"{API}/events/{state['event_id']}", headers=headers, json={
            "title": "TEST_Standup_v2", "notes": "updated",
        })
        assert r.status_code == 200
        assert r.json()["title"] == "TEST_Standup_v2"
        # Verify persistence via GET
        r2 = session.get(f"{API}/events/{state['event_id']}", headers=headers)
        assert r2.json()["title"] == "TEST_Standup_v2"
        assert r2.json()["notes"] == "updated"

    def test_isolation_user_b_cannot_get_a_event(self, session, state):
        headers = {"Authorization": f"Bearer {state['token_b']}"}
        r = session.get(f"{API}/events/{state['event_id']}", headers=headers)
        assert r.status_code == 404

    def test_isolation_user_b_list_empty(self, session, state):
        headers = {"Authorization": f"Bearer {state['token_b']}"}
        r = session.get(f"{API}/events", headers=headers)
        assert r.status_code == 200
        assert all(e["id"] != state["event_id"] for e in r.json())

    def test_events_require_auth(self, session):
        r = session.get(f"{API}/events")
        assert r.status_code == 401

    def test_get_nonexistent(self, session, state):
        headers = {"Authorization": f"Bearer {state['token_a']}"}
        r = session.get(f"{API}/events/{uuid.uuid4()}", headers=headers)
        assert r.status_code == 404
