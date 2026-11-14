"""Statement → ledger: suggestions that learn, Xero-style.

For each statement line Hymn suggests what it is, in this order:

1. **Already recorded**: the same payment is already in the ledger (same
   bank/UPI reference, or same account, amount and direction within two
   days) → link the line as evidence, create nothing.
2. **Your own accounts**: a card payment or transfer whose other side is
   already in the ledger (e.g. the bank's debit when the card statement's
   payment was confirmed first) → already recorded. If the other side was
   confirmed as spending, offer to turn it into the transfer it really was.
3. **Your "always" rules**, then **what you confirmed before** for the same
   merchant on this account.
4. **Simple patterns** (card "payment received" → card bill, "salary" →
   salary).
5. **Well-known merchants** from Hymn's built-in list (free, no AI).
6. Otherwise one cheap AI guess per statement for the leftovers (each
   merchant asked about once per user), else uncategorised; Hymn learns
   from what you choose.

Nothing is written until the user confirms. Every confirmation teaches the
rule for that merchant; a correction replaces it; "always" makes it a rule.
The first statement confirmed for an account sets its opening balance, and
each confirmation reports whether the ledger now agrees with the statement's
closing balance.
"""
from __future__ import annotations

import re
import uuid
from collections import defaultdict
from datetime import date as date_type, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Literal, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from pymongo import ReplaceOne, UpdateOne

import categories
import ledger
import ledger_sync
import life_objects
import merchant_directory
import statements_ai
from claude_client import AssistantUnavailable
from deps import get_current_user, get_db
from statements import money, statements_router

DUPLICATE_DAYS = 2
TRANSFER_DAYS = 5
_STOPWORDS = frozenset({
    "UPI", "NEFT", "IMPS", "RTGS", "POS", "ATM", "ECOM", "ACH", "NACH", "MMT", "INB", "BIL", "BILLPAY",
    "TO", "FROM", "BY", "FOR", "THE", "AND", "OF", "TRF", "TRANSFER", "PAYMENT", "PAID", "PAY",
    "DR", "CR", "REF", "TXN", "INR", "RS", "PVT", "LTD", "LIMITED", "PRIVATE", "INDIA", "COM", "WWW",
    "OKAXIS", "OKICICI", "OKHDFCBANK", "OKSBI", "YBL", "IBL", "AXL", "PAYTM", "APL",
})
_SETTLEMENT_WORDS = re.compile(r"PAYMENT|RECEIVED|THANK|AUTOPAY|BBPS", re.I)
_SALARY_WORDS = re.compile(r"\bSAL(ARY)?\b", re.I)
_INTEREST_WORDS = re.compile(r"\bINT(EREST)?\b|INT\.PD|INT PD", re.I)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def merchant_key(description: str) -> str:
    """A stable key for "the same merchant": the first two meaningful words,
    ignoring payment-rail words, reference numbers and UPI handles."""
    words = []
    for token in re.split(r"[^A-Z]+", (description or "").upper()):
        if len(token) < 3 or token in _STOPWORDS or token.endswith("BANK"):
            continue
        if token not in words:
            words.append(token)
        if len(words) == 2:
            break
    return " ".join(words)


def _amount(value: Any) -> Optional[Decimal]:
    text = str(value or "").replace(",", "").strip()
    try:
        d = Decimal(text) if text else None
    except InvalidOperation:
        return None
    return d if d and d.is_finite() and d > 0 else None


def _days_apart(a: str, b: str) -> int:
    return abs((date_type.fromisoformat(a) - date_type.fromisoformat(b)).days)


def line_effect(line: dict, account: dict) -> Optional[Decimal]:
    """The signed posting this line makes on its own account (debit-positive
    ledger sign), or None if the line has no single amount."""
    debit, credit = _amount(line.get("debit")), _amount(line.get("credit"))
    if (debit is None) == (credit is None):
        return None
    # Debit column = money out of (or more owed on) the account.
    return -debit if debit is not None else credit


def _real_accounts_of_type(accounts: Dict[str, dict], types) -> List[dict]:
    return [a for a in accounts.values() if a.get("account_type") in types]


