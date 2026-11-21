"""The admin page's server side: who gets in, usage and AI cost counting, the
budget stop and AI switches, actions on accounts, invites, and the rule that
the admin never sees content (and never sees Health use per person)."""
from __future__ import annotations

import asyncio
import base64
import json
import types
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

import ai_budget
import claude_client
import food_ai
import metering
from claude_client import AssistantUnavailable

BOSS = "boss@example.com"
PW = "correct-horse-battery"


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    metering._counts.clear()
    metering._seen.clear()
    metering._versions.clear()
    metering.reset_cache()
    monkeypatch.setenv("HYMN_ADMIN_EMAILS", BOSS)
    yield
    metering._counts.clear()
    metering._seen.clear()
    metering.reset_cache()


def _signup(client, email, name="Asha", **extra):
    r = client.post("/api/auth/signup", json={"name": name, "email": email, "password": PW,
                                              "security_question": "Q?", "security_answer": "A", **extra})
    return r


def _person(client, email, name="Asha"):
    b = _signup(client, email, name).json()
    return {"id": b["user"]["id"], "h": {"Authorization": f"Bearer {b['access_token']}"}, "email": email}


@pytest.fixture()
def boss(client):
    return _person(client, BOSS, "Boss")


@pytest.fixture()
def asha(client):
    return _person(client, "asha@example.com")


def _flush(server):
    asyncio.run(metering.flush(server.db))


class FakeAI:
    """The Anthropic client's inner object: records calls, returns usage."""

    def __init__(self, input_tokens=1_000_000, output_tokens=100_000, parsed=None):
        self.calls = 0
        self.usage = types.SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens,
                                           cache_read_input_tokens=0, cache_creation_input_tokens=0,
                                           server_tool_use=None)
        self.parsed = parsed
        outer = self

        async def parse(**kw):
            outer.calls += 1
            return types.SimpleNamespace(model=kw["model"], usage=outer.usage, stop_reason="end_turn",
                                         parsed_output=outer.parsed)
        self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(parse=parse, create=parse))
        self.messages = self.beta.messages

    def with_options(self, **kw):
        return self


@pytest.fixture()
def fake_ai(monkeypatch):
    fake = FakeAI()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(claude_client, "_client", fake)
    return fake


def _ai_call(feature, user_id, model="claude-haiku-5-5"):
    async def go():
        metering.set_actor(user_id, feature)
        return await claude_client.get_client().with_options(timeout=5).beta.messages.parse(model=model, messages=[])
    return asyncio.run(go())


# --- who gets in ------------------------------------------------------------------------

def test_only_the_admin_with_a_fresh_login_gets_in(client, server, boss, asha):
    assert client.get("/api/admin/overview", headers=asha["h"]).status_code == 403
    assert client.get("/api/admin/overview").status_code == 401
    assert client.get("/api/admin/overview", headers=boss["h"]).status_code == 200
    old = datetime.now(timezone.utc) - timedelta(hours=13)
    stale = jwt.encode({"sub": boss["id"], "tv": 0, "iat": old, "exp": old + timedelta(days=30)},
                       server.JWT_SECRET, algorithm=server.JWT_ALG)
    r = client.get("/api/admin/overview", headers={"Authorization": f"Bearer {stale}"})
    assert r.status_code == 401 and "sign in again" in r.json()["detail"]


def test_the_page_is_served_with_strict_headers(client):
    r = client.get("/admin")
    assert r.status_code == 200 and "Hymn Admin" in r.text
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store" and "innerHTML" not in r.text


# --- usage counting -----------------------------------------------------------------------

def test_usage_is_counted_per_person_and_feature(client, server, boss, asha):
    client.post("/api/tasks", headers=asha["h"], json={"title": "Call bank"})
    client.get("/api/tasks", headers={**asha["h"], "X-App-Version": "1.4.0"})
    client.post("/api/people", headers=asha["h"], json={"name": "Amma", "relation": "mother"})
    o = client.get("/api/admin/overview", headers=boss["h"]).json()
    feats = {f["feature"]: f for f in o["features_7_days"]}
    assert feats["tasks"]["calls"] == 2 and feats["tasks"]["people"] == 1 and feats["tasks"]["area"] == "everyday"
    assert feats["people"]["area"] == "family"
    assert "admin" not in feats                          # the admin page itself isn't counted
    assert o["people"]["active_today"] >= 1 and o["people"]["total"] == 2
    me = asyncio.run(server.db.users.find_one({"id": asha["id"]}))
    assert me["last_active_at"] and me["app_version"] == "1.4.0"
    row = next(u for u in client.get("/api/admin/users", headers=boss["h"]).json()["users"] if u["id"] == asha["id"])
    assert row["app_version"] == "1.4.0"


