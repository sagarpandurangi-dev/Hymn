"""Backend tests: Task Deferment + Check-in Money Spent + Spending endpoint + Money Position actual_spending.

Live HTTP against EXPO_PUBLIC_BACKEND_URL. No mocks. Each scenario provisions
its own TEST_ user so scenarios are independent.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

DEFAULTS = {"Knowledge", "Health", "Money", "Soul"}


# ------------------------- helpers ----------------------------------------
def _signup(email: str, password: str = "TestPass123!") -> str:
    r = requests.post(
        f"{API}/auth/signup",
        json={"email": email, "password": password, "security_question": "q?", "security_answer": "a"},
        timeout=15,
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


def _h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _first_default_domain_id(tok: str) -> str:
    lst = requests.get(f"{API}/domains", headers=_h(tok), timeout=10).json()
    for d in lst:
        if d["name"] in DEFAULTS:
            return d["id"]
    raise AssertionError("no default domain found")


def _mk_goal(tok: str, title: str = "TEST_goal") -> dict:
    did = _first_default_domain_id(tok)
    r = requests.post(f"{API}/goals", headers=_h(tok), json={"title": title, "domain_id": did}, timeout=10)
    assert r.status_code == 201, r.text
    return r.json()


def _mk_eo(tok: str, goal_id: str, title: str = "TEST_eo", status: str = "active") -> dict:
    r = requests.post(
        f"{API}/expected-outcomes",
        headers=_h(tok),
        json={"goal_id": goal_id, "title": title, "status": status},
        timeout=10,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _mk_task(tok: str, title: str, due_date: str = "", origin: str = "standalone", **extra) -> dict:
    body = {"title": title, "origin": origin}
    if due_date:
        body["due_date"] = due_date
    body.update(extra)
    r = requests.post(f"{API}/tasks", headers=_h(tok), json=body, timeout=10)
    assert r.status_code == 201, r.text
    return r.json()


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _today_offset(days: int) -> str:
    return (datetime.now(timezone.utc).date() + timedelta(days=days)).isoformat()


def _this_month() -> str:
    return datetime.now(timezone.utc).date().strftime("%Y-%m")


@pytest.fixture
def tok() -> str:
    return _signup(f"TEST_defer_{uuid.uuid4().hex[:8]}@hymn.app")


# ==========================================================================
# 1. Task deferment
# ==========================================================================
# Scenario dates: spec suggested 2026-06-01 baseline, but container clock is
# past that. We use a fixed strictly-future baseline (60 days out) so tests
# are reproducible regardless of "today". Semantics identical to the spec.
_BASE = _today_offset(60)               # baseline
_B_PLUS_4 = _today_offset(64)           # +4
_B_PLUS_9 = _today_offset(69)           # +9
_B_PLUS_14 = _today_offset(74)          # +14 (boundary, allowed)
_B_PLUS_15 = _today_offset(75)          # +15 (over cap, rejected)


class TestDeferHappyPath:
    """Chain of 3 defers all within +14 of baseline -> ok; 4th fails count cap."""

    def test_three_defers_ok_fourth_count_capped(self, tok):
        t = _mk_task(tok, "TEST_defer_chain", due_date=_BASE)
        assert t["defer_count"] == 0
        assert t["original_due_date"] == _BASE
        assert t["deferred_until"] is None

        # 1st defer -> +4
        r = requests.post(f"{API}/tasks/{t['id']}/defer", headers=_h(tok),
                          json={"deferred_until": _B_PLUS_4}, timeout=10)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["deferred_until"] == _B_PLUS_4
        assert j["defer_count"] == 1
        assert j["original_due_date"] == _BASE

        # 2nd defer -> +9
        r = requests.post(f"{API}/tasks/{t['id']}/defer", headers=_h(tok),
                          json={"deferred_until": _B_PLUS_9}, timeout=10)
        assert r.status_code == 200, r.text
        assert r.json()["defer_count"] == 2
        assert r.json()["deferred_until"] == _B_PLUS_9

        # 3rd defer -> +14 (boundary allowed)
        r = requests.post(f"{API}/tasks/{t['id']}/defer", headers=_h(tok),
                          json={"deferred_until": _B_PLUS_14}, timeout=10)
        assert r.status_code == 200, r.text
        assert r.json()["defer_count"] == 3
        assert r.json()["deferred_until"] == _B_PLUS_14

        # 4th defer -> should FAIL: count cap
        r = requests.post(f"{API}/tasks/{t['id']}/defer", headers=_h(tok),
                          json={"deferred_until": _B_PLUS_15}, timeout=10)
        assert r.status_code == 400
        assert "3" in r.json().get("detail", "").lower() or "deferred" in r.json().get("detail", "").lower()

    def test_persistence_via_get(self, tok):
        t = _mk_task(tok, "TEST_defer_persist", due_date=_BASE)
        requests.post(f"{API}/tasks/{t['id']}/defer", headers=_h(tok),
                      json={"deferred_until": _B_PLUS_4}, timeout=10)
        got = requests.get(f"{API}/tasks/{t['id']}", headers=_h(tok), timeout=10).json()
        assert got["defer_count"] == 1
        assert got["deferred_until"] == _B_PLUS_4
        assert got["original_due_date"] == _BASE


class TestDeferDayCap:
    def test_day_cap_boundary_pass_and_fail(self, tok):
        # +15 fails
        t1 = _mk_task(tok, "TEST_defer_15fail", due_date=_BASE)
        r = requests.post(f"{API}/tasks/{t1['id']}/defer", headers=_h(tok),
                          json={"deferred_until": _B_PLUS_15}, timeout=10)
        assert r.status_code == 400, r.text
        assert "14" in r.json().get("detail", "")
        # +14 passes on a fresh task
        t2 = _mk_task(tok, "TEST_defer_14pass", due_date=_BASE)
        r = requests.post(f"{API}/tasks/{t2['id']}/defer", headers=_h(tok),
                          json={"deferred_until": _B_PLUS_14}, timeout=10)
        assert r.status_code == 200, r.text
        assert r.json()["deferred_until"] == _B_PLUS_14


class TestDeferNoDueDate:
    def test_no_due_date_baseline_is_today(self, tok):
        t = _mk_task(tok, "TEST_defer_no_due")
        assert t["original_due_date"] is None
        # today+1 allowed
        r = requests.post(f"{API}/tasks/{t['id']}/defer", headers=_h(tok),
                          json={"deferred_until": _today_offset(1)}, timeout=10)
        assert r.status_code == 200, r.text
        j = r.json()
        # baseline is frozen to today after first defer
        assert j["original_due_date"] == _today()
        assert j["deferred_until"] == _today_offset(1)

    def test_no_due_date_beyond_14_fails(self, tok):
        t = _mk_task(tok, "TEST_defer_no_due_fail")
        r = requests.post(f"{API}/tasks/{t['id']}/defer", headers=_h(tok),
                          json={"deferred_until": _today_offset(15)}, timeout=10)
        assert r.status_code == 400
        assert "14" in r.json().get("detail", "")


class TestDeferInvalidDates:
    def test_past_date_400(self, tok):
        t = _mk_task(tok, "TEST_defer_past", due_date="2026-06-01")
        r = requests.post(f"{API}/tasks/{t['id']}/defer", headers=_h(tok),
                          json={"deferred_until": _today_offset(-1)}, timeout=10)
        assert r.status_code == 400
        assert "future" in r.json().get("detail", "").lower()

    def test_same_day_400(self, tok):
        t = _mk_task(tok, "TEST_defer_today", due_date="2026-06-01")
        r = requests.post(f"{API}/tasks/{t['id']}/defer", headers=_h(tok),
                          json={"deferred_until": _today()}, timeout=10)
        assert r.status_code == 400
        assert "future" in r.json().get("detail", "").lower()

    def test_malformed_date_400(self, tok):
        t = _mk_task(tok, "TEST_defer_bad", due_date="2026-06-01")
        r = requests.post(f"{API}/tasks/{t['id']}/defer", headers=_h(tok),
                          json={"deferred_until": "not-a-date"}, timeout=10)
        assert r.status_code == 400


class TestDeferDoneTask:
    def test_defer_done_task_400(self, tok):
        t = _mk_task(tok, "TEST_defer_done", due_date="2026-06-01")
        r = requests.put(f"{API}/tasks/{t['id']}", headers=_h(tok), json={"status": "done"}, timeout=10)
        assert r.status_code == 200 and r.json()["status"] == "done"
        r = requests.post(f"{API}/tasks/{t['id']}/defer", headers=_h(tok),
                          json={"deferred_until": "2026-06-05"}, timeout=10)
        assert r.status_code == 400
        assert "completed" in r.json().get("detail", "").lower() or "cancel" in r.json().get("detail", "").lower()

    def test_defer_nonexistent_404(self, tok):
        r = requests.post(f"{API}/tasks/does-not-exist/defer", headers=_h(tok),
                          json={"deferred_until": "2026-06-05"}, timeout=10)
        assert r.status_code == 404


class TestIncludeCompletedFilter:
    def test_default_and_false(self, tok):
        t_todo = _mk_task(tok, "TEST_ic_todo")
        t_done = _mk_task(tok, "TEST_ic_done")
        r = requests.put(f"{API}/tasks/{t_done['id']}", headers=_h(tok), json={"status": "done"}, timeout=10)
        assert r.status_code == 200

        # default: both visible
        lst_default = requests.get(f"{API}/tasks", headers=_h(tok), timeout=10).json()
        ids_default = {x["id"] for x in lst_default}
        assert t_todo["id"] in ids_default
        assert t_done["id"] in ids_default

        # explicit include_completed=true: both visible
        lst_true = requests.get(f"{API}/tasks?include_completed=true", headers=_h(tok), timeout=10).json()
        ids_true = {x["id"] for x in lst_true}
        assert t_todo["id"] in ids_true and t_done["id"] in ids_true

        # include_completed=false: only todo
        lst_false = requests.get(f"{API}/tasks?include_completed=false", headers=_h(tok), timeout=10).json()
        ids_false = {x["id"] for x in lst_false}
        assert t_todo["id"] in ids_false
        assert t_done["id"] not in ids_false


# ==========================================================================
# 2. Check-in with task_id + money_spent + complete_task
# ==========================================================================
class TestCheckinTaskUpdate:
    def _setup(self, tok):
        g = _mk_goal(tok, "TEST_g_chkupd")
        eo = _mk_eo(tok, g["id"], "eo_chkupd")
        t = requests.post(f"{API}/tasks", headers=_h(tok),
                          json={"title": "TEST_t_chkupd", "origin": "expected_outcome",
                                "expected_outcome_id": eo["id"]}, timeout=10).json()
        return g, eo, t

    def test_checkin_without_complete_task_bumps_updated_at(self, tok):
        _, eo, t = self._setup(tok)
        before = requests.get(f"{API}/tasks/{t['id']}", headers=_h(tok), timeout=10).json()
        r = requests.post(f"{API}/checkins", headers=_h(tok), json={
            "type": "goal", "title": "TEST_c_noc", "date": "2026-01-05", "time": "09:00",
            "expected_outcome_id": eo["id"], "task_id": t["id"],
        }, timeout=10)
        assert r.status_code == 201, r.text
        assert r.json()["task_id"] == t["id"]
        after = requests.get(f"{API}/tasks/{t['id']}", headers=_h(tok), timeout=10).json()
        assert after["status"] == "todo"
        assert after["updated_at"] >= before["updated_at"]

    def test_checkin_with_complete_task_flips_done(self, tok):
        _, eo, t = self._setup(tok)
        r = requests.post(f"{API}/checkins", headers=_h(tok), json={
            "type": "goal", "title": "TEST_c_c", "date": "2026-01-05", "time": "09:00",
            "expected_outcome_id": eo["id"], "task_id": t["id"], "complete_task": True,
        }, timeout=10)
        assert r.status_code == 201, r.text
        after = requests.get(f"{API}/tasks/{t['id']}", headers=_h(tok), timeout=10).json()
        assert after["status"] == "done"

    def test_task_from_different_eo_400(self, tok):
        g = _mk_goal(tok, "TEST_g_A")
        eo_a = _mk_eo(tok, g["id"], "eo_A")
        eo_b = _mk_eo(tok, g["id"], "eo_B")
        t_b = requests.post(f"{API}/tasks", headers=_h(tok),
                            json={"title": "TEST_t_B", "origin": "expected_outcome",
                                  "expected_outcome_id": eo_b["id"]}, timeout=10).json()
        # check-in under eo_a referencing task from eo_b -> 400
        r = requests.post(f"{API}/checkins", headers=_h(tok), json={
            "type": "goal", "title": "x", "date": "2026-01-05", "time": "09:00",
            "expected_outcome_id": eo_a["id"], "task_id": t_b["id"],
        }, timeout=10)
        assert r.status_code == 400


class TestCheckinMoney:
    def test_money_spent_ok(self, tok):
        r = requests.post(f"{API}/checkins", headers=_h(tok), json={
            "type": "life", "title": "TEST_m_ok", "date": "2026-01-06", "time": "09:00",
            "money_spent": "42.50", "money_currency": "USD",
        }, timeout=10)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["money_spent"] == "42.50"
        assert body["money_currency"] == "USD"
        # GET echoes as strings
        got = requests.get(f"{API}/checkins/{body['id']}", headers=_h(tok), timeout=10).json()
        assert got["money_spent"] == "42.50"
        assert got["money_currency"] == "USD"

    def test_money_spent_numeric_zero_ok(self, tok):
        r = requests.post(f"{API}/checkins", headers=_h(tok), json={
            "type": "life", "title": "TEST_m_zero", "date": "2026-01-06", "time": "09:00",
            "money_spent": 0, "money_currency": "USD",
        }, timeout=10)
        # Note: money_spent 0 with != "" and is not None => passes validation & stored
        assert r.status_code == 201, r.text
        assert r.json()["money_spent"] in ("0", "0.0", "0.00")
        assert r.json()["money_currency"] == "USD"

    def test_money_spent_nan_400(self, tok):
        r = requests.post(f"{API}/checkins", headers=_h(tok), json={
            "type": "life", "title": "TEST_m_nan", "date": "2026-01-06", "time": "09:00",
            "money_spent": "NaN", "money_currency": "USD",
        }, timeout=10)
        assert r.status_code == 400
        assert "finite" in r.json().get("detail", "").lower() or "nan" in r.json().get("detail", "").lower()

    def test_money_spent_negative_400(self, tok):
        r = requests.post(f"{API}/checkins", headers=_h(tok), json={
            "type": "life", "title": "TEST_m_neg", "date": "2026-01-06", "time": "09:00",
            "money_spent": "-1", "money_currency": "USD",
        }, timeout=10)
        assert r.status_code == 400
        assert "positive" in r.json().get("detail", "").lower() or "zero" in r.json().get("detail", "").lower()

    def test_money_spent_infinity_400(self, tok):
        r = requests.post(f"{API}/checkins", headers=_h(tok), json={
            "type": "life", "title": "TEST_m_inf", "date": "2026-01-06", "time": "09:00",
            "money_spent": "Infinity", "money_currency": "USD",
        }, timeout=10)
        assert r.status_code == 400
        assert "finite" in r.json().get("detail", "").lower()

    def test_money_spent_without_currency_400(self, tok):
        r = requests.post(f"{API}/checkins", headers=_h(tok), json={
            "type": "life", "title": "TEST_m_nocur", "date": "2026-01-06", "time": "09:00",
            "money_spent": "10",
        }, timeout=10)
        assert r.status_code == 400
        assert "currency" in r.json().get("detail", "").lower()

    def test_money_spent_bad_currency_400(self, tok):
        r = requests.post(f"{API}/checkins", headers=_h(tok), json={
            "type": "life", "title": "TEST_m_badcur", "date": "2026-01-06", "time": "09:00",
            "money_spent": "10", "money_currency": "dollar",
        }, timeout=10)
        assert r.status_code == 400

    def test_money_omitted_ok(self, tok):
        r = requests.post(f"{API}/checkins", headers=_h(tok), json={
            "type": "life", "title": "TEST_m_none", "date": "2026-01-06", "time": "09:00",
        }, timeout=10)
        assert r.status_code == 201, r.text
        b = r.json()
        assert b["money_spent"] is None
        assert b["money_currency"] is None


# ==========================================================================
# 3. Money position: actual_spending
# ==========================================================================
class TestMoneyPositionActualSpending:
    def test_actual_spending_deducted(self, tok):
        # bank USD liquid 100
        r = requests.post(f"{API}/portfolio/financial-accounts", headers=_h(tok), json={
            "account_type": "bank", "name": "TEST_mp_bank", "currency": "USD",
            "current_value": 100, "liquidity_type": "liquid", "fixed_or_flexible": "flexible",
        }, timeout=15)
        assert r.status_code == 201, r.text
        # income USD 500 fixed for this month
        month = _this_month()
        r = requests.post(f"{API}/portfolio/monthly-money-commitments", headers=_h(tok), json={
            "title": "TEST_mp_income", "currency": "USD", "amount": 500,
            "commitment_type": "income", "fixed_or_flexible": "fixed", "start_month": month,
        }, timeout=15)
        assert r.status_code == 201, r.text
        # expense USD 100 fixed for this month
        r = requests.post(f"{API}/portfolio/monthly-money-commitments", headers=_h(tok), json={
            "title": "TEST_mp_rent", "currency": "USD", "amount": 100,
            "commitment_type": "expense", "fixed_or_flexible": "fixed", "start_month": month,
        }, timeout=15)
        assert r.status_code == 201, r.text
        # check-in money_spent=25 USD dated today
        r = requests.post(f"{API}/checkins", headers=_h(tok), json={
            "type": "life", "title": "TEST_mp_spend", "date": _today(), "time": "10:00",
            "money_spent": "25", "money_currency": "USD",
        }, timeout=10)
        assert r.status_code == 201, r.text
        # money-position for this month, USD
        r = requests.get(f"{API}/portfolio/money-position?month={month}&currency=USD",
                         headers=_h(tok), timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["opening_liquid_assets"] == "100.00"
        assert d["planned_income"] == "500.00"
        assert d["fixed_outflows"] == "100.00"
        assert d["flexible_outflows"] == "0.00"
        assert d["planned_savings"] == "0.00"
        assert d["planned_investments"] == "0.00"
        assert d["actual_spending"] == "25.00"
        # available = 100+500-100-0-0-0 -25 = 475
        assert d["available_for_flexible_spending"] == "475.00"

    def test_actual_spending_isolated_by_currency(self, tok):
        # spend in USD and INR — INR month-position should only reflect INR
        r = requests.post(f"{API}/checkins", headers=_h(tok), json={
            "type": "life", "title": "TEST_mp_inr", "date": _today(), "time": "10:00",
            "money_spent": "500", "money_currency": "INR",
        }, timeout=10)
        assert r.status_code == 201, r.text
        r = requests.post(f"{API}/checkins", headers=_h(tok), json={
            "type": "life", "title": "TEST_mp_usd_only", "date": _today(), "time": "10:01",
            "money_spent": "10", "money_currency": "USD",
        }, timeout=10)
        assert r.status_code == 201, r.text
        month = _this_month()
        r = requests.get(f"{API}/portfolio/money-position?month={month}&currency=INR",
                         headers=_h(tok), timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["actual_spending"] == "500.00"

    def test_actual_spending_isolated_by_month(self, tok):
        # spend "2020-01-15" USD 999 should not affect this-month position
        r = requests.post(f"{API}/checkins", headers=_h(tok), json={
            "type": "life", "title": "TEST_mp_old", "date": "2020-01-15", "time": "10:00",
            "money_spent": "999", "money_currency": "USD",
        }, timeout=10)
        assert r.status_code == 201, r.text
        month = _this_month()
        r = requests.get(f"{API}/portfolio/money-position?month={month}&currency=USD",
                         headers=_h(tok), timeout=15)
        assert r.status_code == 200
        # sanity: actual_spending should not contain the 999
        d = r.json()
        assert "999" not in d["actual_spending"]


# ==========================================================================
# 4. Spending endpoint
# ==========================================================================
class TestSpendingEndpoint:
    def test_grouped_by_currency_and_sorted(self, tok):
        today = _today()
        # Two USD (10, 15) + one INR (500) today
        r1 = requests.post(f"{API}/checkins", headers=_h(tok), json={
            "type": "life", "title": "TEST_sp_usd_15", "date": today, "time": "11:00",
            "money_spent": "15", "money_currency": "USD",
        }, timeout=10)
        assert r1.status_code == 201, r1.text
        r2 = requests.post(f"{API}/checkins", headers=_h(tok), json={
            "type": "life", "title": "TEST_sp_usd_10", "date": today, "time": "08:00",
            "money_spent": "10", "money_currency": "USD",
        }, timeout=10)
        assert r2.status_code == 201, r2.text
        r3 = requests.post(f"{API}/checkins", headers=_h(tok), json={
            "type": "life", "title": "TEST_sp_inr_500", "date": today, "time": "09:30",
            "money_spent": "500", "money_currency": "INR",
        }, timeout=10)
        assert r3.status_code == 201, r3.text
        # An older check-in — should be excluded
        r4 = requests.post(f"{API}/checkins", headers=_h(tok), json={
            "type": "life", "title": "TEST_sp_old", "date": "2020-01-01", "time": "12:00",
            "money_spent": "999", "money_currency": "USD",
        }, timeout=10)
        assert r4.status_code == 201
        # And a check-in today WITHOUT money — should be excluded
        r5 = requests.post(f"{API}/checkins", headers=_h(tok), json={
            "type": "life", "title": "TEST_sp_nomoney", "date": today, "time": "14:00",
        }, timeout=10)
        assert r5.status_code == 201

        r = requests.get(f"{API}/spending?date={today}", headers=_h(tok), timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["date"] == today
        groups = {g["currency"]: g for g in body["groups"]}
        assert "USD" in groups and "INR" in groups
        assert len(groups) == 2

        # USD total = 25.00
        usd = groups["USD"]
        assert usd["total"] == "25.00"
        assert len(usd["entries"]) == 2
        # sorted by time ascending
        times = [e["time"] for e in usd["entries"]]
        assert times == sorted(times), f"USD entries not sorted: {times}"
        assert times[0] == "08:00" and times[1] == "11:00"
        # entries include the fields
        assert usd["entries"][0]["title"] == "TEST_sp_usd_10"
        assert usd["entries"][0]["amount"] in ("10", "10.0", "10.00")
        assert usd["entries"][1]["amount"] in ("15", "15.0", "15.00")

        # INR
        inr = groups["INR"]
        assert inr["total"] == "500.00"
        assert len(inr["entries"]) == 1
        assert inr["entries"][0]["amount"] in ("500", "500.0", "500.00")

    def test_missing_date_param(self, tok):
        r = requests.get(f"{API}/spending", headers=_h(tok), timeout=10)
        assert r.status_code in (400, 422), r.text

    def test_malformed_date_400(self, tok):
        r = requests.get(f"{API}/spending?date=2026/01/01", headers=_h(tok), timeout=10)
        assert r.status_code == 400
        r = requests.get(f"{API}/spending?date=not-a-date", headers=_h(tok), timeout=10)
        assert r.status_code == 400

    def test_no_spending_returns_empty_groups(self, tok):
        r = requests.get(f"{API}/spending?date=2019-05-15", headers=_h(tok), timeout=10)
        assert r.status_code == 200
        assert r.json() == {"date": "2019-05-15", "groups": []}


# ==========================================================================
# 5. Regression sweep
# ==========================================================================
class TestRegression:
    def test_domains_goals_tasks_checkins_journeys(self, tok):
        # domains
        r = requests.get(f"{API}/domains", headers=_h(tok), timeout=10)
        assert r.status_code == 200
        assert len(r.json()) >= 4  # defaults
        # goals
        g = _mk_goal(tok, "TEST_rg_goal")
        r = requests.get(f"{API}/goals", headers=_h(tok), timeout=10)
        assert r.status_code == 200 and any(x["id"] == g["id"] for x in r.json())
        # tasks CRUD
        t = _mk_task(tok, "TEST_rg_task")
        r = requests.put(f"{API}/tasks/{t['id']}", headers=_h(tok), json={"title": "TEST_rg_task2"}, timeout=10)
        assert r.status_code == 200 and r.json()["title"] == "TEST_rg_task2"
        r = requests.delete(f"{API}/tasks/{t['id']}", headers=_h(tok), timeout=10)
        assert r.status_code == 200
        # checkins
        r = requests.post(f"{API}/checkins", headers=_h(tok), json={
            "type": "life", "title": "TEST_rg_c", "date": "2026-01-01", "time": "09:00",
        }, timeout=10)
        assert r.status_code == 201
        cid = r.json()["id"]
        assert requests.get(f"{API}/checkins/{cid}", headers=_h(tok), timeout=10).status_code == 200
        # knowledge journeys
        r = requests.get(f"{API}/knowledge/journeys", headers=_h(tok), timeout=10)
        assert r.status_code == 200