def find_rule(rules: Dict[tuple, dict], key: str, account_id: str, direction: str) -> Optional[dict]:
    """Exact merchant key first; otherwise the most-confirmed rule sharing its
    first word (descriptions vary: "ZOMATO LTD" vs "ZOMATO ORDER 99")."""
    if not key:
        return None
    exact = rules.get((key, account_id, direction))
    if exact:
        return exact
    first = key.split(" ")[0]
    similar = [r for (k, acct, d), r in rules.items()
               if acct == account_id and d == direction and k.split(" ")[0] == first]
    return max(similar, key=lambda r: (bool(r.get("always")), r.get("times_confirmed", 0)), default=None)


# ---------------------------------------------------------------------------
# Similar names and habits: learning beyond the exact merchant
# ---------------------------------------------------------------------------

# Words that say nothing about what a shop sells.
_GENERIC_WORDS = frozenset({
    "SRI", "SHRI", "SREE", "SHREE", "NEW", "STORE", "STORES", "SHOP", "SHOPPE", "ENTERPRISES", "ENTERPRISE",
    "TRADERS", "TRADING", "SERVICES", "SERVICE", "CENTRE", "CENTER", "AGENCIES", "AGENCY", "CORNER",
    "MART", "GENERAL", "COMPANY", "CORP", "CORPORATION", "INTERNATIONAL", "GROUP", "SONS", "BROTHERS",
    "BANGALORE", "BENGALURU", "MUMBAI", "DELHI", "CHENNAI", "HYDERABAD", "PUNE", "KOLKATA",
})
HABIT_WINDOW_DAYS = 120
HABIT_MIN_TIMES = 4
HABIT_SHARE = Decimal("0.75")
SIMILAR_SHARE = Decimal("0.66")


def _close(a: str, b: str) -> bool:
    """Same word, or one letter off for words of 5+ letters (KRISHA ~ KRISHNA)."""
    if a == b:
        return True
    if min(len(a), len(b)) < 5 or a[0] != b[0] or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    return any(long_[:i] + long_[i + 1:] == short for i in range(len(long_)))


def similar_category(key: str, rules: Dict[tuple, dict], direction: str) -> Optional[tuple]:
    """(category, example merchant) when the user's confirmed merchants that
    share a meaningful word with this one mostly agree, else None."""
    words = [w for w in key.split(" ") if w and w not in _GENERIC_WORDS]
    if not words:
        return None
    votes: Dict[str, int] = defaultdict(int)
    example: Dict[str, tuple] = {}
    for (k, _acct, d), r in rules.items():
        cat = r.get("category") or ""
        if d != direction or r.get("kind") != "expense" or not cat or cat.endswith(":uncategorised") or k == key:
            continue
        theirs = [w for w in k.split(" ") if w not in _GENERIC_WORDS]
        if any(_close(w, t) for w in words for t in theirs):
            weight = max(1, r.get("times_confirmed", 1))
            votes[cat] += weight
            if weight > example.get(cat, (0, ""))[0]:  # most-confirmed example
                example[cat] = (weight, k)
    if not votes:
        return None
    best = max(votes, key=votes.get)
    if Decimal(votes[best]) / sum(votes.values()) < SIMILAR_SHARE:
        return None
    return best, example[best][1]


def habit_category(amount: Decimal, day: str, history: List[dict]) -> Optional[dict]:
    """When the user often spends about this amount (±10%, at least ₹5) and
    usually files it the same way, that category; else None. ``history``
    rows: {date, amount, category} of confirmed, categorised spending."""
    start = (date_type.fromisoformat(day) - timedelta(days=HABIT_WINDOW_DAYS)).isoformat()
    band = max(amount * Decimal("0.10"), Decimal(5))
    near = [h for h in history if start <= h["date"] <= day and abs(h["amount"] - amount) <= band]
    if len({h["date"] for h in near}) < HABIT_MIN_TIMES:
        return None
    counts: Dict[str, int] = defaultdict(int)
    for h in near:
        counts[h["category"]] += 1
    best = max(counts, key=counts.get)
    if Decimal(counts[best]) / len(near) < HABIT_SHARE:
        return None
    return {"category": best, "times": counts[best], "since": min(h["date"] for h in near)}


