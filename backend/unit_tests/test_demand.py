"""Demand reports for local sellers: what people plan (property, car…), counted anonymously.

Rules that matter: sellers only see people who switched sharing on, only groups of at least
``demand_min_count``, never sensitive categories, never anything personal, and nothing at all
until the owner switches sharing on; Pamphlet needs the partner key; every pull is logged."""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pytest

import demand
import metering

BOSS = "boss@example.com"
PW = "correct-horse-battery"
KEY = "partner-test-key"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("HYMN_ADMIN_EMAILS", BOSS)
    monkeypatch.setenv("HYMN_PARTNER_KEY", KEY)
    metering._counts.clear()
    metering.reset_cache()
    yield
    metering._counts.clear()


def _person(client, email, name="Asha"):
    b = client.post("/api/auth/signup", json={"name": name, "email": email, "password": PW,
                                               "security_question": "Q?", "security_answer": "A"}).json()
    return {"id": b["user"]["id"], "h": {"Authorization": f"Bearer {b['access_token']}"}}


def _day(n):
    return (date.today() + timedelta(days=n)).isoformat()


def _seed(server, n, *, consent=True, category="property", form="3 BHK", city="Bengaluru", area="Whitefield",
          budget=10_000_000, days=60, prefix="u", status="active"):
    async def go():
        for i in range(n):
            uid = f"{prefix}{i}"
            await server.db.users.insert_one({"id": uid, "email": f"{uid}@x.com", "name": f"Secret Name {uid}",
                                              "demand_sharing": {"on": consent}})
            await server.db.life_plans.insert_one({
                "id": f"plan-{uid}", "user_id": uid, "title": "Our home", "status": status,
                "target_date": _day(days), "for_what": "private note about my family",
                "intent": {"category": category, "form": form, "budget_inr": budget, "city": city,
                           "area": area, "pincode": "560066", "source": "planner"}})
    asyncio.run(go())


def _sharing(server, on=True, min_count=None):
    changes = {"demand_sharing_on": on}
    if min_count:
        changes["demand_min_count"] = min_count
    asyncio.run(metering.save_settings(server.db, changes))


def _pull(client, **params):
    return client.get("/api/partner/demand", params=params, headers={"X-Hymn-Partner-Key": KEY})


# ---------------------------------------------------------------------------
# Classifying plans
# ---------------------------------------------------------------------------

def test_classify_reads_title_form_and_budget():
    assert demand.classify({"title": "Buy a 3BHK flat in Pune, about 1.2 Cr"}) == {
        "category": "property", "form": "3 BHK", "budget_inr": 12_000_000, "source": "guess"}
    c = demand.classify({"title": "New electric SUV under 25 lakh"})
    assert (c["category"], c["form"], c["budget_inr"]) == ("car", "SUV", 2_500_000)
    assert demand.classify({"title": "Learn guitar"})["category"] == "other"
    assert demand.classify({"title": "Plan", "template": "first_child"})["category"] == "child"


def test_clean_intent_prefers_what_was_said_and_tidies_it():
    it = demand.clean_intent({"title": "Our home 2 BHK"}, {"category": "property", "form": "3 BHK",
                                                           "budget_inr": "9500000", "city": "bengaluru",
                                                           "area": " whitefield ", "pincode": "560 066"})
    assert it == {"category": "property", "form": "3 BHK", "budget_inr": 9_500_000, "city": "Bengaluru",
                  "area": "Whitefield", "pincode": "560066", "source": "planner"}
    assert demand.clean_intent({"title": "x"}, {"category": "spaceship", "pincode": "12"})["category"] == "other"
    assert demand.clean_intent({"title": "x"}, {"budget_inr": -5})["budget_inr"] is None


