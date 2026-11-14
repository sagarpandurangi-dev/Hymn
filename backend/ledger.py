"""Double-entry ledger: the single source of truth for what money did.

Model
-----
* A **transaction** is one economic event (a dinner, a salary, a card bill
  payment, an EMI). It holds its **postings** inline, so a transaction and
  its postings are written atomically in one document.
* Each posting moves a signed amount on one account. Postings of a
  transaction always sum to zero — the invariant that makes double counting
  impossible.
* Sign convention (debit positive):
    asset +   = more money          liability − = more owed
    expense + = cost incurred       income −    = income earned
    equity −  = opening balances
* **Real accounts** are the user's ``financial_accounts`` (bank, cash, card,
  loan, FD, fund…), referenced by their id. **Nominal accounts** are system
  codes such as ``expense:uncategorised`` or ``income:salary``; user
  categories will join them as ``category:<id>``.
* Each posting has a ``date``: when it hit that account. The transaction
  ``date`` is when the economic event happened.

Views
-----
* **Accrual**: an expense counts on the transaction date, whoever paid.
* **Cash**: an expense counts when money leaves an asset account. Expenses
  charged to a liability (credit card) count when that card is paid,
  matched to the oldest unpaid charges first (FIFO). Refunds on a card
  cancel charges; overpayment is credit that later charges consume.

This module is built alongside the existing finance engine. Nothing in the
app reads it until the switch-over (plan step A3).
"""
from __future__ import annotations

import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date as date_type, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Literal, Optional

from bson.decimal128 import Decimal128
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from deps import get_current_user, get_db

ledger_router = APIRouter(prefix="/ledger", tags=["ledger"])

ZERO = Decimal(0)
CENT = Decimal("0.01")

ASSET_TYPES = frozenset({
    "cash", "bank", "fixed_deposit", "recurring_deposit", "mutual_fund",
    "stock", "bond", "crypto", "gold", "real_estate", "other_asset",
    "epf", "ppf", "nps", "deposit_given", "money_lent",
})
LIABILITY_TYPES = frozenset({
    "credit_card", "personal_loan", "home_loan", "vehicle_loan", "other_liability", "money_borrowed",
})
LOAN_TYPES = frozenset({"personal_loan", "home_loan", "vehicle_loan", "other_liability", "money_borrowed"})

# Categories come from the two-level tree in ``categories`` (older flat keys
# stay valid); user-defined ones will join as ``category:<id>``.
import categories as _categories  # noqa: E402

EXPENSE_CATEGORIES = tuple(_categories.EXPENSE)
INCOME_CATEGORIES = tuple(_categories.INCOME)

NOMINAL_ACCOUNTS: Dict[str, str] = {
    **{f"expense:{c}": "expense" for c in EXPENSE_CATEGORIES},
    **{f"income:{c}": "income" for c in INCOME_CATEGORIES},
    "equity:opening": "equity",
}

KINDS = (
    "expense", "income", "gift", "transfer", "investment", "redemption",
    "card_settlement", "loan_payment", "refund", "opening_balance", "borrowing",
)
# Kinds whose money only moves between the user's own accounts.
OWN_ACCOUNT_KINDS = frozenset({"transfer", "investment", "redemption", "card_settlement"})


class LedgerError(ValueError):
    """A transaction that would break the ledger's rules."""


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def to_decimal(value: Any, field: str = "amount") -> Decimal:
    if isinstance(value, Decimal128):
        return value.to_decimal()
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise LedgerError(f"{field} must be a number")
    if not d.is_finite():
        raise LedgerError(f"{field} must be a finite number")
    return d


def positive(value: Any, field: str) -> Decimal:
    d = to_decimal(value, field)
    if d <= 0:
        raise LedgerError(f"{field} must be greater than zero")
    return d


def valid_date(value: Any, field: str = "date") -> str:
    try:
        return date_type.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        raise LedgerError(f"{field} must be YYYY-MM-DD")


def account_class(account_id: str, real_accounts: Dict[str, dict]) -> str:
    """asset | liability | expense | income | equity, or raise."""
    if account_id in NOMINAL_ACCOUNTS:
        return NOMINAL_ACCOUNTS[account_id]
    acct = real_accounts.get(account_id)
    if acct is None:
        raise LedgerError(f"Unknown account {account_id!r}")
    t = acct.get("account_type")
    if t in ASSET_TYPES:
        return "asset"
    if t in LIABILITY_TYPES:
        return "liability"
    raise LedgerError(f"Account {account_id!r} has unsupported type {t!r}")


