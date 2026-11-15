"""Health: six domains, sources kept, no compensation, red flags first, consent."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

import health

TODAY = date.today()


@pytest.fixture()
def user(client):
    r = client.post("/api/auth/signup", json={"name": "H", "email": "health@example.com",
                                              "password": "correct-horse-battery", "security_question": "Q?",
                                              "security_answer": "A"})
    b = r.json()
    return {"id": b["user"]["id"], "headers": {"Authorization": f"Bearer {b['access_token']}"}}


PROFILE = {"consent": True, "date_of_birth": "1990-05-10", "sex": "male", "height_cm": 175,
           "family_history": ["diabetes"], "smoking": "current"}


def _m(metric, value, days_ago=0, source="you"):
    return {"metric": metric, "value": value, "taken_on": (TODAY - timedelta(days=days_ago)).isoformat(),
            "source": source}


def test_nothing_without_consent(client, user):
    h = user["headers"]
    assert client.post("/api/health/measurements", headers=h, json=[_m("weight_kg", 80)]).status_code == 403
    assert client.put("/api/health/profile", headers=h, json={**PROFILE, "consent": False}).status_code == 400
    assert client.get("/api/health/dashboard", headers=h).status_code == 403


def test_dashboard_sources_cutoffs_and_no_compensation(client, user):
    h = user["headers"]
    assert client.put("/api/health/profile", headers=h, json=PROFILE).status_code == 200
    r = client.post("/api/health/measurements", headers=h, json=[
        _m("bp_systolic", 132), _m("bp_diastolic", 85), _m("waist_cm", 92), _m("weight_kg", 74),
        _m("fasting_glucose", 130, 20, "lab"), _m("ldl", 120, 700, "lab"),
        *[_m("steps", 11000, d, "watch") for d in range(7)], *[_m("active_minutes", 45, d) for d in range(7)]])
    assert r.status_code == 201, r.text
    d = client.get("/api/health/dashboard", headers=h).json()
    assert "overall" not in d and d["rules_reviewed"] is False
    dom = {x["domain"]: x for x in d["domains"]}
    ind = lambda k, m: next(i for i in dom[k]["indicators"] if i["metric"] == m)
    assert ind("cardiovascular", "bp_systolic")["status"] == "amber"
    assert ind("cardiovascular", "smoking")["status"] == "red" and dom["cardiovascular"]["rating"] == 1
    assert ind("metabolic", "waist_cm")["status"] == "amber"                          # South Asian cut-off: 90 cm
    assert ind("metabolic", "bmi")["value"] == "24.2" and ind("metabolic", "bmi")["status"] == "amber"
    glucose = ind("metabolic", "fasting_glucose")
    assert (glucose["status"], glucose["source"]) == ("red", "lab")
    assert ind("metabolic", "ldl")["status"] == "outdated"                            # 700 days old: not "normal"
    assert dom["physical"]["colour"] == "green"                                       # great activity…
    assert dom["metabolic"]["colour"] == "red"                                        # …doesn't hide high glucose
    assert ind("physical", "steps")["based_on"] == "7-day average"
    assert ind("organ_recovery", "egfr")["status"] == "not_measured"                  # labs are optional…
    assert {"Fasting glucose", "Smoking"} <= {x["label"] for x in d["risks"]}
    assert not any(m["metric"] == "egfr" for m in d["missing"])                       # …and never nagged for
    assert any(m["metric"] == "resting_hr" for m in d["missing"])


def test_red_flags_come_first(client, user):
    h = user["headers"]
    client.put("/api/health/profile", headers=h, json=PROFILE)
    r = client.post("/api/health/daily", headers=h, json={
        "date": TODAY.isoformat(), "mood": 1, "symptoms": ["blood_in_stool", "self_harm_thoughts"]}).json()
    assert r["red_flags"][0]["level"] == "emergency_mental" and "14416" in r["red_flags"][0]["action"]
    assert r["red_flags"][1]["level"] == "doctor_soon"
    client.post("/api/health/measurements", headers=h, json=[_m("bp_systolic", 186), _m("bp_diastolic", 100)])
    flags = client.get("/api/health/dashboard", headers=h).json()["red_flags"]
    assert flags[0]["what"] == "Very high blood pressure"
    assert client.post("/api/health/daily", headers=h, json={"date": TODAY.isoformat(),
                                                             "symptoms": ["nonsense"]}).status_code == 400


def test_daily_log_is_one_entry_per_day_and_checks_values(client, user):
    h = user["headers"]
    client.put("/api/health/profile", headers=h, json=PROFILE)
    client.post("/api/health/daily", headers=h, json={"date": TODAY.isoformat(), "energy": 2, "bowel": 2})
    client.post("/api/health/daily", headers=h, json={"date": TODAY.isoformat(), "energy": 4})
    energy = client.get("/api/health/measurements?metric=energy", headers=h).json()
    assert [e["value"] for e in energy] == [4.0]
    assert client.post("/api/health/measurements", headers=h, json=[_m("bp_systolic", 400)]).status_code == 400


def test_screening_keeps_weight_loss_away_from_those_who_need_a_doctor(client, user):
    h = user["headers"]
    client.put("/api/health/profile", headers=h, json={**PROFILE, "pregnant_or_breastfeeding": True})
    s = client.get("/api/health/dashboard", headers=h).json()["screening"]
    assert s["weight_loss_ok"] is False and "Pregnant or breastfeeding" in s["see_doctor_first_because"]
    assert health.screening({"date_of_birth": "2012-01-01"}, {}, TODAY)["weight_loss_ok"] is False


def test_delete_everything(client, server, user):
    h = user["headers"]
    client.put("/api/health/profile", headers=h, json=PROFILE)
    client.post("/api/health/measurements", headers=h, json=[_m("weight_kg", 80)])
    assert client.delete("/api/health/all", headers=h).status_code == 200
    assert client.get("/api/health/profile", headers=h).json() == {"consent": False}
    import asyncio
    assert asyncio.run(server.db.health_measurements.count_documents({"user_id": user["id"]})) == 0


def test_health_plans_say_what_life_they_serve(client, user):
    h = user["headers"]
    dream = client.post("/api/life-plans", headers=h, json={
        "title": "Trek to Kedarkantha with my son", "target_date": "2027-12-01",
        "requirements": [{"area": "family", "what": "Son is free in December", "kind": "condition"}]}).json()
    quit_ = client.post("/api/life-plans", headers=h, json={
        "title": "Quit smoking", "target_date": "2027-03-01", "for_what": "Keep up with my son on the trek",
        "serves_plan_id": dream["id"],
        "requirements": [{"area": "health", "what": "Talk to a doctor about stop-smoking aids", "kind": "condition"}]})
    assert quit_.status_code == 201, quit_.text
    q = quit_.json()
    assert q["for_what"] == "Keep up with my son on the trek" and q["serves"]["title"] == dream["title"]
    bad = client.post("/api/life-plans", headers=h, json={
        "title": "X", "target_date": "2027-03-01", "serves_plan_id": "nope",
        "requirements": [{"area": "health", "what": "Y", "kind": "condition"}]})
    assert bad.status_code == 400


def test_suggestions_come_from_logs_never_labs(client, user):
    h = user["headers"]
    client.put("/api/health/profile", headers=h, json=PROFILE)
    first = client.get("/api/health/suggestions", headers=h).json()
    assert len(first) == 1 and "Log food and movement" in first[0]["action"]           # nothing logged yet
    client.post("/api/health/measurements", headers=h, json=[_m("fasting_glucose", 180, 1, "lab")])
    assert "Log food and movement" in client.get("/api/health/suggestions", headers=h).json()[0]["action"]
    for d in range(7):
        client.post("/api/health/daily", headers=h, json={
            "date": (TODAY - timedelta(days=d)).isoformat(), "active_minutes": 10, "sleep_hours": 6,
            "veg_fruit_portions": 2, "sugary_items": 3, "strength_session": 0})
    s = client.get("/api/health/suggestions", headers=h).json()
    assert len(s) == 3 and [x["what"] for x in s] == ["Move a little more", "Keep your muscles", "Protect your sleep"]
    assert all({"what", "why", "action", "measure", "review_in_days"} <= set(x) for x in s)
    assert not any("glucose" in (x["what"] + x["action"]).lower() for x in s)      # the lab value didn't drive it
