"""Backend tests for Domains + Goals CRUD + default seeding + per-user isolation."""
import os
import time
import uuid

import pytest
import requests

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

DEFAULTS = {"Knowledge", "Health", "Money", "Soul"}


def _signup(email: str, password: str = "TestPass123!") -> str:
    r = requests.post(
        f"{API}/auth/signup",
        json={
            "email": email,
            "password": password,
            "security_question": "q?",
            "security_answer": "a",
        },
        timeout=15,
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


def _login(email: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def token_a() -> str:
    email = f"TEST_dg_a_{uuid.uuid4().hex[:8]}@hymn.app"
    return _signup(email)


@pytest.fixture(scope="module")
def token_b() -> str:
    email = f"TEST_dg_b_{uuid.uuid4().hex[:8]}@hymn.app"
    return _signup(email)


@pytest.fixture(scope="module")
def token_seed() -> str:
    """test@hymn.app – used to sanity-check the seeded user."""
    try:
        return _login("test@hymn.app", "TestPass123!")
    except AssertionError:
        return _signup("test@hymn.app", "TestPass123!")


# ---------- Domains ----------
class TestDomains:
    def test_default_seed_on_first_get(self, token_a):
        r = requests.get(f"{API}/domains", headers=_h(token_a), timeout=10)
        assert r.status_code == 200, r.text
        items = r.json()
        names = {d["name"] for d in items}
        assert DEFAULTS.issubset(names), f"missing defaults: {DEFAULTS - names}"
        for d in items:
            if d["name"] in DEFAULTS:
                assert d["is_default"] is True, d

    def test_seed_is_idempotent(self, token_a):
        r1 = requests.get(f"{API}/domains", headers=_h(token_a), timeout=10)
        r2 = requests.get(f"{API}/domains", headers=_h(token_a), timeout=10)
        assert r1.status_code == 200 and r2.status_code == 200
        names1 = sorted(d["name"] for d in r1.json())
        names2 = sorted(d["name"] for d in r2.json())
        assert names1 == names2
        # No duplicates
        assert len(names1) == len(set(names1))

    def test_seed_for_returning_user(self, token_seed):
        r = requests.get(f"{API}/domains", headers=_h(token_seed), timeout=10)
        assert r.status_code == 200
        names = {d["name"] for d in r.json()}
        assert DEFAULTS.issubset(names)

    def test_create_custom_domain(self, token_a):
        name = f"TEST_custom_{uuid.uuid4().hex[:6]}"
        r = requests.post(f"{API}/domains", headers=_h(token_a), json={"name": name}, timeout=10)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["name"] == name
        assert body["is_default"] is False
        # Verify persistence via GET
        lst = requests.get(f"{API}/domains", headers=_h(token_a), timeout=10).json()
        assert any(d["id"] == body["id"] and d["name"] == name for d in lst)

    def test_create_duplicate_case_insensitive_400(self, token_a):
        name = f"TEST_dupe_{uuid.uuid4().hex[:6]}"
        r1 = requests.post(f"{API}/domains", headers=_h(token_a), json={"name": name}, timeout=10)
        assert r1.status_code == 201
        r2 = requests.post(f"{API}/domains", headers=_h(token_a), json={"name": name.upper()}, timeout=10)
        assert r2.status_code == 400, r2.text

    def test_update_domain_name(self, token_a):
        old = f"TEST_upd_{uuid.uuid4().hex[:6]}"
        new = f"TEST_upd_new_{uuid.uuid4().hex[:6]}"
        d = requests.post(f"{API}/domains", headers=_h(token_a), json={"name": old}, timeout=10).json()
        r = requests.put(f"{API}/domains/{d['id']}", headers=_h(token_a), json={"name": new}, timeout=10)
        assert r.status_code == 200, r.text
        assert r.json()["name"] == new
        lst = requests.get(f"{API}/domains", headers=_h(token_a), timeout=10).json()
        assert any(x["id"] == d["id"] and x["name"] == new for x in lst)

    def test_update_domain_name_conflict_400(self, token_a):
        n1 = f"TEST_conflictA_{uuid.uuid4().hex[:6]}"
        n2 = f"TEST_conflictB_{uuid.uuid4().hex[:6]}"
        d1 = requests.post(f"{API}/domains", headers=_h(token_a), json={"name": n1}, timeout=10).json()
        requests.post(f"{API}/domains", headers=_h(token_a), json={"name": n2}, timeout=10)
        r = requests.put(f"{API}/domains/{d1['id']}", headers=_h(token_a), json={"name": n2}, timeout=10)
        assert r.status_code == 400

    def test_delete_domain_success(self, token_a):
        d = requests.post(f"{API}/domains", headers=_h(token_a), json={"name": f"TEST_del_{uuid.uuid4().hex[:6]}"}, timeout=10).json()
        r = requests.delete(f"{API}/domains/{d['id']}", headers=_h(token_a), timeout=10)
        assert r.status_code == 200, r.text
        lst = requests.get(f"{API}/domains", headers=_h(token_a), timeout=10).json()
        assert not any(x["id"] == d["id"] for x in lst)

    def test_delete_domain_with_linked_goal_400(self, token_a):
        d = requests.post(f"{API}/domains", headers=_h(token_a), json={"name": f"TEST_link_{uuid.uuid4().hex[:6]}"}, timeout=10).json()
        g = requests.post(
            f"{API}/goals",
            headers=_h(token_a),
            json={"title": "TEST_link_goal", "domain_id": d["id"]},
            timeout=10,
        ).json()
        r = requests.delete(f"{API}/domains/{d['id']}", headers=_h(token_a), timeout=10)
        assert r.status_code == 400, r.text
        # Cleanup: delete goal then domain
        requests.delete(f"{API}/goals/{g['id']}", headers=_h(token_a), timeout=10)
        r2 = requests.delete(f"{API}/domains/{d['id']}", headers=_h(token_a), timeout=10)
        assert r2.status_code == 200

    def test_delete_domain_not_owned_404(self, token_a, token_b):
        d = requests.post(f"{API}/domains", headers=_h(token_a), json={"name": f"TEST_own_{uuid.uuid4().hex[:6]}"}, timeout=10).json()
        r = requests.delete(f"{API}/domains/{d['id']}", headers=_h(token_b), timeout=10)
        assert r.status_code == 404


# ---------- Goals ----------
def _first_default_domain_id(tok: str) -> str:
    lst = requests.get(f"{API}/domains", headers=_h(tok), timeout=10).json()
    for d in lst:
        if d["name"] in DEFAULTS:
            return d["id"]
    raise AssertionError("no default domain found")


class TestGoals:
    def test_create_goal_valid(self, token_a):
        did = _first_default_domain_id(token_a)
        payload = {
            "title": f"TEST_goal_{uuid.uuid4().hex[:6]}",
            "domain_id": did,
            "target_outcome": "hit target",
            "deadline": "2026-12-31",
            "status": "active",
            "notes": "n",
        }
        r = requests.post(f"{API}/goals", headers=_h(token_a), json=payload, timeout=10)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["title"] == payload["title"]
        assert body["domain_id"] == did
        assert body["domain_name"]  # non-empty
        # GET verification
        got = requests.get(f"{API}/goals/{body['id']}", headers=_h(token_a), timeout=10).json()
        assert got["title"] == payload["title"]

    def test_create_goal_invalid_domain_400(self, token_a):
        r = requests.post(
            f"{API}/goals",
            headers=_h(token_a),
            json={"title": "x", "domain_id": "nonexistent-domain-id"},
            timeout=10,
        )
        assert r.status_code == 400

    def test_create_goal_invalid_status_400(self, token_a):
        did = _first_default_domain_id(token_a)
        r = requests.post(
            f"{API}/goals",
            headers=_h(token_a),
            json={"title": "x", "domain_id": did, "status": "bogus"},
            timeout=10,
        )
        assert r.status_code == 400

    def test_list_only_own_goals_and_domain_name(self, token_a, token_b):
        did_a = _first_default_domain_id(token_a)
        title = f"TEST_only_a_{uuid.uuid4().hex[:6]}"
        requests.post(f"{API}/goals", headers=_h(token_a), json={"title": title, "domain_id": did_a}, timeout=10)
        lst_a = requests.get(f"{API}/goals", headers=_h(token_a), timeout=10).json()
        lst_b = requests.get(f"{API}/goals", headers=_h(token_b), timeout=10).json()
        assert any(g["title"] == title for g in lst_a)
        assert not any(g["title"] == title for g in lst_b)
        # domain_name present on every item
        for g in lst_a:
            assert "domain_name" in g

    def test_cross_user_get_returns_404(self, token_a, token_b):
        did = _first_default_domain_id(token_a)
        g = requests.post(f"{API}/goals", headers=_h(token_a), json={"title": "TEST_iso", "domain_id": did}, timeout=10).json()
        r_get = requests.get(f"{API}/goals/{g['id']}", headers=_h(token_b), timeout=10)
        r_put = requests.put(f"{API}/goals/{g['id']}", headers=_h(token_b), json={"title": "hack"}, timeout=10)
        r_del = requests.delete(f"{API}/goals/{g['id']}", headers=_h(token_b), timeout=10)
        assert r_get.status_code == 404
        assert r_put.status_code == 404
        assert r_del.status_code == 404

    def test_status_transitions_persist(self, token_a):
        did = _first_default_domain_id(token_a)
        g = requests.post(f"{API}/goals", headers=_h(token_a), json={"title": "TEST_trans", "domain_id": did}, timeout=10).json()
        for st in ["paused", "completed", "abandoned"]:
            r = requests.put(f"{API}/goals/{g['id']}", headers=_h(token_a), json={"status": st}, timeout=10)
            assert r.status_code == 200, r.text
            got = requests.get(f"{API}/goals/{g['id']}", headers=_h(token_a), timeout=10).json()
            assert got["status"] == st

    def test_delete_goal(self, token_a):
        did = _first_default_domain_id(token_a)
        g = requests.post(f"{API}/goals", headers=_h(token_a), json={"title": "TEST_del", "domain_id": did}, timeout=10).json()
        r = requests.delete(f"{API}/goals/{g['id']}", headers=_h(token_a), timeout=10)
        assert r.status_code == 200
        assert requests.get(f"{API}/goals/{g['id']}", headers=_h(token_a), timeout=10).status_code == 404
