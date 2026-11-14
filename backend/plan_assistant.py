"""The planning assistant: a conversation that turns any ask into a checked plan.

The AI (Opus) talks, asks and reasons; it never computes numbers about the
person or invents free time. It must call tools for that:

* ``get_context``: what Hymn knows about the person, each fact with its
  source (money book, planned money, time blocks, family, what they told
  Hymn). Facts the person corrects win.
* ``remember_fact``: store a correction or answer ("I'm 27", "take-home is
  ₹1.2L", "partner works").
* ``find_time``: real free slots.
* ``check_money``: an amount by a date → available now / by T−1 / status.
* ``future_cost``: today's price at a later date (inflation).
* ``loan_affordability``: EMI for a loan and what share of income it is.
* ``propose_plan``: saves the plan (what must go right, what may stop it)
  as a draft and returns the engine's benchmark and verdict. Every option
  the AI offers goes through it.

Nothing becomes active until the person accepts a plan
(``POST /api/life-plans/{id}/accept``).
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import date as date_type, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, List, Optional

import anthropic
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import claude_client
import life_plans
from claude_client import AssistantUnavailable
from deps import get_current_user, get_db

logger = logging.getLogger(__name__)
plan_chat_router = APIRouter(prefix="/plan-chat", tags=["plan-chat"])

MODEL = os.environ.get("HYMN_PLANNING_MODEL") or "claude-opus-5-5"
MAX_STEPS = 12
INFLATION = Decimal("0.06")
EMI_SHARE_LIMIT = Decimal("0.50")
WEB_SEARCH = {"type": "web_search_20260209", "name": "web_search", "max_uses": 3}

SYSTEM = """You are Hymn's planner. You help one person plan anything — from "45 minutes of guitar this
week" to "a house at 29, a wedding at 30, a child by 32" — honestly and holistically.

How you work:
1. Understand the ask: what, by when (a target date T), which areas it touches (money, health, family &
   relationships, learning, work, time). Small asks (only time, this week): skip to find_time and offer
   slots. Big asks: ask at most 3 short questions you truly need (city, rough budget, partner, health
   situation…) before planning.
2. Call get_context and show the person, briefly, what you're assuming about them; invite corrections.
   Save corrections and answers with remember_fact.
3. Work out WHAT MUST GO RIGHT (requirements) and WHAT MAY STOP IT (risks), across every area the goal
   touches — not just money. A child is health, family, work, time and money. Requirements are time
   (minutes), money (an amount by a date) or conditions only the person can confirm.
4. Call propose_plan. It benchmarks every requirement against what's available now and what can be
   built up by T−1, and returns a verdict. Report it plainly: what's covered now, by then, short by how
   much, and what's unknown.
5. If it doesn't fit, offer 2–3 concrete options (change order, amount, date, scope) and check EACH
   with propose_plan before presenting it.

Checklists: for buying a house, a wedding or a first child, call use_template first and start from its
requirements and risks (fill in amounts from what the person tells you); anything you add beyond it, say is
your suggestion. If a checklist says reviewed: false, tell the person it is a draft still being checked by an
expert.

Rules you never break:
- Never state a number about the person's money or time unless a tool gave it to you. Never do
  arithmetic yourself: use future_cost, loan_affordability, check_money, find_time, propose_plan.
- Prices you look up on the web are estimates: say so and give the source.
- Health: help them prepare (check-ups, timing questions to raise, insurance) and always say to confirm
  with their doctor. No diagnoses, no medical instructions.
