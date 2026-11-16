"""Work: roles and their time, overtime, leave, wins and appraisals, payslips."""
from __future__ import annotations

import asyncio
import base64
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

import ledger
import nudges
import payslip_ai
import plan_assistant
import work
from payslip_ai import Line, Payslip
from test_ledger_conversion import _account
from test_ledger_sync import _convert

TODAY = date.today()
MONDAY = TODAY - timedelta(days=TODAY.weekday())


def _iso(d):
    return d.isoformat()


@pytest.fixture()
def user(client, server):
    b = client.post("/api/auth/signup", json={"name": "Ravi", "email": "work@example.com",
                                              "password": "correct-horse-battery", "security_question": "Q?",
                                              "security_answer": "A"}).json()
    asyncio.run(server.db.users.update_one({"id": b["user"]["id"]}, {"$set": {"plan": "premium"}}))
    return {"id": b["user"]["id"], "headers": {"Authorization": f"Bearer {b['access_token']}"}}


def _job(client, user, **extra):
    body = {"type": "salaried", "organisation": "Acme", "title": "Analyst", "started_on": "2024-01-01",
            "start_time": "09:30", "end_time": "18:30", "commute_minutes": 45,
            "leave_types": [{"key": "earned", "label": "Earned", "per_year": 18, "carried_forward": 6,
                             "carry_forward_max": 10, "year_starts": "01-01"},
                            {"key": "casual", "per_year": 8}], **extra}
    r = client.post("/api/work/roles", headers=user["headers"], json=body)
    assert r.status_code == 201, r.text
    return r.json()


# --- Roles and time ------------------------------------------------------------------

def test_a_job_becomes_time_blocks_and_ending_it_frees_them(client, server, user):
    role = _job(client, user)
    assert (role["planned_hours_per_week"], role["commute_hours_per_week"]) == (45.0, 7.5)
    assert role["features"] == {"leave": True, "appraisal": True, "payslips": True, "wins": True, "time": True}
    blocks = asyncio.run(server.db.time_commitments.find({"source_id": role["id"]}, {"_id": 0}).to_list(None))
    work_b = [b for b in blocks if b["commitment_type"] == "work"]
    commute = sorted((b["start_time"], b["end_time"]) for b in blocks if b["day_of_week"] == "monday"
                     and b["commitment_type"] == "commute")
    assert len(work_b) == 5 and commute == [("08:45", "09:30"), ("18:30", "19:15")]
    t = client.get(f"/api/reports/time?week_start={_iso(MONDAY)}", headers=user["headers"]).json()
    areas = {a["area"]: a for a in t["spent"]["areas"]}
    assert areas["work"]["planned_hours"] == "45.0" and areas["commute"]["planned_hours"] == "7.5"
    # Working from home on Fridays: no commute that day.
    client.patch(f"/api/work/roles/{role['id']}", headers=user["headers"],
                 json={"office_days": ["monday", "tuesday", "wednesday", "thursday"]})
    assert asyncio.run(server.db.time_commitments.count_documents({"source_id": role["id"],
                                                                    "commitment_type": "commute"})) == 8
    client.patch(f"/api/work/roles/{role['id']}", headers=user["headers"], json={"ended_on": _iso(TODAY)})
    assert asyncio.run(server.db.time_commitments.count_documents({"source_id": role["id"]})) == 0
    assert client.post("/api/work/roles", headers=user["headers"], json={
        "type": "salaried", "start_time": "09:00"}).status_code == 400              # half a schedule


def test_parts_switch_on_by_type(client, user):
    free = client.post("/api/work/roles", headers=user["headers"], json={"type": "freelancer", "title": "Designer"}).json()
    assert free["features"]["leave"] is False and free["features"]["payslips"] is False and "leave" not in free
    assert client.post("/api/work/roles", headers=user["headers"], json={
        "type": "business_owner", "leave_types": [{"key": "earned", "per_year": 10}]}).status_code == 400
    assert client.post("/api/work/leave", headers=user["headers"], json={
        "role_id": free["id"], "type": "earned", "from": _iso(TODAY), "to": _iso(TODAY)}).status_code == 400


