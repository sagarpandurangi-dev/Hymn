"""Ledger core: postings, invariants, balances and both spending views."""
from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

import ledger
from ledger import Draft, LedgerError, build_postings

ACCOUNTS = {
    "bank": {"id": "bank", "account_type": "bank", "currency": "INR", "name": "HDFC"},
    "fd": {"id": "fd", "account_type": "fixed_deposit", "currency": "INR", "name": "FD"},
    "card": {"id": "card", "account_type": "credit_card", "currency": "INR", "name": "Scapia"},
    "loan": {"id": "loan", "account_type": "vehicle_loan", "currency": "INR", "name": "Car loan"},
    "usd": {"id": "usd", "account_type": "bank", "currency": "USD", "name": "US"},
}


def _draft(kind, **kw):
    kw.setdefault("date", "2026-11-05")
    kw.setdefault("currency", "INR")
    return Draft(kind=kind, **kw)


def _amounts(postings):
    return {p["account_id"]: p["amount"] for p in postings}


# ---------------------------------------------------------------------------
# Postings per kind
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("draft, expected", [
    (_draft("expense", amount="500", from_account_id="bank", category="expense:fees"),
     {"expense:fees": Decimal(500), "bank": Decimal(-500)}),
    (_draft("expense", amount="2000", from_account_id="card"),
     {"expense:uncategorised": Decimal(2000), "card": Decimal(-2000)}),
    (_draft("income", amount="100000", to_account_id="bank", category="income:salary"),
     {"bank": Decimal(100000), "income:salary": Decimal(-100000)}),
    (_draft("gift", amount="400000", to_account_id="bank"),
     {"bank": Decimal(400000), "income:gift": Decimal(-400000)}),
    (_draft("transfer", amount="50000", from_account_id="bank", to_account_id="fd"),
     {"fd": Decimal(50000), "bank": Decimal(-50000)}),
    (_draft("card_settlement", amount="2000", from_account_id="bank", to_account_id="card"),
     {"card": Decimal(2000), "bank": Decimal(-2000)}),
    (_draft("loan_payment", principal="8000", interest="2000", from_account_id="bank", to_account_id="loan"),
     {"bank": Decimal(-10000), "loan": Decimal(8000), "expense:interest": Decimal(2000)}),
    (_draft("refund", amount="200", to_account_id="card"),
     {"card": Decimal(200), "expense:uncategorised": Decimal(-200)}),
    (_draft("opening_balance", amount="20000", account_id="card"),
     {"card": Decimal(-20000), "equity:opening": Decimal(20000)}),
    (_draft("opening_balance", amount="150000", account_id="bank"),
     {"bank": Decimal(150000), "equity:opening": Decimal(-150000)}),
])
def test_postings_per_kind_balance_to_zero(draft, expected):
    postings = build_postings(draft, ACCOUNTS)
    assert _amounts(postings) == expected
    assert sum(p["amount"] for p in postings) == 0


def test_cash_date_applies_to_real_accounts_only():
    postings = build_postings(
        _draft("expense", amount="100", from_account_id="bank", cash_date="2026-11-07"), ACCOUNTS,
    )
    assert {p["account_id"]: p["date"] for p in postings} == {
        "expense:uncategorised": "2026-11-05", "bank": "2026-11-07",
    }


@pytest.mark.parametrize("draft, message", [
    (_draft("expense", amount="0", from_account_id="bank"), "greater than zero"),
    (_draft("expense", amount="-5", from_account_id="bank"), "greater than zero"),
    (_draft("expense", amount="abc", from_account_id="bank"), "number"),
    (_draft("expense", amount="5"), "from_account_id is required"),
    (_draft("expense", amount="5", from_account_id="nope"), "Unknown account"),
    (_draft("expense", amount="5", from_account_id="usd"), "is in USD"),
    (_draft("expense", amount="5", from_account_id="bank", category="income:salary"), "expense account"),
    (_draft("income", amount="5", to_account_id="card"), "asset"),
    (_draft("transfer", amount="5", from_account_id="bank", to_account_id="bank"), "must differ"),
    (_draft("transfer", amount="5", from_account_id="bank", to_account_id="card"), "asset"),
    (_draft("card_settlement", amount="5", from_account_id="bank", to_account_id="loan"), "credit_card"),
    (_draft("loan_payment", principal="5", from_account_id="bank", to_account_id="card"), "loan"),
    (_draft("loan_payment", principal="0", interest="0", from_account_id="bank", to_account_id="loan"), "not both zero"),
    (_draft("expense", amount="5", from_account_id="bank", date="05-11-2026"), "YYYY-MM-DD"),
    (_draft("bribe", amount="5"), "kind must be"),
])
def test_invalid_transactions_are_rejected(draft, message):
    with pytest.raises(LedgerError, match=message):
        build_postings(draft, ACCOUNTS)


