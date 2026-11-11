"""Conversion of existing finance data into the ledger (synthetic data only)."""
from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import pytest
from bson.decimal128 import Decimal128

import money_service


@pytest.fixture()
def user(client):
    r = client.post("/api/auth/signup", json={
        "name": "Convert", "email": "convert@example.com", "password": "correct-horse-battery",
        "security_question": "Q?", "security_answer": "A",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    return {"id": body["user"]["id"], "headers": {"Authorization": f"Bearer {body['access_token']}"}}


def _account(db, uid, acct_id, account_type="bank", value="100000", as_of="2026-11-01T00:00:00+00:00",
             currency="INR"):
    asyncio.run(db.financial_accounts.insert_one({
        "id": acct_id, "user_id": uid, "name": acct_id.title(), "account_type": account_type,
        "currency": currency, "current_value": Decimal128(value), "balance_as_of": as_of,
        "liquidity_type": "liquid",
    }))


def _event(db, uid, amount, day, direction="outflow", account_id="bank", **kw):
    ev = {
        "id": str(uuid.uuid4()), "user_id": uid, "amount": Decimal128(amount), "currency": "INR",
        "direction": direction, "event_date": day, "description": kw.pop("description", "thing"),
        "source": "manual", "confirmation_status": "confirmed",
        "lifecycle_status": "awaiting_reconciliation", "account_id": account_id,
        "occurred_at": None, "occurred_at_precision": "date_only", "created_at": day,
    }
    ev.update(kw)
    asyncio.run(db.financial_events.insert_one(ev))
    return ev


def _preview(client, user):
    r = client.get("/api/ledger/conversion/preview", headers=user["headers"])
    assert r.status_code == 200, r.text
    return r.json()


def _finance_balance(db, uid, acct_id):
    rows = asyncio.run(money_service.load_account_positions(db, uid))
    row = next(r for r in rows if r["account_id"] == acct_id)
    return Decimal(row["effective_current_balance"])


@pytest.fixture()
def history(server, user):
    db, uid = server.db, user["id"]
    _account(db, uid, "bank")
    _event(db, uid, "500", "2026-10-30")                          # before the snapshot
    _event(db, uid, "200", "2026-11-01")                          # same day: ambiguous, in snapshot
    _event(db, uid, "1000", "2026-11-05")                         # after
    _event(db, uid, "50000", "2026-11-07", direction="inflow",
           occurred_at="2026-11-07T09:00:00+00:00", occurred_at_precision="exact")
    return db, uid


def test_preview_matches_finance_and_keeps_history(client, user, history):
    db, uid = history
    report = _preview(client, user)
    bank = report["accounts"][0]
    assert bank["opening_balance"] == "100700"       # snapshot + the 700 already spent in it
    assert bank["opening_date"] == "2026-10-30"
    assert (bank["events_converted"], bank["events_in_snapshot"]) == (4, 2)
    assert Decimal(bank["ledger_balance_today"]) == _finance_balance(db, uid, "bank") == Decimal("149000")
    assert report["verification"]["balances_match"] is True
    assert report["verification"]["spending_matches"] is True
    assert {(m["month"], m["ledger"]) for m in report["verification"]["monthly_spending"]} == {
        ("2026-10", "500"), ("2026-11", "1200"),
    }
    assert report["transactions_to_create"] == 5
    assert report["summary"][1] == "✓ Every account balance matches Finance today."


def test_preview_writes_nothing(client, user, history):
    db, uid = history
    _preview(client, user)
    assert asyncio.run(db.ledger_transactions.count_documents({})) == 0


def test_card_debt_becomes_an_opening_amount_owed(client, user, server):
    _account(server.db, user["id"], "card", account_type="credit_card", value="20000")
    report = _preview(client, user)
    card = report["accounts"][0]
    assert (card["opening_balance"], card["ledger_balance_today"]) == ("20000", "20000")


def test_entries_that_dont_count_today_are_listed_not_moved(client, user, server):
    db, uid = server.db, user["id"]
    _account(db, uid, "bank")
    _event(db, uid, "10", "2026-11-05", lifecycle_status="pending_account_assignment", account_id=None,
           confirmation_status="pending")
    _event(db, uid, "20", "2026-11-05", lifecycle_status="pending_deduplication", confirmation_status="pending")
    _event(db, uid, "30", "2026-11-05", lifecycle_status="void")
    _event(db, uid, "40", "2026-11-05", confirmation_status="rejected")
    _event(db, uid, "50", "2026-11-05", currency="USD")
    _event(db, uid, "0", "2026-11-05")
    asyncio.run(db.checkins.insert_one({"id": "old", "user_id": uid, "money_spent": Decimal128("75"),
                                        "money_currency": "INR"}))
    report = _preview(client, user)
    assert {k: v["count"] for k, v in report["skipped"].items()} == {
        "needs_account": 1, "needs_review": 1, "void": 1, "rejected": 1,
        "currency_mismatch": 1, "zero_amount": 1,
    }
    assert report["orphan_checkin_spends"] == {"count": 1, "totals": {"INR": "75"}}
    assert report["transactions_to_create"] == 1  # the opening balance only
    assert report["verification"]["balances_match"] is True


def test_apply_needs_the_previewed_fingerprint(client, user, history):
    r = client.post("/api/ledger/conversion/apply", headers=user["headers"], json={"fingerprint": "nope"})
    assert r.status_code == 409


def test_apply_writes_what_the_preview_showed_once(client, user, history):
    db, uid = history
    report = _preview(client, user)
    r = client.post("/api/ledger/conversion/apply", headers=user["headers"],
                    json={"fingerprint": report["fingerprint"]})
    assert r.status_code == 200, r.text
    assert r.json()["created"] == r.json()["entries_created"] == 5

    balances = client.get("/api/ledger/balances?as_of=2026-12-31", headers=user["headers"]).json()
    assert balances[0]["balance"] == "149000.00"
    spending = client.get("/api/ledger/spending?basis=accrual&start=2026-11-01&end=2026-11-30",
                          headers=user["headers"]).json()
    assert spending["by_currency"][0]["total"] == "1200.00"

    txs = client.get("/api/ledger/transactions", headers=user["headers"]).json()
    converted = [t for t in txs if t["evidence_ids"]]
    assert len(converted) == 4
    assert all(t["provenance"] == "conversion" and t["locked"] is False for t in txs)

    assert _preview(client, user)["already_converted"] is True
    again = client.post("/api/ledger/conversion/apply", headers=user["headers"],
                        json={"fingerprint": report["fingerprint"]})
    assert again.status_code == 409


def test_data_changed_since_preview_blocks_apply(client, user, history):
    db, uid = history
    report = _preview(client, user)
    _event(db, uid, "99", "2026-11-09")
    r = client.post("/api/ledger/conversion/apply", headers=user["headers"],
                    json={"fingerprint": report["fingerprint"]})
    assert r.status_code == 409
    assert "changed" in r.json()["detail"]


def test_conversion_is_per_user(client, user, history, server):
    _account(server.db, "someone-else", "theirs")
    report = _preview(client, user)
    assert [a["account_id"] for a in report["accounts"]] == ["bank"]
