"""Auth hardening: password policy, failed-attempt throttle, revocation."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from jose import jwt

import auth_throttle

PASSWORD = "correct-horse-battery"
ANSWER = "Pune"


def _signup(client, email="a@example.com", password=PASSWORD):
    return client.post("/api/auth/signup", json={
        "name": "Test User",
        "email": email,
        "password": password,
        "security_question": "City of birth?",
        "security_answer": ANSWER,
    })


def _login(client, email="a@example.com", password=PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def _reset(client, answer, new_password="another-long-password", email="a@example.com"):
    return client.post("/api/auth/forgot-password", json={
        "email": email, "security_answer": answer, "new_password": new_password,
    })


def _me(client, token):
    return client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})


# ---------------------------------------------------------------------------
# Password policy
# ---------------------------------------------------------------------------

def test_signup_rejects_short_password_with_readable_message(client):
    r = _signup(client, password="short")
    assert r.status_code == 400
    assert "10" in r.json()["detail"]


def test_signup_accepts_long_password(client):
    r = _signup(client)
    assert r.status_code == 201, r.text
    assert _me(client, r.json()["access_token"]).status_code == 200


def test_reset_rejects_short_new_password(client):
    _signup(client)
    r = _reset(client, ANSWER, new_password="short")
    assert r.status_code == 400
    assert "10" in r.json()["detail"]
    assert _login(client).status_code == 200


# ---------------------------------------------------------------------------
# Failed-attempt throttle
# ---------------------------------------------------------------------------

def test_login_locks_after_repeated_failures(client):
    _signup(client)
    limit = auth_throttle.LIMITS["login"][0][1]
    for _ in range(limit):
        assert _login(client, password="wrong-password").status_code == 400
    r = _login(client)  # even the right password is refused while locked
    assert r.status_code == 429
    assert r.json()["detail"] == auth_throttle.TOO_MANY_ATTEMPTS


def test_successful_login_clears_failures(client):
    _signup(client)
    limit = auth_throttle.LIMITS["login"][0][1]
    for _ in range(limit - 1):
        _login(client, password="wrong-password")
    assert _login(client).status_code == 200
    for _ in range(limit - 1):
        assert _login(client, password="wrong-password").status_code == 400
    assert _login(client).status_code == 200


def test_login_throttle_is_per_email(client):
    _signup(client, email="a@example.com")
    _signup(client, email="b@example.com")
    for _ in range(auth_throttle.LIMITS["login"][0][1]):
        _login(client, email="a@example.com", password="wrong-password")
    assert _login(client, email="a@example.com").status_code == 429
    assert _login(client, email="b@example.com").status_code == 200


def test_unknown_email_is_throttled_like_a_real_one(client):
    for _ in range(auth_throttle.LIMITS["login"][0][1]):
        assert _login(client, email="nobody@example.com").status_code == 400
    assert _login(client, email="nobody@example.com").status_code == 429


def test_security_answer_guessing_is_throttled(client):
    _signup(client)
    limit = auth_throttle.LIMITS["forgot_password"][0][1]
    for i in range(limit):
        assert _reset(client, f"guess-{i}").status_code == 400
    assert _reset(client, ANSWER).status_code == 429
    assert _login(client).status_code == 200  # password unchanged


def test_failures_outside_window_do_not_count(client, server):
    _signup(client)
    window, limit = auth_throttle.LIMITS["login"][0]
    stale = datetime.now(timezone.utc) - window - timedelta(minutes=1)
    asyncio.run(server.db.auth_attempts.insert_many([
        {"action": "login", "subject": "email:a@example.com", "at": stale}
        for _ in range(limit)
    ]))
    assert _login(client).status_code == 200


# ---------------------------------------------------------------------------
# Token revocation
# ---------------------------------------------------------------------------

def test_logout_revokes_token_on_every_device(client):
    _signup(client)
    phone = _login(client).json()["access_token"]
    laptop = _login(client).json()["access_token"]
    r = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {phone}"})
    assert r.status_code == 200
    assert _me(client, phone).status_code == 401
    assert _me(client, laptop).status_code == 401
    assert _me(client, _login(client).json()["access_token"]).status_code == 200


def test_password_reset_revokes_existing_tokens(client):
    _signup(client)
    old = _login(client).json()["access_token"]
    assert _reset(client, ANSWER).status_code == 200
    assert _me(client, old).status_code == 401
    assert _login(client, password="another-long-password").status_code == 200


def test_tokens_issued_before_versioning_still_work(client, server):
    _signup(client)
    user = asyncio.run(
        server.db.users.find_one({"email": "a@example.com"}),
    )
    legacy = jwt.encode(
        {"sub": user["id"], "exp": datetime.now(timezone.utc) + timedelta(days=1)},
        server.JWT_SECRET, algorithm=server.JWT_ALG,
    )
    assert _me(client, legacy).status_code == 200
