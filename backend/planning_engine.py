"""Hymn Planning Engine — Conversational.

Reformed from the deterministic analyze → confirm → generate → approve
pipeline to a **single conversational thread per (target_type, target_id)**
that enriches the existing Goal or Project rather than creating parallel
planning objects.

Design highlights
-----------------
* One ``plan_conversations`` doc per (user, target_type, target_id). Messages
  and any proposed changes are appended atomically.
* The LLM (Anthropic Claude Sonnet 4.5 via emergentintegrations) is invoked
  with the Anthropic ``web_search`` provider-hosted tool enabled so the model
  can ground its recommendations. The tool executes on the API side; we
  never surface tool calls or raw JSON to the UI.
* The assistant reply is split into a *prose* section (what the UI shows)
  and a *structured proposal* section (parsed on the server, hidden from the
  UI). The structured proposal is stored on the message so the UI can render
  an "Apply changes" card next to the assistant bubble.
* ``POST .../materialize`` applies the proposal into the target Goal/Project
  by creating or updating existing expected_outcomes / tasks / check-ins /
  goal cadence in an atomic pass, with per-action idempotency.

Endpoints
---------
* ``GET  /planning/{target_type}/{target_id}/conversation``  — get or create.
* ``POST /planning/{target_type}/{target_id}/messages``      — user turn.
* ``POST /planning/{target_type}/{target_id}/reset``         — start over.
* ``POST /planning/conversations/{id}/materialize``           — apply proposal.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from deps import get_current_user, get_db

load_dotenv()
logger = logging.getLogger(__name__)

planning_router = APIRouter(prefix="/planning", tags=["planning"])

TARGET_TYPES = ("goal", "project")

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


def _require(cond: bool, msg: str, code: int = 400) -> None:
    if not cond:
        raise HTTPException(status_code=code, detail=msg)


def _iso_date(v: Any) -> Optional[str]:
    if not isinstance(v, str) or not v:
        return None
    try:
        datetime.strptime(v, "%Y-%m-%d")
        return v
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Context snapshot — kept small so we don't blow the LLM context.
# ---------------------------------------------------------------------------


async def _read_target(db, user_id: str, target_type: str, target_id: str) -> dict:
    coll = {"goal": "goals", "project": "projects"}.get(target_type)
    _require(coll is not None, f"Unsupported target_type: {target_type}")
    doc = await db[coll].find_one({"id": target_id, "user_id": user_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"{target_type.title()} not found")
    return doc


async def _read_context(db, user_id: str, target_type: str, target_id: str) -> Dict[str, Any]:
    """Portfolio-aware context: target + existing outcomes/tasks/check-ins +
    other active goals/projects + time commitments + rough weekly capacity.
    Kept compact so we don't blow the LLM context window."""
    target = await _read_target(db, user_id, target_type, target_id)
    if target_type == "goal":
        outcomes = await db.expected_outcomes.find(
            {"user_id": user_id, "goal_id": target_id}, {"_id": 0},
        ).to_list(length=200)
        eo_ids = [e["id"] for e in outcomes]
        tasks = await db.tasks.find(
            {"user_id": user_id, "expected_outcome_id": {"$in": eo_ids}}, {"_id": 0},
        ).to_list(length=500) if eo_ids else []
        checkins = await db.checkins.find(
            {"user_id": user_id, "goal_id": target_id}, {"_id": 0},
        ).sort("created_at", -1).to_list(length=25)
    else:  # project
        outcomes = []
        tasks = await db.tasks.find(
            {"user_id": user_id, "project_id": target_id}, {"_id": 0},
        ).to_list(length=500)
        checkins = await db.checkins.find(
            {"user_id": user_id, "project_id": target_id}, {"_id": 0},
        ).sort("created_at", -1).to_list(length=25)

    # ---- Portfolio-wide context (other active goals, projects, time) ------
    other_goals = await db.goals.find(
        {"user_id": user_id, "id": {"$ne": target_id if target_type == "goal" else None},
         "status": {"$in": ["active", "paused"]}},
        {"_id": 0},
    ).to_list(length=200)
    other_projects = await db.projects.find(
        {"user_id": user_id, "id": {"$ne": target_id if target_type == "project" else None},
         "status": {"$in": ["active", "paused"]}},
        {"_id": 0},
    ).to_list(length=200)

    # Time commitments (recurring weekly). Only include currently-effective
    # ones (effective_from <= today AND (effective_until is null or >= today)).
    today = datetime.now(timezone.utc).date().isoformat()
    time_commitments = await db.time_commitments.find(
        {"user_id": user_id, "effective_from": {"$lte": today}},
        {"_id": 0},
    ).to_list(length=500)
    time_commitments = [
        tc for tc in time_commitments
        if not tc.get("effective_until") or tc["effective_until"] >= today
    ]

    # Rough weekly capacity: 168h/week - sum(committed hours from time_commitments).
    def _minutes(hhmm: str) -> int:
        try:
            h, m = hhmm.split(":")
            return int(h) * 60 + int(m)
        except Exception:
            return 0
    weekly_committed_minutes = 0
    for tc in time_commitments:
        weekly_committed_minutes += max(0, _minutes(tc.get("end_time", "0:0")) - _minutes(tc.get("start_time", "0:0")))
    weekly_capacity = {
        "committed_hours_per_week": round(weekly_committed_minutes / 60.0, 1),
        "free_hours_per_week_estimate": max(0.0, round(168 - weekly_committed_minutes / 60.0, 1)),
    }

    # Count active tasks with due dates across the user (workload heat).
    upcoming_task_count = await db.tasks.count_documents({
        "user_id": user_id,
        "status": {"$nin": ["done", "cancelled"]},
        "due_date": {"$ne": ""},
    })

    return {
        "target_type": target_type,
        "target": {
            "id": target["id"],
            "title": target.get("title"),
            "notes": (target.get("notes") or "")[:1000],
            "deadline": target.get("deadline") or target.get("target_end_date") or "",
            "status": target.get("status"),
            "priority": target.get("priority"),
            "checkin_cadence": target.get("checkin_cadence") or "",
            "journey_type": target.get("journey_type") or "",
            "commitment_type": target.get("commitment_type") or "postponable",
        },
        "expected_outcomes": [
            {"id": e["id"], "title": e.get("title"), "status": e.get("status"),
             "target_value": e.get("target_value"), "current_value": e.get("current_value"),
             "unit": e.get("unit"), "deadline": e.get("deadline")}
            for e in outcomes
        ],
        "tasks": [
            {"id": t["id"], "title": t.get("title"), "status": t.get("status"),
             "priority": t.get("priority"), "due_date": t.get("due_date"),
             "expected_outcome_id": t.get("expected_outcome_id"),
             "commitment_type": t.get("commitment_type") or "postponable"}
            for t in tasks
        ],
        "checkins_recent": [
            {"date": c.get("date"), "title": c.get("title"), "notes": (c.get("notes") or "")[:200]}
            for c in checkins
        ],
        "other_goals": [
            {"id": g["id"], "title": g.get("title"), "domain_name": g.get("domain_name") or "",
             "deadline": g.get("deadline"), "status": g.get("status"),
             "commitment_type": g.get("commitment_type") or "postponable",
             "checkin_cadence": g.get("checkin_cadence") or ""}
            for g in other_goals
        ],
        "other_projects": [
            {"id": p["id"], "title": p.get("title"),
             "start_date": p.get("start_date"), "target_end_date": p.get("target_end_date"),
             "status": p.get("status"),
             "commitment_type": p.get("commitment_type") or "postponable"}
            for p in other_projects
        ],
        "time_commitments": [
            {"id": tc["id"], "title": tc.get("title"),
             "day_of_week": tc.get("day_of_week"), "start_time": tc.get("start_time"),
             "end_time": tc.get("end_time"), "commitment_type": tc.get("commitment_type"),
             "flexibility": tc.get("flexibility") or "flexible"}
            for tc in time_commitments
        ],
        "weekly_capacity": weekly_capacity,
        "upcoming_task_count": upcoming_task_count,
    }


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are Hymn's Planning Copilot — a warm, practical, senior coach who
helps the user decompose a Goal or Project into concrete Expected Outcomes,
Tasks, and Check-ins that enrich what they already have. You do NOT create
new goals or parallel plans; you always add to (or refine) the existing
target the user is planning.