def test_overtime_shows_up_and_the_week_says_so(client, user):
    role = _job(client, user)
    h = user["headers"]
    for d, extra in ((0, 120), (1, 60), (2, 90)):
        client.post("/api/work/days", headers=h, json={"role_id": role["id"], "date": _iso(MONDAY + timedelta(days=d)),
                                                       "extra_minutes": extra})
    client.post("/api/work/days", headers=h, json={"role_id": role["id"], "date": _iso(MONDAY), "extra_minutes": 180})
    t = client.get(f"/api/reports/time?week_start={_iso(MONDAY)}", headers=h).json()
    wk = next(a for a in t["spent"]["areas"] if a["area"] == "work")
    assert wk["actual_hours"] == "50.5"                                           # 45 + 3 + 1 + 1.5 (Monday replaced)
    w = client.get(f"/api/work/week?week_start={_iso(MONDAY)}", headers=h).json()
    assert (w["over_plan_hours"], w["in_its_box"]) == (5.5, False)
    assert w["summary"].startswith("Work ran 5.5 hours over plan")
    client.post("/api/work/days", headers=h, json={"role_id": role["id"], "date": _iso(MONDAY), "extra_minutes": 0})
    for d in (1, 2):
        client.post("/api/work/days", headers=h, json={"role_id": role["id"], "date": _iso(MONDAY + timedelta(days=d)),
                                                       "extra_minutes": 30})
    assert client.get(f"/api/work/week?week_start={_iso(MONDAY)}", headers=h).json()["in_its_box"] is True


# --- Leave ---------------------------------------------------------------------------------

def test_leave_balances_expiry_and_the_planner(client, server, user):
    h = user["headers"]
    role = _job(client, user)
    next_mon = MONDAY + timedelta(days=7)
    r = client.post("/api/work/leave", headers=h, json={"role_id": role["id"], "type": "earned",
                                                        "from": _iso(next_mon), "to": _iso(next_mon + timedelta(days=6))})
    assert r.json()["days"] == 5                                                   # weekends don't count
    client.post("/api/work/leave", headers=h, json={"role_id": role["id"], "type": "casual", "from": _iso(next_mon),
                                                    "to": _iso(next_mon), "half_day": True})
    roles = client.get(f"/api/work/roles/{role['id']}", headers=h).json()
    earned = next(b for b in roles["leave"] if b["type"] == "earned")
    if next_mon.year == TODAY.year:
        assert (earned["planned"], earned["left"], earned["expiring"]) == (5, 19, 9)   # 18 + 6 − 5; over the cap of 10
    big = client.post("/api/work/leave", headers=h, json={"role_id": role["id"], "type": "casual",
                                                          "from": _iso(next_mon), "to": _iso(next_mon), "days": 30})
    assert big.json()["warning"]
    client.delete(f"/api/work/leave/{big.json()['id']}", headers=h)
    out = asyncio.run(plan_assistant.run_tool(server.db, {"id": user["id"]}, {"id": "c"}, "check_leave", {"days": 10}))
    assert out["fits"] is True and {b["label"] for b in out["leave"]} == {"Earned", "Casual"}
    facts = {f["key"]: f for f in asyncio.run(plan_assistant.get_context(server.db, {"id": user["id"]}))["facts"]}
    assert "Analyst at Acme" in facts["work"]["value"] and "earned" in facts["leave_left"]["value"]


def test_leave_year_and_days_are_counted_right():
    assert work.leave_year("04-01", date(2026, 3, 31)) == (date(2025, 4, 1), date(2026, 3, 31))
    assert work.leave_year("04-01", date(2026, 4, 1)) == (date(2026, 4, 1), date(2027, 3, 31))
    days = ["monday", "tuesday", "wednesday", "thursday", "friday"]
    assert work.leave_days(date(2026, 11, 13), date(2026, 11, 16), days) == 2.0      # Fri + Mon
    assert work.leave_days(date(2026, 11, 13), date(2026, 11, 13), days, half_day=True) == 0.5


# --- Wins and appraisals ----------------------------------------------------------------------