def spending_history(transactions: List[dict], currency: str) -> List[dict]:
    """Confirmed, categorised spending (one row per category posting)."""
    out = []
    for tx in transactions:
        if tx["kind"] != "expense" or tx["currency"] != currency:
            continue
        for p in tx["postings"]:
            if p["account_id"].startswith("expense:") and not p["account_id"].endswith(":uncategorised"):
                out.append({"date": tx["date"], "amount": p["amount"], "category": p["account_id"]})
    return out


def _label(category: str) -> str:
    return category.split(":", 1)[-1].replace("_", " ")


def emi_match(amount: Decimal, day: str, loans: List[dict]) -> Optional[tuple]:
    """(loan object, schedule row) when an outgoing amount is a loan's EMI
    due within 10 days of this date (₹1 slack)."""
    for loan in loans:
        for row in loan["schedule"]:
            if abs(Decimal(row["emi"]) - amount) <= 1 and _days_apart(row["date"], day) <= 10:
                return loan, row
    return None


def suggest_line(line: dict, account: dict, accounts: Dict[str, dict], rules: Dict[tuple, dict],
                 transactions: List[dict], history: Optional[List[dict]] = None,
                 loans: Optional[List[dict]] = None) -> Dict[str, Any]:
    """Pure: one suggestion for one line."""
    effect = line_effect(line, account)
    base = {"n": line["n"], "date": line["date"], "description": line["description"],
            "debit": line.get("debit", ""), "credit": line.get("credit", "")}
    if effect is None or not _valid(line.get("date")):
        return {**base, "action": "skip", "confidence": "none",
                "why": "This line has no single amount or date; it can't be recorded."}
    amount = abs(effect)
    is_card = account.get("account_type") == "credit_card"
    out_of_account = effect < 0  # money out, or more owed on a card
    ref = (line.get("reference") or "").strip()

    # 1–2. Already recorded (same reference, or same movement on this account).
    for tx in transactions:
        if ref and ref in tx.get("references", []):
            return {**base, "action": "duplicate", "duplicate_of": tx["id"], "confidence": "matched",
                    "why": f"Same reference {ref} is already recorded ({tx['description'] or tx['kind']})."}
    for tx in transactions:
        if _days_apart(tx["date"], line["date"]) > DUPLICATE_DAYS:
            continue
        for p in tx["postings"]:
            if p["account_id"] == account["id"] and p["amount"] == effect:
                return {**base, "action": "duplicate", "duplicate_of": tx["id"], "confidence": "matched",
                        "why": f"Already recorded on {tx['date']}: {tx['description'] or tx['kind']}."}

    # A card payment whose bank side was confirmed as spending: offer the fix.
    if is_card and not out_of_account:
        for tx in transactions:
            if tx["kind"] != "expense" or _days_apart(tx["date"], line["date"]) > TRANSFER_DAYS:
                continue
            bank_leg = [p for p in tx["postings"] if p["account_id"] in accounts
                        and accounts[p["account_id"]].get("account_type") in ledger.ASSET_TYPES
                        and p["amount"] == -amount]
            if bank_leg:
                return {**base, "action": "merge", "kind": "card_settlement", "merge_with": tx["id"],
                        "counter_account_id": bank_leg[0]["account_id"], "confidence": "matched",
                        "why": f"Matches {accounts[bank_leg[0]['account_id']].get('name', 'a bank')} "
                               f"paying {amount} on {tx['date']}, recorded as spending. This is your "
                               f"card bill: record it as a card payment instead."}

    # 2b. A loan EMI: split into principal and interest from the schedule.
    if loans and effect < 0 and account.get("account_type") in ("bank", "cash"):
        hit = emi_match(-effect, line["date"], loans)
        if hit:
            loan, row = hit
            return {**base, "action": "create", "kind": "loan_payment", "counter_account_id": loan["account_id"],
                    "principal": row["principal"], "interest": row["interest"], "confidence": "loan",
                    "why": f"EMI {row['n']} of {len(loan['schedule'])} for {loan['name']}: "
                           f"{money(Decimal(row['principal']), account.get('currency', 'INR'))} principal, "
                           f"{money(Decimal(row['interest']), account.get('currency', 'INR'))} interest."}

    # 3. Rules and past confirmations for this merchant on this account.
    key = merchant_key(line["description"])
    rule = find_rule(rules, key, account["id"], "out" if out_of_account else "in")
    if rule:
        times = rule.get("times_confirmed", 0)
        label = rule["category"] or rule["kind"]
        return {**base, "action": "create", "kind": rule["kind"], "category": rule["category"],
                "counter_account_id": rule["counter_account_id"],
                "confidence": "rule" if rule.get("always") else "learned", "rule_id": rule["id"],
                "why": (f"Your rule: {rule['merchant_key']} → {label}." if rule.get("always")
                        else f"You chose {label} for {rule['merchant_key']} {times} "
                             f"time{'s' if times != 1 else ''} before.")}

    # 4. Simple patterns.
    banks = [a for a in _real_accounts_of_type(accounts, {"bank"}) if a.get("currency") == account.get("currency")]
    if is_card and not out_of_account:
        if _SETTLEMENT_WORDS.search(line["description"]):
            counter = banks[0]["id"] if len(banks) == 1 else None
            return {**base, "action": "create", "kind": "card_settlement", "counter_account_id": counter,
                    "confidence": "guess", "why": "Looks like a card bill payment."
                    + ("" if counter else " Pick the account it was paid from.")}
        return {**base, "action": "create", "kind": "refund", "category": "expense:uncategorised",
                "confidence": "guess", "why": "Money back on the card: looks like a refund."}
    if not out_of_account and _SALARY_WORDS.search(line["description"]):
        return {**base, "action": "create", "kind": "income", "category": "income:salary",
                "confidence": "guess", "why": "Looks like salary."}
    if not out_of_account and _INTEREST_WORDS.search(line["description"]):
        return {**base, "action": "create", "kind": "income", "category": "income:interest",
                "confidence": "guess", "why": "Looks like interest."}

    # 5. Well-known merchants.
    known = merchant_directory.lookup(line["description"]) if out_of_account else None
    if known:
        category, keyword = known
        return {**base, "action": "create", "kind": "expense", "category": f"expense:{category}",
                "confidence": "known",
                "why": f"{keyword.title()} is usually {category.replace('_', ' ')}. Change it once and Hymn learns."}

    # 6. Names like ones the user already filed (UDUPI FOOD KITCHEN ~ UDUPI NAIVEDHYA).
    if out_of_account:
        similar = similar_category(key, rules, "out")
        if similar:
            category, example = similar
            return {**base, "action": "create", "kind": "expense", "category": category,
                    "confidence": "similar",
                    "why": f"Similar to {example}, which you marked {_label(category)}."}

    # 7. Habits: about the same amount, filed the same way, again and again.
    if out_of_account and history:
        habit = habit_category(-effect, line["date"], history)
        if habit:
            when = date_type.fromisoformat(habit["since"]).strftime("%-d %b")
            return {**base, "action": "create", "kind": "expense", "category": habit["category"],
                    "confidence": "habit",
                    "why": f"You often spend about {money(-effect, account.get('currency', 'INR'))} on "
                           f"{_label(habit['category'])}: {habit['times']} times since {when}."}

    # 8. Unknown.
    if out_of_account:
        return {**base, "action": "create", "kind": "expense", "category": "expense:uncategorised",
                "confidence": "new", "why": "New to Hymn. Pick a category once and Hymn learns it."}
    return {**base, "action": "create", "kind": "income", "category": "income:uncategorised",
            "confidence": "new", "why": "New to Hymn. Pick what this is once and Hymn learns it."}