You have access to the `web_search` tool. Use it sparingly and only when a
question would genuinely benefit from up-to-date external information
(e.g. current best practices for a professional certification, syllabus for
a course, benchmark timelines). Never invent citations. If web_search is
unavailable or returns nothing useful, say so plainly and keep going with
what you know.

CAPACITY & PORTFOLIO AWARENESS (CRITICAL):
You are given the user's OTHER active goals, projects, and weekly TIME
COMMITMENTS in the context prelude. Before proposing new work, quickly
consider whether the user has the time / mental bandwidth for it.
- Rough weekly free capacity is provided; typical sustainable output is
  ~8–15 hours/week on optional pursuits after work + sleep + routines.
- If the plan you're about to propose would exceed the user's realistic
  free capacity given everything else running, DO NOT silently pretend
  it fits. Tell the user honestly, name 1–3 SPECIFIC other items in
  their portfolio that could be POSTPONED or CANCELLED to make room,
  and offer them the choice. NEVER suggest touching items whose
  commitment_type is "exclusive" (a booked movie ticket, a scheduled
  surgery, a fixed exam date) — those are non-negotiable; find room
  elsewhere or advise scaling this new plan down.

LIFE PATTERNS (VERY IMPORTANT):
Watch for the user casually mentioning recurring life patterns —
"I work a job from 10 to 6 all weekdays", "I have pilates every morning",
"I sleep by 11", "I pick up my kid at 4 on Wednesdays", "I fast on
Tuesdays". If they mention a pattern that is NOT already in their
existing time_commitments:
  • If you have enough info (title, day(s), start & end time), include it
    in the proposal block under `time_commitments`.
  • If key info is missing (e.g. they said "pilates every morning" — you
    know title=Pilates but not the exact time), ASK ONE clarifying
    question in the prose section, and DO NOT include it in the
    proposal block yet. Add it on the next turn when the user replies.

RESPONSE FORMAT (STRICT):
Every response has TWO parts:

1) A short conversational reply for the user (Markdown, 2–5 short
   paragraphs, warm and specific, no headers "## Section" style). Reference
   what they already have when relevant. Ask ONE focused follow-up question
   when needed. Never expose tool calls, JSON, or your own reasoning steps.

2) If (and only if) you are proposing concrete changes, append a
   machine-readable block on its own line at the very end of the message:

<<<HYMN_PROPOSAL>>>
{"summary": "one-line human summary",
 "feasibility_note": "one short line if capacity is tight, otherwise omit",
 "expected_outcomes": [{"title": "...", "target_value": "", "unit": "",
                         "deadline": "YYYY-MM-DD or empty",
                         "outcome_type": "generic"}],
 "tasks": [{"title": "...",
             "expected_outcome_title": "match one of the above OR an existing outcome title (case-insensitive)",
             "due_date": "YYYY-MM-DD or empty",
             "priority": "low|medium|high",
             "commitment_type": "postponable|exclusive",
             "notes": "optional short note"}],
 "checkins": [{"type": "goal|project|life",
                "title": "one-line label",
                "date": "YYYY-MM-DD",
                "time": "HH:MM",
                "expected_outcome_title": "for goal type — existing OR newly proposed outcome title",
                "project_id": "for project type — the current target id",
                "notes": "optional short note"}],
 "checkin_recurrences": [{"type": "goal|project|life",
                           "title": "Studies for CA",
                           "start_date": "YYYY-MM-DD",
                           "end_date":   "YYYY-MM-DD",
                           "days_of_week": ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"],
                           "time": "HH:MM",
                           "expected_outcome_title": "for goal type",
                           "project_id": "for project type",
                           "notes": "optional short note"}],
 "existing_item_updates": [{"kind": "goal|project|task",
                             "id": "existing id from context",
                             "patch": {"title": "…", "notes": "…",
                                        "priority": "low|medium|high",
                                        "status": "active|paused|abandoned|completed|todo|in_progress|done|cancelled",
                                        "due_date": "YYYY-MM-DD",
                                        "deadline": "YYYY-MM-DD"}}],
 "existing_item_changes": [{"kind": "goal|project|task",
                             "id": "existing id from context",
                             "action": "postpone|cancel",
                             "new_due_date": "YYYY-MM-DD if postpone, else omit",
                             "reason": "one short line"}],
 "consolidations": [{"kind": "goal|project",
                      "candidate_ids": ["id1", "id2", …],
                      "reason": "why these look like duplicates in one line"}],
 "time_commitments": [{"title": "e.g. Job",
                        "day_of_week": "monday|tuesday|…|sunday",
                        "start_time": "HH:MM (24h)",
                        "end_time": "HH:MM (24h)",
                        "commitment_type": "work|sleep|commute|study|meal|caregiving|household|health|personal|other",
                        "flexibility": "fixed|flexible",
                        "notes": "optional"}],
 "checkin_cadence": "daily|weekly|monthly|manual OR omit",
 "target_updates": {"deadline": "YYYY-MM-DD or omit",
                     "notes": "optional refined why/description or omit",
                     "commitment_type": "postponable|exclusive OR omit"}}
