"""WhatsApp task capture: forward or type a message to Hymn's number → a task.

Flow: Meta's webhook → signature check → store (deduped by message id) → 200.
After a short pause (``BATCH_SECONDS``, so several forwards become one task) the
messages are routed: STOP / link code / START / help / button and list replies /
"done" / new content. New content goes to the parser (``whatsapp_ai``), which
only extracts a task; the person confirms on a card (Add / Edit / Cancel, or
Today / Tomorrow / Pick date when there's no date). Reminders are approved
templates with Done / Snooze buttons.

Rules that never bend (see ``docs/WHATSAPP_API.md``):
- Not a general assistant: anything that isn't a task gets one fixed reply.
- AI disclosure on the first reply of every new 24-hour conversation window.
- Consent is logged before anything is sent; STOP (or the app's switch) stops
  every message; checked before each send.
- Free-form messages only inside the 24-hour window; reminders are templates.
- Phone numbers are removed before text reaches the AI; raw text is deleted
  after 7 days; Health isn't handled over WhatsApp.

Nothing is sent or accepted until the WA_* variables are set on Railway.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from pymongo.errors import DuplicateKeyError

import whatsapp_ai
from claude_client import AssistantUnavailable
from deps import get_current_user, get_db

logger = logging.getLogger(__name__)

whatsapp_router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])

BATCH_SECONDS = 10                       # wait this long after the last message, then read them together
WINDOW = timedelta(hours=24)             # Meta's customer service window
RAW_TEXT_DAYS = 7                        # raw inbound text is deleted after this
LINK_CODE_MINUTES = 30
DEFAULT_TZ = "Asia/Kolkata"
DEFAULT_REMINDER_TIME = "09:00"          # tasks with a date but no time
REMINDER_CATCH_UP = timedelta(hours=12)  # a reminder missed while the server was down still goes
MIN_CONFIDENCE = 0.6
MIN_DUE_CONFIDENCE = 0.5
AUTO_PROCESS = True                      # tests switch this off and call process_due themselves

CONSENT_VERSION = "2026-11-19"
CONSENT_TEXT = ("Send me WhatsApp messages from Hymn about tasks I add there, and their reminders. "
                "Hymn uses AI to read what I forward. I can reply STOP anytime.")
DISCLOSURE = "Hymn uses AI to read what you forward and create tasks."
OFF_TOPIC = "I only add, update and complete Hymn tasks. Open the app for more."
NOT_UNDERSTOOD = 'I couldn\'t tell what the task is. Could you send it in one line, like "Pay rent by Friday"?'
UNAVAILABLE = "I couldn't read that just now. Please try again in a minute."
TEXT_ONLY = "I can only read text for now. Type or forward the task as text."
LIMIT_REACHED = "You've reached today's limit for WhatsApp tasks. It resets tomorrow."

TEMPLATE_REMINDER = "task_due_reminder"   # Reminder: your Hymn task "{{1}}" is due {{2}}. [Done] [Snooze 1 day]
TEMPLATE_OVERDUE = "task_overdue"         # submitted for later; one reminder per task at launch
TEMPLATE_LINKED = "link_confirmed"

STOP_WORDS = {"stop", "unsubscribe", "stop all", "opt out", "optout"}
START_WORDS = {"start", "resume", "subscribe"}
HELP_WORDS = {"help", "human", "support", "agent"}
DONE_WORDS = {"done", "completed", "complete", "finished", "did it", "ho gaya", "hogaya"}
CANCEL_WORDS = {"cancel"}
_LINK = re.compile(r"\bLINK-([A-Z0-9]{6})\b")


# ---------------------------------------------------------------------------
# Config and small helpers
# ---------------------------------------------------------------------------

def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def configured() -> bool:
    return all(_env(k) for k in ("WA_PHONE_NUMBER_ID", "WA_ACCESS_TOKEN", "WA_APP_SECRET", "WA_VERIFY_TOKEN"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _tz(user: Optional[dict]) -> ZoneInfo:
    try:
        return ZoneInfo((user or {}).get("timezone") or DEFAULT_TZ)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TZ)


def _app_link() -> str:
    return _env("HYMN_APP_LINK") or "the Hymn app"


def _help_text() -> str:
    email, url = _env("HYMN_SUPPORT_EMAIL"), _env("HYMN_SUPPORT_URL")
    parts = [p for p in (f"email {email}" if email else "", f"use the form at {url}" if url else "") if p]
    if not parts:
        logger.warning("whatsapp: HYMN_SUPPORT_EMAIL / HYMN_SUPPORT_URL not set")
        return "For help, open Hymn → Me → Help and a person will get back to you."
    return "For help from a person, " + " or ".join(parts) + "."


def due_text(due_date: str, due_time: str, tz: ZoneInfo, now: datetime) -> str:
    """'today', 'tomorrow at 5:30 pm', 'Mon 24 Nov'."""
    if not due_date:
        return ""
    d = date.fromisoformat(due_date)
    today = now.astimezone(tz).date()
    word = "today" if d == today else "tomorrow" if d == today + timedelta(days=1) else d.strftime("%a %d %b")
    if due_time:
        h, m = map(int, due_time.split(":"))
        word += " at " + time(h, m).strftime("%I:%M %p").lstrip("0").lower().replace(":00 ", " ")
    return word


# ---------------------------------------------------------------------------
# Sending (every outbound message goes through ``send``)
# ---------------------------------------------------------------------------

def post_graph(payload: dict) -> dict:
    """POST one message to the WhatsApp Cloud API. Tests replace this."""
    url = (f"https://graph.facebook.com/{_env('WA_GRAPH_VERSION') or 'v23.0'}/"
           f"{_env('WA_PHONE_NUMBER_ID')}/messages")
    r = requests.post(url, json=payload, timeout=15,
                      headers={"Authorization": f"Bearer {_env('WA_ACCESS_TOKEN')}"})
    r.raise_for_status()
    return r.json()


async def opted_out(db, wa_id: str) -> bool:
    return bool(await db.wa_opt_out.find_one({"wa_id": wa_id}, {"_id": 1}))


async def _disclosure_due(db, wa_id: str) -> bool:
    s = await db.wa_session.find_one({"wa_id": wa_id}, {"_id": 0}) or {}
    last = _parse(s.get("last_disclosure_at"))
    started = _parse(s.get("window_started_at"))
    return last is None or (started is not None and last < started)


async def send(db, wa_id: str, message: dict, kind: str, *, user_id: Optional[str] = None,
               task_id: Optional[str] = None, draft_id: Optional[str] = None,
               now: Optional[datetime] = None) -> Optional[str]:
    """Send one message, or refuse: opted out, or free-form outside the 24h window.

    Adds the AI disclosure to the first text in each new window. Returns the
    message id, or None when nothing was sent."""
    now = now or _now()
    if await opted_out(db, wa_id):
        logger.info("whatsapp: not sending %s to an opted-out number", kind)
        return None
    message = json.loads(json.dumps(message))
    free_form = message["type"] != "template"
    disclose = False
    if free_form:
        s = await db.wa_session.find_one({"wa_id": wa_id}, {"_id": 0}) or {}
        last_in = _parse(s.get("last_inbound_at"))
        if last_in is None or now - last_in > WINDOW:
            logger.warning("whatsapp: blocked a free-form %s outside the 24h window", kind)
            return None
        if message["type"] in ("text", "interactive") and await _disclosure_due(db, wa_id):
            disclose = True
            if message["type"] == "text":
                message["text"]["body"] += "\n\n" + DISCLOSURE
            else:
                message["interactive"]["body"]["text"] += "\n\n" + DISCLOSURE
    payload = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": wa_id, **message}
    try:
        response = await asyncio.to_thread(post_graph, payload)
    except (requests.RequestException, ValueError) as exc:
        logger.warning("whatsapp: send %s failed: %s", kind, exc)
        return None
    wamid = ((response or {}).get("messages") or [{}])[0].get("id") or f"local-{uuid.uuid4()}"
    await db.wa_outbound.insert_one({
        "wamid": wamid, "wa_id": wa_id, "user_id": user_id, "task_id": task_id, "draft_id": draft_id,
        "kind": kind, "template_name": (message.get("template") or {}).get("name"), "sent_at": _iso(now)})
    if disclose:
        await db.wa_session.update_one({"wa_id": wa_id}, {"$set": {"last_disclosure_at": _iso(now)}})
    return wamid


async def send_text(db, wa_id, body, kind="system", **kw):
    return await send(db, wa_id, {"type": "text", "text": {"body": body}}, kind, **kw)


async def send_buttons(db, wa_id, body, buttons, kind="card", **kw):
    return await send(db, wa_id, {"type": "interactive", "interactive": {
        "type": "button", "body": {"text": body},
        "action": {"buttons": [{"type": "reply", "reply": {"id": i, "title": t[:20]}} for i, t in buttons]}}},
        kind, **kw)


async def send_list(db, wa_id, body, rows, kind="list", **kw):
    return await send(db, wa_id, {"type": "interactive", "interactive": {
        "type": "list", "body": {"text": body},
        "action": {"button": "Choose", "sections": [{"title": "Tasks" if kind == "list" else "Dates",
                                                     "rows": [_row(i, t) for i, t in rows[:10]]}]}}},
        kind, **kw)


def _row(row_id: str, title: str) -> dict:
    """List rows show 24 characters; a longer title also goes in full underneath."""
    row = {"id": row_id, "title": title if len(title) <= 24 else title[:23].rstrip() + "…"}
    if len(title) > 24:
        row["description"] = title[:72]
    return row


async def confirm(db, wa_id: str, their_wamid: str, text: str, **kw):
    """✅ on their message; when the AI disclosure is due, a short text instead (a reaction can't carry it)."""
    if await _disclosure_due(db, wa_id):
        return await send_text(db, wa_id, "✅ " + text, **kw)
    return await send(db, wa_id, {"type": "reaction", "reaction": {"message_id": their_wamid, "emoji": "✅"}},
                      "reaction", **kw)


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------

def signature_ok(raw: bytes, header: str, secret: str) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest((header or "").encode(), expected.encode())


def _normalise(m: dict) -> dict:
    ctx = m.get("context") or {}
    kind = m.get("type")
    text, reply_id = "", None
    if kind == "text":
        text = (m.get("text") or {}).get("body") or ""
    elif kind == "interactive":
        inter = m.get("interactive") or {}
        r = inter.get("button_reply") or inter.get("list_reply") or {}
        reply_id, text = r.get("id"), r.get("title") or ""
    elif kind == "button":                       # a template's quick-reply button
        b = m.get("button") or {}
        reply_id, text = b.get("payload"), b.get("text") or ""
    return {"wamid": m.get("id"), "wa_id": str(m.get("from") or ""), "type": kind, "raw_text": text,
            "reply_id": reply_id, "context_id": ctx.get("id"),
            "forwarded": bool(ctx.get("forwarded")), "frequently_forwarded": bool(ctx.get("frequently_forwarded"))}


async def store_inbound(db, payload: dict, now: datetime) -> List[str]:
    """Save each new message (deduped by its id); returns the senders with something new."""
    senders: List[str] = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            for m in (change.get("value") or {}).get("messages") or []:
                doc = _normalise(m)
                if not doc["wamid"] or not doc["wa_id"]:
                    continue
                link = await db.wa_link.find_one({"wa_id": doc["wa_id"]}, {"_id": 0, "user_id": 1})
                doc.update({"user_id": (link or {}).get("user_id"), "received_at": _iso(now), "processed": False})
                try:
                    await db.wa_inbound.insert_one(doc)
                except DuplicateKeyError:
                    continue
                s = await db.wa_session.find_one({"wa_id": doc["wa_id"]}, {"_id": 0}) or {}
                last_in = _parse(s.get("last_inbound_at"))
                upd = {"last_inbound_at": _iso(now), "user_id": doc["user_id"]}
                if last_in is None or now - last_in > WINDOW:
                    upd["window_started_at"] = _iso(now)
                await db.wa_session.update_one({"wa_id": doc["wa_id"]}, {"$set": upd}, upsert=True)
                if doc["wa_id"] not in senders:
                    senders.append(doc["wa_id"])
    return senders


_pending: set = set()


async def _process_after(wa_id: str) -> None:
    await asyncio.sleep(BATCH_SECONDS + 0.5)
    try:
        await process_due(get_db(), wa_id)
    except Exception:
        logger.exception("whatsapp: processing failed for a sender")


@whatsapp_router.get("/webhook")
async def verify_webhook(mode: str = Query("", alias="hub.mode"), token: str = Query("", alias="hub.verify_token"),
                         challenge: str = Query("", alias="hub.challenge")):
    expected = _env("WA_VERIFY_TOKEN")
    if mode == "subscribe" and expected and hmac.compare_digest(token.encode(), expected.encode()):
        return PlainTextResponse(challenge)
    raise HTTPException(status_code=403, detail="Verification failed")


@whatsapp_router.post("/webhook")
async def receive_webhook(request: Request):
    secret = _env("WA_APP_SECRET")
    if not secret:
        raise HTTPException(status_code=404, detail="WhatsApp isn't set up")
    raw = await request.body()
    if not signature_ok(raw, request.headers.get("X-Hub-Signature-256", ""), secret):
        raise HTTPException(status_code=401, detail="Bad signature")
    try:
        payload = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Not JSON")
    senders = await store_inbound(get_db(), payload, _now())
    if AUTO_PROCESS:
        for wa_id in senders:
            task = asyncio.create_task(_process_after(wa_id))
            _pending.add(task)
            task.add_done_callback(_pending.discard)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

async def process_due(db, wa_id: str, now: Optional[datetime] = None, force: bool = False) -> None:
    """Handle this sender's unprocessed messages once the newest is BATCH_SECONDS old."""
    now = now or _now()
    pending = await db.wa_inbound.find({"wa_id": wa_id, "processed": False}, {"_id": 0}) \
        .sort("received_at", 1).to_list(length=50)
    if not pending:
        return
    newest = _parse(pending[-1]["received_at"])
    if not force and newest and now - newest < timedelta(seconds=BATCH_SECONDS):
        return
    claimed = []
    for m in pending:      # claim each one so two workers never handle the same message
        r = await db.wa_inbound.update_one({"wamid": m["wamid"], "processed": False},
                                           {"$set": {"processed": True, "processed_at": _iso(now)}})
        if r.modified_count:
            claimed.append(m)
    if claimed:
        await handle(db, wa_id, claimed, now)


async def handle(db, wa_id: str, msgs: List[dict], now: datetime) -> None:
    link = await db.wa_link.find_one({"wa_id": wa_id}, {"_id": 0})
    uid = (link or {}).get("user_id")
    content: List[dict] = []
    told_unlinked = False
    for m in msgs:
        text = (m.get("raw_text") or "").strip()
        low = " ".join(text.lower().strip(" .!✅").split())
        if low in STOP_WORDS:
            await set_opt_out(db, wa_id, uid, "whatsapp", now)
            return                                   # nothing more, of any kind
        code = _LINK.search(text.upper())
        if code:
            link = await link_number(db, wa_id, code.group(1), now) or link
            uid = (link or {}).get("user_id")
            continue
        if low in START_WORDS and await opted_out(db, wa_id):
            await db.wa_opt_out.delete_one({"wa_id": wa_id})
            await send_text(db, wa_id, "You're back on. Reply STOP anytime.", user_id=uid, now=now)
            continue
        if await opted_out(db, wa_id):
            continue
        if not link:
            if not told_unlinked:
                told_unlinked = True
                await send_text(db, wa_id, f"This number isn't connected to Hymn yet. Open {_app_link()} → "
                                           "Me → WhatsApp to connect it.", now=now)
            continue
        if low in HELP_WORDS:
            await send_text(db, wa_id, _help_text(), user_id=uid, now=now)
            continue
        if m.get("reply_id"):
            await on_reply(db, link, m, now)
            continue
        first, _, rest = low.partition(" ")
        if low in DONE_WORDS or first == "done":       # "complete the report" is a new task, not a done
            await on_done(db, link, m, "" if low in DONE_WORDS else rest, now)
            continue
        if low in CANCEL_WORDS:
            d = await db.wa_drafts.find_one_and_update(
                {"user_id": uid, "status": {"$in": ["pending", "editing"]}}, {"$set": {"status": "cancelled"}},
                sort=[("created_at", -1)])
            await send_text(db, wa_id, "Okay, not added." if d else "There's nothing to cancel.", user_id=uid, now=now)
            continue
        content.append(m)
    if content and link and not await opted_out(db, wa_id):
        await on_content(db, link, content, now)


# ---------------------------------------------------------------------------
# Linking, consent, opt-out
# ---------------------------------------------------------------------------

async def link_number(db, wa_id: str, code: str, now: datetime) -> Optional[dict]:
    row = await db.wa_link_codes.find_one({"code": code, "used": False}, {"_id": 0})
    if not row or (_parse(row["expires_at"]) or now) < now:
        await send_text(db, wa_id, f"That link code has expired. Open {_app_link()} → Me → WhatsApp to get a new one.",
                        now=now)
        return None
    uid = row["user_id"]
    await db.wa_link_codes.update_one({"code": code}, {"$set": {"used": True, "used_at": _iso(now)}})
    await db.wa_link.delete_many({"$or": [{"wa_id": wa_id}, {"user_id": uid}]})
    link = {"user_id": uid, "wa_id": wa_id, "linked_at": _iso(now)}
    await db.wa_link.insert_one(dict(link))
    await db.consent_log.insert_one({"user_id": uid, "wa_id": wa_id, "consent_text_version": CONSENT_VERSION,
                                     "method": "app_checkbox_then_whatsapp_code", "created_at": _iso(now)})
    await db.wa_opt_out.delete_many({"wa_id": wa_id})     # linking again is opting in again
    await db.wa_session.update_one({"wa_id": wa_id}, {"$set": {"user_id": uid}})
    await db.wa_inbound.update_many({"wa_id": wa_id, "user_id": None}, {"$set": {"user_id": uid}})
    await send_text(db, wa_id, "Connected. Forward or type anything you need to do and I'll make it a task. "
                               "Reply STOP anytime.", user_id=uid, now=now)
    return link


async def set_opt_out(db, wa_id: str, user_id: Optional[str], channel: str, now: datetime) -> None:
    await db.wa_opt_out.update_one({"wa_id": wa_id}, {"$set": {"user_id": user_id, "opted_out_at": _iso(now),
                                                              "channel": channel}}, upsert=True)
    logger.info("whatsapp: a number opted out (%s)", channel)


# ---------------------------------------------------------------------------
# New content → parse → confirm card
# ---------------------------------------------------------------------------

async def _user(db, uid: str) -> Optional[dict]:
    return await db.users.find_one({"id": uid}, {"_id": 0})


async def on_content(db, link: dict, msgs: List[dict], now: datetime) -> None:
    wa_id, uid = link["wa_id"], link["user_id"]
    text = "\n\n".join(m["raw_text"] for m in msgs if (m.get("raw_text") or "").strip())
    if not text:
        await send_text(db, wa_id, TEXT_ONLY, user_id=uid, now=now)
        return
    wamids = [m["wamid"] for m in msgs]
    if any(m.get("frequently_forwarded") for m in msgs):
        draft = await _new_draft(db, link, {"status": "chain", "text": text, "source_wamids": wamids}, now)
        await send_buttons(db, wa_id, "This looks like a message forwarded many times. Make it a task?",
                           [(f"chain:{draft['id']}:add", "Add as task"), (f"chain:{draft['id']}:ignore", "Ignore")],
                           user_id=uid, draft_id=draft["id"], now=now)
        return
    await parse_and_card(db, link, text, wamids, now)


async def _new_draft(db, link: dict, fields: dict, now: datetime) -> dict:
    draft = {"id": str(uuid.uuid4()), "user_id": link["user_id"], "wa_id": link["wa_id"],
             "created_at": _iso(now), **fields}
    await db.wa_drafts.insert_one(dict(draft))
    return draft


async def parse_and_card(db, link: dict, text: str, wamids: List[str], now: datetime) -> None:
    import ai_budget

    wa_id, uid = link["wa_id"], link["user_id"]
    user = await _user(db, uid)
    if not user:
        return
    try:
        await ai_budget.spend(db, user, "light")
    except HTTPException:
        await send_text(db, wa_id, LIMIT_REACHED, user_id=uid, now=now)
        return
    tz = _tz(user)
    import metering
    metering.set_actor(uid, "whatsapp")
    try:
        p, usage = await whatsapp_ai.parse_task(text, str(tz.key), now.astimezone(tz))
    except AssistantUnavailable:
        await send_text(db, wa_id, UNAVAILABLE, user_id=uid, now=now)
        return
    await db.wa_ai_usage.insert_one({"user_id": uid, "at": _iso(now), "model": whatsapp_ai.MODEL, **usage})
    if not p.is_task:
        await send_text(db, wa_id, OFF_TOPIC, user_id=uid, now=now)
        return
    if p.confidence < MIN_CONFIDENCE or not p.title:
        await send_text(db, wa_id, NOT_UNDERSTOOD, user_id=uid, now=now)
        return
    if p.area == "health":
        await db.wa_inbound.update_many({"wamid": {"$in": wamids}}, {"$unset": {"raw_text": ""}})
        await send_text(db, wa_id, f"Health things are kept in the app, not over WhatsApp. Add this in "
                                   f"{_app_link()} → Life → Health.", user_id=uid, now=now)
        return
    # An earlier card being edited is replaced by this one.
    await db.wa_drafts.update_many({"user_id": uid, "status": "editing"}, {"$set": {"status": "replaced"}})
    due_ok = p.due_date and p.due_confidence >= MIN_DUE_CONFIDENCE
    draft = await _new_draft(db, link, {
        "status": "pending", "title": p.title, "due_date": p.due_date if due_ok else "",
        "due_time": p.due_time if due_ok else "", "area": p.area, "people": p.people,
        "source_wamids": wamids}, now)
    await send_card(db, link, draft, tz, now)


async def send_card(db, link: dict, draft: dict, tz: ZoneInfo, now: datetime) -> None:
    did = draft["id"]
    when = due_text(draft["due_date"], draft["due_time"], tz, now)
    if when:
        body = f"Add this task?\n\n*{draft['title']}*\nDue: {when}"
        buttons = [(f"add:{did}", "Add"), (f"edit:{did}", "Edit"), (f"cancel:{did}", "Cancel")]
    else:
        body = f"Add this task?\n\n*{draft['title']}*\nWhen is it due?"
        buttons = [(f"due:{did}:today", "Today"), (f"due:{did}:tomorrow", "Tomorrow"), (f"due:{did}:pick", "Pick date")]
    await send_buttons(db, link["wa_id"], body, buttons, user_id=link["user_id"], draft_id=did, now=now)


# ---------------------------------------------------------------------------
# Button and list replies
# ---------------------------------------------------------------------------

async def on_reply(db, link: dict, m: dict, now: datetime) -> None:
    wa_id, uid = link["wa_id"], link["user_id"]
    parts = (m.get("reply_id") or "").split(":")
    action, ref = parts[0], (parts[1] if len(parts) > 1 else "")
    arg = parts[2] if len(parts) > 2 else ""
    user = await _user(db, uid)
    if not user:
        return
    tz = _tz(user)
    if action in ("done", "snooze", "pick"):
        task = await db.tasks.find_one({"id": ref, "user_id": uid}, {"_id": 0})
        if not task:
            await send_text(db, wa_id, "I can't find that task any more.", user_id=uid, now=now)
        elif action == "snooze":
            await snooze(db, user, task, m, now)
        else:
            await complete(db, user, task, m, now)
        return
    draft = await db.wa_drafts.find_one({"id": ref, "user_id": uid}, {"_id": 0})
    if not draft:
        await send_text(db, wa_id, "That card has expired. Send the task again.", user_id=uid, now=now)
        return
    if action == "chain":
        if draft["status"] != "chain":
            return
        if arg == "add":
            await db.wa_drafts.update_one({"id": ref}, {"$set": {"status": "replaced"}, "$unset": {"text": ""}})
            await parse_and_card(db, link, draft.get("text") or "", draft.get("source_wamids") or [], now)
        else:
            await db.wa_drafts.update_one({"id": ref}, {"$set": {"status": "cancelled"}, "$unset": {"text": ""}})
            await send_text(db, wa_id, "Okay, ignored.", user_id=uid, now=now)
        return
    if draft["status"] not in ("pending", "editing"):
        await send_text(db, wa_id, "That one's already handled.", user_id=uid, now=now)
        return
    today = now.astimezone(tz).date()
    if action == "add":
        await create_from_draft(db, user, draft, m, now)
    elif action == "edit":
        await db.wa_drafts.update_one({"id": ref}, {"$set": {"status": "editing"}})
        await send_text(db, wa_id, "Send the task again the way you want it.", user_id=uid, now=now)
    elif action == "cancel":
        await db.wa_drafts.update_one({"id": ref}, {"$set": {"status": "cancelled"}})
        await send_text(db, wa_id, "Okay, not added.", user_id=uid, now=now)
    elif action == "due" and arg in ("today", "tomorrow"):
        draft["due_date"] = (today + timedelta(days=0 if arg == "today" else 1)).isoformat()
        await create_from_draft(db, user, draft, m, now)
    elif action == "due" and arg == "pick":
        rows = []
        for i in range(10):
            d = today + timedelta(days=i)
            rows.append((f"date:{ref}:{d.isoformat()}",
                         "Today" if i == 0 else "Tomorrow" if i == 1 else d.strftime("%a %d %b")))
        await send_list(db, wa_id, f"When is “{draft['title']}” due?", rows, kind="dates", user_id=uid,
                        draft_id=ref, now=now)
    elif action == "date":
        try:
            draft["due_date"] = date.fromisoformat(arg).isoformat()
        except ValueError:
            return
        await create_from_draft(db, user, draft, m, now)


async def create_from_draft(db, user: dict, draft: dict, m: dict, now: datetime) -> Optional[dict]:
    from server import TaskCreate, create_task

    claimed = await db.wa_drafts.find_one_and_update(
        {"id": draft["id"], "status": {"$in": ["pending", "editing"]}}, {"$set": {"status": "added"}})
    if not claimed:
        return None
    task = await create_task(TaskCreate(title=draft["title"], due_date=draft.get("due_date") or "",
                                        notes="Added from WhatsApp"), current_user=user)
    tid = task.id if hasattr(task, "id") else task["id"]
    await db.tasks.update_one({"id": tid}, {"$set": {
        "source": "whatsapp", "source_ref": (draft.get("source_wamids") or [None])[0], "area": draft.get("area") or None,
        "due_time": draft.get("due_time") or None, "wa_reminded_at": None}})
    await db.wa_drafts.update_one({"id": draft["id"]}, {"$set": {"task_id": tid}})
    # The card now stands for the task, so "done" quoted on it closes this task.
    await db.wa_outbound.update_many({"draft_id": draft["id"]}, {"$set": {"task_id": tid}})
    target = (draft.get("source_wamids") or [m["wamid"]])[0]
    await confirm(db, draft["wa_id"], target, f"Added: {draft['title']}", user_id=user["id"], task_id=tid, now=now)
    return await db.tasks.find_one({"id": tid}, {"_id": 0})


# ---------------------------------------------------------------------------
# Done, snooze
# ---------------------------------------------------------------------------

async def complete(db, user: dict, task: dict, m: dict, now: datetime) -> None:
    from server import TaskUpdate, update_task

    if task.get("status") != "done":
        await update_task(task["id"], TaskUpdate(status="done"), current_user=user)
    await confirm(db, m["wa_id"], m["wamid"], f"Done: {task['title']}", user_id=user["id"], task_id=task["id"], now=now)


async def snooze(db, user: dict, task: dict, m: dict, now: datetime) -> None:
    from server import TaskUpdate, update_task

    new = (now.astimezone(_tz(user)).date() + timedelta(days=1)).isoformat()
    await update_task(task["id"], TaskUpdate(due_date=new), current_user=user)
    await db.tasks.update_one({"id": task["id"]}, {"$set": {"wa_reminded_at": None}})
    await send_text(db, m["wa_id"], f"Okay, I'll remind you tomorrow about “{task['title']}”.", user_id=user["id"],
                    task_id=task["id"], now=now)


def _words(s: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(w) > 2}


async def on_done(db, link: dict, m: dict, words: str, now: datetime) -> None:
    wa_id, uid = link["wa_id"], link["user_id"]
    user = await _user(db, uid)
    if not user:
        return
    if m.get("context_id"):                                   # quoted a card or reminder: that exact task
        out = await db.wa_outbound.find_one({"wamid": m["context_id"], "wa_id": wa_id}, {"_id": 0})
        if out and out.get("task_id"):
            task = await db.tasks.find_one({"id": out["task_id"], "user_id": uid}, {"_id": 0})
            if task:
                await complete(db, user, task, m, now)
                return
        if out and out.get("draft_id"):
            await send_text(db, wa_id, "That one isn't added yet — tap Add on the card first.", user_id=uid, now=now)
            return
    open_tasks = await db.tasks.find({"user_id": uid, "status": "todo"}, {"_id": 0}) \
        .sort("created_at", -1).to_list(length=200)
    if words:
        want = _words(words)
        scored = sorted(((len(want & _words(t["title"])), t) for t in open_tasks), key=lambda x: -x[0])
        if scored and scored[0][0] > 0 and (len(scored) == 1 or scored[1][0] < scored[0][0]):
            await complete(db, user, scored[0][1], m, now)
            return
        choices = [t for s, t in scored if s > 0] or open_tasks
    else:
        since = _iso(now - timedelta(hours=24))
        recent = [t for t in open_tasks if t.get("source") == "whatsapp"
                  and (t.get("created_at", "") >= since or (t.get("wa_reminded_at") or "") >= since)]
        if len(recent) == 1:
            await complete(db, user, recent[0], m, now)
            return
        choices = [t for t in open_tasks if t.get("source") == "whatsapp"] or open_tasks
    if not choices:
        await send_text(db, wa_id, "You have no open tasks.", user_id=uid, now=now)
        return
    await send_list(db, wa_id, "Which one is done?", [(f"pick:{t['id']}", t["title"]) for t in choices[:10]],
                    user_id=uid, now=now)


# ---------------------------------------------------------------------------
# Every minute: late batches, reminders, clean-up
# ---------------------------------------------------------------------------

async def _template_numbers_today(db, now: datetime) -> set:
    rows = await db.wa_outbound.find({"template_name": {"$ne": None}, "sent_at": {"$gte": _iso(now - WINDOW)}},
                                     {"_id": 0, "wa_id": 1}).to_list(length=None)
    return {r["wa_id"] for r in rows}


def messaging_limit() -> int:
    try:
        return max(1, int(_env("WA_MESSAGING_LIMIT") or 250))
    except ValueError:
        return 250


async def send_reminders(db, now: datetime) -> int:
    sent = 0
    limit = messaging_limit()
    reached = await _template_numbers_today(db, now)
    async for link in db.wa_link.find({}, {"_id": 0}):
        wa_id = link["wa_id"]
        if await opted_out(db, wa_id):
            continue
        user = await _user(db, link["user_id"])
        if not user:
            continue
        tz = _tz(user)
        local = now.astimezone(tz)
        days = [(local.date() - timedelta(days=1)).isoformat(), local.date().isoformat()]
        async for t in db.tasks.find({"user_id": user["id"], "status": "todo", "source": "whatsapp",
                                      "wa_reminded_at": None, "due_date": {"$in": days}}, {"_id": 0}):
            h, mi = map(int, (t.get("due_time") or DEFAULT_REMINDER_TIME).split(":"))
            at = datetime.combine(date.fromisoformat(t["due_date"]), time(h, mi), tzinfo=tz)
            if not (at <= local <= at + REMINDER_CATCH_UP):
                continue
            if wa_id not in reached and len(reached) >= limit:
                logger.warning("whatsapp: messaging limit (%d numbers a day) reached; reminder waits", limit)
                continue
            if wa_id not in reached and len(reached) + 1 >= 0.8 * limit:
                logger.warning("whatsapp: %d of %d daily numbers used (80%% alert)", len(reached) + 1, limit)
            when = due_text(t["due_date"], t.get("due_time") or "", tz, now)
            wamid = await send(db, wa_id, {"type": "template", "template": {
                "name": TEMPLATE_REMINDER, "language": {"code": _env("WA_TEMPLATE_LANG") or "en"},
                "components": [
                    {"type": "body", "parameters": [{"type": "text", "text": t["title"][:60]},
                                                    {"type": "text", "text": when}]},
                    {"type": "button", "sub_type": "quick_reply", "index": "0",
                     "parameters": [{"type": "payload", "payload": f"done:{t['id']}"}]},
                    {"type": "button", "sub_type": "quick_reply", "index": "1",
                     "parameters": [{"type": "payload", "payload": f"snooze:{t['id']}"}]}]}},
                "reminder", user_id=user["id"], task_id=t["id"], now=now)
            if wamid:
                await db.tasks.update_one({"id": t["id"]}, {"$set": {"wa_reminded_at": _iso(now)}})
                reached.add(wa_id)
                sent += 1
    return sent


async def purge(db, now: datetime) -> None:
    """Raw message text goes after 7 days (the task keeps only its fields); old cards go too."""
    cutoff = _iso(now - timedelta(days=RAW_TEXT_DAYS))
    await db.wa_inbound.update_many({"received_at": {"$lt": cutoff}, "raw_text": {"$exists": True}},
                                    {"$unset": {"raw_text": ""}})
    await db.wa_drafts.delete_many({"created_at": {"$lt": cutoff}})
    await db.wa_link_codes.delete_many({"expires_at": {"$lt": _iso(now - timedelta(days=1))}})


async def whatsapp_tick(db, now: Optional[datetime] = None) -> None:
    now = now or _now()
    await purge(db, now)
    if not configured():
        return
    late = await db.wa_inbound.distinct("wa_id", {"processed": False,
                                                  "received_at": {"$lte": _iso(now - timedelta(seconds=BATCH_SECONDS))}})
    for wa_id in late:      # e.g. the server restarted during the pause
        try:
            await process_due(db, wa_id, now, force=True)
        except Exception:
            logger.exception("whatsapp: late processing failed")
    await send_reminders(db, now)


# ---------------------------------------------------------------------------
# The app's side: connect, pause, disconnect
# ---------------------------------------------------------------------------

class LinkRequest(BaseModel):
    consent: bool


class PauseRequest(BaseModel):
    paused: bool


def _masked(wa_id: str) -> str:
    return "•••• " + wa_id[-4:] if wa_id else ""


async def _status(db, user: dict) -> dict:
    link = await db.wa_link.find_one({"user_id": user["id"]}, {"_id": 0})
    paused = bool(link and await opted_out(db, link["wa_id"]))
    return {"available": configured(), "linked": bool(link), "number": _masked((link or {}).get("wa_id", "")),
            "linked_at": (link or {}).get("linked_at"), "paused": paused,
            "consent_text": CONSENT_TEXT, "consent_version": CONSENT_VERSION}


@whatsapp_router.get("")
async def status(current_user: dict = Depends(get_current_user)):
    return await _status(get_db(), current_user)


@whatsapp_router.post("/link")
async def start_link(body: LinkRequest, current_user: dict = Depends(get_current_user)):
    db = get_db()
    if not configured() or not _env("WA_DISPLAY_NUMBER"):
        raise HTTPException(status_code=503, detail="WhatsApp isn't available yet.")
    if not body.consent:
        raise HTTPException(status_code=400, detail="Please tick the box to agree first.")
    now = _now()
    await db.consent_log.insert_one({"user_id": current_user["id"], "wa_id": None,
                                     "consent_text_version": CONSENT_VERSION, "consent_text": CONSENT_TEXT,
                                     "method": "app_checkbox", "created_at": _iso(now)})
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    code = "".join(secrets.choice(alphabet) for _ in range(6))
    await db.wa_link_codes.insert_one({"code": code, "user_id": current_user["id"], "used": False,
                                       "created_at": _iso(now),
                                       "expires_at": _iso(now + timedelta(minutes=LINK_CODE_MINUTES))})
    number = re.sub(r"\D", "", _env("WA_DISPLAY_NUMBER"))
    return {"code": f"LINK-{code}", "url": f"https://wa.me/{number}?text=LINK-{code}",
            "expires_in_minutes": LINK_CODE_MINUTES}


@whatsapp_router.post("/pause")
async def pause(body: PauseRequest, current_user: dict = Depends(get_current_user)):
    db = get_db()
    link = await db.wa_link.find_one({"user_id": current_user["id"]}, {"_id": 0})
    if not link:
        raise HTTPException(status_code=404, detail="WhatsApp isn't connected.")
    if body.paused:
        await set_opt_out(db, link["wa_id"], current_user["id"], "app", _now())
    else:
        await db.wa_opt_out.delete_many({"wa_id": link["wa_id"]})
    return await _status(db, current_user)


@whatsapp_router.delete("/link")
async def unlink(current_user: dict = Depends(get_current_user)):
    db = get_db()
    link = await db.wa_link.find_one({"user_id": current_user["id"]}, {"_id": 0})
    if link:
        await set_opt_out(db, link["wa_id"], current_user["id"], "app_disconnect", _now())
        await db.wa_link.delete_many({"user_id": current_user["id"]})
    return await _status(db, current_user)


async def ensure_whatsapp_indexes(db) -> None:
    await db.wa_inbound.create_index("wamid", unique=True)
    await db.wa_inbound.create_index([("wa_id", 1), ("processed", 1), ("received_at", 1)])
    await db.wa_inbound.create_index("received_at")
    await db.wa_outbound.create_index("wamid")
    await db.wa_outbound.create_index("sent_at")
    await db.wa_link.create_index("wa_id", unique=True)
    await db.wa_link.create_index("user_id", unique=True)
    await db.wa_link_codes.create_index("code", unique=True)
    await db.wa_session.create_index("wa_id", unique=True)
    await db.wa_opt_out.create_index("wa_id", unique=True)
    await db.wa_drafts.create_index("id", unique=True)
    await db.wa_drafts.create_index([("user_id", 1), ("status", 1), ("created_at", -1)])
    await db.tasks.create_index([("user_id", 1), ("source", 1), ("status", 1), ("due_date", 1)])