def draft_for(decision: dict, line: dict, account: dict, currency: str) -> ledger.Draft:
    """Turn a confirmed decision into a ledger draft from this account's side."""
    effect = line_effect(line, account)
    amount = str(abs(effect))
    kind = decision["kind"]
    acct = account["id"]
    counter = decision.get("counter_account_id")
    common = {"kind": kind, "date": line["date"], "currency": currency,
              "description": line["description"], "amount": amount}
    if kind == "expense":
        return ledger.Draft(**common, from_account_id=acct, category=decision.get("category"))
    if kind in ("income", "gift"):
        return ledger.Draft(**common, to_account_id=acct, category=decision.get("category"))
    if kind == "refund":
        return ledger.Draft(**common, to_account_id=acct, category=decision.get("category"))
    if kind == "card_settlement":
        if account.get("account_type") == "credit_card":
            return ledger.Draft(**common, from_account_id=counter, to_account_id=acct)
        return ledger.Draft(**common, from_account_id=acct, to_account_id=counter)
    if kind == "loan_payment":
        principal = Decimal(str(decision.get("principal") or 0))
        interest = Decimal(abs(effect)) - principal  # whatever isn't principal is interest
        return ledger.Draft(kind=kind, date=line["date"], currency=currency, description=line["description"],
                            from_account_id=acct, to_account_id=counter, principal=str(principal),
                            interest=str(max(interest, Decimal(0))))
    if kind in ("transfer", "investment", "redemption"):
        if effect < 0:
            return ledger.Draft(**common, from_account_id=acct, to_account_id=counter)
        return ledger.Draft(**common, from_account_id=counter, to_account_id=acct)
    raise ledger.LedgerError(f"kind {kind!r} can't be confirmed from a statement line")


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------

