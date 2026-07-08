"""Backend tests for DELETE /api/events/{id} isolation + auth handling."""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/") or os.environ["EXPO_BACKEND_URL"].rstrip("/")


@pytest.fixture(scope="module")
def owner_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": "test@hymn.app", "password": "TestPass123!"}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def other_token():
    ts = int(time.time() * 1000)
    email = f"TEST_delete_other_{ts}_{uuid.uuid4().hex[:6]}@hymn.app"
    r = requests.post(f"{BASE_URL}/api/auth/signup", json={
        "email": email, "password": "OtherPass123!",
        "security_question": "q", "security_answer": "a",
    }, timeout=15)
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


def _create_event(token: str, title: str) -> str:
    r = requests.post(f"{BASE_URL}/api/events",
                      json={"type": "milestone", "title": title,
                            "date": "2026-01-15", "time": "10:00", "notes": "delete test"},
                      headers={"Authorization": f"Bearer {token}"}, timeout=15)
    assert r.status_code == 201, r.text
    return r.json()["id"]


class TestEventDelete:
    def test_delete_own_event_success(self, owner_token):
        eid = _create_event(owner_token, f"TEST_del_own_{uuid.uuid4().hex[:6]}")
        r = requests.delete(f"{BASE_URL}/api/events/{eid}",
                            headers={"Authorization": f"Bearer {owner_token}"}, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "detail" in body

        # verify GET now 404
        rget = requests.get(f"{BASE_URL}/api/events/{eid}",
                            headers={"Authorization": f"Bearer {owner_token}"}, timeout=15)
        assert rget.status_code == 404

        # verify not in list
        rlist = requests.get(f"{BASE_URL}/api/events",
                             headers={"Authorization": f"Bearer {owner_token}"}, timeout=15)
        assert rlist.status_code == 200
        ids = [e["id"] for e in rlist.json()]
        assert eid not in ids

    def test_delete_without_auth_returns_401(self, owner_token):
        eid = _create_event(owner_token, f"TEST_del_noauth_{uuid.uuid4().hex[:6]}")
        try:
            r = requests.delete(f"{BASE_URL}/api/events/{eid}", timeout=15)
            assert r.status_code == 401, r.text
            # cleanup — still exists
            rget = requests.get(f"{BASE_URL}/api/events/{eid}",
                                headers={"Authorization": f"Bearer {owner_token}"}, timeout=15)
            assert rget.status_code == 200
        finally:
            requests.delete(f"{BASE_URL}/api/events/{eid}",
                            headers={"Authorization": f"Bearer {owner_token}"}, timeout=15)

    def test_delete_other_users_event_returns_404_and_isolation(self, owner_token, other_token):
        eid = _create_event(owner_token, f"TEST_del_isolation_{uuid.uuid4().hex[:6]}")
        try:
            r = requests.delete(f"{BASE_URL}/api/events/{eid}",
                                headers={"Authorization": f"Bearer {other_token}"}, timeout=15)
            assert r.status_code == 404, r.text
            # original owner still sees it
            rget = requests.get(f"{BASE_URL}/api/events/{eid}",
                                headers={"Authorization": f"Bearer {owner_token}"}, timeout=15)
            assert rget.status_code == 200
            assert rget.json()["id"] == eid
        finally:
            requests.delete(f"{BASE_URL}/api/events/{eid}",
                            headers={"Authorization": f"Bearer {owner_token}"}, timeout=15)

    def test_delete_nonexistent_returns_404(self, owner_token):
        fake_id = str(uuid.uuid4())
        r = requests.delete(f"{BASE_URL}/api/events/{fake_id}",
                            headers={"Authorization": f"Bearer {owner_token}"}, timeout=15)
        assert r.status_code == 404, r.text

    def test_delete_with_bad_token_returns_401(self):
        r = requests.delete(f"{BASE_URL}/api/events/{uuid.uuid4()}",
                            headers={"Authorization": "Bearer not-a-real-token"}, timeout=15)
        assert r.status_code == 401