def check_balanced(postings: List[dict]) -> None:
    if len(postings) < 2:
        raise LedgerError("A transaction needs at least two postings")
    if any(p["amount"] == 0 for p in postings):
        raise LedgerError("Postings must not be zero")
    if sum((p["amount"] for p in postings), ZERO) != 0:
        raise LedgerError("Postings must sum to zero")


@dataclass
class Draft:
    kind: str
    date: str
    currency: str
    description: str = ""
    amount: Any = None
    from_account_id: Optional[str] = None
    to_account_id: Optional[str] = None
    account_id: Optional[str] = None
    category: Optional[str] = None
    principal: Any = None
    interest: Any = None
    cash_date: Optional[str] = None


def build_postings(d: Draft, real_accounts: Dict[str, dict]) -> List[dict]:
    """Turn a user-level description of an event into balanced postings."""
    if d.kind not in KINDS:
        raise LedgerError(f"kind must be one of {list(KINDS)}")
    tx_date = valid_date(d.date)
    cash_date = valid_date(d.cash_date, "cash_date") if d.cash_date else tx_date

    def real(account_id: Optional[str], role: str, allowed: tuple = ("asset", "liability")) -> str:
        if not account_id:
            raise LedgerError(f"{role} is required")
        cls = account_class(account_id, real_accounts)
        if cls not in allowed:
            raise LedgerError(f"{role} must be a {' or '.join(allowed)} account")
        acct = real_accounts[account_id]
        if acct.get("currency") != d.currency:
            raise LedgerError(f"{role} is in {acct.get('currency')}, transaction is in {d.currency}")
        return account_id

    def nominal(code: Optional[str], default: str, expected: str) -> str:
        code = code or default
        if NOMINAL_ACCOUNTS.get(code) != expected:
            raise LedgerError(f"category must be an {expected} account")
        return code

    def p(account_id: str, amount: Decimal, on: str) -> dict:
        return {"account_id": account_id, "amount": amount, "date": on}

    k = d.kind
    if k == "expense":
        amt = positive(d.amount, "amount")
        src = real(d.from_account_id, "from_account_id")
        cat = nominal(d.category, "expense:uncategorised", "expense")
        postings = [p(cat, amt, tx_date), p(src, -amt, cash_date)]
    elif k in ("income", "gift"):
        amt = positive(d.amount, "amount")
        dst = real(d.to_account_id, "to_account_id", ("asset",))
        default = "income:gift" if k == "gift" else "income:uncategorised"
        cat = nominal(d.category, default, "income")
        postings = [p(dst, amt, cash_date), p(cat, -amt, tx_date)]
    elif k in OWN_ACCOUNT_KINDS:
        amt = positive(d.amount, "amount")
        src = real(d.from_account_id, "from_account_id", ("asset",))
        to_allowed = ("liability",) if k == "card_settlement" else ("asset",)
        dst = real(d.to_account_id, "to_account_id", to_allowed)
        if src == dst:
            raise LedgerError("from_account_id and to_account_id must differ")
        if k == "card_settlement" and real_accounts[dst].get("account_type") != "credit_card":
            raise LedgerError("card_settlement must pay a credit_card account")
        postings = [p(dst, amt, cash_date), p(src, -amt, cash_date)]
    elif k == "borrowing":  # a loan paid out to you: you hold more and owe more
        amt = positive(d.amount, "amount")
        loan = real(d.from_account_id, "from_account_id", ("liability",))
        if real_accounts[loan].get("account_type") not in LOAN_TYPES:
            raise LedgerError("borrowing must come from a loan account")
        dst = real(d.to_account_id, "to_account_id", ("asset",))
        postings = [p(dst, amt, cash_date), p(loan, -amt, cash_date)]
    elif k == "loan_payment":
        principal = to_decimal(d.principal or 0, "principal")
        interest = to_decimal(d.interest or 0, "interest")
        if principal < 0 or interest < 0 or principal + interest <= 0:
            raise LedgerError("principal and interest must be zero or more, and not both zero")
        src = real(d.from_account_id, "from_account_id", ("asset",))
        loan = real(d.to_account_id, "to_account_id", ("liability",))
        if real_accounts[loan].get("account_type") not in LOAN_TYPES:
            raise LedgerError("loan_payment must pay a loan account")
        postings = [p(src, -(principal + interest), cash_date)]
        if principal:
            postings.append(p(loan, principal, cash_date))
        if interest:
            postings.append(p("expense:interest", interest, tx_date))
    elif k == "refund":
        amt = positive(d.amount, "amount")
        dst = real(d.to_account_id, "to_account_id")
        cat = nominal(d.category, "expense:uncategorised", "expense")
        postings = [p(dst, amt, cash_date), p(cat, -amt, tx_date)]
    else:  # opening_balance: the balance as the user reads it (owed for liabilities)
        amt = to_decimal(d.amount, "amount")
        acct = real(d.account_id, "account_id")
        signed = -amt if account_class(acct, real_accounts) == "liability" else amt
        if signed == 0:
            raise LedgerError("amount must not be zero")
        postings = [p(acct, signed, tx_date), p("equity:opening", -signed, tx_date)]

    check_balanced(postings)
    return postings


