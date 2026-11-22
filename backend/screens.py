"""One call per screen: everything a screen shows, in a single round trip.

The phone pays for each request it makes; a screen that needs four answers
should ask once. These endpoints bundle what the screens read today, and
reuse the per-request memo so the bundle costs about as much as its largest
part.
"""
from __future__ import annotations

from datetime import date as date_type

from fastapi import APIRouter, Depends

import display
import planned_money
from deps import get_current_user, get_db

screens_router = APIRouter(prefix="/screens", tags=["screens"])


def _when(item: dict, today) -> str:
    """Once: "Tuesday" / "5 Dec"; monthly: "Every month"; yearly: "Every December"."""
    if item.get("repeat") == "monthly":
        return "Every month"
    if item.get("repeat") == "yearly" and item.get("start_month"):
        return "Every " + date_type.fromisoformat(item["start_month"] + "-01").strftime("%B")
    return display.day(item.get("date"), today) if item.get("date") else ""


@screens_router.get("/finance")
async def finance_screen(current_user: dict = Depends(get_current_user)):
    """The Finance tab: the dashboard (position, available money, forecast…)
    plus the next 6 planned items and this month's planned totals."""
    import finance_manager

    dashboard = await finance_manager.get_dashboard(current_user=current_user)
    items = await planned_money.load_items(get_db(), current_user["id"])
    upcoming = sorted((i for i in items if i["status"] == "active"),
                      key=lambda i: i.get("date") or (i.get("start_month") or "") + "-01")[:6]
    month = date_type.today().isoformat()[:7]
    currencies = sorted({i["currency"] for i in items if i["currency"]})
    totals = [{"month": month, "currency": c,
               **{k: planned_money._out(v) for k, v in planned_money.month_totals(items, month, c).items()}}
              for c in currencies]
    today = date_type.today()
    want = current_user.get("portfolio_reporting_currency") or "INR"
    pos = (dashboard.get("position") or {}).get("currencies") or []
    row = next((c for c in pos if c["currency"] == want), pos[0] if pos else None)
    left = next((r for r in dashboard.get("available_liquidity") or [] if r.get("currency") == want), None)
    headline = {
        "currency": want,
        "net_worth": row["net_worth"] if row else None,
        "net_worth_label": display.money(row["net_worth"], row["currency"]) if row else None,
        "left_to_spend": left.get("available_unreserved") if left else None,
        "left_to_spend_label": display.money(left.get("available_unreserved"), want) if left else None,
        "coming_up": [{"id": i["id"], "title": i.get("title") or "", "direction": i.get("direction"),
                       "when": _when(i, today),
                       "amount_label": display.money(i.get("amount"), i.get("currency"), sign=i.get("direction") == "in")}
                      for i in upcoming[:4]],
    }
    return {"dashboard": dashboard, "planned_upcoming": [planned_money.public(i) for i in upcoming],
            "planned_this_month": totals, "headline": headline}


# ---------------------------------------------------------------------------
# Today, Life and the Money headline: ready-worded for the redesigned screens
# (docs/DESIGN.md). Each part is optional: a part that fails or has nothing to
# say is left out (null), never shown as zeros.
# ---------------------------------------------------------------------------

import logging as _logging

_log = _logging.getLogger(__name__)


async def _safe(coro, what: str):
    try:
        return await coro
    except Exception:
        _log.exception("screens: %s failed", what)
        return None


def _local(user: dict):
    from life_plans import local_now
    return local_now(user)


async def _free_today(db, user: dict, now) -> dict:
    from life_plans import free_slots
    blocks = await db.time_commitments.find({"user_id": user["id"]}, {"_id": 0}).to_list(length=None)
    bookings = await db.resource_allocations.find({"user_id": user["id"]}, {"_id": 0}).to_list(length=None)
    slots = free_slots([now.date()], blocks, bookings, "06:00", "23:00", 15, now=now)
    minutes = sum(s["minutes"] for s in slots)
    return {"minutes": minutes, "label": display.duration(minutes),
            "when": "this evening" if now.hour >= 16 else "today"}