def test_server_errors_are_logged_without_content(server, monkeypatch, boss):
    from fastapi.testclient import TestClient

    c = TestClient(server.app, raise_server_exceptions=False)
    monkeypatch.setattr(server, "task_to_response", lambda d: 1 / 0)
    h = boss["h"]
    assert c.post("/api/tasks", headers=h, json={"title": "Private title"}).status_code == 500
    [e] = asyncio.run(server.db.errors.find({}, {"_id": 0}).to_list(length=None))
    assert e["route"] == "/api/tasks" and e["status"] == 500 and e["user_id"] == boss["id"]
    assert "Private title" not in json.dumps(e)
    sysinfo = c.get("/api/admin/system", headers=h).json()
    assert sysinfo["errors_7_days_by_route"] == [{"route": "POST /api/tasks", "count": 1}]


# --- AI cost, budget, switches ------------------------------------------------------------

def test_each_ai_call_is_costed_in_rupees(client, server, boss, asha, fake_ai):
    _ai_call("inbox", asha["id"])                       # 1M in + 100K out on Haiku = $0.10 + $0.05
    [row] = asyncio.run(server.db.ai_calls.find({}, {"_id": 0}).to_list(length=None))
    assert row["user_id"] == asha["id"] and row["feature"] == "inbox" and row["model"] == "claude-haiku-5-5"
    assert row["cost_usd"] == pytest.approx(0.15) and row["cost_inr"] == pytest.approx(0.15 * 88)
    _ai_call("plan-chat", asha["id"], model="claude-opus-5-5")   # $4 + $2 = $6
    ai = client.get("/api/admin/ai", headers=boss["h"]).json()
    assert ai["month_inr"] == pytest.approx(6.15 * 88)
    assert {f["feature"]: f["calls"] for f in ai["by_feature"]} == {"inbox": 1, "plan-chat": 1}
    assert ai["top_people"][0]["email"] == "asha@example.com"
    assert metering.cost_usd("claude-made-up", {"input": 1_000_000, "output": 0, "cache_read": 0,
                                                "cache_write": 0, "searches": 2}) == pytest.approx(4.02)


def test_the_monthly_stop_pauses_every_ai_feature(client, server, boss, asha, fake_ai):
    client.put("/api/admin/settings", headers=boss["h"], json={"ai_warn_inr": 10, "ai_stop_inr": 20})
    _ai_call("inbox", asha["id"])                       # ₹13.2: past the warning
    assert client.get("/api/admin/overview", headers=boss["h"]).json()["ai"]["status"] == "warning"
    _ai_call("inbox", asha["id"])                       # ₹26.4: past the stop
    with pytest.raises(AssistantUnavailable):
        _ai_call("learning", asha["id"])
    assert fake_ai.calls == 2                           # the third call never reached the AI
    assert client.get("/api/admin/overview", headers=boss["h"]).json()["ai"]["status"] == "stopped"
    client.put("/api/admin/settings", headers=boss["h"], json={"ai_stop_inr": 1000})
    _ai_call("learning", asha["id"])
    assert fake_ai.calls == 3


def test_a_switched_off_feature_is_refused_and_others_still_work(client, server, boss, asha, fake_ai):
    r = client.put("/api/admin/settings", headers=boss["h"], json={"ai_off": ["inbox"]})
    assert r.status_code == 200 and r.json()["ai_off"] == ["inbox"]
    with pytest.raises(AssistantUnavailable):
        _ai_call("inbox", asha["id"])
    _ai_call("learning", asha["id"])
    assert fake_ai.calls == 1
    assert client.put("/api/admin/settings", headers=boss["h"], json={"ai_off": ["chess"]}).status_code == 400
    assert client.put("/api/admin/settings", headers=boss["h"],
                      json={"ai_warn_inr": 50, "ai_stop_inr": 40}).status_code == 400


def test_a_real_route_is_attributed_to_its_person_and_feature(client, server, boss, asha, fake_ai):
    fake_ai.parsed = food_ai.PhotoReading(kind="not_food", items=[], label=food_ai.Label(
        product_name="", serving_size="", kcal="", protein_g="", carbs_g="", fat_g="", sugar_g=""))
    client.put("/api/health/profile", headers=asha["h"], json={"consent": True})
    img = base64.b64encode(b"\xff\xd8 fake jpeg").decode()
    assert client.post("/api/food/photo", headers=asha["h"], json={"image_base64": img,
                                                                   "media_type": "image/jpeg"}).status_code == 200
    [row] = asyncio.run(server.db.ai_calls.find({}, {"_id": 0}).to_list(length=None))
    assert row["user_id"] == asha["id"] and row["feature"] == "food"
    detail = client.get(f"/api/admin/users/{asha['id']}", headers=boss["h"]).json()
    assert [f["feature"] for f in detail["ai_month_by_feature"]] == ["private"]   # Health use is never shown per person