- Money: no specific products (no fund, stock or policy names to buy). Talk about amounts and timing.
- Never promise outcomes you can't control (e.g. a pregnancy date). Say "prepare by", not "will".
- Be short, warm and concrete. Plain words, no jargon. Indian context (₹, lakh, crore) unless told
  otherwise."""

TOOLS = [
    {"name": "get_context", "description": "What Hymn knows about the person, each fact with its source.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "remember_fact", "description": "Save a fact the person told you or corrected.",
     "input_schema": {"type": "object", "properties": {
         "key": {"type": "string", "description": "snake_case, e.g. date_of_birth, monthly_take_home, city"},
         "value": {"type": "string"}, "label": {"type": "string"}}, "required": ["key", "value"]}},
    {"name": "find_time", "description": "Real free slots of at least `minutes` before `by`.",
     "input_schema": {"type": "object", "properties": {
         "minutes": {"type": "integer"}, "by": {"type": "string", "description": "YYYY-MM-DD"},
         "earliest": {"type": "string", "description": "HH:MM"}, "latest": {"type": "string"},
         "weekdays": {"type": "array", "items": {"type": "string"}}}, "required": ["minutes", "by"]}},
    {"name": "check_money", "description": "Is this amount available now, or by the month before `by`?",
     "input_schema": {"type": "object", "properties": {
         "amount": {"type": "number"}, "by": {"type": "string"}, "currency": {"type": "string"}},
         "required": ["amount", "by"]}},
    {"name": "future_cost", "description": "Today's price at a future date with inflation (default 6%/yr).",
     "input_schema": {"type": "object", "properties": {
         "amount_today": {"type": "number"}, "on": {"type": "string"},
         "inflation_percent": {"type": "number"}}, "required": ["amount_today", "on"]}},
    {"name": "loan_affordability", "description": "EMI for a loan and its share of monthly income.",
     "input_schema": {"type": "object", "properties": {
         "principal": {"type": "number"}, "annual_rate_percent": {"type": "number"},
         "tenure_months": {"type": "integer"}, "monthly_income": {"type": "number"}},
         "required": ["principal", "annual_rate_percent", "tenure_months", "monthly_income"]}},
    {"name": "use_template", "description": (
        "Checklist (requirements and risks with sources) for a big life event: house, wedding, first_child."),
     "input_schema": {"type": "object", "properties": {
         "key": {"type": "string", "enum": ["house", "wedding", "first_child"]},
         "params": {"type": "object", "description": "house: price, stamp_duty_percent, interiors; wedding: "
                    "budget, family_contribution; first_child: delivery_cost, monthly_child_cost"}},
         "required": ["key"]}},
    {"name": "propose_plan", "description": (
        "Save a plan as a draft and get the benchmark (available now / built up by T−1 / status per "
        "requirement) and verdict. Use for the main plan and for every option you offer."),
     "input_schema": {"type": "object", "properties": {
         "title": {"type": "string"}, "target_date": {"type": "string"},
         "requirements": {"type": "array", "items": {"type": "object", "properties": {
             "area": {"type": "string", "enum": list(life_plans.AREAS)}, "what": {"type": "string"},
             "kind": {"type": "string", "enum": ["time", "money", "condition"]}, "amount": {"type": "number"},
             "currency": {"type": "string"}, "needed_by": {"type": "string"}, "earliest": {"type": "string"},
             "latest": {"type": "string"}, "min_block": {"type": "integer"},
             "weekdays": {"type": "array", "items": {"type": "string"}}},
             "required": ["area", "what", "kind"]}},
         "risks": {"type": "array", "items": {"type": "object", "properties": {
             "area": {"type": "string", "enum": list(life_plans.AREAS)}, "what": {"type": "string"},
             "likelihood": {"type": "string", "enum": ["low", "medium", "high"]},
             "early_warning": {"type": "string"}, "mitigation": {"type": "string"}},
             "required": ["area", "what"]}}},
         "required": ["title", "target_date", "requirements"]}},
]


def _d(v: Any) -> Decimal:
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError):
        return Decimal(0)


def _money(d: Decimal) -> str:
    return format(d.quantize(Decimal("1")), "f")


# ---------------------------------------------------------------------------
# Pure tools
# ---------------------------------------------------------------------------

def future_cost(amount_today: Any, on: str, today: date_type, inflation_percent: Any = None) -> dict:
    rate = _d(inflation_percent) / 100 if inflation_percent not in (None, "") else INFLATION
    years = Decimal(max((date_type.fromisoformat(on) - today).days, 0)) / Decimal("365.25")
    value = _d(amount_today) * (1 + rate) ** int(years) * (1 + rate * (years - int(years)))
    return {"amount_today": _money(_d(amount_today)), "on": on, "inflation_percent": str(rate * 100),
            "years": f"{years:.1f}", "amount_then": _money(value)}


def loan_affordability(principal: Any, annual_rate_percent: Any, tenure_months: int, monthly_income: Any) -> dict:
    rows = life_plans_schedule(principal, annual_rate_percent, tenure_months)
    emi = _d(rows[0]["emi"]) if rows else Decimal(0)
    income = _d(monthly_income)
    share = (emi / income) if income else None
    return {"emi": _money(emi), "total_interest": _money(sum((_d(r["interest"]) for r in rows), Decimal(0))),
            "share_of_income_percent": f"{share * 100:.0f}" if share is not None else None,
            "within_usual_bank_limit": bool(share is not None and share <= EMI_SHARE_LIMIT),
            "bank_limit_note": "Banks usually keep all EMIs under about 50% of take-home pay."}


def life_plans_schedule(principal, rate, months):
    import life_objects
    return life_objects.loan_schedule({"loan_principal": str(principal), "annual_rate_percent": str(rate),
                                       "tenure_months": int(months), "first_emi_date": "2000-01-01"})


# ---------------------------------------------------------------------------
# Context: what Hymn knows (with sources)
# ---------------------------------------------------------------------------

async def get_context(db, user: dict) -> dict:
    import planned_money
    import reports
    from money_service import load_availability, monthly_actual_spending

    uid = user["id"]
    facts: List[dict] = []
    accounts = await db.financial_accounts.find({"user_id": uid}, {"_id": 0, "currency": 1}).to_list(length=None)
    currency = next((a["currency"] for a in accounts if a.get("currency")), "INR")
    avail = (await load_availability(db, uid))["by_currency"].get(currency, {})
    facts.append({"key": "available_to_spend", "label": "Money available to spend today",
                  "value": _money(Decimal(avail.get("available_unreserved", 0))), "source": "money book"})
    nw = await reports.net_worth_summary(db, uid, date_type.today().isoformat(), currency)
    facts.append({"key": "net_worth", "label": "Net worth", "value": _money(nw["net_worth"]),
                  "source": "money book and assets"})
    month = date_type.today().isoformat()[:7]
    past, m = [], month
    for _ in range(3):
        y, mm = int(m[:4]), int(m[5:7])
        m = f"{y - 1}-12" if mm == 1 else f"{y}-{mm - 1:02d}"
        past.append(await monthly_actual_spending(db, uid, m, currency))
    with_data = [x for x in past if x > 0]
    if with_data:
        facts.append({"key": "usual_monthly_spending", "label": "Usual monthly spending",
                      "value": _money(sum(with_data, Decimal(0)) / len(with_data)),
                      "source": f"last {len(with_data)} month(s) of spending"})
    t = planned_money.month_totals(await planned_money.load_items(db, uid), month, currency)
    if t["income"]:
        facts.append({"key": "monthly_take_home", "label": "Monthly take-home (planned income)",
                      "value": _money(t["income"]), "source": "planned money"})
    if t["spend"]:
        facts.append({"key": "monthly_bills", "label": "Monthly bills and EMIs (planned)",
                      "value": _money(t["spend"]), "source": "planned money"})
    loans = await db.life_objects.find({"user_id": uid, "type": "liability", "ended_on": None},
                                       {"_id": 0, "name": 1, "emi": 1, "loan_principal": 1}).to_list(length=None)
    if loans:
        facts.append({"key": "loans", "label": "Loans", "value": ", ".join(l["name"] for l in loans),
                      "source": "things you owe"})
    blocks = await db.time_commitments.find({"user_id": uid}, {"_id": 0}).to_list(length=None)
    monday = date_type.today() - timedelta(days=date_type.today().weekday())
    import time_reports
    plan = time_reports.planned(blocks, [], [monday + timedelta(days=i) for i in range(7)])
    committed = sum(sum(v.values()) for v in plan["lines"].values())
    facts.append({"key": "free_hours_per_week", "label": "Free hours a week (outside fixed blocks)",
                  "value": f"{(time_reports.WEEK - committed) / 60:.0f}", "source": "your time blocks"})
    member = await db.household_members.find_one({"user_id": uid, "status": "active"}, {"household_id": 1})
    if member:
        people = await db.household_members.find(
            {"household_id": member["household_id"], "status": "active", "user_id": {"$ne": uid}},
            {"_id": 0, "name": 1, "relation": 1}).to_list(length=None)
        if people:
            facts.append({"key": "family", "label": "Family in Hymn",
                          "value": ", ".join(f"{p['name']} ({p.get('relation') or 'family'})" for p in people),
                          "source": "family"})
    told = await db.user_facts.find({"user_id": uid}, {"_id": 0}).to_list(length=None)
    by_key = {f["key"]: f for f in facts}
    for f in told:
        by_key[f["key"]] = {"key": f["key"], "label": f.get("label") or f["key"].replace("_", " "),
                            "value": f["value"], "source": "you told Hymn"}
    return {"currency": currency, "today": date_type.today().isoformat(), "facts": list(by_key.values())}


# ---------------------------------------------------------------------------
# Running tools
# ---------------------------------------------------------------------------

async def run_tool(db, user: dict, chat: dict, name: str, args: dict) -> Any:
    uid = user["id"]
    if name == "get_context":
        return await get_context(db, user)
    if name == "remember_fact":
        await db.user_facts.update_one(
            {"user_id": uid, "key": args["key"]},
            {"$set": {"value": str(args["value"]), "label": args.get("label"),
                      "updated_at": datetime.now(timezone.utc).isoformat()}}, upsert=True)
        return {"saved": args["key"]}
    if name == "find_time":
        now = life_plans.local_now(user)
        by = date_type.fromisoformat(args["by"])
        days = [now.date() + timedelta(days=i) for i in range(max((by - now.date()).days, 0) + 1)][:62]
        blocks = await db.time_commitments.find({"user_id": uid}, {"_id": 0}).to_list(length=None)
        bookings = await db.resource_allocations.find(
            {"user_id": uid, "resource_type": "time", "status": {"$in": ["reserved", "consumed"]}},
            {"_id": 0}).to_list(length=None)
        slots = life_plans.free_slots(days, blocks, bookings, args.get("earliest") or life_plans.DEFAULT_EARLIEST,
                                      args.get("latest") or life_plans.DEFAULT_LATEST, int(args["minutes"]), now,
                                      args.get("weekdays"))
        return {"slots": slots[:8], "total_free_minutes": sum(s["minutes"] for s in slots)}
    if name == "check_money":
        m = await life_plans.money_by(db, uid, args.get("currency") or "INR", args["by"])
        need = _d(args["amount"])
        status = "now" if m["now"] >= need else "by_then" if m["by_then"] >= need else "short"
        return {"needed": _money(need), "available_now": _money(m["now"]),
                "built_up_by_month_before": _money(m["by_then"]), "status": status,
                "gap": _money(max(need - max(m["now"], m["by_then"]), Decimal(0)))}
    if name == "future_cost":
        return future_cost(args["amount_today"], args["on"], date_type.today(), args.get("inflation_percent"))
    if name == "loan_affordability":
        return loan_affordability(args["principal"], args["annual_rate_percent"], args["tenure_months"],
                                  args["monthly_income"])
    if name == "use_template":
        import plan_templates
        out = plan_templates.fill(user, args["key"], args.get("params") or {})
        return out or {"error": "No checklist for that yet; plan from first principles."}
    if name == "propose_plan":
        plan = await life_plans._save(db, uid, args["title"], args["target_date"], args["requirements"],
                                      args.get("risks") or [], status="draft", chat_id=chat["id"])
        evaluated = await life_plans._evaluated(db, uid, plan)
        chat.setdefault("plan_ids", []).append(plan["id"])
        return {"plan_id": plan["id"], "verdict": evaluated["verdict"],
                "requirements": [{k: r.get(k) for k in ("what", "area", "kind", "amount", "status",
                                                        "available_now", "built_up_by_then", "gap")}
                                 for r in evaluated["requirements"]]}
    return {"error": f"unknown tool {name}"}


def _dump(block) -> dict:
    return block.model_dump(exclude_none=True) if hasattr(block, "model_dump") else dict(block)


async def call_model(system: str, messages: List[dict], tools: List[dict]):
    """One model call (replaced by a fake in tests)."""
    client = claude_client.get_client()
    try:
        return await client.beta.messages.create(
            model=MODEL, max_tokens=8000, system=system, messages=messages, tools=tools,
            output_config={"effort": "high"}, **claude_client.fallback_kwargs(MODEL))
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
        raise claude_client.unavailable_from(exc) from exc


async def converse(db, user: dict, chat: dict, text: str) -> str:
    """Add the person's message, let the AI work with its tools, return its reply."""
    chat["messages"].append({"role": "user", "content": text})
    for _ in range(MAX_STEPS):
        response = await call_model(SYSTEM, chat["messages"], TOOLS + [WEB_SEARCH])
        content = [_dump(b) for b in response.content]
        chat["messages"].append({"role": "assistant", "content": content})
        if response.stop_reason == "pause_turn":
            continue
        uses = [b for b in content if b.get("type") == "tool_use"]
        if response.stop_reason == "tool_use" and uses:
            results = []
            for u in uses:
                try:
                    out = await run_tool(db, user, chat, u["name"], u.get("input") or {})
                    results.append({"type": "tool_result", "tool_use_id": u["id"], "content": json.dumps(out)})
                except (HTTPException, ValueError, KeyError) as exc:
                    detail = getattr(exc, "detail", None) or str(exc)
                    results.append({"type": "tool_result", "tool_use_id": u["id"], "is_error": True,
                                    "content": f"Couldn't do that: {detail}"})
            chat["messages"].append({"role": "user", "content": results})
            continue
        reply = "".join(b.get("text", "") for b in content if b.get("type") == "text").strip()
        if not reply:
            raise AssistantUnavailable("empty answer")
        return reply
    raise AssistantUnavailable("too many steps")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    chat_id: Optional[str] = None