def test_wins_feed_the_appraisal_pack(client, server, user):
    h = user["headers"]
    role = _job(client, user, next_appraisal=_iso(TODAY + timedelta(days=60)))
    client.post("/api/work/wins", headers=h, json={"role_id": role["id"], "date": _iso(TODAY - timedelta(days=40)),
                                                   "text": "Closed the Q2 audit two weeks early"})
    client.post("/api/work/wins", headers=h, json={"role_id": role["id"], "date": _iso(TODAY), "text": "Trained 3 juniors"})
    asyncio.run(server.db.learning_sessions.insert_one({"user_id": user["id"], "title": "CA", "minutes": 90,
                                                        "date": _iso(TODAY)}))
    pack = client.get(f"/api/work/roles/{role['id']}/appraisal-pack", headers=h).json()
    assert pack["wins"] == 2 and pack["learning"] == [{"journey": "CA", "hours": 1.5}]
    assert sum(len(m["wins"]) for m in pack["wins_by_month"]) == 2


# --- Payslips ---------------------------------------------------------------------------------

def test_deductions_are_sorted_by_their_label():
    kinds = {l: work.deduction_kind(l) for l in ("Employee PF", "E.P.F.", "Provident Fund", "VPF", "P.Tax",
                                                 "Professional Tax", "Prof. Tax", "TDS", "Income Tax", "IT",
                                                 "Group Mediclaim", "Health insurance premium", "Canteen",
                                                 "Loan recovery", "Profit share")}
    assert [l for l, k in kinds.items() if k == "pf"] == ["Employee PF", "E.P.F.", "Provident Fund", "VPF"]
    assert [l for l, k in kinds.items() if k == "professional_tax"] == ["P.Tax", "Professional Tax", "Prof. Tax"]
    assert [l for l, k in kinds.items() if k == "income_tax"] == ["TDS", "Income Tax", "IT"]
    assert [l for l, k in kinds.items() if k == "health_insurance"] == ["Group Mediclaim", "Health insurance premium"]
    assert [l for l, k in kinds.items() if k == "other"] == ["Canteen", "Loan recovery", "Profit share"]


SLIP = {"month": "2026-10", "gross": "100000", "net": "79800", "employer_pf": "1800",
        "earnings": [{"label": "Basic", "amount": "50000"}, {"label": "HRA", "amount": "20000"},
                     {"label": "Special allowance", "amount": "30000"}],
        "deductions": [{"label": "Employee PF", "amount": "1800"}, {"label": "TDS", "amount": "16000"},
                       {"label": "Professional Tax", "amount": "200"}, {"label": "Group Mediclaim", "amount": "500"},
                       {"label": "Canteen", "amount": "1700"}]}


def test_reading_a_payslip_checks_the_sums(client, user, monkeypatch):
    async def fake(data, media_type):
        return Payslip(is_payslip=True, month="2026-10", employer="Acme", gross="100000", net="80000",
                       employer_pf="1800", earnings=[Line(**e) for e in SLIP["earnings"]],
                       deductions=[Line(**d) for d in SLIP["deductions"]])
    monkeypatch.setattr(payslip_ai, "read_payslip", fake)
    img = base64.b64encode(b"\x89PNG fake").decode()
    r = client.post("/api/work/payslips/read", headers=user["headers"], json={"file_base64": img,
                                                                              "media_type": "image/png"}).json()
    assert r["problems"] == ["Gross 100000 minus deductions 20200 is 79800, but take-home is 80000."]
    assert {d["label"]: d["kind"] for d in r["deductions"]}["TDS"] == "income_tax"
    free = client.post("/api/auth/signup", json={"name": "F", "email": "fw@example.com",
                                                 "password": "correct-horse-battery", "security_question": "Q?",
                                                 "security_answer": "A"}).json()
    assert client.post("/api/work/payslips/read", headers={"Authorization": f"Bearer {free['access_token']}"},
                       json={"file_base64": img, "media_type": "image/png"}).status_code == 403


