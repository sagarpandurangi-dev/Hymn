"""Fuel: real mileage and cost per km / day from fill check-ins."""
from __future__ import annotations

from life_objects import fuel_report


def _fill(day, odo, amount=None, price="100", full=True, litres=None, money=None):
    data = {"odometer": odo, "price_per_litre": price, "full_tank": full}
    if amount:
        data["amount"] = amount
    if litres:
        data["litres"] = litres
    return {"date": day, "data": data, "money_spent": money}


def test_mileage_between_full_tanks_with_a_partial_in_between():
    r = fuel_report([_fill("2026-01-01", "10000", "3000"),
                     _fill("2026-01-10", "10300", "1000", full=False),     # partial top-up
                     _fill("2026-01-21", "10600", "2000")])
    s = r["stretches"][0]
    assert (s["km"], s["litres"], s["km_per_litre"]) == ("600.00", "30.00", "20.00")
    assert (s["cost"], s["cost_per_km"], s["cost_per_day"], s["days"]) == ("3000.00", "5.00", "150.00", 20)
    assert r["km_per_litre"] == "20.00" and r["latest_price_per_litre"] == "100.00"


def test_amount_from_check_in_money_and_litres_given():
    r = fuel_report([_fill("2026-02-01", "5000", money="2000", price="100"),
                     _fill("2026-02-11", "5250", litres="15", price="102")])
    assert r["stretches"][0]["km_per_litre"] == "16.67"
    assert r["fills"][1]["amount"] == "1530.00"


def test_not_enough_fills():
    assert fuel_report([_fill("2026-01-01", "100", "500")])["km_per_litre"] is None
    assert fuel_report([{"date": "2026-01-01", "data": {"note": "washed"}}])["fills"] == []
