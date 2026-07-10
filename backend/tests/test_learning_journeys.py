"""Backend tests for Learning Journeys (Learn module) + sanity regression."""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://personal-os-app-8.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

PRIMARY_EMAIL = "test@hymn.app"
PRIMARY_PASSWORD = "TestPass123!"


@pytest.fixture(scope="module")
def primary_token():
    r = requests.post(f"{API}/auth/login", json={"email": PRIMARY_EMAIL, "password": PRIMARY_PASSWORD}, timeout=15)
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def primary_headers(primary_token):
    return {"Authorization": f"Bearer {primary_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def secondary_headers():
    email = f"test_lj_{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(f"{API}/auth/signup", json={
        "email": email, "password": "TestPass123!",
        "security_question": "q?", "security_answer": "a",
    }, timeout=15)
    assert r.status_code == 201, f"Signup failed: {r.status_code} {r.text}"
    return {"Authorization": f"Bearer {r.json()['access_token']}", "Content-Type": "application/json"}


# ---------- Unauthorized ----------
class TestUnauthorized:
    def test_get_list_unauth(self):
        r = requests.get(f"{API}/learning-journeys", timeout=10)
        assert r.status_code == 401, f"expected 401 got {r.status_code}"

    def test_post_unauth(self):
        r = requests.post(f"{API}/learning-journeys", json={"title": "x"}, timeout=10)
        assert r.status_code == 401

    def test_put_unauth(self):
        r = requests.put(f"{API}/learning-journeys/some-id", json={"title": "x"}, timeout=10)
        assert r.status_code == 401

    def test_delete_unauth(self):
        r = requests.delete(f"{API}/learning-journeys/some-id", timeout=10)
        assert r.status_code == 401


# ---------- CRUD ----------
class TestCRUD:
    created_id: str | None = None

    def test_a_create(self, primary_headers):
        payload = {
            "title": "TEST_Learn Rust",
            "description": "Study rust systems programming",
            "target_completion_date": "2026-12-31",
        }
        r = requests.post(f"{API}/learning-journeys", headers=primary_headers, json=payload, timeout=10)
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["title"] == payload["title"]
        assert data["description"] == payload["description"]
        assert data["target_completion_date"] == payload["target_completion_date"]
        assert data["status"] == "active"
        assert data["id"]
        TestCRUD.created_id = data["id"]

    def test_b_list_contains(self, primary_headers):
        r = requests.get(f"{API}/learning-journeys", headers=primary_headers, timeout=10)
        assert r.status_code == 200
        ids = [j["id"] for j in r.json()]
        assert TestCRUD.created_id in ids

    def test_c_get_by_id(self, primary_headers):
        r = requests.get(f"{API}/learning-journeys/{TestCRUD.created_id}", headers=primary_headers, timeout=10)
        assert r.status_code == 200
        assert r.json()["id"] == TestCRUD.created_id

    def test_d_update(self, primary_headers):
        r = requests.put(f"{API}/learning-journeys/{TestCRUD.created_id}",
                         headers=primary_headers,
                         json={"status": "archived", "title": "TEST_Updated"}, timeout=10)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "archived"
        assert data["title"] == "TEST_Updated"
        # Verify via GET
        g = requests.get(f"{API}/learning-journeys/{TestCRUD.created_id}", headers=primary_headers, timeout=10)
        assert g.json()["status"] == "archived"
        assert g.json()["title"] == "TEST_Updated"

    def test_e_invalid_status(self, primary_headers):
        r = requests.put(f"{API}/learning-journeys/{TestCRUD.created_id}",
                         headers=primary_headers, json={"status": "foobar"}, timeout=10)
        assert r.status_code == 400

    def test_f_delete_and_verify(self, primary_headers):
        r = requests.delete(f"{API}/learning-journeys/{TestCRUD.created_id}", headers=primary_headers, timeout=10)
        assert r.status_code == 200
        assert "detail" in r.json()
        g = requests.get(f"{API}/learning-journeys/{TestCRUD.created_id}", headers=primary_headers, timeout=10)
        assert g.status_code == 404

    def test_g_get_nonexistent(self, primary_headers):
        r = requests.get(f"{API}/learning-journeys/nonexistent", headers=primary_headers, timeout=10)
        assert r.status_code == 404


# ---------- User isolation ----------
class TestUserIsolation:
    def test_isolation(self, primary_headers, secondary_headers):
        # Primary creates a journey
        r1 = requests.post(f"{API}/learning-journeys", headers=primary_headers,
                           json={"title": "TEST_Primary", "description": "", "target_completion_date": ""}, timeout=10)
        assert r1.status_code == 201
        primary_id = r1.json()["id"]

        # Secondary creates
        r2 = requests.post(f"{API}/learning-journeys", headers=secondary_headers,
                           json={"title": "TEST_Secondary", "description": "", "target_completion_date": ""}, timeout=10)
        assert r2.status_code == 201
        secondary_id = r2.json()["id"]

        # Primary should NOT see secondary's
        lp = requests.get(f"{API}/learning-journeys", headers=primary_headers, timeout=10).json()
        assert secondary_id not in [j["id"] for j in lp]
        assert primary_id in [j["id"] for j in lp]

        # Secondary should NOT see primary's
        ls = requests.get(f"{API}/learning-journeys", headers=secondary_headers, timeout=10).json()
        assert primary_id not in [j["id"] for j in ls]
        assert secondary_id in [j["id"] for j in ls]

        # Cross-user GET/PUT/DELETE → 404
        assert requests.get(f"{API}/learning-journeys/{secondary_id}", headers=primary_headers, timeout=10).status_code == 404
        assert requests.put(f"{API}/learning-journeys/{secondary_id}", headers=primary_headers, json={"title": "hack"}, timeout=10).status_code == 404
        assert requests.delete(f"{API}/learning-journeys/{secondary_id}", headers=primary_headers, timeout=10).status_code == 404

        # cleanup
        requests.delete(f"{API}/learning-journeys/{primary_id}", headers=primary_headers, timeout=10)
        requests.delete(f"{API}/learning-journeys/{secondary_id}", headers=secondary_headers, timeout=10)


# ---------- Sanity regression ----------
class TestRegression:
    @pytest.mark.parametrize("path", [
        "/auth/me", "/goals", "/projects", "/tasks", "/checkins", "/domains", "/outcome-types",
    ])
    def test_endpoint_ok(self, primary_headers, path):
        r = requests.get(f"{API}{path}", headers=primary_headers, timeout=15)
        assert r.status_code == 200, f"{path} -> {r.status_code} {r.text[:200]}"
