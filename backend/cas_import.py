"""Investments from a Consolidated Account Statement (CAS) PDF.

Anyone can get one, free:

* **CAMS / KFintech CAS** — every mutual fund folio under a PAN (request it
  on the CAMS or KFintech website; it is emailed as a PDF whose password the
  person sets);
* **NSDL / CDSL CAS** — sent monthly to everyone with a demat account:
  shares, bonds, mutual funds held in demat and NPS.

Hymn reads it in code (the open-source ``casparser``, MIT licence — no AI,
so no cost per upload), checks each fund's units add up, shows a preview,
and only on "apply" brings the market values into the money book:

* each mutual fund (per folio) becomes its own investment account; shares,
  bonds and NPS become one account per demat account / PRAN with the
  holdings listed;
* the value is the statement's market value on its valuation date. Changes
  since the last import are recorded as a **market value change**
  (``revaluation``), never as income or spending, so past months stay as
  they were and nothing is counted twice. (Users who haven't switched to the
  money book yet get the account's balance updated instead.)
* an older statement never overwrites a newer value; the same statement
  can't be applied twice.

The password is used in memory only and never stored; nor are the PAN,
email, phone or address printed on the statement. Premium, like bank
statements.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import uuid
from datetime import date as date_type, datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional

from bson.decimal128 import Decimal128
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import ledger
import ledger_sync
from deps import get_current_user, get_db
from plans import require_feature

cas_router = APIRouter(prefix="/investments/cas", tags=["investments"])

MAX_BYTES = 15 * 1024 * 1024
CENT = Decimal("0.01")
VALUE_TOLERANCE = Decimal("0.01")      # units × price within 1% of the printed value
UNITS_TOLERANCE = Decimal("0.001")


class CASUnreadable(Exception):
    """Wrong password, or not a CAS Hymn can read."""


def _d(v) -> Optional[Decimal]:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except Exception:
        return None


def _day(v) -> str:
    if isinstance(v, date_type):
        return v.isoformat()
    s = str(v or "")[:10]
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s if fmt == "%Y-%m-%d" else str(v), fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def read(pdf: bytes, password: str) -> dict:
    """Parse a CAS PDF into plain holdings. Raises CASUnreadable."""
    import casparser
    from casparser.exceptions import ParserException

    try:
        data = casparser.read_cas_pdf(io.BytesIO(pdf), password)
    except ParserException as exc:
        raise CASUnreadable(type(exc).__name__) from exc
    except Exception as exc:  # malformed PDFs raise all sorts
        raise CASUnreadable(type(exc).__name__) from exc
    return normalise(data.model_dump(by_alias=True) if hasattr(data, "model_dump") else dict(data))


def normalise(d: dict) -> dict:
    """casparser output (CAMS/KFin or NSDL/CDSL) → Hymn's plain shape."""
    period = d.get("statement_period") or {}
    out = {"period": {"from": _day(period.get("from") or period.get("from_")), "to": _day(period.get("to"))},
           "investor": (d.get("investor_info") or {}).get("name", ""), "holdings": [],
           "warnings": list(d.get("parse_warnings") or [])}
    if "folios" in d:
        out["source"] = "CAMS/KFintech"
        for f in d["folios"]:
            for s in f.get("schemes", []):
                val = s.get("valuation") or {}
                units, close_calc = _d(s.get("close")), _d(s.get("close_calculated"))
                h = {"kind": "mutual_fund", "name": s.get("scheme", "").strip(), "amc": f.get("amc", ""),
                     "folio": f.get("folio", ""), "isin": s.get("isin") or s.get("rta_code") or "",
                     "units": units, "price": _d(val.get("nav")), "value": _d(val.get("value")) or Decimal(0),
                     "cost": _d(val.get("cost")), "valued_on": _day(val.get("date")) or out["period"]["to"]}
                if units is not None and close_calc is not None and abs(units - close_calc) > UNITS_TOLERANCE:
                    h["check"] = (f"Units don't add up: the statement shows {units}, its transactions give "
                                  f"{close_calc}.")
                out["holdings"].append(h)
    else:
        out["source"] = "NSDL/CDSL"
        to = out["period"]["to"]
        for a in d.get("accounts", []):
            where = f"{a.get('name', '').strip()} {str(a.get('client_id') or '')[-4:]}".strip()
            stocks = [{"name": e.get("name") or e["isin"], "isin": e["isin"], "units": _d(e.get("num_shares")),
                       "price": _d(e.get("price")), "value": _d(e.get("value")) or Decimal(0)}
                      for e in a.get("equities", [])]
            if stocks:
                out["holdings"].append({"kind": "stock", "name": f"Shares — {where}", "isin": f"demat:{where}",
                                        "folio": "", "units": None, "price": None, "valued_on": to,
                                        "value": sum((x["value"] for x in stocks), Decimal(0)), "items": stocks})
            bonds = [{"name": b.get("name") or b["isin"], "isin": b["isin"], "units": _d(b.get("num_bonds")),
                      "value": _d(b.get("value")) or Decimal(0)} for b in a.get("bonds", [])]
            if bonds:
                out["holdings"].append({"kind": "bond", "name": f"Bonds — {where}", "isin": f"bonds:{where}",
                                        "folio": "", "units": None, "price": None, "valued_on": to,
                                        "value": sum((x["value"] for x in bonds), Decimal(0)), "items": bonds})
            for m in a.get("mutual_funds", []):
                out["holdings"].append({"kind": "mutual_fund", "name": (m.get("name") or m["isin"]).strip(),
                                        "amc": "", "folio": m.get("folio") or f"demat {where}", "isin": m["isin"],
                                        "units": _d(m.get("balance")), "price": _d(m.get("nav")),
                                        "value": _d(m.get("value")) or Decimal(0), "cost": _d(m.get("total_cost")),
                                        "valued_on": to})
        nps = d.get("nps")
        if nps:
            pran = str(nps.get("pran") or "")[-4:]
            out["holdings"].append({"kind": "nps", "name": f"NPS{' …' + pran if pran else ''}", "isin": f"nps:{pran}",
                                    "folio": "", "units": None, "price": None, "valued_on": to,
                                    "value": _d(nps.get("value")) or Decimal(0),
                                    "items": [{"name": s.get("scheme"), "units": _d(s.get("units")),
                                               "value": _d(s.get("value"))} for s in nps.get("schemes", [])]})
    for h in out["holdings"]:
        h["key"] = f"{h['kind']}:{h['isin']}:{h['folio']}".lower()
        if h.get("units") is not None and h.get("price") is not None and h["value"] and "check" not in h:
            if abs(h["units"] * h["price"] - h["value"]) > h["value"] * VALUE_TOLERANCE:
                h["check"] = "Units × price doesn't match the value printed; please check this one."
    return out


