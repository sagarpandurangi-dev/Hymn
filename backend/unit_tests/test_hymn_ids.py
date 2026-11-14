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


def test_owner_granted_alias(client, server, monkeypatch):
    monkeypatch.setenv("HYMN_ALIAS_GRANTS", "Owner@Example.com=sagar77, bad@example.com=PRIYA")
    a = _signup(client, "owner@example.com", name="Sagar")
    me = client.get("/api/auth/me", headers=a["headers"]).json()
    assert me["hymn_alias"] == "SAGAR77" and grade(me["hymn_id"]) == "standard"
    b = _signup(client, "someone@example.com")
    found = client.get("/api/hymn-id/find/sagar77", headers=b["headers"]).json()
    assert found == {"hymn_id": me["hymn_id"], "alias": "SAGAR77", "first_name": "Sagar"}
    assert client.get("/api/hymn-id/check/SAGAR77", headers=b["headers"]).json()["available"] is False
    bad = _signup(client, "bad@example.com")
    assert client.get("/api/auth/me", headers=bad["headers"]).json()["hymn_alias"] is None  # invalid alias ignored


def test_granted_alias_already_taken_is_not_stolen(client, server, monkeypatch):
    a = _signup(client, "first@example.com")
    asyncio.run(hymn_ids.grant_alias(server.db, {"id": a["id"]}, "SAGAR77"))
    monkeypatch.setenv("HYMN_ALIAS_GRANTS", "second@example.com=SAGAR77")
    b = _signup(client, "second@example.com")
    assert client.get("/api/auth/me", headers=b["headers"]).json()["hymn_alias"] is None


def test_prices_set_themselves():
    from hymn_ids import quote
    p = lambda v, g, s=0, n=0: quote(v, g, s, n)
    assert p("S482915", "standard") == {"price_inr": 0, "how": "free"}
    ladder = [p("S123456", "pattern")["price_inr"], p("S150890", "birthday")["price_inr"],
              p("S000786", "special")["price_inr"], p("S777777", "special")["price_inr"],
              p("SAGAR77", "alias")["price_inr"]]
    assert ladder == sorted(ladder) and len(set(ladder)) == 5        # cheapest → dearest, SAGAR77 on top
    assert p("S150890", "birthday", 3)["price_inr"] > p("S150890", "birthday", 0)["price_inr"]  # demand
    assert p("PRIYA88", "alias", 0, 500)["price_inr"] is None or \
        p("PRIYA88", "alias", 0, 500)["price_inr"] > p("XQZRT88", "alias")["price_inr"]   # popular names
    hot = p("S150890", "birthday", 10)
    assert hot["how"] == "auction" and hot["reserve_inr"] > 0                           # many want it


def test_base_prices_can_be_tuned_without_code(monkeypatch):
    from hymn_ids import quote
    before = quote("S123456", "pattern", 0)["price_inr"]
    monkeypatch.setenv("HYMN_ID_BASE_PRICES", "pattern=499")
    assert quote("S123456", "pattern", 0)["price_inr"] > before


def test_check_shows_price_and_counts_demand(client, server):
    users = [_signup(client, f"buyer{i}@example.com") for i in range(3)]
    first = client.get("/api/hymn-id/check/S150890", headers=users[0]["headers"]).json()
    client.get("/api/hymn-id/check/S150890", headers=users[0]["headers"])   # same person again: no extra demand
    assert client.get("/api/hymn-id/check/S150890", headers=users[0]["headers"]).json()["price_inr"] == first["price_inr"]
    for u in users[1:]:
        client.get("/api/hymn-id/check/S150890", headers=u["headers"])
    later = client.get("/api/hymn-id/check/S150890", headers=users[0]["headers"]).json()
    assert later["how"] == "fixed" and later["price_inr"] > first["price_inr"]
    free = client.get("/api/hymn-id/check/S482915", headers=users[0]["headers"]).json()
    assert "price_inr" not in free or free["price_inr"] == 0


def test_lookalike_aliases_are_the_same(client, server, monkeypatch):
    from hymn_ids import skeleton
    assert skeleton("SAGAR77") == skeleton("5AGAR77") == skeleton("SA6AR77")
    assert alias_problem("S1Z3456") is not None          # reads as the real ID S123456
    assert alias_problem("SB12345") is not None          # reads as S812345
    monkeypatch.setenv("HYMN_ALIAS_GRANTS", "owner2@example.com=SAGAR77,copy@example.com=5AGAR77")
    owner = _signup(client, "owner2@example.com", name="Sagar")
    assert client.get("/api/auth/me", headers=owner["headers"]).json()["hymn_alias"] == "SAGAR77"
    copy = _signup(client, "copy@example.com")
    assert client.get("/api/auth/me", headers=copy["headers"]).json()["hymn_alias"] is None
    assert client.get("/api/hymn-id/check/5AGAR77", headers=copy["headers"]).json()["available"] is False
    found = client.get("/api/hymn-id/find/5AGAR77", headers=copy["headers"]).json()
    assert found["alias"] == "SAGAR77"