async def _load_rules(db, user_id: str) -> Dict[tuple, dict]:
    rows = await db.match_rules.find({"user_id": user_id}, {"_id": 0}).to_list(length=None)
    return {(r["merchant_key"], r["account_id"], r["direction"]): r for r in rows}


def learn(rules: Dict[tuple, dict], user_id: str, key: str, account_id: str, direction: str,
          decision: dict, always: Optional[bool]) -> Optional[dict]:
    """Update ``rules`` in memory with what the user just confirmed and return
    the rule to save. A correction replaces what Hymn had learned."""
    if not key or decision["kind"] == "loan_payment":  # EMIs come from the schedule, not a rule
        return None
    result = {"kind": decision["kind"], "category": decision.get("category"),
              "counter_account_id": decision.get("counter_account_id")}
    now = _now()
    existing = rules.get((key, account_id, direction))
    if existing is None:
        rule = {"id": str(uuid.uuid4()), "user_id": user_id, "merchant_key": key, "account_id": account_id,
                "direction": direction, **result, "times_confirmed": 1, "always": bool(always),
                "created_at": now, "updated_at": now}
    else:
        same = all(existing.get(k) == v for k, v in result.items())
        rule = {**existing, **result, "updated_at": now,
                "times_confirmed": existing.get("times_confirmed", 0) + 1 if same else 1}
        if always is not None:
            rule["always"] = always
    rules[(key, account_id, direction)] = rule
    return rule


async def _statement_and_account(db, user_id: str, import_id: str):
    doc = await db.statement_imports.find_one({"id": import_id, "user_id": user_id}, {"_id": 0})
    if doc is None:
        raise HTTPException(status_code=404, detail="Statement not found")
    if doc.get("status") not in ("ready", "needs_review", "confirmed"):
        raise HTTPException(status_code=409, detail="This statement hasn't been read yet.")
    accounts = await ledger.real_accounts_for(db, user_id)
    account = accounts.get(doc.get("account_id") or "")
    return doc, accounts, account


def _account_suggestions(doc: dict, accounts: Dict[str, dict]) -> List[str]:
    meta = doc.get("metadata") or {}
    want_card = meta.get("account_kind") in ("credit_card",)
    hints = [h.lower() for h in (meta.get("account_last4"), (meta.get("institution") or "").split(" ")[0]) if h]
    scored = []
    for a in accounts.values():
        if a.get("currency") != meta.get("currency"):
            continue
        if (a.get("account_type") == "credit_card") != want_card:
            continue
        score = sum(1 for h in hints if h in (a.get("name") or "").lower())
        scored.append((score, a["id"]))
    return [aid for _, aid in sorted(scored, key=lambda x: -x[0])]


async def _transactions_near(db, user_id: str, doc: dict) -> List[dict]:
    meta = doc.get("metadata") or {}
    dates = [l["date"] for l in doc.get("lines", []) if _valid(l.get("date"))]
    if not dates:
        return []
    lo = (date_type.fromisoformat(min(dates)) - timedelta(days=TRANSFER_DAYS)).isoformat()
    hi = (date_type.fromisoformat(max(dates)) + timedelta(days=TRANSFER_DAYS)).isoformat()
    return [t for t in await ledger.load_transactions(db, user_id)
            if lo <= t["date"] <= hi and t["currency"] == meta.get("currency")]


def _valid(d: Any) -> bool:
    try:
        date_type.fromisoformat(str(d))
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

class LinkRequest(BaseModel):
    account_id: str


