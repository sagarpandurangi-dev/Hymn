"""Backend tests for the Portfolio Manager foundation.

Covers:
- CRUD + validation for time_commitments, financial_accounts,
  monthly_money_commitments and resource_allocations
- User isolation for every collection
- Ownership validation on resource_allocations
- Time overlap union calculation (pure helper + endpoint)
- Daily and weekly time capacity endpoints
- Monthly money position calculation
- Idempotent index creation
- Basic regression on the existing goals/domains surface
"""
from __future__ import annotations

import os
import time
import uuid
from typing import Optional

import pytest
import requests

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _signup(email: str, password: str = "PortfolioTest123!") -> str:
    r = requests.post(
        f"{API}/auth/signup",
        json={
            "email": email, "password": password,
            "security_question": "q?", "security_answer": "a",
        },
        timeout=15,
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


def _hdrs(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def token() -> str:
    return _signup(f"portfolio.a.{uuid.uuid4().hex[:8]}@hymn.app")


@pytest.fixture(scope="module")
def other_token() -> str:
    return _signup(f"portfolio.b.{uuid.uuid4().hex[:8]}@hymn.app")


# ---------------------------------------------------------------------------
# TIME COMMITMENTS
# ---------------------------------------------------------------------------

def _tc_payload(**over) -> dict:
    base = {
        "title": "Sleep",
        "day_of_week": "monday",
        "start_time": "22:00",
        "end_time": "23:59",
        "commitment_type": "sleep",
        "flexibility": "fixed",
        "effective_from": "2026-01-01",
        "effective_until": None,
        "source_type": "manual",
        "source_id": None,
        "notes": "",
    }
    base.update(over)
    return base


class TestTimeCommitmentsCrud:
    def test_requires_auth(self):
        assert requests.get(f"{API}/portfolio/time-commitments", timeout=10).status_code == 401
        assert requests.post(f"{API}/portfolio/time-commitments", json=_tc_payload(), timeout=10).status_code == 401

    def test_create_and_list(self, token):
        r = requests.post(f"{API}/portfolio/time-commitments", json=_tc_payload(), headers=_hdrs(token), timeout=10)
        assert r.status_code == 201, r.text
        got = r.json()
        assert got["id"] and got["title"] == "Sleep" and got["day_of_week"] == "monday"
        assert got["effective_until"] is None

        r = requests.get(f"{API}/portfolio/time-commitments", headers=_hdrs(token), timeout=10)
        assert r.status_code == 200
        assert any(x["id"] == got["id"] for x in r.json())

    def test_reject_end_before_start(self, token):
        r = requests.post(
            f"{API}/portfolio/time-commitments",
            json=_tc_payload(start_time="10:00", end_time="09:00"),
            headers=_hdrs(token), timeout=10,
        )
        assert r.status_code == 400
        assert "end_time" in r.json()["detail"].lower()

    def test_reject_cross_midnight(self, token):
        r = requests.post(
            f"{API}/portfolio/time-commitments",
            json=_tc_payload(start_time="23:30", end_time="24:30"),
            headers=_hdrs(token), timeout=10,
        )
        assert r.status_code in (400, 422)

    def test_reject_bad_enums(self, token):
        for field, bad in [("day_of_week", "funday"), ("commitment_type", "yoga"),
                            ("flexibility", "sort_of"), ("source_type", "cosmic")]:
            r = requests.post(
                f"{API}/portfolio/time-commitments",
                json=_tc_payload(**{field: bad}),
                headers=_hdrs(token), timeout=10,
            )
            assert r.status_code == 400, f"{field}={bad} should 400"

    def test_reject_bad_time_format(self, token):
        r = requests.post(
            f"{API}/portfolio/time-commitments",
            json=_tc_payload(start_time="9am", end_time="10am"),
            headers=_hdrs(token), timeout=10,
        )
        assert r.status_code == 400

    def test_reject_effective_until_before_from(self, token):
        r = requests.post(
            f"{API}/portfolio/time-commitments",
            json=_tc_payload(effective_from="2026-06-01", effective_until="2026-01-01"),
            headers=_hdrs(token), timeout=10,
        )
        assert r.status_code == 400

    def test_update_and_delete(self, token):
        r = requests.post(f"{API}/portfolio/time-commitments",
                          json=_tc_payload(title="temp", day_of_week="tuesday"),
                          headers=_hdrs(token), timeout=10)
        cid = r.json()["id"]

        r = requests.put(
            f"{API}/portfolio/time-commitments/{cid}",
            json={"title": "renamed", "end_time": "23:30"},
            headers=_hdrs(token), timeout=10,
        )
        assert r.status_code == 200 and r.json()["title"] == "renamed"

        r = requests.delete(f"{API}/portfolio/time-commitments/{cid}", headers=_hdrs(token), timeout=10)
        assert r.status_code == 200

        r = requests.put(f"{API}/portfolio/time-commitments/{cid}",
                         json={"title": "x"}, headers=_hdrs(token), timeout=10)
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# FINANCIAL ACCOUNTS
# ---------------------------------------------------------------------------

def _acct_payload(**over) -> dict:
    base = {
        "account_type": "bank",
        "name": "Savings A",
        "currency": "INR",
        "current_value": 50000.00,
        "liquidity_type": "liquid",
        "fixed_or_flexible": "flexible",
        "notes": "",
    }
    base.update(over)
    return base


class TestFinancialAccountsCrud:
    def test_create_and_list(self, token):
        r = requests.post(f"{API}/portfolio/financial-accounts", json=_acct_payload(),
                          headers=_hdrs(token), timeout=10)
        assert r.status_code == 201, r.text
        got = r.json()
        assert got["id"] and got["currency"] == "INR"

        r = requests.get(f"{API}/portfolio/financial-accounts?currency=INR",
                         headers=_hdrs(token), timeout=10)
        assert r.status_code == 200
        assert any(x["id"] == got["id"] for x in r.json())

    def test_reject_negative_value(self, token):
        r = requests.post(f"{API}/portfolio/financial-accounts",
                          json=_acct_payload(current_value=-1),
                          headers=_hdrs(token), timeout=10)
        assert r.status_code == 400

    def test_reject_bad_currency(self, token):
        r = requests.post(f"{API}/portfolio/financial-accounts",
                          json=_acct_payload(currency="rupees"),
                          headers=_hdrs(token), timeout=10)
        assert r.status_code == 400

    def test_reject_unknown_account_type(self, token):
        r = requests.post(f"{API}/portfolio/financial-accounts",
                          json=_acct_payload(account_type="magic_beans"),
                          headers=_hdrs(token), timeout=10)
        assert r.status_code == 400

    def test_liability_stored_positive(self, token):
        r = requests.post(f"{API}/portfolio/financial-accounts",
                          json=_acct_payload(account_type="credit_card", name="Amex",
                                              current_value=12000, liquidity_type="liquid"),
                          headers=_hdrs(token), timeout=10)
        assert r.status_code == 201
        assert r.json()["current_value"] == 12000.0

    def test_update_and_delete(self, token):
        r = requests.post(f"{API}/portfolio/financial-accounts",
                          json=_acct_payload(name="tmp"), headers=_hdrs(token), timeout=10)
        aid = r.json()["id"]
        r = requests.put(f"{API}/portfolio/financial-accounts/{aid}",
                         json={"current_value": 75000},
                         headers=_hdrs(token), timeout=10)
        assert r.status_code == 200 and r.json()["current_value"] == 75000.0
        r = requests.delete(f"{API}/portfolio/financial-accounts/{aid}",
                            headers=_hdrs(token), timeout=10)
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# MONTHLY MONEY COMMITMENTS
# ---------------------------------------------------------------------------

def _mmc_payload(**over) -> dict:
    base = {
        "title": "Salary",
        "currency": "INR",
        "amount": 100000,
        "commitment_type": "income",
        "fixed_or_flexible": "fixed",
        "start_month": "2026-01",
        "end_month": None,
        "source_type": "manual",
        "notes": "",
    }
    base.update(over)
    return base


class TestMonthlyMoneyCommitments:
    def test_create_and_list(self, token):
        r = requests.post(f"{API}/portfolio/monthly-money-commitments",
                          json=_mmc_payload(), headers=_hdrs(token), timeout=10)
        assert r.status_code == 201, r.text
        assert r.json()["end_month"] is None

    def test_reject_negative_amount(self, token):
        r = requests.post(f"{API}/portfolio/monthly-money-commitments",
                          json=_mmc_payload(amount=-1), headers=_hdrs(token), timeout=10)
        assert r.status_code == 400

    def test_reject_end_before_start(self, token):
        r = requests.post(f"{API}/portfolio/monthly-money-commitments",
                          json=_mmc_payload(start_month="2026-06", end_month="2026-03"),
                          headers=_hdrs(token), timeout=10)
        assert r.status_code == 400

    def test_reject_bad_month_format(self, token):
        r = requests.post(f"{API}/portfolio/monthly-money-commitments",
                          json=_mmc_payload(start_month="Jan-2026"),
                          headers=_hdrs(token), timeout=10)
        assert r.status_code == 400

    def test_reject_bad_type(self, token):
        r = requests.post(f"{API}/portfolio/monthly-money-commitments",
                          json=_mmc_payload(commitment_type="tithing"),
                          headers=_hdrs(token), timeout=10)
        assert r.status_code == 400

    def test_update_and_delete(self, token):
        r = requests.post(f"{API}/portfolio/monthly-money-commitments",
                          json=_mmc_payload(title="tmp"), headers=_hdrs(token), timeout=10)
        cid = r.json()["id"]
        r = requests.put(f"{API}/portfolio/monthly-money-commitments/{cid}",
                         json={"amount": 5}, headers=_hdrs(token), timeout=10)
        assert r.status_code == 200
        r = requests.delete(f"{API}/portfolio/monthly-money-commitments/{cid}",
                            headers=_hdrs(token), timeout=10)
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# RESOURCE ALLOCATIONS
# ---------------------------------------------------------------------------

def _time_alloc_one_time(**over) -> dict:
    base = {
        "resource_type": "time", "owner_type": "standalone", "owner_id": None,
        "allocation_mode": "one_time",
        "date": "2026-05-05", "day_of_week": None,
        "start_time": "09:00", "end_time": "10:30",
        "quantity": 90, "unit": "minutes", "currency": None,
        "status": "proposed", "fixed_or_flexible": "flexible",
    }
    base.update(over)
    return base


def _time_alloc_recurring(**over) -> dict:
    base = {
        "resource_type": "time", "owner_type": "task", "owner_id": "fake-task-id",
        "allocation_mode": "recurring",
        "date": None, "day_of_week": "tuesday",
        "start_time": "18:00", "end_time": "19:00",
        "quantity": 60, "unit": "minutes", "currency": None,
        "status": "reserved", "fixed_or_flexible": "flexible",
    }
    base.update(over)
    return base


def _money_alloc_one_time(**over) -> dict:
    base = {
        "resource_type": "money", "owner_type": "project", "owner_id": "proj-1",
        "allocation_mode": "one_time",
        "date": "2026-05-05", "day_of_week": None,
        "start_time": None, "end_time": None,
        "quantity": 500, "unit": "currency", "currency": "INR",
        "status": "proposed", "fixed_or_flexible": "fixed",
    }
    base.update(over)
    return base


def _money_alloc_recurring(**over) -> dict:
    base = {
        "resource_type": "money", "owner_type": "knowledge_journey",
        "owner_id": "kj-1", "allocation_mode": "recurring",
        "date": None, "day_of_week": None,
        "start_time": None, "end_time": None,
        "quantity": 200, "unit": "currency", "currency": "USD",
        "status": "proposed", "fixed_or_flexible": "flexible",
    }
    base.update(over)
    return base


class TestResourceAllocationsValidation:
    def test_time_one_time_happy(self, token):
        r = requests.post(f"{API}/portfolio/resource-allocations",
                          json=_time_alloc_one_time(), headers=_hdrs(token), timeout=10)
        assert r.status_code == 201, r.text

    def test_time_recurring_happy(self, token):
        r = requests.post(f"{API}/portfolio/resource-allocations",
                          json=_time_alloc_recurring(), headers=_hdrs(token), timeout=10)
        assert r.status_code == 201, r.text

    def test_money_one_time_happy(self, token):
        r = requests.post(f"{API}/portfolio/resource-allocations",
                          json=_money_alloc_one_time(), headers=_hdrs(token), timeout=10)
        assert r.status_code == 201, r.text

    def test_money_recurring_no_date(self, token):
        r = requests.post(f"{API}/portfolio/resource-allocations",
                          json=_money_alloc_recurring(), headers=_hdrs(token), timeout=10)
        assert r.status_code == 201, r.text

    # -- ownership rules
    def test_standalone_rejects_owner_id(self, token):
        r = requests.post(f"{API}/portfolio/resource-allocations",
                          json=_time_alloc_one_time(owner_type="standalone", owner_id="ghost"),
                          headers=_hdrs(token), timeout=10)
        assert r.status_code == 400

    def test_non_standalone_requires_owner_id(self, token):
        r = requests.post(f"{API}/portfolio/resource-allocations",
                          json=_time_alloc_one_time(owner_type="task", owner_id=None),
                          headers=_hdrs(token), timeout=10)
        assert r.status_code == 400

    def test_owner_type_goal_forbidden(self, token):
        # The spec explicitly forbids goal / expected_outcome / etc.
        for bad in ("goal", "expected_outcome", "check_in", "component", "domain", "external"):
            r = requests.post(f"{API}/portfolio/resource-allocations",
                              json=_time_alloc_one_time(owner_type=bad, owner_id="x"),
                              headers=_hdrs(token), timeout=10)
            assert r.status_code == 400, f"owner_type={bad} must be rejected"

    # -- time validations
    def test_time_one_time_requires_date(self, token):
        r = requests.post(f"{API}/portfolio/resource-allocations",
                          json=_time_alloc_one_time(date=None),
                          headers=_hdrs(token), timeout=10)
        assert r.status_code == 400

    def test_time_one_time_forbids_day_of_week(self, token):
        r = requests.post(f"{API}/portfolio/resource-allocations",
                          json=_time_alloc_one_time(day_of_week="monday"),
                          headers=_hdrs(token), timeout=10)
        assert r.status_code == 400

    def test_time_recurring_forbids_date(self, token):
        r = requests.post(f"{API}/portfolio/resource-allocations",
                          json=_time_alloc_recurring(date="2026-05-05"),
                          headers=_hdrs(token), timeout=10)
        assert r.status_code == 400

    def test_time_recurring_requires_day(self, token):
        r = requests.post(f"{API}/portfolio/resource-allocations",
                          json=_time_alloc_recurring(day_of_week=None),
                          headers=_hdrs(token), timeout=10)
        assert r.status_code == 400

    def test_time_quantity_must_equal_duration(self, token):
        r = requests.post(f"{API}/portfolio/resource-allocations",
                          json=_time_alloc_one_time(quantity=45),
                          headers=_hdrs(token), timeout=10)
        assert r.status_code == 400
        assert "duration" in r.json()["detail"].lower()

    def test_time_forbids_currency(self, token):
        r = requests.post(f"{API}/portfolio/resource-allocations",
                          json=_time_alloc_one_time(currency="INR"),
                          headers=_hdrs(token), timeout=10)
        assert r.status_code == 400

    # -- money validations
    def test_money_requires_currency(self, token):
        r = requests.post(f"{API}/portfolio/resource-allocations",
                          json=_money_alloc_one_time(currency=None),
                          headers=_hdrs(token), timeout=10)
        assert r.status_code == 400

    def test_money_forbids_start_time(self, token):
        r = requests.post(f"{API}/portfolio/resource-allocations",
                          json=_money_alloc_one_time(start_time="09:00"),
                          headers=_hdrs(token), timeout=10)
        assert r.status_code == 400

    def test_money_rejects_negative_quantity(self, token):
        r = requests.post(f"{API}/portfolio/resource-allocations",
                          json=_money_alloc_one_time(quantity=-1),
                          headers=_hdrs(token), timeout=10)
        assert r.status_code == 400

    def test_money_one_time_requires_date(self, token):
        r = requests.post(f"{API}/portfolio/resource-allocations",
                          json=_money_alloc_one_time(date=None),
                          headers=_hdrs(token), timeout=10)
        assert r.status_code == 400

    def test_list_filter_by_resource_type(self, token):
        r = requests.get(f"{API}/portfolio/resource-allocations?resource_type=money",
                         headers=_hdrs(token), timeout=10)
        assert r.status_code == 200
        for row in r.json():
            assert row["resource_type"] == "money"

    def test_update_and_delete(self, token):
        r = requests.post(f"{API}/portfolio/resource-allocations",
                          json=_time_alloc_one_time(), headers=_hdrs(token), timeout=10)
        aid = r.json()["id"]
        r = requests.put(f"{API}/portfolio/resource-allocations/{aid}",
                         json={"status": "consumed"}, headers=_hdrs(token), timeout=10)
        assert r.status_code == 200 and r.json()["status"] == "consumed"
        r = requests.delete(f"{API}/portfolio/resource-allocations/{aid}",
                            headers=_hdrs(token), timeout=10)
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# USER ISOLATION
# ---------------------------------------------------------------------------

class TestUserIsolation:
    def test_time_commitments_isolated(self, token, other_token):
        r = requests.post(f"{API}/portfolio/time-commitments",
                          json=_tc_payload(title="A only", day_of_week="wednesday"),
                          headers=_hdrs(token), timeout=10)
        cid = r.json()["id"]
        r = requests.get(f"{API}/portfolio/time-commitments", headers=_hdrs(other_token), timeout=10)
        assert r.status_code == 200
        assert not any(x["id"] == cid for x in r.json())
        # cross-user delete / update = 404
        r = requests.delete(f"{API}/portfolio/time-commitments/{cid}",
                            headers=_hdrs(other_token), timeout=10)
        assert r.status_code == 404
        r = requests.put(f"{API}/portfolio/time-commitments/{cid}",
                         json={"title": "steal"}, headers=_hdrs(other_token), timeout=10)
        assert r.status_code == 404

    def test_accounts_isolated(self, token, other_token):
        r = requests.post(f"{API}/portfolio/financial-accounts",
                          json=_acct_payload(name="A vault"),
                          headers=_hdrs(token), timeout=10)
        aid = r.json()["id"]
        r = requests.get(f"{API}/portfolio/financial-accounts", headers=_hdrs(other_token), timeout=10)
        assert not any(x["id"] == aid for x in r.json())

    def test_money_commitments_isolated(self, token, other_token):
        r = requests.post(f"{API}/portfolio/monthly-money-commitments",
                          json=_mmc_payload(title="A salary"),
                          headers=_hdrs(token), timeout=10)
        cid = r.json()["id"]
        r = requests.get(f"{API}/portfolio/monthly-money-commitments",
                         headers=_hdrs(other_token), timeout=10)
        assert not any(x["id"] == cid for x in r.json())

    def test_allocations_isolated(self, token, other_token):
        r = requests.post(f"{API}/portfolio/resource-allocations",
                          json=_time_alloc_one_time(date="2027-01-01"),
                          headers=_hdrs(token), timeout=10)
        aid = r.json()["id"]
        r = requests.get(f"{API}/portfolio/resource-allocations",
                         headers=_hdrs(other_token), timeout=10)
        assert not any(x["id"] == aid for x in r.json())


# ---------------------------------------------------------------------------
# TIME OVERLAP UNION (unit test on the helper)
# ---------------------------------------------------------------------------

class TestTimeUnionHelper:
    def test_helper_math(self):
        from portfolio_manager import compute_time_union_and_overlap
        # No overlap
        assert compute_time_union_and_overlap([(0, 60), (120, 180)]) == (120, 0)
        # Full overlap
        assert compute_time_union_and_overlap([(0, 60), (0, 60)]) == (60, 60)
        # Partial overlap
        assert compute_time_union_and_overlap([(0, 60), (30, 90)]) == (90, 30)
        # Touching intervals merge cleanly
        assert compute_time_union_and_overlap([(0, 30), (30, 60)]) == (60, 0)
        # Nested interval
        assert compute_time_union_and_overlap([(0, 120), (30, 60)]) == (120, 30)
        # Empty
        assert compute_time_union_and_overlap([]) == (0, 0)


# ---------------------------------------------------------------------------
# TIME CAPACITY (daily + weekly)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def capacity_token() -> str:
    tok = _signup(f"portfolio.cap.{uuid.uuid4().hex[:8]}@hymn.app")
    # Seed a set of commitments on a Monday 2026-01-05.
    #  * Sleep 22:00 – 23:59 (119 min)                          — fixed
    #  * Work  09:00 – 17:00 (480 min)                          — fixed
    #  * Meeting 10:00 – 11:00 (60 min, overlaps Work)          — flexible
    #  * Meal   12:00 – 13:00 (60 min, overlaps Work)           — fixed
    # Expected union for that Monday: 22-23:59 (119) + 09-17 (480) = 599
    # Expected overlap: (119+480+60+60) - 599 = 120
    for c in [
        _tc_payload(title="Sleep", day_of_week="monday", start_time="22:00", end_time="23:59",
                    commitment_type="sleep", flexibility="fixed", effective_from="2026-01-01"),
        _tc_payload(title="Work",  day_of_week="monday", start_time="09:00", end_time="17:00",
                    commitment_type="work",  flexibility="fixed", effective_from="2026-01-01"),
        _tc_payload(title="Team meeting", day_of_week="monday",
                    start_time="10:00", end_time="11:00",
                    commitment_type="work", flexibility="flexible", effective_from="2026-01-01"),
        _tc_payload(title="Lunch", day_of_week="monday",
                    start_time="12:00", end_time="13:00",
                    commitment_type="meal", flexibility="fixed", effective_from="2026-01-01"),
        # Wednesday: single 60-minute commitment
        _tc_payload(title="Yoga", day_of_week="wednesday",
                    start_time="06:30", end_time="07:30",
                    commitment_type="personal", flexibility="flexible",
                    effective_from="2026-01-01"),
        # Friday-only commitment effective only in Feb (should not count on Jan 9)
        _tc_payload(title="Feb-only class", day_of_week="friday",
                    start_time="19:00", end_time="20:00",
                    commitment_type="personal", flexibility="flexible",
                    effective_from="2026-02-01", effective_until="2026-02-28"),
    ]:
        r = requests.post(f"{API}/portfolio/time-commitments", json=c, headers=_hdrs(tok), timeout=10)
        assert r.status_code == 201, r.text
    return tok


class TestTimeCapacity:
    def test_daily_capacity_math(self, capacity_token):
        r = requests.get(f"{API}/portfolio/time-capacity/day?date=2026-01-05",
                         headers=_hdrs(capacity_token), timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["date"] == "2026-01-05"
        assert body["day_of_week"] == "monday"
        assert body["total_minutes"] == 1440
        assert body["committed_minutes"] == 599
        assert body["available_minutes"] == 1440 - 599
        assert body["overlapping_minutes"] == 120
        assert len(body["commitments"]) == 4

    def test_effective_window_excludes_out_of_range(self, capacity_token):
        # Jan 9 is Friday. Only "Feb-only class" (Feb) is a Friday commitment;
        # it must NOT count on Jan 9. Expected commitments: 0.
        r = requests.get(f"{API}/portfolio/time-capacity/day?date=2026-01-09",
                         headers=_hdrs(capacity_token), timeout=10)
        body = r.json()
        assert body["day_of_week"] == "friday"
        assert body["committed_minutes"] == 0
        assert body["overlapping_minutes"] == 0
        assert body["available_minutes"] == 1440

    def test_weekly_requires_monday(self, capacity_token):
        r = requests.get(f"{API}/portfolio/time-capacity/week?week_start_date=2026-01-06",
                         headers=_hdrs(capacity_token), timeout=10)
        assert r.status_code == 400

    def test_weekly_seven_days(self, capacity_token):
        r = requests.get(f"{API}/portfolio/time-capacity/week?week_start_date=2026-01-05",
                         headers=_hdrs(capacity_token), timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert len(body["days"]) == 7
        assert [d["day_of_week"] for d in body["days"]] == list(
            ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        )
        # Wednesday should show the 60 min yoga.
        wed = body["days"][2]
        assert wed["committed_minutes"] == 60

    def test_bad_date_format(self, capacity_token):
        r = requests.get(f"{API}/portfolio/time-capacity/day?date=05-01-2026",
                         headers=_hdrs(capacity_token), timeout=10)
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# MONEY POSITION
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def position_token() -> str:
    tok = _signup(f"portfolio.pos.{uuid.uuid4().hex[:8]}@hymn.app")
    # Assets
    for a in [
        _acct_payload(account_type="bank", name="Bank", currency="INR", current_value=100000,
                      liquidity_type="liquid"),
        _acct_payload(account_type="cash", name="Cash", currency="INR", current_value=25000,
                      liquidity_type="liquid"),
        _acct_payload(account_type="stock", name="Stocks", currency="INR", current_value=200000,
                      liquidity_type="semi_liquid"),  # NOT counted (not liquid)
        _acct_payload(account_type="bank", name="US Bank", currency="USD", current_value=1000,
                      liquidity_type="liquid"),  # NOT counted (wrong currency)
        # Liability — must be excluded from opening_liquid_assets.
        _acct_payload(account_type="credit_card", name="Card", currency="INR",
                      current_value=15000, liquidity_type="liquid"),
    ]:
        r = requests.post(f"{API}/portfolio/financial-accounts", json=a, headers=_hdrs(tok), timeout=10)
        assert r.status_code == 201, r.text

    # Commitments active in 2026-05
    for c in [
        _mmc_payload(title="Salary", currency="INR", amount=80000,
                     commitment_type="income", fixed_or_flexible="fixed",
                     start_month="2026-01"),
        _mmc_payload(title="Rent", currency="INR", amount=25000,
                     commitment_type="expense", fixed_or_flexible="fixed",
                     start_month="2026-01"),
        _mmc_payload(title="Loan EMI", currency="INR", amount=10000,
                     commitment_type="debt_payment", fixed_or_flexible="fixed",
                     start_month="2026-01"),
        _mmc_payload(title="Groceries", currency="INR", amount=12000,
                     commitment_type="expense", fixed_or_flexible="flexible",
                     start_month="2026-01"),
        _mmc_payload(title="Emergency fund", currency="INR", amount=5000,
                     commitment_type="saving", fixed_or_flexible="fixed",
                     start_month="2026-01"),
        _mmc_payload(title="Index SIP", currency="INR", amount=8000,
                     commitment_type="investment", fixed_or_flexible="fixed",
                     start_month="2026-01"),
        # Ends before May (must be excluded)
        _mmc_payload(title="Old subscription", currency="INR", amount=2000,
                     commitment_type="expense", fixed_or_flexible="flexible",
                     start_month="2026-01", end_month="2026-03"),
        # USD commitment (must be excluded from INR position)
        _mmc_payload(title="AWS", currency="USD", amount=50,
                     commitment_type="expense", fixed_or_flexible="flexible",
                     start_month="2026-01"),
    ]:
        r = requests.post(f"{API}/portfolio/monthly-money-commitments",
                          json=c, headers=_hdrs(tok), timeout=10)
        assert r.status_code == 201, r.text
    return tok


class TestMoneyPosition:
    def test_position_math(self, position_token):
        r = requests.get(f"{API}/portfolio/money-position?month=2026-05&currency=INR",
                         headers=_hdrs(position_token), timeout=10)
        assert r.status_code == 200, r.text
        b = r.json()
        # Assets: Bank 100000 + Cash 25000 = 125000
        # (Stocks excluded — semi_liquid, US bank excluded — USD, CC excluded — liability)
        assert b["opening_liquid_assets"] == 125000.00
        assert b["planned_income"] == 80000.00
        # Fixed outflows: Rent 25000 + Loan EMI 10000 = 35000
        assert b["fixed_outflows"] == 35000.00
        # Flexible outflows: Groceries 12000  (Old subscription excluded)
        assert b["flexible_outflows"] == 12000.00
        assert b["planned_savings"] == 5000.00
        assert b["planned_investments"] == 8000.00
        expected = 125000 + 80000 - 35000 - 12000 - 5000 - 8000
        assert b["available_for_flexible_spending"] == float(expected)

    def test_position_bad_month(self, position_token):
        r = requests.get(f"{API}/portfolio/money-position?month=May-2026&currency=INR",
                         headers=_hdrs(position_token), timeout=10)
        assert r.status_code == 400

    def test_position_bad_currency(self, position_token):
        r = requests.get(f"{API}/portfolio/money-position?month=2026-05&currency=rupee",
                         headers=_hdrs(position_token), timeout=10)
        assert r.status_code == 400

    def test_position_wrong_currency_returns_zeroes(self, position_token):
        r = requests.get(f"{API}/portfolio/money-position?month=2026-05&currency=EUR",
                         headers=_hdrs(position_token), timeout=10)
        b = r.json()
        assert b["opening_liquid_assets"] == 0
        assert b["planned_income"] == 0
        assert b["available_for_flexible_spending"] == 0


# ---------------------------------------------------------------------------
# INDEX BOOTSTRAP IDEMPOTENCY
# ---------------------------------------------------------------------------

class TestIndexBootstrap:
    def test_ensure_portfolio_indexes_idempotent(self):
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        from portfolio_manager import ensure_portfolio_indexes

        mongo_url = os.environ["MONGO_URL"]
        db_name = os.environ["DB_NAME"]
        loop = asyncio.new_event_loop()
        try:
            async def run() -> list:
                client = AsyncIOMotorClient(mongo_url)
                database = client[db_name]
                # Call twice — must not throw and must not create duplicates.
                await ensure_portfolio_indexes(database)
                await ensure_portfolio_indexes(database)
                names = {
                    coll: sorted(await database[coll].index_information())
                    for coll in [
                        "time_commitments", "financial_accounts",
                        "monthly_money_commitments", "resource_allocations",
                    ]
                }
                client.close()
                return names

            names = loop.run_until_complete(run())
        finally:
            loop.close()

        for coll, idxs in names.items():
            # Every collection should have at least a couple of indexes plus _id_.
            assert "_id_" in idxs, coll
            assert len(idxs) >= 3, f"{coll} indexes={idxs}"


# ---------------------------------------------------------------------------
# EXISTING BACKEND REGRESSION SMOKE
# ---------------------------------------------------------------------------

class TestExistingSurfaceRegression:
    def test_domains_still_seeded(self, token):
        r = requests.get(f"{API}/domains", headers=_hdrs(token), timeout=10)
        assert r.status_code == 200
        names = {d["name"] for d in r.json()}
        assert {"Knowledge", "Health", "Money", "Soul"}.issubset(names)

    def test_goals_still_work(self, token):
        r = requests.get(f"{API}/domains", headers=_hdrs(token), timeout=10)
        knowledge = next(d for d in r.json() if d["name"] == "Knowledge")
        r = requests.post(
            f"{API}/goals",
            json={"title": "regression", "domain_id": knowledge["id"], "status": "active"},
            headers=_hdrs(token), timeout=10,
        )
        assert r.status_code == 201, r.text
        r = requests.get(f"{API}/goals", headers=_hdrs(token), timeout=10)
        assert r.status_code == 200

    def test_outcome_types_still_work(self, token):
        r = requests.get(f"{API}/outcome-types", headers=_hdrs(token), timeout=10)
        assert r.status_code == 200
        assert "types" in r.json()
