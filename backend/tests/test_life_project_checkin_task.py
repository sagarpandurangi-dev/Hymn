"""Backend smoke tests for Project + Life check-ins with task_id linkage, complete_task, and money_spent.

Spec: iteration 13 request. Covers 9 scenarios:
  1. Project check-in + task_id (same project) + complete_task=false + money_spent=12.50 USD -> 201
  2. Project check-in + task_id + complete_task=true -> task flips to done
  3. Project check-in + task from DIFFERENT project -> 400
  4. Life check-in + task_id (user owns) + complete_task=false + money=5 INR -> 201
  5. Life check-in + task_id + complete_task=true -> task flips to done
  6. Life check-in + task_id owned by another user -> 400
  7. Life check-in money_spent WITHOUT money_currency -> 400
  8. GET /api/spending?date=today groups life+project entries by currency w/ 2dp totals
  9. GET /api/portfolio/money-position current-month USD sees USD money_spent in actual_spending
"""
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
import requests

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"


# ---------- helpers ----------
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


def _mk_project(tok: str, title: str) -> dict:
    r = requests.post(f"{API}/projects", headers=_h(tok), json={"title": title}, timeout=10)
    assert r.status_code == 201, r.text
    return r.json()


def _mk_project_task(tok: str, project_id: str, title: str) -> dict:
    r = requests.post(
        f"{API}/tasks",
        headers=_h(tok),
        json={"title": title, "origin": "project", "project_id": project_id},
        timeout=10,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _mk_life_task(tok: str, title: str) -> dict:
    r = requests.post(
        f"{API}/tasks",
        headers=_h(tok),
        json={"title": title, "origin": "standalone"},
        timeout=10,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _this_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def token_a() -> str:
    return _signup(f"TEST_ck_a_{uuid.uuid4().hex[:8]}@hymn.app")


@pytest.fixture(scope="module")
def token_b() -> str:
    return _signup(f"TEST_ck_b_{uuid.uuid4().hex[:8]}@hymn.app")


@pytest.fixture(scope="module")
def seeds(token_a, token_b):
    """Provision: two projects owned by A (used + foreign-to-project-1), two life tasks (A + B)."""
    p_used = _mk_project(token_a, f"TEST_p_used_{uuid.uuid4().hex[:6]}")
    p_foreign = _mk_project(token_a, f"TEST_p_foreign_{uuid.uuid4().hex[:6]}")
    task_in_used = _mk_project_task(token_a, p_used["id"], "TEST_pt_used")
    task_in_foreign = _mk_project_task(token_a, p_foreign["id"], "TEST_pt_foreign")
    life_task_a = _mk_life_task(token_a, "TEST_life_task_a")
    life_task_b = _mk_life_task(token_b, "TEST_life_task_b")
    return {
        "p_used": p_used,
        "p_foreign": p_foreign,
        "task_in_used": task_in_used,
        "task_in_foreign": task_in_foreign,
        "life_task_a": life_task_a,
        "life_task_b": life_task_b,
    }


# ---------- Scenario 1 ----------
class TestScenario1_ProjectCheckinTaskMoneyNoComplete:
    def test_201_task_stays_todo_and_updated_at_bumps_money_echoed(self, token_a, seeds):
        task_id = seeds["task_in_used"]["id"]
        proj_id = seeds["p_used"]["id"]
        # Snapshot BEFORE
        t_before = requests.get(f"{API}/tasks/{task_id}", headers=_h(token_a), timeout=10).json()
        assert t_before["status"] == "todo"
        before_ts = t_before["updated_at"]

        r = requests.post(
            f"{API}/checkins",
            headers=_h(token_a),
            json={
                "type": "project", "title": "TEST_p_c1", "date": _today(), "time": "09:00",
                "project_id": proj_id, "task_id": task_id,
                "complete_task": False,
                "money_spent": "12.50", "money_currency": "USD",
            },
            timeout=10,
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["task_id"] == task_id
        assert body["project_id"] == proj_id
        assert body["money_spent"] == "12.50", f"echo: {body['money_spent']}"
        assert body["money_currency"] == "USD"

        # Task must remain todo, updated_at must bump
        t_after = requests.get(f"{API}/tasks/{task_id}", headers=_h(token_a), timeout=10).json()
        assert t_after["status"] == "todo"
        assert t_after["updated_at"] > before_ts, f"updated_at not bumped: {before_ts} -> {t_after['updated_at']}"


# ---------- Scenario 2 ----------
class TestScenario2_ProjectCheckinCompleteTaskTrue:
    def test_complete_task_true_flips_status_to_done(self, token_a, seeds):
        # Use a fresh task under the used project so scenario 1's task isn't disturbed
        proj_id = seeds["p_used"]["id"]
        new_task = _mk_project_task(token_a, proj_id, "TEST_pt_complete")
        r = requests.post(
            f"{API}/checkins",
            headers=_h(token_a),
            json={
                "type": "project", "title": "TEST_p_c2", "date": _today(), "time": "09:05",
                "project_id": proj_id, "task_id": new_task["id"],
                "complete_task": True,
            },
            timeout=10,
        )
        assert r.status_code == 201, r.text
        t_after = requests.get(f"{API}/tasks/{new_task['id']}", headers=_h(token_a), timeout=10).json()
        assert t_after["status"] == "done"


# ---------- Scenario 3 ----------
class TestScenario3_ProjectCheckinTaskFromDifferentProject:
    def test_400_when_task_belongs_to_different_project(self, token_a, seeds):
        p_used_id = seeds["p_used"]["id"]
        foreign_task_id = seeds["task_in_foreign"]["id"]  # lives under p_foreign
        r = requests.post(
            f"{API}/checkins",
            headers=_h(token_a),
            json={
                "type": "project", "title": "TEST_p_c3", "date": _today(), "time": "09:10",
                "project_id": p_used_id, "task_id": foreign_task_id,
            },
            timeout=10,
        )
        assert r.status_code == 400, r.text


# ---------- Scenario 4 ----------
class TestScenario4_LifeCheckinTaskMoneyNoComplete:
    def test_201_task_stays_todo_updated_at_bumps(self, token_a, seeds):
        task_id = seeds["life_task_a"]["id"]
        t_before = requests.get(f"{API}/tasks/{task_id}", headers=_h(token_a), timeout=10).json()
        assert t_before["status"] == "todo"
        before_ts = t_before["updated_at"]

        r = requests.post(
            f"{API}/checkins",
            headers=_h(token_a),
            json={
                "type": "life", "title": "TEST_l_c4", "date": _today(), "time": "10:00",
                "task_id": task_id,
                "complete_task": False,
                "money_spent": "5", "money_currency": "INR",
            },
            timeout=10,
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["task_id"] == task_id
        assert body["type"] == "life"
        assert body["project_id"] is None and body["goal_id"] is None and body["expected_outcome_id"] is None
        # Backend echoes str(Decimal(input)) — "5" stays "5", not forced to 2dp on echo
        assert Decimal(body["money_spent"]) == Decimal("5"), f"money_spent echo mismatch: {body['money_spent']}"
        assert body["money_currency"] == "INR"

        t_after = requests.get(f"{API}/tasks/{task_id}", headers=_h(token_a), timeout=10).json()
        assert t_after["status"] == "todo"
        assert t_after["updated_at"] > before_ts


# ---------- Scenario 5 ----------
class TestScenario5_LifeCheckinCompleteTaskTrue:
    def test_complete_task_true_flips_to_done(self, token_a):
        # New standalone task exclusively for this scenario
        new_task = _mk_life_task(token_a, "TEST_life_task_c5")
        r = requests.post(
            f"{API}/checkins",
            headers=_h(token_a),
            json={
                "type": "life", "title": "TEST_l_c5", "date": _today(), "time": "10:05",
                "task_id": new_task["id"],
                "complete_task": True,
            },
            timeout=10,
        )
        assert r.status_code == 201, r.text
        t_after = requests.get(f"{API}/tasks/{new_task['id']}", headers=_h(token_a), timeout=10).json()
        assert t_after["status"] == "done"


# ---------- Scenario 6 ----------
class TestScenario6_LifeCheckinForeignUserTask:
    def test_400_when_task_owned_by_another_user(self, token_a, seeds):
        foreign_task_id = seeds["life_task_b"]["id"]  # owned by B
        r = requests.post(
            f"{API}/checkins",
            headers=_h(token_a),
            json={
                "type": "life", "title": "TEST_l_c6", "date": _today(), "time": "10:10",
                "task_id": foreign_task_id,
            },
            timeout=10,
        )
        assert r.status_code == 400, r.text


# ---------- Scenario 7 ----------
class TestScenario7_LifeCheckinMoneyWithoutCurrency:
    def test_400_missing_currency(self, token_a):
        r = requests.post(
            f"{API}/checkins",
            headers=_h(token_a),
            json={
                "type": "life", "title": "TEST_l_c7", "date": _today(), "time": "10:15",
                "money_spent": "3.14",
                # money_currency missing
            },
            timeout=10,
        )
        assert r.status_code == 400, r.text
        assert "money_currency" in r.json().get("detail", "").lower() or "currency" in r.json().get("detail", "").lower()


# ---------- Scenario 8 ----------
class TestScenario8_SpendingIncludesLifeAndProject:
    def test_spending_today_groups_by_currency_2dp(self, token_a):
        # By this point scenarios 1 (USD 12.50 project) + 4 (INR 5.00 life) are already recorded today.
        r = requests.get(f"{API}/spending", headers=_h(token_a), params={"date": _today()}, timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["date"] == _today()
        groups = {g["currency"]: g for g in body.get("groups", [])}
        assert "USD" in groups, f"USD group missing; groups: {groups}"
        assert "INR" in groups, f"INR group missing; groups: {groups}"

        # Totals are 2-dp strings
        for cur, g in groups.items():
            assert isinstance(g["total"], str), f"{cur} total not a string"
            # 2dp check (may include leading digits)
            assert "." in g["total"] and len(g["total"].split(".")[1]) == 2, f"{cur} total not 2dp: {g['total']}"

        # USD total must be at least 12.50 (may be more if other USD checkins accumulated)
        assert Decimal(groups["USD"]["total"]) >= Decimal("12.50")
        # INR total >= 5.00
        assert Decimal(groups["INR"]["total"]) >= Decimal("5.00")

        # /api/spending entries don't currently expose 'type' or 'project_id' — the projection
        # only carries id/title/time/amount/notes/goal_id/task_id/expected_outcome_id. So we
        # instead verify each group has non-zero entries and that the USD/INR totals reflect
        # the two check-ins we posted (project USD 12.50 in scen 1, life INR 5.00 in scen 4).
        for cur in ("USD", "INR"):
            assert len(groups[cur].get("entries", [])) >= 1, f"{cur} group has no entries"


# ---------- Scenario 9 ----------
class TestScenario9_MoneyPositionUSDActualSpending:
    def test_actual_spending_reflects_usd_checkin(self, token_a):
        month = _this_month()
        r = requests.get(
            f"{API}/portfolio/money-position",
            headers=_h(token_a),
            params={"month": month, "currency": "USD"},
            timeout=10,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # actual_spending is a 2-dp string; must be >= 12.50 (from scenario 1)
        actual = body.get("actual_spending")
        assert isinstance(actual, str), f"actual_spending should be 2-dp string, got {type(actual)}: {actual}"
        assert Decimal(actual) >= Decimal("12.50"), f"actual_spending {actual} < 12.50 (USD spend from scenario 1)"


# ---------- Regression: existing goal check-in flow still works ----------
class TestRegressionGoalCheckin:
    """Sanity check that the existing goal-checkin-with-task path is untouched."""

    def _first_default_domain_id(self, tok: str) -> str:
        lst = requests.get(f"{API}/domains", headers=_h(tok), timeout=10).json()
        for d in lst:
            if d["name"] in {"Knowledge", "Health", "Money", "Soul"}:
                return d["id"]
        raise AssertionError("no default domain found")

    def test_goal_checkin_task_link_still_validates_eo_scope(self, token_a):
        did = self._first_default_domain_id(token_a)
        g = requests.post(f"{API}/goals", headers=_h(token_a), json={"title": "TEST_g_reg", "domain_id": did}, timeout=10).json()
        eo1 = requests.post(f"{API}/expected-outcomes", headers=_h(token_a), json={"goal_id": g["id"], "title": "eo_reg1"}, timeout=10).json()
        eo2 = requests.post(f"{API}/expected-outcomes", headers=_h(token_a), json={"goal_id": g["id"], "title": "eo_reg2"}, timeout=10).json()
        t_eo2 = requests.post(
            f"{API}/tasks", headers=_h(token_a),
            json={"title": "TEST_t_reg", "origin": "expected_outcome", "expected_outcome_id": eo2["id"]},
            timeout=10,
        ).json()
        # Goal checkin with task from OTHER EO under same goal must 400 (untouched behavior).
        r = requests.post(
            f"{API}/checkins", headers=_h(token_a),
            json={
                "type": "goal", "title": "TEST_reg_c", "date": _today(), "time": "11:00",
                "expected_outcome_id": eo1["id"], "task_id": t_eo2["id"],
            },
            timeout=10,
        )
        assert r.status_code == 400, r.text

    def test_goal_checkin_money_still_works(self, token_a):
        did = self._first_default_domain_id(token_a)
        g = requests.post(f"{API}/goals", headers=_h(token_a), json={"title": "TEST_g_reg2", "domain_id": did}, timeout=10).json()
        eo = requests.post(f"{API}/expected-outcomes", headers=_h(token_a), json={"goal_id": g["id"], "title": "eo_reg_m"}, timeout=10).json()
        r = requests.post(
            f"{API}/checkins", headers=_h(token_a),
            json={
                "type": "goal", "title": "TEST_g_c_money", "date": _today(), "time": "11:05",
                "expected_outcome_id": eo["id"],
                "money_spent": "7.25", "money_currency": "USD",
            },
            timeout=10,
        )
        assert r.status_code == 201, r.text
        assert r.json()["money_spent"] == "7.25"
        assert r.json()["money_currency"] == "USD"
