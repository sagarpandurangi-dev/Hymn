"""Portfolio Onboarding Wizard bug-fix backend verification.

Focus per iteration 15 review request:
  A) POST /api/portfolio/time-commitments with end_time="24:00" succeeds.
  B) POST with end_time <= start_time (and end_time != 24:00) -> 400.
  C) Weekly capacity endpoint reflects a newly-created block using
     effective_from = current local Monday.
"""
from __future__ import annotations

import os
import uuid
from datetime import date, timedelta

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL must be set"
BASE_URL = BASE_URL.rstrip("/")

TEST_EMAIL = "test@hymn.app"
TEST_PASSWORD = "TestPass123!"


def _monday_iso() -> str:
    d = date.today()
    d = d - timedelta(days=d.weekday())  # Monday of the current week
    return d.isoformat()


@pytest.fixture(scope="module")
def token() -> str:
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        timeout=30,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture
def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture
def cleanup_ids(auth_headers):
    """Delete any commitments created in the test after it runs."""
    created: list[str] = []
    yield created
    for cid in created:
        try:
            requests.delete(
                f"{BASE_URL}/api/portfolio/time-commitments/{cid}",
                headers=auth_headers,
                timeout=15,
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# A) end_time == "24:00" is a valid sentinel meaning "end of day"
# ---------------------------------------------------------------------------
def test_end_time_24_00_accepted(auth_headers, cleanup_ids):
    monday = _monday_iso()
    payload = {
        "title": f"TEST_sleep_night_{uuid.uuid4().hex[:6]}",
        "day_of_week": "monday",
        "start_time": "23:30",
        "end_time": "24:00",
        "commitment_type": "sleep",
        "flexibility": "fixed",
        "effective_from": monday,
        "source_type": "onboarding",
    }
    r = requests.post(
        f"{BASE_URL}/api/portfolio/time-commitments",
        headers=auth_headers,
        json=payload,
        timeout=30,
    )
    assert r.status_code == 201, f"24:00 sentinel rejected: {r.status_code} {r.text}"
    body = r.json()
    assert body["end_time"] == "24:00"
    assert body["start_time"] == "23:30"
    cleanup_ids.append(body["id"])


# ---------------------------------------------------------------------------
# B) end_time <= start_time (and != 24:00) is rejected 400
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "start,end",
    [
        ("10:00", "09:00"),   # end < start
        ("10:00", "10:00"),   # equal
        ("23:30", "06:30"),   # cross-midnight NOT allowed as single row
    ],
)
def test_end_before_or_equal_start_rejected(auth_headers, start, end):
    monday = _monday_iso()
    payload = {
        "title": "TEST_reject",
        "day_of_week": "monday",
        "start_time": start,
        "end_time": end,
        "commitment_type": "sleep",
        "flexibility": "fixed",
        "effective_from": monday,
    }
    r = requests.post(
        f"{BASE_URL}/api/portfolio/time-commitments",
        headers=auth_headers,
        json=payload,
        timeout=30,
    )
    assert r.status_code == 400, (
        f"expected 400 for start={start} end={end}, got {r.status_code} {r.text}"
    )