async def _left_to_spend(db, user: dict) -> dict:
    import finance_manager
    rows = await finance_manager._available_liquidity(db, user["id"])
    if not rows:
        return None
    want = user.get("portfolio_reporting_currency") or "INR"
    row = next((r for r in rows if r.get("currency") == want), rows[0])
    amount = row.get("available_unreserved")
    return {"amount": amount, "currency": row.get("currency"), "label": display.money(amount, row.get("currency"))}


async def _next_day_that_matters(db, user: dict, today) -> dict:
    from relationships import days_coming
    best = None
    async for p in db.people.find({"user_id": user["id"]}, {"_id": 0}):
        for c in days_coming(p, today, 7):
            if best is None or c["in_days"] < best["in_days"]:
                best = c
    if best:
        detail = []
        if best.get("years") and best["label"].lower() == "birthday":
            detail.append(f"Turns {best['years']}")
        elif best.get("years"):
            detail.append(f"{best['years']} years")
        if best.get("gift_budget"):
            detail.append(f"gift budget {display.money(best['gift_budget'])}")
        return {"kind": "person_day", "person_id": best["person_id"],
                "title": f"{best['name']}'s {best['label'].lower()}", "when": display.day(best["on"], today),
                "detail": " · ".join(detail), "screen": "people"}
    items = await planned_money.load_items(db, user["id"])
    soon = []
    for i in items:
        if i["status"] != "active" or i.get("direction") != "out" or not i.get("date"):
            continue
        try:
            d = date_type.fromisoformat(i["date"])
        except ValueError:
            continue
        if 0 <= (d - today).days <= 7:
            soon.append((d, i))
    if soon:
        d, i = sorted(soon, key=lambda x: x[0])[0]
        return {"kind": "money_due", "title": i.get("title") or "A payment", "when": display.day(d, today),
                "detail": display.money(i.get("amount"), i.get("currency")), "screen": "finance/planned"}
    return None


@screens_router.get("/today")
async def today_screen(current_user: dict = Depends(get_current_user)):
    """The Today tab, top to bottom: greeting, your 3 things, the next day that
    matters (or a payment due), free time, money left to spend, setup."""
    import account
    db = get_db()
    uid = current_user["id"]
    now = _local(current_user)
    today = now.date()
    iso = today.isoformat()
    open_tasks = await db.tasks.find({"user_id": uid, "status": "todo", "due_date": {"$nin": [None, ""], "$lte": iso}},
                                     {"_id": 0, "id": 1, "title": 1, "due_date": 1, "priority": 1}).to_list(length=200)
    rank = {"high": 0, "medium": 1, "low": 2}
    open_tasks.sort(key=lambda t: (t["due_date"] == iso, rank.get(t.get("priority"), 1), t["due_date"]))
    done_today = await db.tasks.find({"user_id": uid, "status": "done", "due_date": iso},
                                     {"_id": 0, "id": 1, "title": 1}).to_list(length=20)
    things = [{"task_id": t["id"], "title": t["title"], "done": True, "note": ""} for t in done_today[:1]]
    for t in open_tasks[: 3 - len(things)]:
        things.append({"task_id": t["id"], "title": t["title"], "done": False,
                       "note": "" if t["due_date"] == iso else f"since {display.day(t['due_date'], today)}"})
    setup = await _safe(account.setup(current_user=current_user), "setup")
    review_open = await db.inbox_items.count_documents({"user_id": uid, "status": "open"})
    return {
        "date_label": f"{now.strftime('%A')}, {today.day} {now.strftime('%B')}",
        "greeting": display.greeting(now.hour, current_user.get("name")),
        "things": things, "more_things": max(0, len(open_tasks) - (3 - min(1, len(done_today)))),
        "highlight": await _safe(_next_day_that_matters(db, current_user, today), "highlight"),
        "free_time": await _safe(_free_today(db, current_user, now), "free time"),
        "money": await _safe(_left_to_spend(db, current_user), "money"),
        "review": {"open": review_open} if review_open else None,
        "setup": None if not setup or setup.get("complete") else {
            "done": setup["done"], "of": setup["of"],
            "next": {"title": setup["next"]["title"], "screen": setup["next"]["screen"]} if setup.get("next") else None},
    }


