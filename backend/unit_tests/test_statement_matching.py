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
    assert (s[0]["confidence"], s[0]["category"]) == ("known", "expense:food")
    assert s[0]["why"] == "Zomato is usually food. Change it once and Hymn learns."
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
    assert _suggest(client, user, nxt)["lines"][0]["confidence"] == "known"  # back to the built-in list


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


def test_ai_guesses_each_unknown_merchant_once_per_user(client, user, server, monkeypatch):
    calls = []

    async def guess(lines, expense, income):
        calls.append(sorted(l["description"] for l in lines))
        assert "food" in expense and "salary" in income
        return {l["n"]: "expense:food" for l in lines if "VARIETIES" in l["description"]}
    monkeypatch.setattr(statements_ai, "guess_categories", guess)
    sid = _statement(server, user, [_line(1, "2026-10-02", "UPI/111/SRI KRISHNA VARIETIES", debit="90"),
                                    _line(2, "2026-10-09", "UPI/222/SRI KRISHNA VARIETIES", debit="60"),
                                    _line(3, "2026-10-03", "UPI/333/RAMESH KUMAR", debit="200"),
                                    _line(4, "2026-10-04", "SWIGGY BANGALORE", debit="450")], account_id="bank")
    lines = {l["n"]: l for l in _suggest(client, user, sid)["lines"]}
    assert [lines[n]["confidence"] for n in (1, 2, 3, 4)] == ["ai", "ai", "new", "known"]
    assert lines[1]["category"] == lines[2]["category"] == "expense:food"
    assert "guess" in lines[1]["why"].lower()
    # One line per unknown merchant; Swiggy came from the free list.
    assert calls == [["UPI/111/SRI KRISHNA VARIETIES", "UPI/333/RAMESH KUMAR"]]
    # The same merchants on another card's statement: no AI call at all.
    sid2 = _statement(server, user, [_line(1, "2026-10-12", "SRI KRISHNA VARIETIES BLR", debit="80"),
                                     _line(2, "2026-10-13", "RAMESH KUMAR", debit="100")],
                      kind="credit_card", account_id="card", last4="9876")
    lines2 = {l["n"]: l for l in _suggest(client, user, sid2)["lines"]}
    assert lines2[1]["confidence"] == "ai" and lines2[2]["confidence"] == "new"
    assert len(calls) == 1


def test_ai_failure_is_not_remembered(client, user, server, monkeypatch, no_ai):
    sid = _statement(server, user, [_line(1, "2026-10-02", "SRI KRISHNA VARIETIES", debit="90")], account_id="bank")
    _suggest(client, user, sid)
    _suggest(client, user, sid)
    assert len(no_ai) == 2  # asked again next time, not cached as "no idea"


def test_known_merchants_need_no_ai(client, user, server, no_ai):
    sid = _statement(server, user, [_line(1, "2026-10-02", "UPI/4521/SWIGGY8/swiggy@icici", debit="450"),
                                    _line(2, "2026-10-03", "INDIAN OIL CORP HSR", debit="2000"),
                                    _line(3, "2026-10-04", "NETFLIX.COM", debit="649")], account_id="bank")
    lines = {l["n"]: l for l in _suggest(client, user, sid)["lines"]}
    assert [lines[n]["category"] for n in (1, 2, 3)] == ["expense:food", "expense:fuel", "expense:subscriptions"]
    assert all(l["confidence"] == "known" for l in lines.values())
    assert no_ai == []


@pytest.mark.parametrize("desc,expected", [
    ("UPI/4521/SWIGGY8/swiggy@icici", "food"),
    ("SWIGGY INSTAMART BLR", "groceries"),
    ("Uber India Systems", "transport"),
    ("FASTAG RECHARGE", "transport"),
    ("BESCOM BILL PAYMENT", "bills"),
    ("GST ON ANNUAL FEE", "fees"),
    ("POS COLA STORE", None),          # OLA must not match inside COLA
    ("UPI/NANDINI R/xx", None),        # people's names are not merchants
    ("RAMESH H M", None),
    ("AMAZON PAY INDIA", None),        # mixed merchants are left to the user / AI
    ("ATM CASH WDL", None),            # cash is a transfer, not spending
])
def test_merchant_directory(desc, expected):
    import merchant_directory
    hit = merchant_directory.lookup(desc)
    assert (hit[0] if hit else None) == expected


def test_directory_categories_exist_in_the_ledger():
    import ledger
    import merchant_directory
    assert all(c in ledger.EXPENSE_CATEGORIES and c != "uncategorised" for _, c in merchant_directory.KEYWORDS)
    assert len(merchant_directory.KEYWORDS) >= 500