def test_payslip_on_the_money_book_shows_gross_without_double_counting(client, server, user):
    db, uid, h = server.db, user["id"], user["headers"]
    _account(db, uid, "bank", account_type="bank", value="50000")
    _account(db, uid, "epf", account_type="epf", value="200000")
    _convert(client, user)
    role = _job(client, user)
    bad = client.post("/api/work/payslips", headers=h, json={**SLIP, "role_id": role["id"], "net": "80000"})
    assert bad.status_code == 400 and bad.json()["detail"]["problems"]
    r = client.post("/api/work/payslips", headers=h, json={**SLIP, "role_id": role["id"], "pf_account_id": "epf"})
    assert r.status_code == 201, r.text
    assert sorted(r.json()["recorded_in_money_book"]) == ["health_insurance", "income_tax", "other", "pf",
                                                          "professional_tax"]
    # Take-home arrives through the bank as usual (here: typed as income).
    asyncio.run(ledger.record(db, uid, ledger.Draft(kind="income", date="2026-10-31", currency="INR", amount="79800",
                                                    to_account_id="bank", category="income:salary",
                                                    description="Salary"), provenance="statement"))
    epf = next(b for b in asyncio.run(ledger.balances(db, uid, "2026-12-31")) if b["account_id"] == "epf")
    assert Decimal(epf["balance"]) == 203600                                       # 2,00,000 + 1,800 + 1,800
    ie = client.get("/api/reports/income-expenditure?month=2026-10", headers=h).json()[0]["this_month"]
    assert ie["total_income"] == "101800.00"                                        # gross + employer PF
    assert Decimal(ie["total_expenditure"]) == 18400                                # TDS + PT + mediclaim + canteen
    cf = client.get("/api/reports/cash-flow?start=2026-10-01&end=2026-10-31", headers=h).json()[0]
    assert cf["net_change"] == "79800.00"                                           # only take-home moved cash
    assert client.post("/api/work/payslips", headers=h, json={**SLIP, "role_id": role["id"]}).status_code == 409


def test_payslip_before_the_money_book_is_just_kept(client, server, user):
    role = _job(client, user)
    r = client.post("/api/work/payslips", headers=user["headers"], json={**SLIP, "role_id": role["id"]}).json()
    assert r["recorded_in_money_book"] == [] and r["totals"]["pf"] == "1800"
    assert asyncio.run(server.db.ledger_transactions.count_documents({"user_id": user["id"]})) == 0
    asyncio.run(server.db.payslips.update_one({"id": r["id"]}, {"$set": {"net": "80000"}}))
    assert asyncio.run(work.take_home(server.db, user["id"])) == 80000


def test_salary_deduction_entries_balance():
    postings = ledger.build_postings(ledger.Draft(kind="salary_deduction", date="2026-10-31", currency="INR",
                                                  amount="16000", category="expense:income_tax"), {})
    assert sum(p["amount"] for p in postings) == 0
    assert {p["account_id"] for p in postings} == {"expense:income_tax", "income:salary_withheld"}


# --- Nudges --------------------------------------------------------------------------------------

def test_appraisal_leave_and_friday_nudges(client, server, user):
    db, h = server.db, user["headers"]
    asyncio.run(nudges.ensure_nudge_indexes(db))
    asyncio.run(db.users.update_one({"id": user["id"]}, {"$set": {"timezone": "Asia/Kolkata"}}))
    k = ZoneInfo("Asia/Kolkata")
    local_today = datetime.now(k).date()
    friday = local_today + timedelta(days=(4 - local_today.weekday()) % 7)
    role = _job(client, user, next_appraisal=_iso(friday + timedelta(days=21)),
                leave_types=[{"key": "earned", "label": "Earned", "per_year": 18, "carried_forward": 6,
                              "carry_forward_max": 10, "year_starts": _iso(friday + timedelta(days=31))[5:]}])
    client.post("/api/work/wins", headers=h, json={"role_id": role["id"], "date": _iso(local_today), "text": "Shipped"})
    for d in range(4):
        client.post("/api/work/days", headers=h, json={"role_id": role["id"],
                                                       "date": _iso(friday - timedelta(days=d)), "extra_minutes": 60})
    at = datetime(friday.year, friday.month, friday.day, 18, 35, tzinfo=k).astimezone(timezone.utc)
    got = {n["kind"]: n for n in asyncio.run(nudges.run_due_nudges(db, at)) if n["kind"].startswith("work")}
    assert set(got) == {"work_appraisal", "work_leave", "work_week"}
    assert "1 win" in got["work_appraisal"]["body"] and got["work_leave"]["title"].startswith("14 earned days expire")
    assert got["work_week"]["title"] == "Work ran 4.0 hours over this week"
    assert [n for n in asyncio.run(nudges.run_due_nudges(db, at + timedelta(minutes=10)))
            if n["kind"].startswith("work")] == []