def displayed_balance(cls: str, raw: Decimal) -> Decimal:
    """Balances as people read them: money held, or money owed."""
    return -raw if cls in ("liability", "income", "equity") else raw


# ---------------------------------------------------------------------------
# Spending views (pure; transactions are plain dicts with Decimal amounts)
# ---------------------------------------------------------------------------

def accrual_spending(transactions: List[dict], start: str, end: str) -> Dict[str, Dict[str, Decimal]]:
    """{currency: {expense account: amount}} for transactions dated in range."""
    out: Dict[str, Dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for tx in transactions:
        if not (start <= tx["date"] <= end):
            continue
        for p in tx["postings"]:
            if NOMINAL_ACCOUNTS.get(p["account_id"]) == "expense" or p["account_id"].startswith("category:"):
                out[tx["currency"]][p["account_id"]] += p["amount"]
    return out


def cash_spending(transactions: List[dict], real_accounts: Dict[str, dict],
                  start: str, end: str) -> Dict[str, Dict[str, Decimal]]:
    """{currency: {expense account: amount}} counted when money left an asset.

    Expenses paid from assets count on the asset posting's date. Expenses
    charged to a liability join that account's FIFO queue and count when a
    payment from an asset reaches them.
    """
    out: Dict[str, Dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))

    def recognise(currency: str, on: str, account: str, amount: Decimal) -> None:
        if start <= on <= end and amount:
            out[currency][account] += amount

    def is_expense(account_id: str) -> bool:
        return NOMINAL_ACCOUNTS.get(account_id) == "expense" or account_id.startswith("category:")

    # Per liability: queue of [expense account, remaining] and spare credit.
    queues: Dict[str, deque] = defaultdict(deque)
    credit: Dict[str, Decimal] = defaultdict(Decimal)

    def consume(liability: str, amount: Decimal, on: Optional[str], currency: str) -> Decimal:
        """Settle up to ``amount`` of the oldest charges; recognise them on
        ``on`` (None = cancel without recognising). Returns what is left."""
        q = queues[liability]
        while amount > 0 and q:
            head = q[0]
            take = min(amount, head[1])
            if on is not None:
                recognise(currency, on, head[0], take)
            head[1] -= take
            amount -= take
            if head[1] == 0:
                q.popleft()
        return amount

    for tx in sorted(transactions, key=lambda t: (t["date"], t.get("created_at", ""))):
        cur = tx["currency"]
        postings = tx["postings"]
        expense_postings = [p for p in postings if is_expense(p["account_id"])]
        liability_postings = [
            p for p in postings
            if p["account_id"] in real_accounts
            and real_accounts[p["account_id"]].get("account_type") in LIABILITY_TYPES
        ]
        asset_postings = [
            p for p in postings
            if p["account_id"] in real_accounts
            and real_accounts[p["account_id"]].get("account_type") in ASSET_TYPES
        ]
        cards = [p for p in liability_postings if real_accounts[p["account_id"]].get("account_type") == "credit_card"]

        if tx["kind"] == "opening_balance" and cards:
            # Owed before the ledger began: older, uncategorised spending
            # that the first payments settle (cash view only).
            owed = -cards[0]["amount"]
            if owed > 0:
                queues[cards[0]["account_id"]].append(["expense:uncategorised", owed])
            else:
                credit[cards[0]["account_id"]] += -owed
            continue
        if tx["kind"] == "card_settlement":
            card = cards[0]
            left = consume(card["account_id"], card["amount"], card["date"], cur)
            credit[card["account_id"]] += left
            continue
        if cards and expense_postings:
            card_id = cards[0]["account_id"]
            for e in expense_postings:
                if e["amount"] > 0:  # a charge
                    from_credit = min(credit[card_id], e["amount"])
                    credit[card_id] -= from_credit
                    recognise(cur, e["date"], e["account_id"], from_credit)
                    if e["amount"] - from_credit:
                        queues[card_id].append([e["account_id"], e["amount"] - from_credit])
                else:  # a refund on the card cancels charges, no cash moved
                    left = consume(card_id, -e["amount"], None, cur)
                    credit[card_id] += left
            continue
        # Paid from (or refunded to) an asset, or interest on a loan payment.
        on = asset_postings[0]["date"] if asset_postings else tx["date"]
        for e in expense_postings:
            recognise(cur, on, e["account_id"], e["amount"])
    return out


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _store(postings: List[dict]) -> List[dict]:
    return [{**p, "amount": Decimal128(p["amount"])} for p in postings]