# --- privacy ------------------------------------------------------------------------------

def test_the_admin_never_sees_content(client, server, boss, asha):
    h = asha["h"]
    client.post("/api/tasks", headers=h, json={"title": "SECRET-TASK", "notes": "SECRET-NOTE"})
    client.post("/api/checkins", headers=h, json={"type": "life", "title": "SECRET-CHECKIN", "date": "2026-11-20",
                                                  "time": "07:00", "notes": "SECRET-DIARY"})
    client.post("/api/people", headers=h, json={"name": "SECRET-PERSON", "relation": "friend",
                                                "notes": "SECRET-PRIVATE"})
    client.post("/api/portfolio/financial-accounts", headers=h, json={
        "account_type": "bank", "name": "SECRET-BANK", "currency": "INR", "current_value": "987654",
        "liquidity_type": "liquid", "fixed_or_flexible": "flexible"})
    client.put("/api/health/profile", headers=h, json={"consent": True, "conditions": ["diabetes"]})
    client.post("/api/health/daily", headers=h, json={"date": "2026-11-20", "mood": 2, "sleep_hours": 5})
    seen = []
    for path in ("/api/admin/overview", "/api/admin/users", f"/api/admin/users/{asha['id']}", "/api/admin/ai",
                 "/api/admin/system", "/api/admin/audit", "/api/admin/invites", "/api/admin/settings"):
        r = client.get(path, headers=boss["h"])
        assert r.status_code == 200, path
        seen.append(r.text)
    everything = " ".join(seen)
    for secret in ("SECRET-", "987654", "diabetes"):
        assert secret not in everything
    detail = json.loads(seen[2])
    assert "health" not in json.dumps(detail["features_30_days"]) and "private" in json.dumps(detail["features_30_days"])
    assert all(s["key"] != "health" for s in detail["setup"])
    row = next(u for u in json.loads(seen[1])["users"] if u["email"] == "asha@example.com")
    assert "health" not in row["top_features"]
    overview = json.loads(seen[0])
    assert any(f["feature"] == "health" for f in overview["features_7_days"])   # totals still count it


# --- actions ------------------------------------------------------------------------------

def test_plan_allowance_sign_out_pause_and_delete(client, server, boss, asha):
    b = boss["h"]
    uid = asha["id"]
    assert client.post(f"/api/admin/users/{uid}/plan", headers=b, json={"plan": "premium"}).json()["plan"] == "premium"
    assert client.get("/api/auth/me", headers=asha["h"]).json()["plan"] == "premium"
    client.post(f"/api/admin/users/{uid}/plan", headers=b, json={"plan": "default"})
    assert client.get("/api/auth/me", headers=asha["h"]).json()["plan"] == "free"

    before = ai_budget.limit_for(asyncio.run(server.db.users.find_one({"id": uid})), "strong")
    client.post(f"/api/admin/users/{uid}/ai-allowance", headers=b, json={"strong": 30, "light": 0, "days": 7})
    assert ai_budget.limit_for(asyncio.run(server.db.users.find_one({"id": uid})), "strong") == before + 30

    client.post(f"/api/admin/users/{uid}/sign-out", headers=b)
    assert client.get("/api/auth/me", headers=asha["h"]).status_code == 401
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"email": asha["email"],
                                                                           "password": PW}).json()["access_token"]}
    client.post(f"/api/admin/users/{uid}/suspend", headers=b, json={"suspended": True})
    assert client.get("/api/auth/me", headers=h).status_code == 401           # paused also signs out
    r = client.post("/api/auth/login", json={"email": asha["email"], "password": PW})
    assert r.status_code == 403 and "paused" in r.json()["detail"]
    client.post(f"/api/admin/users/{uid}/suspend", headers=b, json={"suspended": False})
    assert client.post("/api/auth/login", json={"email": asha["email"], "password": PW}).status_code == 200

    assert client.post(f"/api/admin/users/{boss['id']}/suspend", headers=b, json={"suspended": True}).status_code == 400
    assert client.request("DELETE", f"/api/admin/users/{uid}", headers=b,
                          json={"confirm_email": "wrong@example.com"}).status_code == 400
    assert client.request("DELETE", f"/api/admin/users/{uid}", headers=b,
                          json={"confirm_email": "asha@example.com"}).status_code == 200
    assert asyncio.run(server.db.users.find_one({"id": uid})) is None
    actions = [a["action"] for a in client.get("/api/admin/audit", headers=b).json()]
    assert actions[:2] == ["delete_user", "unsuspend"] and "set_plan" in actions and "sign_out" in actions


