"""Premium: the trial, the beta pass, limits and Premium-only features (editable),
Razorpay and RevenueCat subscriptions (signed webhooks, grace, cancelling,
expiry), promo codes, cancelling, deletion, and the revenue numbers."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import pytest

import billing
import metering
import plan_assistant

BOSS = "boss@example.com"
PW = "correct-horse-battery"
RZP_SECRET = "rzp-webhook-secret"
RC_AUTH = "Bearer rc-secret"


@pytest.fixture(autouse=True)
def env(monkeypatch, server):
    monkeypatch.setenv("HYMN_ADMIN_EMAILS", BOSS)
    asyncio.run(billing.ensure_billing_indexes(server.db))      # the live server creates these at start-up


def _signup(client, email):
    b = client.post("/api/auth/signup", json={"name": "A", "email": email, "password": PW,
                                              "security_question": "Q?", "security_answer": "A"}).json()
    return {"id": b["user"]["id"], "h": {"Authorization": f"Bearer {b['access_token']}"}, "email": email}


def _settings(server, **changes):
    asyncio.run(metering.save_settings(server.db, changes))


@pytest.fixture()
def boss(client):
    return _signup(client, BOSS)


@pytest.fixture()
def asha(client):
    return _signup(client, "asha@example.com")


def _me(client, who):
    return client.get("/api/billing", headers=who["h"]).json()


@pytest.fixture()
def razorpay(server, monkeypatch):
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_key")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "rzp_test_secret")
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", RZP_SECRET)
    _settings(server, razorpay_plan_monthly="plan_M", razorpay_plan_yearly="plan_Y", razorpay_plan_founding="plan_F")
    calls = []

    def fake(method, path, body=None):
        calls.append((method, path, body))
        return {"id": f"sub_{len(calls)}", "short_url": "https://rzp.io/i/x", "status": "created"}
    monkeypatch.setattr(billing, "razorpay_request", fake)
    return calls


def _rzp_event(client, kind, sub_id, user_id, status, end, event_id, amount=19900, plan="plan_M", secret=RZP_SECRET):
    body = json.dumps({"entity": "event", "event": kind, "payload": {
        "subscription": {"entity": {"id": sub_id, "plan_id": plan, "status": status,
                                    "current_end": int(end.timestamp()), "notes": {"user_id": user_id}}},
        "payment": {"entity": {"id": "pay_1", "amount": amount}}}}).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post("/api/billing/webhooks/razorpay", content=body,
                       headers={"X-Razorpay-Signature": sig, "X-Razorpay-Event-Id": event_id,
                                "Content-Type": "application/json"})


NOW = datetime.now(timezone.utc)


# --- trial, beta pass ---------------------------------------------------------------------

def test_new_people_get_a_trial_that_ends(client, server):
    _settings(server, trial_days=14)
    p = _signup(client, "new@example.com")
    me = _me(client, p)
    assert me["plan"] == "premium" and me["in_trial"] is True and me["trial_days_left"] == 14
    assert me["source"] == "trial" and me["subscription"] is None
    asyncio.run(server.db.users.update_one({"id": p["id"]}, {"$set": {"trial_until": (NOW - timedelta(hours=1)).isoformat()}}))
    asyncio.run(billing.refresh(server.db, p["id"]))
    me = _me(client, p)
    assert me["plan"] == "free" and me["in_trial"] is False


def test_the_beta_pass_and_founding_members(client, server, boss, asha):
    later = (NOW + timedelta(days=60)).date().isoformat()
    r = client.post("/api/admin/billing/beta", headers=boss["h"], json={"until": later, "apply_to_everyone_now": True})
    assert r.json()["applied_to"] == 2
    assert _me(client, asha)["plan"] == "premium" and _me(client, asha)["founding_member"] is True
    newcomer = _signup(client, "late@example.com")
    me = _me(client, newcomer)
    assert me["source"] == "beta" and me["founding_member"] and me["prices"]["founding_yearly"] == 999
    client.post("/api/admin/billing/beta", headers=boss["h"], json={"until": None})
    assert _me(client, _signup(client, "after@example.com"))["plan"] == "free"


# --- limits and Premium-only features --------------------------------------------------------

def test_free_plan_limits_and_they_can_be_changed(client, server, boss, asha, monkeypatch):
    async def converse(db, user, chat, text):
        return "ok"
    monkeypatch.setattr(plan_assistant, "converse", converse)
    h = asha["h"]
    codes = [client.post("/api/plan-chat", headers=h, json={"message": "plan"}).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 403]
    r = client.post("/api/plan-chat", headers=h, json={"message": "plan"})
    assert "free plan includes 3 planning conversations" in r.json()["detail"]
    for i in range(2):
        r = client.post("/api/care", headers=h, json={"name": f"P{i}", "relation": "mother", "their_consent": True})
    assert r.status_code == 403
    r = client.put("/api/admin/settings", headers=boss["h"], json={"limits": {"care_profiles": {"free": 2, "premium": 5}}})
    assert r.status_code == 200 and r.json()["limits"]["care_profiles"]["free"] == 2
    assert r.json()["limits"]["planner_chats_month"]["free"] == 3                 # the others are kept
    assert client.post("/api/care", headers=h, json={"name": "P1", "relation": "father",
                                                      "their_consent": True}).status_code == 201
    assert client.put("/api/admin/settings", headers=boss["h"],
                      json={"limits": {"chess": {"free": 1}}}).status_code == 400
    assert client.put("/api/admin/settings", headers=boss["h"],
                      json={"limits": {"care_profiles": {"free": -1}}}).status_code == 400
    client.post(f"/api/admin/users/{asha['id']}/plan", headers=boss["h"], json={"plan": "premium"})
    assert client.post("/api/plan-chat", headers=h, json={"message": "plan"}).status_code == 200   # Premium: no limit


def test_premium_only_features_can_be_switched(client, server, boss, asha):
    assert client.get("/api/life-objects", headers=asha["h"]).status_code == 403
    client.put("/api/admin/settings", headers=boss["h"], json={"premium_only": ["statements"]})
    assert client.get("/api/life-objects", headers=asha["h"]).status_code == 200
    assert client.put("/api/admin/settings", headers=boss["h"], json={"premium_only": ["chess"]}).status_code == 400


def test_public_prices_follow_the_settings(client, boss):
    r = client.get("/api/billing/plans").json()
    assert (r["monthly"], r["yearly"], r["currency"]) == (199, 1499, "INR")
    assert {x["key"] for x in r["limits"]} >= {"planner_chats_month", "whatsapp_tasks_month"}
    client.put("/api/admin/settings", headers=boss["h"], json={"price_monthly_inr": 249})
    assert client.get("/api/billing/plans").json()["monthly"] == 249


# --- Razorpay -----------------------------------------------------------------------------------

def test_razorpay_checkout_payment_grace_cancel_and_expiry(client, server, asha, razorpay):
    r = client.post("/api/billing/checkout", headers=asha["h"], json={"plan": "monthly"})
    assert r.status_code == 200 and r.json()["key_id"] == "rzp_test_key" and r.json()["amount_inr"] == 199
    sub_id = r.json()["subscription_id"]
    assert razorpay[0][2]["plan_id"] == "plan_M" and razorpay[0][2]["notes"] == {"user_id": asha["id"]}
    assert _me(client, asha)["plan"] == "free"                                  # not paid yet
    assert _rzp_event(client, "subscription.activated", sub_id, asha["id"], "active", NOW + timedelta(days=30),
                      "evt_1", secret="forged").status_code == 401
    assert _rzp_event(client, "subscription.activated", sub_id, asha["id"], "active", NOW + timedelta(days=30),
                      "evt_1").json()["result"] == "active"
    me = _me(client, asha)
    assert me["plan"] == "premium" and me["source"] == "subscription"
    assert me["subscription"]["status"] == "active" and me["subscription"]["plan"] == "monthly"
    assert _rzp_event(client, "subscription.activated", sub_id, asha["id"], "active", NOW + timedelta(days=30),
                      "evt_1").json()["result"] == "duplicate"
    assert client.post("/api/billing/checkout", headers=asha["h"], json={"plan": "yearly"}).status_code == 409
    # A failed renewal: Premium continues for the grace days.
    _rzp_event(client, "subscription.pending", sub_id, asha["id"], "pending", NOW - timedelta(hours=1), "evt_2")
    sub = asyncio.run(server.db.subscriptions.find_one({"provider_ref": sub_id}))
    assert sub["status"] == "grace" and datetime.fromisoformat(sub["access_until"]) > NOW + timedelta(days=6)
    assert _me(client, asha)["plan"] == "premium"
    # Cancelled with time left: Premium until the end of the paid period.
    _rzp_event(client, "subscription.charged", sub_id, asha["id"], "active", NOW + timedelta(days=30), "evt_3")
    r = client.post("/api/billing/cancel", headers=asha["h"])
    assert r.status_code == 200 and razorpay[-1][1] == f"/subscriptions/{sub_id}/cancel"
    _rzp_event(client, "subscription.cancelled", sub_id, asha["id"], "cancelled", NOW + timedelta(days=30), "evt_4")
    me = _me(client, asha)
    assert me["plan"] == "premium" and me["subscription"]["ends_on"] and me["subscription"]["renews_on"] is None
    # Halted (no payment after retries): Premium ends.
    _rzp_event(client, "subscription.halted", sub_id, asha["id"], "halted", NOW - timedelta(days=1), "evt_5")
    assert _me(client, asha)["plan"] == "free"


def test_founding_members_pay_the_founding_price(client, server, boss, asha, razorpay):
    client.post("/api/admin/billing/beta", headers=boss["h"],
                json={"until": (NOW + timedelta(days=30)).date().isoformat(), "apply_to_everyone_now": True})
    r = client.post("/api/billing/checkout", headers=asha["h"], json={"plan": "yearly"})
    assert r.json()["plan"] == "founding" and r.json()["amount_inr"] == 999 and razorpay[-1][2]["plan_id"] == "plan_F"


def test_checkout_waits_for_payment_keys(client, asha):
    r = client.post("/api/billing/checkout", headers=asha["h"], json={"plan": "monthly"})
    assert r.status_code == 503 and "aren't set up" in r.json()["detail"]
    assert _me(client, asha)["can_buy_on_web"] is False


def test_a_manual_choice_beats_a_subscription(client, server, boss, asha, razorpay):
    sub_id = client.post("/api/billing/checkout", headers=asha["h"], json={"plan": "monthly"}).json()["subscription_id"]
    _rzp_event(client, "subscription.activated", sub_id, asha["id"], "active", NOW + timedelta(days=30), "e1")
    client.post(f"/api/admin/users/{asha['id']}/plan", headers=boss["h"], json={"plan": "free"})
    assert _me(client, asha)["plan"] == "free"


def test_deleting_an_account_stops_its_website_subscription(client, server, asha, razorpay):
    sub_id = client.post("/api/billing/checkout", headers=asha["h"], json={"plan": "monthly"}).json()["subscription_id"]
    _rzp_event(client, "subscription.activated", sub_id, asha["id"], "active", NOW + timedelta(days=30), "e1")
    client.request("DELETE", "/api/account", headers=asha["h"], json={"password": PW, "confirm": "DELETE"})
    assert razorpay[-1] == ("POST", f"/subscriptions/{sub_id}/cancel", {"cancel_at_cycle_end": 0})


# --- RevenueCat (stores) ------------------------------------------------------------------------

def _rc(client, event, auth=RC_AUTH):
    return client.post("/api/billing/webhooks/revenuecat", headers={"Authorization": auth},
                       json={"api_version": "1.0", "event": event})


def test_store_purchases_through_revenuecat(client, server, asha, monkeypatch):
    monkeypatch.setenv("REVENUECAT_WEBHOOK_AUTH", RC_AUTH)
    ms = lambda d: int((NOW + d).timestamp() * 1000)
    base = {"app_user_id": asha["id"], "product_id": "hymn_premium_yearly", "store": "PLAY_STORE",
            "original_transaction_id": "GPA.1", "environment": "PRODUCTION"}
    assert _rc(client, {**base, "type": "INITIAL_PURCHASE", "id": "rc1"}, auth="Bearer wrong").status_code == 401
    assert _rc(client, {"type": "TEST", "id": "t"}).json()["result"] == "test"
    assert _rc(client, {**base, "type": "INITIAL_PURCHASE", "id": "rc1", "expiration_at_ms": ms(timedelta(days=365)),
                        "price_in_purchased_currency": 1499, "currency": "INR"}).json()["result"] == "active"
    me = _me(client, asha)
    assert me["plan"] == "premium" and me["subscription"]["plan"] == "yearly" and me["subscription"]["store"] == "PLAY_STORE"
    r = client.post("/api/billing/cancel", headers=asha["h"])
    assert r.status_code == 409 and "Google Play" in r.json()["detail"]
    _rc(client, {**base, "type": "BILLING_ISSUE", "id": "rc2", "expiration_at_ms": ms(-timedelta(hours=1))})
    assert _me(client, asha)["plan"] == "premium"                                # grace
    _rc(client, {**base, "type": "EXPIRATION", "id": "rc3", "expiration_at_ms": ms(-timedelta(hours=1))})
    assert _me(client, asha)["plan"] == "free"
    assert _rc(client, {**base, "app_user_id": "nobody", "type": "RENEWAL", "id": "rc4"}).json()["result"] == "unknown_user"


# --- promo codes ----------------------------------------------------------------------------------

def test_promo_codes_add_free_premium_days_once(client, server, boss, asha):
    code = client.post("/api/admin/billing/promos", headers=boss["h"], json={"days": 30, "count": 1, "max_uses": 2}) \
        .json()["codes"][0]
    r = client.post("/api/billing/redeem", headers=asha["h"], json={"code": code.lower()})
    assert r.status_code == 200 and r.json()["premium_source"] == "promo"
    assert _me(client, asha)["plan"] == "premium"
    assert client.post("/api/billing/redeem", headers=asha["h"], json={"code": code}).status_code == 400   # once each
    other = _signup(client, "other@example.com")
    assert client.post("/api/billing/redeem", headers=other["h"], json={"code": code}).status_code == 200
    third = _signup(client, "third@example.com")
    assert client.post("/api/billing/redeem", headers=third["h"], json={"code": code}).status_code == 400   # used up
    assert client.post("/api/billing/redeem", headers=third["h"], json={"code": "NOPE1234"}).status_code == 400


# --- the admin's view ------------------------------------------------------------------------------

def test_revenue_numbers(client, server, boss, asha, razorpay):
    sub_id = client.post("/api/billing/checkout", headers=asha["h"], json={"plan": "monthly"}).json()["subscription_id"]
    _rzp_event(client, "subscription.activated", sub_id, asha["id"], "active", NOW + timedelta(days=30), "e1")
    d = client.get("/api/admin/billing", headers=boss["h"]).json()
    assert d["subscribers"] == 1 and d["monthly_revenue_inr"] == 199
    assert d["by_provider_plan"] == [{"key": "razorpay:monthly", "count": 1}]
    assert d["payments_ready"]["razorpay"] is True and d["events"][0]["email"] == "asha@example.com"
    assert client.get("/api/admin/billing", headers=asha["h"]).status_code == 403
    detail = client.get(f"/api/admin/users/{asha['id']}", headers=boss["h"]).json()
    assert detail["premium"]["source"] == "subscription" and detail["premium"]["subscription"]["plan"] == "monthly"


def test_one_learning_journey_at_a_time_on_the_free_plan(client, asha, monkeypatch):
    import learning_ai
    from learning_ai import Intake, Question

    async def intake(goal):
        return Intake(title=goal, shape="skill", questions=[Question(key="level", question="Level?")])
    monkeypatch.setattr(learning_ai, "intake", intake)
    first = client.post("/api/learning", headers=asha["h"], json={"goal": "Guitar"})
    assert first.status_code == 201
    assert client.post("/api/learning", headers=asha["h"], json={"goal": "Spanish"}).status_code == 403
    client.delete(f"/api/learning/{first.json()['id']}", headers=asha["h"])          # stopping one frees the slot
    assert client.post("/api/learning", headers=asha["h"], json={"goal": "Spanish"}).status_code == 201