def _plain(v):
    if isinstance(v, Decimal):
        return format(v, "f")
    if isinstance(v, list):
        return [_plain(x) for x in v]
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    return v


ACCOUNT_TYPE = {"mutual_fund": "mutual_fund", "stock": "stock", "bond": "bond", "nps": "nps"}


async def _accounts_by_key(db, user_id: str) -> Dict[str, dict]:
    rows = await db.financial_accounts.find({"user_id": user_id, "cas_key": {"$exists": True}},
                                            {"_id": 0}).to_list(length=None)
    return {r["cas_key"]: r for r in rows}


async def _current_value(db, user_id: str, acct: dict, on: str, converted: bool) -> Decimal:
    if converted:
        for b in await ledger.balances(db, user_id, on):
            if b["account_id"] == acct["id"]:
                return Decimal(b["balance"])
        return Decimal(0)
    v = acct.get("current_value")
    return v.to_decimal() if isinstance(v, Decimal128) else Decimal(str(v or 0))


async def plan(db, user_id: str, parsed: dict) -> dict:
    """What applying would do, per holding."""
    converted = (await ledger_sync.sync(db, user_id))["converted"]
    existing = await _accounts_by_key(db, user_id)
    lines, total = [], Decimal(0)
    for h in parsed["holdings"]:
        acct = existing.get(h["key"])
        line = {"key": h["key"], "kind": h["kind"], "name": h["name"], "folio": h.get("folio", ""),
                "units": h.get("units"), "price": h.get("price"), "value": h["value"], "cost": h.get("cost"),
                "valued_on": h["valued_on"], "items": h.get("items"), "check": h.get("check")}
        total += h["value"]
        if acct is None:
            line["action"] = "new"
        elif (acct.get("cas_valued_on") or "") > h["valued_on"]:
            line["action"] = "older"           # Hymn already has a newer value
        else:
            before = await _current_value(db, user_id, acct, h["valued_on"], converted)
            line.update(account_id=acct["id"], before=before, change=h["value"] - before,
                        action="same" if h["value"] == before else "update")
        lines.append(line)
    seen = {h["key"] for h in parsed["holdings"]}
    missing = [{"account_id": a["id"], "name": a["name"]} for k, a in existing.items()
               if k not in seen and a.get("cas_source") == parsed["source"]]
    # Investment accounts typed by hand: if they hold the same funds, the
    # person links or replaces them so nothing is counted twice.
    others = await db.financial_accounts.find(
        {"user_id": user_id, "cas_key": {"$exists": False}, "replaced_by_cas": {"$exists": False},
         "account_type": {"$in": list(ACCOUNT_TYPE.values())}},
        {"_id": 0, "id": 1, "name": 1, "account_type": 1}).to_list(length=None)
    for o in others:
        o["value"] = await _current_value(db, user_id, o if converted else
                                          await db.financial_accounts.find_one({"id": o["id"]}, {"_id": 0}),
                                          date_type.today().isoformat(), converted)
    return {"lines": lines, "total": total, "missing": missing, "converted": converted,
            "your_other_investment_accounts": others}


