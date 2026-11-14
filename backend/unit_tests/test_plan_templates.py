"""Checklists for big life events, hidden until an expert signs them off."""
from __future__ import annotations

import asyncio

import plan_assistant
import plan_templates


def test_house_numbers_follow_the_lending_limits():
    big = plan_templates.house({"price": "9000000"})
    reqs = {r["what"]: r for r in big["requirements"]}
    assert reqs["Down payment (the part the bank won't lend)"]["amount"] == "2250000"    # 75% LTV above ₹75L
    assert reqs["Stamp duty and registration"]["amount"] == "630000"
    small = plan_templates.house({"price": "2500000"})
    assert small["requirements"][0]["amount"] == "250000"                                # 90% LTV up to ₹30L
    assert all(r.get("source") for r in big["requirements"])                             # every line says why


def test_every_area_is_covered_for_a_first_child():
    child = plan_templates.first_child({})
    assert {r["area"] for r in child["requirements"]} >= {"health", "money", "work", "family", "learning"}
    health = [r for r in child["requirements"] + child["risks"] if r["area"] == "health"]
    assert all("doctor" in (r.get("source", "") + r.get("mitigation", "") + r["what"]).lower() for r in health)


def test_drafts_are_hidden_until_reviewed(monkeypatch):
    owner, tester = {"email": "owner@example.com"}, {"email": "tester@example.com"}
    monkeypatch.setenv("HYMN_TEMPLATE_PREVIEW_EMAILS", "owner@example.com")
    assert plan_templates.fill(tester, "house") is None
    assert plan_templates.fill(owner, "house")["reviewed"] is False
    monkeypatch.setenv("HYMN_REVIEWED_TEMPLATES", "house")
    assert plan_templates.fill(tester, "house")["reviewed"] is True
    assert plan_templates.fill(tester, "first_child") is None                            # still a draft
    assert [t["key"] for t in plan_templates.available(tester)] == ["house"]


def test_planner_tool_returns_the_checklist(server, monkeypatch):
    monkeypatch.setenv("HYMN_TEMPLATE_PREVIEW_EMAILS", "owner@example.com")
    out = asyncio.run(plan_assistant.run_tool(server.db, {"id": "u", "email": "owner@example.com"}, {"id": "c"},
                                              "use_template", {"key": "wedding", "params": {"budget": 2000000,
                                                                                             "family_contribution": 500000}}))
    assert out["requirements"][0]["amount"] == "1500000" and out["reviewed"] is False
    hidden = asyncio.run(plan_assistant.run_tool(server.db, {"id": "u", "email": "x@example.com"}, {"id": "c"},
                                                 "use_template", {"key": "wedding"}))
    assert "error" in hidden
    assert "use_template first" in plan_assistant.SYSTEM