def _load(tx: dict) -> dict:
    tx = {k: v for k, v in tx.items() if k != "_id"}
    tx["postings"] = [{**p, "amount": to_decimal(p["amount"])} for p in tx["postings"]]
    return tx


def _public(tx: dict) -> dict:
    out = dict(tx)
    out["postings"] = [{**p, "amount": format(p["amount"], "f")} for p in tx["postings"]]
    return out


async def real_accounts_for(db, user_id: str) -> Dict[str, dict]:
    rows = await db.financial_accounts.find(
        {"user_id": user_id}, {"_id": 0, "id": 1, "account_type": 1, "currency": 1, "name": 1},
    ).to_list(length=None)
    return {r["id"]: r for r in rows}


def build_transaction(user_id: str, draft: Draft, accounts: Dict[str, dict], *, provenance: str = "user",
                      evidence_ids: Optional[List[str]] = None,
                      references: Optional[List[str]] = None) -> dict:
    """Validate and assemble a transaction without writing it."""
    postings = build_postings(draft, accounts)
    now = _now()
    return {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "kind": draft.kind,
        "date": valid_date(draft.date),
        "currency": draft.currency,
        "description": (draft.description or "").strip(),
        "postings": postings,
        "status": "posted",
        "provenance": provenance,
        # What a person entered or corrected is never rewritten by automation.
        "locked": provenance == "user",
        "evidence_ids": evidence_ids or [],
        # Bank / UPI reference numbers, used to recognise the same payment
        # reported by another statement.
        "references": [r for r in (references or []) if r],
        "created_at": now,
        "updated_at": now,
    }


def storable(tx: dict) -> dict:
    return {**tx, "postings": _store(tx["postings"])}


async def record(db, user_id: str, draft: Draft, *, provenance: str = "user",
                 evidence_ids: Optional[List[str]] = None,
                 references: Optional[List[str]] = None) -> dict:
    accounts = await real_accounts_for(db, user_id)
    tx = build_transaction(user_id, draft, accounts, provenance=provenance,
                           evidence_ids=evidence_ids, references=references)
    await db.ledger_transactions.insert_one(storable(tx))
    import request_cache
    request_cache.forget(user_id)
    return tx


async def load_transactions(db, user_id: str, *, account_id: Optional[str] = None) -> List[dict]:
    import request_cache

    if not account_id:
        remembered = request_cache.get(("txs", user_id))
        if remembered is not None:
            return list(remembered)
    query: Dict[str, Any] = {"user_id": user_id, "status": "posted"}
    if account_id:
        query["postings.account_id"] = account_id
    rows = await db.ledger_transactions.find(query).sort("date", 1).to_list(length=None)
    txs = [_load(r) for r in rows]
    if not account_id:
        request_cache.put(("txs", user_id), txs)
    return list(txs)


async def balances(db, user_id: str, as_of: str) -> List[dict]:
    accounts = await real_accounts_for(db, user_id)
    raw: Dict[str, Decimal] = defaultdict(Decimal)
    for tx in await load_transactions(db, user_id):
        for p in tx["postings"]:
            if p["account_id"] in accounts and p["date"] <= as_of:
                raw[p["account_id"]] += p["amount"]
    out = []
    for acct_id, acct in accounts.items():
        cls = account_class(acct_id, accounts)
        out.append({
            "account_id": acct_id,
            "name": acct.get("name", ""),
            "account_type": acct.get("account_type"),
            "currency": acct.get("currency"),
            "class": cls,
            "balance": format(displayed_balance(cls, raw[acct_id]).quantize(CENT), "f"),
        })
    return out


