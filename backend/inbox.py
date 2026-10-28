"""Brain-dump inbox: capture, daily filter, migration, weekly patterns.

Flow
----
1. Capture  — ``POST /inbox/dumps`` stores the raw text *first*, then asks
   Claude to split and label it (task / reminder / idea / plan). If that
   fails the dump becomes one ``unsorted`` item, so nothing is ever lost;
   ``POST /inbox/dumps/{id}/sort`` retries later.
2. Filter   — ``GET /inbox/review`` lists a short batch of open items;
   ``POST /inbox/review`` marks each done / discard / nugget / keep.
   Every "keep" bumps ``review_count``, the avoidance signal.
3. Migrate  — ``POST /inbox/items/{id}/migrate`` moves a nugget to where it
   lives (a task, a dated "calendar" task, or the wishlist) with an explicit
   next step.
4. Patterns — ``POST /inbox/patterns`` analyses the last 7 days and stores
   the result; ``GET /inbox/patterns`` returns the latest.

Collections: ``inbox_dumps``, ``inbox_items``, ``inbox_reviews``,
``inbox_insights``, ``wishlist_items``.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import List, Literal, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

import inbox_ai
from deps import get_current_user, get_db

inbox_router = APIRouter(prefix="/inbox", tags=["inbox"])

CATEGORIES = ("task", "reminder", "idea", "plan")
REVIEW_DECISIONS = ("done", "discard", "nugget", "keep")
DESTINATIONS = ("task", "calendar", "wishlist")
DEFAULT_REVIEW_SIZE = 8
# A dump stuck in "sorting" this long (crash mid-request) may be re-sorted.
STALE_SORTING = timedelta(minutes=5)
# Items kept open through this many reviews count as avoided.
AVOIDED_AFTER_REVIEWS = 3

REVIEW_PROMPT = (
    "Which of these are complete? Which should be discarded? "
    "Which are nuggets of gold that need action?"
)
MIGRATE_PROMPT = "Where should this live? (Task, Calendar, Wishlist)"

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _resolve_tz(name: Optional[str]) -> Optional[ZoneInfo]:
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(status_code=400, detail=f"Unknown timezone {name!r}")


def _local_to_utc_iso(value: str, tz: ZoneInfo) -> Optional[str]:
    """Model output ``YYYY-MM-DDTHH:MM`` (user-local) → UTC ISO, or None."""
    try:
        local = datetime.strptime(value.strip(), "%Y-%m-%dT%H:%M")
    except (ValueError, AttributeError):
        return None
    return _iso(local.replace(tzinfo=tz).astimezone(timezone.utc))


def _public(doc: Optional[dict]) -> Optional[dict]:
    if doc is not None:
        doc.pop("_id", None)
    return doc


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class DumpCreate(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    # Client-generated id so a retried submit is stored once.
    client_dump_id: Optional[str] = Field(default=None, min_length=8, max_length=128)
    # IANA name, e.g. "Asia/Kolkata". Remembered on the user when given.
    timezone: Optional[str] = None
    source: Literal["app", "whatsapp"] = "app"


class ItemUpdate(BaseModel):
    text: Optional[str] = Field(default=None, min_length=1, max_length=1000)
    category: Optional[Literal["task", "reminder", "idea", "plan"]] = None
    # UTC ISO 8601; empty string clears it.
    remind_at: Optional[str] = None


class ReviewDecision(BaseModel):
    item_id: str
    decision: Literal["done", "discard", "nugget", "keep"]


class ReviewSubmit(BaseModel):
    decisions: List[ReviewDecision] = Field(min_length=1, max_length=50)


class MigrateRequest(BaseModel):
    destination: Literal["task", "calendar", "wishlist"]
    # The concrete next action; becomes the task title.
    next_step: str = Field(min_length=1, max_length=200)
    due_date: Optional[str] = None       # YYYY-MM-DD; required for calendar
    time: Optional[str] = None           # HH:MM, calendar only
    project_id: Optional[str] = None
    expected_outcome_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------

async def _user_tz(db, user: dict, requested: Optional[str]) -> ZoneInfo:
    tz = _resolve_tz(requested)
    if tz is not None:
        if requested != user.get("timezone"):
            await db.users.update_one({"id": user["id"]}, {"$set": {"timezone": requested}})
        return tz
    return _resolve_tz(user.get("timezone")) or ZoneInfo("UTC")


def _new_item(user_id: str, dump_id: str, text: str, category: str,
              remind_at: Optional[str] = None) -> dict:
    now = _iso(_now())
    return {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "dump_id": dump_id,
        "text": text.strip(),
        "category": category,
        "status": "open",
        "remind_at": remind_at,
        "review_count": 0,
        "last_reviewed_at": None,
        "next_step": None,
        "migrated_to": None,
        "created_at": now,
        "updated_at": now,
        "closed_at": None,
    }


async def _sort_and_store(db, user: dict, dump: dict, tz: ZoneInfo) -> dict:
    """Sort a dump already marked ``sorting``. Returns the updated dump.

    On success the sorted items replace any earlier ``unsorted`` fallback
    item; on failure a single fallback item holds the raw text.
    """
    now_local = _now().astimezone(tz).strftime("%Y-%m-%dT%H:%M (%A)")
    try:
        sorted_dump = await inbox_ai.sort_dump(dump["raw_text"], now_local=now_local, tz_name=str(tz))
    except inbox_ai.AssistantUnavailable as exc:
        existing = await db.inbox_items.find_one({"dump_id": dump["id"], "category": "unsorted"})
        if existing is None:
            await db.inbox_items.insert_one(
                _new_item(user["id"], dump["id"], dump["raw_text"], "unsorted"),
            )
        await db.inbox_dumps.update_one(
            {"id": dump["id"]},
            {"$set": {"status": "unsorted", "error": str(exc), "updated_at": _iso(_now())}},
        )
        return await db.inbox_dumps.find_one({"id": dump["id"]}, {"_id": 0})

    items = []
    for it in sorted_dump.items:
        remind_at = _local_to_utc_iso(it.remind_at_local, tz) if it.category == "reminder" else None
        items.append(_new_item(user["id"], dump["id"], it.text, it.category, remind_at))
    await db.inbox_items.delete_many({"dump_id": dump["id"], "category": "unsorted", "status": "open"})
    await db.inbox_items.insert_many(items)
    await db.inbox_dumps.update_one(
        {"id": dump["id"]},
        {"$set": {
            "status": "sorted",
            "error": None,
            "encouragement": sorted_dump.encouragement.strip(),
            "updated_at": _iso(_now()),
        }},
    )
    return await db.inbox_dumps.find_one({"id": dump["id"]}, {"_id": 0})


def _ack(dump: dict, items: List[dict]) -> str:
    if dump["status"] != "sorted":
        return "Saved. I couldn't sort it just now; it's safe in your inbox and I'll sort it later."
    counts = {c: sum(1 for i in items if i["category"] == c) for c in CATEGORIES}
    parts = [f"{n} {c}{'s' if n != 1 else ''}" for c, n in counts.items() if n]
    ack = f"Saved: {', '.join(parts)}."
    untimed = sum(1 for i in items if i["category"] == "reminder" and not i["remind_at"])
    if untimed:
        ack += f" {untimed} reminder{'s' if untimed != 1 else ''} need{'s' if untimed == 1 else ''} a time."
    if dump.get("encouragement"):
        ack = f"{dump['encouragement']} {ack}"
    return ack


async def _dump_response(db, dump: dict) -> dict:
    items = await db.inbox_items.find({"dump_id": dump["id"]}, {"_id": 0}).sort("created_at", 1).to_list(length=200)
    return {"dump": dump, "items": items, "ack": _ack(dump, items)}


@inbox_router.post("/dumps", status_code=201)
async def create_dump(body: DumpCreate, current_user: dict = Depends(get_current_user)):
    db = get_db()
    user_id = current_user["id"]
    if body.client_dump_id:
        existing = await db.inbox_dumps.find_one(
            {"user_id": user_id, "client_dump_id": body.client_dump_id}, {"_id": 0},
        )
        if existing:
            return await _dump_response(db, existing)
    tz = await _user_tz(db, current_user, body.timezone)

    now = _iso(_now())
    dump = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "client_dump_id": body.client_dump_id,
        "source": body.source,
        "raw_text": body.text.strip(),
        "status": "sorting",
        "sorting_started_at": now,
        "error": None,
        "encouragement": None,
        "created_at": now,
        "updated_at": now,
    }
    try:
        await db.inbox_dumps.insert_one(dump)
    except DuplicateKeyError:
        existing = await db.inbox_dumps.find_one(
            {"user_id": user_id, "client_dump_id": body.client_dump_id}, {"_id": 0},
        )
        return await _dump_response(db, existing)
    dump.pop("_id", None)
    dump = await _sort_and_store(db, current_user, dump, tz)
    return await _dump_response(db, dump)


@inbox_router.post("/dumps/{dump_id}/sort")
async def resort_dump(dump_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    now = _now()
    claimed = await db.inbox_dumps.find_one_and_update(
        {
            "id": dump_id,
            "user_id": current_user["id"],
            "$or": [
                {"status": "unsorted"},
                {"status": "sorting", "sorting_started_at": {"$lt": _iso(now - STALE_SORTING)}},
            ],
        },
        {"$set": {"status": "sorting", "sorting_started_at": _iso(now)}},
        projection={"_id": 0},
    )
    if claimed is None:
        dump = await db.inbox_dumps.find_one({"id": dump_id, "user_id": current_user["id"]}, {"_id": 0})
        if dump is None:
            raise HTTPException(status_code=404, detail="Dump not found")
        raise HTTPException(status_code=409, detail=f"Dump is {dump['status']}; nothing to sort")
    fallback = await db.inbox_items.find_one({"dump_id": dump_id, "category": "unsorted"})
    if fallback is not None and fallback["status"] != "open":
        # The user already acted on the raw item; re-sorting would duplicate it.
        await db.inbox_dumps.update_one({"id": dump_id}, {"$set": {"status": "unsorted"}})
        raise HTTPException(status_code=409, detail="The unsorted item was already handled")
    tz = await _user_tz(db, current_user, None)
    dump = await _sort_and_store(db, current_user, claimed, tz)
    return await _dump_response(db, dump)


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------

@inbox_router.get("/items")
async def list_items(
    status: Optional[str] = Query(default="open"),
    category: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    q: dict = {"user_id": current_user["id"]}
    if status:
        q["status"] = status
    if category:
        q["category"] = category
    return await get_db().inbox_items.find(q, {"_id": 0}).sort("created_at", -1).to_list(length=500)


async def _get_item(db, user_id: str, item_id: str) -> dict:
    item = await db.inbox_items.find_one({"id": item_id, "user_id": user_id}, {"_id": 0})
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@inbox_router.patch("/items/{item_id}")
async def update_item(item_id: str, body: ItemUpdate, current_user: dict = Depends(get_current_user)):
    db = get_db()
    await _get_item(db, current_user["id"], item_id)
    updates: dict = {}
    if body.text is not None:
        updates["text"] = body.text.strip()
    if body.category is not None:
        updates["category"] = body.category
    if body.remind_at is not None:
        if body.remind_at == "":
            updates["remind_at"] = None
        else:
            try:
                parsed = datetime.fromisoformat(body.remind_at)
            except ValueError:
                raise HTTPException(status_code=400, detail="remind_at must be ISO 8601")
            if parsed.tzinfo is None:
                raise HTTPException(status_code=400, detail="remind_at must include a timezone")
            updates["remind_at"] = _iso(parsed.astimezone(timezone.utc))
    if updates:
        updates["updated_at"] = _iso(_now())
        await db.inbox_items.update_one({"id": item_id}, {"$set": updates})
    return await _get_item(db, current_user["id"], item_id)


# ---------------------------------------------------------------------------
# Filter (daily review)
# ---------------------------------------------------------------------------

@inbox_router.get("/review")
async def get_review(
    limit: int = Query(default=DEFAULT_REVIEW_SIZE, ge=1, le=25),
    current_user: dict = Depends(get_current_user),
):
    """A short batch: due reminders first, then the oldest open items."""
    db = get_db()
    user_id = current_user["id"]
    now_iso = _iso(_now())
    due = await db.inbox_items.find(
        {"user_id": user_id, "status": "open", "remind_at": {"$ne": None, "$lte": now_iso}},
        {"_id": 0},
    ).sort("remind_at", 1).limit(limit).to_list(length=limit)
    rest: List[dict] = []
    remaining = limit - len(due)
    if remaining > 0:
        rest = await db.inbox_items.find(
            {"user_id": user_id, "status": "open", "id": {"$nin": [i["id"] for i in due]}},
            {"_id": 0},
        ).sort("created_at", 1).limit(remaining).to_list(length=remaining)
    nuggets = await db.inbox_items.find(
        {"user_id": user_id, "status": "nugget"}, {"_id": 0},
    ).sort("updated_at", 1).to_list(length=50)
    open_total = await db.inbox_items.count_documents({"user_id": user_id, "status": "open"})
    return {
        "prompt": REVIEW_PROMPT,
        "items": due + rest,
        "open_total": open_total,
        "nuggets": nuggets,
        "migrate_prompt": MIGRATE_PROMPT,
    }


@inbox_router.post("/review")
async def submit_review(body: ReviewSubmit, current_user: dict = Depends(get_current_user)):
    db = get_db()
    user_id = current_user["id"]
    now = _iso(_now())
    ids = [d.item_id for d in body.decisions]
    if len(set(ids)) != len(ids):
        raise HTTPException(status_code=400, detail="Each item may appear once")
    found = await db.inbox_items.find(
        {"user_id": user_id, "id": {"$in": ids}, "status": "open"}, {"_id": 0, "id": 1},
    ).to_list(length=len(ids))
    missing = set(ids) - {f["id"] for f in found}
    if missing:
        raise HTTPException(status_code=400, detail=f"Not open items: {sorted(missing)}")

    for d in body.decisions:
        if d.decision == "keep":
            update = {"$set": {"last_reviewed_at": now, "updated_at": now}, "$inc": {"review_count": 1}}
        else:
            status = {"done": "done", "discard": "discarded", "nugget": "nugget"}[d.decision]
            fields = {"status": status, "last_reviewed_at": now, "updated_at": now}
            if status in ("done", "discarded"):
                fields["closed_at"] = now
            update = {"$set": fields}
        await db.inbox_items.update_one({"id": d.item_id, "user_id": user_id, "status": "open"}, update)

    await db.inbox_reviews.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "decisions": [d.model_dump() for d in body.decisions],
        "created_at": now,
    })
    nuggets = await db.inbox_items.find(
        {"user_id": user_id, "status": "nugget"}, {"_id": 0},
    ).sort("updated_at", 1).to_list(length=50)
    counts = {k: sum(1 for d in body.decisions if d.decision == k) for k in REVIEW_DECISIONS}
    return {"counts": counts, "nuggets": nuggets, "migrate_prompt": MIGRATE_PROMPT}


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

def _validate_date(value: Optional[str], field: str) -> Optional[str]:
    if not value:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{field} must be YYYY-MM-DD")


@inbox_router.post("/items/{item_id}/migrate")
async def migrate_item(item_id: str, body: MigrateRequest, current_user: dict = Depends(get_current_user)):
    db = get_db()
    user_id = current_user["id"]
    item = await _get_item(db, user_id, item_id)
    if item["status"] not in ("open", "nugget"):
        raise HTTPException(status_code=409, detail=f"Item is already {item['status']}")
    due_date = _validate_date(body.due_date, "due_date")
    if body.time and not _HHMM.match(body.time):
        raise HTTPException(status_code=400, detail="time must be HH:MM")
    if body.destination == "calendar" and not due_date:
        raise HTTPException(status_code=400, detail="A calendar entry needs a due_date")
    if body.project_id and body.expected_outcome_id:
        raise HTTPException(status_code=400, detail="Choose a project or a goal outcome, not both")

    # Claim first so a double submit can't create two destinations.
    now = _iso(_now())
    claimed = await db.inbox_items.find_one_and_update(
        {"id": item_id, "user_id": user_id, "status": {"$in": ["open", "nugget"]}},
        {"$set": {"status": "migrating", "updated_at": now}},
    )
    if claimed is None:
        raise HTTPException(status_code=409, detail="Item changed; reload and try again")

    try:
        if body.destination == "wishlist":
            wish = {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "title": item["text"],
                "next_step": body.next_step.strip(),
                "source_item_id": item_id,
                "status": "open",
                "created_at": now,
                "updated_at": now,
            }
            await db.wishlist_items.insert_one(wish)
            migrated_to = {"type": "wishlist", "id": wish["id"]}
        else:
            # Lazy import: server imports this module at startup.
            from server import TaskCreate, create_task

            notes = f"From your brain dump: {item['text']}"
            if body.destination == "calendar" and body.time:
                notes = f"Scheduled for {body.time}. {notes}"
            origin = "standalone"
            if body.project_id:
                origin = "project"
            elif body.expected_outcome_id:
                origin = "expected_outcome"
            task = await create_task(TaskCreate(
                title=body.next_step.strip(),
                due_date=due_date or "",
                notes=notes,
                origin=origin,
                project_id=body.project_id,
                expected_outcome_id=body.expected_outcome_id,
            ), current_user=current_user)
            migrated_to = {"type": body.destination, "id": task.id}
    except BaseException:
        await db.inbox_items.update_one(
            {"id": item_id, "status": "migrating"},
            {"$set": {"status": item["status"], "updated_at": _iso(_now())}},
        )
        raise

    await db.inbox_items.update_one(
        {"id": item_id},
        {"$set": {
            "status": "migrated",
            "next_step": body.next_step.strip(),
            "migrated_to": migrated_to,
            "closed_at": _iso(_now()),
            "updated_at": _iso(_now()),
        }},
    )
    return {"item": await _get_item(db, user_id, item_id), "migrated_to": migrated_to}


@inbox_router.get("/wishlist")
async def list_wishlist(current_user: dict = Depends(get_current_user)):
    return await get_db().wishlist_items.find(
        {"user_id": current_user["id"], "status": "open"}, {"_id": 0},
    ).sort("created_at", -1).to_list(length=500)


# ---------------------------------------------------------------------------
# Patterns (weekly)
# ---------------------------------------------------------------------------

async def build_week_stats(db, user_id: str, *, now: Optional[datetime] = None) -> dict:
    now = now or _now()
    since = _iso(now - timedelta(days=7))
    captured = await db.inbox_items.find(
        {"user_id": user_id, "created_at": {"$gte": since}}, {"_id": 0},
    ).to_list(length=1000)
    avoided = await db.inbox_items.find(
        {"user_id": user_id, "status": "open", "review_count": {"$gte": AVOIDED_AFTER_REVIEWS}},
        {"_id": 0},
    ).sort("review_count", -1).to_list(length=20)
    closed = await db.inbox_items.find(
        {"user_id": user_id, "closed_at": {"$gte": since}}, {"_id": 0, "status": 1},
    ).to_list(length=1000)
    reviews = await db.inbox_reviews.count_documents({"user_id": user_id, "created_at": {"$gte": since}})
    return {
        "since": since,
        "captured": len(captured),
        "captured_by_category": {c: sum(1 for i in captured if i["category"] == c) for c in CATEGORIES},
        "completed": sum(1 for c in closed if c["status"] == "done"),
        "discarded": sum(1 for c in closed if c["status"] == "discarded"),
        "migrated": sum(1 for c in closed if c["status"] == "migrated"),
        "reviews": reviews,
        "avoided": [
            {"id": i["id"], "text": i["text"], "category": i["category"], "review_count": i["review_count"]}
            for i in avoided
        ],
        "_captured_items": captured,
    }


def _week_report(stats: dict) -> str:
    items = [
        {"text": i["text"], "category": i["category"], "status": i["status"]}
        for i in stats["_captured_items"]
    ]
    public = {k: v for k, v in stats.items() if not k.startswith("_")}
    return (
        "<week_stats>\n" + json.dumps(public, indent=1) + "\n</week_stats>\n"
        "<captured_items>\n" + json.dumps(items, indent=1) + "\n</captured_items>"
    )


@inbox_router.post("/patterns", status_code=201)
async def generate_patterns(current_user: dict = Depends(get_current_user)):
    db = get_db()
    stats = await build_week_stats(db, current_user["id"])
    insight = None
    error = None
    if stats["captured"] or stats["avoided"]:
        try:
            insight = (await inbox_ai.summarise_patterns(_week_report(stats))).model_dump()
        except inbox_ai.AssistantUnavailable as exc:
            error = str(exc)
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": current_user["id"],
        "stats": {k: v for k, v in stats.items() if not k.startswith("_")},
        "insight": insight,
        "error": error,
        "created_at": _iso(_now()),
    }
    await db.inbox_insights.insert_one(doc)
    return _public(doc)


@inbox_router.get("/patterns")
async def latest_patterns(current_user: dict = Depends(get_current_user)):
    doc = await get_db().inbox_insights.find_one(
        {"user_id": current_user["id"]}, {"_id": 0}, sort=[("created_at", -1)],
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="No weekly patterns yet")
    return doc


async def ensure_inbox_indexes(db) -> None:
    await db.inbox_dumps.create_index("id", unique=True)
    await db.inbox_dumps.create_index(
        [("user_id", 1), ("client_dump_id", 1)],
        unique=True,
        partialFilterExpression={"client_dump_id": {"$type": "string"}},
    )
    await db.inbox_items.create_index("id", unique=True)
    await db.inbox_items.create_index([("user_id", 1), ("status", 1), ("created_at", 1)])
    await db.inbox_items.create_index("dump_id")
    await db.inbox_reviews.create_index([("user_id", 1), ("created_at", -1)])
    await db.inbox_insights.create_index([("user_id", 1), ("created_at", -1)])
    await db.wishlist_items.create_index([("user_id", 1), ("status", 1)])
