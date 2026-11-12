"""After conversion the ledger follows the old finance records (synthetic data)."""
from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from bson.decimal128 import Decimal128

import ledger
import ledger_sync
from test_ledger_conversion import _account, _event, _finance_balance, _preview


@pytest.fixture()
def user(client):
    r = client.post("/api/auth/signup", json={
        "name": "Sync", "email": "sync@example.com", "password": "correct-horse-battery",
        "security_question": "Q?", "security_answer": "A",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    return {"id": body["user"]["id"], "headers": {"Authorization": f"Bearer {body['access_token']}"}}


def _convert(client, user):
    report = _preview(client, user)
    r = client.post("/api/ledger/conversion/apply", headers=user["headers"], json={"fingerprint": report["fingerprint"]})
    assert r.status_code == 200, r.text


def _sync(server, user):
    return asyncio.run(ledger_sync.sync(server.db, user["id"]))


def _ledger_balance(client, user, acct_id):
    rows = client.get("/api/ledger/balances?as_of=2027-12-31", headers=user["headers"]).json()
    return Decimal(next(r for r in rows if r["account_id"] == acct_id)["balance"])


def _assert_agrees(client, user, server, *accounts):
    """The ledger equals the old records read by the conversion's rules
    (money held for banks, money owed for cards)."""
    report = _preview(client, user)
    expected = {r["account_id"]: Decimal(r["finance_balance_today"]) for r in report["accounts"]}
    for a in accounts:
        assert _ledger_balance(client, user, a) == expected[a], a
    assert _ledger_balance(client, user, "bank") == _finance_balance(server.db, user["id"], "bank")


@pytest.fixture()
def converted(client, server, user):
    db, uid = server.db, user["id"]
    _account(db, uid, "bank")
    _account(db, uid, "card", account_type="credit_card", value="3000")
    _event(db, uid, "500", "2026-10-30")
    _event(db, uid, "1000", "2026-11-05")
    _event(db, uid, "700", "2026-11-06", account_id="card")
    _convert(client, user)
    return db, uid


def test_nothing_to_do_right_after_conversion(client, server, user, converted):
    assert _sync(server, user) == {"converted": True, "created": 0, "voided": 0, "linked": 0}
    _assert_agrees(client, user, server, "bank", "card")


def test_users_who_never_converted_are_untouched(client, server, user):
    _account(server.db, user["id"], "bank")
    _event(server.db, user["id"], "100", "2026-11-05")
    assert _sync(server, user)["converted"] is False
    assert asyncio.run(server.db.ledger_transactions.count_documents({})) == 0


def test_new_spend_after_conversion_reaches_the_ledger_once(client, server, user, converted):
    db, uid = converted
    ev = _event(db, uid, "250", "2026-11-10", description="Lunch")
    _event(db, uid, "400", "2026-11-11", account_id="card")
    assert _sync(server, user)["created"] == 2
    assert _sync(server, user)["created"] == 0  # idempotent
    _assert_agrees(client, user, server, "bank", "card")
    spend = client.get("/api/ledger/spending?basis=accrual&start=2026-11-01&end=2026-11-30",
                       headers=user["headers"]).json()
    assert spend["by_currency"][0]["total"] == "2350.00"
    tx = asyncio.run(db.ledger_transactions.find_one({"evidence_ids": ev["id"]}))
    assert tx["provenance"] == "event" and tx["description"] == "Lunch"


def test_rejected_or_changed_events_follow(client, server, user, converted):
    db, uid = converted
    ev = _event(db, uid, "250", "2026-11-10")
    _sync(server, user)
    asyncio.run(db.financial_events.update_one({"id": ev["id"]}, {"$set": {"amount": Decimal128("300")}}))
    assert _sync(server, user)["voided"] == 1
    _assert_agrees(client, user, server, "bank")
    asyncio.run(db.financial_events.update_one({"id": ev["id"]}, {"$set": {"confirmation_status": "rejected"}}))
    _sync(server, user)
    _assert_agrees(client, user, server, "bank")
    posted = asyncio.run(db.ledger_transactions.count_documents({"evidence_ids": ev["id"], "status": "posted"}))
    assert posted == 0
    # Changed back: the same entry comes back, not a copy.
    asyncio.run(db.financial_events.update_one({"id": ev["id"]}, {"$set": {"confirmation_status": "confirmed"}}))
    _sync(server, user)
    _assert_agrees(client, user, server, "bank")
    assert asyncio.run(db.ledger_transactions.count_documents({"evidence_ids": ev["id"], "status": "posted"})) == 1


def test_retyped_account_balance_redoes_the_opening(client, server, user, converted):
    db, uid = converted
    asyncio.run(db.financial_accounts.update_one(
        {"id": "bank"}, {"$set": {"current_value": Decimal128("80000"), "balance_as_of": "2026-11-20T00:00:00+00:00"}}))
    _sync(server, user)
    _assert_agrees(client, user, server, "bank", "card")


def test_a_person_void_is_respected(client, server, user, converted):
    db, uid = converted
    ev = _event(db, uid, "250", "2026-11-10")
    _sync(server, user)
    tx = asyncio.run(db.ledger_transactions.find_one({"evidence_ids": ev["id"]}))
    assert client.post(f"/api/ledger/transactions/{tx['id']}/void", headers=user["headers"]).status_code == 200
    assert _sync(server, user)["created"] == 0
    # Even if the old record is edited later.
    asyncio.run(db.financial_events.update_one({"id": ev["id"]}, {"$set": {"amount": Decimal128("260")}}))
    assert _sync(server, user)["created"] == 0


def test_statement_entry_for_the_same_payment_is_not_counted_twice(client, server, user, converted):
    db, uid = converted
    stmt_tx = asyncio.run(ledger.record(db, uid, ledger.Draft(
        kind="expense", date="2026-11-12", currency="INR", amount="999", from_account_id="bank",
        category="expense:food"), provenance="user", evidence_ids=["stmt:s1:4"]))
    ev = _event(db, uid, "999", "2026-11-11", description="Dinner")  # recorded a day apart
    result = _sync(server, user)
    assert (result["created"], result["linked"]) == (0, 1)
    linked = asyncio.run(db.ledger_transactions.find_one({"id": stmt_tx["id"]}))
    assert ev["id"] in linked["evidence_ids"]
    # Rejecting the old record later doesn't remove what the statement proved.
    asyncio.run(db.financial_events.update_one({"id": ev["id"]}, {"$set": {"confirmation_status": "rejected"}}))
    _sync(server, user)
    assert asyncio.run(db.ledger_transactions.find_one({"id": stmt_tx["id"]}))["status"] == "posted"


def test_statement_opening_wins_over_typed_balance(client, server, user, converted):
    db, uid = converted
    asyncio.run(db.financial_accounts.insert_one({
        "id": "hdfc", "user_id": uid, "name": "HDFC", "account_type": "bank", "currency": "INR",
        "current_value": Decimal128("5000"), "balance_as_of": "2026-11-01T00:00:00+00:00", "liquidity_type": "liquid"}))
    asyncio.run(ledger.record(db, uid, ledger.Draft(
        kind="opening_balance", date="2026-10-01", currency="INR", amount="7000", account_id="hdfc"),
        provenance="document", evidence_ids=["stmt:s2:opening"]))
    _sync(server, user)
    assert _ledger_balance(client, user, "hdfc") == Decimal("7000")
