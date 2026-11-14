"""Loans: EMI schedules and splitting EMIs into principal and interest."""
from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import pytest

from life_objects import loan_schedule


def test_reducing_balance_schedule():
    rows = loan_schedule({"loan_principal": "500000", "annual_rate_percent": "9", "tenure_months": 60,
                          "first_emi_date": "2026-01-05", "method": "reducing"})
    assert len(rows) == 60 and rows[0]["emi"] == "10379.18"
    assert rows[0]["interest"] == "3750.00" and rows[0]["principal"] == "6629.18"   # 9%/12 of 5L
    assert sum(Decimal(r["principal"]) for r in rows) == Decimal("500000.00")
    assert rows[-1]["owed_after"] == "0.00" and rows[1]["date"] == "2026-02-05"
    assert Decimal(rows[30]["interest"]) < Decimal(rows[0]["interest"])               # interest falls over time


def test_flat_and_document_emi():
    flat = loan_schedule({"loan_principal": "100000", "annual_rate_percent": "12", "tenure_months": 12,
                          "first_emi_date": "2026-01-31", "method": "flat"})
    assert (flat[0]["emi"], flat[0]["interest"]) == ("9333.33", "1000.00")
    assert flat[1]["date"] == "2026-02-28"                                            # month-end handled
    assert sum(Decimal(r["principal"]) for r in flat) == Decimal("100000.00")
    doc = loan_schedule({"loan_principal": "500000", "annual_rate_percent": "9", "tenure_months": 60,
                         "first_emi_date": "2026-01-05", "emi": "10400"})
    assert doc[0]["emi"] == "10400.00" and doc[-1]["owed_after"] == "0.00"
    assert loan_schedule({"loan_principal": "1000"}) == []


@pytest.fixture()
def premium_user(client, monkeypatch):
    monkeypatch.setenv("HYMN_PREMIUM_EMAILS", "loan@example.com")
    r = client.post("/api/auth/signup", json={"name": "L", "email": "loan@example.com",
                                              "password": "correct-horse-battery", "security_question": "Q?",
                                              "security_answer": "A"})
    body = r.json()
    return {"id": body["user"]["id"], "headers": {"Authorization": f"Bearer {body['access_token']}"}}


def test_statement_emi_is_split_and_recorded(client, server, premium_user):
    db, uid, h = server.db, premium_user["id"], premium_user["headers"]
    asyncio.run(db.financial_accounts.insert_many([
        {"id": "bank", "user_id": uid, "name": "HDFC", "account_type": "bank", "currency": "INR"},
        {"id": "carloan", "user_id": uid, "name": "Car loan", "account_type": "vehicle_loan", "currency": "INR"}]))
    r = client.post("/api/life-objects", headers=h, json={
        "type": "liability", "kind": "loan", "name": "Car loan", "started_on": "2025-12-20", "account_id": "carloan",
        "loan_principal": "500000", "annual_rate_percent": "9", "tenure_months": 60, "first_emi_date": "2026-01-05"})
    assert r.status_code == 201, r.text
    sched = client.get(f"/api/life-objects/{r.json()['id']}/schedule", headers=h).json()
    assert sched["emi"] == "10379.18" and Decimal(sched["total_interest"]) > 0
    sid = str(uuid.uuid4())
    asyncio.run(db.statement_imports.insert_one({
        "id": sid, "user_id": uid, "file_id": "f", "filename": "s.pdf", "status": "ready", "account_id": "bank",
        "lines": [{"n": 1, "date": "2026-02-05", "description": "ACH D- HDFC BANK LTD LOAN EMI", "reference": "",
                   "debit": "10379.18", "credit": "", "balance": ""}],
        "metadata": {"institution": "HDFC", "account_kind": "bank", "account_last4": "", "currency": "INR",
                     "period_start": "2026-02-01", "period_end": "2026-02-28", "opening_balance": "",
                     "closing_balance": ""}}))
    line = client.get(f"/api/statements/{sid}/suggestions", headers=h).json()["lines"][0]
    assert (line["kind"], line["confidence"], line["counter_account_id"]) == ("loan_payment", "loan", "carloan")
    assert (line["principal"], line["interest"]) == ("6678.90", "3700.28")             # EMI 2's split
    assert line["why"].startswith("EMI 2 of 60 for Car loan")
    r = client.post(f"/api/statements/{sid}/confirm", headers=h, json={"decisions": [
        {"n": 1, "action": "create", "kind": "loan_payment", "counter_account_id": "carloan",
         "principal": line["principal"]}]})
    assert r.status_code == 200, r.text
    tx = asyncio.run(db.ledger_transactions.find_one({"user_id": uid, "kind": "loan_payment"}))
    postings = {p["account_id"]: str(p["amount"]) for p in tx["postings"]}
    assert postings["expense:interest"] == "3700.28" and postings["carloan"] == "6678.90"
    assert asyncio.run(db.match_rules.count_documents({"user_id": uid})) == 0          # EMIs aren't learned as rules