def test_plans_store_an_intent(client):
    a = _person(client, "asha@example.com")
    r = client.post("/api/life-plans", headers=a["h"], json={
        "title": "Buy a 2 BHK in Pune", "target_date": _day(200),
        "requirements": [{"area": "money", "what": "Down payment", "kind": "money", "amount": 2000000,
                          "needed_by": _day(190)}],
        "intent": {"city": "Pune", "area": "Baner", "budget_inr": 8000000}})
    assert r.status_code == 201, r.text
    import server
    plan = asyncio.run(server.db.life_plans.find_one({"user_id": a["id"]}))
    assert plan["intent"]["category"] == "property" and plan["intent"]["form"] == "2 BHK"
    assert plan["intent"]["area"] == "Baner" and plan["intent"]["budget_inr"] == 8_000_000

    fix = client.patch(f"/api/demand/plans/{plan['id']}", headers=a["h"], json={"form": "3 BHK", "pincode": "411045"})
    assert fix.status_code == 200 and fix.json()["intent"]["form"] == "3 BHK"
    assert fix.json()["intent"]["area"] == "Baner" and fix.json()["intent"]["source"] == "person"
    b = _person(client, "bina@example.com", "Bina")
    assert client.patch(f"/api/demand/plans/{plan['id']}", headers=b["h"], json={"form": "1 BHK"}).status_code == 404


# ---------------------------------------------------------------------------
# Consent
# ---------------------------------------------------------------------------

def test_consent_is_off_by_default_and_logged(client, server):
    a = _person(client, "asha@example.com")
    assert client.get("/api/demand/consent", headers=a["h"]).json()["on"] is False
    assert client.put("/api/demand/consent", headers=a["h"], json={"on": True}).json()["on"] is True
    assert client.get("/api/demand/consent", headers=a["h"]).json()["on"] is True
    client.put("/api/demand/consent", headers=a["h"], json={"on": False})
    log = asyncio.run(server.db.consent_log.find({"user_id": a["id"]}).to_list(10))
    assert [x["on"] for x in log] == [True, False] and all(x["consent_text_version"] for x in log)


# ---------------------------------------------------------------------------
# Pamphlet's report
# ---------------------------------------------------------------------------

def test_the_owners_example_report(client, server):
    _seed(server, 25)
    _sharing(server)
    r = _pull(client, category="property", city="Bengaluru", area="Whitefield", within_days=100)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["people"] == 25 and body["budget"]["average"] == "₹1 Cr"
    assert body["forms"][0] == {"form": "3 BHK", "share": 100}
    assert body["text"].startswith("25 people would like to buy a home in Whitefield, Bengaluru within 100 days.")
    assert "Average budget: ₹1 Cr" in body["text"] and "Focus on 3 BHK" in body["text"]


def test_nothing_personal_ever_reaches_pamphlet(client, server):
    _seed(server, 25)
    _sharing(server)
    text = str(_pull(client, category="property").json()) + str(
        client.get("/api/partner/demand/areas", params={"category": "property"},
                   headers={"X-Hymn-Partner-Key": KEY}).json())
    for leak in ("Secret Name", "@x.com", "u1", "plan-", "private note", "560066", "user_id"):
        assert leak not in text


def test_only_people_who_agreed_are_counted(client, server):
    _seed(server, 15, prefix="yes")
    _seed(server, 30, consent=False, prefix="no")
    _sharing(server)
    body = _pull(client, category="property").json()
    assert body["people"] is None and body["hidden"] is True and body["text"] == ""
    _seed(server, 5, prefix="more")
    assert _pull(client, category="property").json()["people"] == 20


def test_small_groups_are_hidden(client, server):
    _seed(server, 19)
    _sharing(server)
    assert _pull(client, category="property").json()["people"] is None
    _seed(server, 1, prefix="last")
    assert _pull(client, category="property").json()["people"] == 20


def test_areas_only_listed_when_big_enough(client, server):
    _seed(server, 22, area="Whitefield")
    _seed(server, 8, area="Indiranagar", prefix="ind")
    _sharing(server)
    body = _pull(client, category="property", city="Bengaluru").json()
    assert body["people"] == 30 and [a["area"] for a in body["areas"]] == ["Whitefield"]
    areas = client.get("/api/partner/demand/areas", params={"category": "property"},
                       headers={"X-Hymn-Partner-Key": KEY}).json()["areas"]
    assert areas == [{"city": "Bengaluru", "area": "Whitefield", "people": 22}]


