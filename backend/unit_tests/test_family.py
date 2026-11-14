"""Family net worth: invites by Pamphlet ID, consent, notional members, joint items."""
from __future__ import annotations

import asyncio

import ledger


def _signup(client, email, name):
    r = client.post("/api/auth/signup", json={"name": name, "email": email, "password": "correct-horse-battery",
                                              "security_question": "Q?", "security_answer": "A"})
    b = r.json()
    return {"id": b["user"]["id"], "hymn_id": b["user"]["hymn_id"],
            "headers": {"Authorization": f"Bearer {b['access_token']}"}}


def _bank(db, uid, amount):
    asyncio.run(db.financial_accounts.insert_one({"id": f"bank-{uid}", "user_id": uid, "name": "Bank",
                                                  "account_type": "bank", "currency": "INR"}))
    asyncio.run(ledger.record(db, uid, ledger.Draft(kind="opening_balance", date="2026-01-01", currency="INR",
                                                    amount=amount, account_id=f"bank-{uid}"), provenance="user"))


def test_family_net_worth_with_consent(client, server):
    db = server.db
    sagar = _signup(client, "sagar@example.com", "Sagar P")
    wife = _signup(client, "wife@example.com", "Asha K")
    stranger = _signup(client, "x@example.com", "X")
    _bank(db, sagar["id"], "200000")
    _bank(db, wife["id"], "150000")
    h = sagar["headers"]
    assert client.post("/api/family", headers=h).status_code == 201
    assert client.post("/api/family", headers=h).status_code == 409
    inv = client.post("/api/family/invite", headers=h, json={"pamphlet_id": wife["hymn_id"], "relation": "spouse"})
    assert inv.status_code == 201 and inv.json()["name"] == "Asha"
    # Before she accepts, nothing of hers is counted.
    nw = client.get("/api/family/net-worth", headers=h).json()
    assert nw["family"]["net_worth"] == "200000.00"
    # Only she can accept, choosing to share just her total.
    assert client.post(f"/api/family/invites/{inv.json()['id']}/accept", headers=stranger["headers"],
                       json={"share": "full"}).status_code == 404
    mine = client.get("/api/family", headers=wife["headers"]).json()["invites_for_me"]
    assert len(mine) == 1
    assert client.post(f"/api/family/invites/{mine[0]['id']}/accept", headers=wife["headers"],
                       json={"share": "total"}).status_code == 200
    # A kid without an account, and a joint home owned 50/50.
    kid = client.post("/api/family/members", headers=h, json={"name": "Anika", "relation": "daughter"}).json()
    client.post("/api/family/items", headers=h, json={"side": "asset", "group": "retirement", "name": "Sukanya",
                                                      "amount": "50000", "shares": {kid["id"]: 100}})
    me_id = next(m["member_id"] for m in client.get("/api/family/net-worth", headers=h).json()["members"]
                 if m["name"] == "Sagar P")
    wife_id = mine[0]["id"]
    r = client.post("/api/family/items", headers=h, json={"side": "asset", "group": "fixed", "name": "Flat",
                                                          "amount": "8000000", "shares": {me_id: 50, wife_id: 50}})
    assert r.status_code == 201, r.text
    nw = client.get("/api/family/net-worth", headers=h).json()
    cols = {m["name"]: m for m in nw["members"]}
    assert cols["Asha"]["net_worth"] == "4150000.00" and "assets" not in cols["Asha"]   # total only, as she chose
    assert cols["Sagar P"]["assets"] == {"cash": "200000.00", "fixed": "4000000.00"}
    assert cols["Anika"]["net_worth"] == "50000.00"
    assert nw["family"]["net_worth"] == "8400000.00"                                     # the flat counted once
    assert nw["family"]["assets"].get("cash") == "200000.00"                               # her breakdown never leaks
    # She can see the family too, and leave.
    assert client.get("/api/family/net-worth", headers=wife["headers"]).status_code == 200
    assert client.post("/api/family/leave", headers=wife["headers"]).status_code == 200
    assert client.get("/api/family/net-worth", headers=h).json()["family"]["net_worth"] == "4250000.00"


def test_rules(client, server):
    a = _signup(client, "a@example.com", "A")
    h = a["headers"]
    assert client.get("/api/family/net-worth", headers=h).status_code == 404
    client.post("/api/family", headers=h)
    assert client.post("/api/family/invite", headers=h, json={"pamphlet_id": "S000001"}).status_code == 404
    assert client.post("/api/family/invite", headers=h, json={"pamphlet_id": a["hymn_id"]}).status_code == 400
    me = client.get("/api/family", headers=h).json()["members"][0]["id"]
    bad = client.post("/api/family/items", headers=h, json={"side": "asset", "group": "fixed", "name": "Plot",
                                                            "amount": "100", "shares": {me: 60}})
    assert bad.status_code == 400
    item = client.post("/api/family/items", headers=h, json={"side": "liability", "group": "loans", "name": "Dad",
                                                             "amount": "50000", "shares": {me: 100}}).json()
    b = _signup(client, "b@example.com", "B")
    assert client.delete(f"/api/family/items/{item['id']}", headers=b["headers"]).status_code == 404
    assert client.delete(f"/api/family/items/{item['id']}", headers=h).status_code == 200