async def _area_health(db, user: dict, today) -> dict:
    import health
    from health_checkups import _calendar
    from fastapi import HTTPException
    try:
        profile = await health._profile(db, user["id"])          # 403 until they consent
    except HTTPException:
        profile = None
    if not profile or not profile.get("consent"):
        return {"line": "Switch on a 30-second daily check-in.", "status": "setup"}
    rows = await db.health_measurements.find({"user_id": user["id"]}, {"_id": 0}).to_list(length=None)
    parts, status = [], "good"
    sleep = health.recent_average(rows, "sleep_hours", today)
    if sleep:
        parts.append(f"Slept {display.duration(int(float(sleep[0]) * 60))} on average.")
    cal = await _safe(_calendar(db, user), "check-ups")
    due = [c for c in (cal or {}).get("checks", []) if c["status"] in ("overdue", "due_soon")]
    if due:
        parts.append("One check-up due." if len(due) == 1 else f"{len(due)} check-ups due.")
        status = "attention"
    return {"line": " ".join(parts) or "Log a day to see how you're doing.", "status": status if parts else "quiet"}


async def _area_family(db, user: dict, today) -> dict:
    from relationships import summary
    s = await summary(current_user=user)
    if not s["people"]:
        return {"line": "Add the people who matter most.", "status": "setup"}
    parts = []
    if s["coming_up"]:
        c = s["coming_up"][0]
        parts.append(f"{c['name']}'s {c['label'].lower()} {display.day(c['on'], today).lower() if c['in_days'] < 2 else 'on ' + display.day(c['on'], today)}.")
    named = {s["coming_up"][0]["person_id"]} if s["coming_up"] else set()
    hear = [h for h in s["might_like_to_hear_from_you"] if h["person_id"] not in named]
    if hear:
        parts.append(f"{hear[0]['name']} might like to hear from you.")
    return {"line": " ".join(parts) or f"{s['moments_this_month']} moments together this month.",
            "status": "attention" if parts else "good"}


async def _area_learning(db, user: dict, today) -> dict:
    from learning import list_journeys
    rows = [j for j in await list_journeys(current_user=user) if j["status"] == "active"]
    if not rows:
        return {"line": "Start learning something.", "status": "setup"}
    j = rows[0]
    pace = (j.get("pace") or {}).get("status")
    words = {"on_track": "On track.", "ahead": "Ahead.", "behind": "A little behind."}.get(pace, "")
    mins = sum(x.get("today_minutes") or 0 for x in rows)
    line = f"{display.duration(mins)} of {j['title']} today. {words}".strip() if mins else f"{j['title']}: {words or 'nothing due today.'}"
    return {"line": line, "status": "attention" if pace == "behind" else "good"}


async def _area_work(db, user: dict, today) -> dict:
    if not await db.work_roles.find_one({"user_id": user["id"], "ended_on": None}, {"_id": 1}):
        return {"line": "Add your work hours.", "status": "setup"}
    from work import week
    w = await week(week_start=None, current_user=user)
    line = w.get("summary") or "This week so far."
    return {"line": line, "status": "good" if "in its box" in line else "attention"}


async def _area_plans(db, user: dict, today) -> dict:
    from life_plans import list_plans
    plans = await list_plans(current_user=user)
    if not plans:
        return {"line": "Tell Hymn one thing you want.", "status": "setup"}
    p = plans[0]
    drift = p.get("drift") or []
    state = "needs attention" if drift or p.get("verdict") in ("short", "not_yet") else "on track"
    more = f" (+{len(plans) - 1} more)" if len(plans) > 1 else ""
    return {"line": f"{p.get('title')}: {state}.{more}", "status": "attention" if state != "on track" else "good"}


@screens_router.get("/life")
async def life_screen(current_user: dict = Depends(get_current_user)):
    """The Life tab: each area with one line on how it's going.
    status: good · attention · setup (not started) · quiet (nothing to say)."""
    db = get_db()
    today = _local(current_user).date()
    areas = []
    for key, title, screen, fn in (("health", "Health", "health", _area_health),
                                   ("family", "Family", "people", _area_family),
                                   ("learning", "Learning", "learning", _area_learning),
                                   ("work", "Work", "work", _area_work),
                                   ("plans", "Plans", "planner", _area_plans)):
        got = await _safe(fn(db, current_user, today), key) or {"line": "", "status": "quiet"}
        areas.append({"key": key, "title": title, "screen": screen, **got})
    return {"areas": areas}