# ---------------------------------------------------------------------------
# C) Weekly capacity reflects newly-created block whose effective_from is
#    the current-local Monday (matches the frontend fix in setup.tsx).
# ---------------------------------------------------------------------------
def test_weekly_capacity_reflects_new_block(auth_headers, cleanup_ids):
    monday = _monday_iso()

    # Snapshot committed minutes on a target weekday BEFORE creating.
    target_dow = "thursday"
    r0 = requests.get(
        f"{BASE_URL}/api/portfolio/time-capacity/week",
        headers=auth_headers,
        params={"week_start_date": monday},
        timeout=30,
    )
    assert r0.status_code == 200, r0.text
    week_before = r0.json()
    thu_before = next(d for d in week_before["days"] if d["day_of_week"] == target_dow)
    committed_before = thu_before["committed_minutes"]
    available_before = thu_before["available_minutes"]

    # Pick a start_time that is guaranteed not to overlap: search for a free
    # 30-min slot within existing commitments (fallback 04:00-04:30).
    used = {(c["start_time"], c["end_time"]) for c in thu_before["commitments"]}
    start_time, end_time = "04:00", "04:30"
    # trivial: if 04:00-04:30 is already taken, try 04:30-05:00 etc.
    for h in range(2, 6):
        cand_s = f"{h:02d}:00"
        cand_e = f"{h:02d}:30"
        conflict = False
        for cs, ce in used:
            if not (cand_e <= cs or cand_s >= ce):
                conflict = True
                break
        if not conflict:
            start_time, end_time = cand_s, cand_e
            break

    payload = {
        "title": f"TEST_capacity_{uuid.uuid4().hex[:6]}",
        "day_of_week": target_dow,
        "start_time": start_time,
        "end_time": end_time,
        "commitment_type": "personal",
        "flexibility": "flexible",
        "effective_from": monday,
        "source_type": "onboarding",
    }
    r1 = requests.post(
        f"{BASE_URL}/api/portfolio/time-commitments",
        headers=auth_headers,
        json=payload,
        timeout=30,
    )
    assert r1.status_code == 201, r1.text
    cid = r1.json()["id"]
    cleanup_ids.append(cid)

    # Re-fetch the weekly capacity for the same Monday.
    r2 = requests.get(
        f"{BASE_URL}/api/portfolio/time-capacity/week",
        headers=auth_headers,
        params={"week_start_date": monday},
        timeout=30,
    )
    assert r2.status_code == 200, r2.text
    thu_after = next(d for d in r2.json()["days"] if d["day_of_week"] == target_dow)

    assert thu_after["committed_minutes"] >= committed_before + 30, (
        f"committed_minutes did not grow by >=30: "
        f"before={committed_before} after={thu_after['committed_minutes']}"
    )
    assert thu_after["available_minutes"] <= available_before - 30, (
        f"available_minutes did not shrink by >=30: "
        f"before={available_before} after={thu_after['available_minutes']}"
    )
    ids = [c["id"] for c in thu_after["commitments"]]
    assert cid in ids, "newly-created block missing from Thursday commitments list"


# ---------------------------------------------------------------------------
# D) Both records of a split cross-midnight block persist correctly.
#    (Frontend sends two POSTs — we simulate the same two payloads here.)
# ---------------------------------------------------------------------------
def test_cross_midnight_split_persists_both_halves(auth_headers, cleanup_ids):
    monday = _monday_iso()
    title = f"TEST_cross_{uuid.uuid4().hex[:6]}"
    # First half: Monday 23:30 -> 24:00
    r1 = requests.post(
        f"{BASE_URL}/api/portfolio/time-commitments",
        headers=auth_headers,
        json={
            "title": title,
            "day_of_week": "monday",
            "start_time": "23:30",
            "end_time": "24:00",
            "commitment_type": "sleep",
            "flexibility": "fixed",
            "effective_from": monday,
            "source_type": "onboarding",
        },
        timeout=30,
    )
    assert r1.status_code == 201, r1.text
    cleanup_ids.append(r1.json()["id"])

    # Second half: Tuesday 00:00 -> 06:30
    r2 = requests.post(
        f"{BASE_URL}/api/portfolio/time-commitments",
        headers=auth_headers,
        json={
            "title": title,
            "day_of_week": "tuesday",
            "start_time": "00:00",
            "end_time": "06:30",
            "commitment_type": "sleep",
            "flexibility": "fixed",
            "effective_from": monday,
            "source_type": "onboarding",
        },
        timeout=30,
    )
    assert r2.status_code == 201, r2.text
    cleanup_ids.append(r2.json()["id"])

    # Both should be listed
    r = requests.get(
        f"{BASE_URL}/api/portfolio/time-commitments",
        headers=auth_headers,
        timeout=30,
    )
    assert r.status_code == 200
    rows = [x for x in r.json() if x["title"] == title]
    assert len(rows) == 2
    days = sorted(x["day_of_week"] for x in rows)
    assert days == ["monday", "tuesday"]
    for x in rows:
        if x["day_of_week"] == "monday":
            assert x["start_time"] == "23:30" and x["end_time"] == "24:00"
        else:
            assert x["start_time"] == "00:00" and x["end_time"] == "06:30"

    # Weekly capacity should count 30 (Mon) + 390 (Tue) minutes for this pair.
    rw = requests.get(
        f"{BASE_URL}/api/portfolio/time-capacity/week",
        headers=auth_headers,
        params={"week_start_date": monday},
        timeout=30,
    )
    assert rw.status_code == 200
    mon = next(d for d in rw.json()["days"] if d["day_of_week"] == "monday")
    tue = next(d for d in rw.json()["days"] if d["day_of_week"] == "tuesday")
    mon_ids = {c["id"] for c in mon["commitments"]}
    tue_ids = {c["id"] for c in tue["commitments"]}
    assert r1.json()["id"] in mon_ids
    assert r2.json()["id"] in tue_ids