async def ensure_ledger_indexes(db) -> None:
    await db.ledger_transactions.create_index("id", unique=True)
    await db.ledger_transactions.create_index([("user_id", 1), ("status", 1), ("date", 1)])
    await db.ledger_transactions.create_index([("user_id", 1), ("postings.account_id", 1), ("date", 1)])
    await db.ledger_transactions.create_index("evidence_ids")
    await db.ledger_transactions.create_index([("user_id", 1), ("references", 1)])


# ---------------------------------------------------------------------------
# Routes (not used by the app until the switch-over)
# ---------------------------------------------------------------------------

class TransactionCreate(BaseModel):
    kind: Literal[
        "expense", "income", "gift", "transfer", "investment", "redemption",
        "card_settlement", "loan_payment", "refund", "opening_balance", "borrowing",
    ]
    date: str
    currency: str = Field(min_length=3, max_length=3)
    description: str = Field(default="", max_length=500)
    amount: Optional[str] = None
    from_account_id: Optional[str] = None
    to_account_id: Optional[str] = None
    account_id: Optional[str] = None
    category: Optional[str] = None
    principal: Optional[str] = None
    interest: Optional[str] = None
    cash_date: Optional[str] = None


def _bad_request(exc: LedgerError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@ledger_router.post("/transactions", status_code=201)
async def create_transaction(body: TransactionCreate, current_user: dict = Depends(get_current_user)):
    try:
        tx = await record(get_db(), current_user["id"], Draft(**body.model_dump()))
    except LedgerError as exc:
        raise _bad_request(exc)
    return _public(tx)


@ledger_router.get("/transactions")
async def list_transactions(account_id: Optional[str] = None,
                            current_user: dict = Depends(get_current_user)):
    import ledger_sync
    await ledger_sync.sync(get_db(), current_user["id"])
    txs = await load_transactions(get_db(), current_user["id"], account_id=account_id)
    return [_public(t) for t in reversed(txs)]


@ledger_router.post("/transactions/{tx_id}/void")
async def void_transaction(tx_id: str, current_user: dict = Depends(get_current_user)):
    # A person may void anything, locked included; automation never voids.
    result = await get_db().ledger_transactions.update_one(
        {"id": tx_id, "user_id": current_user["id"], "status": "posted"},
        {"$set": {"status": "void", "voided_by": "person", "voided_at": _now(), "updated_at": _now()}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Transaction not found or already void")
    return {"detail": "Voided"}


@ledger_router.get("/categories")
async def get_categories(current_user: dict = Depends(get_current_user)):
    """The two-level category tree for pickers: groups → categories."""
    return _categories.tree()


@ledger_router.get("/balances")
async def get_balances(as_of: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    try:
        day = valid_date(as_of) if as_of else date_type.today().isoformat()
    except LedgerError as exc:
        raise _bad_request(exc)
    import ledger_sync
    await ledger_sync.sync(get_db(), current_user["id"])
    return await balances(get_db(), current_user["id"], day)


@ledger_router.get("/spending")
async def get_spending_report(
    start: str = Query(...), end: str = Query(...),
    basis: Literal["accrual", "cash"] = "accrual",
    current_user: dict = Depends(get_current_user),
):
    try:
        start, end = valid_date(start, "start"), valid_date(end, "end")
    except LedgerError as exc:
        raise _bad_request(exc)
    db = get_db()
    import ledger_sync
    await ledger_sync.sync(db, current_user["id"])
    txs = await load_transactions(db, current_user["id"])
    if basis == "accrual":
        report = accrual_spending(txs, start, end)
    else:
        report = cash_spending(txs, await real_accounts_for(db, current_user["id"]), start, end)
    return {
        "basis": basis, "start": start, "end": end,
        "by_currency": [
            {
                "currency": cur,
                "total": format(sum(cats.values(), ZERO).quantize(CENT), "f"),
                "by_account": {k: format(v.quantize(CENT), "f") for k, v in sorted(cats.items()) if v},
            }
            for cur, cats in sorted(report.items())
        ],
    }
