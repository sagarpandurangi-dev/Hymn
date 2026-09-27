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
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple

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

    # Batch 2B2 — canonical weekly capacity via time_service.
    today = datetime.now(timezone.utc).date()
    monday = today - timedelta(days=today.weekday())
    from time_service import load_week_time_capacity  # noqa: WPS433
    capacity = await load_week_time_capacity(db, user_id, monday.isoformat())

    # Time commitments (recurring weekly). Only include currently-effective
    # ones (effective_from <= today AND (effective_until is null or >= today)).
    today_iso = today.isoformat()
    time_commitments = await db.time_commitments.find(
        {"user_id": user_id, "effective_from": {"$lte": today_iso}},
        {"_id": 0},
    ).to_list(length=500)
    time_commitments = [
        tc for tc in time_commitments
        if not tc.get("effective_until") or tc["effective_until"] >= today_iso
    ]

    weekly_capacity = {
        # Legacy keys — kept so downstream compatibility never breaks.
        "committed_hours_per_week": round(capacity["committed_minutes"] / 60.0, 1),
        "free_hours_per_week_estimate": round(capacity["available_minutes"] / 60.0, 1),
        # Batch 2B2 — canonical decomposition.
        "baseline_committed_hours_per_week": round(capacity["baseline_committed_minutes"] / 60.0, 1),
        "reserved_hours_per_week": round(capacity["reserved_minutes"] / 60.0, 1),
        "overlapping_hours_per_week": round(capacity["overlapping_minutes"] / 60.0, 1),
        "capacity_basis": "recorded_commitments_and_active_reservations",
        "is_estimate": True,
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
 "plan": {"title": "human-readable name for this plan",
          "phases": [{"title": "phase name",
                      "description": "optional short description or null",
                      "milestones": [{"title": "milestone name",
                                       "description": "optional short description or null",
                                       "target_date": "YYYY-MM-DD or null",
                                       "tasks": [{"title": "task name",
                                                   "description": "optional short description or null",
                                                   "due_date": "YYYY-MM-DD or null",
                                                   "priority": "low|medium|high",
                                                   "required_checkins": [{"title": "one-line label",
                                                                            "prompt": "what the user should verify or report",
                                                                            "cadence": "once|daily|weekly|monthly|quarterly"}]}]}]}]},
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
- Every actionable proposal MUST include a `plan` object with a
  non-empty `phases` list. Every phase MUST have a non-empty
  `milestones` list; every milestone MUST have a non-empty `tasks`
  list; every task MUST have a non-empty `required_checkins` list.
  This is the durable Plan → Phase → Milestone → Task → Required
  Check-in hierarchy Hymn stores server-side.
- `required_checkins` describe future obligations the user will
  verify — they are NOT completed check-ins. Never invent progress,
  qualifications, current balances, or historical activity for them.
- Only propose additions/refinements to the current target — never delete
  its existing items.
- Do not propose deleting, merging, postponing, cancelling, completing, renaming, or otherwise modifying existing Goals, Projects, Expected Outcomes, Tasks, or Check-ins. Explain any suggested trade-off conversationally. Hymn requires item-by-item user review before existing records may be changed.
- For Goals: tasks MUST attach to a proposed or existing expected_outcome.
- For Projects: tasks attach directly to the project (leave
  expected_outcome_title empty).
- Keep it tight: 1–6 new outcomes and 1–20 new tasks per turn — smaller is better.
- If the user is just asking a question or exploring, DO NOT include the
  proposal block. Only include it when proposing concrete additions.
- `checkin_recurrences` are expanded server-side into one check-in per
  matching day within [start_date, end_date] (including backfill into
  the past if the range straddles today). Prefer a recurrence over
  emitting 30 individual checkins.
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
        # Batch 2B2 — describe the number honestly. This is *recorded*
        # uncommitted time (recurring commitments + active
        # reservations), not guaranteed free / usable time. Missing
        # sleep, meals, travel, caregiving or other unrecorded
        # obligations may still occupy some of these hours.
        lines.append(
            f"\nWEEKLY CAPACITY (recorded uncommitted time, estimate): "
            f"{wc.get('committed_hours_per_week', 0)}h already recorded "
            f"(baseline {wc.get('baseline_committed_hours_per_week', 0)}h + reservations "
            f"{wc.get('reserved_hours_per_week', 0)}h; overlap "
            f"{wc.get('overlapping_hours_per_week', 0)}h), ~"
            f"{wc.get('free_hours_per_week_estimate', 0)}h remains uncommitted in the record."
            "\nCAPACITY BASIS: This is recorded uncommitted time, not guaranteed free or usable time."
            " Sleep, breaks, travel, caregiving and other obligations may be included in the remainder if the user hasn't recorded them."
            " If a proposal's feasibility depends on time you don't know, ask the user rather than invent availability."
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
        # Batch 2B8 — expose draft revision + materialization state so the
        # UI can decide whether the plan is editable.
        "proposal_revision": msg.get("proposal_revision"),
        "materialization_state": msg.get("materialization_state"),
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


def _materialization_key(
    conversation_id: str,
    message_id: str,
    artifact_kind: str,
    artifact_position: str,
) -> str:
    """Deterministic key identifying a single additive artifact."""
    return f"{conversation_id}:{message_id}:{artifact_kind}:{artifact_position}"


def _materialized_id(materialization_key: str) -> str:
    """Non-secret deterministic id derived from a materialization key."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"hymn:{materialization_key}"))


async def _upsert_artifact(
    db, collection: str, user_id: str, key: str, document: dict,
) -> Tuple[dict, bool]:
    """Upsert an additive artifact keyed by (user_id, planning_materialization_key).
    Returns (stored_document, was_inserted_this_attempt)."""
    result = await db[collection].update_one(
        {"user_id": user_id, "planning_materialization_key": key},
        {"$setOnInsert": document},
        upsert=True,
    )
    stored = await db[collection].find_one(
        {"user_id": user_id, "planning_materialization_key": key}, {"_id": 0},
    )
    return stored or document, result.upserted_id is not None


VALID_REQUIRED_CHECKIN_CADENCES = {"once", "daily", "weekly", "monthly", "quarterly"}


def _validate_plan_hierarchy(plan: Any) -> None:
    """Strictly validate a durable Plan → Phase → Milestone → Task →
    Required Check-in hierarchy. On any structural or field error raises
    HTTPException(status_code=422, ...) whose detail identifies the
    exact hierarchy location using zero-based indexes.
    """
    def fail(location: str, msg: str) -> None:
        raise HTTPException(status_code=422, detail=f"{location} {msg}")

    def _nonblank_str(v: Any) -> bool:
        return isinstance(v, str) and v.strip() != ""

    if not isinstance(plan, dict):
        fail("plan", "must be an object")
    if not _nonblank_str(plan.get("title")):
        fail("plan.title", "must be a non-empty string")
    phases = plan.get("phases")
    if not isinstance(phases, list) or len(phases) == 0:
        fail("plan.phases", "must be a non-empty array")
    for pi, phase in enumerate(phases):
        ploc = f"plan.phases[{pi}]"
        if not isinstance(phase, dict):
            fail(ploc, "must be an object")
        if not _nonblank_str(phase.get("title")):
            fail(f"{ploc}.title", "must be a non-empty string")
        milestones = phase.get("milestones")
        if not isinstance(milestones, list) or len(milestones) == 0:
            fail(f"{ploc}.milestones", "must be a non-empty array")
        for mi, milestone in enumerate(milestones):
            mloc = f"{ploc}.milestones[{mi}]"
            if not isinstance(milestone, dict):
                fail(mloc, "must be an object")
            if not _nonblank_str(milestone.get("title")):
                fail(f"{mloc}.title", "must be a non-empty string")
            td = milestone.get("target_date")
            if td is not None and _iso_date(td) is None:
                fail(f"{mloc}.target_date", "must be null or YYYY-MM-DD")
            tasks = milestone.get("tasks")
            if not isinstance(tasks, list) or len(tasks) == 0:
                fail(f"{mloc}.tasks", "must be a non-empty array")
            for ti, task in enumerate(tasks):
                tloc = f"{mloc}.tasks[{ti}]"
                if not isinstance(task, dict):
                    fail(tloc, "must be an object")
                if not _nonblank_str(task.get("title")):
                    fail(f"{tloc}.title", "must be a non-empty string")
                dd = task.get("due_date")
                if dd is not None and _iso_date(dd) is None:
                    fail(f"{tloc}.due_date", "must be null or YYYY-MM-DD")
                pr = task.get("priority")
                if pr not in VALID_PRIORITIES:
                    fail(f"{tloc}.priority", "must be one of low, medium, high")
                rcs = task.get("required_checkins")
                if not isinstance(rcs, list) or len(rcs) == 0:
                    fail(f"{tloc}.required_checkins", "must be a non-empty array")
                for ri, rc in enumerate(rcs):
                    rloc = f"{tloc}.required_checkins[{ri}]"
                    if not isinstance(rc, dict):
                        fail(rloc, "must be an object")
                    if not _nonblank_str(rc.get("title")):
                        fail(f"{rloc}.title", "must be a non-empty string")
                    if not _nonblank_str(rc.get("prompt")):
                        fail(f"{rloc}.prompt", "must be a non-empty string")
                    if rc.get("cadence") not in VALID_REQUIRED_CHECKIN_CADENCES:
                        fail(
                            f"{rloc}.cadence",
                            "must be one of once, daily, weekly, monthly, quarterly",
                        )


# ---------------------------------------------------------------------------
# Batch 2B8 — draft (in-conversation) hierarchy editing helpers.
# These operate on the proposal.plan JSON embedded in the assistant message
# in `plan_conversations`. They MUST NEVER touch permanent hierarchy records
# in plans / plan_phases / plan_milestones / tasks / required_checkins.
# ---------------------------------------------------------------------------


import copy as _copy  # local alias to avoid shadowing any existing name


_DRAFT_EDITABLE_FIELDS: Dict[str, set] = {
    "plan": {"title"},
    "phase": {"title", "description"},
    "milestone": {"title", "description", "target_date"},
    "task": {"title", "description", "due_date", "priority"},
    "required_checkin": {"title", "prompt", "cadence"},
}

_DRAFT_ENTITY_TYPES = ("plan", "phase", "milestone", "task", "required_checkin")


def _draft_node_id(
    message_id: str,
    node_type: str,
    structural_path: str,
) -> str:
    """Deterministic UUIDv5 for a draft hierarchy node.

    Draft IDs are namespaced separately from Batch 2B7 permanent
    materialization IDs so they can never collide.
    """
    return str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"hymn:draft:{message_id}:{node_type}:{structural_path}",
    ))


def _normalise_draft_hierarchy(plan: dict, message_id: str) -> dict:
    """Return a deep-copied plan with stable draft node IDs assigned.

    - Preserves any existing valid string id.
    - Assigns a deterministic id (via ``_draft_node_id``) where missing.
    - Validates all ids are non-empty strings and globally unique.
    - Never mutates the caller's dictionary.
    """
    if not isinstance(plan, dict):
        raise HTTPException(status_code=422, detail="plan must be an object")
    new_plan = _copy.deepcopy(plan)

    seen: Dict[str, str] = {}

    def _assign(node: dict, node_type: str, structural_path: str, location: str) -> None:
        # Batch 2B8.1 — reject malformed present ids. Only a truly missing
        # key or an explicit null may be filled in with a deterministic id.
        if "id" not in node or node.get("id") is None:
            nid = _draft_node_id(message_id, node_type, structural_path)
        else:
            current = node.get("id")
            if not isinstance(current, str) or not current.strip():
                raise HTTPException(
                    status_code=422,
                    detail=f"{location}.id must be a non-empty string",
                )
            nid = current.strip()
        if not isinstance(nid, str) or not nid:
            raise HTTPException(status_code=422, detail=f"{location}.id must be a non-empty string")
        if nid in seen:
            raise HTTPException(
                status_code=422,
                detail=f"{location}.id duplicates {seen[nid]}",
            )
        seen[nid] = location
        node["id"] = nid

    _assign(new_plan, "plan", "0", "plan")

    phases = new_plan.get("phases")
    if not isinstance(phases, list):
        raise HTTPException(status_code=422, detail="plan.phases must be a non-empty array")
    for pi, phase in enumerate(phases):
        if not isinstance(phase, dict):
            raise HTTPException(status_code=422, detail=f"plan.phases[{pi}] must be an object")
        _assign(phase, "phase", f"{pi}", f"plan.phases[{pi}]")
        milestones = phase.get("milestones")
        if not isinstance(milestones, list):
            raise HTTPException(
                status_code=422,
                detail=f"plan.phases[{pi}].milestones must be a non-empty array",
            )
        for mi, milestone in enumerate(milestones):
            if not isinstance(milestone, dict):
                raise HTTPException(
                    status_code=422,
                    detail=f"plan.phases[{pi}].milestones[{mi}] must be an object",
                )
            _assign(
                milestone, "milestone", f"{pi}:{mi}",
                f"plan.phases[{pi}].milestones[{mi}]",
            )
            tasks = milestone.get("tasks")
            if not isinstance(tasks, list):
                raise HTTPException(
                    status_code=422,
                    detail=f"plan.phases[{pi}].milestones[{mi}].tasks must be a non-empty array",
                )
            for ti, task in enumerate(tasks):
                if not isinstance(task, dict):
                    raise HTTPException(
                        status_code=422,
                        detail=f"plan.phases[{pi}].milestones[{mi}].tasks[{ti}] must be an object",
                    )
                _assign(
                    task, "task", f"{pi}:{mi}:{ti}",
                    f"plan.phases[{pi}].milestones[{mi}].tasks[{ti}]",
                )
                rcs = task.get("required_checkins")
                if not isinstance(rcs, list):
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            f"plan.phases[{pi}].milestones[{mi}].tasks[{ti}]"
                            f".required_checkins must be a non-empty array"
                        ),
                    )
                for ri, rc in enumerate(rcs):
                    if not isinstance(rc, dict):
                        raise HTTPException(
                            status_code=422,
                            detail=(
                                f"plan.phases[{pi}].milestones[{mi}].tasks[{ti}]"
                                f".required_checkins[{ri}] must be an object"
                            ),
                        )
                    _assign(
                        rc, "required_checkin", f"{pi}:{mi}:{ti}:{ri}",
                        (
                            f"plan.phases[{pi}].milestones[{mi}].tasks[{ti}]"
                            f".required_checkins[{ri}]"
                        ),
                    )

    return new_plan


def _collect_draft_ids(plan: dict) -> Dict[str, str]:
    """Return {node_id: location_string} for every node in the draft plan."""
    ids: Dict[str, str] = {}

    def _record(node: dict, location: str) -> None:
        nid = node.get("id") if isinstance(node, dict) else None
        if not (isinstance(nid, str) and nid):
            raise HTTPException(status_code=422, detail=f"{location}.id must be a non-empty string")
        if nid in ids:
            raise HTTPException(
                status_code=422,
                detail=f"{location}.id duplicates {ids[nid]}",
            )
        ids[nid] = location

    _record(plan, "plan")
    for pi, phase in enumerate(plan.get("phases") or []):
        _record(phase, f"plan.phases[{pi}]")
        for mi, m in enumerate(phase.get("milestones") or []):
            _record(m, f"plan.phases[{pi}].milestones[{mi}]")
            for ti, t in enumerate(m.get("tasks") or []):
                _record(t, f"plan.phases[{pi}].milestones[{mi}].tasks[{ti}]")
                for ri, rc in enumerate(t.get("required_checkins") or []):
                    _record(
                        rc,
                        (
                            f"plan.phases[{pi}].milestones[{mi}].tasks[{ti}]"
                            f".required_checkins[{ri}]"
                        ),
                    )
    return ids


def _locate_draft_node(plan: dict, entity_type: str, entity_id: str) -> Dict[str, Any]:
    """Find a node by stable draft id.

    Returns a dict with keys:
      node, parent, container_list, index,
      phase, milestone, task (ancestors where relevant),
      located_type.
    Raises 404 if not found. Raises 400 if entity_type does not match the
    located node's type. NEVER locates by title or by client-supplied index.
    """
    if not isinstance(entity_id, str) or not entity_id:
        raise HTTPException(status_code=404, detail=f"Draft {entity_type} not found")

    # Plan itself.
    if plan.get("id") == entity_id:
        located_type = "plan"
        if entity_type != located_type:
            raise HTTPException(
                status_code=400,
                detail="entity_id does not identify the requested entity_type",
            )
        return {
            "node": plan, "parent": None, "container_list": None,
            "index": None, "phase": None, "milestone": None, "task": None,
            "located_type": "plan",
        }

    phases = plan.get("phases") or []
    for pi, phase in enumerate(phases):
        if isinstance(phase, dict) and phase.get("id") == entity_id:
            located_type = "phase"
            if entity_type != located_type:
                raise HTTPException(
                    status_code=400,
                    detail="entity_id does not identify the requested entity_type",
                )
            return {
                "node": phase, "parent": plan, "container_list": phases,
                "index": pi, "phase": phase, "milestone": None, "task": None,
                "located_type": "phase",
            }
        milestones = (phase or {}).get("milestones") or []
        for mi, m in enumerate(milestones):
            if isinstance(m, dict) and m.get("id") == entity_id:
                located_type = "milestone"
                if entity_type != located_type:
                    raise HTTPException(
                        status_code=400,
                        detail="entity_id does not identify the requested entity_type",
                    )
                return {
                    "node": m, "parent": phase, "container_list": milestones,
                    "index": mi, "phase": phase, "milestone": m, "task": None,
                    "located_type": "milestone",
                }
            tasks = (m or {}).get("tasks") or []
            for ti, t in enumerate(tasks):
                if isinstance(t, dict) and t.get("id") == entity_id:
                    located_type = "task"
                    if entity_type != located_type:
                        raise HTTPException(
                            status_code=400,
                            detail="entity_id does not identify the requested entity_type",
                        )
                    return {
                        "node": t, "parent": m, "container_list": tasks,
                        "index": ti, "phase": phase, "milestone": m, "task": t,
                        "located_type": "task",
                    }
                rcs = (t or {}).get("required_checkins") or []
                for ri, rc in enumerate(rcs):
                    if isinstance(rc, dict) and rc.get("id") == entity_id:
                        located_type = "required_checkin"
                        if entity_type != located_type:
                            raise HTTPException(
                                status_code=400,
                                detail="entity_id does not identify the requested entity_type",
                            )
                        return {
                            "node": rc, "parent": t, "container_list": rcs,
                            "index": ri, "phase": phase, "milestone": m, "task": t,
                            "located_type": "required_checkin",
                        }

    raise HTTPException(status_code=404, detail=f"Draft {entity_type} not found")


def _validate_editable_values(
    entity_type: str, values: Any, *, require_all: bool,
    allow_nested_children: bool = False,
) -> Dict[str, Any]:
    """Return a dict of validated field->value for a draft edit.

    - Rejects unknown fields (does not silently discard).
    - Validates each supplied field per the batch 2B7 rules.
    - When ``allow_nested_children`` is True (used by ``add``) the reserved
      keys ``milestones``, ``tasks``, and ``required_checkins`` are also
      accepted here — the caller is responsible for consuming them.
    """
    allowed = _DRAFT_EDITABLE_FIELDS[entity_type]
    if not isinstance(values, dict):
        raise HTTPException(status_code=400, detail="values must be an object")
    # Batch 2B8.1 — entity-specific nested child keys, strictly enforced.
    # A phase can only carry a nested `milestones` list, a milestone a
    # nested `tasks` list, a task a nested `required_checkins` list. All
    # other nested keys go through the unknown-field rejection below.
    nested_child_key_by_entity = {
        "phase": "milestones",
        "milestone": "tasks",
        "task": "required_checkins",
        "plan": None,
        "required_checkin": None,
    }
    if allow_nested_children:
        expected_child = nested_child_key_by_entity.get(entity_type)
        child_keys = {expected_child} if expected_child else set()
    else:
        child_keys = set()
    unknown = [k for k in values.keys() if k not in allowed and k not in child_keys]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown field(s) for {entity_type}: {', '.join(sorted(unknown))}",
        )
    if require_all:
        # For ``add``, required_checkin needs title/prompt/cadence explicitly.
        # For phase/milestone/task the create defaults fill in what values omits.
        pass
    out: Dict[str, Any] = {}
    if "title" in values or (require_all and entity_type in {"required_checkin"}):
        t = values.get("title")
        if not (isinstance(t, str) and t.strip()):
            raise HTTPException(status_code=400, detail="title must be a non-empty string")
        out["title"] = t.strip()
    if "description" in values:
        d = values.get("description")
        if d is None:
            out["description"] = None
        elif isinstance(d, str):
            out["description"] = d.strip() if d.strip() else None
        else:
            raise HTTPException(status_code=400, detail="description must be a string or null")
    if "target_date" in values:
        td = values.get("target_date")
        if td is None:
            out["target_date"] = None
        elif isinstance(td, str) and _iso_date(td):
            out["target_date"] = td
        else:
            raise HTTPException(status_code=400, detail="target_date must be null or YYYY-MM-DD")
    if "due_date" in values:
        dd = values.get("due_date")
        if dd is None:
            out["due_date"] = None
        elif isinstance(dd, str) and _iso_date(dd):
            out["due_date"] = dd
        else:
            raise HTTPException(status_code=400, detail="due_date must be null or YYYY-MM-DD")
    if "priority" in values:
        pr = values.get("priority")
        if pr not in VALID_PRIORITIES:
            raise HTTPException(status_code=400, detail="priority must be one of low, medium, high")
        out["priority"] = pr
    if "prompt" in values or (require_all and entity_type == "required_checkin"):
        p = values.get("prompt")
        if not (isinstance(p, str) and p.strip()):
            raise HTTPException(status_code=400, detail="prompt must be a non-empty string")
        out["prompt"] = p.strip()
    if "cadence" in values or (require_all and entity_type == "required_checkin"):
        c = values.get("cadence")
        if c not in VALID_REQUIRED_CHECKIN_CADENCES:
            raise HTTPException(
                status_code=400,
                detail="cadence must be one of once, daily, weekly, monthly, quarterly",
            )
        out["cadence"] = c
    return out


def _op_child_id(message_id: str, operation_id: str, node_type: str, relative_path: str) -> str:
    return str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"hymn:draft-operation:{message_id}:{operation_id}:{node_type}:{relative_path}",
    ))


def _build_added_required_checkin(
    values: Dict[str, Any],
    message_id: str, operation_id: str, relative_path: str,
) -> dict:
    v = _validate_editable_values("required_checkin", values, require_all=True, allow_nested_children=False)
    return {
        "id": _op_child_id(message_id, operation_id, "required_checkin", relative_path),
        "title": v["title"], "prompt": v["prompt"], "cadence": v["cadence"],
    }


def _build_added_task(
    values: Dict[str, Any],
    message_id: str, operation_id: str, relative_path: str,
) -> dict:
    edit = _validate_editable_values("task", values, require_all=False, allow_nested_children=True)
    title = edit.get("title")
    if not title:
        raise HTTPException(status_code=400, detail="title must be a non-empty string")
    rcs_in = values.get("required_checkins")
    if not isinstance(rcs_in, list) or not rcs_in:
        raise HTTPException(
            status_code=400,
            detail="An added task requires values.required_checkins with at least one entry",
        )
    task = {
        "id": _op_child_id(message_id, operation_id, "task", relative_path),
        "title": title,
        "description": edit.get("description", None),
        "due_date": edit.get("due_date", None),
        "priority": edit.get("priority", "medium"),
        "required_checkins": [],
    }
    for ri, rc_values in enumerate(rcs_in):
        if not isinstance(rc_values, dict):
            raise HTTPException(status_code=400, detail=f"required_checkins[{ri}] must be an object")
        task["required_checkins"].append(_build_added_required_checkin(
            rc_values, message_id, operation_id, f"{relative_path}:rc{ri}",
        ))
    return task


def _build_added_milestone(
    values: Dict[str, Any],
    message_id: str, operation_id: str, relative_path: str,
) -> dict:
    edit = _validate_editable_values("milestone", values, require_all=False, allow_nested_children=True)
    title = edit.get("title")
    if not title:
        raise HTTPException(status_code=400, detail="title must be a non-empty string")
    tasks_in = values.get("tasks")
    if not isinstance(tasks_in, list) or not tasks_in:
        raise HTTPException(
            status_code=400,
            detail="An added milestone requires values.tasks with at least one entry",
        )
    milestone = {
        "id": _op_child_id(message_id, operation_id, "milestone", relative_path),
        "title": title,
        "description": edit.get("description", None),
        "target_date": edit.get("target_date", None),
        "tasks": [],
    }
    for ti, t_values in enumerate(tasks_in):
        if not isinstance(t_values, dict):
            raise HTTPException(status_code=400, detail=f"tasks[{ti}] must be an object")
        milestone["tasks"].append(_build_added_task(
            t_values, message_id, operation_id, f"{relative_path}:t{ti}",
        ))
    return milestone


def _build_added_phase(
    values: Dict[str, Any],
    message_id: str, operation_id: str, relative_path: str,
) -> dict:
    edit = _validate_editable_values("phase", values, require_all=False, allow_nested_children=True)
    title = edit.get("title")
    if not title:
        raise HTTPException(status_code=400, detail="title must be a non-empty string")
    milestones_in = values.get("milestones")
    if not isinstance(milestones_in, list) or not milestones_in:
        raise HTTPException(
            status_code=400,
            detail="An added phase requires values.milestones with at least one entry",
        )
    phase = {
        "id": _op_child_id(message_id, operation_id, "phase", relative_path),
        "title": title,
        "description": edit.get("description", None),
        "milestones": [],
    }
    for mi, m_values in enumerate(milestones_in):
        if not isinstance(m_values, dict):
            raise HTTPException(status_code=400, detail=f"milestones[{mi}] must be an object")
        phase["milestones"].append(_build_added_milestone(
            m_values, message_id, operation_id, f"{relative_path}:m{mi}",
        ))
    return phase


def _reassign_duplicate_ids(node: dict, entity_type: str, message_id: str, operation_id: str) -> None:
    """Rewrite every id inside a duplicated subtree to a new deterministic id
    derived from (message_id, operation_id, node_type, original_id).
    """
    original_id = node.get("id")
    node["id"] = _op_child_id(
        message_id, operation_id, entity_type, original_id or "root",
    )
    if entity_type == "phase":
        for m in node.get("milestones") or []:
            _reassign_duplicate_ids(m, "milestone", message_id, operation_id)
    elif entity_type == "milestone":
        for t in node.get("tasks") or []:
            _reassign_duplicate_ids(t, "task", message_id, operation_id)
    elif entity_type == "task":
        for rc in node.get("required_checkins") or []:
            _reassign_duplicate_ids(rc, "required_checkin", message_id, operation_id)


def _apply_draft_hierarchy_operation(
    plan: dict, message_id: str, body: "HierarchyOperationRequest",
) -> dict:
    """Apply exactly one draft edit to a deep copy of the plan and return it.
    Validates the complete resulting hierarchy before returning.
    """
    new_plan = _copy.deepcopy(plan)
    action = body.action
    etype = body.entity_type

    # ------ Action: update -----------------------------------------------
    if action == "update":
        if not body.entity_id:
            raise HTTPException(status_code=400, detail="entity_id is required for update")
        if body.parent_id is not None:
            raise HTTPException(status_code=400, detail="parent_id must be null for update")
        if body.position is not None:
            raise HTTPException(status_code=400, detail="position must be null for update")
        if not isinstance(body.values, dict) or not body.values:
            raise HTTPException(status_code=400, detail="values is required and must not be empty for update")
        loc = _locate_draft_node(new_plan, etype, body.entity_id)
        validated = _validate_editable_values(etype, body.values, require_all=False)
        loc["node"].update(validated)

    # ------ Action: add --------------------------------------------------
    elif action == "add":
        if etype == "plan":
            raise HTTPException(status_code=400, detail="A draft already has one plan")
        if body.entity_id is not None:
            raise HTTPException(status_code=400, detail="entity_id must be null for add")
        if not body.parent_id:
            raise HTTPException(status_code=400, detail="parent_id is required for add")
        if body.position is None:
            raise HTTPException(status_code=400, detail="position is required for add")
        if not isinstance(body.values, dict):
            raise HTTPException(status_code=400, detail="values is required for add")

        # Determine required parent type.
        required_parent_type = {
            "phase": "plan", "milestone": "phase",
            "task": "milestone", "required_checkin": "task",
        }[etype]
        if required_parent_type == "plan":
            if body.parent_id != new_plan.get("id"):
                raise HTTPException(
                    status_code=400,
                    detail="parent_id must reference the draft plan",
                )
            container = new_plan.setdefault("phases", [])
        else:
            parent_loc = _locate_draft_node(new_plan, required_parent_type, body.parent_id)
            child_key = {
                "phase": "milestones", "milestone": "tasks",
                "task": "required_checkins",
            }[required_parent_type]
            container = parent_loc["node"].setdefault(child_key, [])

        max_pos = len(container) + 1
        if body.position < 1 or body.position > max_pos:
            raise HTTPException(
                status_code=400,
                detail=f"position must be between 1 and {max_pos}",
            )

        if etype == "phase":
            new_node = _build_added_phase(body.values, message_id, body.operation_id, "new")
        elif etype == "milestone":
            new_node = _build_added_milestone(body.values, message_id, body.operation_id, "new")
        elif etype == "task":
            new_node = _build_added_task(body.values, message_id, body.operation_id, "new")
        else:  # required_checkin
            new_node = _build_added_required_checkin(body.values, message_id, body.operation_id, "new")

        container.insert(body.position - 1, new_node)

    # ------ Action: delete ----------------------------------------------
    elif action == "delete":
        if not body.entity_id:
            raise HTTPException(status_code=400, detail="entity_id is required for delete")
        if body.values is not None or body.parent_id is not None or body.position is not None:
            raise HTTPException(
                status_code=400,
                detail="values, parent_id, and position must be null for delete",
            )
        if etype == "plan":
            raise HTTPException(status_code=400, detail="The draft plan itself cannot be deleted")
        loc = _locate_draft_node(new_plan, etype, body.entity_id)
        container: List[dict] = loc["container_list"]
        idx: int = loc["index"]
        # Invariants: keep at least one at every level after removal.
        if etype == "phase" and len(container) <= 1:
            raise HTTPException(
                status_code=409, detail="A plan must contain at least one phase",
            )
        if etype == "milestone" and len(container) <= 1:
            raise HTTPException(
                status_code=409, detail="A phase must contain at least one milestone",
            )
        if etype == "task" and len(container) <= 1:
            raise HTTPException(
                status_code=409, detail="A milestone must contain at least one task",
            )
        if etype == "required_checkin" and len(container) <= 1:
            raise HTTPException(
                status_code=409, detail="A task must contain at least one required check-in",
            )
        container.pop(idx)

    # ------ Action: move -------------------------------------------------
    elif action == "move":
        if not body.entity_id:
            raise HTTPException(status_code=400, detail="entity_id is required for move")
        if body.parent_id is None:
            raise HTTPException(status_code=400, detail="parent_id is required for move")
        if body.position is None:
            raise HTTPException(status_code=400, detail="position is required for move")
        if body.values is not None:
            raise HTTPException(status_code=400, detail="values must be null for move")
        if etype == "plan":
            raise HTTPException(status_code=400, detail="The draft plan itself cannot be moved")

        loc = _locate_draft_node(new_plan, etype, body.entity_id)
        source_list: List[dict] = loc["container_list"]
        source_index: int = loc["index"]

        required_parent_type = {
            "phase": "plan", "milestone": "phase",
            "task": "milestone", "required_checkin": "task",
        }[etype]

        if required_parent_type == "plan":
            if body.parent_id != new_plan.get("id"):
                raise HTTPException(
                    status_code=400,
                    detail="parent_id must reference the draft plan",
                )
            dest_list = new_plan.setdefault("phases", [])
        else:
            parent_loc = _locate_draft_node(new_plan, required_parent_type, body.parent_id)
            child_key = {
                "phase": "milestones", "milestone": "tasks",
                "task": "required_checkins",
            }[required_parent_type]
            dest_list = parent_loc["node"].setdefault(child_key, [])

        same_parent = dest_list is source_list
        if same_parent:
            if body.position < 1 or body.position > len(dest_list):
                raise HTTPException(
                    status_code=400,
                    detail=f"position must be between 1 and {len(dest_list)}",
                )
        else:
            # Cross-parent move must not leave source empty.
            if etype == "milestone" and len(source_list) <= 1:
                raise HTTPException(
                    status_code=409,
                    detail="Moving the last milestone out of a phase is forbidden",
                )
            if etype == "task" and len(source_list) <= 1:
                raise HTTPException(
                    status_code=409,
                    detail="Moving the last task out of a milestone is forbidden",
                )
            if etype == "required_checkin" and len(source_list) <= 1:
                raise HTTPException(
                    status_code=409,
                    detail="Moving the last required check-in out of a task is forbidden",
                )
            if body.position < 1 or body.position > len(dest_list) + 1:
                raise HTTPException(
                    status_code=400,
                    detail=f"position must be between 1 and {len(dest_list) + 1}",
                )

        node = source_list.pop(source_index)
        # If same_parent and the removal shifted indices, use raw insert.
        dest_list.insert(body.position - 1, node)

    # ------ Action: duplicate -------------------------------------------
    elif action == "duplicate":
        if not body.entity_id:
            raise HTTPException(status_code=400, detail="entity_id is required for duplicate")
        if body.parent_id is None:
            raise HTTPException(status_code=400, detail="parent_id is required for duplicate")
        if body.position is None:
            raise HTTPException(status_code=400, detail="position is required for duplicate")
        if body.values is not None:
            raise HTTPException(status_code=400, detail="values must be null for duplicate")
        if etype == "plan":
            raise HTTPException(status_code=400, detail="The draft plan itself cannot be duplicated")

        loc = _locate_draft_node(new_plan, etype, body.entity_id)

        required_parent_type = {
            "phase": "plan", "milestone": "phase",
            "task": "milestone", "required_checkin": "task",
        }[etype]

        if required_parent_type == "plan":
            if body.parent_id != new_plan.get("id"):
                raise HTTPException(
                    status_code=400,
                    detail="parent_id must reference the draft plan",
                )
            dest_list = new_plan.setdefault("phases", [])
        else:
            parent_loc = _locate_draft_node(new_plan, required_parent_type, body.parent_id)
            child_key = {
                "phase": "milestones", "milestone": "tasks",
                "task": "required_checkins",
            }[required_parent_type]
            dest_list = parent_loc["node"].setdefault(child_key, [])

        if body.position < 1 or body.position > len(dest_list) + 1:
            raise HTTPException(
                status_code=400,
                detail=f"position must be between 1 and {len(dest_list) + 1}",
            )

        duplicate = _copy.deepcopy(loc["node"])
        _reassign_duplicate_ids(duplicate, etype, message_id, body.operation_id)
        dest_list.insert(body.position - 1, duplicate)

    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {action}")

    # Validate the full resulting hierarchy.
    _validate_plan_hierarchy(new_plan)
    _collect_draft_ids(new_plan)  # ensures every id is present and unique
    return new_plan




async def _materialize_proposal(
    db, user_id: str, target_type: str, target_id: str, proposal: dict,
    conversation_id: str, message_id: str,
) -> Dict[str, Any]:
    """Idempotently apply an additive proposal with best-effort compensation
    for records inserted during the current attempt.

    Not multi-collection atomic — every write is a per-key upsert.
    Reapplying the same (conversation_id, message_id) yields the same records.
    """
    if not isinstance(proposal, dict):
        raise HTTPException(status_code=400, detail="Invalid proposal.")

    # Batch 2B6 — reject unsafe historical operations up front.
    unsafe_review = HTTPException(
        status_code=409,
        detail="This proposal contains changes that require item-by-item review and cannot be applied yet.",
    )
    for legacy_field in ("existing_item_changes", "existing_item_updates", "consolidations"):
        v = proposal.get(legacy_field)
        if isinstance(v, list) and len(v) > 0:
            raise unsafe_review

    now = _now()
    today = datetime.now(timezone.utc).date().isoformat()
    created_outcomes: List[str] = []
    created_tasks: List[str] = []
    created_time_commitments: List[str] = []
    created_checkins: List[str] = []
    # Batch 2B7 — durable Plan hierarchy result buckets.
    plan_document: Optional[dict] = None
    phase_documents: List[dict] = []
    milestone_documents: List[dict] = []
    hierarchical_task_documents: List[dict] = []
    required_checkin_documents: List[dict] = []
    inserted_this_attempt: Dict[str, List[str]] = {
        "expected_outcomes": [], "tasks": [], "time_commitments": [], "checkins": [],
        "plans": [], "plan_phases": [], "plan_milestones": [], "required_checkins": [],
    }
    target_updates: Dict[str, Any] = {}
    plan_input = proposal.get("plan")
    has_plan_hierarchy = plan_input is not None
    if has_plan_hierarchy:
        _validate_plan_hierarchy(plan_input)

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
        # 2. Expected outcomes (goals only).
        if target_type == "goal":
            for idx, eo in enumerate(proposal.get("expected_outcomes") or []):
                if not isinstance(eo, dict):
                    continue
                title = (eo.get("title") or "").strip()
                if not title:
                    continue
                key_lower = title.lower()
                if key_lower in outcome_id_by_title:
                    # Title-dedupe against existing.
                    continue
                key = _materialization_key(conversation_id, message_id, "expected_outcome", str(idx))
                doc = {
                    "id": _materialized_id(key), "user_id": user_id, "goal_id": target_id,
                    "title": title,
                    "target_value": (eo.get("target_value") or "").strip(),
                    "current_value": "",
                    "unit": (eo.get("unit") or "").strip(),
                    "deadline": _iso_date(eo.get("deadline")) or "",
                    "status": "active", "notes": "",
                    "outcome_type": eo.get("outcome_type") or "generic",
                    "planning_materialization_key": key,
                    "created_at": now, "updated_at": now,
                }
                stored, was_new = await _upsert_artifact(db, "expected_outcomes", user_id, key, doc)
                outcome_id_by_title[key_lower] = stored["id"]
                created_outcomes.append(stored["id"])
                if was_new:
                    inserted_this_attempt["expected_outcomes"].append(stored["id"])

        # 2b. Batch 2B7 — Durable Plan → Phase → Milestone → Task →
        # Required Check-in hierarchy. When the proposal carries a
        # `plan` object we materialize this permanent hierarchy and
        # skip the legacy flat tasks/checkins/checkin_recurrences
        # so the same proposal cannot produce two competing views.
        if has_plan_hierarchy:
            plan_title = (plan_input.get("title") or "").strip()
            plan_key = _materialization_key(conversation_id, message_id, "plan", "0")
            plan_doc = {
                "id": _materialized_id(plan_key), "user_id": user_id,
                "target_type": target_type, "target_id": target_id,
                "title": plan_title, "status": "active",
                "source_conversation_id": conversation_id,
                "planning_materialization_key": plan_key,
                "created_at": now, "updated_at": now,
            }
            stored_plan, was_new = await _upsert_artifact(db, "plans", user_id, plan_key, plan_doc)
            plan_document = stored_plan
            plan_id_val = stored_plan["id"]
            if was_new:
                inserted_this_attempt["plans"].append(stored_plan["id"])
            for pi, phase in enumerate(plan_input.get("phases") or []):
                phase_title = (phase.get("title") or "").strip()
                phase_desc_raw = phase.get("description")
                phase_desc = phase_desc_raw.strip() if isinstance(phase_desc_raw, str) and phase_desc_raw.strip() else None
                phase_key = _materialization_key(conversation_id, message_id, "phase", str(pi))
                phase_doc = {
                    "id": _materialized_id(phase_key), "user_id": user_id,
                    "plan_id": plan_id_val,
                    "title": phase_title, "description": phase_desc,
                    "position": pi + 1, "status": "active",
                    "source_conversation_id": conversation_id,
                    "planning_materialization_key": phase_key,
                    "created_at": now, "updated_at": now,
                }
                stored_phase, was_new = await _upsert_artifact(db, "plan_phases", user_id, phase_key, phase_doc)
                phase_documents.append(stored_phase)
                phase_id_val = stored_phase["id"]
                if was_new:
                    inserted_this_attempt["plan_phases"].append(stored_phase["id"])
                for mi, milestone in enumerate(phase.get("milestones") or []):
                    m_title = (milestone.get("title") or "").strip()
                    m_desc_raw = milestone.get("description")
                    m_desc = m_desc_raw.strip() if isinstance(m_desc_raw, str) and m_desc_raw.strip() else None
                    m_target_date = _iso_date(milestone.get("target_date")) or None
                    m_key = _materialization_key(conversation_id, message_id, "milestone", f"{pi}:{mi}")
                    m_doc = {
                        "id": _materialized_id(m_key), "user_id": user_id,
                        "plan_id": plan_id_val, "phase_id": phase_id_val,
                        "title": m_title, "description": m_desc,
                        "target_date": m_target_date,
                        "position": mi + 1, "status": "active",
                        "source_conversation_id": conversation_id,
                        "planning_materialization_key": m_key,
                        "created_at": now, "updated_at": now,
                    }
                    stored_m, was_new = await _upsert_artifact(db, "plan_milestones", user_id, m_key, m_doc)
                    milestone_documents.append(stored_m)
                    milestone_id_val = stored_m["id"]
                    if was_new:
                        inserted_this_attempt["plan_milestones"].append(stored_m["id"])
                    for ti, task in enumerate(milestone.get("tasks") or []):
                        t_title = (task.get("title") or "").strip()
                        t_desc_raw = task.get("description")
                        t_desc = t_desc_raw.strip() if isinstance(t_desc_raw, str) and t_desc_raw.strip() else ""
                        t_due = _iso_date(task.get("due_date")) or ""
                        t_priority = (task.get("priority") or "medium").lower()
                        if t_priority not in VALID_PRIORITIES:
                            t_priority = "medium"
                        t_key = _materialization_key(conversation_id, message_id, "task", f"{pi}:{mi}:{ti}")
                        t_doc = {
                            "id": _materialized_id(t_key), "user_id": user_id,
                            "title": t_title, "description": t_desc,
                            "due_date": t_due, "priority": t_priority,
                            "status": "todo",
                            "notes": "",
                            "origin": "plan",
                            "plan_id": plan_id_val,
                            "phase_id": phase_id_val,
                            "milestone_id": milestone_id_val,
                            "goal_id": target_id if target_type == "goal" else None,
                            "project_id": target_id if target_type == "project" else None,
                            "expected_outcome_id": None,
                            "plan_position": ti + 1,
                            "assigned_to_type": "self", "assigned_to_name": "", "assigned_to_phone": "",
                            "commitment_type": "postponable",
                            "planning_materialization_key": t_key,
                            "created_at": now, "updated_at": now,
                        }
                        stored_t, was_new = await _upsert_artifact(db, "tasks", user_id, t_key, t_doc)
                        hierarchical_task_documents.append(stored_t)
                        task_id_val = stored_t["id"]
                        created_tasks.append(stored_t["id"])
                        if was_new:
                            inserted_this_attempt["tasks"].append(stored_t["id"])
                        for ri, rc in enumerate(task.get("required_checkins") or []):
                            rc_title = (rc.get("title") or "").strip()
                            rc_prompt = (rc.get("prompt") or "").strip()
                            rc_cadence = rc.get("cadence")
                            rc_key = _materialization_key(
                                conversation_id, message_id, "required_checkin",
                                f"{pi}:{mi}:{ti}:{ri}",
                            )
                            rc_doc = {
                                "id": _materialized_id(rc_key), "user_id": user_id,
                                "plan_id": plan_id_val, "phase_id": phase_id_val,
                                "milestone_id": milestone_id_val, "task_id": task_id_val,
                                "title": rc_title, "prompt": rc_prompt,
                                "cadence": rc_cadence,
                                "position": ri + 1, "status": "active",
                                "source_conversation_id": conversation_id,
                                "planning_materialization_key": rc_key,
                                "created_at": now, "updated_at": now,
                            }
                            stored_rc, was_new = await _upsert_artifact(
                                db, "required_checkins", user_id, rc_key, rc_doc,
                            )
                            required_checkin_documents.append(stored_rc)
                            if was_new:
                                inserted_this_attempt["required_checkins"].append(stored_rc["id"])

        # 3. Tasks (legacy flat proposal path — only when no plan hierarchy).
        if not has_plan_hierarchy:
            for idx, tk in enumerate(proposal.get("tasks") or []):
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
                else:
                    project_id = target_id
                    origin = "project"
                key = _materialization_key(conversation_id, message_id, "task", str(idx))
                doc = {
                    "id": _materialized_id(key), "user_id": user_id,
                    "title": title, "due_date": due,
                    "priority": priority, "status": "todo",
                    "notes": (tk.get("notes") or "").strip(),
                    "origin": origin,
                    "expected_outcome_id": expected_outcome_id,
                    "project_id": project_id,
                    "component_id": None,
                    "assigned_to_type": "self", "assigned_to_name": "", "assigned_to_phone": "",
                    "commitment_type": commitment_type,
                    "planning_materialization_key": key,
                    "created_at": now, "updated_at": now,
                }
                stored, was_new = await _upsert_artifact(db, "tasks", user_id, key, doc)
                created_tasks.append(stored["id"])
                if was_new:
                    inserted_this_attempt["tasks"].append(stored["id"])

        # 4. Time commitments.
        for idx, tc in enumerate(proposal.get("time_commitments") or []):
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
            key = _materialization_key(conversation_id, message_id, "time_commitment", str(idx))
            doc = {
                "id": _materialized_id(key), "user_id": user_id,
                "title": title, "day_of_week": day,
                "start_time": start, "end_time": end,
                "commitment_type": ctype, "flexibility": flex,
                "effective_from": today, "effective_until": None,
                "source_type": "system", "source_id": None,
                "notes": (tc.get("notes") or "").strip(),
                "planning_materialization_key": key,
                "created_at": now, "updated_at": now,
            }
            stored, was_new = await _upsert_artifact(db, "time_commitments", user_id, key, doc)
            created_time_commitments.append(stored["id"])
            if was_new:
                inserted_this_attempt["time_commitments"].append(stored["id"])

        # 5. Check-ins.
        async def _resolve_checkin_anchor(entry: dict) -> Optional[Dict[str, Any]]:
            ci_type = (entry.get("type") or "").lower()
            if ci_type not in VALID_CHECKIN_TYPES:
                return None
            base = {"type": ci_type,
                    "expected_outcome_id": None, "goal_id": None,
                    "project_id": None, "task_id": None,
                    "outcome_type": None}
            if ci_type == "goal":
                eo_title = (entry.get("expected_outcome_title") or "").strip().lower()
                eo_id: Optional[str] = None
                if eo_title and eo_title in outcome_id_by_title:
                    eo_id = outcome_id_by_title[eo_title]
                elif target_type == "goal" and outcome_id_by_title:
                    eo_id = next(iter(outcome_id_by_title.values()))
                if not eo_id:
                    return None
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
            return base

        for idx, entry in enumerate((proposal.get("checkins") or []) if not has_plan_hierarchy else []):
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
            key = _materialization_key(conversation_id, message_id, "checkin", str(idx))
            doc = {
                "id": _materialized_id(key), "user_id": user_id,
                "type": anchor["type"], "title": title,
                "date": date, "time": time_hhmm,
                "notes": (entry.get("notes") or "").strip(), "attachment": "",
                "expected_outcome_id": anchor["expected_outcome_id"],
                "goal_id": anchor["goal_id"], "project_id": anchor["project_id"],
                "task_id": None, "component_id": None, "follow_up_task_id": None,
                "source": "system", "outcome_type": anchor["outcome_type"],
                "data": {}, "money_spent": None, "money_currency": None,
                "planning_materialization_key": key,
                "created_at": now, "updated_at": now,
            }
            stored, was_new = await _upsert_artifact(db, "checkins", user_id, key, doc)
            created_checkins.append(stored["id"])
            if was_new:
                inserted_this_attempt["checkins"].append(stored["id"])

        # 6. Recurring check-ins (legacy — skipped when plan hierarchy present).
        for rule_index, rule in enumerate((proposal.get("checkin_recurrences") or []) if not has_plan_hierarchy else []):
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
                dows = None
            for d in _iter_dates(start, end, dows):
                key = _materialization_key(conversation_id, message_id, "recurring_checkin", f"{rule_index}:{d}")
                doc = {
                    "id": _materialized_id(key), "user_id": user_id,
                    "type": anchor["type"], "title": title,
                    "date": d, "time": time_hhmm,
                    "notes": (rule.get("notes") or "").strip(), "attachment": "",
                    "expected_outcome_id": anchor["expected_outcome_id"],
                    "goal_id": anchor["goal_id"], "project_id": anchor["project_id"],
                    "task_id": None, "component_id": None, "follow_up_task_id": None,
                    "source": "system", "outcome_type": anchor["outcome_type"],
                    "data": {}, "money_spent": None, "money_currency": None,
                    "planning_materialization_key": key,
                    "created_at": now, "updated_at": now,
                }
                stored, was_new = await _upsert_artifact(db, "checkins", user_id, key, doc)
                created_checkins.append(stored["id"])
                if was_new:
                    inserted_this_attempt["checkins"].append(stored["id"])

        # 7. Cadence + target updates (deadline / notes / commitment_type only).
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
        # Best-effort compensation — only for records inserted THIS attempt.
        for tid in inserted_this_attempt["tasks"]:
            await db.tasks.delete_one({"id": tid, "user_id": user_id})
        for eid in inserted_this_attempt["expected_outcomes"]:
            await db.expected_outcomes.delete_one({"id": eid, "user_id": user_id})
        for tcid in inserted_this_attempt["time_commitments"]:
            await db.time_commitments.delete_one({"id": tcid, "user_id": user_id})
        for cid in inserted_this_attempt["checkins"]:
            await db.checkins.delete_one({"id": cid, "user_id": user_id})
        # Batch 2B7 — compensation for plan hierarchy inserts.
        for rcid in inserted_this_attempt["required_checkins"]:
            await db.required_checkins.delete_one({"id": rcid, "user_id": user_id})
        for mid in inserted_this_attempt["plan_milestones"]:
            await db.plan_milestones.delete_one({"id": mid, "user_id": user_id})
        for phid in inserted_this_attempt["plan_phases"]:
            await db.plan_phases.delete_one({"id": phid, "user_id": user_id})
        for pid in inserted_this_attempt["plans"]:
            await db.plans.delete_one({"id": pid, "user_id": user_id})
        raise HTTPException(status_code=500,
                            detail=f"Failed to apply proposal: {type(exc).__name__}")

    return {
        "created_outcomes": created_outcomes,
        "created_tasks": created_tasks,
        "created_time_commitments": created_time_commitments,
        "created_checkins": created_checkins,
        "target_updated": bool(target_updates),
        # Batch 2B7 — durable Plan hierarchy artifacts (empty for legacy proposals).
        "plan": plan_document,
        "phases": phase_documents,
        "milestones": milestone_documents,
        "tasks": hierarchical_task_documents,
        "required_checkins": required_checkin_documents,
    }


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class MessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class MaterializeRequest(BaseModel):
    message_id: str
    # Batch 2B8 — required for editable plan proposals so that a concurrent
    # edit cannot slip in between reading and materializing the draft. Legacy
    # proposals (no plan hierarchy) may still omit this.
    expected_proposal_revision: Optional[int] = Field(default=None, ge=1)


class HierarchyOperationRequest(BaseModel):
    operation_id: str = Field(min_length=1, max_length=64)
    expected_revision: int = Field(ge=1)
    action: Literal["add", "update", "delete", "move", "duplicate"]
    entity_type: Literal[
        "plan",
        "phase",
        "milestone",
        "task",
        "required_checkin",
    ]
    entity_id: Optional[str] = None
    parent_id: Optional[str] = None
    position: Optional[int] = Field(default=None, ge=1)
    values: Optional[Dict[str, Any]] = None


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
    # LLM call uses in-memory copy of history including this user_msg.
    conv_messages_for_llm = list(conv.get("messages") or []) + [user_msg]
    raw = await _call_llm(conv_messages_for_llm, body.content.strip(), ctx)
    prose, proposal = _split_message(raw)
    if not prose and proposal:
        prose = proposal.get("summary") or "Here are some proposed changes for your plan."

    # Batch 2B8 — generate the assistant message id up front so that when
    # the proposal carries a durable Plan hierarchy we can normalise it with
    # stable draft node ids anchored to this message id before storing.
    assistant_message_id = _uuid()
    if isinstance(proposal, dict) and isinstance(proposal.get("plan"), dict):
        _validate_plan_hierarchy(proposal["plan"])
        proposal["plan"] = _normalise_draft_hierarchy(proposal["plan"], assistant_message_id)
        asst_msg = {
            "id": assistant_message_id, "role": "assistant",
            "content": raw,
            "proposal": proposal,
            "proposal_revision": 1,
            "proposal_operation_ids": [],
            "created_at": _now(),
        }
    else:
        asst_msg = {
            "id": assistant_message_id, "role": "assistant",
            "content": raw,
            "proposal": proposal,
            "created_at": _now(),
        }

    # Batch 2B6 — atomic $push instead of a whole-document replace so a
    # concurrent write can't erase materialization state.
    r = await db.plan_conversations.update_one(
        {"id": conv["id"], "user_id": current_user["id"]},
        {"$push": {"messages": {"$each": [user_msg, asst_msg]}},
         "$set": {"updated_at": _now()}},
    )
    if r.modified_count == 0:
        raise HTTPException(status_code=409, detail="Conversation changed; reload and try again.")
    fresh = await db.plan_conversations.find_one(
        {"id": conv["id"], "user_id": current_user["id"]}, {"_id": 0},
    )
    return _public_conversation(fresh or conv)


@planning_router.post("/{target_type}/{target_id}/reset")
async def reset_conversation(
    target_type: str, target_id: str,
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    _require(target_type in TARGET_TYPES, f"target_type must be one of {list(TARGET_TYPES)}")
    await _read_target(db, current_user["id"], target_type, target_id)
    # Batch 2B6 — refuse to delete while a materialization is in flight.
    r = await db.plan_conversations.delete_one({
        "user_id": current_user["id"],
        "target_type": target_type,
        "target_id": target_id,
        "messages": {"$not": {"$elemMatch": {"materialization_state": "applying"}}},
    })
    if r.deleted_count == 0:
        still = await db.plan_conversations.find_one(
            {"user_id": current_user["id"], "target_type": target_type, "target_id": target_id},
            {"_id": 0, "id": 1},
        )
        if still:
            raise HTTPException(
                status_code=409,
                detail="A proposal is currently being applied. Try again after it finishes.",
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
    for m in conv.get("messages") or []:
        if m.get("id") == body.message_id:
            target_msg = m
            break
    if not target_msg:
        raise HTTPException(status_code=404, detail="Message not found")
    if target_msg.get("materialized_at"):
        # Already applied — return stored result idempotently.
        return {
            "conversation": _public_conversation(conv),
            "result": target_msg.get("materialization_result") or {},
        }
    proposal = target_msg.get("proposal")
    if not proposal:
        raise HTTPException(status_code=400, detail="This message has no proposal to apply.")

    # Batch 2B8 — revision guard for editable plan proposals.
    has_plan = isinstance(proposal, dict) and isinstance(proposal.get("plan"), dict)
    if has_plan:
        if body.expected_proposal_revision is None:
            raise HTTPException(
                status_code=400,
                detail="expected_proposal_revision is required for an editable plan",
            )
        stored_rev = target_msg.get("proposal_revision")
        if not isinstance(stored_rev, int) or stored_rev != body.expected_proposal_revision:
            raise HTTPException(
                status_code=409,
                detail="The draft changed; refresh it before applying",
            )

    # Batch 2B6 — atomic claim on the embedded message. Batch 2B8 adds a
    # proposal_revision predicate so that any edit racing this claim is
    # forced to fail with a revision-mismatch 409.
    claim_id = _uuid()
    claim_started_at = _now()
    claim_elem_match: Dict[str, Any] = {
        "id": body.message_id,
        "materialized_at": {"$exists": False},
        "$or": [
            {"materialization_state": {"$exists": False}},
            {"materialization_state": "failed"},
        ],
    }
    if has_plan:
        claim_elem_match["proposal_revision"] = body.expected_proposal_revision
    claim = await db.plan_conversations.update_one(
        {
            "id": conversation_id,
            "user_id": current_user["id"],
            "messages": {"$elemMatch": claim_elem_match},
        },
        {
            "$set": {
                "messages.$.materialization_state": "applying",
                "messages.$.materialization_claim_id": claim_id,
                "messages.$.materialization_started_at": claim_started_at,
                "updated_at": _now(),
            },
        },
    )
    if claim.modified_count == 0:
        fresh = await db.plan_conversations.find_one(
            {"id": conversation_id, "user_id": current_user["id"]}, {"_id": 0},
        )
        if fresh:
            for m in fresh.get("messages") or []:
                if m.get("id") == body.message_id:
                    if m.get("materialization_state") == "applied" and m.get("materialized_at"):
                        return {
                            "conversation": _public_conversation(fresh),
                            "result": m.get("materialization_result") or {},
                        }
                    if m.get("materialization_state") == "applying":
                        raise HTTPException(status_code=409, detail="This proposal is already being applied.")
                    if has_plan and m.get("proposal_revision") != body.expected_proposal_revision:
                        raise HTTPException(
                            status_code=409,
                            detail="The draft changed; refresh it before applying",
                        )
                    break
        raise HTTPException(status_code=409, detail="This proposal could not be claimed for application.")

    try:
        # Batch 2B8.1 — reread + claim verification are now INSIDE the try
        # block so that any failure here runs the existing except-cleanup
        # and clears the "applying" state. This matches the guarantee that
        # a claim once set is always released (either to "applied" or to
        # "failed") no matter which downstream step raises.
        claimed_conv = await db.plan_conversations.find_one(
            {"id": conversation_id, "user_id": current_user["id"]}, {"_id": 0},
        ) or conv
        claimed_msg: Optional[dict] = None
        for m in claimed_conv.get("messages") or []:
            if m.get("id") == body.message_id and m.get("materialization_claim_id") == claim_id:
                claimed_msg = m
                break
        if claimed_msg is None or not isinstance(claimed_msg.get("proposal"), dict):
            raise HTTPException(
                status_code=409,
                detail="This proposal could not be claimed for application.",
            )
        proposal = claimed_msg["proposal"]

        result = await _materialize_proposal(
            db, current_user["id"], conv["target_type"], conv["target_id"], proposal,
            conversation_id=conversation_id, message_id=body.message_id,
        )
        bits: List[str] = []
        if result.get("created_outcomes"):
            n = len(result["created_outcomes"]); bits.append(f"{n} outcome{'s' if n != 1 else ''}")
        if result.get("created_tasks"):
            n = len(result["created_tasks"]); bits.append(f"{n} task{'s' if n != 1 else ''}")
        if result.get("created_checkins"):
            n = len(result["created_checkins"]); bits.append(f"{n} check-in{'s' if n != 1 else ''}")
        if result.get("created_time_commitments"):
            n = len(result["created_time_commitments"]); bits.append(f"{n} time commitment{'s' if n != 1 else ''}")
        summary = "Added " + ", ".join(bits) + "." if bits else "Applied."

        finalise = await db.plan_conversations.update_one(
            {
                "id": conversation_id,
                "user_id": current_user["id"],
                "messages": {"$elemMatch": {
                    "id": body.message_id,
                    "materialization_claim_id": claim_id,
                }},
            },
            {
                "$set": {
                    "messages.$.materialization_state": "applied",
                    "messages.$.materialized_at": _now(),
                    "messages.$.materialized_summary": summary,
                    "messages.$.materialization_result": result,
                    "updated_at": _now(),
                },
                "$unset": {
                    "messages.$.materialization_claim_id": "",
                    "messages.$.materialization_started_at": "",
                    "messages.$.materialization_error": "",
                },
            },
        )
        if finalise.modified_count == 0:
            raise HTTPException(
                status_code=409,
                detail="Proposal application completed but its conversation state could not be finalized.",
            )
        fresh = await db.plan_conversations.find_one(
            {"id": conversation_id, "user_id": current_user["id"]}, {"_id": 0},
        )
        return {"conversation": _public_conversation(fresh or conv), "result": result}
    except Exception as exc:
        await db.plan_conversations.update_one(
            {
                "id": conversation_id,
                "user_id": current_user["id"],
                "messages": {"$elemMatch": {
                    "id": body.message_id,
                    "materialization_claim_id": claim_id,
                }},
            },
            {
                "$set": {
                    "messages.$.materialization_state": "failed",
                    "messages.$.materialization_error": type(exc).__name__,
                    "updated_at": _now(),
                },
                "$unset": {
                    "messages.$.materialization_claim_id": "",
                    "messages.$.materialization_started_at": "",
                },
            },
        )
        raise


# ---------------------------------------------------------------------------
# Batch 2B8 — draft (in-conversation) hierarchy editing endpoints.
# These operate ONLY on the proposal.plan embedded in the assistant message
# in plan_conversations. They MUST NEVER edit permanent hierarchy records.
# No LLM call happens here.
# ---------------------------------------------------------------------------


def _get_assistant_hierarchy_message(conv: dict, message_id: str) -> dict:
    """Return the assistant message with an editable plan hierarchy, or
    raise the appropriate error (404 / 400 / 409)."""
    target_msg: Optional[dict] = None
    for m in conv.get("messages") or []:
        if m.get("id") == message_id:
            target_msg = m
            break
    if not target_msg:
        raise HTTPException(status_code=404, detail="Message not found")
    if target_msg.get("role") != "assistant":
        raise HTTPException(status_code=400, detail="This message has no editable plan hierarchy")
    proposal = target_msg.get("proposal")
    if not isinstance(proposal, dict) or not isinstance(proposal.get("plan"), dict):
        raise HTTPException(status_code=400, detail="This message has no editable plan hierarchy")
    if target_msg.get("materialized_at"):
        raise HTTPException(status_code=409, detail="This proposal has already been applied")
    if target_msg.get("materialization_state") == "applied":
        raise HTTPException(status_code=409, detail="This proposal has already been applied")
    if target_msg.get("materialization_state") == "applying":
        raise HTTPException(status_code=409, detail="This proposal is currently being applied")
    return target_msg


def _valid_uuid(v: Any) -> bool:
    if not isinstance(v, str) or not v:
        return False
    try:
        uuid.UUID(v)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


@planning_router.get("/conversations/{conversation_id}/proposals/{message_id}/hierarchy")
async def read_draft_hierarchy(
    conversation_id: str, message_id: str,
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    conv = await db.plan_conversations.find_one(
        {"id": conversation_id, "user_id": current_user["id"]}, {"_id": 0},
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    msg = _get_assistant_hierarchy_message(conv, message_id)

    # Batch 2B8.2 — strict presence/validity checks. `type(x) is int` (not
    # ``isinstance``) rejects booleans, which are ``int`` subclass instances
    # in Python but must never be treated as revisions.
    stored_revision_raw = msg.get("proposal_revision")
    stored_operations_raw = msg.get("proposal_operation_ids")
    needs_backfill = not (
        type(stored_revision_raw) is int
        and stored_revision_raw >= 1
        and isinstance(stored_operations_raw, list)
    )
    plan = msg["proposal"].get("plan") or {}
    # Also backfill if any node is missing an id.
    try:
        _collect_draft_ids(plan)
        ids_ok = True
    except HTTPException:
        ids_ok = False

    if needs_backfill or not ids_ok:
        normalised = _normalise_draft_hierarchy(plan, message_id)

        # Batch 2B8.1 / 2B8.2 — compare-and-set predicate.
        # Field PRESENCE and field VALIDITY are captured separately: the
        # predicate must match the exact stored raw value when the field is
        # present, even if that value is malformed (null, 0, True/False, a
        # string, or a wrong-typed list). Only if the field is truly absent
        # do we match ``{"$exists": False}``. This lets a subsequent write
        # repair malformed fields instead of stalling forever.
        snapshot_plan = plan
        revision_field_present = "proposal_revision" in msg
        operations_field_present = "proposal_operation_ids" in msg
        snapshot_rev_raw = stored_revision_raw  # raw, unconverted
        snapshot_ops_raw = stored_operations_raw  # raw, unconverted

        # Writing values are normalised strictly.
        new_revision = (
            snapshot_rev_raw
            if type(snapshot_rev_raw) is int and snapshot_rev_raw >= 1
            else 1
        )
        new_ops = (
            list(snapshot_ops_raw)
            if isinstance(snapshot_ops_raw, list)
            else []
        )

        elem_match: Dict[str, Any] = {
            "id": message_id,
            "materialized_at": {"$exists": False},
            "materialization_state": {"$nin": ["applying", "applied"]},
            "proposal.plan": snapshot_plan,
        }
        if revision_field_present:
            elem_match["proposal_revision"] = snapshot_rev_raw
        else:
            elem_match["proposal_revision"] = {"$exists": False}
        if operations_field_present:
            elem_match["proposal_operation_ids"] = snapshot_ops_raw
        else:
            elem_match["proposal_operation_ids"] = {"$exists": False}

        r = await db.plan_conversations.update_one(
            {
                "id": conversation_id,
                "user_id": current_user["id"],
                "messages": {"$elemMatch": elem_match},
            },
            {
                "$set": {
                    "messages.$.proposal.plan": normalised,
                    "messages.$.proposal_revision": new_revision,
                    "messages.$.proposal_operation_ids": new_ops,
                    "updated_at": _now(),
                },
            },
        )
        # Whether the CAS write hit or not, always re-read and re-check the
        # message. modified_count == 0 might just mean another request
        # (concurrent normalise, edit, apply) already put the message into
        # a healthier state — in which case we should serve THAT hierarchy,
        # not our stale one.
        conv = await db.plan_conversations.find_one(
            {"id": conversation_id, "user_id": current_user["id"]}, {"_id": 0},
        )
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        # _get_assistant_hierarchy_message raises the state-specific 409s
        # (applied / applying) — those responses must be preserved.
        msg = _get_assistant_hierarchy_message(conv, message_id)

        fresh_plan = (msg.get("proposal") or {}).get("plan")
        fresh_rev = msg.get("proposal_revision")
        fresh_ops = msg.get("proposal_operation_ids")
        fresh_is_valid = False
        # Batch 2B8.2 — exact int type check so booleans do not sneak in as
        # revisions.
        if (
            isinstance(fresh_plan, dict)
            and type(fresh_rev) is int
            and fresh_rev >= 1
            and isinstance(fresh_ops, list)
        ):
            try:
                _validate_plan_hierarchy(fresh_plan)
                _collect_draft_ids(fresh_plan)
                fresh_is_valid = True
            except HTTPException:
                fresh_is_valid = False
        if not fresh_is_valid:
            # Do NOT persist or return the stale in-memory hierarchy.
            raise HTTPException(status_code=409, detail="The draft changed; refresh it and try again")

    return {
        "conversation_id": conversation_id,
        "message_id": message_id,
        "proposal_revision": msg.get("proposal_revision") or 1,
        "plan": (msg.get("proposal") or {}).get("plan") or {},
    }


@planning_router.post(
    "/conversations/{conversation_id}/proposals/{message_id}/hierarchy/operations"
)
async def apply_hierarchy_operation(
    conversation_id: str, message_id: str, body: HierarchyOperationRequest,
    current_user: dict = Depends(get_current_user),
):
    if not _valid_uuid(body.operation_id):
        raise HTTPException(status_code=400, detail="operation_id must be a valid UUID")

    db = get_db()
    conv = await db.plan_conversations.find_one(
        {"id": conversation_id, "user_id": current_user["id"]}, {"_id": 0},
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    msg = _get_assistant_hierarchy_message(conv, message_id)

    # Idempotency — the same operation id must not be applied twice.
    existing_ops = list(msg.get("proposal_operation_ids") or [])
    if body.operation_id in existing_ops:
        return {
            "conversation_id": conversation_id,
            "message_id": message_id,
            "operation_id": body.operation_id,
            "proposal_revision": msg.get("proposal_revision") or 1,
            "plan": (msg.get("proposal") or {}).get("plan") or {},
        }

    stored_rev = msg.get("proposal_revision")
    if not isinstance(stored_rev, int) or stored_rev != body.expected_revision:
        raise HTTPException(status_code=409, detail="The draft changed; refresh it and try again")

    current_plan = (msg.get("proposal") or {}).get("plan") or {}
    updated_plan = _apply_draft_hierarchy_operation(current_plan, message_id, body)

    r = await db.plan_conversations.update_one(
        {
            "id": conversation_id,
            "user_id": current_user["id"],
            "messages": {"$elemMatch": {
                "id": message_id,
                "proposal_revision": body.expected_revision,
                "materialized_at": {"$exists": False},
                "materialization_state": {"$nin": ["applying", "applied"]},
                "proposal_operation_ids": {"$ne": body.operation_id},
            }},
        },
        {
            "$set": {
                "messages.$.proposal.plan": updated_plan,
                "messages.$.proposal_revision": body.expected_revision + 1,
                "updated_at": _now(),
            },
            "$push": {"messages.$.proposal_operation_ids": body.operation_id},
            "$unset": {
                "messages.$.materialization_state": "",
                "messages.$.materialization_error": "",
            },
        },
    )

    if r.modified_count == 0:
        fresh = await db.plan_conversations.find_one(
            {"id": conversation_id, "user_id": current_user["id"]}, {"_id": 0},
        )
        if fresh:
            for m in fresh.get("messages") or []:
                if m.get("id") == message_id:
                    if body.operation_id in (m.get("proposal_operation_ids") or []):
                        return {
                            "conversation_id": conversation_id,
                            "message_id": message_id,
                            "operation_id": body.operation_id,
                            "proposal_revision": m.get("proposal_revision") or 1,
                            "plan": (m.get("proposal") or {}).get("plan") or {},
                        }
                    if m.get("materialized_at") or m.get("materialization_state") == "applied":
                        raise HTTPException(status_code=409, detail="This proposal has already been applied")
                    if m.get("materialization_state") == "applying":
                        raise HTTPException(status_code=409, detail="This proposal is currently being applied")
                    break
        raise HTTPException(status_code=409, detail="The draft changed; refresh it and try again")

    return {
        "conversation_id": conversation_id,
        "message_id": message_id,
        "operation_id": body.operation_id,
        "proposal_revision": body.expected_revision + 1,
        "plan": updated_plan,
    }


# ---------------------------------------------------------------------------
# Durable Plan hierarchy — read-only endpoints (Batch 2B7)
# ---------------------------------------------------------------------------


@planning_router.get("/hierarchy/targets/{target_type}/{target_id}")
async def list_target_plans(
    target_type: str, target_id: str,
    current_user: dict = Depends(get_current_user),
):
    _require(target_type in TARGET_TYPES, f"target_type must be one of {list(TARGET_TYPES)}")
    db = get_db()
    plans = await db.plans.find(
        {
            "user_id": current_user["id"],
            "target_type": target_type,
            "target_id": target_id,
        },
        {"_id": 0},
    ).sort("created_at", -1).to_list(length=500)
    return {"plans": plans}


@planning_router.get("/hierarchy/plans/{plan_id}")
async def read_plan_hierarchy(
    plan_id: str,
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    plan = await db.plans.find_one(
        {"id": plan_id, "user_id": current_user["id"]}, {"_id": 0},
    )
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    phases = await db.plan_phases.find(
        {"user_id": current_user["id"], "plan_id": plan_id}, {"_id": 0},
    ).sort("position", 1).to_list(length=1000)
    milestones = await db.plan_milestones.find(
        {"user_id": current_user["id"], "plan_id": plan_id}, {"_id": 0},
    ).sort("position", 1).to_list(length=5000)
    tasks = await db.tasks.find(
        {"user_id": current_user["id"], "plan_id": plan_id}, {"_id": 0},
    ).sort("plan_position", 1).to_list(length=20000)
    required_checkins = await db.required_checkins.find(
        {"user_id": current_user["id"], "plan_id": plan_id}, {"_id": 0},
    ).sort("position", 1).to_list(length=50000)

    tasks_by_milestone: Dict[str, List[dict]] = {}
    for t in tasks:
        tasks_by_milestone.setdefault(t.get("milestone_id") or "", []).append(t)
    for lst in tasks_by_milestone.values():
        lst.sort(key=lambda x: int(x.get("plan_position") or 0))

    rcs_by_task: Dict[str, List[dict]] = {}
    for rc in required_checkins:
        rcs_by_task.setdefault(rc.get("task_id") or "", []).append(rc)
    for lst in rcs_by_task.values():
        lst.sort(key=lambda x: int(x.get("position") or 0))

    milestones_by_phase: Dict[str, List[dict]] = {}
    for m in milestones:
        milestones_by_phase.setdefault(m.get("phase_id") or "", []).append(m)
    for lst in milestones_by_phase.values():
        lst.sort(key=lambda x: int(x.get("position") or 0))

    phases.sort(key=lambda x: int(x.get("position") or 0))
    nested_phases: List[dict] = []
    for phase in phases:
        phase_out = dict(phase)
        phase_milestones = milestones_by_phase.get(phase["id"], [])
        nested_milestones: List[dict] = []
        for m in phase_milestones:
            m_out = dict(m)
            m_tasks = tasks_by_milestone.get(m["id"], [])
            nested_tasks: List[dict] = []
            for t in m_tasks:
                t_out = dict(t)
                t_out["required_checkins"] = rcs_by_task.get(t["id"], [])
                nested_tasks.append(t_out)
            m_out["tasks"] = nested_tasks
            nested_milestones.append(m_out)
        phase_out["milestones"] = nested_milestones
        nested_phases.append(phase_out)

    plan_out = dict(plan)
    plan_out["phases"] = nested_phases
    return {"plan": plan_out}


# ---------------------------------------------------------------------------
# Index bootstrap
# ---------------------------------------------------------------------------


async def ensure_planning_indexes(database) -> None:
    await database.plan_conversations.create_index("id", unique=True)
    await database.plan_conversations.create_index(
        [("user_id", 1), ("target_type", 1), ("target_id", 1)], unique=True,
    )
    await database.plan_conversations.create_index([("user_id", 1), ("updated_at", -1)])
    # Batch 2B6 — per-collection partial unique indexes on the
    # materialization key so retries cannot create duplicates even if
    # the app-level upsert loses the race with a concurrent writer.
    await database.expected_outcomes.create_index(
        [("user_id", 1), ("planning_materialization_key", 1)],
        unique=True,
        partialFilterExpression={"planning_materialization_key": {"$type": "string"}},
        name="expected_outcomes_planning_mat_key_uniq",
    )
    await database.tasks.create_index(
        [("user_id", 1), ("planning_materialization_key", 1)],
        unique=True,
        partialFilterExpression={"planning_materialization_key": {"$type": "string"}},
        name="tasks_planning_mat_key_uniq",
    )
    await database.time_commitments.create_index(
        [("user_id", 1), ("planning_materialization_key", 1)],
        unique=True,
        partialFilterExpression={"planning_materialization_key": {"$type": "string"}},
        name="time_commitments_planning_mat_key_uniq",
    )
    await database.checkins.create_index(
        [("user_id", 1), ("planning_materialization_key", 1)],
        unique=True,
        partialFilterExpression={"planning_materialization_key": {"$type": "string"}},
        name="checkins_planning_mat_key_uniq",
    )
    # Batch 2B7 — durable Plan hierarchy: partial unique indexes on
    # planning_materialization_key so retries cannot duplicate plan,
    # phase, milestone, or required-check-in records.
    await database.plans.create_index(
        [("user_id", 1), ("planning_materialization_key", 1)],
        unique=True,
        partialFilterExpression={"planning_materialization_key": {"$type": "string"}},
        name="plans_planning_mat_key_uniq",
    )
    await database.plan_phases.create_index(
        [("user_id", 1), ("planning_materialization_key", 1)],
        unique=True,
        partialFilterExpression={"planning_materialization_key": {"$type": "string"}},
        name="plan_phases_planning_mat_key_uniq",
    )
    await database.plan_milestones.create_index(
        [("user_id", 1), ("planning_materialization_key", 1)],
        unique=True,
        partialFilterExpression={"planning_materialization_key": {"$type": "string"}},
        name="plan_milestones_planning_mat_key_uniq",
    )
    await database.required_checkins.create_index(
        [("user_id", 1), ("planning_materialization_key", 1)],
        unique=True,
        partialFilterExpression={"planning_materialization_key": {"$type": "string"}},
        name="required_checkins_planning_mat_key_uniq",
    )
    # Batch 2B7 — non-unique lookup indexes for hierarchy reads.
    await database.plans.create_index(
        [("user_id", 1), ("target_type", 1), ("target_id", 1)],
        name="plans_user_target_lookup",
    )
    await database.plan_phases.create_index(
        [("user_id", 1), ("plan_id", 1), ("position", 1)],
        name="plan_phases_user_plan_position",
    )
    await database.plan_milestones.create_index(
        [("user_id", 1), ("plan_id", 1), ("phase_id", 1), ("position", 1)],
        name="plan_milestones_user_plan_phase_position",
    )
    await database.tasks.create_index(
        [("user_id", 1), ("plan_id", 1), ("phase_id", 1), ("milestone_id", 1), ("plan_position", 1)],
        name="tasks_user_plan_phase_milestone_position",
    )
    await database.required_checkins.create_index(
        [("user_id", 1), ("plan_id", 1), ("task_id", 1), ("position", 1)],
        name="required_checkins_user_plan_task_position",
    )
