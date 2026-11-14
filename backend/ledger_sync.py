"""Keeps the ledger in step with the old finance records after conversion.

The one-time conversion (``ledger_conversion``) copied accounts and events
into the ledger. The app still records money the old way (check-in spends,
commitment payments, reconciliation), so without this module the ledger
would go stale the day after conversion.

``sync`` recomputes what the ledger *should* hold from the old records,
using the very same rules as the conversion (``plan_conversion``), and
changes only the difference:

* a new event that counts → a new entry (or, if a statement already
  recorded the same payment, the event is attached to that entry instead of
  counting it twice);
* an event whose amount, date or account changed → its entry is replaced;
* an event that was rejected or voided → its entry is voided;
* an account balance typed in again → its opening balance is redone so the
  ledger agrees with it.

Only entries the system derived (provenance ``conversion`` or ``event``)
are ever changed. Statement lines, a person's own entries, and anything a
person voided are left alone. Users who never converted are not touched.
Writes are idempotent (entry ids are derived from their content), so two
syncs running at once cannot double-count.
"""
from __future__ import annotations

import uuid
from datetime import date as date_type, datetime, timezone
from typing import Dict, List, Optional

from pymongo import UpdateOne
from pymongo.errors import BulkWriteError

import ledger
import ledger_conversion

DERIVED = ("conversion", "event")
SAME_PAYMENT_DAYS = 2
_NS = uuid.UUID("4f1c2f0e-7a51-4c3e-9a0e-1d1b6f0c9b21")


def _signature(kind: str, date: str, currency: str, postings: List[dict]) -> tuple:
    return (kind, date, currency,
            tuple(sorted((p["account_id"], format(ledger.to_decimal(p["amount"]).quantize(ledger.CENT), "f"))
                         for p in postings)))


def _real_posting(postings: List[dict], real: Dict[str, dict]) -> Optional[dict]:
    return next((p for p in postings if p["account_id"] in real), None)


def _key_of_existing(tx: dict, real: Dict[str, dict]) -> Optional[tuple]:
    if tx["kind"] == "opening_balance" and not tx.get("evidence_ids"):
        p = _real_posting(tx["postings"], real)
        return ("opening", p["account_id"]) if p else None
    ids = tx.get("evidence_ids") or []
    return ("event", ids[0]) if ids else None


def _days_apart(a: str, b: str) -> int:
    return abs((date_type.fromisoformat(a) - date_type.fromisoformat(b)).days)


def plan_sync(accounts: List[dict], events: List[dict], transactions: List[dict], today: str) -> dict:
    """Pure: what to insert, void and link. ``transactions`` are loaded
    ledger transactions (any status, Decimal amounts)."""
    real = {a["id"]: a for a in accounts}
    event_ids = {e["id"] for e in events}

    # Accounts whose opening came from a statement or a person: their typed
    # snapshot no longer sets the opening balance.
    opened_elsewhere = {
        p["account_id"]
        for tx in transactions
        if tx["status"] == "posted" and tx["kind"] == "opening_balance" and tx.get("provenance") not in DERIVED
        for p in tx["postings"] if p["account_id"] in real
    }

    desired: Dict[tuple, dict] = {}
    for d in ledger_conversion.plan_conversion(accounts, events, [], today)["drafts"]:
        draft = d["draft"]
        if draft.kind == "opening_balance":
            if draft.account_id in opened_elsewhere:
                continue
            key = ("opening", draft.account_id)
        else:
            key = ("event", d["evidence_ids"][0])
        postings = ledger.build_postings(draft, real)
        desired[key] = {"draft": draft, "evidence_ids": d["evidence_ids"],
                        "signature": _signature(draft.kind, draft.date, draft.currency, postings)}

    derived_posted: Dict[tuple, List[dict]] = {}
    voided_by_person = set()
    claimed = set()  # event ids already attached to a statement / person entry
    free_others = []  # posted non-derived entries no event is attached to yet
    for tx in transactions:
        if tx.get("provenance") in DERIVED:
            key = _key_of_existing(tx, real)
            if key is None:
                continue
            if tx["status"] == "posted" and any(str(i).startswith("stmt:") for i in tx.get("evidence_ids") or []):
                # A statement confirmed this entry: it stays, whatever the
                # old record says now.
                if key[0] == "event":
                    claimed.add(key[1])
                continue
            if tx["status"] == "posted":
                derived_posted.setdefault(key, []).append(tx)
            elif tx.get("voided_by") != "sync":
                voided_by_person.add(key)
        elif tx["status"] == "posted":
            mine = [i for i in tx.get("evidence_ids") or [] if i in event_ids]
            claimed.update(mine)
            if not mine:
                free_others.append(tx)

    inserts, voids, links = [], [], []
    for key, want in desired.items():
        have = derived_posted.pop(key, [])
        keep = next((t for t in have if _signature(t["kind"], t["date"], t["currency"], t["postings"])
                     == want["signature"]), None)
        voids.extend(t["id"] for t in have if t is not keep)
        if keep or key in voided_by_person or (key[0] == "event" and key[1] in claimed):
            continue
        if key[0] == "event":
            same = _same_payment(want, free_others, real)
            if same is not None:
                free_others.remove(same)
                links.append((same["id"], key[1]))
                continue
        inserts.append(want)
    # Derived entries nothing asks for any more (rejected / voided events,
    # duplicates).
    for txs in derived_posted.values():
        voids.extend(t["id"] for t in txs)
    return {"inserts": inserts, "voids": voids, "links": links}