<<<END>>>

Rules for the proposal block:
- Only propose additions/refinements to the current target — never delete
  its existing items.
- For Goals: tasks MUST attach to a proposed or existing expected_outcome.
- For Projects: tasks attach directly to the project (leave
  expected_outcome_title empty).
- Keep it tight: 1–6 new outcomes and 1–20 new tasks per turn — smaller is better.
- If the user is just asking a question or exploring, DO NOT include the
  proposal block. Only include it when proposing concrete additions.
- `existing_item_changes` and `existing_item_updates` must reference the
  EXACT id of a real item from the context prelude, and the item MUST NOT
  have commitment_type="exclusive" — Hymn will refuse to apply changes
  to exclusive items on the server side.
- `checkin_recurrences` are expanded server-side into one check-in per
  matching day within [start_date, end_date] (including backfill into
  the past if the range straddles today). Prefer a recurrence over
  emitting 30 individual checkins.
- `consolidations`: whenever you notice two or more items in the
  portfolio that appear to be duplicates (near-identical titles, same
  domain, overlapping outcomes), propose a consolidation. Provide ALL
  candidate ids. Hymn will pick the richest survivor automatically
  based on metadata density; you do NOT need to pick the survivor.
- `time_commitments` should only be added when the user's message
  clearly established a recurring life pattern with an explicit or
  strongly-implied start/end time.
- All dates must be ISO YYYY-MM-DD. All times HH:MM (24-hour).
- Never wrap the proposal in code fences. Emit it verbatim, exactly once,
  as the final content of your message.