def test_deleting_an_account_keeps_only_unnamed_totals(client, server, boss, asha, fake_ai):
    client.get("/api/tasks", headers=asha["h"])
    _ai_call("inbox", asha["id"])
    _flush(server)
    client.request("DELETE", f"/api/admin/users/{asha['id']}", headers=boss["h"], json={"confirm_email": asha["email"]})
    db = server.db
    for name in ("ai_calls", "usage_daily"):
        assert asyncio.run(db[name].count_documents({"user_id": asha["id"]})) == 0, name
    assert asyncio.run(db.ai_daily.count_documents({})) == 1
    assert asyncio.run(db.usage_totals.count_documents({"feature": "tasks"})) == 1


def test_old_detail_is_purged_and_daily_totals_stay(server, asha, fake_ai):
    _ai_call("inbox", asha["id"])
    asyncio.run(metering.record_error(server.db, "GET", "/api/x", 500, None))
    asyncio.run(metering.purge(server.db, datetime.now(timezone.utc) + timedelta(days=31)))
    assert asyncio.run(server.db.errors.count_documents({})) == 0
    assert asyncio.run(server.db.ai_calls.count_documents({})) == 1
    asyncio.run(metering.purge(server.db, datetime.now(timezone.utc) + timedelta(days=91)))
    assert asyncio.run(server.db.ai_calls.count_documents({})) == 0
    assert asyncio.run(server.db.ai_daily.count_documents({})) == 1


# --- invites --------------------------------------------------------------------------------

def test_invite_only_beta_with_friends_inviting_friends(client, server, boss):
    b = boss["h"]
    assert _signup(client, "open@example.com").status_code == 201             # off by default
    client.put("/api/admin/settings", headers=b, json={"invite_only": True, "invites_per_person": 1, "beta_cap": 5})
    r = _signup(client, "nocode@example.com")
    assert r.status_code == 403 and "invite-only" in r.json()["detail"]
    code = client.post("/api/admin/invites", headers=b, json={"count": 1, "max_uses": 2, "cohort": "friends"}) \
        .json()["codes"][0]
    assert client.get(f"/api/invites/check?code={code.lower()}").json()["valid"] is True
    r = _signup(client, "riya@example.com", invite_code=code.lower())            # any case works
    assert r.status_code == 201
    riya = {"Authorization": f"Bearer {r.json()['access_token']}"}
    mine = client.get("/api/invites/mine", headers=riya).json()
    assert mine["left"] == 1 and mine["invite_only"] is True
    assert _signup(client, "dev@example.com", invite_code=mine["code"]).status_code == 201   # a friend of a friend
    assert _signup(client, "dev2@example.com", invite_code=mine["code"]).status_code == 403  # Riya's code is used up
    dev = asyncio.run(server.db.users.find_one({"email": "dev@example.com"}))
    riya_doc = asyncio.run(server.db.users.find_one({"email": "riya@example.com"}))
    assert riya_doc["cohort"] == "friends" and riya_doc["invited_by"] == "admin"
    assert dev["invited_by"] == riya_doc["id"] and dev["cohort"] == "friends"
    users = client.get("/api/admin/users?q=friends", headers=b).json()["users"]
    assert {u["email"] for u in users} == {"riya@example.com", "dev@example.com"}
    assert next(u for u in users if u["email"] == "dev@example.com")["invited_by"] == "riya@example.com"
    # The cap: 5 accounts now exist (open, boss, riya, dev + one more), then it's full.
    assert _signup(client, "five@example.com", invite_code=code).status_code == 201
    r = _signup(client, "six@example.com", invite_code=client.post(
        "/api/admin/invites", headers=b, json={"count": 1}).json()["codes"][0])
    assert r.status_code == 403 and "full" in r.json()["detail"]
    client.post(f"/api/admin/invites/{code}/off", headers=b)
    assert client.get(f"/api/invites/check?code={code}").json()["valid"] is False


def test_a_paused_account_is_refused_even_with_a_valid_login(client, server, asha):
    asyncio.run(server.db.users.update_one({"id": asha["id"]}, {"$set": {"suspended": True}}))
    r = client.get("/api/auth/me", headers=asha["h"])
    assert r.status_code == 403 and "paused" in r.json()["detail"]
