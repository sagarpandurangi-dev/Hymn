"""Two-level categories; older flat keys keep working."""
from __future__ import annotations

import categories
import ledger


def test_old_keys_still_valid_and_grouped():
    for old in ("food", "transport", "bills", "health", "insurance", "taxes", "charity", "education", "family",
                "groceries", "fuel", "rent", "shopping", "interest", "fees", "depreciation", "uncategorised"):
        assert old in ledger.EXPENSE_CATEGORIES
    assert categories.describe("expense:food")["group_label"] == "Food"
    assert categories.describe("expense:bills")["group"] == "home"
    assert categories.describe("expense:ordering_in") == {
        "group": "food", "group_label": "Food", "category": "ordering_in", "category_label": "Ordering in"}
    assert categories.describe("income:salary")["group"] == "salary"


def test_insurance_is_its_own_group_not_a_finance_cost():
    assert categories.describe("expense:term_life")["group"] == "insurance"
    assert categories.describe("expense:health_insurance")["group"] == "insurance"
    assert all(c in ("interest", "fees") for _, _, cats in categories.EXPENSE_TREE if _ == "finance_costs"
               for c, _l in cats)


def test_each_key_once_and_suggestions_avoid_catch_alls():
    keys = [c for _, _, cats in categories.EXPENSE_TREE for c, _ in cats]
    assert len(keys) == len(set(keys))
    assert "food" not in categories.SUGGESTIBLE_EXPENSE and "eating_out" in categories.SUGGESTIBLE_EXPENSE


def test_tree_endpoint(client):
    r = client.post("/api/auth/signup", json={"name": "C", "email": "cat@example.com",
                                              "password": "correct-horse-battery", "security_question": "Q?",
                                              "security_answer": "A"})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    t = client.get("/api/ledger/categories", headers=h).json()
    food = next(g for g in t["expense"] if g["group"] == "food")
    assert [c["key"] for c in food["categories"]][:3] == ["groceries", "eating_out", "ordering_in"]
