"""The three money statements (synthetic data)."""
from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

import ledger


@pytest.fixture()
def user(client):
    r = client.post("/api/auth/signup", json={"name": "Ravi", "email": "ravi@example.com",
                                              "password": "correct-horse-battery", "security_question": "Q?",
                                              "security_answer": "A"})
    body = r.json()
    return {"id": body["user"]["id"], "headers": {"Authorization": f"Bearer {body['access_token']}"}}


def _acct(db, uid, aid, t):
    asyncio.run(db.financial_accounts.insert_one({"id": aid, "user_id": uid, "name": aid.upper(), "account_type": t,
                                                  "currency": "INR", "current_value": "0"}))


def _rec(db, uid, **kw):
    return asyncio.run(ledger.record(db, uid, ledger.Draft(currency="INR", **kw), provenance="user"))


@pytest.fixture()
def ravi(server, user):
    db, uid = server.db, user["id"]
    for aid, t in (("bank", "bank"), ("card", "credit_card"), ("epf", "epf"), ("mf", "mutual_fund"),
                   ("deposit", "deposit_given"), ("loan", "personal_loan")):
        _acct(db, uid, aid, t)
    _rec(db, uid, kind="opening_balance", date="2026-03-31", amount="100000", account_id="bank")
    _rec(db, uid, kind="opening_balance", date="2026-03-31", amount="300000", account_id="epf")
    _rec(db, uid, kind="income", date="2026-04-30", amount="100000", to_account_id="bank", category="income:salary")
    _rec(db, uid, kind="expense", date="2026-05-02", amount="5000", from_account_id="card", category="expense:groceries")
    _rec(db, uid, kind="card_settlement", date="2026-05-20", amount="5000", from_account_id="bank", to_account_id="card")
    _rec(db, uid, kind="investment", date="2026-05-05", amount="10000", from_account_id="bank", to_account_id="mf")
    _rec(db, uid, kind="expense", date="2026-05-07", amount="25000", from_account_id="bank", category="expense:rent")
    _rec(db, uid, kind="opening_balance", date="2026-05-01", amount="100000", account_id="deposit")
    _rec(db, uid, kind="borrowing", date="2026-05-10", amount="50000", from_account_id="loan", to_account_id="bank")
    _rec(db, uid, kind="loan_payment", date="2026-05-25", from_account_id="bank", to_account_id="loan",
         principal="4000", interest="1000")
    asyncio.run(db.life_objects.insert_one({
        "id": "car", "user_id": uid, "type": "asset", "kind": "car", "name": "Swift", "currency": "INR",
        "started_on": "2026-05-01", "purchase_price": "600000", "expected_life_months": 60, "residual_value": "0"}))
    return db, uid


def test_statement_of_net_worth_balances_and_explains_itself(client, user, ravi):
    nw = client.get("/api/reports/net-worth?as_of=2026-05-31", headers=user["headers"]).json()[0]
    left, right = nw["left"], nw["right"]
    assert left["total"] == right["total"]                                    # both sides agree
    n = left["net_worth"]
    assert Decimal(n["opening"]) == Decimal("400000")                          # bank + EPF on 31 Mar
    assert Decimal(n["opening"]) + Decimal(n["surplus_this_year"]) + Decimal(n["other_changes"]) == Decimal(n["total"])
    groups = {g["group"]: g for g in right["assets"]}
    assert set(groups) == {"fixed", "investments", "retirement", "deposits", "cash"}
    assert groups["fixed"]["lines"][0]["name"] == "Swift"
    assert Decimal(groups["fixed"]["amount"]) < Decimal("600000")              # car has lost value
    assert {g["group"] for g in left["liabilities"]} == {"loans"}                # card fully paid
    assert left["liabilities"][0]["amount"] == "46000.00"


def test_income_and_expenditure_is_vertical_and_drillable(client, user, ravi):
    ie = client.get("/api/reports/income-expenditure?month=2026-05", headers=user["headers"]).json()[0]
    may = ie["this_month"]
    groups = {g["group"]: g for g in may["expenditure"]}
    assert groups["food"]["categories"] == [{"category": "expense:groceries", "label": "Groceries", "amount": "5000.00"}]
    assert groups["home"]["amount"] == "25000.00"
    assert groups["finance_costs"]["amount"] == "1000.00"                     # loan interest, not principal
    assert any(c["label"] == "Car value loss" for c in groups["transport"]["categories"])
    assert "investments" not in groups and may["total_income"] == "0.00"      # SIP and card bill aren't spending
    ytd = ie["year_to_date"]
    assert ytd["total_income"] == "100000.00" and ytd["savings_rate_percent"] is not None
    rows = client.get("/api/reports/entries?category=expense:groceries&start=2026-05-01&end=2026-05-31",
                      headers=user["headers"]).json()
    assert [r["amount"] for r in rows] == ["5000.00"]


def test_cash_flow_adds_up(client, user, ravi):
    cf = client.get("/api/reports/cash-flow?start=2026-04-01&end=2026-05-31", headers=user["headers"]).json()[0]
    assert cf["adds_up"] is True
    assert (cf["opening_cash"], cf["closing_cash"]) == ("100000.00", "205000.00")
    lines = {l["key"]: l["amount"] for s in cf["sections"] for l in s["lines"]}
    assert lines == {"living:income": "100000.00", "living:spent": "-26000.00", "living:card_bills": "-5000.00",
                     "investing:bought": "-10000.00", "borrowing:received": "50000.00",
                     "borrowing:repaid": "-4000.00"}