def test_timeframe_drafts_and_past_plans(client, server):
    _seed(server, 20, days=60, prefix="soon")
    _seed(server, 20, days=300, prefix="later")
    _seed(server, 20, status="draft", prefix="draft")
    _seed(server, 20, days=-5, prefix="past")
    _sharing(server)
    assert _pull(client, category="property", within_days=100).json()["people"] == 20
    body = _pull(client, category="property").json()
    assert body["people"] == 40 and body["when"]["within 100 days"] == 20 and body["when"]["within a year"] == 20


def test_sensitive_categories_never_go_out(client, server):
    _seed(server, 30, category="child", form="", prefix="c")
    _seed(server, 30, category="health", form="", prefix="h")
    _sharing(server)
    assert _pull(client, category="child").status_code == 400
    assert _pull(client, category="health").status_code == 400
    boss = _person(client, BOSS, "Boss")
    cats = {c["category"]: c for c in client.get("/api/admin/demand", headers=boss["h"]).json()["categories"]}
    assert cats["child"]["people"] == 30 and cats["child"]["shareable_people"] is None
    assert cats["child"]["never_shared"] is True


def test_switched_off_until_the_owner_turns_it_on(client, server):
    _seed(server, 25)
    assert _pull(client, category="property").status_code == 503
    _sharing(server)
    assert _pull(client, category="property").status_code == 200
    _sharing(server, on=False)
    assert _pull(client, category="property").status_code == 503


def test_partner_key_required(client, server, monkeypatch):
    _seed(server, 25)
    _sharing(server)
    assert client.get("/api/partner/demand", params={"category": "property"}).status_code == 401
    assert client.get("/api/partner/demand", params={"category": "property"},
                      headers={"X-Hymn-Partner-Key": "wrong"}).status_code == 401
    monkeypatch.delenv("HYMN_PARTNER_KEY")
    assert client.get("/api/partner/demand", params={"category": "property"},
                      headers={"X-Hymn-Partner-Key": ""}).status_code == 401


def test_every_pull_is_logged(client, server):
    _seed(server, 25)
    _sharing(server)
    _pull(client, category="property", city="Bengaluru")
    log = asyncio.run(server.db.partner_requests.find({}, {"_id": 0}).to_list(5))
    assert len(log) == 1 and log[0]["category"] == "property" and log[0]["people"] == 25


def test_owner_can_raise_but_not_drop_below_ten(client, server):
    _seed(server, 25)
    _sharing(server, min_count=30)
    assert _pull(client, category="property").json()["people"] is None
    boss = _person(client, BOSS, "Boss")
    assert client.put("/api/admin/settings", headers=boss["h"], json={"demand_min_count": 5}).status_code == 422
    assert client.put("/api/admin/settings", headers=boss["h"], json={"demand_min_count": 20}).status_code == 200


# ---------------------------------------------------------------------------
# The owner's view
# ---------------------------------------------------------------------------

def test_admin_sees_all_counts_and_a_preview(client, server):
    _seed(server, 12, prefix="yes")
    _seed(server, 30, consent=False, prefix="no")
    _seed(server, 3, category="car", form="SUV", prefix="car")
    boss = _person(client, BOSS, "Boss")
    a = _person(client, "asha@example.com")
    assert client.get("/api/admin/demand", headers=a["h"]).status_code == 403
    body = client.get("/api/admin/demand", headers=boss["h"], params={"category": "property"}).json()
    prop = next(c for c in body["categories"] if c["category"] == "property")
    assert prop["people"] == 42 and prop["shareable_people"] == 12
    car = next(c for c in body["categories"] if c["category"] == "car")
    assert car["people"] is None                     # fewer than 5: hidden even from the owner
    assert body["all_plans"]["people"] == 42 and body["for_sellers"]["people"] is None
    assert body["sharing_on"] is False and body["vendor_min"] == 20 and body["people_sharing"] == 15
    assert "Secret Name" not in str(body)
