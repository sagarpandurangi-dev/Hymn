"""
Smoke test for Hymn Finance engine after cleanup of dead endpoints.

Verifies:
1. Removed endpoints return 404 or 405
2. Retained endpoints still return 2xx (auth'd)
"""
import os
import pytest
import requests

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")

TEST_EMAIL = "test@hymn.app"
TEST_PASSWORD = "TestPass123!"


@pytest.fixture(scope="module")
def auth_token():
    resp = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        timeout=30,
    )
    assert resp.status_code == 200, f"Login failed: {resp.status_code} {resp.text}"
    data = resp.json()
    token = data.get("token") or data.get("access_token")
    assert token, f"No token in login response: {data}"
    return token


@pytest.fixture(scope="module")
def headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}


# ---------- Removed endpoints: expect 404/405 ----------
REMOVED_CASES = [
    ("GET", "/api/finance/reserved", None),
    ("GET", "/api/finance/available-liquidity", None),
    ("POST", "/api/finance/scenarios", {"name": "test", "actions": []}),
    ("GET", "/api/finance/overrides", None),
    ("POST", "/api/finance/shared-expenses/i-owe", {"amount": 10, "currency": "USD"}),
    ("POST", "/api/finance/shared-expenses/i-paid", {"amount": 10, "currency": "USD"}),
]


@pytest.mark.parametrize("method,path,body", REMOVED_CASES)
def test_removed_endpoint_returns_404_or_405(headers, method, path, body):
    url = f"{BASE_URL}{path}"
    if method == "GET":
        r = requests.get(url, headers=headers, timeout=30)
    else:
        r = requests.post(url, headers=headers, json=body, timeout=30)
    assert r.status_code in (404, 405), (
        f"Removed endpoint {method} {path} returned {r.status_code}, expected 404/405. Body: {r.text[:300]}"
    )


# ---------- Retained endpoints: expect 2xx (except overrides POST allowed to be 4xx validation) ----------

def test_dashboard(headers):
    r = requests.get(f"{BASE_URL}/api/finance/dashboard", headers=headers, timeout=60)
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"


def test_position(headers):
    r = requests.get(f"{BASE_URL}/api/finance/position", headers=headers, timeout=60)
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"


def test_forecast(headers):
    r = requests.get(f"{BASE_URL}/api/finance/forecast", headers=headers, timeout=60)
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"


def test_forecasts_twin(headers):
    r = requests.get(f"{BASE_URL}/api/finance/forecasts", headers=headers, timeout=60)
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"


def test_reconciliation_suggestions(headers):
    r = requests.get(f"{BASE_URL}/api/finance/reconciliation/suggestions", headers=headers, timeout=60)
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"


def test_commitments_due_for_review(headers):
    r = requests.get(f"{BASE_URL}/api/finance/commitments-due-for-review", headers=headers, timeout=60)
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"


def test_expected_income(headers):
    r = requests.get(f"{BASE_URL}/api/finance/expected-income", headers=headers, timeout=60)
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"


def test_scenarios_list(headers):
    r = requests.get(f"{BASE_URL}/api/finance/scenarios/list", headers=headers, timeout=60)
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"


def test_decision_assessment(headers):
    body = {
        "decision": "Buy a laptop",
        "amount": 1000,
        "currency": "USD",
    }
    r = requests.post(f"{BASE_URL}/api/finance/decision-assessment", headers=headers, json=body, timeout=90)
    # Accept 2xx or 4xx validation error, just NOT 404/405/5xx
    assert r.status_code < 500 and r.status_code not in (404, 405), (
        f"{r.status_code} {r.text[:300]}"
    )


def test_overrides_post_exists(headers):
    # POST should exist (route not removed). Empty body may 4xx due to validation, that's OK — just NOT 404/405
    r = requests.post(f"{BASE_URL}/api/finance/overrides", headers=headers, json={}, timeout=30)
    assert r.status_code not in (404, 405), f"POST /overrides returned {r.status_code}, route missing? {r.text[:300]}"
    assert r.status_code < 500, f"POST /overrides 5xx regression: {r.status_code} {r.text[:300]}"


def test_rebalance_candidates(headers):
    r = requests.get(f"{BASE_URL}/api/finance/rebalance-candidates", headers=headers, params={"currency": "USD"}, timeout=60)
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
