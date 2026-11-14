"""The category tree: group → category, for spending and income.

Statements show groups first and open into categories, then entries
(Food → Groceries / Eating out / Ordering in → Swiggy 12 Nov …).

Category keys are what the ledger stores (``expense:<key>``). Keys from the
first, flat list (``food``, ``transport``, ``bills``…) stay valid forever so
history and learned rules never break; they sit in their group as
"<Group> (other)". New suggestions use the finer keys.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

# (group key, group label, [(category key, label), ...]) in display order.
EXPENSE_TREE: List[Tuple[str, str, List[Tuple[str, str]]]] = [
    ("home", "Home", [("rent", "Rent"), ("maintenance", "Maintenance"), ("electricity_water", "Electricity & water"),
                      ("gas", "Gas"), ("internet_phone", "Internet & phone"), ("repairs", "Repairs"),
                      ("household_help", "Household help"), ("bills", "Home (other)")]),
    ("food", "Food", [("groceries", "Groceries"), ("eating_out", "Eating out"), ("ordering_in", "Ordering in"),
                      ("food", "Food (other)")]),
    ("transport", "Transport", [("fuel", "Fuel"), ("cabs", "Cabs & autos"), ("public_transport", "Public transport"),
                                ("parking_tolls", "Parking & tolls"), ("car_upkeep", "Car upkeep"),
                                ("depreciation", "Car value loss"), ("transport", "Transport (other)")]),
    ("health", "Health", [("medicines", "Medicines"), ("doctor_tests", "Doctor & tests"), ("fitness", "Gym & fitness"),
                          ("health", "Health (other)")]),
    ("insurance", "Insurance", [("term_life", "Term life"), ("health_insurance", "Health"),
                                ("vehicle_insurance", "Vehicle"), ("insurance", "Other insurance")]),
    ("family", "Family", [("parents", "Parents"), ("kids", "Kids"), ("gifts", "Gifts"),
                          ("celebrations", "Celebrations"), ("family", "Family (other)")]),
    ("lifestyle", "Lifestyle", [("shopping", "Shopping"), ("entertainment", "Entertainment"),
                                ("subscriptions", "Subscriptions"), ("personal_care", "Grooming"),
                                ("travel", "Travel & holidays")]),
    ("education", "Education", [("courses", "Courses"), ("books", "Books"), ("school_fees", "School & college fees"),
                                ("education", "Education (other)")]),
    ("finance_costs", "Finance costs", [("interest", "Loan interest"), ("fees", "Bank & card fees")]),
    ("taxes", "Taxes", [("income_tax", "Income tax"), ("property_tax", "Property tax"), ("taxes", "Other taxes")]),
    ("charity", "Charity", [("donations", "Donations"), ("religious", "Religious"), ("charity", "Charity (other)")]),
    ("unsorted", "Not yet sorted", [("uncategorised", "Not yet sorted")]),
]

INCOME_TREE: List[Tuple[str, str, List[Tuple[str, str]]]] = [
    ("salary", "Salary", [("salary", "Salary (take-home)"), ("bonus", "Bonus")]),
    ("investment_income", "Interest & dividends", [("interest", "Interest"), ("dividends", "Dividends")]),
    ("other_income", "Other income", [("rent_received", "Rent received"), ("refund", "Refunds & cashback"),
                                      ("gift", "Gifts received"), ("other", "Other")]),
    ("unsorted", "Not yet sorted", [("uncategorised", "Not yet sorted")]),
]


def _flatten(tree) -> Dict[str, Tuple[str, str, str]]:
    """{category key: (group key, group label, category label)}"""
    return {c: (g, glabel, clabel) for g, glabel, cats in tree for c, clabel in cats}


EXPENSE: Dict[str, Tuple[str, str, str]] = _flatten(EXPENSE_TREE)
INCOME: Dict[str, Tuple[str, str, str]] = _flatten(INCOME_TREE)

# Suggestions shouldn't land in the catch-alls or system-only categories.
SUGGESTIBLE_EXPENSE = [c for c, (g, _, label) in EXPENSE.items()
                       if not label.endswith("(other)") and c not in ("uncategorised", "depreciation", "interest", "fees",
                                                                       "insurance", "taxes")]
SUGGESTIBLE_INCOME = [c for c in INCOME if c != "uncategorised"]


def describe(account_id: str) -> Dict[str, str]:
    """Group and labels for a ledger category account like expense:groceries."""
    side, _, key = account_id.partition(":")
    table = EXPENSE if side == "expense" else INCOME
    group, glabel, clabel = table.get(key, ("unsorted", "Not yet sorted", key.replace("_", " ").title()))
    return {"group": group, "group_label": glabel, "category": key, "category_label": clabel}


def tree() -> Dict[str, list]:
    """For the app's category pickers."""
    def shape(t):
        return [{"group": g, "label": gl, "categories": [{"key": c, "label": cl} for c, cl in cats]}
                for g, gl, cats in t]
    return {"expense": shape(EXPENSE_TREE), "income": shape(INCOME_TREE)}
