"""Live HTTP integration tests for Portfolio Manager (backend only).

Exercises every /api/portfolio endpoint through the public EXPO_PUBLIC_BACKEND_URL
against the running FastAPI service. Also validates a small regression surface
on /api/domains, /api/goals, /api/tasks, /api/checkins, /api/knowledge/journeys
to confirm the deps.py extraction did not break existing routes.
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timedelta

import pytest
import requests


# Backend URL from frontend env (public endpoint) — never localhost.
def _load_backend_url() -> str:
    env_path = "/app/frontend/.env"
    with open(env_path, "r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
                return line.split("=", 1)[1].strip().strip('"').rstrip("/")
    raise RuntimeError("EXPO_PUBLIC_BACKEND_URL not found")


BASE_URL = _load_backend_url()
API = f"{BASE_URL}/api"


# ---------- Auth helpers ----------
def _signup() -> tuple[str, dict]:
    """Sign up a fresh TEST_ user; return (token, user)."""
    suffix = uuid.uuid4().hex[:10]
    email = f"TEST_pm_{suffix}@example.com"
    payload = {
        "email": email,
        "password": "TestPass123!",
        "security_question": "Color?",
        "security_answer": "blue",
    }
    r = requests.post(f"{API}/auth/signup", json=payload, timeout=30)
    assert r.status_code == 201, f"signup failed {r.status_code}: {r.text}"
    data = r.json()
    return data["access_token"], data["user"]


@pytest.fixture(scope="module")
def user_a():
    tok, u = _signup()
    h = {"Authorization": f"Bearer {tok}"}
    # Seed real Hymn objects so allocation tests can reference them and
    # satisfy the new owner-integrity check.
    owner_ids = _seed_owner_objects(h)
    return {"token": tok, "user": u, "h": h, "owners": owner_ids}


@pytest.fixture(scope="module")
def user_b():
    tok, u = _signup()
    h = {"Authorization": f"Bearer {tok}"}
    owner_ids = _seed_owner_objects(h)
    return {"token": tok, "user": u, "h": h, "owners": owner_ids}


def _seed_owner_objects(h: dict) -> dict:
    """Create one task, one project and one knowledge journey per user."""
    rt = requests.post(f"{API}/tasks", json={"title": f"TEST_pm_owner_{uuid.uuid4().hex[:6]}"},
                      headers=h, timeout=30)
    assert rt.status_code == 201, rt.text
    task_id = rt.json()["id"]

    rp = requests.post(f"{API}/projects", json={"title": f"TEST_pm_proj_{uuid.uuid4().hex[:6]}"},
                       headers=h, timeout=30)
    assert rp.status_code == 201, rp.text
    proj_id = rp.json()["id"]

    rj = requests.post(f"{API}/knowledge/journeys", json={
        "journey_type": "skill",
        "title": f"TEST_pm_kj_{uuid.uuid4().hex[:6]}",
        "why": "portfolio-owner-integrity",
        "target_completion_date": "",
        "first_outcome": {"title": "eo"},
        "first_task": {"title": "t", "priority": "medium"},
        "checkin_cadence": "manual",
    }, headers=h, timeout=30)
    assert rj.status_code == 201, rj.text
    kj_id = rj.json()["id"]

    return {"task": task_id, "project": proj_id, "knowledge_journey": kj_id}


# ==========================================================================
# Time commitments
# ==========================================================================
class TestTimeCommitments:
    def test_create_ok_and_persisted(self, user_a):
        body = {
            "title": "TEST_sleep",
            "day_of_week": "monday",
            "start_time": "23:00",
            "end_time": "23:59",
            "commitment_type": "sleep",
            "flexibility": "fixed",
            "effective_from": "2026-01-01",
        }
        r = requests.post(f"{API}/portfolio/time-commitments", json=body, headers=user_a["h"], timeout=30)
        assert r.status_code == 201, r.text
        d = r.json()
        assert d["id"] and d["user_id"] == user_a["user"]["id"]
        assert d["title"] == "TEST_sleep"
        assert d["effective_until"] is None
        user_a["tc_id"] = d["id"]

        # GET verification
        r2 = requests.get(f"{API}/portfolio/time-commitments", headers=user_a["h"], timeout=30)
        assert r2.status_code == 200
        assert any(x["id"] == d["id"] for x in r2.json())

    def test_reject_end_le_start(self, user_a):
        body = {"title": "x", "day_of_week": "monday", "start_time": "10:00", "end_time": "09:00",
                "commitment_type": "work", "flexibility": "fixed", "effective_from": "2026-01-01"}
        r = requests.post(f"{API}/portfolio/time-commitments", json=body, headers=user_a["h"], timeout=30)
        assert r.status_code == 400, r.text

    def test_reject_cross_midnight(self, user_a):
        body = {"title": "x", "day_of_week": "monday", "start_time": "23:00", "end_time": "24:00",
                "commitment_type": "sleep", "flexibility": "fixed", "effective_from": "2026-01-01"}
        r = requests.post(f"{API}/portfolio/time-commitments", json=body, headers=user_a["h"], timeout=30)
        # 24:00 is not a valid HH:mm token per regex → 400
        assert r.status_code == 400

    def test_reject_bad_day_of_week(self, user_a):
        body = {"title": "x", "day_of_week": "funday", "start_time": "09:00", "end_time": "10:00",
                "commitment_type": "work", "flexibility": "fixed", "effective_from": "2026-01-01"}
        r = requests.post(f"{API}/portfolio/time-commitments", json=body, headers=user_a["h"], timeout=30)
        assert r.status_code == 400

    def test_reject_bad_commitment_type(self, user_a):
        body = {"title": "x", "day_of_week": "monday", "start_time": "09:00", "end_time": "10:00",
                "commitment_type": "party", "flexibility": "fixed", "effective_from": "2026-01-01"}
        r = requests.post(f"{API}/portfolio/time-commitments", json=body, headers=user_a["h"], timeout=30)
        assert r.status_code == 400

    def test_reject_bad_flexibility(self, user_a):
        body = {"title": "x", "day_of_week": "monday", "start_time": "09:00", "end_time": "10:00",
                "commitment_type": "work", "flexibility": "sorta", "effective_from": "2026-01-01"}
        r = requests.post(f"{API}/portfolio/time-commitments", json=body, headers=user_a["h"], timeout=30)
        assert r.status_code == 400

    def test_reject_effective_until_before_from(self, user_a):
        body = {"title": "x", "day_of_week": "monday", "start_time": "09:00", "end_time": "10:00",
                "commitment_type": "work", "flexibility": "fixed",
                "effective_from": "2026-02-01", "effective_until": "2026-01-01"}
        r = requests.post(f"{API}/portfolio/time-commitments", json=body, headers=user_a["h"], timeout=30)
        assert r.status_code == 400

    def test_bad_time_format(self, user_a):
        body = {"title": "x", "day_of_week": "monday", "start_time": "9:00", "end_time": "10:00",
                "commitment_type": "work", "flexibility": "fixed", "effective_from": "2026-01-01"}
        r = requests.post(f"{API}/portfolio/time-commitments", json=body, headers=user_a["h"], timeout=30)
        assert r.status_code == 400

    def test_update_and_delete(self, user_a):
        # create
        body = {"title": "TEST_upd", "day_of_week": "friday", "start_time": "10:00", "end_time": "11:00",
                "commitment_type": "work", "flexibility": "fixed", "effective_from": "2026-01-01"}
        r = requests.post(f"{API}/portfolio/time-commitments", json=body, headers=user_a["h"], timeout=30)
        assert r.status_code == 201
        cid = r.json()["id"]
        # update
        r2 = requests.put(f"{API}/portfolio/time-commitments/{cid}", json={"title": "TEST_upd2"}, headers=user_a["h"], timeout=30)
        assert r2.status_code == 200
        assert r2.json()["title"] == "TEST_upd2"
        # delete
        r3 = requests.delete(f"{API}/portfolio/time-commitments/{cid}", headers=user_a["h"], timeout=30)
        assert r3.status_code == 200
        # verify gone
        r4 = requests.delete(f"{API}/portfolio/time-commitments/{cid}", headers=user_a["h"], timeout=30)
        assert r4.status_code == 404


# ==========================================================================
# Financial accounts
# ==========================================================================
class TestFinancialAccounts:
    def test_create_asset_ok(self, user_a):
        body = {"account_type": "cash", "name": "TEST_wallet", "currency": "USD",
                "current_value": 500.0, "liquidity_type": "liquid", "fixed_or_flexible": "flexible"}
        r = requests.post(f"{API}/portfolio/financial-accounts", json=body, headers=user_a["h"], timeout=30)
        assert r.status_code == 201, r.text
        d = r.json()
        assert d["currency"] == "USD"
        assert d["current_value"] == "500.0"
        assert isinstance(d["current_value"], str)
        user_a["fa_id"] = d["id"]

    def test_create_liability_positive_value(self, user_a):
        body = {"account_type": "credit_card", "name": "TEST_cc", "currency": "USD",
                "current_value": 1200.0, "liquidity_type": "liquid", "fixed_or_flexible": "fixed"}
        r = requests.post(f"{API}/portfolio/financial-accounts", json=body, headers=user_a["h"], timeout=30)
        assert r.status_code == 201, r.text
        assert r.json()["current_value"] == "1200.0"

    def test_reject_negative_value(self, user_a):
        body = {"account_type": "cash", "name": "n", "currency": "USD",
                "current_value": -50, "liquidity_type": "liquid", "fixed_or_flexible": "flexible"}
        r = requests.post(f"{API}/portfolio/financial-accounts", json=body, headers=user_a["h"], timeout=30)
        assert r.status_code == 400

    def test_reject_bad_currency(self, user_a):
        body = {"account_type": "cash", "name": "n", "currency": "dollar",
                "current_value": 10, "liquidity_type": "liquid", "fixed_or_flexible": "flexible"}
        r = requests.post(f"{API}/portfolio/financial-accounts", json=body, headers=user_a["h"], timeout=30)
        assert r.status_code == 400

    def test_reject_bad_account_type(self, user_a):
        body = {"account_type": "gold_bar", "name": "n", "currency": "USD",
                "current_value": 10, "liquidity_type": "liquid", "fixed_or_flexible": "flexible"}
        r = requests.post(f"{API}/portfolio/financial-accounts", json=body, headers=user_a["h"], timeout=30)
        assert r.status_code == 400

    def test_reject_bad_liquidity(self, user_a):
        body = {"account_type": "cash", "name": "n", "currency": "USD",
                "current_value": 10, "liquidity_type": "fluid", "fixed_or_flexible": "flexible"}
        r = requests.post(f"{API}/portfolio/financial-accounts", json=body, headers=user_a["h"], timeout=30)
        assert r.status_code == 400

    def test_update_and_delete(self, user_a):
        body = {"account_type": "cash", "name": "TEST_tmp", "currency": "USD",
                "current_value": 1, "liquidity_type": "liquid", "fixed_or_flexible": "flexible"}
        r = requests.post(f"{API}/portfolio/financial-accounts", json=body, headers=user_a["h"], timeout=30)
        aid = r.json()["id"]
        r2 = requests.put(f"{API}/portfolio/financial-accounts/{aid}", json={"current_value": 99}, headers=user_a["h"], timeout=30)
        assert r2.status_code == 200 and r2.json()["current_value"] == "99"
        r3 = requests.delete(f"{API}/portfolio/financial-accounts/{aid}", headers=user_a["h"], timeout=30)
        assert r3.status_code == 200


# ==========================================================================
# Monthly money commitments
# ==========================================================================
class TestMonthlyMoneyCommitments:
    def test_create_income(self, user_a):
        body = {"title": "TEST_salary", "currency": "USD", "amount": 5000,
                "commitment_type": "income", "fixed_or_flexible": "fixed",
                "start_month": "2026-01"}
        r = requests.post(f"{API}/portfolio/monthly-money-commitments", json=body, headers=user_a["h"], timeout=30)
        assert r.status_code == 201, r.text
        assert r.json()["amount"] == "5000"
        user_a["mm_income"] = r.json()["id"]

    def test_create_expense_fixed(self, user_a):
        body = {"title": "TEST_rent", "currency": "USD", "amount": 1500,
                "commitment_type": "expense", "fixed_or_flexible": "fixed",
                "start_month": "2026-01"}
        r = requests.post(f"{API}/portfolio/monthly-money-commitments", json=body, headers=user_a["h"], timeout=30)
        assert r.status_code == 201

    def test_create_expense_flexible(self, user_a):
        body = {"title": "TEST_food", "currency": "USD", "amount": 600,
                "commitment_type": "expense", "fixed_or_flexible": "flexible",
                "start_month": "2026-01"}
        r = requests.post(f"{API}/portfolio/monthly-money-commitments", json=body, headers=user_a["h"], timeout=30)
        assert r.status_code == 201

    def test_reject_negative_amount(self, user_a):
        body = {"title": "x", "currency": "USD", "amount": -10,
                "commitment_type": "expense", "fixed_or_flexible": "fixed", "start_month": "2026-01"}
        r = requests.post(f"{API}/portfolio/monthly-money-commitments", json=body, headers=user_a["h"], timeout=30)
        assert r.status_code == 400

    def test_reject_bad_month(self, user_a):
        body = {"title": "x", "currency": "USD", "amount": 10,
                "commitment_type": "expense", "fixed_or_flexible": "fixed", "start_month": "2026/01"}
        r = requests.post(f"{API}/portfolio/monthly-money-commitments", json=body, headers=user_a["h"], timeout=30)
        assert r.status_code == 400

    def test_reject_end_before_start(self, user_a):
        body = {"title": "x", "currency": "USD", "amount": 10,
                "commitment_type": "expense", "fixed_or_flexible": "fixed",
                "start_month": "2026-06", "end_month": "2026-01"}
        r = requests.post(f"{API}/portfolio/monthly-money-commitments", json=body, headers=user_a["h"], timeout=30)
        assert r.status_code == 400

    def test_reject_bad_type(self, user_a):
        body = {"title": "x", "currency": "USD", "amount": 10,
                "commitment_type": "gift", "fixed_or_flexible": "fixed", "start_month": "2026-01"}
        r = requests.post(f"{API}/portfolio/monthly-money-commitments", json=body, headers=user_a["h"], timeout=30)
        assert r.status_code == 400

    def test_update_and_delete(self, user_a):
        body = {"title": "TEST_mm_tmp", "currency": "USD", "amount": 10,
                "commitment_type": "saving", "fixed_or_flexible": "flexible", "start_month": "2026-01"}
        r = requests.post(f"{API}/portfolio/monthly-money-commitments", json=body, headers=user_a["h"], timeout=30)
        mid = r.json()["id"]
        r2 = requests.put(f"{API}/portfolio/monthly-money-commitments/{mid}", json={"amount": 42}, headers=user_a["h"], timeout=30)
        assert r2.status_code == 200 and r2.json()["amount"] == "42"
        r3 = requests.delete(f"{API}/portfolio/monthly-money-commitments/{mid}", headers=user_a["h"], timeout=30)
        assert r3.status_code == 200


# ==========================================================================
# Resource allocations
# ==========================================================================
class TestResourceAllocations:
    def test_time_recurring_ok(self, user_a):
        body = {"resource_type": "time", "owner_type": "standalone", "allocation_mode": "recurring",
                "day_of_week": "tuesday", "start_time": "09:00", "end_time": "10:00",
                "quantity": 60, "unit": "minutes", "status": "proposed", "fixed_or_flexible": "flexible"}
        r = requests.post(f"{API}/portfolio/resource-allocations", json=body, headers=user_a["h"], timeout=30)
        assert r.status_code == 201, r.text
        d = r.json()
        assert d["currency"] is None and d["date"] is None
        assert d["quantity"] == "60"
        assert isinstance(d["quantity"], str)

    def test_time_recurring_forbids_date(self, user_a):
        body = {"resource_type": "time", "owner_type": "standalone", "allocation_mode": "recurring",
                "day_of_week": "tuesday", "date": "2026-01-05",
                "start_time": "09:00", "end_time": "10:00", "quantity": 60,
                "unit": "minutes", "status": "proposed", "fixed_or_flexible": "flexible"}
        r = requests.post(f"{API}/portfolio/resource-allocations", json=body, headers=user_a["h"], timeout=30)
        assert r.status_code == 400

    def test_time_one_time_ok(self, user_a):
        body = {"resource_type": "time", "owner_type": "task", "owner_id": user_a["owners"]["task"],
                "allocation_mode": "one_time", "date": "2026-01-05",
                "start_time": "08:00", "end_time": "09:30", "quantity": 90,
                "unit": "minutes", "status": "proposed", "fixed_or_flexible": "flexible"}
        r = requests.post(f"{API}/portfolio/resource-allocations", json=body, headers=user_a["h"], timeout=30)
        assert r.status_code == 201, r.text

    def test_time_one_time_forbids_day_of_week(self, user_a):
        body = {"resource_type": "time", "owner_type": "standalone", "allocation_mode": "one_time",
                "date": "2026-01-05", "day_of_week": "monday",
                "start_time": "08:00", "end_time": "09:00", "quantity": 60,
                "unit": "minutes", "status": "proposed", "fixed_or_flexible": "flexible"}
        r = requests.post(f"{API}/portfolio/resource-allocations", json=body, headers=user_a["h"], timeout=30)
        assert r.status_code == 400

    def test_time_quantity_must_match_duration(self, user_a):
        body = {"resource_type": "time", "owner_type": "standalone", "allocation_mode": "recurring",
                "day_of_week": "monday", "start_time": "09:00", "end_time": "10:00",
                "quantity": 55, "unit": "minutes", "status": "proposed", "fixed_or_flexible": "flexible"}
        r = requests.post(f"{API}/portfolio/resource-allocations", json=body, headers=user_a["h"], timeout=30)
        assert r.status_code == 400

    def test_time_currency_forbidden(self, user_a):
        body = {"resource_type": "time", "owner_type": "standalone", "allocation_mode": "recurring",
                "day_of_week": "monday", "start_time": "09:00", "end_time": "10:00",
                "quantity": 60, "unit": "minutes", "currency": "USD",
                "status": "proposed", "fixed_or_flexible": "flexible"}
        r = requests.post(f"{API}/portfolio/resource-allocations", json=body, headers=user_a["h"], timeout=30)
        assert r.status_code == 400

    def test_money_one_time_ok(self, user_a):
        body = {"resource_type": "money", "owner_type": "project", "owner_id": user_a["owners"]["project"],
                "allocation_mode": "one_time", "date": "2026-01-15",
                "quantity": 100.0, "unit": "currency", "currency": "USD",
                "status": "proposed", "fixed_or_flexible": "flexible"}
        r = requests.post(f"{API}/portfolio/resource-allocations", json=body, headers=user_a["h"], timeout=30)
        assert r.status_code == 201, r.text
        assert r.json()["quantity"] == "100.0"
        assert isinstance(r.json()["quantity"], str)

    def test_money_requires_currency(self, user_a):
        body = {"resource_type": "money", "owner_type": "standalone", "allocation_mode": "one_time",
                "date": "2026-01-15", "quantity": 100, "unit": "currency",
                "status": "proposed", "fixed_or_flexible": "flexible"}
        r = requests.post(f"{API}/portfolio/resource-allocations", json=body, headers=user_a["h"], timeout=30)
        assert r.status_code == 400

    def test_money_forbids_times(self, user_a):
        body = {"resource_type": "money", "owner_type": "standalone", "allocation_mode": "one_time",
                "date": "2026-01-15", "start_time": "09:00", "quantity": 100,
                "unit": "currency", "currency": "USD",
                "status": "proposed", "fixed_or_flexible": "flexible"}
        r = requests.post(f"{API}/portfolio/resource-allocations", json=body, headers=user_a["h"], timeout=30)
        assert r.status_code == 400

    def test_money_negative_quantity_rejected(self, user_a):
        body = {"resource_type": "money", "owner_type": "standalone", "allocation_mode": "one_time",
                "date": "2026-01-15", "quantity": -1, "unit": "currency", "currency": "USD",
                "status": "proposed", "fixed_or_flexible": "flexible"}
        r = requests.post(f"{API}/portfolio/resource-allocations", json=body, headers=user_a["h"], timeout=30)
        assert r.status_code == 400

    def test_owner_type_goal_rejected(self, user_a):
        body = {"resource_type": "money", "owner_type": "goal", "owner_id": "g1",
                "allocation_mode": "one_time", "date": "2026-01-15",
                "quantity": 10, "unit": "currency", "currency": "USD",
                "status": "proposed", "fixed_or_flexible": "flexible"}
        r = requests.post(f"{API}/portfolio/resource-allocations", json=body, headers=user_a["h"], timeout=30)
        # goal is NOT allowed → 400/422
        assert r.status_code in (400, 422)

    def test_owner_type_accepted_set(self, user_a):
        # standalone requires owner_id=null; the other three require owner_id AND
        # the referenced object must exist for this user.
        cases = [
            ("task", user_a["owners"]["task"]),
            ("project", user_a["owners"]["project"]),
            ("knowledge_journey", user_a["owners"]["knowledge_journey"]),
        ]
        for ot, oid in cases:
            body = {"resource_type": "money", "owner_type": ot, "owner_id": oid,
                    "allocation_mode": "one_time", "date": "2026-01-15",
                    "quantity": 10, "unit": "currency", "currency": "USD",
                    "status": "proposed", "fixed_or_flexible": "flexible"}
            r = requests.post(f"{API}/portfolio/resource-allocations", json=body, headers=user_a["h"], timeout=30)
            assert r.status_code == 201, f"{ot}: {r.text}"

    def test_standalone_forbids_owner_id(self, user_a):
        body = {"resource_type": "money", "owner_type": "standalone", "owner_id": "should-not",
                "allocation_mode": "one_time", "date": "2026-01-15",
                "quantity": 10, "unit": "currency", "currency": "USD",
                "status": "proposed", "fixed_or_flexible": "flexible"}
        r = requests.post(f"{API}/portfolio/resource-allocations", json=body, headers=user_a["h"], timeout=30)
        assert r.status_code == 400

    def test_non_standalone_requires_owner_id(self, user_a):
        body = {"resource_type": "money", "owner_type": "task",
                "allocation_mode": "one_time", "date": "2026-01-15",
                "quantity": 10, "unit": "currency", "currency": "USD",
                "status": "proposed", "fixed_or_flexible": "flexible"}
        r = requests.post(f"{API}/portfolio/resource-allocations", json=body, headers=user_a["h"], timeout=30)
        assert r.status_code == 400

    def test_update_delete_allocation(self, user_a):
        body = {"resource_type": "time", "owner_type": "standalone",
                "allocation_mode": "recurring", "day_of_week": "thursday",
                "start_time": "08:00", "end_time": "09:00", "quantity": 60,
                "unit": "minutes", "status": "proposed", "fixed_or_flexible": "flexible"}
        r = requests.post(f"{API}/portfolio/resource-allocations", json=body, headers=user_a["h"], timeout=30)
        aid = r.json()["id"]
        r2 = requests.put(f"{API}/portfolio/resource-allocations/{aid}",
                          json={"status": "reserved"}, headers=user_a["h"], timeout=30)
        assert r2.status_code == 200 and r2.json()["status"] == "reserved"
        r3 = requests.delete(f"{API}/portfolio/resource-allocations/{aid}", headers=user_a["h"], timeout=30)
        assert r3.status_code == 200


# ==========================================================================
# Derived capacity endpoints
# ==========================================================================
class TestDerivedCapacity:
    def test_daily_capacity_union_of_overlapping(self, user_a):
        # user has TEST_sleep monday 23:00–23:59 (59m) already
        # Add overlapping monday intervals: 08:00-10:00, 09:00-11:00 => union 3h=180m
        b1 = {"title": "TEST_ov1", "day_of_week": "monday", "start_time": "08:00", "end_time": "10:00",
              "commitment_type": "work", "flexibility": "fixed", "effective_from": "2026-01-01"}
        b2 = {"title": "TEST_ov2", "day_of_week": "monday", "start_time": "09:00", "end_time": "11:00",
              "commitment_type": "work", "flexibility": "fixed", "effective_from": "2026-01-01"}
        requests.post(f"{API}/portfolio/time-commitments", json=b1, headers=user_a["h"], timeout=30)
        requests.post(f"{API}/portfolio/time-commitments", json=b2, headers=user_a["h"], timeout=30)
        # A Monday: 2026-01-05
        r = requests.get(f"{API}/portfolio/time-capacity/day",
                         params={"date": "2026-01-05"}, headers=user_a["h"], timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["day_of_week"] == "monday"
        # committed should be 180 (union of 8-11) + 59 (23:00-23:59) = 239
        assert d["committed_minutes"] == 239, d
        assert d["overlapping_minutes"] == 60, d  # 2h+2h = 240, union=180 → overlap=60
        assert d["available_minutes"] == 1440 - 239
        assert d["total_minutes"] == 1440

    def test_daily_capacity_bad_date(self, user_a):
        r = requests.get(f"{API}/portfolio/time-capacity/day",
                         params={"date": "2026-13-40"}, headers=user_a["h"], timeout=30)
        assert r.status_code == 400

    def test_weekly_capacity_requires_monday(self, user_a):
        # 2026-01-06 is a Tuesday
        r = requests.get(f"{API}/portfolio/time-capacity/week",
                         params={"week_start_date": "2026-01-06"}, headers=user_a["h"], timeout=30)
        assert r.status_code == 400, r.text

    def test_weekly_capacity_ok(self, user_a):
        r = requests.get(f"{API}/portfolio/time-capacity/week",
                         params={"week_start_date": "2026-01-05"}, headers=user_a["h"], timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert len(d["days"]) == 7
        assert d["days"][0]["day_of_week"] == "monday"
        assert d["days"][6]["day_of_week"] == "sunday"

    def test_money_position_math(self, user_a):
        # user_a has: income 5000 fixed, rent 1500 fixed expense, food 600 flexible expense
        # And two liquid USD assets: TEST_wallet 500, plus TEST_cc (liability, NOT counted as liquid asset)
        r = requests.get(f"{API}/portfolio/money-position",
                         params={"month": "2026-01", "currency": "USD"},
                         headers=user_a["h"], timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["month"] == "2026-01" and d["currency"] == "USD"
        assert d["planned_income"] == "5000.00"
        assert d["fixed_outflows"] == "1500.00"
        assert d["flexible_outflows"] == "600.00"
        # opening liquid assets: cash 500 (credit_card excluded because it's liability)
        assert d["opening_liquid_assets"] == "500.00"
        # available = 500 + 5000 - 1500 - 600 = 3400
        assert d["available_for_flexible_spending"] == "3400.00"

    def test_money_position_empty_currency(self, user_a):
        r = requests.get(f"{API}/portfolio/money-position",
                         params={"month": "2026-01", "currency": "EUR"},
                         headers=user_a["h"], timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["planned_income"] == "0.00"
        assert d["fixed_outflows"] == "0.00"
        assert d["flexible_outflows"] == "0.00"
        assert d["opening_liquid_assets"] == "0.00"
        assert d["available_for_flexible_spending"] == "0.00"

    def test_money_position_bad_month_and_currency(self, user_a):
        r = requests.get(f"{API}/portfolio/money-position",
                         params={"month": "2026/01", "currency": "USD"},
                         headers=user_a["h"], timeout=30)
        assert r.status_code == 400
        r = requests.get(f"{API}/portfolio/money-position",
                         params={"month": "2026-01", "currency": "us"},
                         headers=user_a["h"], timeout=30)
        assert r.status_code == 400


# ==========================================================================
# User isolation across all 4 collections
# ==========================================================================
class TestUserIsolation:
    def test_isolation_all_collections(self, user_a, user_b):
        # user A owns tc_id, and let's grab a monthly commitment id
        tc_id = user_a.get("tc_id")
        assert tc_id
        # user B cannot see, update or delete
        r = requests.get(f"{API}/portfolio/time-commitments", headers=user_b["h"], timeout=30)
        assert r.status_code == 200
        assert all(x["id"] != tc_id for x in r.json())
        r2 = requests.put(f"{API}/portfolio/time-commitments/{tc_id}",
                          json={"title": "hack"}, headers=user_b["h"], timeout=30)
        assert r2.status_code == 404
        r3 = requests.delete(f"{API}/portfolio/time-commitments/{tc_id}", headers=user_b["h"], timeout=30)
        assert r3.status_code == 404

        # Same idea, financial account
        fa_id = user_a.get("fa_id")
        assert fa_id
        r = requests.put(f"{API}/portfolio/financial-accounts/{fa_id}",
                         json={"current_value": 1}, headers=user_b["h"], timeout=30)
        assert r.status_code == 404
        r = requests.delete(f"{API}/portfolio/financial-accounts/{fa_id}", headers=user_b["h"], timeout=30)
        assert r.status_code == 404

        # Monthly money commitment
        mm_id = user_a.get("mm_income")
        assert mm_id
        r = requests.put(f"{API}/portfolio/monthly-money-commitments/{mm_id}",
                         json={"amount": 1}, headers=user_b["h"], timeout=30)
        assert r.status_code == 404

    def test_auth_required(self):
        r = requests.get(f"{API}/portfolio/time-commitments", timeout=30)
        assert r.status_code in (401, 403)


# ==========================================================================
# Owner integrity — existence + user ownership of the referenced object
# ==========================================================================
class TestAllocationOwnerIntegrity:
    def test_valid_task_owner(self, user_a):
        body = {"resource_type": "money", "owner_type": "task",
                "owner_id": user_a["owners"]["task"],
                "allocation_mode": "one_time", "date": "2026-01-15",
                "quantity": 10, "unit": "currency", "currency": "USD",
                "status": "proposed", "fixed_or_flexible": "flexible"}
        r = requests.post(f"{API}/portfolio/resource-allocations", json=body,
                          headers=user_a["h"], timeout=30)
        assert r.status_code == 201, r.text

    def test_nonexistent_owner_rejected(self, user_a):
        for ot in ("task", "project", "knowledge_journey"):
            body = {"resource_type": "money", "owner_type": ot,
                    "owner_id": str(uuid.uuid4()),
                    "allocation_mode": "one_time", "date": "2026-01-15",
                    "quantity": 10, "unit": "currency", "currency": "USD",
                    "status": "proposed", "fixed_or_flexible": "flexible"}
            r = requests.post(f"{API}/portfolio/resource-allocations", json=body,
                              headers=user_a["h"], timeout=30)
            assert r.status_code == 400, f"{ot}: {r.text}"

    def test_foreign_user_owner_rejected(self, user_a, user_b):
        # user_a references user_b's task -> 400
        for ot in ("task", "project", "knowledge_journey"):
            body = {"resource_type": "money", "owner_type": ot,
                    "owner_id": user_b["owners"][ot],
                    "allocation_mode": "one_time", "date": "2026-01-15",
                    "quantity": 10, "unit": "currency", "currency": "USD",
                    "status": "proposed", "fixed_or_flexible": "flexible"}
            r = requests.post(f"{API}/portfolio/resource-allocations", json=body,
                              headers=user_a["h"], timeout=30)
            assert r.status_code == 400, f"{ot}: {r.text}"

    def test_standalone_with_null_owner_id_accepted(self, user_a):
        body = {"resource_type": "money", "owner_type": "standalone", "owner_id": None,
                "allocation_mode": "one_time", "date": "2026-01-15",
                "quantity": 10, "unit": "currency", "currency": "USD",
                "status": "proposed", "fixed_or_flexible": "flexible"}
        r = requests.post(f"{API}/portfolio/resource-allocations", json=body,
                          headers=user_a["h"], timeout=30)
        assert r.status_code == 201, r.text

    def test_standalone_with_non_null_owner_id_rejected(self, user_a):
        body = {"resource_type": "money", "owner_type": "standalone",
                "owner_id": "should-be-null",
                "allocation_mode": "one_time", "date": "2026-01-15",
                "quantity": 10, "unit": "currency", "currency": "USD",
                "status": "proposed", "fixed_or_flexible": "flexible"}
        r = requests.post(f"{API}/portfolio/resource-allocations", json=body,
                          headers=user_a["h"], timeout=30)
        assert r.status_code == 400


# ==========================================================================
# Money as Decimal — no binary float leakage, precision preserved
# ==========================================================================
class TestMoneyDecimalStorage:
    def test_account_string_precision(self, user_a):
        body = {"account_type": "cash", "name": f"TEST_dec_{uuid.uuid4().hex[:6]}",
                "currency": "USD", "current_value": "9999.9999",
                "liquidity_type": "liquid", "fixed_or_flexible": "flexible"}
        r = requests.post(f"{API}/portfolio/financial-accounts", json=body,
                          headers=user_a["h"], timeout=30)
        assert r.status_code == 201, r.text
        d = r.json()
        assert d["current_value"] == "9999.9999"
        assert isinstance(d["current_value"], str)

    def test_account_reject_nan_and_infinity(self, user_a):
        for bad in ("NaN", "Infinity", "-Infinity"):
            body = {"account_type": "cash", "name": "x", "currency": "USD",
                    "current_value": bad, "liquidity_type": "liquid",
                    "fixed_or_flexible": "flexible"}
            r = requests.post(f"{API}/portfolio/financial-accounts", json=body,
                              headers=user_a["h"], timeout=30)
            assert r.status_code == 400, f"{bad}: {r.text}"

    def test_commitment_string_precision(self, user_a):
        body = {"title": f"TEST_pdec_{uuid.uuid4().hex[:6]}", "currency": "USD",
                "amount": "1234.5678", "commitment_type": "saving",
                "fixed_or_flexible": "flexible", "start_month": "2026-01"}
        r = requests.post(f"{API}/portfolio/monthly-money-commitments", json=body,
                          headers=user_a["h"], timeout=30)
        assert r.status_code == 201, r.text
        assert r.json()["amount"] == "1234.5678"

    def test_money_allocation_string_precision(self, user_a):
        body = {"resource_type": "money", "owner_type": "standalone", "owner_id": None,
                "allocation_mode": "one_time", "date": "2026-01-15",
                "quantity": "99.9500", "unit": "currency", "currency": "USD",
                "status": "proposed", "fixed_or_flexible": "flexible"}
        r = requests.post(f"{API}/portfolio/resource-allocations", json=body,
                          headers=user_a["h"], timeout=30)
        assert r.status_code == 201, r.text
        assert r.json()["quantity"] == "99.9500"

    def test_money_allocation_reject_nan(self, user_a):
        body = {"resource_type": "money", "owner_type": "standalone", "owner_id": None,
                "allocation_mode": "one_time", "date": "2026-01-15",
                "quantity": "NaN", "unit": "currency", "currency": "USD",
                "status": "proposed", "fixed_or_flexible": "flexible"}
        r = requests.post(f"{API}/portfolio/resource-allocations", json=body,
                          headers=user_a["h"], timeout=30)
        assert r.status_code == 400


# ==========================================================================
# Iteration 1A explicit money-position scenario (fresh user, exact numbers)
# ==========================================================================
class TestMoneyPositionIteration1A:
    def test_exact_scenario(self):
        tok, u = _signup()
        h = {"Authorization": f"Bearer {tok}"}

        # Assets: bank USD liquid 100.50, cash USD liquid 25.25,
        #         semi_liquid stock (excluded), credit_card USD (liability, excluded).
        for body in [
            {"account_type": "bank", "name": "TEST_bank", "currency": "USD",
             "current_value": "100.50", "liquidity_type": "liquid",
             "fixed_or_flexible": "flexible"},
            {"account_type": "cash", "name": "TEST_cash", "currency": "USD",
             "current_value": "25.25", "liquidity_type": "liquid",
             "fixed_or_flexible": "flexible"},
            {"account_type": "stock", "name": "TEST_stock", "currency": "USD",
             "current_value": "9999.99", "liquidity_type": "semi_liquid",
             "fixed_or_flexible": "flexible"},
            {"account_type": "credit_card", "name": "TEST_cc", "currency": "USD",
             "current_value": "300.00", "liquidity_type": "liquid",
             "fixed_or_flexible": "fixed"},
        ]:
            r = requests.post(f"{API}/portfolio/financial-accounts", json=body,
                              headers=h, timeout=30)
            assert r.status_code == 201, r.text

        # Commitments active for 2026-05, USD.
        for body in [
            {"title": "TEST_income", "currency": "USD", "amount": "500.25",
             "commitment_type": "income", "fixed_or_flexible": "fixed",
             "start_month": "2026-01"},
            {"title": "TEST_rent", "currency": "USD", "amount": "100.10",
             "commitment_type": "expense", "fixed_or_flexible": "fixed",
             "start_month": "2026-01"},
            {"title": "TEST_food", "currency": "USD", "amount": "50.05",
             "commitment_type": "expense", "fixed_or_flexible": "flexible",
             "start_month": "2026-01"},
            {"title": "TEST_save", "currency": "USD", "amount": "10.10",
             "commitment_type": "saving", "fixed_or_flexible": "fixed",
             "start_month": "2026-01"},
            {"title": "TEST_invest", "currency": "USD", "amount": "5.20",
             "commitment_type": "investment", "fixed_or_flexible": "fixed",
             "start_month": "2026-01"},
        ]:
            r = requests.post(f"{API}/portfolio/monthly-money-commitments",
                              json=body, headers=h, timeout=30)
            assert r.status_code == 201, r.text

        r = requests.get(f"{API}/portfolio/money-position",
                         params={"month": "2026-05", "currency": "USD"},
                         headers=h, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["opening_liquid_assets"] == "125.75", d
        assert d["planned_income"] == "500.25", d
        assert d["fixed_outflows"] == "100.10", d
        assert d["flexible_outflows"] == "50.05", d
        assert d["planned_savings"] == "10.10", d
        assert d["planned_investments"] == "5.20", d
        assert d["available_for_flexible_spending"] == "460.55", d
        # Every money field must be a JSON string, never a float.
        for k in ("opening_liquid_assets", "planned_income", "fixed_outflows",
                  "flexible_outflows", "planned_savings", "planned_investments",
                  "available_for_flexible_spending"):
            assert isinstance(d[k], str), f"{k} is {type(d[k])}"

    def test_empty_currency_returns_zeros(self):
        tok, u = _signup()
        h = {"Authorization": f"Bearer {tok}"}
        r = requests.get(f"{API}/portfolio/money-position",
                         params={"month": "2026-05", "currency": "JPY"},
                         headers=h, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("opening_liquid_assets", "planned_income", "fixed_outflows",
                  "flexible_outflows", "planned_savings", "planned_investments",
                  "available_for_flexible_spending"):
            assert d[k] == "0.00", f"{k}={d[k]}"


# ==========================================================================
# PUT owner-integrity: switching owner to nonexistent / foreign user rejects
# and does NOT mutate the persisted row.
# ==========================================================================
class TestAllocationUpdateOwnerIntegrity:
    def test_put_reject_nonexistent_and_foreign(self, user_a, user_b):
        # Seed a valid standalone money allocation on user_a.
        body = {"resource_type": "money", "owner_type": "standalone",
                "owner_id": None, "allocation_mode": "one_time",
                "date": "2026-02-01", "quantity": "42.42", "unit": "currency",
                "currency": "USD", "status": "proposed",
                "fixed_or_flexible": "flexible"}
        r = requests.post(f"{API}/portfolio/resource-allocations", json=body,
                          headers=user_a["h"], timeout=30)
        assert r.status_code == 201, r.text
        aid = r.json()["id"]

        # PUT switch to task/nonexistent uuid -> 400
        r = requests.put(f"{API}/portfolio/resource-allocations/{aid}",
                         json={"owner_type": "task",
                               "owner_id": str(uuid.uuid4())},
                         headers=user_a["h"], timeout=30)
        assert r.status_code == 400, r.text

        # PUT switch to user_b's task -> 400
        r = requests.put(f"{API}/portfolio/resource-allocations/{aid}",
                         json={"owner_type": "task",
                               "owner_id": user_b["owners"]["task"]},
                         headers=user_a["h"], timeout=30)
        assert r.status_code == 400, r.text

        # Persisted row unchanged: still standalone, quantity 42.42.
        r = requests.get(f"{API}/portfolio/resource-allocations",
                         headers=user_a["h"], timeout=30)
        assert r.status_code == 200
        row = next((x for x in r.json() if x["id"] == aid), None)
        assert row is not None
        assert row["owner_type"] == "standalone"
        assert row["owner_id"] is None
        assert row["quantity"] == "42.42"


# ==========================================================================
# Regression: existing surface still works (deps.py extraction)
# ==========================================================================
class TestExistingSurfaceRegression:
    def test_auth_me(self, user_a):
        r = requests.get(f"{API}/auth/me", headers=user_a["h"], timeout=30)
        assert r.status_code == 200
        assert r.json()["id"] == user_a["user"]["id"]

    def test_list_domains(self, user_a):
        r = requests.get(f"{API}/domains", headers=user_a["h"], timeout=30)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_list_goals_tasks_checkins(self, user_a):
        for path in ("/goals", "/tasks", "/checkins"):
            r = requests.get(f"{API}{path}", headers=user_a["h"], timeout=30)
            assert r.status_code == 200, f"{path}: {r.text}"
            assert isinstance(r.json(), list)

    def test_knowledge_journey_create(self, user_a):
        body = {
            "title": "TEST_regress_kj",
            "why": "regression",
            "journey_type": "skill",
            "has_stages": False,
            "stages": [],
            "target_completion_date": "",
            "checkin_cadence": "weekly",
            "first_outcome": {"title": "TEST_eo"},
            "first_task": {"title": "TEST_task", "priority": "medium"},
        }
        r = requests.post(f"{API}/knowledge/journeys", json=body, headers=user_a["h"], timeout=30)
        assert r.status_code == 201, r.text
        assert r.json()["title"] == "TEST_regress_kj"

    def test_list_knowledge_journeys(self, user_a):
        r = requests.get(f"{API}/knowledge/journeys", headers=user_a["h"], timeout=30)
        assert r.status_code == 200