@statements_router.post("/{import_id}/link")
async def link_account(import_id: str, body: LinkRequest, current_user: dict = Depends(get_current_user)):
    db = get_db()
    doc, accounts, _ = await _statement_and_account(db, current_user["id"], import_id)
    account = accounts.get(body.account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    if account.get("currency") != (doc.get("metadata") or {}).get("currency"):
        raise HTTPException(status_code=400, detail="That account is in a different currency.")
    if doc.get("confirmed_lines") and doc.get("account_id") != account["id"]:
        raise HTTPException(status_code=409, detail="Some lines are already confirmed for another account, "
                                                    "so this statement's account can't be changed.")
    await db.statement_imports.update_one({"id": import_id}, {"$set": {"account_id": account["id"]}})
    return {"account_id": account["id"]}


@statements_router.get("/{import_id}/suggestions")
async def suggestions(import_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    doc, accounts, account = await _statement_and_account(db, current_user["id"], import_id)
    if account is None:
        return {"account_id": None, "account_suggestions": _account_suggestions(doc, accounts), "lines": []}
    # Spends recorded the old way since conversion must be in the ledger,
    # or their statement lines would look new and count twice.
    await ledger_sync.sync(db, current_user["id"])
    rules = await _load_rules(db, current_user["id"])
    txs = await _transactions_near(db, current_user["id"], doc)
    history = spending_history(await ledger.load_transactions(db, current_user["id"]), account.get("currency"))
    done = set(doc.get("confirmed_lines", []))
    loans = []
    for o in await db.life_objects.find({"user_id": current_user["id"], "type": "liability",
                                         "account_id": {"$ne": None}}, {"_id": 0}).to_list(length=None):
        rows = life_objects.loan_schedule(o)
        if rows and o["account_id"] in accounts:
            loans.append({"name": o["name"], "account_id": o["account_id"], "schedule": rows})
    suggested = [suggest_line(l, account, accounts, rules, txs, history, loans)
                 for l in doc.get("lines", []) if l["n"] not in done]
    await _add_ai_guesses(db, current_user["id"], suggested)
    lines = [_with_nested(s) for s in suggested]
    return {"account_id": account["id"], "account_suggestions": [], "confirmed_lines": sorted(done),
            "lines": lines}


async def _add_ai_guesses(db, user_id: str, suggested: List[dict]) -> None:
    """Lines nothing else recognised get one AI guess per merchant, ever.

    Guesses are remembered per user by merchant and direction, so the same
    merchant on ten cards or twelve months of statements is asked about once,
    and each statement sends only merchants never seen before, one line per
    merchant. If the AI is unavailable nothing is remembered and the lines
    stay uncategorised.
    """
    new = [s for s in suggested if s.get("confidence") == "new"]
    keyed = {}
    for s in new:
        key = merchant_key(s["description"])
        if key:  # no merchant words at all: nothing to guess from
            keyed.setdefault((key, "out" if s["kind"] == "expense" else "in"), []).append(s)
    if not keyed:
        return
    known = {(g["merchant_key"], g["direction"]): g["category"] async for g in db.merchant_guesses.find(
        {"user_id": user_id, "merchant_key": {"$in": sorted({k for k, _ in keyed})}})}
    unseen = [k for k in keyed if k not in known]
    if unseen:
        ask = [{"n": i, "description": keyed[k][0]["description"], "direction": k[1]} for i, k in enumerate(unseen)]
        try:
            fresh = await statements_ai.guess_categories(
                ask, categories.SUGGESTIBLE_EXPENSE, categories.SUGGESTIBLE_INCOME)
        except AssistantUnavailable:
            fresh = None
        if fresh is not None:
            now = datetime.now(timezone.utc).isoformat()
            for i, k in enumerate(unseen):
                known[k] = fresh.get(i, "")  # "" = asked, no confident guess
            await db.merchant_guesses.bulk_write([
                UpdateOne({"user_id": user_id, "merchant_key": k[0], "direction": k[1]},
                          {"$set": {"category": known[k], "updated_at": now}}, upsert=True)
                for k in unseen])
    for k, lines in keyed.items():
        guess = known.get(k)
        if guess:
            for s in lines:
                s.update(category=guess, confidence="ai",
                         why=f"Hymn's guess: {guess.split(':')[1].replace('_', ' ')}. "
                             f"Confirm or change it once and Hymn learns.")


_LINE_FIELDS = ("n", "date", "description", "debit", "credit")


def _with_nested(row: dict) -> dict:
    """The app reads the suggestion as a nested ``suggestion`` object; keep
    the flat fields too."""
    return {**row, "suggestion": {k: v for k, v in row.items() if k not in _LINE_FIELDS}}


class Decision(BaseModel):
    n: int
    action: Literal["create", "duplicate", "merge", "skip"]
    kind: Optional[str] = None
    category: Optional[str] = None
    counter_account_id: Optional[str] = None
    duplicate_of: Optional[str] = None
    merge_with: Optional[str] = None
    always: Optional[bool] = None
    principal: Optional[str] = None     # loan_payment: the principal part


class ConfirmRequest(BaseModel):
    decisions: List[Decision] = Field(min_length=1, max_length=2000)


async def _ensure_opening(db, user_id: str, doc: dict, account: dict) -> bool:
    """The first statement confirmed for an account sets its opening balance."""
    meta = doc.get("metadata") or {}
    opening = _amount(meta.get("opening_balance"))
    if opening is None:  # missing or zero: nothing to set
        return False
    if await db.ledger_transactions.find_one(
            {"user_id": user_id, "status": "posted", "postings.account_id": account["id"]}, {"_id": 1}):
        return False
    first = min((l["date"] for l in doc.get("lines", []) if _valid(l.get("date"))),
                default=meta.get("period_start"))
    start = meta.get("period_start") if _valid(meta.get("period_start")) else first
    if not _valid(start):
        return False
    await ledger.record(db, user_id, ledger.Draft(
        kind="opening_balance", date=start, currency=account["currency"], amount=str(opening),
        account_id=account["id"], description=f"Opening balance from statement: {doc.get('filename', '')}"),
        provenance="document", evidence_ids=[f"stmt:{doc['id']}:opening"])
    return True


async def _balance_check(db, user_id: str, doc: dict, account: dict) -> Dict[str, Any]:
    meta = doc.get("metadata") or {}
    closing = _amount(meta.get("closing_balance"))
    end = meta.get("period_end") if _valid(meta.get("period_end")) else None
    if closing is None or end is None:
        return {"available": False}
    rows = await ledger.balances(db, user_id, end)
    row = next((r for r in rows if r["account_id"] == account["id"]), None)
    ledger_balance = Decimal(row["balance"]) if row else Decimal(0)
    gap = abs(ledger_balance - closing)
    return {"available": True, "ledger_balance": format(ledger_balance, "f"),
            "statement_closing": format(closing, "f"), "matches": gap <= Decimal("1.00")}


@statements_router.post("/{import_id}/confirm")
async def confirm(import_id: str, body: ConfirmRequest, current_user: dict = Depends(get_current_user)):
    """Confirm lines in a few batch writes, whatever the statement's size:
    everything is validated and assembled in memory first, so a bad line
    writes nothing."""
    db = get_db()
    user_id = current_user["id"]
    doc, accounts, account = await _statement_and_account(db, user_id, import_id)
    if account is None:
        raise HTTPException(status_code=409, detail="Link this statement to an account first.")
    currency = (doc.get("metadata") or {}).get("currency")
    lines = {l["n"]: l for l in doc.get("lines", [])}
    done = set(doc.get("confirmed_lines", []))
    rules = await _load_rules(db, user_id)
    counts = {"created": 0, "linked_to_existing": 0, "merged": 0, "skipped": 0}

    todo = [d for d in body.decisions if d.n not in done]
    for d in body.decisions:
        if d.n not in lines:
            raise HTTPException(status_code=400, detail=f"Line {d.n} isn't in this statement.")
    referenced = {d.duplicate_of for d in todo if d.action == "duplicate"} | \
                 {d.merge_with for d in todo if d.action == "merge"}
    existing = {t["id"]: t for t in await db.ledger_transactions.find(
        {"user_id": user_id, "status": "posted", "id": {"$in": [r for r in referenced if r]}},
        {"_id": 0, "id": 1, "evidence_ids": 1}).to_list(length=None)}

    new_txs, voided, evidence_links, changed_rules, confirmed = [], [], [], {}, []
    for d in todo:
        if d.n in confirmed:
            continue
        line = lines[d.n]
        evidence = f"stmt:{import_id}:{d.n}"
        ref = (line.get("reference") or "").strip()
        if d.action == "skip":
            counts["skipped"] += 1
        elif d.action == "duplicate":
            if d.duplicate_of not in existing:
                raise HTTPException(status_code=400, detail=f"Line {d.n}: that entry no longer exists.")
            evidence_links.append((d.duplicate_of, evidence, ref))
            counts["linked_to_existing"] += 1
        else:
            decision = d.model_dump()
            evidence_ids = [evidence]
            if d.action == "merge":
                if d.merge_with not in existing:
                    raise HTTPException(status_code=400, detail=f"Line {d.n}: that entry no longer exists.")
                voided.append(d.merge_with)
                evidence_ids += existing[d.merge_with].get("evidence_ids", [])
                counts["merged"] += 1
            else:
                counts["created"] += 1
            try:
                new_txs.append(ledger.build_transaction(
                    user_id, draft_for(decision, line, account, currency), accounts,
                    provenance="user", evidence_ids=evidence_ids, references=[ref] if ref else None))
            except ledger.LedgerError as exc:
                raise HTTPException(status_code=400, detail=f"Line {d.n}: {exc}")
            direction = "out" if line_effect(line, account) < 0 else "in"
            key = merchant_key(line["description"])
            # Strengthen the rule this line matched rather than starting another.
            known = find_rule(rules, key, account["id"], direction)
            rule = learn(rules, user_id, known["merchant_key"] if known else key, account["id"],
                         direction, decision, d.always)
            if rule:
                changed_rules[rule["id"]] = rule
        confirmed.append(d.n)

    # Writes: a handful of batch operations.
    opening_created = await _ensure_opening(db, user_id, doc, account) if confirmed else False
    if voided:
        await db.ledger_transactions.update_many(
            {"id": {"$in": voided}, "user_id": user_id},
            {"$set": {"status": "void", "voided_at": _now(), "void_reason": "replaced by card payment"}})
    if evidence_links:
        await db.ledger_transactions.bulk_write([
            UpdateOne({"id": tx_id, "user_id": user_id},
                      {"$addToSet": {"evidence_ids": ev, **({"references": ref} if ref else {})}})
            for tx_id, ev, ref in evidence_links
        ])
    if new_txs:
        await db.ledger_transactions.insert_many([ledger.storable(t) for t in new_txs])
    if changed_rules:
        await db.match_rules.bulk_write([
            ReplaceOne({"id": r["id"]}, r, upsert=True) for r in changed_rules.values()
        ])
    done |= set(confirmed)
    update: Dict[str, Any] = {"$addToSet": {"confirmed_lines": {"$each": confirmed}},
                              "$set": {"updated_at": _now()}}
    if done >= set(lines):
        update["$set"]["status"] = "confirmed"
    await db.statement_imports.update_one({"id": import_id}, update)
    return {**counts, "opening_balance_set": opening_created,
            "remaining": len(set(lines) - done),
            "balance_check": await _balance_check(db, user_id, doc, account)}


@statements_router.get("/rules/all")
async def list_rules(current_user: dict = Depends(get_current_user)):
    return await get_db().match_rules.find(
        {"user_id": current_user["id"]}, {"_id": 0}).sort("times_confirmed", -1).to_list(length=1000)


class RuleUpdate(BaseModel):
    always: bool


@statements_router.patch("/rules/{rule_id}")
async def update_rule(rule_id: str, body: RuleUpdate, current_user: dict = Depends(get_current_user)):
    r = await get_db().match_rules.update_one(
        {"id": rule_id, "user_id": current_user["id"]}, {"$set": {"always": body.always, "updated_at": _now()}})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"detail": "Updated"}


@statements_router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: str, current_user: dict = Depends(get_current_user)):
    r = await get_db().match_rules.delete_one({"id": rule_id, "user_id": current_user["id"]})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"detail": "Deleted"}


async def ensure_matching_indexes(db) -> None:
    await db.merchant_guesses.create_index(
        [("user_id", 1), ("merchant_key", 1), ("direction", 1)], unique=True)
    await db.match_rules.create_index(
        [("user_id", 1), ("merchant_key", 1), ("account_id", 1), ("direction", 1)], unique=True)
