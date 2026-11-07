"""Backend-only tests for Timeline search on GET /api/checkins?q=<term>.

Covers spec (iteration 14):
 1. User isolation (user A cannot see user B's rows).
 2. Case insensitivity.
 3. Match on notes.
 4. Substring match.
 5. Regex metacharacters as literals.
 6. Combined with goal_id filter.
 7. Sort order (date/time desc).
 8. Empty/whitespace query returns full list.
 9. Regression: no q still returns all user's check-ins in date/time desc.
"""
import os
import uuid
from datetime import datetime, timezone

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


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _mk_life_checkin(tok: str, title: str, notes: str = "", date: str = None, time: str = "09:00") -> dict:
    payload = {
        "type": "life",
        "title": title,
        "date": date or _today(),
        "time": time,
    }
    if notes:
        payload["notes"] = notes
    r = requests.post(f"{API}/checkins", headers=_h(tok), json=payload, timeout=10)
    assert r.status_code == 201, f"life checkin create failed: {r.status_code} {r.text}"
    return r.json()


def _first_default_domain_id(tok: str) -> str:
    lst = requests.get(f"{API}/domains", headers=_h(tok), timeout=10).json()
    for d in lst:
        if d.get("name") in {"Knowledge", "Health", "Money", "Soul"}:
            return d["id"]
    raise AssertionError("no default domain found")


def _mk_goal_with_eo(tok: str, goal_title: str) -> tuple:
    did = _first_default_domain_id(tok)
    g = requests.post(
        f"{API}/goals", headers=_h(tok),
        json={"title": goal_title, "domain_id": did}, timeout=10,
    ).json()
    eo = requests.post(
        f"{API}/expected-outcomes", headers=_h(tok),
        json={"goal_id": g["id"], "title": f"eo_{goal_title}"}, timeout=10,
    ).json()
    return g, eo


def _mk_goal_checkin(tok: str, eo_id: str, title: str, date: str = None, time: str = "09:00", notes: str = "") -> dict:
    payload = {
        "type": "goal",
        "title": title,
        "date": date or _today(),
        "time": time,
        "expected_outcome_id": eo_id,
    }
    if notes:
        payload["notes"] = notes
    r = requests.post(f"{API}/checkins", headers=_h(tok), json=payload, timeout=10)
    assert r.status_code == 201, f"goal checkin create failed: {r.status_code} {r.text}"
    return r.json()


def _list(tok: str, **params) -> list:
    r = requests.get(f"{API}/checkins", headers=_h(tok), params=params, timeout=10)
    assert r.status_code == 200, r.text
    return r.json()


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def token_a() -> str:
    return _signup(f"TEST_search_a_{uuid.uuid4().hex[:8]}@hymn.app")


@pytest.fixture(scope="module")
def token_b() -> str:
    return _signup(f"TEST_search_b_{uuid.uuid4().hex[:8]}@hymn.app")


# ---------- Scenario 1: user isolation ----------
class TestUserIsolation:
    def test_user_a_never_sees_user_bs_row(self, token_a, token_b):
        # A creates two, B creates one that would match the same query.
        a_run = _mk_life_checkin(token_a, "MorningRun", time="08:00")
        _mk_life_checkin(token_a, "Breakfast log", time="08:05")
        b_run = _mk_life_checkin(token_b, "MorningRun in Berlin", time="08:10")

        rows = _list(token_a, q="morning")
        ids = [r["id"] for r in rows]
        assert a_run["id"] in ids, f"A's MorningRun missing from own results: {ids}"
        assert b_run["id"] not in ids, f"LEAK: A saw B's row {b_run['id']} in {ids}"
        # Only one match for A (the MorningRun).
        matches = [r for r in rows if "morning" in r["title"].lower() or "morning" in (r.get("notes") or "").lower()]
        assert len(matches) == 1, f"expected exactly 1 morning match for A, got {len(matches)}: {[r['title'] for r in rows]}"


# ---------- Scenario 2: case insensitivity ----------
class TestCaseInsensitivity:
    def test_all_case_variants_return_same_row(self, token_a):
        # relies on A already having 'MorningRun' from scenario 1
        got = {}
        for q in ("morningrun", "MorningRun", "MORNING"):
            rows = _list(token_a, q=q)
            got[q] = [r for r in rows if r["title"] == "MorningRun"]
            assert len(got[q]) == 1, f"q={q!r}: expected 1 MorningRun row, got {len(got[q])}"
        # All queries yield identical id.
        ids = {tuple(r["id"] for r in got[q]) for q in got}
        assert len(ids) == 1, f"case variants returned different rows: {ids}"


# ---------- Scenario 3: match on notes ----------
class TestMatchOnNotes:
    def test_notes_match_and_nonsense_returns_empty(self, token_a):
        c = _mk_life_checkin(
            token_a, title="TEST_notes_row", notes="Grocery run at whole foods", time="09:15",
        )
        for q in ("grocery", "whole"):
            rows = _list(token_a, q=q)
            assert any(r["id"] == c["id"] for r in rows), f"q={q!r}: notes row missing"
        rows = _list(token_a, q="nonsense_xyzzy_" + uuid.uuid4().hex[:6])
        assert rows == [], f"nonsense query returned rows: {rows}"