@plan_chat_router.post("")
async def chat(body: ChatMessage, current_user: dict = Depends(get_current_user)):
    db = get_db()
    if body.chat_id:
        convo = await db.plan_chats.find_one({"id": body.chat_id, "user_id": current_user["id"]}, {"_id": 0})
        if not convo:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        convo = {"id": str(uuid.uuid4()), "user_id": current_user["id"], "messages": [], "plan_ids": [],
                 "created_at": datetime.now(timezone.utc).isoformat()}
    before = list(convo["messages"])
    try:
        reply = await converse(db, current_user, convo, body.message)
    except AssistantUnavailable:
        convo["messages"] = before  # nothing half-done is kept
        raise HTTPException(status_code=503, detail="The planner is unavailable right now. Try again in a minute.")
    convo["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.plan_chats.replace_one({"id": convo["id"]}, convo, upsert=True)
    latest = None
    if convo["plan_ids"]:
        p = await db.life_plans.find_one({"id": convo["plan_ids"][-1], "user_id": current_user["id"]}, {"_id": 0})
        if p:
            latest = await life_plans._evaluated(db, current_user["id"], p)
    return {"chat_id": convo["id"], "reply": reply, "latest_plan": latest,
            "plan_ids": convo["plan_ids"]}


@plan_chat_router.get("/{chat_id}")
async def history(chat_id: str, current_user: dict = Depends(get_current_user)):
    """The conversation as the person saw it (text turns only)."""
    convo = await get_db().plan_chats.find_one({"id": chat_id, "user_id": current_user["id"]}, {"_id": 0})
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found")
    turns = []
    for m in convo["messages"]:
        if isinstance(m["content"], str):
            turns.append({"role": m["role"], "text": m["content"]})
        else:
            text = "".join(b.get("text", "") for b in m["content"] if b.get("type") == "text").strip()
            if text and m["role"] == "assistant":
                turns.append({"role": "assistant", "text": text})
    return {"chat_id": chat_id, "turns": turns, "plan_ids": convo.get("plan_ids", [])}


async def ensure_plan_chat_indexes(db) -> None:
    await db.plan_chats.create_index("id", unique=True)
    await db.user_facts.create_index([("user_id", 1), ("key", 1)], unique=True)
