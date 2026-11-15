"""Investments from a CAS PDF: parse → preview → apply, without double counting."""
from __future__ import annotations

import asyncio
import base64
import copy
from decimal import Decimal

import pytest

import cas_import
import ledger
import ledger_sync
import money_service
from test_ledger_conversion import _account
from test_ledger_sync import _convert

PDF = base64.b64encode(b"%PDF-1.4 not really").decode()

CAMS = {
    "statement_period": {"from": "01-Apr-2026", "to": "10-Nov-2026"},
    "investor_info": {"name": "RAVI KUMAR", "email": "ravi@example.com", "address": "Somewhere", "mobile": "999"},
    "file_type": "CAMS", "cas_type": "DETAILED", "parse_warnings": [],
    "folios": [{"folio": "123/45", "amc": "Axis Mutual Fund", "schemes": [
        {"scheme": "Axis Small Cap Fund - Direct Growth", "rta_code": "AX1", "rta": "KFINTECH",
         "isin": "INF846K01K35", "open": "0", "close": "100.000", "close_calculated": "100.000",
         "valuation": {"date": "2026-11-10", "nav": "100.50", "value": "10050.00", "cost": "9000"},
         "transactions": []},
        {"scheme": "Parag Parikh Flexi Cap - Direct Growth", "rta_code": "PP1", "rta": "CAMS",
         "isin": "INF879O01027", "open": "0", "close": "50.000", "close_calculated": "50.000",
         "valuation": {"date": "2026-11-10", "nav": "80.00", "value": "4000.00"}, "transactions": []},
    ]}],
}
NSDL = {
    "statement_period": {"from": "2026-10-01", "to": "2026-10-31"},
    "investor_info": {"name": "RAVI KUMAR", "email": "", "address": "", "mobile": ""},
    "file_type": "CDSL", "parse_warnings": [],
    "accounts": [{"name": "Zerodha Broking", "type": "CDSL", "client_id": "1208160012345678", "folios": 0,
                  "balance": "16000", "owners": [],
                  "equities": [{"name": "INFOSYS", "isin": "INE009A01021", "num_shares": "10", "price": "1500",
                                "value": "15000"}],
                  "mutual_funds": [{"name": "Axis Small Cap", "isin": "INF846K01K35", "balance": "10", "nav": "100",
                                    "value": "1000", "folio": "123/45"}], "bonds": []}],
    "nps": {"pran": "XXXX1234", "value": "250000", "schemes": [{"scheme": "SBI Scheme E Tier I", "units": "5000",
                                                                 "nav": "50", "value": "250000"}]},
}


def _with(data, **changes):
    d = copy.deepcopy(data)
    for path, v in changes.items():
        node = d
        keys = path.split(".")
        for k in keys[:-1]:
            node = node[int(k)] if k.isdigit() else node[k]
        node[keys[-1]] = v
    return d


@pytest.fixture()
def user(client, server):
    b = client.post("/api/auth/signup", json={"name": "Ravi", "email": "cas@example.com",
                                              "password": "correct-horse-battery", "security_question": "Q?",
                                              "security_answer": "A"}).json()
    asyncio.run(server.db.users.update_one({"id": b["user"]["id"]}, {"$set": {"plan": "premium"}}))
    return {"id": b["user"]["id"], "headers": {"Authorization": f"Bearer {b['access_token']}"}}


def _feed(monkeypatch, data):
    monkeypatch.setattr(cas_import, "read", lambda pdf, pw: cas_import.normalise(data))


