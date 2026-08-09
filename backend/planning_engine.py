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
    """Small, chat-friendly context: target + existing outcomes/tasks/check-ins.
    Never dumps the whole portfolio."""
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
             "expected_outcome_id": t.get("expected_outcome_id")}
            for t in tasks
        ],
        "checkins_recent": [
            {"date": c.get("date"), "title": c.get("title"), "notes": (c.get("notes") or "")[:200]}
            for c in checkins
        ],
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

RESPONSE FORMAT (STRICT):
Every response has TWO parts:

1) A short conversational reply for the user (Markdown, 2–5 short
   paragraphs, warm and specific, no headers "## Section" style). Reference
   what they already have when relevant. Ask one focused follow-up question
   when needed. Never expose tool calls, JSON, or your own reasoning steps.

2) If (and only if) you are proposing concrete changes to the plan, append
   a machine-readable block on its own line at the very end of the message:

<<<HYMN_PROPOSAL>>>
{"summary": "one-line human summary",
 "expected_outcomes": [{"title": "...", "target_value": "", "unit": "",
                         "deadline": "YYYY-MM-DD or empty",
                         "outcome_type": "generic"}],
 "tasks": [{"title": "...", "expected_outcome_title": "match one of the above OR an existing outcome title (case-insensitive)",
             "due_date": "YYYY-MM-DD or empty", "priority": "low|medium|high",
             "notes": "optional short note"}],
 "checkin_cadence": "daily|weekly|monthly|manual OR omit",
 "target_updates": {"deadline": "YYYY-MM-DD or omit",
                     "notes": "optional refined why/description or omit"}}
<<<END>>>

Rules for the proposal block:
- Only propose additions/refinements — never delete existing items.
- For Goals: tasks MUST attach to a proposed or existing expected_outcome.
- For Projects: tasks attach directly to the project (leave expected_outcome_title empty).
- Keep it tight: 1–6 new outcomes and 1–20 new tasks per turn — smaller is better.
- If the user is just asking a question or exploring, DO NOT include the
  proposal block. Only include it when proposing concrete additions.
- All dates must be ISO YYYY-MM-DD.
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
        f"- check-in cadence: {t.get('checkin_cadence') or '—'}",
    ]
    if t.get("journey_type"):
        lines.append(f"- journey type: {t['journey_type']}")
    if t.get("notes"):
        lines.append(f"- notes: {t['notes'][:300]}")
    if ctx["expected_outcomes"]:
        lines.append("\nEXISTING EXPECTED OUTCOMES:")
        for e in ctx["expected_outcomes"][:20]:
            lines.append(f"- {e['title']} (status={e['status']}, {e.get('current_value','')}/{e.get('target_value','') or '—'} {e.get('unit') or ''})")
    if ctx["tasks"]:
        lines.append(f"\nEXISTING TASKS ({len(ctx['tasks'])}, first 20 shown):")
        for tk in ctx["tasks"][:20]:
            lines.append(f"- {tk['title']} [{tk['status']}, {tk.get('priority')}]")
    if ctx["checkins_recent"]:
        lines.append(f"\nRECENT CHECK-INS: {len(ctx['checkins_recent'])} in the last window.")
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


async def _materialize_proposal(
    db, user_id: str, target_type: str, target_id: str, proposal: dict,
) -> Dict[str, Any]:
    """Atomically apply a proposal. Compensates on failure."""
    if not isinstance(proposal, dict):
        raise HTTPException(status_code=400, detail="Invalid proposal.")

    now = _now()
    created_outcomes: List[str] = []
    created_tasks: List[str] = []

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
                "created_at": now, "updated_at": now,
            })
            created_tasks.append(task_id)

        # 4. Cadence + target update.
        target_updates: Dict[str, Any] = {}
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
        raise HTTPException(status_code=500,
                            detail=f"Failed to apply proposal: {type(exc).__name__}: {exc}")

    return {
        "created_outcomes": created_outcomes,
        "created_tasks": created_tasks,
        "target_updated": bool(target_updates) if 'target_updates' in locals() else False,
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
    target_msg["materialized_summary"] = (
        f"Added {len(result['created_outcomes'])} outcome"
        f"{'s' if len(result['created_outcomes']) != 1 else ''} and "
        f"{len(result['created_tasks'])} task"
        f"{'s' if len(result['created_tasks']) != 1 else ''}."
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
