"""Statement → ledger: suggestions, learning, own-account matching, openings."""
from __future__ import annotations

import asyncio
import uuid

import pytest

import statements_ai
from claude_client import AssistantUnavailable
from statement_matching import merchant_key

BANK = {"id": "bank", "account_type": "bank", "currency": "INR", "name": "HDFC Salary 1234"}
CARD = {"id": "card", "account_type": "credit_card", "currency": "INR", "name": "Scapia card 9876"}
USD = {"id": "usd", "account_type": "bank", "currency": "USD", "name": "US bank"}


@pytest.fixture(autouse=True)
def no_ai(monkeypatch):
    """Offline by default: the category guesser is unavailable."""
    calls = []

    async def down(lines, expense, income):
        calls.append(lines)
        raise AssistantUnavailable("offline")
    monkeypatch.setattr(statements_ai, "guess_categories", down)
    return calls


@pytest.fixture()
def user(client, server):
    r = client.post("/api/auth/signup", json={
        "name": "Match", "email": "match@example.com", "password": "correct-horse-battery",
        "security_question": "Q?", "security_answer": "A",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    uid = body["user"]["id"]
    asyncio.run(server.db.financial_accounts.insert_many([{**a, "user_id": uid} for a in (BANK, CARD, USD)]))
    return {"id": uid, "headers": {"Authorization": f"Bearer {body['access_token']}"}}


def _line(n, date, desc, debit="", credit="", ref="", balance=""):
    return {"n": n, "date": date, "description": desc, "reference": ref,
            "debit": debit, "credit": credit, "balance": balance}


def _statement(server, user, lines, kind="bank", opening="", closing="", account_id=None,
               period=("2026-10-01", "2026-10-31"), last4="1234", institution="HDFC Bank"):
    doc = {
        "id": str(uuid.uuid4()), "user_id": user["id"], "file_id": "f", "filename": "s.pdf",
        "status": "ready", "lines": lines, "account_id": account_id,
        "metadata": {"institution": institution, "account_kind": kind, "account_last4": last4,
                     "currency": "INR", "period_start": period[0], "period_end": period[1],
                     "opening_balance": opening, "closing_balance": closing},
        "created_at": "2026-11-01", "updated_at": "2026-11-01",
    }
    asyncio.run(server.db.statement_imports.insert_one(doc))
    return doc["id"]


def _suggest(client, user, sid):
    r = client.get(f"/api/statements/{sid}/suggestions", headers=user["headers"])
    assert r.status_code == 200, r.text
    return r.json()


def _confirm(client, user, sid, decisions, status=200):
    r = client.post(f"/api/statements/{sid}/confirm", headers=user["headers"], json={"decisions": decisions})
    assert r.status_code == status, r.text
    return r.json()


def _accept_all(client, user, sid, overrides=None):
    overrides = overrides or {}
    s = _suggest(client, user, sid)
    decisions = []
    for line in s["lines"]:
        d = {k: line.get(k) for k in ("action", "kind", "category", "counter_account_id",
                                      "duplicate_of", "merge_with")}
        d.update(overrides.get(line["n"], {}))
        decisions.append({"n": line["n"], **d})
    return _confirm(client, user, sid, decisions)


def _spending(client, user, basis="accrual"):
    r = client.get(f"/api/ledger/spending?basis={basis}&start=2026-10-01&end=2026-12-31", headers=user["headers"])
    rows = r.json()["by_currency"]
    return rows[0]["by_account"] if rows else {}


# ---------------------------------------------------------------------------
# Merchant keys
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("desc, key", [
    ("UPI/ZOMATO LTD/zomato@hdfcbank/Payment 4471", "ZOMATO"),
    ("POS 4321 SWIGGY BANGALORE", "SWIGGY BANGALORE"),
    ("NEFT-SAL-ZEISS INDIA PVT LTD", "SAL ZEISS"),
    ("123456", ""),
])
def test_merchant_key(desc, key):
    assert merchant_key(desc) == key


# ---------------------------------------------------------------------------
# Linking
# ---------------------------------------------------------------------------

def test_statement_must_be_linked_and_hymn_suggests_the_account(client, user, server):
    sid = _statement(server, user, [_line(1, "2026-10-02", "ZOMATO", debit="500")])
    s = _suggest(client, user, sid)
    assert s["account_id"] is None and s["account_suggestions"][0] == "bank"
    _confirm(client, user, sid, [{"n": 1, "action": "skip"}], status=409)
    wrong = client.post(f"/api/statements/{sid}/link", headers=user["headers"], json={"account_id": "usd"})
    assert wrong.status_code == 400
    ok = client.post(f"/api/statements/{sid}/link", headers=user["headers"], json={"account_id": "bank"})
    assert ok.status_code == 200
    assert _suggest(client, user, sid)["account_id"] == "bank"


# ---------------------------------------------------------------------------
# Learning
# ---------------------------------------------------------------------------

def test_hymn_learns_from_confirmations_and_corrections(client, user, server):
    sid = _statement(server, user, [
        _line(1, "2026-10-02", "UPI/ZOMATO LTD/zomato@hdfcbank", debit="500"),
        _line(2, "2026-10-03", "NEFT SALARY ZEISS", credit="100000"),
    ], account_id="bank")
    s = _suggest(client, user, sid)["lines"]
    assert (s[0]["confidence"], s[0]["category"]) == ("new", "expense:uncategorised")
    assert (s[1]["confidence"], s[1]["category"]) == ("guess", "income:salary")
    assert s[1]["suggestion"]["category"] == "income:salary" and "n" not in s[1]["suggestion"]
    _accept_all(client, user, sid, {1: {"category": "expense:food"}})

    nxt = _statement(server, user, [_line(1, "2026-11-04", "UPI/ZOMATO LTD/order 99", debit="350")],
                     account_id="bank", period=("2026-11-01", "2026-11-30"))
    s = _suggest(client, user, nxt)["lines"][0]
    assert (s["confidence"], s["category"]) == ("learned", "expense:food")
    assert s["why"] == "You chose expense:food for ZOMATO 1 time before."

    # A correction replaces what was learned.
    _confirm(client, user, nxt, [{"n": 1, "action": "create", "kind": "expense", "category": "expense:groceries"}])
    rules = client.get("/api/statements/rules/all", headers=user["headers"]).json()
    zomato = next(r for r in rules if r["merchant_key"] == "ZOMATO")
    assert (zomato["category"], zomato["times_confirmed"]) == ("expense:groceries", 1)


def test_always_makes_a_rule(client, user, server):
    sid = _statement(server, user, [_line(1, "2026-10-02", "SWIGGY", debit="400")], account_id="bank")
    _confirm(client, user, sid, [{"n": 1, "action": "create", "kind": "expense",
                                  "category": "expense:food", "always": True}])
    nxt = _statement(server, user, [_line(1, "2026-10-09", "SWIGGY", debit="250")], account_id="bank")
    s = _suggest(client, user, nxt)["lines"][0]
    assert (s["confidence"], s["why"]) == ("rule", "Your rule: SWIGGY → expense:food.")
    rule = client.get("/api/statements/rules/all", headers=user["headers"]).json()[0]
    assert client.patch(f"/api/statements/rules/{rule['id']}", headers=user["headers"],
                        json={"always": False}).status_code == 200
    assert client.delete(f"/api/statements/rules/{rule['id']}", headers=user["headers"]).status_code == 200
    assert _suggest(client, user, nxt)["lines"][0]["confidence"] == "new"


# ---------------------------------------------------------------------------
# Own accounts: card bills and duplicates are counted once
# ---------------------------------------------------------------------------

def test_card_payment_then_bank_debit_is_counted_once(client, user, server):
    card_sid = _statement(server, user, [
        _line(1, "2026-10-05", "AMAZON", debit="2000"),
        _line(2, "2026-10-20", "PAYMENT RECEIVED - THANK YOU", credit="2000"),
    ], kind="credit_card", account_id="card")
    s = _suggest(client, user, card_sid)["lines"]
    assert (s[1]["kind"], s[1]["counter_account_id"]) == ("card_settlement", "bank")
    _accept_all(client, user, card_sid)

    bank_sid = _statement(server, user, [_line(1, "2026-10-21", "CRED CLUB CARD BILL", debit="2000")],
                          account_id="bank")
    s = _suggest(client, user, bank_sid)["lines"][0]
    assert s["action"] == "duplicate"
    result = _accept_all(client, user, bank_sid)
    assert result["linked_to_existing"] == 1 and result["created"] == 0
    assert _spending(client, user) == {"expense:uncategorised": "2000.00"}       # the purchase only
    assert _spending(client, user, "cash") == {"expense:uncategorised": "2000.00"}


def test_bank_debit_first_recorded_as_spending_is_fixed_by_the_card_statement(client, user, server):
    bank_sid = _statement(server, user, [_line(1, "2026-10-21", "CRED CLUB", debit="2000")], account_id="bank")
    _accept_all(client, user, bank_sid)                          # wrongly kept as spending
    assert _spending(client, user) == {"expense:uncategorised": "2000.00"}

    card_sid = _statement(server, user, [
        _line(1, "2026-10-05", "AMAZON", debit="2000"),
        _line(2, "2026-10-20", "PAYMENT RECEIVED", credit="2000"),
    ], kind="credit_card", account_id="card")
    s = _suggest(client, user, card_sid)["lines"][1]
    assert (s["action"], s["kind"], s["counter_account_id"]) == ("merge", "card_settlement", "bank")
    result = _accept_all(client, user, card_sid)
    assert result["merged"] == 1
    assert _spending(client, user) == {"expense:uncategorised": "2000.00"}       # Amazon, not twice


def test_same_reference_from_another_source_is_already_recorded(client, user, server):
    bank_sid = _statement(server, user, [_line(1, "2026-10-02", "UPI ZOMATO", debit="540", ref="UPI123")],
                          account_id="bank")
    _accept_all(client, user, bank_sid)
    phonepe = _statement(server, user, [_line(1, "2026-10-02", "Paid to Zomato", debit="540", ref="UPI123")],
                         kind="wallet", account_id="bank", institution="PhonePe")
    s = _suggest(client, user, phonepe)["lines"][0]
    assert s["action"] == "duplicate" and "UPI123" in s["why"]


# ---------------------------------------------------------------------------
# Opening balances, reconciliation, safety
# ---------------------------------------------------------------------------

def test_first_statement_sets_opening_and_reconciles(client, user, server):
    sid = _statement(server, user, [
        _line(1, "2026-10-02", "ZOMATO", debit="500", balance="9500"),
        _line(2, "2026-10-03", "SALARY", credit="1000", balance="10500"),
    ], opening="10000", closing="10500", account_id="bank")
    result = _accept_all(client, user, sid)
    assert result["opening_balance_set"] is True
    assert result["balance_check"] == {"available": True, "ledger_balance": "10500.00",
                                       "statement_closing": "10500", "matches": True}
    assert result["remaining"] == 0
    assert client.get(f"/api/statements/{sid}", headers=user["headers"]).json()["status"] == "confirmed"

    # The next statement for the same account doesn't set another opening.
    nxt = _statement(server, user, [_line(1, "2026-11-02", "ZOMATO", debit="100")],
                     opening="10500", account_id="bank", period=("2026-11-01", "2026-11-30"))
    assert _accept_all(client, user, nxt)["opening_balance_set"] is False


def test_a_bad_line_writes_nothing(client, user, server):
    sid = _statement(server, user, [
        _line(1, "2026-10-02", "ZOMATO", debit="500"),
        _line(2, "2026-10-20", "PAYMENT RECEIVED", credit="100"),
    ], opening="1000", account_id="card", kind="credit_card")
    r = client.post(f"/api/statements/{sid}/confirm", headers=user["headers"], json={"decisions": [
        {"n": 1, "action": "create", "kind": "expense", "category": "expense:food"},
        {"n": 2, "action": "create", "kind": "card_settlement", "counter_account_id": "usd"},
    ]})
    assert r.status_code == 400 and "Line 2" in r.json()["detail"]
    assert asyncio.run(server.db.ledger_transactions.count_documents({})) == 0


def test_confirming_twice_does_not_duplicate(client, user, server):
    sid = _statement(server, user, [_line(1, "2026-10-02", "ZOMATO", debit="500")], account_id="bank")
    decision = [{"n": 1, "action": "create", "kind": "expense", "category": "expense:food"}]
    _confirm(client, user, sid, decision)
    _confirm(client, user, sid, decision)
    assert asyncio.run(server.db.ledger_transactions.count_documents({"kind": "expense"})) == 1
    assert _suggest(client, user, sid)["lines"] == []


def test_rules_and_statements_are_private(client, user, server):
    sid = _statement(server, user, [_line(1, "2026-10-02", "ZOMATO", debit="500")], account_id="bank")
    other = client.post("/api/auth/signup", json={
        "name": "Other", "email": "other@example.com", "password": "another-long-password",
        "security_question": "Q?", "security_answer": "A",
    }).json()
    h = {"Authorization": f"Bearer {other['access_token']}"}
    assert client.get(f"/api/statements/{sid}/suggestions", headers=h).status_code == 404
    assert client.get("/api/statements/rules/all", headers=h).json() == []


def test_ai_guesses_categories_for_new_merchants_once(client, user, server, monkeypatch):
    calls = []

    async def guess(lines, expense, income):
        calls.append([l["n"] for l in lines])
        assert "food" in expense and "salary" in income
        return {1: "expense:food"}
    monkeypatch.setattr(statements_ai, "guess_categories", guess)
    sid = _statement(server, user, [_line(1, "2026-10-02", "SWIGGY BANGALORE", debit="450"),
                                    _line(2, "2026-10-03", "RAMESH K", debit="200")], account_id="bank")
    lines = {l["n"]: l for l in _suggest(client, user, sid)["lines"]}
    assert lines[1]["category"] == "expense:food" and lines[1]["confidence"] == "ai"
    assert "guess" in lines[1]["why"].lower()
    assert lines[2]["category"] == "expense:uncategorised" and lines[2]["confidence"] == "new"
    _suggest(client, user, sid)
    assert calls == [[1, 2]]  # cached: asked once per statement


def test_learned_rules_beat_ai_guesses(client, user, server, monkeypatch, no_ai):
    sid = _statement(server, user, [_line(1, "2026-10-02", "SWIGGY BANGALORE", debit="450")], account_id="bank")
    _accept_all(client, user, sid, {1: {"category": "expense:groceries"}})
    sid2 = _statement(server, user, [_line(1, "2026-10-12", "SWIGGY BANGALORE", debit="300")], account_id="bank")
    line = _suggest(client, user, sid2)["lines"][0]
    assert line["category"] == "expense:groceries" and line["confidence"] == "learned"
    assert no_ai == [[{"n": 1, "description": "SWIGGY BANGALORE", "direction": "out"}]]


def test_ai_down_still_suggests(client, user, server):
    sid = _statement(server, user, [_line(1, "2026-10-02", "SWIGGY", debit="450")], account_id="bank")
    line = _suggest(client, user, sid)["lines"][0]
    assert line["confidence"] == "new"


def test_account_can_be_changed_until_lines_are_confirmed(client, user, server):
    sid = _statement(server, user, [_line(1, "2026-10-02", "SWIGGY", debit="450")], account_id="card")
    r = client.post(f"/api/statements/{sid}/link", headers=user["headers"], json={"account_id": "bank"})
    assert r.status_code == 200, r.text
    _accept_all(client, user, sid)
    r = client.post(f"/api/statements/{sid}/link", headers=user["headers"], json={"account_id": "card"})
    assert r.status_code == 409
    r = client.post(f"/api/statements/{sid}/link", headers=user["headers"], json={"account_id": "bank"})
    assert r.status_code == 200
