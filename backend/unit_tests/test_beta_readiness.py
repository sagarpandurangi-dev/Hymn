"""Beta readiness: AI daily caps, upload size cap, safe headers, docs off in
production, account export and deletion, first-time setup."""
from __future__ import annotations

import asyncio
import importlib

import pytest

import ai_budget
import learning_ai
from learning_ai import Intake, Question


def _signup(client, email, name="Asha"):
    b = client.post("/api/auth/signup", json={"name": name, "email": email, "password": "correct-horse-battery",
                                              "security_question": "Q?", "security_answer": "A"}).json()
    return b["user"]["id"], {"Authorization": f"Bearer {b['access_token']}"}


@pytest.fixture()
def user(client):
    uid, h = _signup(client, "beta@example.com")
    return {"id": uid, "headers": h}


def test_ai_calls_are_capped_per_person_per_day(client, user, monkeypatch):
    async def intake(goal):
        return Intake(title="X", shape="skill", questions=[Question(key="level", question="Level?")])
    monkeypatch.setattr(learning_ai, "intake", intake)
    monkeypatch.setenv("HYMN_AI_LIGHT_PER_DAY", "2")
    h = user["headers"]
    assert [client.post("/api/learning", headers=h, json={"goal": "Guitar"}).status_code for _ in range(3)] == \
        [201, 201, 429]
    # Someone else has their own allowance; Premium has more.
    _, other = _signup(client, "beta2@example.com")
    assert client.post("/api/learning", headers=other, json={"goal": "Guitar"}).status_code == 201
    assert ai_budget.limit_for({"plan": "premium"}, "strong") > ai_budget.limit_for({"plan": "free"}, "strong")
    # The expensive bucket is separate and guards the planner.
    monkeypatch.setenv("HYMN_AI_STRONG_PER_DAY", "0")
    r = client.post("/api/plan-chat", headers=h, json={"text": "Plan a trip"})
    assert r.status_code == 429 and "resets tomorrow" in r.json()["detail"]


def test_oversized_uploads_are_refused_and_headers_are_safe(client, user):
    r = client.post("/api/food/photo", headers={**user["headers"], "Content-Length": str(40 * 1024 * 1024)},
                    content=b"{}")
    assert r.status_code == 413
    ok = client.get("/api/", headers=user["headers"])
    assert ok.headers["X-Content-Type-Options"] == "nosniff" and ok.headers["X-Frame-Options"] == "DENY"
    assert ok.headers["Cache-Control"] == "no-store" and "max-age" in ok.headers["Strict-Transport-Security"]


def test_api_docs_are_off_in_production_only(server, monkeypatch):
    assert server.app.docs_url == "/docs"                       # test / preview keep them
    monkeypatch.setenv("HYMN_RUNTIME_MODE", "production")
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    try:
        prod = importlib.reload(server)
        assert prod.app.docs_url is None and prod.app.openapi_url is None and prod.app.redoc_url is None
    finally:
        monkeypatch.setenv("HYMN_RUNTIME_MODE", "test")
        monkeypatch.delenv("JWT_SECRET", raising=False)
        importlib.reload(server)


def test_domain_names_with_symbols_are_matched_literally(client, user):
    h = user["headers"]
    assert client.post("/api/domains", headers=h, json={"name": "C++ (work)"}).status_code == 201
    assert client.post("/api/domains", headers=h, json={"name": "C++ (work)"}).status_code == 400   # duplicate
    assert client.post("/api/domains", headers=h, json={"name": ".*"}).status_code == 201            # not a wildcard


def _fill(client, server, uid, h):
    client.put("/api/health/profile", headers=h, json={"consent": True})
    client.post("/api/health/daily", headers=h, json={"date": "2026-11-10", "mood": 4})
    amma = client.post("/api/care", headers=h, json={"name": "Amma", "relation": "mother", "their_consent": True}).json()
    client.put(f"/api/health/profile?for={amma['id']}", headers=h, json={"consent": True})
    client.post(f"/api/health/measurements?for={amma['id']}", headers=h,
                json=[{"metric": "bp_systolic", "value": 130, "taken_on": "2026-11-10"}])
    client.post("/api/people", headers=h, json={"name": "Priya", "relation": "friend"})
    client.post("/api/work/roles", headers=h, json={"type": "salaried", "organisation": "Acme",
                                                    "start_time": "09:00", "end_time": "18:00"})
    assert client.post("/api/family", headers=h, json={"name": "Home"}).status_code in (200, 201)
    assert asyncio.run(server.db.households.count_documents({})) == 1
    return amma


def test_export_has_everything_but_secrets(client, server, user):
    amma = _fill(client, server, user["id"], user["headers"])
    out = client.get("/api/account/export", headers=user["headers"]).json()
    text = str(out)
    assert "hashed_password" not in text and "hashed_security_answer" not in text
    assert {"health_measurements", "people", "work_roles", "time_commitments", "care_profiles"} <= set(out["data"])
    assert any(r["user_id"] == amma["id"] for r in out["data"]["health_measurements"])    # people you look after
    assert out["account"]["email"] == "beta@example.com"


def test_deleting_an_account_removes_everything_and_only_theirs(client, server, user):
    db, h = server.db, user["headers"]
    amma = _fill(client, server, user["id"], h)
    other_id, oh = _signup(client, "stays@example.com", "Stay")
    client.post("/api/people", headers=oh, json={"name": "Kept", "relation": "friend"})
    my_id = client.get("/api/auth/me", headers=h).json()["hymn_id"]
    assert client.request("DELETE", "/api/account", headers=h, json={"password": "wrong", "confirm": "DELETE"}) \
        .status_code == 400
    assert client.request("DELETE", "/api/account", headers=h,
                          json={"password": "correct-horse-battery", "confirm": "yes"}).status_code == 400
    r = client.request("DELETE", "/api/account", headers=h,
                       json={"password": "correct-horse-battery", "confirm": "DELETE"})
    assert r.status_code == 200 and r.json()["records_removed"] > 5
    assert client.get("/api/auth/me", headers=h).status_code == 401                       # signed out everywhere

    async def left():
        n = 0
        for name in await db.list_collection_names():
            n += await db[name].count_documents({"user_id": {"$in": [user["id"], amma["id"]]}})
        return n, await db.care_profiles.count_documents({}), await db.households.count_documents({}), \
            await db.people.count_documents({"user_id": other_id}), await db.hymn_ids.find_one({"display": my_id})
    n, care, homes, others_people, retired = asyncio.run(left())
    assert (n, care, homes, others_people) == (0, 0, 0, 1)
    assert retired["status"] == "retired" and retired["owner_user_id"] is None           # never reissued
    assert client.post("/api/auth/login", json={"email": "beta@example.com",
                                                "password": "correct-horse-battery"}).status_code == 400


def test_first_time_setup_checklist(client, server, user, monkeypatch):
    h = user["headers"]
    s = client.get("/api/account/setup", headers=h).json()
    assert (s["done"], s["complete"], s["next"]["key"]) == (0, False, "timezone")
    assert next(x for x in s["steps"] if x["key"] == "health")["optional"] is True
    client.put("/api/nudges/settings", headers=h, json={"timezone": "Asia/Kolkata"})
    client.post("/api/work/roles", headers=h, json={"type": "salaried", "start_time": "09:00", "end_time": "18:00"})
    client.post("/api/people", headers=h, json={"name": "Priya", "relation": "friend"})
    s = client.get("/api/account/setup", headers=h).json()
    assert s["done"] == 3 and s["next"]["key"] == "accounts" and s["of"] == 6
