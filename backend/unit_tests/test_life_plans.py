"""Planning engine: must-go-right requirements benchmarked against now and T−1."""
from __future__ import annotations

import asyncio
from datetime import date, datetime

import pytest

import life_plans
from life_plans import free_slots


@pytest.fixture()
def user(client):
    r = client.post("/api/auth/signup", json={"name": "P", "email": "plan@example.com",
                                              "password": "correct-horse-battery", "security_question": "Q?",
                                              "security_answer": "A"})
    b = r.json()
    return {"id": b["user"]["id"], "headers": {"Authorization": f"Bearer {b['access_token']}"}}


SLEEP = {"day_of_week": "monday", "start_time": "23:00", "end_time": "07:00", "effective_from": "2026-01-01"}
WORK = {"day_of_week": "tuesday", "start_time": "09:00", "end_time": "20:00", "effective_from": "2026-01-01"}


def test_free_slots_respect_blocks_overnight_bookings_and_now():
    tue = date(2026, 11, 17)
    booked = [{"allocation_mode": "one_time", "date": "2026-11-17", "start_time": "20:30", "end_time": "21:00"}]
    slots = free_slots([tue], [SLEEP, WORK], booked, "06:00", "22:30", 45)
    # Monday-night sleep runs to 07:00, work 09–20, booked 20:30–21:00.
    assert slots == [{"date": "2026-11-17", "start": "07:00", "end": "09:00", "minutes": 120},
                     {"date": "2026-11-17", "start": "21:00", "end": "22:30", "minutes": 90}]
    later = free_slots([tue], [SLEEP, WORK], booked, "06:00", "22:30", 45, now=datetime(2026, 11, 17, 21, 0))
    assert later == [{"date": "2026-11-17", "start": "21:15", "end": "22:30", "minutes": 75}]
    assert free_slots([tue], [SLEEP, WORK], [], "18:00", "22:30", 45, weekdays=["wednesday"]) == []


def test_guitar_this_week_end_to_end(client, server, user, monkeypatch):
    monkeypatch.setattr(life_plans, "local_now", lambda u: datetime(2026, 11, 17, 8, 0))   # Tuesday 8am
    for d in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"):
        client.post("/api/portfolio/time-commitments", headers=user["headers"], json={
            "title": "Sleep", "day_of_week": d, "start_time": "23:00", "end_time": "07:00",
            "commitment_type": "sleep", "flexibility": "fixed", "effective_from": "2026-01-01"})
    r = client.post("/api/life-plans/quick-time", headers=user["headers"], json={
        "title": "Guitar", "minutes": 45, "earliest": "18:00", "latest": "22:00"})
    assert r.status_code == 201, r.text
    plan = r.json()
    req = plan["requirements"][0]
    assert plan["target_date"] == "2026-11-22" and plan["verdict"] == "fits_by_then"
    assert req["status"] == "by_then" and req["slots"][0] == {"date": "2026-11-17", "start": "18:00",
                                                             "end": "22:00", "minutes": 240}
    b = client.post(f"/api/life-plans/{plan['id']}/book", headers=user["headers"], json={
        "requirement_id": req["id"], "date": "2026-11-17", "start": "20:15", "minutes": 45})
    assert b.status_code == 201, b.text
    assert b.json()["verdict"] == "fits_now" and b.json()["requirements"][0]["available_now"] == 45
    clash = client.post(f"/api/life-plans/{plan['id']}/book", headers=user["headers"], json={
        "requirement_id": req["id"], "date": "2026-11-17", "start": "20:30", "minutes": 30})
    assert clash.status_code == 409
    # The booked time now counts as committed in the week's time statements.
    t = client.get("/api/reports/time?week_start=2026-11-17", headers=user["headers"]).json()
    assert t["commitments"]["flexible_and_set_aside_hours"] == "0.8"


def test_money_and_conditions_against_now_and_t_minus_1(client, server, user, monkeypatch):
    import finance_manager
    monkeypatch.setattr(finance_manager, "_today_iso", lambda: "2026-11-01")
    monkeypatch.setattr(life_plans, "local_now", lambda u: datetime(2026, 11, 1, 9, 0))
    asyncio.run(server.db.financial_accounts.insert_one({
        "id": "bank", "user_id": user["id"], "name": "Bank", "account_type": "bank", "currency": "INR",
        "current_value": "100000", "balance_as_of": "2026-10-31T00:00:00+00:00", "liquidity_type": "liquid"}))
    client.post("/api/planned-money", headers=user["headers"], json={
        "title": "Salary", "direction": "in", "purpose": "income", "amount": "100000", "currency": "INR",
        "repeat": "monthly", "start_month": "2026-01"})
    client.post("/api/planned-money", headers=user["headers"], json={
        "title": "Rent", "direction": "out", "purpose": "spend", "amount": "70000", "currency": "INR",
        "repeat": "monthly", "start_month": "2026-01"})
    body = {"title": "Goa trip", "target_date": "2027-03-15", "requirements": [
        {"area": "money", "what": "Trip fund", "kind": "money", "amount": "150000", "currency": "INR"},
        {"area": "money", "what": "Flights", "kind": "money", "amount": "30000", "currency": "INR"},
        {"area": "family", "what": "Partner can take leave", "kind": "condition"},
        {"area": "money", "what": "Villa deposit", "kind": "money", "amount": "900000", "currency": "INR"}],
        "risks": [{"area": "work", "what": "Leave not approved", "likelihood": "medium",
                   "early_warning": "No leave request by January", "mitigation": "Apply in December"}]}
    r = client.post("/api/life-plans", headers=user["headers"], json=body)
    assert r.status_code == 201, r.text
    reqs = {q["what"]: q for q in r.json()["requirements"]}
    assert reqs["Flights"]["status"] == "now"                                   # ₹1L today covers ₹30k
    assert reqs["Trip fund"]["status"] == "by_then"                             # +₹30k a month Nov–Feb
    assert reqs["Trip fund"]["built_up_by_then"] == "220000.00"
    assert reqs["Villa deposit"]["status"] == "short" and reqs["Villa deposit"]["gap"] == "680000.00"
    assert reqs["Partner can take leave"]["status"] == "unknown"
    assert r.json()["verdict"] == "doesnt_fit" and r.json()["risks"][0]["early_warning"]
    cond = reqs["Partner can take leave"]["id"]
    a = client.post(f"/api/life-plans/{r.json()['id']}/requirements/{cond}/answer", headers=user["headers"],
                    json={"answer": "yes"}).json()
    assert next(q for q in a["requirements"] if q["id"] == cond)["status"] == "now"
    bad = client.post("/api/life-plans", headers=user["headers"], json={**body, "requirements": [
        {"area": "money", "what": "X", "kind": "money", "amount": "10", "needed_by": "2027-12-01"}]})
    assert bad.status_code == 400