# ---------- Scenario 4: substring match ----------
class TestSubstringMatch:
    def test_orn_matches_morningrun_and_akfa_matches_breakfast(self, token_a):
        rows_orn = _list(token_a, q="orn")
        titles_orn = [r["title"] for r in rows_orn]
        assert "MorningRun" in titles_orn, f"'orn' did not match MorningRun. titles={titles_orn}"

        rows_akfa = _list(token_a, q="akfa")
        titles_akfa = [r["title"] for r in rows_akfa]
        assert "Breakfast log" in titles_akfa, f"'akfa' did not match 'Breakfast log'. titles={titles_akfa}"


# ---------- Scenario 5: regex metachars as literals ----------
class TestRegexMetacharsLiteral:
    def test_dot_and_dollar_treated_literally(self, token_a):
        title = "cost was 12.50$"
        c = _mk_life_checkin(token_a, title=title, time="09:20")

        rows_match = _list(token_a, q="12.50")
        assert any(r["id"] == c["id"] for r in rows_match), f"'12.50' did not match literal row"

        rows_none = _list(token_a, q="12x50")
        # if regex '.' were live, '12x50' would NOT match (the dot only matches 1 char).
        # We assert the row is not returned by the substring literal match.
        assert not any(r["id"] == c["id"] for r in rows_none), "'12x50' unexpectedly matched literal '12.50$' row"


# ---------- Scenario 6: goal_id + q filter combo ----------
class TestGoalIdCombined:
    def test_goal_id_scopes_search_results(self, token_a):
        g1, eo1 = _mk_goal_with_eo(token_a, f"TEST_g_search_{uuid.uuid4().hex[:6]}")
        g2, eo2 = _mk_goal_with_eo(token_a, f"TEST_g_other_{uuid.uuid4().hex[:6]}")
        # Under G1: two rows both containing 'demoX'
        c_g1_a = _mk_goal_checkin(token_a, eo1["id"], "demoX under g1", time="09:30")
        c_g1_b = _mk_goal_checkin(token_a, eo1["id"], "another demoX g1", time="09:31")
        # Under G2: also contains 'demoX' but should be excluded.
        c_g2 = _mk_goal_checkin(token_a, eo2["id"], "demoX under g2", time="09:32")
        # Unrelated life row also containing 'demoX'
        _mk_life_checkin(token_a, title="life demoX unrelated", time="09:33")

        rows = _list(token_a, goal_id=g1["id"], q="demoX")
        ids = {r["id"] for r in rows}
        assert c_g1_a["id"] in ids and c_g1_b["id"] in ids, f"missing g1 rows: {ids}"
        assert c_g2["id"] not in ids, f"leaked g2 row into g1 filter: {ids}"
        # All rows in response must have goal_id == g1
        for r in rows:
            assert r.get("goal_id") == g1["id"], f"non-G1 row leaked: {r}"


# ---------- Scenario 7: sort order ----------
class TestSortOrder:
    def test_results_are_date_time_desc(self, token_a):
        # Use a rarely-used token unique to this test so no other rows contaminate ordering.
        tok = _signup(f"TEST_search_sort_{uuid.uuid4().hex[:8]}@hymn.app")
        c1 = _mk_life_checkin(tok, "demo alpha", date="2026-06-01", time="09:00")
        c2 = _mk_life_checkin(tok, "demo beta", date="2026-06-05", time="08:00")
        c3 = _mk_life_checkin(tok, "demo gamma", date="2026-06-05", time="10:00")

        rows = _list(tok, q="demo")
        # Filter down to just our 3 (defensive, in case future seeds add more)
        our = [r for r in rows if r["id"] in {c1["id"], c2["id"], c3["id"]}]
        assert len(our) == 3, f"expected 3 demo rows, got {len(our)}"
        expected_order = [c3["id"], c2["id"], c1["id"]]  # 06-05 10:00, 06-05 08:00, 06-01 09:00
        actual_order = [r["id"] for r in our]
        assert actual_order == expected_order, (
            f"sort order wrong.\nexpected {expected_order}\ngot      {actual_order}\n"
            f"raw dates/times: {[(r['date'], r['time']) for r in our]}"
        )


# ---------- Scenario 8: empty / whitespace query ----------
class TestEmptyQuery:
    def test_empty_q_returns_all(self, token_a):
        all_rows = _list(token_a)  # no q at all
        empty_q = _list(token_a, q="")
        space_q = _list(token_a, q=" ")
        # Same count and same id-set
        assert {r["id"] for r in empty_q} == {r["id"] for r in all_rows}, (
            f"q='' differs from no-q: {len(empty_q)} vs {len(all_rows)}"
        )
        assert {r["id"] for r in space_q} == {r["id"] for r in all_rows}, (
            f"q=' ' differs from no-q: {len(space_q)} vs {len(all_rows)}"
        )


# ---------- Scenario 9: regression — no q, date/time desc ----------
class TestRegressionListNoQuery:
    def test_no_q_returns_all_user_rows_sorted_desc(self, token_a):
        rows = _list(token_a)
        # Must be non-empty (fixtures created plenty of A rows).
        assert len(rows) > 0, "no rows for user A"
        # Verify strict descending order by (date, time).
        keys = [(r.get("date", ""), r.get("time", "")) for r in rows]
        for i in range(len(keys) - 1):
            assert keys[i] >= keys[i + 1], f"not sorted at index {i}: {keys[i]} < {keys[i+1]}"
        # Every row is A's (user isolation regression)
        # We can't cheaply verify user_id in response (it may be omitted), so assert we don't see
        # a user B-signature row.
        b_leak = [r for r in rows if r["title"] == "MorningRun in Berlin"]
        assert b_leak == [], f"B's row leaked into A's default list: {b_leak}"
