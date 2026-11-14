"""The three money statements, read from the ledger (and life objects).

* **Statement of Net Worth** (side by side, old style): liabilities and net
  worth on the left, assets on the right. Net worth = opening net worth at
  the start of the financial year (1 April) + this year's surplus + other
  changes (opening balances added, assets bought or revalued…), so the
  sides always agree and each piece is explained.
* **Income & Expenditure** (vertical): income, then spending by group →
  category → entries; surplus and savings rate; columns for the month, the
  month before and the financial year to date. Accrual view: a card dinner
  counts the day it was eaten. Assets' value loss (life objects) shows as
  "Car value loss" etc.
* **Cash Flow**: opening cash → living → investing → borrowing → closing
  cash, in the cash view (what actually left or reached bank and cash).

Amounts are per currency; nothing converts between currencies.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date as date_type, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query

import categories
import ledger
import ledger_sync
import life_objects
from deps import get_current_user, get_db

reports_router = APIRouter(prefix="/reports", tags=["reports"])

ZERO = Decimal(0)
CENT = Decimal("0.01")

ASSET_GROUPS: List[Tuple[str, str, frozenset]] = [
    ("fixed", "Fixed assets", frozenset({"real_estate"})),
    ("investments", "Investments", frozenset({"mutual_fund", "stock", "bond", "crypto", "gold",
                                              "fixed_deposit", "recurring_deposit"})),
    ("retirement", "Retirement & long-term", frozenset({"epf", "ppf", "nps"})),
    ("deposits", "Deposits & money lent", frozenset({"deposit_given", "money_lent", "other_asset"})),
    ("cash", "Cash & bank", frozenset({"cash", "bank"})),
]
LIABILITY_GROUPS: List[Tuple[str, str, frozenset]] = [
    ("loans", "Loans", frozenset({"home_loan", "vehicle_loan", "personal_loan", "money_borrowed", "other_liability"})),
    ("current", "Current liabilities", frozenset({"credit_card"})),
]
CASH_TYPES = frozenset({"cash", "bank"})
INVEST_TYPES = frozenset().union(*(g[2] for g in ASSET_GROUPS if g[0] != "cash"))


def _out(d: Decimal) -> str:
    return format(d.quantize(CENT), "f")


def fy_start(day: str) -> str:
    d = date_type.fromisoformat(day)
    return f"{d.year if d.month >= 4 else d.year - 1}-04-01"


def _prev_day(day: str) -> str:
    return (date_type.fromisoformat(day) - timedelta(days=1)).isoformat()


def _month_bounds(month: str) -> Tuple[str, str]:
    y, m = int(month[:4]), int(month[5:7])
    nxt = date_type(y + (m == 12), 1 if m == 12 else m + 1, 1)
    return f"{month}-01", (nxt - timedelta(days=1)).isoformat()


# ---------------------------------------------------------------------------
# Pure builders
# ---------------------------------------------------------------------------

def raw_balances(txs: List[dict], accounts: Dict[str, dict], as_of: str) -> Dict[str, Decimal]:
    raw: Dict[str, Decimal] = defaultdict(Decimal)
    for tx in txs:
        for p in tx["postings"]:
            if p["account_id"] in accounts and p["date"] <= as_of:
                raw[p["account_id"]] += p["amount"]
    return raw


def net_worth_at(txs, accounts, objects, as_of: str, currency: str) -> Dict[str, Decimal]:
    """{line key: amount} for assets (+) and liabilities (−) on a date."""
    raw = raw_balances(txs, accounts, as_of)
    out: Dict[str, Decimal] = {}
    for aid, acct in accounts.items():
        if acct.get("currency") != currency:
            continue
        cls = ledger.account_class(aid, accounts)
        out[aid] = raw[aid] if cls == "asset" else raw[aid]  # liabilities are negative raw
    for o in objects:
        if (o.get("currency") or "INR") != currency or o.get("type") != "asset":
            continue
        value = life_objects.book_value(o, as_of)
        if o.get("account_id") in out:
            out[o["account_id"]] = value  # the account holds the asset; show its book value
        elif value:
            out[f"object:{o['id']}"] = value
    return out


def income_expenditure(txs, objects, start: str, end: str, currency: str) -> dict:
    """Accrual income and spending by category for a period."""
    amounts: Dict[str, Decimal] = defaultdict(Decimal)
    for tx in txs:
        if tx["currency"] != currency or not (start <= tx["date"] <= end):
            continue
        for p in tx["postings"]:
            if p["account_id"].startswith("expense:"):
                amounts[p["account_id"]] += p["amount"]
            elif p["account_id"].startswith("income:"):
                amounts[p["account_id"]] -= p["amount"]
    for o in objects:
        if (o.get("currency") or "INR") == currency:
            lost = life_objects.value_lost_between(o, start, end)
            if lost:
                amounts["expense:depreciation"] += lost
    return amounts


def _tree(amounts: Dict[str, Decimal], side: str) -> Tuple[List[dict], Decimal]:
    tree = categories.EXPENSE_TREE if side == "expense" else categories.INCOME_TREE
    groups, total = [], ZERO
    known = {c for _, _, cats in tree for c, _ in cats}
    for g, glabel, cats in tree:
        rows = [{"category": f"{side}:{c}", "label": label, "amount": amounts.get(f"{side}:{c}", ZERO)}
                for c, label in cats]
        if g == "unsorted":  # anything outside the tree lands here too
            rows += [{"category": k, "label": categories.describe(k)["category_label"], "amount": v}
                     for k, v in amounts.items() if k.startswith(f"{side}:") and k.partition(":")[2] not in known]
        rows = [r for r in rows if r["amount"]]
        if rows:
            subtotal = sum((r["amount"] for r in rows), ZERO)
            total += subtotal
            groups.append({"group": g, "label": glabel, "amount": subtotal, "categories": rows})
    return groups, total


def cash_flow(txs, accounts, start: str, end: str, currency: str) -> dict:
    cash = {a for a, acct in accounts.items() if acct.get("account_type") in CASH_TYPES
            and acct.get("currency") == currency}
    loans = {a for a, acct in accounts.items() if acct.get("account_type") in ledger.LOAN_TYPES}
    invest = {a for a, acct in accounts.items() if acct.get("account_type") in INVEST_TYPES}
    cards = {a for a, acct in accounts.items() if acct.get("account_type") == "credit_card"}
    lines = defaultdict(Decimal)
    for tx in txs:
        if tx["currency"] != currency:
            continue
        moved = sum((p["amount"] for p in tx["postings"] if p["account_id"] in cash and start <= p["date"] <= end), ZERO)
        if not moved:
            continue
        others = {p["account_id"]: p["amount"] for p in tx["postings"] if p["account_id"] not in cash}
        if not others:
            continue  # between your own bank and cash: no flow
        if "equity:opening" in others:
            lines["other:opening"] += moved
        elif loans & set(others):
            interest = others.get("expense:interest", ZERO)
            principal = moved + interest
            lines["borrowing:received" if moved > 0 else "borrowing:repaid"] += principal
            if interest:
                lines["living:spent"] -= interest
        elif invest & set(others):
            lines["investing:sold" if moved > 0 else "investing:bought"] += moved
        elif cards & set(others):
            lines["living:card_bills"] += moved
        elif moved > 0:
            lines["living:income"] += moved
        else:
            lines["living:spent"] += moved
    opening = sum((v for a, v in raw_balances(txs, accounts, _prev_day(start)).items() if a in cash), ZERO)
    closing = sum((v for a, v in raw_balances(txs, accounts, end).items() if a in cash), ZERO)
    return {"opening": opening, "closing": closing, "lines": lines}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

async def _data(db, user_id: str):
    await ledger_sync.sync(db, user_id)
    accounts = await ledger.real_accounts_for(db, user_id)
    names = {a["id"]: a for a in await db.financial_accounts.find(
        {"user_id": user_id}, {"_id": 0, "id": 1, "name": 1, "account_type": 1, "currency": 1}).to_list(length=None)}
    txs = await ledger.load_transactions(db, user_id)
    objects = await db.life_objects.find({"user_id": user_id}, {"_id": 0}).to_list(length=None)
    return accounts, names, txs, objects


def _currencies(accounts, objects, currency: Optional[str]) -> List[str]:
    found = sorted({a.get("currency") for a in accounts.values() if a.get("currency")}
                   | {o.get("currency") or "INR" for o in objects})
    return [currency] if currency else (found or ["INR"])


def _valid(day: str, field: str) -> str:
    try:
        return date_type.fromisoformat(day).isoformat()
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{field} must be YYYY-MM-DD")


@reports_router.get("/net-worth")
async def net_worth(as_of: Optional[str] = None, currency: Optional[str] = None,
                    current_user: dict = Depends(get_current_user)):
    """Statement of Net Worth, side by side."""
    day = _valid(as_of, "as_of") if as_of else date_type.today().isoformat()
    accounts, names, txs, objects = await _data(get_db(), current_user["id"])
    obj_names = {f"object:{o['id']}": o for o in objects}
    out = []
    for cur in _currencies(accounts, objects, currency):
        now = net_worth_at(txs, accounts, objects, day, cur)
        opening_day = _prev_day(fy_start(day))
        opening = sum(net_worth_at(txs, accounts, objects, opening_day, cur).values(), ZERO)
        ie = income_expenditure(txs, objects, fy_start(day), day, cur)
        surplus = sum((v for k, v in ie.items() if k.startswith("income:")), ZERO) - \
            sum((v for k, v in ie.items() if k.startswith("expense:")), ZERO)

        def lines_for(groups, sign):
            result, total = [], ZERO
            for key, label, types in groups:
                rows = []
                for k, v in now.items():
                    t = (names.get(k) or {}).get("account_type")
                    if k.startswith("object:"):
                        t = "real_estate" if key == "fixed" else None
                    if t in types and v * sign > 0:
                        o = obj_names.get(k)
                        rows.append({"id": k, "name": (o or {}).get("name") or (names.get(k) or {}).get("name", ""),
                                     "amount": _out(v * sign)})
                if rows:
                    sub = sum((Decimal(r["amount"]) for r in rows), ZERO)
                    total += sub
                    result.append({"group": key, "label": label, "amount": _out(sub), "lines": rows})
            return result, total

        assets, total_assets = lines_for(ASSET_GROUPS, 1)
        liabilities, total_liabilities = lines_for(LIABILITY_GROUPS, -1)
        closing = total_assets - total_liabilities
        out.append({
            "currency": cur, "as_of": day, "financial_year_start": fy_start(day),
            "left": {
                "net_worth": {"opening": _out(opening), "surplus_this_year": _out(surplus),
                              "other_changes": _out(closing - opening - surplus), "total": _out(closing)},
                "liabilities": liabilities,
                "total": _out(closing + total_liabilities),
            },
            "right": {"assets": assets, "total": _out(total_assets)},
        })
    return out


@reports_router.get("/income-expenditure")
async def income_and_expenditure(month: Optional[str] = None, currency: Optional[str] = None,
                                 current_user: dict = Depends(get_current_user)):
    """Vertical Income & Expenditure: this month, last month, year to date."""
    month = month or date_type.today().isoformat()[:7]
    try:
        start, end = _month_bounds(month)
    except ValueError:
        raise HTTPException(status_code=400, detail="month must be YYYY-MM")
    prev = (date_type.fromisoformat(start) - timedelta(days=1)).isoformat()[:7]
    p_start, p_end = _month_bounds(prev)
    periods = [("this_month", start, end), ("last_month", p_start, p_end), ("year_to_date", fy_start(end), end)]
    accounts, _names, txs, objects = await _data(get_db(), current_user["id"])
    out = []
    for cur in _currencies(accounts, objects, currency):
        cols = {}
        for key, s, e in periods:
            amounts = income_expenditure(txs, objects, s, e, cur)
            income, total_in = _tree(amounts, "income")
            spending, total_out = _tree(amounts, "expense")
            surplus = total_in - total_out
            cols[key] = {
                "start": s, "end": e,
                "income": [{**g, "amount": _out(g["amount"]),
                            "categories": [{**c, "amount": _out(c["amount"])} for c in g["categories"]]}
                           for g in income],
                "total_income": _out(total_in),
                "expenditure": [{**g, "amount": _out(g["amount"]),
                                 "categories": [{**c, "amount": _out(c["amount"])} for c in g["categories"]]}
                                for g in spending],
                "total_expenditure": _out(total_out),
                "surplus": _out(surplus),
                "savings_rate_percent": _out(surplus / total_in * 100) if total_in > 0 else None,
            }
        out.append({"currency": cur, "month": month, **cols})
    return out


@reports_router.get("/entries")
async def entries(category: str = Query(...), start: str = Query(...), end: str = Query(...),
                  current_user: dict = Depends(get_current_user)):
    """The entries behind one line (e.g. expense:groceries) for a period."""
    start, end = _valid(start, "start"), _valid(end, "end")
    db = get_db()
    await ledger_sync.sync(db, current_user["id"])
    rows = []
    for tx in await ledger.load_transactions(db, current_user["id"]):
        if not (start <= tx["date"] <= end):
            continue
        amt = sum((p["amount"] for p in tx["postings"] if p["account_id"] == category), ZERO)
        if amt:
            rows.append({"id": tx["id"], "date": tx["date"], "description": tx.get("description") or "",
                         "currency": tx["currency"], "amount": _out(-amt if category.startswith("income:") else amt)})
    return sorted(rows, key=lambda r: r["date"], reverse=True)


@reports_router.get("/cash-flow")
async def cash_flow_statement(month: Optional[str] = None, start: Optional[str] = None, end: Optional[str] = None,
                              currency: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    if start or end:
        s, e = _valid(start, "start"), _valid(end, "end")
    else:
        try:
            s, e = _month_bounds(month or date_type.today().isoformat()[:7])
        except ValueError:
            raise HTTPException(status_code=400, detail="month must be YYYY-MM")
    accounts, _names, txs, objects = await _data(get_db(), current_user["id"])
    labels = {"living:income": "Income received", "living:spent": "Spent from bank & cash",
              "living:card_bills": "Card bills paid", "investing:bought": "Put into investments & assets",
              "investing:sold": "Taken out of investments & assets", "borrowing:received": "Loans received",
              "borrowing:repaid": "Loan principal repaid", "other:opening": "Opening balances added"}
    out = []
    for cur in _currencies(accounts, objects, currency):
        cf = cash_flow(txs, accounts, s, e, cur)
        sections = []
        for key, title in (("living", "Living"), ("investing", "Investing"), ("borrowing", "Borrowing"),
                           ("other", "Other")):
            rows = [{"key": k, "label": labels[k], "amount": _out(v)} for k, v in cf["lines"].items()
                    if k.startswith(key + ":") and v]
            if rows:
                sections.append({"section": key, "label": title, "lines": rows,
                                 "net": _out(sum((Decimal(r["amount"]) for r in rows), ZERO))})
        net = sum(cf["lines"].values(), ZERO)
        out.append({"currency": cur, "start": s, "end": e, "opening_cash": _out(cf["opening"]),
                    "sections": sections, "net_change": _out(net), "closing_cash": _out(cf["closing"]),
                    "adds_up": (cf["opening"] + net).quantize(CENT) == cf["closing"].quantize(CENT)})
    return out