class Upload(BaseModel):
    file_base64: str
    password: str = Field(default="", max_length=64)      # used in memory only


@cas_router.post("/preview")
async def preview(body: Upload, current_user: dict = Depends(get_current_user)):
    require_feature(current_user, "statements", "Importing investment statements is part of Premium.")
    db = get_db()
    try:
        pdf = base64.b64decode(body.file_base64.split(",")[-1], validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="That file couldn't be read.")
    if not pdf or len(pdf) > MAX_BYTES:
        raise HTTPException(status_code=400, detail="Please use a PDF under 15 MB.")
    try:
        parsed = read(pdf, body.password)
    except CASUnreadable:
        raise HTTPException(status_code=400, detail="Hymn couldn't open this statement. Check the password (the "
                                                    "one you set when requesting it; NSDL/CDSL use your PAN) "
                                                    "and that it's a CAMS, KFintech, NSDL or CDSL CAS.")
    if not parsed["holdings"]:
        raise HTTPException(status_code=400, detail="No investments found in this statement.")
    fingerprint = hashlib.sha256(json.dumps(_plain(parsed["holdings"]), sort_keys=True).encode()).hexdigest()
    p = await plan(db, current_user["id"], parsed)
    doc = {"id": str(uuid.uuid4()), "user_id": current_user["id"], "status": "preview", "source": parsed["source"],
           "period": parsed["period"], "investor": parsed["investor"], "fingerprint": fingerprint,
           "holdings": _plain(parsed["holdings"]), "warnings": parsed["warnings"],
           "created_at": datetime.now(timezone.utc).isoformat()}
    await db.cas_imports.insert_one(dict(doc))
    already = await db.cas_imports.find_one({"user_id": current_user["id"], "fingerprint": fingerprint,
                                             "status": "applied"}, {"_id": 1})
    return {"id": doc["id"], "source": doc["source"], "period": doc["period"], "investor": doc["investor"],
            "already_applied": bool(already), "warnings": doc["warnings"], **_plain(p),
            "note": "Values are market values on each valuation date, as printed. Nothing changes until you apply."}