def test_unbalanced_postings_are_rejected():
    with pytest.raises(LedgerError, match="sum to zero"):
        ledger.check_balanced([
            {"account_id": "bank", "amount": Decimal(5)},
            {"account_id": "expense:fees", "amount": Decimal(-4)},
        ])


# ---------------------------------------------------------------------------
# Through the API
# ---------------------------------------------------------------------------

@pytest.fixture()
def user(client, server):
    r = client.post("/api/auth/signup", json={
        "name": "Ledger", "email": "ledger@example.com", "password": "correct-horse-battery",
        "security_question": "Q?", "security_answer": "A",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    uid = body["user"]["id"]
    asyncio.run(server.db.financial_accounts.insert_many([
        {**a, "user_id": uid} for a in ACCOUNTS.values()
    ]))
    return {"id": uid, "headers": {"Authorization": f"Bearer {body['access_token']}"}}


def _post(client, user, **body):
    body.setdefault("currency", "INR")
    r = client.post("/api/ledger/transactions", headers=user["headers"], json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _balances(client, user, as_of="2026-12-31"):
    r = client.get(f"/api/ledger/balances?as_of={as_of}", headers=user["headers"])
    return {b["account_id"]: b["balance"] for b in r.json()}


def _spending(client, user, basis, start, end):
    r = client.get(f"/api/ledger/spending?basis={basis}&start={start}&end={end}", headers=user["headers"])
    assert r.status_code == 200, r.text
    rows = r.json()["by_currency"]
    return rows[0]["by_account"] if rows else {}


def test_moving_money_to_an_fd_is_not_spending(client, user):
    _post(client, user, kind="opening_balance", date="2026-11-01", amount="100000", account_id="bank")
    _post(client, user, kind="transfer", date="2026-11-02", amount="50000",
          from_account_id="bank", to_account_id="fd")
    b = _balances(client, user)
    assert (b["bank"], b["fd"]) == ("50000.00", "50000.00")
    for basis in ("accrual", "cash"):
        assert _spending(client, user, basis, "2026-11-01", "2026-11-30") == {}


def test_card_dinner_is_accrual_spending_now_and_cash_spending_when_paid(client, user):
    _post(client, user, kind="opening_balance", date="2026-11-01", amount="100000", account_id="bank")
    _post(client, user, kind="expense", date="2026-11-05", amount="2000", from_account_id="card")
    assert _balances(client, user, "2026-11-30")["card"] == "2000.00"  # owed
    assert _spending(client, user, "accrual", "2026-11-01", "2026-11-30") == {"expense:uncategorised": "2000.00"}
    assert _spending(client, user, "cash", "2026-11-01", "2026-11-30") == {}

    _post(client, user, kind="card_settlement", date="2026-12-02", amount="2000",
          from_account_id="bank", to_account_id="card")
    b = _balances(client, user)
    assert (b["bank"], b["card"]) == ("98000.00", "0.00")
    assert _spending(client, user, "accrual", "2026-12-01", "2026-12-31") == {}
    assert _spending(client, user, "cash", "2026-12-01", "2026-12-31") == {"expense:uncategorised": "2000.00"}


def test_partial_card_payments_settle_oldest_charges_first(client, user):
    _post(client, user, kind="expense", date="2026-11-01", amount="1000", from_account_id="card",
          category="expense:fees")
    _post(client, user, kind="expense", date="2026-11-03", amount="500", from_account_id="card")
    _post(client, user, kind="card_settlement", date="2026-11-20", amount="1200",
          from_account_id="bank", to_account_id="card")
    assert _spending(client, user, "cash", "2026-11-01", "2026-11-30") == {
        "expense:fees": "1000.00", "expense:uncategorised": "200.00",
    }
    _post(client, user, kind="card_settlement", date="2026-12-05", amount="300",
          from_account_id="bank", to_account_id="card")
    assert _spending(client, user, "cash", "2026-12-01", "2026-12-31") == {"expense:uncategorised": "300.00"}


def test_refund_on_card_cancels_charges(client, user):
    _post(client, user, kind="expense", date="2026-11-01", amount="1000", from_account_id="card")
    _post(client, user, kind="refund", date="2026-11-04", amount="200", to_account_id="card")
    _post(client, user, kind="card_settlement", date="2026-11-20", amount="800",
          from_account_id="bank", to_account_id="card")
    for basis in ("accrual", "cash"):
        assert _spending(client, user, basis, "2026-11-01", "2026-11-30") == {"expense:uncategorised": "800.00"}
    assert _balances(client, user)["card"] == "0.00"


def test_overpaying_a_card_leaves_credit_for_later_charges(client, user):
    _post(client, user, kind="card_settlement", date="2026-11-01", amount="500",
          from_account_id="bank", to_account_id="card")
    _post(client, user, kind="expense", date="2026-11-10", amount="300", from_account_id="card")
    assert _spending(client, user, "cash", "2026-11-10", "2026-11-10") == {"expense:uncategorised": "300.00"}
    assert _balances(client, user)["card"] == "-200.00"  # in credit


def test_owed_before_the_ledger_counts_as_cash_spending_when_paid(client, user):
    _post(client, user, kind="opening_balance", date="2026-11-01", amount="20000", account_id="card")
    _post(client, user, kind="card_settlement", date="2026-11-15", amount="20000",
          from_account_id="bank", to_account_id="card")
    assert _spending(client, user, "accrual", "2026-11-01", "2026-11-30") == {}
    assert _spending(client, user, "cash", "2026-11-01", "2026-11-30") == {"expense:uncategorised": "20000.00"}
    # A later charge isn't swallowed by that payment.
    _post(client, user, kind="expense", date="2026-11-20", amount="100", from_account_id="card")
    assert _spending(client, user, "cash", "2026-11-20", "2026-11-30") == {}


def test_emi_splits_into_principal_and_interest(client, user):
    _post(client, user, kind="opening_balance", date="2026-11-01", amount="500000", account_id="loan")
    _post(client, user, kind="loan_payment", date="2026-11-05", principal="8000", interest="2000",
          from_account_id="bank", to_account_id="loan")
    b = _balances(client, user)
    assert (b["bank"], b["loan"]) == ("-10000.00", "492000.00")
    for basis in ("accrual", "cash"):
        assert _spending(client, user, basis, "2026-11-01", "2026-11-30") == {"expense:interest": "2000.00"}


def test_net_worth_is_unchanged_by_transfers_and_settlements(client, user):
    def net_worth():
        r = client.get("/api/ledger/balances?as_of=2026-12-31", headers=user["headers"]).json()
        return sum(Decimal(b["balance"]) * (1 if b["class"] == "asset" else -1)
                   for b in r if b["currency"] == "INR")

    _post(client, user, kind="opening_balance", date="2026-11-01", amount="100000", account_id="bank")
    _post(client, user, kind="expense", date="2026-11-02", amount="1000", from_account_id="card")
    before = net_worth()
    _post(client, user, kind="transfer", date="2026-11-03", amount="40000", from_account_id="bank", to_account_id="fd")
    _post(client, user, kind="card_settlement", date="2026-11-04", amount="1000", from_account_id="bank", to_account_id="card")
    assert net_worth() == before == Decimal("99000")


def test_voided_transactions_drop_out(client, user):
    tx = _post(client, user, kind="expense", date="2026-11-05", amount="700", from_account_id="bank")
    assert tx["locked"] is True and tx["provenance"] == "user"
    r = client.post(f"/api/ledger/transactions/{tx['id']}/void", headers=user["headers"])
    assert r.status_code == 200
    assert _balances(client, user)["bank"] == "0.00"
    assert _spending(client, user, "accrual", "2026-11-01", "2026-11-30") == {}
    again = client.post(f"/api/ledger/transactions/{tx['id']}/void", headers=user["headers"])
    assert again.status_code == 404


def test_other_users_accounts_cannot_be_used(client, user, server):
    asyncio.run(server.db.financial_accounts.insert_one(
        {"id": "theirs", "user_id": "someone-else", "account_type": "bank", "currency": "INR"},
    ))
    r = client.post("/api/ledger/transactions", headers=user["headers"], json={
        "kind": "expense", "date": "2026-11-05", "currency": "INR", "amount": "5", "from_account_id": "theirs",
    })
    assert r.status_code == 400
    assert "Unknown account" in r.json()["detail"]


def test_bad_report_dates_are_rejected(client, user):
    r = client.get("/api/ledger/spending?start=2026/11/01&end=2026-11-30", headers=user["headers"])
    assert r.status_code == 400
