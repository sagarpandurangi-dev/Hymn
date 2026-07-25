"""Provider-independent email/password and JWT authentication tests."""

import os
import time
import uuid

import pytest
import requests
from pymongo import MongoClient


BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
PASSWORD = "TestPass123!"


@pytest.fixture(scope="module")
def session():
    client = requests.Session()
    client.headers.update({"Content-Type": "application/json"})
    return client


@pytest.fixture(scope="module")
def mongo():
    client = MongoClient(MONGO_URL)
    database = client[DB_NAME]
    yield database
    client.close()


@pytest.fixture(scope="module")
def state():
    return {}


class TestEmailPasswordJwt:
    def test_signup_returns_jwt_and_user(self, session, state):
        email = f"TEST_auth_{time.time_ns()}@hymn.app"
        response = session.post(
            f"{API}/auth/signup",
            json={
                "email": email,
                "password": PASSWORD,
                "security_question": "Colour?",
                "security_answer": "Blue",
            },
            timeout=15,
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["token_type"] == "bearer"
        assert body["access_token"]
        assert body["user"]["email"] == email.lower()
        state.update(
            email=email.lower(),
            user_id=body["user"]["id"],
            token=body["access_token"],
        )

    def test_me_accepts_signup_jwt(self, session, state):
        response = session.get(
            f"{API}/auth/me",
            headers={"Authorization": f"Bearer {state['token']}"},
            timeout=15,
        )
        assert response.status_code == 200, response.text
        assert response.json()["id"] == state["user_id"]

    def test_login_returns_jwt(self, session, state):
        response = session.post(
            f"{API}/auth/login",
            json={"email": state["email"], "password": PASSWORD},
            timeout=15,
        )
        assert response.status_code == 200, response.text
        assert response.json()["access_token"]

    def test_incorrect_password_is_rejected(self, session, state):
        response = session.post(
            f"{API}/auth/login",
            json={"email": state["email"], "password": "wrong-password"},
            timeout=15,
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "Incorrect email or password"

    def test_logout_is_stateless_and_returns_success(self, session, state):
        headers = {"Authorization": f"Bearer {state['token']}"}
        response = session.post(f"{API}/auth/logout", headers=headers, timeout=15)
        assert response.status_code == 200, response.text
        assert response.json() == {"detail": "Logged out"}

        # The frontend completes JWT logout by deleting its stored token.
        still_valid = session.get(f"{API}/auth/me", headers=headers, timeout=15)
        assert still_valid.status_code == 200


class TestPasswordRecovery:
    def test_security_question_and_password_reset(self, session, state):
        question = session.post(
            f"{API}/auth/security-question",
            json={"email": state["email"]},
            timeout=15,
        )
        assert question.status_code == 200
        assert question.json()["security_question"] == "Colour?"

        wrong = session.post(
            f"{API}/auth/forgot-password",
            json={
                "email": state["email"],
                "security_answer": "wrong",
                "new_password": "NewTestPass123!",
            },
            timeout=15,
        )
        assert wrong.status_code == 400

        reset = session.post(
            f"{API}/auth/forgot-password",
            json={
                "email": state["email"],
                "security_answer": "BLUE",
                "new_password": "NewTestPass123!",
            },
            timeout=15,
        )
        assert reset.status_code == 200
        assert reset.json() == {"detail": "Password updated"}

        old_login = session.post(
            f"{API}/auth/login",
            json={"email": state["email"], "password": PASSWORD},
            timeout=15,
        )
        assert old_login.status_code == 400

        new_login = session.post(
            f"{API}/auth/login",
            json={"email": state["email"], "password": "NewTestPass123!"},
            timeout=15,
        )
        assert new_login.status_code == 200


class TestLegacyUserSafety:
    def test_null_password_hash_returns_controlled_401(self, session, mongo):
        user_id = str(uuid.uuid4())
        email = f"TEST_legacy_null_{time.time_ns()}@hymn.app".lower()
        now = "2026-01-01T00:00:00+00:00"
        mongo.users.insert_one(
            {
                "id": user_id,
                "email": email,
                "hashed_password": None,
                "security_question": None,
                "hashed_security_answer": None,
                "created_at": now,
                "updated_at": now,
            }
        )
        try:
            response = session.post(
                f"{API}/auth/login",
                json={"email": email, "password": PASSWORD},
                timeout=15,
            )
            assert response.status_code == 401, response.text
            assert response.json()["detail"] == "Incorrect email or password"
        finally:
            mongo.users.delete_one({"id": user_id})


class TestAuthIndexes:
    def test_users_identity_indexes_are_unique(self, mongo):
        indexes = mongo.users.index_information().values()
        unique_fields = {
            key
            for spec in indexes
            if spec.get("unique")
            for key, _direction in spec.get("key", [])
        }
        assert {"email", "id"} <= unique_fields


def test_cleanup(mongo, state):
    mongo.users.delete_one({"id": state.get("user_id")})