You are talking directly to the user. Do not narrate your process."""


_PROPOSAL_RE = re.compile(
    r"<<<HYMN_PROPOSAL>>>\s*(\{.*?\})\s*<<<END>>>", re.DOTALL,
)


def _split_message(raw: str) -> Tuple[str, Optional[dict]]:
    """Split an assistant reply into (visible_prose, structured_proposal_or_None)."""
    if not raw:
        return "", None
    m = _PROPOSAL_RE.search(raw)
    if not m:
        return raw.strip(), None
    prose = _PROPOSAL_RE.sub("", raw).strip()
    try:
        proposal = json.loads(m.group(1))
        if isinstance(proposal, dict):
            return prose, proposal
    except json.JSONDecodeError:
        pass
    return prose, None


def _context_prelude(ctx: Dict[str, Any]) -> str:
    """Serialize the small context snapshot into a compact system prelude."""
    t = ctx["target"]
    lines = [
        f"CURRENT TARGET ({ctx['target_type'].upper()}):",
        f"- id: {t['id']}",
        f"- title: {t.get('title')}",
        f"- deadline: {t.get('deadline') or '—'}",
        f"- status: {t.get('status') or 'active'}",
        f"- commitment_type: {t.get('commitment_type') or 'postponable'}",
        f"- check-in cadence: {t.get('checkin_cadence') or '—'}",
    ]
    if t.get("journey_type"):
        lines.append(f"- journey type: {t['journey_type']}")
    if t.get("notes"):
        lines.append(f"- notes: {t['notes'][:300]}")
    if ctx["expected_outcomes"]:
        lines.append("\nEXISTING EXPECTED OUTCOMES (on this target):")
        for e in ctx["expected_outcomes"][:20]:
            lines.append(f"- {e['title']} (status={e['status']}, {e.get('current_value','')}/{e.get('target_value','') or '—'} {e.get('unit') or ''})")
    if ctx["tasks"]:
        lines.append(f"\nEXISTING TASKS on this target ({len(ctx['tasks'])}, first 20 shown):")
        for tk in ctx["tasks"][:20]:
            lines.append(f"- {tk['title']} [{tk['status']}, {tk.get('priority')}, commitment={tk.get('commitment_type')}]")
    if ctx["checkins_recent"]:
        lines.append(f"\nRECENT CHECK-INS on this target: {len(ctx['checkins_recent'])} in the last window.")

    # ---- Portfolio view -------------------------------------------------
    other_goals = ctx.get("other_goals") or []
    other_projects = ctx.get("other_projects") or []
    if other_goals:
        lines.append(f"\nOTHER ACTIVE GOALS ({len(other_goals)}, first 15):")
        for g in other_goals[:15]:
            lines.append(
                f"- id={g['id']} · {g['title']} · domain={g.get('domain_name') or '—'}"
                f" · deadline={g.get('deadline') or '—'} · status={g.get('status')}"
                f" · commitment={g.get('commitment_type')}"
                f" · cadence={g.get('checkin_cadence') or '—'}"
            )
    if other_projects:
        lines.append(f"\nOTHER ACTIVE PROJECTS ({len(other_projects)}, first 15):")
        for p in other_projects[:15]:
            lines.append(
                f"- id={p['id']} · {p['title']} · {p.get('start_date') or '—'}→{p.get('target_end_date') or '—'}"
                f" · status={p.get('status')} · commitment={p.get('commitment_type')}"
            )
    tcs = ctx.get("time_commitments") or []
    if tcs:
        lines.append(f"\nWEEKLY TIME COMMITMENTS ({len(tcs)}):")
        for tc in tcs[:30]:
            lines.append(
                f"- {tc['title']} · {tc['day_of_week']} {tc['start_time']}–{tc['end_time']}"
                f" · type={tc.get('commitment_type')} · flexibility={tc.get('flexibility')}"
            )
    else:
        lines.append("\nWEEKLY TIME COMMITMENTS: none recorded yet. Ask contextual questions if the user mentions a recurring life pattern.")
    wc = ctx.get("weekly_capacity") or {}
    if wc:
        lines.append(
            f"\nWEEKLY CAPACITY (rough): {wc.get('committed_hours_per_week', 0)}h committed to routines,"
            f" ~{wc.get('free_hours_per_week_estimate', 0)}h remaining before sleep/breaks/other goals."
        )
    tc_up = ctx.get("upcoming_task_count", 0)
    if tc_up:
        lines.append(f"CURRENT WORKLOAD: {tc_up} open tasks with due dates across the whole portfolio.")

    # ---- Duplicate hints (naive title-similarity across ALL goals/projects)
    def _norm(s: str) -> str:
        import re as _re
        return _re.sub(r"\s+", " ", (s or "").strip().lower())
    all_g = other_goals + ([{"id": t["id"], "title": t.get("title"), "commitment_type": t.get("commitment_type")}] if ctx["target_type"] == "goal" else [])
    all_p = other_projects + ([{"id": t["id"], "title": t.get("title"), "commitment_type": t.get("commitment_type")}] if ctx["target_type"] == "project" else [])
    dup_hints: List[str] = []
    for pool, kind in ((all_g, "goal"), (all_p, "project")):
        seen: Dict[str, List[str]] = {}
        for item in pool:
            key = _norm(item.get("title") or "")
            if not key:
                continue
            # very simple: exact-normalized-title clusters
            seen.setdefault(key, []).append(item["id"])
            # also cluster on trimmed prefixes (first 4 words)
            short = " ".join(key.split()[:4])
            if short and short != key:
                seen.setdefault(short, []).append(item["id"])
        for key, ids in seen.items():
            if len(set(ids)) > 1:
                dup_hints.append(f"- possible duplicate {kind}s: {list(set(ids))} (title fragment ‘{key}’)")
    if dup_hints:
        lines.append("\nPOSSIBLE DUPLICATES (title heuristic, verify before proposing consolidation):")
        lines.extend(dup_hints[:20])
    return "\n".join(lines)


async def _call_llm(history: List[Dict[str, str]], user_text: str, ctx: Dict[str, Any]) -> str:
    """Non-streaming LLM turn with Anthropic web_search enabled.

    Returns the assistant's raw text (still containing any HYMN_PROPOSAL
    block). Raises HTTPException on any provider error so the caller can
    surface a friendly message to the user."""
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        raise HTTPException(status_code=500,
                            detail="Planning is unavailable — LLM key not configured.")
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage  # noqa: WPS433
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500,
                            detail=f"Planning is unavailable — {type(exc).__name__}")

    # Rebuild history as simplified messages [{role, content}]. We drop any
    # HYMN_PROPOSAL blocks from prior assistant messages before feeding the
    # LLM — the model doesn't need to see its own machine block.
    initial = [{"role": "system", "content": _SYSTEM_PROMPT + "\n\n" + _context_prelude(ctx)}]
    for msg in history:
        role = msg.get("role")
        content = msg.get("content") or ""
        if role == "assistant":
            content, _ = _split_message(content)
        if role in ("user", "assistant") and content.strip():
            initial.append({"role": role, "content": content})

    chat = LlmChat(
        api_key=api_key,
        session_id=f"planning-{ctx['target_type']}-{ctx['target']['id']}",
        system_message=initial[0]["content"],
        initial_messages=initial,
    ).with_model("anthropic", "claude-sonnet-4-6")

    # Attach Anthropic web_search tool. Provider-hosted tool → results are
    # applied on the API side; we get the final assistant text back on
    # response.content.
    try:
        chat.with_tools([
            {"type": "web_search_20250305", "name": "web_search", "max_uses": 3},
        ])
    except Exception:
        # If tools API is unavailable, continue without web search.
        pass

    try:
        response = await chat.send_message_with_tools(UserMessage(text=user_text))
    except Exception as exc:
        logger.exception("Planning LLM call failed")
        raise HTTPException(status_code=502,
                            detail=f"Planning assistant temporarily unavailable ({type(exc).__name__}).")

    text = response.content or ""
    return text.strip()


# ---------------------------------------------------------------------------
# Conversation persistence
# ---------------------------------------------------------------------------


async def _get_or_create_conversation(db, user_id: str, target_type: str, target_id: str) -> dict:
    _require(target_type in TARGET_TYPES, f"target_type must be one of {list(TARGET_TYPES)}")
    await _read_target(db, user_id, target_type, target_id)  # ownership + existence
    doc = await db.plan_conversations.find_one(
        {"user_id": user_id, "target_type": target_type, "target_id": target_id},
        {"_id": 0},
    )
    if doc:
        return doc
    now = _now()
    doc = {
        "id": _uuid(),
        "user_id": user_id,
        "target_type": target_type,
        "target_id": target_id,
        "messages": [],
        "created_at": now,
        "updated_at": now,
    }
    await db.plan_conversations.insert_one(doc)
    doc.pop("_id", None)
    return doc


async def _save_conversation(db, conv: dict) -> None:
    conv["updated_at"] = _now()
    await db.plan_conversations.replace_one(
        {"id": conv["id"]}, dict(conv), upsert=True,
    )


def _shape_message(msg: dict) -> dict:
    """Public shape sent to the UI (never leaks the HYMN_PROPOSAL block into
    the visible content)."""
    role = msg.get("role")
    content = msg.get("content") or ""
    proposal = msg.get("proposal")
    if role == "assistant":
        content, _ = _split_message(content)
    return {
        "id": msg.get("id") or _uuid(),
        "role": role,
        "content": content,
        "created_at": msg.get("created_at"),
        "proposal": proposal,  # may be None
        "materialized_at": msg.get("materialized_at"),
        "materialized_summary": msg.get("materialized_summary"),
    }


def _public_conversation(conv: dict) -> dict:
    return {
        "id": conv["id"],
        "target_type": conv["target_type"],
        "target_id": conv["target_id"],
        "created_at": conv["created_at"],
        "updated_at": conv["updated_at"],
        "messages": [_shape_message(m) for m in (conv.get("messages") or [])],
    }


# ---------------------------------------------------------------------------
# Materialization — atomic apply of a proposal into the target.
# ---------------------------------------------------------------------------

VALID_PRIORITIES = {"low", "medium", "high"}
VALID_CADENCES = {"daily", "weekly", "monthly", "manual"}
VALID_COMMITMENT_TYPES = {"postponable", "exclusive"}
VALID_DAYS_OF_WEEK = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
VALID_TC_TYPES = {"sleep", "work", "commute", "study", "meal", "caregiving",
                  "household", "health", "personal", "other"}
VALID_TC_FLEX = {"fixed", "flexible"}
VALID_CHECKIN_TYPES = {"goal", "project", "life"}
VALID_TASK_STATUSES = {"todo", "in_progress", "done", "cancelled"}
VALID_GOAL_STATUSES = {"active", "paused", "completed", "abandoned"}
VALID_PROJECT_STATUSES = {"active", "paused", "completed", "abandoned"}
VALID_UPDATE_FIELDS = {"title", "notes", "priority", "status", "due_date", "deadline"}
_HHMM_RE = re.compile(r"^\d{1,2}:\d{2}$")

_WEEKDAY_INDEX = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                  "friday": 4, "saturday": 5, "sunday": 6}


def _normalize_hhmm(v: Any) -> Optional[str]:
    if not isinstance(v, str) or not _HHMM_RE.match(v.strip()):
        return None
    h, m = v.strip().split(":")
    try:
        hi, mi = int(h), int(m)
        if 0 <= hi < 24 and 0 <= mi < 60:
            return f"{hi:02d}:{mi:02d}"
    except ValueError:
        pass
    return None


def _iter_dates(start: str, end: str, days_of_week: Optional[List[str]] = None):
    """Inclusive iterator over YYYY-MM-DD dates filtered by day-of-week set."""
    try:
        cur = datetime.strptime(start, "%Y-%m-%d").date()
        stop = datetime.strptime(end, "%Y-%m-%d").date()
    except ValueError:
        return
    if cur > stop:
        return
    allowed_idx = None
    if days_of_week:
        allowed_idx = {
            _WEEKDAY_INDEX[d] for d in days_of_week
            if isinstance(d, str) and d.lower() in _WEEKDAY_INDEX
        }
    while cur <= stop:
        if allowed_idx is None or cur.weekday() in allowed_idx:
            yield cur.isoformat()
        cur = cur.fromordinal(cur.toordinal() + 1)


async def _richness_score(db, user_id: str, kind: str, item: dict) -> int:
    """Rank duplicates by metadata density. Higher = more info to keep."""
    score = 0
    if kind == "goal":
        for f in ("target_outcome", "deadline", "notes", "checkin_cadence", "journey_type"):
            v = item.get(f)
            if isinstance(v, str) and v.strip():
                score += 2
        n_eo = await db.expected_outcomes.count_documents(
            {"goal_id": item["id"], "user_id": user_id},
        )
        eo_ids = [
            e["id"] async for e in db.expected_outcomes.find(
                {"goal_id": item["id"], "user_id": user_id}, {"_id": 0, "id": 1},
            )
        ]
        n_t = await db.tasks.count_documents(
            {"expected_outcome_id": {"$in": eo_ids}, "user_id": user_id},
        ) if eo_ids else 0
        n_ci = await db.checkins.count_documents(
            {"goal_id": item["id"], "user_id": user_id},
        )
        score += n_eo * 3 + n_t + n_ci
    else:  # project
        for f in ("description", "start_date", "target_end_date", "notes"):
            v = item.get(f)
            if isinstance(v, str) and v.strip():
                score += 2
        n_t = await db.tasks.count_documents(
            {"project_id": item["id"], "user_id": user_id},
        )
        n_ci = await db.checkins.count_documents(
            {"project_id": item["id"], "user_id": user_id},
        )
        score += n_t + n_ci
    return score


def _is_exclusive(item: dict) -> bool:
    return (item.get("commitment_type") or "postponable") == "exclusive"


async def _materialize_proposal(
    db, user_id: str, target_type: str, target_id: str, proposal: dict,
) -> Dict[str, Any]:
    """Atomically apply a proposal. Compensates on failure."""
    if not isinstance(proposal, dict):
        raise HTTPException(status_code=400, detail="Invalid proposal.")

    now = _now()
    today = datetime.now(timezone.utc).date().isoformat()
    created_outcomes: List[str] = []
    created_tasks: List[str] = []
    created_time_commitments: List[str] = []
    created_checkins: List[str] = []
    applied_existing_changes: List[Dict[str, Any]] = []
    applied_existing_updates: List[Dict[str, Any]] = []
    applied_consolidations: List[Dict[str, Any]] = []
    target_updates: Dict[str, Any] = {}

    # 1. Pull existing outcomes for matching by title.
    if target_type == "goal":
        existing_outcomes = await db.expected_outcomes.find(
            {"user_id": user_id, "goal_id": target_id}, {"_id": 0},
        ).to_list(length=200)
    else:
        existing_outcomes = []
    outcome_id_by_title: Dict[str, str] = {
        (e.get("title") or "").strip().lower(): e["id"] for e in existing_outcomes
    }

    try:
        # 2. Create new expected outcomes (goals only).
        new_outcomes = proposal.get("expected_outcomes") or []
        if target_type == "goal":
            for eo in new_outcomes:
                if not isinstance(eo, dict):
                    continue
                title = (eo.get("title") or "").strip()
                if not title:
                    continue
                key = title.lower()
                if key in outcome_id_by_title:
                    continue  # dedupe against existing
                eo_id = _uuid()
                await db.expected_outcomes.insert_one({
                    "id": eo_id, "user_id": user_id, "goal_id": target_id,
                    "title": title,
                    "target_value": (eo.get("target_value") or "").strip(),
                    "current_value": "",
                    "unit": (eo.get("unit") or "").strip(),
                    "deadline": _iso_date(eo.get("deadline")) or "",
                    "status": "active", "notes": "",
                    "outcome_type": eo.get("outcome_type") or "generic",
                    "created_at": now, "updated_at": now,
                })
                outcome_id_by_title[key] = eo_id
                created_outcomes.append(eo_id)

        # 3. Create new tasks.
        for tk in proposal.get("tasks") or []:
            if not isinstance(tk, dict):
                continue
            title = (tk.get("title") or "").strip()
            if not title:
                continue
            priority = (tk.get("priority") or "medium").lower()
            if priority not in VALID_PRIORITIES:
                priority = "medium"
            commitment_type = (tk.get("commitment_type") or "postponable").lower()
            if commitment_type not in VALID_COMMITMENT_TYPES:
                commitment_type = "postponable"
            due = _iso_date(tk.get("due_date")) or ""

            expected_outcome_id: Optional[str] = None
            project_id: Optional[str] = None
            origin = "standalone"

            if target_type == "goal":
                eo_title = (tk.get("expected_outcome_title") or "").strip().lower()
                if eo_title and eo_title in outcome_id_by_title:
                    expected_outcome_id = outcome_id_by_title[eo_title]
                    origin = "expected_outcome"
                elif outcome_id_by_title:
                    expected_outcome_id = next(iter(outcome_id_by_title.values()))
                    origin = "expected_outcome"
            else:  # project
                project_id = target_id
                origin = "project"

            task_id = _uuid()
            await db.tasks.insert_one({
                "id": task_id, "user_id": user_id,
                "title": title,
                "due_date": due,
                "priority": priority, "status": "todo",
                "notes": (tk.get("notes") or "").strip(),
                "origin": origin,
                "expected_outcome_id": expected_outcome_id,
                "project_id": project_id,
                "component_id": None,
                "assigned_to_type": "self", "assigned_to_name": "", "assigned_to_phone": "",
                "commitment_type": commitment_type,
                "created_at": now, "updated_at": now,
            })
            created_tasks.append(task_id)

        # 4. Create new time commitments (life patterns).
        for tc in proposal.get("time_commitments") or []:
            if not isinstance(tc, dict):
                continue
            title = (tc.get("title") or "").strip()
            day = (tc.get("day_of_week") or "").strip().lower()
            start = _normalize_hhmm(tc.get("start_time"))
            end = _normalize_hhmm(tc.get("end_time"))
            if not (title and day in VALID_DAYS_OF_WEEK and start and end):
                continue
            def _mins(hhmm: str) -> int:
                h, m = hhmm.split(":")
                return int(h) * 60 + int(m)
            if _mins(end) <= _mins(start):
                continue
            ctype = (tc.get("commitment_type") or "personal").strip().lower()
            if ctype not in VALID_TC_TYPES:
                ctype = "personal"
            flex = (tc.get("flexibility") or "flexible").strip().lower()
            if flex not in VALID_TC_FLEX:
                flex = "flexible"
            tc_id = _uuid()
            await db.time_commitments.insert_one({
                "id": tc_id, "user_id": user_id,
                "title": title,
                "day_of_week": day,
                "start_time": start,
                "end_time": end,
                "commitment_type": ctype,
                "flexibility": flex,
                "effective_from": today,
                "effective_until": None,
                "source_type": "system",
                "source_id": None,
                "notes": (tc.get("notes") or "").strip(),
                "created_at": now, "updated_at": now,
            })
            created_time_commitments.append(tc_id)

        # 5. One-off check-ins.
        async def _resolve_checkin_anchor(entry: dict) -> Optional[Dict[str, Any]]:
            """Return a dict with the anchor fields set correctly for the given
            check-in entry, or None if it should be skipped."""
            ci_type = (entry.get("type") or "").lower()
            if ci_type not in VALID_CHECKIN_TYPES:
                return None
            base = {"type": ci_type,
                    "expected_outcome_id": None, "goal_id": None,
                    "project_id": None, "task_id": None,
                    "outcome_type": None}
            if ci_type == "goal":
                # Resolve expected outcome (from newly-created or existing).
                eo_title = (entry.get("expected_outcome_title") or "").strip().lower()
                eo_id: Optional[str] = None
                if eo_title and eo_title in outcome_id_by_title:
                    eo_id = outcome_id_by_title[eo_title]
                elif target_type == "goal" and outcome_id_by_title:
                    eo_id = next(iter(outcome_id_by_title.values()))
                if not eo_id:
                    return None  # no valid anchor
                eo = await db.expected_outcomes.find_one(
                    {"id": eo_id, "user_id": user_id}, {"_id": 0},
                )
                if not eo:
                    return None
                base["expected_outcome_id"] = eo["id"]
                base["goal_id"] = eo["goal_id"]
                base["outcome_type"] = eo.get("outcome_type", "generic")
            elif ci_type == "project":
                pid = (entry.get("project_id") or "").strip() or (target_id if target_type == "project" else None)
                if not pid:
                    return None
                p = await db.projects.find_one({"id": pid, "user_id": user_id}, {"_id": 0, "id": 1})
                if not p:
                    return None
                base["project_id"] = p["id"]
            # life type: no anchor required
            return base

        for entry in proposal.get("checkins") or []:
            if not isinstance(entry, dict):
                continue
            title = (entry.get("title") or "").strip()
            date = _iso_date(entry.get("date")) or ""
            time_hhmm = _normalize_hhmm(entry.get("time")) or ""
            if not (title and date and time_hhmm):
                continue
            anchor = await _resolve_checkin_anchor(entry)
            if not anchor:
                continue
            ci_id = _uuid()
            await db.checkins.insert_one({
                "id": ci_id, "user_id": user_id,
                "type": anchor["type"],
                "title": title,
                "date": date,
                "time": time_hhmm,
                "notes": (entry.get("notes") or "").strip(),
                "attachment": "",
                "expected_outcome_id": anchor["expected_outcome_id"],
                "goal_id": anchor["goal_id"],
                "project_id": anchor["project_id"],
                "task_id": None,
                "component_id": None,
                "follow_up_task_id": None,
                "source": "system",
                "outcome_type": anchor["outcome_type"],
                "data": {},
                "money_spent": None,
                "money_currency": None,
                "created_at": now, "updated_at": now,
            })
            created_checkins.append(ci_id)

        # 6. Recurrence expansion → daily check-ins per rule.
        for rule in proposal.get("checkin_recurrences") or []:
            if not isinstance(rule, dict):
                continue
            title = (rule.get("title") or "").strip()
            start = _iso_date(rule.get("start_date"))
            end = _iso_date(rule.get("end_date"))
            time_hhmm = _normalize_hhmm(rule.get("time")) or ""
            if not (title and start and end and time_hhmm):
                continue
            anchor = await _resolve_checkin_anchor(rule)
            if not anchor:
                continue
            dows = rule.get("days_of_week") or None
            if isinstance(dows, list) and not dows:
                dows = None  # empty list means every day
            for d in _iter_dates(start, end, dows):
                ci_id = _uuid()
                await db.checkins.insert_one({
                    "id": ci_id, "user_id": user_id,
                    "type": anchor["type"],
                    "title": title,
                    "date": d,
                    "time": time_hhmm,
                    "notes": (rule.get("notes") or "").strip(),
                    "attachment": "",
                    "expected_outcome_id": anchor["expected_outcome_id"],
                    "goal_id": anchor["goal_id"],
                    "project_id": anchor["project_id"],
                    "task_id": None,
                    "component_id": None,
                    "follow_up_task_id": None,
                    "source": "system",
                    "outcome_type": anchor["outcome_type"],
                    "data": {},
                    "money_spent": None,
                    "money_currency": None,
                    "created_at": now, "updated_at": now,
                })
                created_checkins.append(ci_id)

        # 7. Apply postpone/cancel actions — NEVER on exclusive items,
        #    NEVER on the current target.
        for change in proposal.get("existing_item_changes") or []:
            if not isinstance(change, dict):
                continue
            kind = (change.get("kind") or "").lower()
            item_id = (change.get("id") or "").strip()
            action = (change.get("action") or "").lower()
            if kind not in ("goal", "project", "task") or not item_id or action not in ("postpone", "cancel"):
                continue
            if kind == target_type and item_id == target_id:
                continue
            coll = {"goal": "goals", "project": "projects", "task": "tasks"}[kind]
            doc = await db[coll].find_one({"id": item_id, "user_id": user_id}, {"_id": 0})
            if not doc:
                continue
            if _is_exclusive(doc):
                continue
            patch: Dict[str, Any] = {"updated_at": now}
            if action == "postpone":
                new_due = _iso_date(change.get("new_due_date"))
                if not new_due:
                    continue
                if kind == "goal":
                    patch["deadline"] = new_due; patch["status"] = "paused"
                elif kind == "project":
                    patch["target_end_date"] = new_due; patch["status"] = "paused"
                else:
                    patch["due_date"] = new_due
            else:
                patch["status"] = "cancelled" if kind == "task" else "abandoned"
            await db[coll].update_one({"id": item_id, "user_id": user_id}, {"$set": patch})
            applied_existing_changes.append({"kind": kind, "id": item_id, "action": action})

        # 8. Free-form patches on existing items — NEVER exclusive, NEVER
        #    the current target for destructive status flips.
        for upd in proposal.get("existing_item_updates") or []:
            if not isinstance(upd, dict):
                continue
            kind = (upd.get("kind") or "").lower()
            item_id = (upd.get("id") or "").strip()
            patch_in = upd.get("patch") or {}
            if kind not in ("goal", "project", "task") or not item_id or not isinstance(patch_in, dict):
                continue
            coll = {"goal": "goals", "project": "projects", "task": "tasks"}[kind]
            doc = await db[coll].find_one({"id": item_id, "user_id": user_id}, {"_id": 0})
            if not doc:
                continue
            if _is_exclusive(doc):
                continue
            patch: Dict[str, Any] = {}
            for k, v in patch_in.items():
                if k not in VALID_UPDATE_FIELDS or not isinstance(v, (str, int, float)):
                    continue
                v = str(v).strip() if not isinstance(v, str) else v.strip()
                if not v:
                    continue
                if k == "priority":
                    if v.lower() in VALID_PRIORITIES:
                        patch["priority"] = v.lower()
                elif k == "status":
                    if kind == "task" and v.lower() in VALID_TASK_STATUSES:
                        patch["status"] = v.lower()
                    elif kind == "goal" and v.lower() in VALID_GOAL_STATUSES:
                        patch["status"] = v.lower()
                    elif kind == "project" and v.lower() in VALID_PROJECT_STATUSES:
                        patch["status"] = v.lower()
                elif k == "due_date":
                    if kind == "task":
                        d = _iso_date(v)
                        if d:
                            patch["due_date"] = d
                elif k == "deadline":
                    if kind == "goal":
                        d = _iso_date(v)
                        if d:
                            patch["deadline"] = d
                    elif kind == "project":
                        d = _iso_date(v)
                        if d:
                            patch["target_end_date"] = d
                elif k == "title":
                    patch["title"] = v[:200]
                elif k == "notes":
                    field = "description" if kind == "project" else "notes"
                    patch[field] = v[:4000]
            if patch:
                patch["updated_at"] = now
                await db[coll].update_one({"id": item_id, "user_id": user_id}, {"$set": patch})
                applied_existing_updates.append({"kind": kind, "id": item_id, "keys": sorted(patch.keys())})

        # 9. Consolidations — server picks survivor by richness.
        for cons in proposal.get("consolidations") or []:
            if not isinstance(cons, dict):
                continue
            kind = (cons.get("kind") or "").lower()
            ids = cons.get("candidate_ids") or []
            if kind not in ("goal", "project") or not isinstance(ids, list) or len(ids) < 2:
                continue
            coll = "goals" if kind == "goal" else "projects"
            candidates = await db[coll].find(
                {"id": {"$in": list({str(i) for i in ids if i})}, "user_id": user_id},
                {"_id": 0},
            ).to_list(length=20)
            candidates = [c for c in candidates if not _is_exclusive(c)]
            if len(candidates) < 2:
                continue
            # Score each; higher wins, tiebreak by older created_at.
            scored: List[Tuple[int, str, dict]] = []
            for c in candidates:
                s = await _richness_score(db, user_id, kind, c)
                scored.append((s, c.get("created_at", ""), c))
            scored.sort(key=lambda x: (-x[0], x[1]))
            survivor = scored[0][2]
            losers = [c for _, _, c in scored[1:]]
            merged_notes = (survivor.get("notes") or "").strip()
            merged_desc = (survivor.get("description") or "").strip() if kind == "project" else None
            for loser in losers:
                # Reparent child docs.
                if kind == "goal":
                    await db.expected_outcomes.update_many(
                        {"goal_id": loser["id"], "user_id": user_id},
                        {"$set": {"goal_id": survivor["id"], "updated_at": now}},
                    )
                    await db.checkins.update_many(
                        {"goal_id": loser["id"], "user_id": user_id},
                        {"$set": {"goal_id": survivor["id"], "updated_at": now}},
                    )
                    # Tasks reference EOs which we've reparented above — no
                    # direct change needed.
                else:  # project
                    await db.tasks.update_many(
                        {"project_id": loser["id"], "user_id": user_id},
                        {"$set": {"project_id": survivor["id"], "updated_at": now}},
                    )
                    await db.checkins.update_many(
                        {"project_id": loser["id"], "user_id": user_id},
                        {"$set": {"project_id": survivor["id"], "updated_at": now}},
                    )
                # Merge notes / description if survivor was empty and loser had content.
                loser_notes = (loser.get("notes") or "").strip()
                if loser_notes and loser_notes not in merged_notes:
                    merged_notes = (merged_notes + "\n\n" + loser_notes).strip() if merged_notes else loser_notes
                if kind == "project":
                    ld = (loser.get("description") or "").strip()
                    if ld and ld not in (merged_desc or ""):
                        merged_desc = (merged_desc + "\n\n" + ld).strip() if merged_desc else ld
                # Delete the loser doc.
                await db[coll].delete_one({"id": loser["id"], "user_id": user_id})
            # Persist merged notes/description onto survivor.
            surv_patch = {"updated_at": now}
            if merged_notes and merged_notes != (survivor.get("notes") or ""):
                surv_patch["notes"] = merged_notes[:8000]
            if kind == "project" and merged_desc and merged_desc != (survivor.get("description") or ""):
                surv_patch["description"] = merged_desc[:8000]
            await db[coll].update_one({"id": survivor["id"], "user_id": user_id}, {"$set": surv_patch})
            applied_consolidations.append({
                "kind": kind,
                "survivor_id": survivor["id"],
                "survivor_title": survivor.get("title"),
                "merged_ids": [l["id"] for l in losers],
                "score": scored[0][0],
            })

        # 10. Cadence + target update (+ commitment_type on target).
        cadence = proposal.get("checkin_cadence")
        if isinstance(cadence, str) and cadence.strip().lower() in VALID_CADENCES:
            target_updates["checkin_cadence"] = cadence.strip().lower()
        tu = proposal.get("target_updates") or {}
        if isinstance(tu, dict):
            deadline = _iso_date(tu.get("deadline"))
            if deadline:
                target_updates["deadline" if target_type == "goal" else "target_end_date"] = deadline
            notes = tu.get("notes")
            if isinstance(notes, str) and notes.strip():
                notes_field = "notes" if target_type == "goal" else "description"
                target_updates[notes_field] = notes.strip()
            ct = (tu.get("commitment_type") or "").strip().lower() if isinstance(tu.get("commitment_type"), str) else ""
            if ct in VALID_COMMITMENT_TYPES:
                target_updates["commitment_type"] = ct
        if target_updates:
            target_updates["updated_at"] = now
            coll = "goals" if target_type == "goal" else "projects"
            await db[coll].update_one(
                {"id": target_id, "user_id": user_id}, {"$set": target_updates},
            )

    except HTTPException:
        raise
    except Exception as exc:
        # Compensating cleanup for the most easily-reversible artifacts.
        # Notes: reparenting done inside consolidations is NOT rolled back
        # since a partial failure there would leave the DB inconsistent
        # anyway; this is best-effort MVP behaviour.
        for tid in created_tasks:
            await db.tasks.delete_one({"id": tid, "user_id": user_id})
        for eid in created_outcomes:
            await db.expected_outcomes.delete_one({"id": eid, "user_id": user_id})
        for tcid in created_time_commitments:
            await db.time_commitments.delete_one({"id": tcid, "user_id": user_id})
        for cid in created_checkins:
            await db.checkins.delete_one({"id": cid, "user_id": user_id})
        raise HTTPException(status_code=500,
                            detail=f"Failed to apply proposal: {type(exc).__name__}: {exc}")

    return {
        "created_outcomes": created_outcomes,
        "created_tasks": created_tasks,
        "created_time_commitments": created_time_commitments,
        "created_checkins": created_checkins,
        "applied_existing_changes": applied_existing_changes,
        "applied_existing_updates": applied_existing_updates,
        "applied_consolidations": applied_consolidations,
        "target_updated": bool(target_updates),
    }


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class MessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class MaterializeRequest(BaseModel):
    message_id: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@planning_router.get("/{target_type}/{target_id}/conversation")
async def get_conversation(
    target_type: str, target_id: str,
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    conv = await _get_or_create_conversation(db, current_user["id"], target_type, target_id)
    return _public_conversation(conv)


@planning_router.post("/{target_type}/{target_id}/messages")
async def post_message(
    target_type: str, target_id: str, body: MessageRequest,
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    conv = await _get_or_create_conversation(db, current_user["id"], target_type, target_id)
    ctx = await _read_context(db, current_user["id"], target_type, target_id)

    now = _now()
    user_msg = {
        "id": _uuid(), "role": "user",
        "content": body.content.strip(),
        "created_at": now,
    }
    conv["messages"].append(user_msg)

    # If this is the very first user turn and it's short, seed a warm opener
    # via a brief invisible priming prompt embedded in the system context —
    # already handled inside _SYSTEM_PROMPT.

    raw = await _call_llm(conv["messages"], body.content.strip(), ctx)
    prose, proposal = _split_message(raw)
    if not prose and proposal:
        prose = proposal.get("summary") or "Here are some proposed changes for your plan."

    asst_msg = {
        "id": _uuid(), "role": "assistant",
        "content": raw,  # store the raw (with HYMN_PROPOSAL) so we can re-parse
        "proposal": proposal,
        "created_at": _now(),
    }
    conv["messages"].append(asst_msg)
    await _save_conversation(db, conv)
    return _public_conversation(conv)


@planning_router.post("/{target_type}/{target_id}/reset")
async def reset_conversation(
    target_type: str, target_id: str,
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    _require(target_type in TARGET_TYPES, f"target_type must be one of {list(TARGET_TYPES)}")
    await _read_target(db, current_user["id"], target_type, target_id)
    await db.plan_conversations.delete_many(
        {"user_id": current_user["id"], "target_type": target_type, "target_id": target_id},
    )
    conv = await _get_or_create_conversation(db, current_user["id"], target_type, target_id)
    return _public_conversation(conv)


@planning_router.post("/conversations/{conversation_id}/materialize")
async def materialize(
    conversation_id: str, body: MaterializeRequest,
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    conv = await db.plan_conversations.find_one(
        {"id": conversation_id, "user_id": current_user["id"]}, {"_id": 0},
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    target_msg: Optional[dict] = None
    for m in conv["messages"]:
        if m.get("id") == body.message_id:
            target_msg = m
            break
    if not target_msg:
        raise HTTPException(status_code=404, detail="Message not found")
    if target_msg.get("materialized_at"):
        raise HTTPException(status_code=400, detail="This proposal is already applied.")
    proposal = target_msg.get("proposal")
    if not proposal:
        raise HTTPException(status_code=400, detail="This message has no proposal to apply.")

    result = await _materialize_proposal(
        db, current_user["id"], conv["target_type"], conv["target_id"], proposal,
    )
    target_msg["materialized_at"] = _now()
    bits: List[str] = []
    if result["created_outcomes"]:
        n = len(result["created_outcomes"])
        bits.append(f"{n} outcome{'s' if n != 1 else ''}")
    if result["created_tasks"]:
        n = len(result["created_tasks"])
        bits.append(f"{n} task{'s' if n != 1 else ''}")
    if result.get("created_checkins"):
        n = len(result["created_checkins"])
        bits.append(f"{n} check-in{'s' if n != 1 else ''}")
    if result.get("created_time_commitments"):
        n = len(result["created_time_commitments"])
        bits.append(f"{n} time commitment{'s' if n != 1 else ''}")
    if result.get("applied_existing_updates"):
        n = len(result["applied_existing_updates"])
        bits.append(f"updated {n} item{'s' if n != 1 else ''}")
    if result.get("applied_existing_changes"):
        n_post = sum(1 for c in result["applied_existing_changes"] if c["action"] == "postpone")
        n_cxl = sum(1 for c in result["applied_existing_changes"] if c["action"] == "cancel")
        if n_post:
            bits.append(f"postponed {n_post}")
        if n_cxl:
            bits.append(f"cancelled {n_cxl}")
    if result.get("applied_consolidations"):
        n = len(result["applied_consolidations"])
        merged = sum(len(c["merged_ids"]) for c in result["applied_consolidations"])
        bits.append(f"consolidated {merged} duplicate{'s' if merged != 1 else ''} in {n} group{'s' if n != 1 else ''}")
    target_msg["materialized_summary"] = (
        "Added " + ", ".join(bits) + "." if bits else "Applied."
    )
    await _save_conversation(db, conv)
    return {
        "conversation": _public_conversation(conv),
        "result": result,
    }


# ---------------------------------------------------------------------------
# Index bootstrap
# ---------------------------------------------------------------------------


async def ensure_planning_indexes(database) -> None:
    await database.plan_conversations.create_index("id", unique=True)
    await database.plan_conversations.create_index(
        [("user_id", 1), ("target_type", 1), ("target_id", 1)], unique=True,
    )
    await database.plan_conversations.create_index([("user_id", 1), ("updated_at", -1)])
