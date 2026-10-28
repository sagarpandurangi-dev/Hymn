"""
Backend smoke tests for two new capabilities:

Feature 1 — Behavioural Calibration
  * GET  /api/finance/calibration
  * POST /api/finance/overrides/{id}/outcome
  * Modified POST /api/finance/decision-assessment (returns original vs
    calibrated classification + calibration block).
  * Auto-tagging on commitment /complete and /cancel.

Feature 2 — Goal cadence extended
  * Goal.checkin_cadence accepts the recurrence vocabulary.
  * New Goal.checkin_anchor_date field.
  * /api/checkins/required semantics with the fortnightly cadence.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, timedelta

import pytest
import requests

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")

EMAIL = "test@hymn.app"
PASSWORD = "TestPass123!"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": EMAIL, "password": PASSWORD}, timeout=30)
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    token = r.json()["access_token"]
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


@pytest.fixture(scope="module")
def domain_id(session):
    r = session.get(f"{BASE_URL}/api/domains", timeout=15)
    assert r.status_code == 200, r.text
    doms = r.json()
    assert doms, "test user has no domains"
    return doms[0]["id"]


@pytest.fixture(scope="module")
def cleanup(session):
    """Track resources for teardown."""
    bag = {
        "account_ids": [],
        "commitment_ids": [],
        "goal_ids": [],
        "checkin_ids": [],
    }
    yield bag

    # Cancel commitments (best-effort — some already completed)
    for cid in bag["commitment_ids"]:
        try:
            session.post(f"{BASE_URL}/api/finance/commitments/{cid}/cancel", timeout=15)
        except Exception:
            pass
    # Delete accounts
    for aid in bag["account_ids"]:
        try:
            session.delete(f"{BASE_URL}/api/portfolio/financial-accounts/{aid}", timeout=15)
        except Exception:
            pass
    # Delete checkins
    for kid in bag["checkin_ids"]:
        try:
            session.delete(f"{BASE_URL}/api/checkins/{kid}", timeout=15)
        except Exception:
            pass
    # Delete goals
    for gid in bag["goal_ids"]:
        try:
            session.delete(f"{BASE_URL}/api/goals/{gid}", timeout=15)
        except Exception:
            pass
    # Clean up any TEST_ overrides left behind (marker in user_comment)
    try:
        # There's no list endpoint, so use direct db is not available.
        # We rely on outcome endpoint idempotency instead.
        pass
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Feature 1 — Behavioural Calibration
# ---------------------------------------------------------------------------
class TestCalibration:
    """Behavioural calibration profile and softening loop."""

    def test_01_calibration_endpoint_shape(self, session):
        # Test 1 (adapted): GET /finance/calibration returns the profile
        # with the documented shape. The test user may have existing
        # overrides from prior test runs, so we assert on shape not zeros.
        r = session.get(f"{BASE_URL}/api/finance/calibration", timeout=20)
        assert r.status_code == 200, r.text
        p = r.json()
        for k in ("total", "by_classification", "by_priority",
                  "by_domain", "by_currency", "outcomes", "trend",
                  "soften_min_count", "soften_min_ratio"):
            assert k in p, f"missing {k} in profile: {p.keys()}"
        assert isinstance(p["total"], int)
        assert isinstance(p["by_classification"], dict)
        assert isinstance(p["by_priority"], list)
        assert p["soften_min_count"] == 3
        assert p["soften_min_ratio"] == 0.70

    def test_02_decision_assessment_safe_no_calibration(self, session, cleanup):
        # Create a USD account with plenty of liquidity so a tiny
        # proposal has clear positive headroom.
        acc = session.post(
            f"{BASE_URL}/api/portfolio/financial-accounts",
            json={
                "account_type": "bank",
                "name": f"TEST_calib_bank_{uuid.uuid4().hex[:6]}",
                "currency": "USD",
                "current_value": "500000",
                "liquidity_type": "liquid",
                "fixed_or_flexible": "flexible",
            }, timeout=20,
        )
        assert acc.status_code == 201, acc.text
        cleanup["account_ids"].append(acc.json()["id"])

        today = date.today()
        due = (today + timedelta(days=45)).isoformat()
        r = session.post(
            f"{BASE_URL}/api/finance/decision-assessment",
            json={
                "amount": "100",
                "currency": "USD",
                "due_date": due,
                "priority": "medium",
            }, timeout=20,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        # Shape: new fields must be present.
        assert "original_classification" in data
        assert "calibration" in data
        cal = data["calibration"]
        for k in ("applied", "original", "calibrated", "reason", "matched_axes"):
            assert k in cal, f"missing calibration.{k}"
        # Per spec: if original is "safe" then calibration must not apply
        # and classification stays "safe". If prior test-user state
        # forces a different original class, we still assert the invariant
        # that calibration never escalates.
        assert cal["original"] == data["original_classification"]
        if data["original_classification"] == "safe":
            assert data["classification"] == "safe", data
            assert cal["applied"] is False, cal
            assert cal["calibrated"] == "safe"
        else:
            # Invariant: calibration only softens; classification is either
            # equal to original or a strictly softer level.
            order = ["safe", "warning", "severe_risk"]
            assert order.index(data["classification"]) <= order.index(
                data["original_classification"]
            ), data

    def test_03_seed_four_vindicated_overrides_and_softening(self, session, cleanup):
        """Combines tests 3 & 4: create 4 warning-triggering commitments,
        reserve → record override → complete with actual==reserved so
        each override auto-tags as vindicated. Then the next similar
        assessment softens warning -> safe."""
        today = date.today()
        # Set month to next month to keep due_date in a stable single month.
        # Use a background low-priority commitment large enough that
        # subsequent high-priority proposals will squeeze it → warning.
        yr = today.year + (1 if today.month == 12 else 0)
        m = 1 if today.month == 12 else today.month + 1
        due = f"{yr:04d}-{m:02d}-15"

        # Snapshot the vindicated count for priority=high USD BEFORE seeding.
        pre = session.get(f"{BASE_URL}/api/finance/calibration", timeout=20).json()
        pre_high = next((r for r in pre["by_priority"] if r["value"] == "high"), None)
        pre_vind = pre_high["vindicated"] if pre_high else 0
        pre_outcome_vind = pre["outcomes"]["vindicated"]

        # 1) Background commitment: low-priority, large amount, same month.
        #    Squeezes future high-priority proposals into "warning".
        bg = session.post(
            f"{BASE_URL}/api/finance/commitments",
            json={
                "title": f"TEST_calib_bg_{uuid.uuid4().hex[:6]}",
                "amount": "300000",
                "currency": "USD",
                "due_date": due,
                "priority": "low",
            }, timeout=20,
        )
        assert bg.status_code == 201, bg.text
        bg_id = bg.json()["id"]
        cleanup["commitment_ids"].append(bg_id)
        rv = session.post(f"{BASE_URL}/api/finance/commitments/{bg_id}/reserve", timeout=20)
        assert rv.status_code == 200, rv.text

        # Sanity: decision-assessment now returns "warning" for a
        # high-priority proposal in the same month.
        probe = session.post(
            f"{BASE_URL}/api/finance/decision-assessment",
            json={"amount": "150000", "currency": "USD",
                  "due_date": due, "priority": "high"},
            timeout=20,
        ).json()
        # The proposal is smaller than background AND lower/equal priority
        # displacement direction (high > low, so no displacement). Combined
        # cash: 500k - 300k - 150k = 50k (positive), background amount is
        # 300k > 50k so background is affected → classification=warning.
        assert probe.get("original_classification") == "warning", (
            f"Failed to force warning: {probe}. Adjust seed amounts."
        )
        assert probe.get("classification") in ("warning", "safe"), probe

        # 2) Seed 4 overrides on priority=high, currency=USD, then
        #    complete each with actual==reserved → auto-vindicated.
        for i in range(4):
            c = session.post(
                f"{BASE_URL}/api/finance/commitments",
                json={
                    "title": f"TEST_calib_ov{i}_{uuid.uuid4().hex[:6]}",
                    "amount": "500",
                    "currency": "USD",
                    "due_date": due,
                    "priority": "high",
                }, timeout=20,
            )
            assert c.status_code == 201, c.text
            cid = c.json()["id"]
            cleanup["commitment_ids"].append(cid)
            rr = session.post(f"{BASE_URL}/api/finance/commitments/{cid}/reserve", timeout=20)
            assert rr.status_code == 200, rr.text

            ov = session.post(
                f"{BASE_URL}/api/finance/overrides",
                json={
                    "commitment_id": cid,
                    "forecast_snapshot": {
                        "priority": "high",
                        "currency": "USD",
                        "domain": "",
                    },
                    "liquidity_result": {"classification": "warning"},
                    "net_worth_result": {},
                    "confidence": "medium",
                    "warning_classification": "warning",
                    "projected_shortfall": None,
                    "affected_commitments": [],
                    "user_comment": "TEST_calib override",
                }, timeout=20,
            )
            assert ov.status_code == 200, ov.text

            comp = session.post(
                f"{BASE_URL}/api/finance/commitments/{cid}/complete",
                json={"actual_amount": "500"}, timeout=20,
            )
            assert comp.status_code == 200, comp.text
            # Reserved commitment is now completed & removed from cleanup
            # cancel set (cancel would 400 on completed state).
            cleanup["commitment_ids"].remove(cid)

        # 3) GET calibration → 4 new vindicated overrides on high/USD.
        prof = session.get(f"{BASE_URL}/api/finance/calibration", timeout=20).json()
        high_bucket = next(r for r in prof["by_priority"] if r["value"] == "high")
        usd_bucket = next(r for r in prof["by_currency"] if r["value"] == "USD")
        assert high_bucket["vindicated"] >= pre_vind + 4, (
            f"expected +4 vindicated for priority=high; pre={pre_vind}, now={high_bucket}"
        )
        assert high_bucket["softens"] is True, high_bucket
        assert usd_bucket["softens"] is True, usd_bucket
        assert prof["outcomes"]["vindicated"] >= pre_outcome_vind + 4

        # 4) Test 4: run new decision-assessment on same priority+currency.
        #    Expected: calibration.applied=true, calibrated=safe,
        #    classification=safe, original_classification=warning.
        final = session.post(
            f"{BASE_URL}/api/finance/decision-assessment",
            json={"amount": "150000", "currency": "USD",
                  "due_date": due, "priority": "high"},
            timeout=20,
        ).json()
        assert final["original_classification"] == "warning", final
        assert final["classification"] == "safe", final
        cal = final["calibration"]
        assert cal["applied"] is True, cal
        assert cal["original"] == "warning"
        assert cal["calibrated"] == "safe"
        assert "priority" in cal["matched_axes"] or "currency" in cal["matched_axes"]
        assert cal["reason"]

    def test_04_manual_outcome_endpoint(self, session, cleanup):
        """Test 5: create one more override and manually mark it regretted."""
        today = date.today()
        yr = today.year + (1 if today.month == 12 else 0)
        m = 1 if today.month == 12 else today.month + 1
        due = f"{yr:04d}-{m:02d}-16"

        c = session.post(
            f"{BASE_URL}/api/finance/commitments",
            json={
                "title": f"TEST_calib_manual_{uuid.uuid4().hex[:6]}",
                "amount": "700",
                "currency": "EUR",
                "due_date": due,
                "priority": "medium",
            }, timeout=20,
        )
        assert c.status_code == 201, c.text
        cid = c.json()["id"]
        cleanup["commitment_ids"].append(cid)
        # Don't need to reserve — override just needs commitment_id.

        ov = session.post(
            f"{BASE_URL}/api/finance/overrides",
            json={
                "commitment_id": cid,
                "forecast_snapshot": {"priority": "medium", "currency": "EUR"},
                "liquidity_result": {},
                "net_worth_result": {},
                "confidence": "medium",
                "warning_classification": "warning",
                "user_comment": "TEST_calib manual outcome",
            }, timeout=20,
        )
        assert ov.status_code == 200, ov.text
        override_id = ov.json()["id"]

        before = session.get(f"{BASE_URL}/api/finance/calibration", timeout=20).json()
        eur_before = next((r for r in before["by_currency"] if r["value"] == "EUR"), None)
        regretted_before = eur_before["regretted"] if eur_before else 0

        # Manual outcome = regretted
        r = session.post(
            f"{BASE_URL}/api/finance/overrides/{override_id}/outcome",
            json={"outcome": "regretted", "notes": "TEST_calib manual"}, timeout=20,
        )
        assert r.status_code == 200, r.text
        assert r.json().get("outcome") == "regretted"

        after = session.get(f"{BASE_URL}/api/finance/calibration", timeout=20).json()
        eur_after = next(r for r in after["by_currency"] if r["value"] == "EUR")
        assert eur_after["regretted"] == regretted_before + 1

    def test_05_invalid_outcome_returns_400(self, session, cleanup):
        # Reuse a fresh override for a valid id, then send an invalid outcome.
        today = date.today()
        yr = today.year + (1 if today.month == 12 else 0)
        m = 1 if today.month == 12 else today.month + 1
        due = f"{yr:04d}-{m:02d}-17"

        c = session.post(
            f"{BASE_URL}/api/finance/commitments",
            json={
                "title": f"TEST_calib_badoutcome_{uuid.uuid4().hex[:6]}",
                "amount": "10", "currency": "USD",
                "due_date": due, "priority": "low",
            }, timeout=20,
        )
        assert c.status_code == 201, c.text
        cid = c.json()["id"]
        cleanup["commitment_ids"].append(cid)

        ov = session.post(
            f"{BASE_URL}/api/finance/overrides",
            json={
                "commitment_id": cid,
                "forecast_snapshot": {"priority": "low", "currency": "USD"},
                "liquidity_result": {}, "net_worth_result": {},
                "confidence": "low", "warning_classification": "warning",
                "user_comment": "TEST_calib bad outcome",
            }, timeout=20,
        )
        assert ov.status_code == 200, ov.text
        oid = ov.json()["id"]

        bad = session.post(
            f"{BASE_URL}/api/finance/overrides/{oid}/outcome",
            json={"outcome": "banana"}, timeout=20,
        )
        assert bad.status_code == 400, (bad.status_code, bad.text)


# ---------------------------------------------------------------------------
# Feature 2 — Goal cadence extended
# ---------------------------------------------------------------------------
class TestGoalCadence:
    """Goal.checkin_cadence extended + checkin_anchor_date."""

    def test_06_create_goal_quarterly_with_anchor(self, session, cleanup, domain_id):
        r = session.post(
            f"{BASE_URL}/api/goals",
            json={
                "title": f"TEST_cadence_q_{uuid.uuid4().hex[:6]}",
                "target_outcome": "TEST",
                "domain_id": domain_id,
                "checkin_cadence": "quarterly",
                "checkin_anchor_date": "2026-01-15",
            }, timeout=20,
        )
        assert r.status_code == 201, r.text
        gid = r.json()["id"]
        cleanup["goal_ids"].append(gid)
        assert r.json()["checkin_cadence"] == "quarterly"
        assert r.json()["checkin_anchor_date"] == "2026-01-15"

        g = session.get(f"{BASE_URL}/api/goals/{gid}", timeout=15).json()
        assert g["checkin_cadence"] == "quarterly"
        assert g["checkin_anchor_date"] == "2026-01-15"

    def test_07_put_goal_change_cadence(self, session, cleanup, domain_id):
        r = session.post(
            f"{BASE_URL}/api/goals",
            json={
                "title": f"TEST_cadence_put_{uuid.uuid4().hex[:6]}",
                "target_outcome": "TEST",
                "domain_id": domain_id,
                "checkin_cadence": "weekly",
            }, timeout=20,
        )
        assert r.status_code == 201, r.text
        gid = r.json()["id"]
        cleanup["goal_ids"].append(gid)

        upd = session.put(
            f"{BASE_URL}/api/goals/{gid}",
            json={
                "checkin_cadence": "fortnightly",
                "checkin_anchor_date": "2026-06-01",
            }, timeout=20,
        )
        assert upd.status_code == 200, upd.text
        assert upd.json()["checkin_cadence"] == "fortnightly"
        assert upd.json()["checkin_anchor_date"] == "2026-06-01"

        g = session.get(f"{BASE_URL}/api/goals/{gid}", timeout=15).json()
        assert g["checkin_cadence"] == "fortnightly"
        assert g["checkin_anchor_date"] == "2026-06-01"

    def test_08_invalid_cadence_and_date_return_400(self, session, cleanup, domain_id):
        bad_cad = session.post(
            f"{BASE_URL}/api/goals",
            json={
                "title": "TEST_bad_cadence",
                "target_outcome": "TEST",
                "domain_id": domain_id,
                "checkin_cadence": "every_leap_year",
            }, timeout=20,
        )
        assert bad_cad.status_code == 400, (bad_cad.status_code, bad_cad.text)

        bad_date = session.post(
            f"{BASE_URL}/api/goals",
            json={
                "title": "TEST_bad_anchor",
                "target_outcome": "TEST",
                "domain_id": domain_id,
                "checkin_cadence": "fortnightly",
                "checkin_anchor_date": "2026-13-01",
            }, timeout=20,
        )
        assert bad_date.status_code == 400, (bad_date.status_code, bad_date.text)

    def test_09_fortnightly_required_checkin_period(self, session, cleanup, domain_id):
        """Test 10: goal with fortnightly cadence anchored 2026-06-01.
        Periods are [06-01..06-14] and [06-15..06-28]. Query on 06-15
        should show the goal (no checkin in 06-15..06-28 period). After
        posting a checkin dated 2026-06-15, the goal should disappear
        from the required list on the same date."""
        r = session.post(
            f"{BASE_URL}/api/goals",
            json={
                "title": f"TEST_cadence_fn_{uuid.uuid4().hex[:6]}",
                "target_outcome": "TEST",
                "domain_id": domain_id,
                "checkin_cadence": "fortnightly",
                "checkin_anchor_date": "2026-06-01",
            }, timeout=20,
        )
        assert r.status_code == 201, r.text
        gid = r.json()["id"]
        cleanup["goal_ids"].append(gid)

        # Query required checkins on 2026-06-15
        req = session.get(
            f"{BASE_URL}/api/checkins/required?date=2026-06-15", timeout=20,
        )
        assert req.status_code == 200, req.text
        ids_before = {row["goal_id"] for row in req.json()}
        assert gid in ids_before, (
            f"Fortnightly goal not returned for date=2026-06-15; "
            f"required={req.json()}"
        )

        # Create an expected outcome (required for goal check-ins).
        eo = session.post(
            f"{BASE_URL}/api/expected-outcomes",
            json={"goal_id": gid, "title": "TEST_cadence_EO"}, timeout=15,
        )
        assert eo.status_code == 201, eo.text
        eo_id = eo.json()["id"]

        # Create a check-in for this goal on 2026-06-15
        ck = session.post(
            f"{BASE_URL}/api/checkins",
            json={
                "goal_id": gid,
                "expected_outcome_id": eo_id,
                "date": "2026-06-15",
                "time": "10:00",
                "title": "TEST_cadence checkin",
                "type": "goal",
                "notes": "TEST_cadence fortnightly period covered",
            }, timeout=20,
        )
        assert ck.status_code in (200, 201), ck.text
        cleanup["checkin_ids"].append(ck.json()["id"])

        # Now goal should no longer appear as required for 06-15.
        req2 = session.get(
            f"{BASE_URL}/api/checkins/required?date=2026-06-15", timeout=20,
        )
        assert req2.status_code == 200, req2.text
        ids_after = {row["goal_id"] for row in req2.json()}
        assert gid not in ids_after, (
            f"Goal should have disappeared after check-in; "
            f"required={req2.json()}"
        )
