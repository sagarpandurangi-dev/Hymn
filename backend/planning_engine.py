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
 "time_commitments": [{"title": "e.g. Job",
                        "day_of_week": "monday|tuesday|…|sunday",
                        "start_time": "HH:MM (24h)",
                        "end_time": "HH:MM (24h)",
                        "commitment_type": "work|sleep|commute|study|meal|caregiving|household|health|personal|other",
                        "flexibility": "fixed|flexible",
                        "notes": "optional"}],
 "existing_item_changes": [{"kind": "goal|project|task",
                             "id": "existing id from context",
                             "action": "postpone|cancel",
                             "new_due_date": "YYYY-MM-DD if postpone, else omit",
                             "reason": "one short line"}],
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
- `existing_item_changes` must reference EXACTLY the id of a real item
  from the context prelude, and the item MUST NOT have
  commitment_type="exclusive". If capacity is tight and every option is
  exclusive, say so in prose and DON'T include existing_item_changes.
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
_HHMM_RE = re.compile(r"^\d{1,2}:\d{2}$")


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
    applied_existing_changes: List[Dict[str, Any]] = []
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
                    # Fallback: attach to the first outcome (existing or newly created)
                    expected_outcome_id = next(iter(outcome_id_by_title.values()))
                    origin = "expected_outcome"
                # If no outcomes at all, task ends up standalone (allowed).
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
                continue  # ignore invalid ranges (LLM slip-up)
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
                "source_type": "system",  # created by planning conversation
                "source_id": None,
                "notes": (tc.get("notes") or "").strip(),
                "created_at": now, "updated_at": now,
            })
            created_time_commitments.append(tc_id)

        # 5. Apply postpone/cancel actions on OTHER portfolio items — but
        #    NEVER on items with commitment_type="exclusive".
        for change in proposal.get("existing_item_changes") or []:
            if not isinstance(change, dict):
                continue
            kind = (change.get("kind") or "").lower()
            item_id = (change.get("id") or "").strip()
            action = (change.get("action") or "").lower()
            if kind not in ("goal", "project", "task") or not item_id or action not in ("postpone", "cancel"):
                continue
            # Never modify the target the user is currently planning.
            if kind == target_type and item_id == target_id:
                continue
            coll = {"goal": "goals", "project": "projects", "task": "tasks"}[kind]
            doc = await db[coll].find_one({"id": item_id, "user_id": user_id}, {"_id": 0})
            if not doc:
                continue
            if (doc.get("commitment_type") or "postponable") == "exclusive":
                continue  # safety net — never touch exclusive items
            patch: Dict[str, Any] = {"updated_at": now}
            if action == "postpone":
                new_due = _iso_date(change.get("new_due_date"))
                if not new_due:
                    continue
                if kind == "goal":
                    patch["deadline"] = new_due
                    patch["status"] = "paused"
                elif kind == "project":
                    patch["target_end_date"] = new_due
                    patch["status"] = "paused"
                else:  # task
                    patch["due_date"] = new_due
            else:  # cancel
                if kind == "task":
                    patch["status"] = "cancelled"
                else:
                    patch["status"] = "abandoned"
            await db[coll].update_one({"id": item_id, "user_id": user_id}, {"$set": patch})
            applied_existing_changes.append({"kind": kind, "id": item_id, "action": action})

        # 6. Cadence + target update (+ commitment_type on target).
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
        # Compensating cleanup.
        for tid in created_tasks:
            await db.tasks.delete_one({"id": tid, "user_id": user_id})
        for eid in created_outcomes:
            await db.expected_outcomes.delete_one({"id": eid, "user_id": user_id})
        for tcid in created_time_commitments:
            await db.time_commitments.delete_one({"id": tcid, "user_id": user_id})
        raise HTTPException(status_code=500,
                            detail=f"Failed to apply proposal: {type(exc).__name__}: {exc}")

    return {
        "created_outcomes": created_outcomes,
        "created_tasks": created_tasks,
        "created_time_commitments": created_time_commitments,
        "applied_existing_changes": applied_existing_changes,
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
    if result.get("created_time_commitments"):
        n = len(result["created_time_commitments"])
        bits.append(f"{n} time commitment{'s' if n != 1 else ''}")
    if result.get("applied_existing_changes"):
        n_post = sum(1 for c in result["applied_existing_changes"] if c["action"] == "postpone")
        n_cxl = sum(1 for c in result["applied_existing_changes"] if c["action"] == "cancel")
        if n_post:
            bits.append(f"postponed {n_post}")
        if n_cxl:
            bits.append(f"cancelled {n_cxl}")
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