def _new_account(user_id: str, h: dict, value: Decimal, converted: bool, source: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {"id": str(uuid.uuid4()), "user_id": user_id, "account_type": ACCOUNT_TYPE[h["kind"]],
            "name": h["name"][:120], "currency": "INR",
            # Users on the money book get the value as a CAS opening entry instead.
            "current_value": Decimal128(Decimal(0) if converted else value),
            "balance_as_of": now if converted else f"{h['valued_on']}T23:59:59+00:00",
            "liquidity_type": "illiquid" if h["kind"] == "nps" else "semi_liquid",
            "fixed_or_flexible": "flexible", "notes": f"From your {source} statement", "created_at": now,
            "updated_at": now}


class Apply(BaseModel):
    # holding key → an investment account you typed by hand that IS this holding
    links: Dict[str, str] = Field(default_factory=dict)
    # accounts you typed by hand that this statement replaces (e.g. one
    # "Mutual funds" total): their value goes to zero on the statement date
    replaces: List[str] = Field(default_factory=list)


@cas_router.post("/{import_id}/apply")
async def apply(import_id: str, body: Optional[Apply] = None, current_user: dict = Depends(get_current_user)):
    require_feature(current_user, "statements", "Importing investment statements is part of Premium.")
    body = body or Apply()
    db = get_db()
    uid = current_user["id"]
    imp = await db.cas_imports.find_one({"id": import_id, "user_id": uid}, {"_id": 0})
    if not imp:
        raise HTTPException(status_code=404, detail="Import not found")
    if imp["status"] == "applied" or await db.cas_imports.find_one(
            {"user_id": uid, "fingerprint": imp["fingerprint"], "status": "applied"}, {"_id": 1}):
        raise HTTPException(status_code=409, detail="This statement is already in your money book.")
    holdings = [{**h, "value": Decimal(h["value"]),
                 "units": _d(h.get("units")), "price": _d(h.get("price"))} for h in imp["holdings"]]
    keys = {h["key"] for h in holdings}
    chosen = list(body.links.values()) + body.replaces
    if len(set(chosen)) != len(chosen):
        raise HTTPException(status_code=400, detail="An account can be linked or replaced only once.")
    hand_typed = {a["id"]: a for a in await db.financial_accounts.find(
        {"user_id": uid, "id": {"$in": chosen}, "cas_key": {"$exists": False},
         "account_type": {"$in": list(ACCOUNT_TYPE.values())}}, {"_id": 0}).to_list(length=None)}
    if any(k not in keys for k in body.links) or any(a not in hand_typed for a in chosen):
        raise HTTPException(status_code=400, detail="Link or replace only your own investment accounts, "
                                                    "with holdings from this statement.")
    converted = (await ledger_sync.sync(db, uid))["converted"]
    on = max((h["valued_on"] for h in holdings), default=date_type.today().isoformat())
    for acct_id in body.replaces:
        acct = hand_typed[acct_id]
        value = await _current_value(db, uid, acct, on, converted)
        if converted and value:
            await ledger.record(db, uid, ledger.Draft(
                kind="revaluation", date=on, currency=acct.get("currency") or "INR", amount=str(-value),
                account_id=acct_id, description=f"Replaced by your {imp['source']} statement"),
                provenance="cas", evidence_ids=[f"cas:{import_id}"])
        elif not converted:
            await db.financial_accounts.update_one({"id": acct_id}, {"$set": {
                "current_value": Decimal128(Decimal(0)), "balance_as_of": f"{on}T23:59:59+00:00"}})
        await db.financial_accounts.update_one({"id": acct_id}, {"$set": {
            "replaced_by_cas": import_id, "notes": f"Replaced by your {imp['source']} statement ({on})"}})
    for key, acct_id in body.links.items():
        await db.financial_accounts.update_one({"id": acct_id}, {"$set": {"cas_key": key, "cas_source": imp["source"]}})
    p = await plan(db, uid, {**imp, "holdings": holdings})
    existing = await _accounts_by_key(db, uid)
    done = {"new": 0, "update": 0, "same": 0, "older": 0}
    for h, line in zip(holdings, p["lines"]):
        done[line["action"]] += 1
        if line["action"] in ("same", "older"):
            continue
        meta = {"cas_key": h["key"], "cas_source": imp["source"], "cas_valued_on": h["valued_on"],
                "cas_units": format(h["units"], "f") if h["units"] is not None else None,
                "cas_price": format(h["price"], "f") if h["price"] is not None else None,
                "cas_items": _plain(h.get("items")), "cas_import_id": import_id}
        desc = f"Market value from your {imp['source']} statement ({h['valued_on']})"
        if line["action"] == "new":
            acct = {**_new_account(uid, h, h["value"], converted, imp["source"]), **meta}
            await db.financial_accounts.insert_one(dict(acct))
            if converted and h["value"]:
                await ledger.record(db, uid, ledger.Draft(kind="opening_balance", date=h["valued_on"],
                                                          currency="INR", amount=str(h["value"]),
                                                          account_id=acct["id"], description=desc),
                                    provenance="cas", evidence_ids=[f"cas:{import_id}"])
            existing[h["key"]] = acct
            continue
        acct = existing[h["key"]]
        if converted:
            await ledger.record(db, uid, ledger.Draft(kind="revaluation", date=h["valued_on"], currency="INR",
                                                      amount=str(line["change"]), account_id=acct["id"],
                                                      description=desc),
                                provenance="cas", evidence_ids=[f"cas:{import_id}"])
            await db.financial_accounts.update_one({"id": acct["id"]}, {"$set": meta})
        else:
            await db.financial_accounts.update_one({"id": acct["id"]}, {"$set": {
                **meta, "current_value": Decimal128(h["value"]),
                "balance_as_of": f"{h['valued_on']}T23:59:59+00:00",
                "updated_at": datetime.now(timezone.utc).isoformat()}})
    await db.cas_imports.update_one({"id": import_id}, {"$set": {
        "status": "applied", "applied_at": datetime.now(timezone.utc).isoformat(), "result": done}})
    return {"applied": done, "linked": len(body.links), "replaced": len(body.replaces),
            "total": _plain(p["total"]), "missing": p["missing"]}


@cas_router.get("")
async def list_imports(current_user: dict = Depends(get_current_user)):
    rows = await get_db().cas_imports.find({"user_id": current_user["id"], "status": "applied"},
                                           {"_id": 0, "holdings": 0, "fingerprint": 0, "user_id": 0}) \
        .sort("created_at", -1).to_list(length=100)
    return rows


async def ensure_cas_indexes(db) -> None:
    await db.cas_imports.create_index([("user_id", 1), ("fingerprint", 1), ("status", 1)])
    await db.financial_accounts.create_index([("user_id", 1), ("cas_key", 1)])