def test_learned_rules_beat_ai_guesses(client, user, server, monkeypatch, no_ai):
    sid = _statement(server, user, [_line(1, "2026-10-02", "SWIGGY BANGALORE", debit="450")], account_id="bank")
    assert _suggest(client, user, sid)["lines"][0]["confidence"] == "known"
    _accept_all(client, user, sid, {1: {"category": "expense:groceries"}})
    sid2 = _statement(server, user, [_line(1, "2026-10-12", "SWIGGY BANGALORE", debit="300")], account_id="bank")
    line = _suggest(client, user, sid2)["lines"][0]
    assert line["category"] == "expense:groceries" and line["confidence"] == "learned"
    assert no_ai == []


def test_ai_down_still_suggests(client, user, server):
    sid = _statement(server, user, [_line(1, "2026-10-02", "SRI KRISHNA VARIETIES", debit="450")], account_id="bank")
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


# ---------------------------------------------------------------------------
# Similar names and habits
# ---------------------------------------------------------------------------

def _rule(key, category, times=1, direction="out", account="bank"):
    return {(key, account, direction): {"merchant_key": key, "account_id": account, "direction": direction,
                                        "kind": "expense", "category": category, "times_confirmed": times}}


def test_similar_names_share_what_you_taught():
    from statement_matching import similar_category
    rules = {**_rule("ANNAPOORNA NAIVEDHYA", "expense:food"), **_rule("RAJU MOTORS", "expense:transport", account="card")}
    assert similar_category("ANNAPOORNA KITCHENETTE", rules, "out") == ("expense:food", "ANNAPOORNA NAIVEDHYA")
    assert similar_category("GOPAL NAIVEDYA", rules, "out")[0] == "expense:food"     # one letter off
    assert similar_category("RAJU MOTOR", rules, "out")[0] == "expense:transport"    # across accounts
    assert similar_category("SRI LAKSHMI", {**rules, **_rule("SRI GANESH", "expense:food")}, "out") is None
    assert similar_category("ANNAPOORNA NAIVEDHYA", rules, "in") is None
    split = {**_rule("RAJU STORES", "expense:groceries", 2), **_rule("RAJU MOTORS", "expense:transport", 2)}
    assert similar_category("RAJU TAILORS", split, "out") is None                  # no clear winner


def test_habits_need_repetition_and_agreement():
    from decimal import Decimal as D
    from statement_matching import habit_category
    hist = [{"date": f"2026-10-{d:02d}", "amount": D(a), "category": "expense:personal_care"}
            for d, a in [(1, "40"), (3, "40"), (6, "45"), (9, "40")]]
    h = habit_category(D("42"), "2026-10-20", hist)
    assert (h["category"], h["times"], h["since"]) == ("expense:personal_care", 4, "2026-10-01")
    assert habit_category(D("42"), "2026-10-20", hist[:3]) is None                      # not often enough
    assert habit_category(D("90"), "2026-10-20", hist) is None                          # different amount
    assert habit_category(D("42"), "2027-06-01", hist) is None                          # too long ago
    mixed = hist + [{"date": f"2026-10-1{d}", "amount": D("40"), "category": "expense:food"} for d in range(3)]
    assert habit_category(D("42"), "2026-10-20", mixed) is None                         # no clear habit


def test_review_uses_names_and_habits(client, user, server):
    first = _statement(server, user, [_line(1, "2026-10-02", "UPI/111/ANNAPOORNA NAIVEDHYA/x", debit="120")]
                       + [_line(n, f"2026-10-{n + 2:02d}", f"UPI/{n}/RAMESH KUMAR/x", debit="40") for n in range(2, 7)],
                       account_id="bank")
    _accept_all(client, user, first, {n: {"category": "expense:food" if n == 1 else "expense:personal_care"}
                                      for n in range(1, 7)})
    nxt = _statement(server, user, [_line(1, "2026-10-20", "UPI/9/ANNAPOORNA DELIGHTS/x", debit="200"),
                                    _line(2, "2026-10-21", "UPI/8/SURESH BABU/x", debit="42")],
                     account_id="card", kind="credit_card", last4="9876", period=("2026-10-16", "2026-10-31"))
    lines = {l["n"]: l for l in _suggest(client, user, nxt)["lines"]}
    assert (lines[1]["confidence"], lines[1]["category"]) == ("similar", "expense:food")
    assert lines[1]["why"] == "Similar to ANNAPOORNA NAIVEDHYA, which you marked food."
    assert (lines[2]["confidence"], lines[2]["category"]) == ("habit", "expense:personal_care")
    assert lines[2]["why"] == "You often spend about ₹42.00 on personal care: 5 times since 4 Oct."


def test_directory_keywords_stay_short():
    import merchant_directory
    assert all(1 <= len(k) <= 4 for k, _ in merchant_directory.KEYWORDS)  # catches a missing comma
