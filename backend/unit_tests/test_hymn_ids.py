"""Hymn IDs: 7 characters; real IDs free, special ones and aliases reserved."""
from __future__ import annotations

import asyncio
import re

import pytest

import hymn_ids
from hymn_ids import alias_problem, canonical, grade


def _signup(client, email, name="Priya Sharma"):
    r = client.post("/api/auth/signup", json={
        "name": name, "email": email, "password": "correct-horse-battery",
        "security_question": "Q?", "security_answer": "A"})
    assert r.status_code == 201, r.text
    body = r.json()
    return {"id": body["user"]["id"], "hymn_id": body["user"]["hymn_id"],
            "headers": {"Authorization": f"Bearer {body['access_token']}"}}


@pytest.mark.parametrize("value,expected", [
    ("S482915", "standard"),
    ("S777777", "special"), ("S000786", "special"), ("K001008", "special"),
    ("S123456", "pattern"), ("S654321", "pattern"), ("S123321", "pattern"), ("S121212", "pattern"),
    ("S150890", "birthday"), ("S290200", "birthday"),
    ("PRIYA88", "alias"), ("SAGAR77", "alias"), ("ROHIT21", "alias"),
    ("PRIYA", None),          # too short: everything is 7 characters
    ("PRIYA888", None),       # too long
    ("I123456", None),        # no I or O in real IDs
    ("A1234567", None),
    ("1234567", None),        # an alias needs letters
    ("S12345A", "alias"),     # two letters: allowed as an alias
])
def test_grades(value, expected):
    assert grade(value) == expected


def test_aliases_never_look_like_real_ids():
    assert alias_problem("SO12345") is not None   # reads as S012345
    assert alias_problem("PRIYA") == "An alias is exactly 7 letters and numbers, like PRIYA88."
    assert alias_problem("PRIYA88") is None
    assert alias_problem("TATA123") == "That alias isn't available."
    assert canonical("ROHIT21") == canonical("R0H1T21")  # look-alikes are the same ID


def test_everyone_gets_a_free_standard_id(client, server):
    a = _signup(client, "a@example.com")
    b = _signup(client, "b@example.com")
    assert re.match(r"^[A-HJ-NP-Z]\d{6}$", a["hymn_id"]) and grade(a["hymn_id"]) == "standard"
    assert a["hymn_id"] != b["hymn_id"]
    me = client.get("/api/auth/me", headers=a["headers"]).json()
    assert me["hymn_id"] == a["hymn_id"]  # stable


def test_existing_users_get_one_when_seen(client, server):
    a = _signup(client, "old@example.com")
    asyncio.run(server.db.users.update_one({"id": a["id"]}, {"$unset": {"hymn_id": ""}}))
    asyncio.run(server.db.hymn_ids.delete_many({}))
    me = client.get("/api/auth/me", headers=a["headers"]).json()
    assert grade(me["hymn_id"]) == "standard"


def test_generator_skips_special_numbers(server, monkeypatch):
    rolls = iter([777777, 123456, 150890, 482915])
    monkeypatch.setattr(hymn_ids.secrets, "randbelow", lambda n: next(rolls))
    monkeypatch.setattr(hymn_ids.secrets, "choice", lambda s: "S")
    assert asyncio.run(hymn_ids.assign_real_id(server.db, "u-1")) == "S482915"


def test_check_and_find(client, server):
    a = _signup(client, "find@example.com")
    b = _signup(client, "other@example.com", name="Ravi")
    c = client.get("/api/hymn-id/check/S777777", headers=a["headers"]).json()
    assert (c["grade"], c["available"], c["can_claim_now"]) == ("special", True, False)
    assert client.get("/api/hymn-id/check/PRIYA", headers=a["headers"]).json()["valid"] is False
    found = client.get(f"/api/hymn-id/find/{b['hymn_id'].lower()}", headers=a["headers"]).json()
    assert found == {"hymn_id": b["hymn_id"], "alias": None, "first_name": "Ravi"}
    assert client.get("/api/hymn-id/find/S000001", headers=a["headers"]).status_code == 404


def test_lookups_are_rate_limited(client, server):
    a = _signup(client, "limit@example.com")
    hymn_ids._LOOKUPS.clear()
    codes = [client.get("/api/hymn-id/check/S482915", headers=a["headers"]).status_code for _ in range(21)]
    assert codes[-1] == 429 and set(codes[:-1]) == {200}