def _same_payment(want: dict, candidates: List[dict], real: Dict[str, dict]) -> Optional[dict]:
    """A statement / person entry for the same payment: same account and
    signed amount, within two days."""
    draft = want["draft"]
    target = _real_posting(ledger.build_postings(draft, real), real)
    for tx in candidates:
        p = _real_posting(tx["postings"], real)
        if (p and tx["kind"] != "opening_balance" and p["account_id"] == target["account_id"]
                and p["amount"] == target["amount"] and _days_apart(tx["date"], draft.date) <= SAME_PAYMENT_DAYS):
            return tx
    return None


async def is_converted(db, user_id: str) -> bool:
    return bool(await db.ledger_transactions.find_one({"user_id": user_id, "provenance": "conversion"}, {"_id": 1}))


async def sync(db, user_id: str) -> dict:
    """Bring the ledger up to date with the old records. Cheap no-op for
    users who haven't converted."""
    import request_cache

    remembered = request_cache.get(("sync", user_id))
    if remembered is not None:
        return remembered
    result = await _sync(db, user_id)
    if result["created"] or result["voided"] or result["linked"]:
        request_cache.forget(user_id)
    request_cache.put(("sync", user_id), result)
    return result


async def _sync(db, user_id: str) -> dict:
    if not await is_converted(db, user_id):
        return {"converted": False, "created": 0, "voided": 0, "linked": 0}
    accounts = await db.financial_accounts.find({"user_id": user_id}, {"_id": 0}).to_list(length=None)
    events = await db.financial_events.find({"user_id": user_id}, {"_id": 0}).to_list(length=None)
    txs = [ledger._load(t) for t in await db.ledger_transactions.find({"user_id": user_id}).to_list(length=None)]
    today = datetime.now(timezone.utc).date().isoformat()
    plan = plan_sync(accounts, events, txs, today)
    real = {a["id"]: a for a in accounts}
    now = ledger._now()

    if plan["voids"]:
        await db.ledger_transactions.update_many(
            {"user_id": user_id, "id": {"$in": plan["voids"]}, "status": "posted",
             "provenance": {"$in": list(DERIVED)}},
            {"$set": {"status": "void", "voided_by": "sync", "voided_at": now, "updated_at": now}})
    if plan["links"]:
        await db.ledger_transactions.bulk_write([
            UpdateOne({"user_id": user_id, "id": tx_id}, {"$addToSet": {"evidence_ids": ev_id},
                                                          "$set": {"updated_at": now}})
            for tx_id, ev_id in plan["links"]])
    created = 0
    by_id = {t["id"]: t for t in txs}
    docs, revive = [], []
    for want in plan["inserts"]:
        tx = ledger.build_transaction(user_id, want["draft"], real, provenance="event",
                                      evidence_ids=want["evidence_ids"])
        # Same content → same id, so concurrent syncs can't insert twice.
        tx["id"] = str(uuid.uuid5(_NS, f"{user_id}|{want['signature']}|{want['evidence_ids']}"))
        if tx["id"] in by_id:  # the same entry existed before and sync voided it
            revive.append(tx["id"])
        else:
            docs.append(ledger.storable(tx))
    if revive:
        result = await db.ledger_transactions.update_many(
            {"user_id": user_id, "id": {"$in": revive}, "status": "void", "voided_by": "sync"},
            {"$set": {"status": "posted", "updated_at": now}, "$unset": {"voided_by": "", "voided_at": ""}})
        created += result.modified_count
    if docs:
        try:
            result = await db.ledger_transactions.insert_many(docs, ordered=False)
            created += len(result.inserted_ids)
        except BulkWriteError as exc:  # another sync got there first
            if any(e.get("code") != 11000 for e in exc.details.get("writeErrors", [])):
                raise
            created += exc.details.get("nInserted", 0)
    return {"converted": True, "created": created, "voided": len(plan["voids"]), "linked": len(plan["links"])}