def _preview(client, user, monkeypatch, data, password="secret"):
    _feed(monkeypatch, data)
    r = client.post("/api/investments/cas/preview", headers=user["headers"],
                    json={"file_base64": PDF, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def _apply(client, user, imp, **body):
    return client.post(f"/api/investments/cas/{imp['id']}/apply", headers=user["headers"], json=body or None)


def _fund(db, uid, key_part):
    return asyncio.run(db.financial_accounts.find_one({"user_id": uid, "cas_key": {"$regex": key_part}}, {"_id": 0}))


# --- Reading ----------------------------------------------------------------------

def test_cams_and_demat_statements_become_holdings():
    c = cas_import.normalise(CAMS)
    assert c["source"] == "CAMS/KFintech" and c["period"] == {"from": "2026-04-01", "to": "2026-11-10"}
    axis = c["holdings"][0]
    assert (axis["key"], axis["value"], axis["valued_on"]) == ("mutual_fund:inf846k01k35:123/45",
                                                               Decimal("10050.00"), "2026-11-10")
    bad = cas_import.normalise(_with(CAMS, **{"folios.0.schemes.1.close_calculated": "49.000"}))
    assert "Units don't add up" in bad["holdings"][1]["check"]
    off = cas_import.normalise(_with(CAMS, **{"folios.0.schemes.1.valuation.value": "5000"}))
    assert "doesn't match" in off["holdings"][1]["check"]
    n = cas_import.normalise(NSDL)
    kinds = {h["kind"]: h for h in n["holdings"]}
    assert kinds["stock"]["name"] == "Shares — Zerodha Broking 5678" and kinds["stock"]["value"] == 15000
    assert kinds["nps"]["value"] == 250000 and kinds["nps"]["name"] == "NPS …1234"
    assert kinds["mutual_fund"]["key"] == axis["key"]                 # same fund, same account


def test_unreadable_pdfs_are_refused_by_the_real_parser():
    with pytest.raises(cas_import.CASUnreadable):
        cas_import.read(b"%PDF-1.4 garbage", "ABCDE1234F")


def test_premium_only_and_nothing_sensitive_is_kept(client, server, user, monkeypatch):
    free = client.post("/api/auth/signup", json={"name": "F", "email": "free@example.com",
                                                 "password": "correct-horse-battery", "security_question": "Q?",
                                                 "security_answer": "A"}).json()
    r = client.post("/api/investments/cas/preview", headers={"Authorization": f"Bearer {free['access_token']}"},
                    json={"file_base64": PDF, "password": "x"})
    assert r.status_code == 403
    p = _preview(client, user, monkeypatch, CAMS, password="MYSECRET99")
    doc = asyncio.run(server.db.cas_imports.find_one({"id": p["id"]}, {"_id": 0}))
    text = str(doc)
    assert "MYSECRET99" not in text and "ravi@example.com" not in text and "Somewhere" not in text
    monkeypatch.setattr(cas_import, "read", lambda pdf, pw: (_ for _ in ()).throw(cas_import.CASUnreadable("x")))
    r = client.post("/api/investments/cas/preview", headers=user["headers"], json={"file_base64": PDF, "password": "x"})
    assert r.status_code == 400 and "password" in r.json()["detail"]


# --- Before switching to the money book ---------------------------------------------

def test_import_update_older_and_twice(client, server, user, monkeypatch):
    db, uid = server.db, user["id"]
    p = _preview(client, user, monkeypatch, CAMS)
    assert [l["action"] for l in p["lines"]] == ["new", "new"] and p["total"] == "14050.00"
    r = _apply(client, user, p).json()
    assert r["applied"]["new"] == 2
    axis = _fund(db, uid, "inf846k01k35")
    rows = asyncio.run(money_service.load_account_positions(db, uid))
    assert Decimal(next(x for x in rows if x["account_id"] == axis["id"])["effective_current_balance"]) == 10050
    assert axis["account_type"] == "mutual_fund" and axis["cas_units"] == "100.000"
    # The same statement again: refused.
    again = _preview(client, user, monkeypatch, CAMS)
    assert again["already_applied"] is True and _apply(client, user, again).status_code == 409
    # A newer statement updates; an older one never overwrites it.
    newer = _with(CAMS, **{"folios.0.schemes.0.valuation": {"date": "2026-12-10", "nav": "110", "value": "11000"}})
    p2 = _preview(client, user, monkeypatch, newer)
    assert p2["lines"][0]["action"] == "update" and p2["lines"][0]["change"] == "950.00"
    _apply(client, user, p2)
    older = _with(CAMS, **{"folios.0.schemes.0.valuation": {"date": "2026-10-01", "nav": "90", "value": "9000"}})
    p3 = _preview(client, user, monkeypatch, older)
    assert p3["lines"][0]["action"] == "older"
    _apply(client, user, p3)
    assert _fund(db, uid, "inf846k01k35")["current_value"].to_decimal() == 11000


def test_hand_typed_accounts_can_be_linked_or_replaced(client, server, user, monkeypatch):
    db, uid = server.db, user["id"]
    _account(db, uid, "my_axis", account_type="mutual_fund", value="9000")
    _account(db, uid, "all_funds", account_type="mutual_fund", value="5000")
    _account(db, uid, "bank", account_type="bank", value="50000")
    p = _preview(client, user, monkeypatch, CAMS)
    assert {a["id"] for a in p["your_other_investment_accounts"]} == {"my_axis", "all_funds"}
    axis_key = p["lines"][0]["key"]
    assert _apply(client, user, p, links={axis_key: "bank"}).status_code == 400          # not an investment
    r = _apply(client, user, p, links={axis_key: "my_axis"}, replaces=["all_funds"]).json()
    assert (r["applied"]["update"], r["applied"]["new"], r["linked"], r["replaced"]) == (1, 1, 1, 1)
    accts = {a["id"]: a for a in asyncio.run(db.financial_accounts.find({"user_id": uid}, {"_id": 0}).to_list(None))}
    assert accts["my_axis"]["current_value"].to_decimal() == 10050
    assert accts["all_funds"]["current_value"].to_decimal() == 0
    funds = [a for a in accts.values() if a["account_type"] == "mutual_fund"]
    assert sum(a["current_value"].to_decimal() for a in funds) == 14050           # counted once
    later = _preview(client, user, monkeypatch, _with(CAMS, **{"folios.0.schemes.0.valuation.date": "2026-12-01"}))
    assert later["your_other_investment_accounts"] == []


# --- On the money book (converted users) ----------------------------------------------

def test_on_the_money_book_value_changes_are_market_moves(client, server, user, monkeypatch):
    db, uid = server.db, user["id"]
    _account(db, uid, "bank", account_type="bank", value="50000")
    _convert(client, user)
    p = _preview(client, user, monkeypatch, CAMS)
    assert p["converted"] is True
    _apply(client, user, p)
    axis = _fund(db, uid, "inf846k01k35")
    assert axis["current_value"].to_decimal() == 0                     # the money book holds the value

    def bal(on="2027-12-31"):
        return Decimal(next(b for b in asyncio.run(ledger.balances(db, uid, on))
                            if b["account_id"] == axis["id"])["balance"])
    assert bal() == 10050 and bal("2026-11-09") == 0                   # from the statement date, not before
    newer = _with(CAMS, **{"folios.0.schemes.0.valuation": {"date": "2026-12-10", "nav": "110", "value": "11000"}})
    _apply(client, user, _preview(client, user, monkeypatch, newer))
    assert bal() == 11000 and bal("2026-12-09") == 10050               # the past stays as it was
    txs = asyncio.run(ledger.load_transactions(db, uid, account_id=axis["id"]))
    assert [t["kind"] for t in txs] == ["opening_balance", "revaluation"]
    # Not income, not spending: the I&E and cash flow don't move.
    ie = client.get("/api/reports/income-expenditure?month=2026-12", headers=user["headers"]).json()[0]
    assert ie["this_month"]["total_income"] == "0.00" and ie["year_to_date"]["surplus"] == "0.00"
    cf = client.get("/api/reports/cash-flow?start=2026-11-01&end=2026-12-31", headers=user["headers"]).json()[0]
    assert [line["key"] for sec in cf["sections"] for line in sec["lines"]] == ["other:opening"]   # bank only
    nw = client.get("/api/reports/net-worth?as_of=2026-12-31", headers=user["headers"]).json()[0]
    inv = next(g for g in nw["right"]["assets"] if g["group"] == "investments")
    assert inv["amount"] == "15000.00" and nw["left"]["net_worth"]["total"] == nw["right"]["total"]
    # The money book's own sync leaves these entries alone.
    asyncio.run(ledger_sync.sync(db, uid))
    assert bal() == 11000


def test_revaluation_entries_balance_and_need_an_asset():
    accts = {"f": {"id": "f", "account_type": "mutual_fund", "currency": "INR"},
             "c": {"id": "c", "account_type": "credit_card", "currency": "INR"}}
    postings = ledger.build_postings(ledger.Draft(kind="revaluation", date="2026-11-10", currency="INR",
                                                  amount="-500", account_id="f"), accts)
    assert sum(p["amount"] for p in postings) == 0 and {p["account_id"] for p in postings} == {"f", "equity:revaluation"}
    with pytest.raises(ledger.LedgerError):
        ledger.build_postings(ledger.Draft(kind="revaluation", date="2026-11-10", currency="INR", amount="5",
                                           account_id="c"), accts)
