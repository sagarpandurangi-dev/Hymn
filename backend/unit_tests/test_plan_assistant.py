"""The planning assistant: the AI talks, tools produce every number (fake AI)."""
from __future__ import annotations

import json
from datetime import date, datetime
from types import SimpleNamespace

import pytest

import life_plans
import plan_assistant
from claude_client import AssistantUnavailable


@pytest.fixture()
def user(client):
    r = client.post("/api/auth/signup", json={"name": "Ravi", "email": "planner@example.com",
                                              "password": "correct-horse-battery", "security_question": "Q?",
                                              "security_answer": "A"})
    b = r.json()
    return {"id": b["user"]["id"], "headers": {"Authorization": f"Bearer {b['access_token']}"}}


def _resp(blocks, stop):
    return SimpleNamespace(content=blocks, stop_reason=stop)


def _use(i, name, args):
    return {"type": "tool_use", "id": f"t{i}", "name": name, "input": args}


class FakeAI:
    """Plays scripted turns; each step can inspect what the tools returned."""

    def __init__(self, steps):
        self.steps, self.seen = list(steps), []

    async def __call__(self, system, messages, tools):
        assert "Never state a number about the person's money or time unless a tool gave it" in system
        assert any(t["name"] == "propose_plan" for t in tools)
        last = messages[-1]["content"]
        if isinstance(last, list):
            self.seen.append({r["tool_use_id"]: (json.loads(r["content"]) if not r.get("is_error") else r)
                              for r in last if r.get("type") == "tool_result"})
        step = self.steps.pop(0)
        return step(self.seen[-1] if self.seen else None) if callable(step) else step


def test_small_ask_gets_real_slots(client, server, user, monkeypatch):
    monkeypatch.setattr(life_plans, "local_now", lambda u: datetime(2026, 11, 17, 8, 0))
    fake = FakeAI([
        _resp([_use(1, "find_time", {"minutes": 45, "by": "2026-11-22", "earliest": "18:00", "latest": "22:00"})],
              "tool_use"),
        lambda seen: _resp([{"type": "text", "text": f"Free from {seen['t1']['slots'][0]['start']} on Tuesday."}],
                           "end_turn"),
    ])
    monkeypatch.setattr(plan_assistant, "call_model", fake)
    r = client.post("/api/plan-chat", headers=user["headers"], json={"message": "45 min of guitar this week"})
    assert r.status_code == 200, r.text
    assert r.json()["reply"] == "Free from 18:00 on Tuesday."
    assert fake.seen[0]["t1"]["slots"][0]["date"] == "2026-11-17"


def test_big_ask_tools_do_the_numbers_and_accepting_picks_one_option(client, server, user, monkeypatch):
    monkeypatch.setattr(plan_assistant, "call_model", FakeAI([
        _resp([_use(1, "get_context", {})], "tool_use"),
        _resp([_use(2, "remember_fact", {"key": "date_of_birth", "value": "1999-05-10", "label": "Birthday"}),
               _use(3, "loan_affordability", {"principal": 7200000, "annual_rate_percent": 8.5,
                                              "tenure_months": 240, "monthly_income": 100000}),
               _use(4, "future_cost", {"amount_today": 2500000, "on": "2029-05-10"})], "tool_use"),
        lambda seen: _resp([_use(5, "propose_plan", {
            "title": "House at 29", "target_date": "2028-05-10",
            "requirements": [{"area": "money", "what": "Down payment and costs", "kind": "money", "amount": 2900000},
                             {"area": "work", "what": "Two years in the same job", "kind": "condition"}],
            "risks": [{"area": "health", "what": "Medical emergency drains the fund", "likelihood": "medium",
                       "early_warning": "No health insurance", "mitigation": "Buy cover first"}]}),
            _use(6, "propose_plan", {
                "title": "Smaller house at 29", "target_date": "2028-05-10",
                "requirements": [{"area": "money", "what": "Down payment", "kind": "money", "amount": 1900000}]})],
            "tool_use") if seen["t3"]["emi"] == "62483" and seen["t3"]["within_usual_bank_limit"] is False
        else pytest.fail(f"EMI came from the tool? {seen}"),
        _resp([{"type": "text", "text": "As planned it doesn't fit; two options below."}], "end_turn"),
    ]))
    r = client.post("/api/plan-chat", headers=user["headers"],
                    json={"message": "House at 29, wedding at 30, kids by 32"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["plan_ids"]) == 2 and body["latest_plan"]["title"] == "Smaller house at 29"
    first = client.get(f"/api/life-plans/{body['plan_ids'][0]}", headers=user["headers"]).json()
    assert first["status"] == "draft" and first["verdict"] == "doesnt_fit"
    assert first["risks"][0]["early_warning"] == "No health insurance"
    assert client.get("/api/life-plans", headers=user["headers"]).json() == []       # drafts aren't active
    ok = client.post(f"/api/life-plans/{body['plan_ids'][1]}/accept", headers=user["headers"]).json()
    assert ok["status"] == "active"
    assert client.get(f"/api/life-plans/{body['plan_ids'][0]}", headers=user["headers"]).json()["status"] == "dropped"
    # What the person told the planner is remembered and shown as theirs.
    ctx = __import__("asyncio").run(plan_assistant.get_context(server.db, {"id": user["id"]}))
    dob = next(f for f in ctx["facts"] if f["key"] == "date_of_birth")
    assert (dob["value"], dob["source"]) == ("1999-05-10", "you told Hymn")
    hist = client.get(f"/api/plan-chat/{body['chat_id']}", headers=user["headers"]).json()["turns"]
    assert [t["role"] for t in hist] == ["user", "assistant"]


def test_tool_errors_go_back_to_the_ai_and_outages_keep_nothing(client, server, user, monkeypatch):
    monkeypatch.setattr(plan_assistant, "call_model", FakeAI([
        _resp([_use(1, "propose_plan", {"title": "X", "target_date": "someday", "requirements": [
            {"area": "money", "what": "Y", "kind": "money", "amount": 10}]})], "tool_use"),
        lambda seen: _resp([{"type": "text", "text": "Which date?"}], "end_turn")
        if seen["t1"].get("is_error") else pytest.fail("error not passed back"),
    ]))
    r = client.post("/api/plan-chat", headers=user["headers"], json={"message": "plan X"})
    assert r.json()["reply"] == "Which date?"

    async def down(*a, **k):
        raise AssistantUnavailable("offline")
    monkeypatch.setattr(plan_assistant, "call_model", down)
    r2 = client.post("/api/plan-chat", headers=user["headers"], json={"message": "again", "chat_id": r.json()["chat_id"]})
    assert r2.status_code == 503
    turns = client.get(f"/api/plan-chat/{r.json()['chat_id']}", headers=user["headers"]).json()["turns"]
    assert [t["text"] for t in turns] == ["plan X", "Which date?"]


def test_pure_tools():
    fc = plan_assistant.future_cost(1000000, "2029-11-17", date(2026, 11, 17))
    assert abs(int(fc["amount_then"]) - 1191016) < 100 and fc["years"] == "3.0"   # ₹10L at 6% for 3 years
    la = plan_assistant.loan_affordability(4000000, 8.5, 240, 150000)
    assert la["within_usual_bank_limit"] is True and la["share_of_income_percent"] == "23"
