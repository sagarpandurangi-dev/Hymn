"""The admin page's server side, and beta invites.

Only emails in the Railway variable HYMN_ADMIN_EMAILS get in, and only with a
login from the last 12 hours. Every change made here is written to
``admin_audit``.

Privacy rule: the admin sees counts, costs and dates, never content (no task
titles, notes, money amounts, messages, health readings). Views about one
person also never show Health use: health features are folded into
"private" there, and only appear in totals with no person attached.
"""
from __future__ import annotations

import os
import re
import secrets
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import metering
from deps import get_current_user, get_db, oauth2_scheme
from plans import user_plan

admin_router = APIRouter(prefix="/admin", tags=["admin"])
invites_router = APIRouter(prefix="/invites", tags=["invites"])
admin_page_router = APIRouter()

FRESH_LOGIN_HOURS = 12
PREMIUM_ONLY_CHOICES = ["statements", "life_objects"]
PRIVATE = "private"                      # what health features are called in per-person views
_SAFE_USER_FIELDS = {"_id": 0, "id": 1, "email": 1, "name": 1, "plan": 1, "created_at": 1, "last_active_at": 1,
                     "cohort": 1, "invited_by": 1, "suspended": 1, "ai_bonus": 1, "timezone": 1,
                     "app_version": 1}
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _day(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def admin_emails() -> set:
    return {e.strip().lower() for e in os.environ.get("HYMN_ADMIN_EMAILS", "").split(",") if e.strip()}


async def require_admin(token: str = Depends(oauth2_scheme), user: dict = Depends(get_current_user)) -> dict:
    from jose import JWTError, jwt
    from server import JWT_ALG, JWT_SECRET

    if (user.get("email") or "").lower() not in admin_emails():
        raise HTTPException(status_code=403, detail="This page is for Hymn's admin only.")
    try:
        iat = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG]).get("iat")
    except JWTError:
        iat = None
    if not iat or _now() - datetime.fromtimestamp(int(iat), timezone.utc) > timedelta(hours=FRESH_LOGIN_HOURS):
        raise HTTPException(status_code=401, detail="Please sign in again to use the admin page.")
    return user


async def audit(db, admin: dict, action: str, target: Optional[str] = None, detail: Optional[dict] = None) -> None:
    await db.admin_audit.insert_one({"at": _now().isoformat(), "admin_id": admin["id"], "action": action,
                                     "target_user_id": target, "detail": detail or {}})


def _private(feature: str) -> str:
    return PRIVATE if metering.area_of(feature) == "health" else feature


async def _users(db) -> List[dict]:
    return await db.users.find({}, _SAFE_USER_FIELDS).to_list(length=None)


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

@admin_router.get("/overview")
async def overview(admin: dict = Depends(require_admin)):
    db = get_db()
    await metering.flush(db)
    now = _now()
    today = _day(now)
    s = await metering.get_settings(db)
    users = await _users(db)
    since30 = _day(now - timedelta(days=29))
    since7 = _day(now - timedelta(days=6))
    rows = await db.usage_daily.find({"day": {"$gte": _day(now - timedelta(days=89))}},
                                     {"_id": 0, "day": 1, "user_id": 1, "feature": 1, "calls": 1}) \
        .to_list(length=None)
    days_of = defaultdict(set)
    for r in rows:
        if metering.area_of(r["feature"]) != "account":
            days_of[r["user_id"]].add(r["day"])
    by_day = defaultdict(set)
    for r in rows:
        if r["day"] >= since30:
            by_day[r["day"]].add(r["user_id"])
    active = [{"day": _day(now - timedelta(days=i)), "people": len(by_day.get(_day(now - timedelta(days=i)), ()))}
              for i in range(29, -1, -1)]
    signups = Counter((u.get("created_at") or "")[:10] for u in users)

    def retention(n: int) -> dict:
        eligible = [u for u in users if u.get("created_at") and
                    _day(now - timedelta(days=89)) <= u["created_at"][:10] <= _day(now - timedelta(days=n))]
        kept = 0
        for u in eligible:
            start = datetime.fromisoformat(u["created_at"][:10]).date() + timedelta(days=n)
            if any(d >= start.isoformat() for d in days_of.get(u["id"], ())):
                kept += 1
        return {"eligible": len(eligible), "returned": kept,
                "percent": round(100 * kept / len(eligible)) if eligible else None}

    totals = await db.usage_totals.find({"day": {"$gte": since7}}, {"_id": 0}).to_list(length=None)
    people_by_feature = defaultdict(set)
    for r in rows:
        if r["day"] >= since7:
            people_by_feature[r["feature"]].add(r["user_id"])
    features = defaultdict(lambda: {"calls": 0, "errors": 0})
    for t in totals:
        features[t["feature"]]["calls"] += t.get("calls", 0)
        features[t["feature"]]["errors"] += t.get("errors", 0)
    feature_rows = sorted(({"feature": f, "area": metering.area_of(f), **v, "people": len(people_by_feature[f])}
                           for f, v in features.items()), key=lambda x: -x["calls"])
    areas = defaultdict(lambda: {"calls": 0, "people": set()})
    for f, v in features.items():
        a = areas[metering.area_of(f)]
        a["calls"] += v["calls"]
        a["people"] |= people_by_feature[f]
    month = now.strftime("%Y-%m")
    ai_rows = await db.ai_daily.find({"month": month}, {"_id": 0}).to_list(length=None)
    month_inr = round(sum(r.get("cost_inr", 0) for r in ai_rows), 2)
    today_inr = round(sum(r.get("cost_inr", 0) for r in ai_rows if r["day"] == today), 2)
    status = "stopped" if month_inr >= s["ai_stop_inr"] else "warning" if month_inr >= s["ai_warn_inr"] else "ok"
    errors_today = await db.errors.count_documents({"day": today})
    with_use = {u for u, d in days_of.items() if d}
    return {
        "as_of": now.isoformat(),
        "people": {"total": len(users), "active_today": len(by_day.get(today, ())),
                   "active_7_days": len({r["user_id"] for r in rows if r["day"] >= since7}),
                   "active_30_days": len({r["user_id"] for r in rows if r["day"] >= since30}),
                   "new_today": signups.get(today, 0),
                   "new_7_days": sum(v for k, v in signups.items() if k >= since7)},
        "active_by_day": active,
        "signups_by_day": [{"day": d["day"], "people": signups.get(d["day"], 0)} for d in active],
        "returned": {"day_1": retention(1), "day_7": retention(7), "day_30": retention(30)},
        "funnel": {"signed_up": len(users), "used_a_feature": len(with_use),
                   "active_3_days": sum(1 for d in days_of.values() if len(d) >= 3),
                   "active_last_7_days": len({r["user_id"] for r in rows if r["day"] >= since7
                                              and metering.area_of(r["feature"]) != "account"})},
        "areas_7_days": sorted(({"area": a, "calls": v["calls"], "people": len(v["people"])} for a, v in areas.items()),
                               key=lambda x: -x["calls"]),
        "features_7_days": feature_rows,
        "ai": {"today_inr": today_inr, "month_inr": month_inr, "warn_inr": s["ai_warn_inr"],
               "stop_inr": s["ai_stop_inr"], "status": status,
               "used_percent": round(100 * month_inr / s["ai_stop_inr"]) if s["ai_stop_inr"] else None,
               "switched_off": s["ai_off"]},
        "errors_today": errors_today,
        "beta": {"people": len(users), "cap": s["beta_cap"], "invite_only": s["invite_only"]},
    }


# ---------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------

async def _ai_by_user(db, month: str) -> dict:
    out = defaultdict(lambda: {"inr": 0.0, "calls": 0})
    async for r in db.ai_calls.find({"month": month}, {"_id": 0, "user_id": 1, "cost_inr": 1}):
        if r.get("user_id"):
            out[r["user_id"]]["inr"] += r.get("cost_inr", 0)
            out[r["user_id"]]["calls"] += 1
    return out


async def _row(db, u: dict, ai: dict, usage: list, emails: dict, wa: set) -> dict:
    mine = [r for r in usage if r["user_id"] == u["id"]]
    feats = Counter()
    for r in mine:
        feats[_private(r["feature"])] += r.get("calls", 0)
    feats.pop(PRIVATE, None)
    return {"id": u["id"], "email": u.get("email"), "name": u.get("name"), "plan": user_plan(u),
            "plan_set_here": u.get("plan") is not None, "joined": u.get("created_at"),
            "last_active": u.get("last_active_at"), "cohort": u.get("cohort"),
            "invited_by": emails.get(u.get("invited_by")) or ("admin" if u.get("invited_by") == "admin" else None),
            "suspended": bool(u.get("suspended")), "ai_month_inr": round(ai.get(u["id"], {}).get("inr", 0), 2),
            "ai_month_calls": ai.get(u["id"], {}).get("calls", 0),
            "active_days_30": len({r["day"] for r in mine}), "top_features": [f for f, _ in feats.most_common(3)],
            "whatsapp": u["id"] in wa, "app_version": u.get("app_version")}


@admin_router.get("/users")
async def list_users(q: str = Query("", max_length=100), sort: str = Query("last_active"),
                     admin: dict = Depends(require_admin)):
    db = get_db()
    await metering.flush(db)
    now = _now()
    users = await _users(db)
    if q:
        ql = q.lower()
        users = [u for u in users if ql in (u.get("email") or "").lower() or ql in (u.get("name") or "").lower()
                 or ql == (u.get("cohort") or "").lower()]
    ai = await _ai_by_user(db, now.strftime("%Y-%m"))
    usage = await db.usage_daily.find({"day": {"$gte": _day(now - timedelta(days=29))}},
                                      {"_id": 0, "user_id": 1, "day": 1, "feature": 1, "calls": 1}).to_list(length=None)
    emails = {u["id"]: u.get("email") for u in await _users(db)}
    wa = {r["user_id"] for r in await db.wa_link.find({}, {"_id": 0, "user_id": 1}).to_list(length=None)}
    rows = [await _row(db, u, ai, usage, emails, wa) for u in users]
    key = {"ai": lambda r: -r["ai_month_inr"], "joined": lambda r: r["joined"] or "",
           "last_active": lambda r: r["last_active"] or ""}.get(sort, lambda r: r["last_active"] or "")
    rows.sort(key=key, reverse=sort in ("joined", "last_active"))
    return {"count": len(rows), "users": rows}


async def _user_or_404(db, user_id: str) -> dict:
    u = await db.users.find_one({"id": user_id}, _SAFE_USER_FIELDS)
    if not u:
        raise HTTPException(status_code=404, detail="No such person")
    return u


@admin_router.get("/users/{user_id}")
async def user_detail(user_id: str, admin: dict = Depends(require_admin)):
    import account

    db = get_db()
    await metering.flush(db)
    now = _now()
    u = await _user_or_404(db, user_id)
    month = now.strftime("%Y-%m")
    usage = await db.usage_daily.find({"user_id": user_id, "day": {"$gte": _day(now - timedelta(days=29))}},
                                      {"_id": 0}).to_list(length=None)
    emails = {x["id"]: x.get("email") for x in await _users(db)}
    wa_link = await db.wa_link.find_one({"user_id": user_id}, {"_id": 0, "wa_id": 1})
    row = await _row(db, u, await _ai_by_user(db, month), usage, emails, {user_id} if wa_link else set())
    per_day = Counter()
    feats = Counter()
    for r in usage:
        if _private(r["feature"]) != PRIVATE:
            per_day[r["day"]] += r.get("calls", 0)
        feats[_private(r["feature"])] += r.get("calls", 0)
    ai_feats = defaultdict(lambda: {"inr": 0.0, "calls": 0})
    async for r in db.ai_calls.find({"user_id": user_id, "month": month}, {"_id": 0, "feature": 1, "cost_inr": 1}):
        a = ai_feats[_private(r.get("feature") or "other")]
        a["inr"] += r.get("cost_inr", 0)
        a["calls"] += 1
    full = await db.users.find_one({"id": user_id}, {"_id": 0})
    setup = await account.setup(current_user=full)
    steps = [{"key": s_["key"], "title": s_["title"], "done": s_["done"]} for s_ in setup["steps"]
             if s_["key"] != "health"]
    code = await db.invites.find_one({"created_by": user_id, "kind": "personal"}, {"_id": 0, "code": 1, "uses": 1})
    return {**row,
            "activity_30_days": [{"day": _day(now - timedelta(days=i)), "calls": per_day.get(_day(now - timedelta(days=i)), 0)}
                                 for i in range(29, -1, -1)],
            "features_30_days": [{"feature": f, "calls": c} for f, c in feats.most_common()],
            "ai_month_by_feature": sorted(({"feature": f, "inr": round(v["inr"], 2), "calls": v["calls"]}
                                           for f, v in ai_feats.items()), key=lambda x: -x["inr"]),
            "setup": steps,
            "invites_used": (code or {}).get("uses", 0),
            "errors_7_days": await db.errors.count_documents({"user_id": user_id,
                                                              "day": {"$gte": _day(now - timedelta(days=6))}}),
            "ai_bonus": u.get("ai_bonus"),
            "premium": {"source": "manual" if u.get("plan") else full.get("premium_source"),
                        "until": full.get("premium_until"), "founding_member": bool(full.get("founding_member")),
                        "subscription": await db.subscriptions.find_one(
                            {"user_id": user_id, "status": {"$in": ["active", "grace", "cancelling"]}},
                            {"_id": 0, "provider": 1, "plan": 1, "status": 1, "current_period_end": 1})}}


class PlanChange(BaseModel):
    plan: str = Field(pattern="^(premium|free|default)$")


class Allowance(BaseModel):
    strong: int = Field(default=0, ge=0, le=500)
    light: int = Field(default=0, ge=0, le=2000)
    days: int = Field(default=7, ge=1, le=90)


class Suspend(BaseModel):
    suspended: bool


class DeleteUser(BaseModel):
    confirm_email: str


@admin_router.post("/users/{user_id}/plan")
async def set_plan(user_id: str, body: PlanChange, admin: dict = Depends(require_admin)):
    db = get_db()
    await _user_or_404(db, user_id)
    if body.plan == "default":
        await db.users.update_one({"id": user_id}, {"$unset": {"plan": ""}})
    else:
        await db.users.update_one({"id": user_id}, {"$set": {"plan": body.plan}})
    await audit(db, admin, "set_plan", user_id, {"plan": body.plan})
    return {"plan": user_plan(await db.users.find_one({"id": user_id}, {"_id": 0}))}


@admin_router.post("/users/{user_id}/ai-allowance")
async def give_allowance(user_id: str, body: Allowance, admin: dict = Depends(require_admin)):
    db = get_db()
    await _user_or_404(db, user_id)
    until = _day(_now() + timedelta(days=body.days - 1))
    bonus = {"strong": body.strong, "light": body.light, "until": until}
    await db.users.update_one({"id": user_id}, {"$set": {"ai_bonus": bonus}})
    await audit(db, admin, "ai_allowance", user_id, bonus)
    return {"ai_bonus": bonus}


@admin_router.post("/users/{user_id}/sign-out")
async def sign_out_everywhere(user_id: str, admin: dict = Depends(require_admin)):
    db = get_db()
    await _user_or_404(db, user_id)
    await db.users.update_one({"id": user_id}, {"$inc": {"token_version": 1}})
    await audit(db, admin, "sign_out", user_id)
    return {"detail": "Signed out on every device."}


@admin_router.post("/users/{user_id}/suspend")
async def suspend(user_id: str, body: Suspend, admin: dict = Depends(require_admin)):
    db = get_db()
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="You can't pause your own account.")
    await _user_or_404(db, user_id)
    upd = {"$set": {"suspended": True}, "$inc": {"token_version": 1}} if body.suspended \
        else {"$unset": {"suspended": ""}}
    await db.users.update_one({"id": user_id}, upd)
    await audit(db, admin, "suspend" if body.suspended else "unsuspend", user_id)
    return {"suspended": body.suspended}


@admin_router.delete("/users/{user_id}")
async def delete_user(user_id: str, body: DeleteUser, admin: dict = Depends(require_admin)):
    import account

    db = get_db()
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="Delete your own account from the app instead.")
    full = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not full:
        raise HTTPException(status_code=404, detail="No such person")
    if body.confirm_email.strip().lower() != (full.get("email") or "").lower():
        raise HTTPException(status_code=400, detail="Type the person's email exactly to confirm.")
    removed = await account.erase_user(db, full)
    await audit(db, admin, "delete_user", user_id, {"records_removed": removed})
    return {"detail": "Deleted.", "records_removed": removed}


# ---------------------------------------------------------------------------
# AI, system, settings, audit
# ---------------------------------------------------------------------------

@admin_router.get("/ai")
async def ai_report(days: int = Query(30, ge=1, le=90), admin: dict = Depends(require_admin)):
    db = get_db()
    now = _now()
    s = await metering.get_settings(db)
    since = _day(now - timedelta(days=days - 1))
    rows = await db.ai_daily.find({"day": {"$gte": since}}, {"_id": 0}).to_list(length=None)
    month = now.strftime("%Y-%m")
    by_day = defaultdict(lambda: {"inr": 0.0, "calls": 0})
    by_feature = defaultdict(lambda: {"inr": 0.0, "calls": 0, "failed": 0})
    by_model = defaultdict(lambda: {"inr": 0.0, "calls": 0, "input": 0, "output": 0, "searches": 0})
    for r in rows:
        d = by_day[r["day"]]
        d["inr"] += r.get("cost_inr", 0)
        d["calls"] += r.get("calls", 0)
        if r.get("month") == month:
            f = by_feature[r["feature"]]
            f["inr"] += r.get("cost_inr", 0)
            f["calls"] += r.get("calls", 0)
            f["failed"] += r.get("failed", 0)
            m = by_model[r["model"]]
            m["inr"] += r.get("cost_inr", 0)
            m["calls"] += r.get("calls", 0)
            for k in ("input", "output", "searches"):
                m[k] += r.get(k, 0)
    month_inr = round(sum(v["inr"] for v in by_feature.values()), 2)
    users = {u["id"]: u.get("email") for u in await _users(db)}
    top = sorted((await _ai_by_user(db, month)).items(), key=lambda kv: -kv[1]["inr"])[:10]
    return {
        "month_inr": month_inr, "warn_inr": s["ai_warn_inr"], "stop_inr": s["ai_stop_inr"], "usd_inr": s["usd_inr"],
        "by_day": [{"day": _day(now - timedelta(days=i)), "inr": round(by_day[_day(now - timedelta(days=i))]["inr"], 2),
                    "calls": by_day[_day(now - timedelta(days=i))]["calls"]} for i in range(days - 1, -1, -1)],
        "by_feature": sorted(({"feature": f, "inr": round(v["inr"], 2), "calls": v["calls"], "failed": v["failed"],
                               "on": f not in s["ai_off"]} for f, v in by_feature.items()), key=lambda x: -x["inr"]),
        "by_model": sorted(({"model": m, "inr": round(v["inr"], 2), **{k: v[k] for k in ("calls", "input", "output",
                                                                                         "searches")}}
                            for m, v in by_model.items()), key=lambda x: -x["inr"]),
        "top_people": [{"user_id": uid, "email": users.get(uid), "inr": round(v["inr"], 2), "calls": v["calls"]}
                       for uid, v in top],
        "features": [{"feature": f, "on": f not in s["ai_off"]} for f in metering.AI_FEATURES],
    }


@admin_router.get("/system")
async def system(admin: dict = Depends(require_admin)):
    import whatsapp

    db = get_db()
    now = _now()
    since7 = _day(now - timedelta(days=6))
    recent = await db.errors.find({}, {"_id": 0, "at": 1, "method": 1, "route": 1, "status": 1}) \
        .sort("at", -1).to_list(length=30)
    by_route = Counter()
    async for e in db.errors.find({"day": {"$gte": since7}}, {"_id": 0, "method": 1, "route": 1}):
        by_route[f"{e['method']} {e['route']}"] += 1
    nudges_today = Counter()
    async for n in db.nudges.find({"created_at": {"$gte": _day(now)}}, {"_id": 0, "status": 1}):
        nudges_today[n.get("status") or "pending"] += 1
    day_ago = (now - timedelta(hours=24)).isoformat()
    return {
        "errors_recent": recent,
        "errors_7_days_by_route": [{"route": r, "count": c} for r, c in by_route.most_common(10)],
        "nudges_today": dict(nudges_today),
        "push_devices": await db.push_tokens.count_documents({}),
        "whatsapp": {"set_up": whatsapp.configured(), "linked": await db.wa_link.count_documents({}),
                     "paused": await db.wa_opt_out.count_documents({}),
                     "messages_in_24h": await db.wa_inbound.count_documents({"received_at": {"$gte": day_ago}}),
                     "reminder_numbers_24h": len(await whatsapp._template_numbers_today(db, now)),
                     "daily_number_limit": whatsapp.messaging_limit()},
    }


class SettingsUpdate(BaseModel):
    ai_warn_inr: Optional[float] = Field(default=None, ge=0, le=10_000_000)
    ai_stop_inr: Optional[float] = Field(default=None, ge=0, le=10_000_000)
    usd_inr: Optional[float] = Field(default=None, gt=10, lt=1000)
    ai_off: Optional[List[str]] = None
    invite_only: Optional[bool] = None
    beta_cap: Optional[int] = Field(default=None, ge=1, le=1_000_000)
    invites_per_person: Optional[int] = Field(default=None, ge=0, le=1000)
    price_monthly_inr: Optional[int] = Field(default=None, ge=1, le=100000)
    price_yearly_inr: Optional[int] = Field(default=None, ge=1, le=1000000)
    price_founding_yearly_inr: Optional[int] = Field(default=None, ge=1, le=1000000)
    trial_days: Optional[int] = Field(default=None, ge=0, le=90)
    grace_days: Optional[int] = Field(default=None, ge=0, le=30)
    razorpay_plan_monthly: Optional[str] = Field(default=None, max_length=60)
    razorpay_plan_yearly: Optional[str] = Field(default=None, max_length=60)
    razorpay_plan_founding: Optional[str] = Field(default=None, max_length=60)
    premium_only: Optional[List[str]] = None
    limits: Optional[dict] = None


def _with_choices(s: dict) -> dict:
    import plans
    return {**s, "ai_features": metering.AI_FEATURES, "premium_only_choices": PREMIUM_ONLY_CHOICES,
            "limit_names": plans.LIMIT_NAMES}


@admin_router.get("/settings")
async def get_settings(admin: dict = Depends(require_admin)):
    return _with_choices(await metering.get_settings(get_db()))


@admin_router.put("/settings")
async def put_settings(body: SettingsUpdate, admin: dict = Depends(require_admin)):
    db = get_db()
    changes = body.model_dump(exclude_none=True)
    if "ai_off" in changes:
        unknown = set(changes["ai_off"]) - set(metering.AI_FEATURES)
        if unknown:
            raise HTTPException(status_code=400, detail=f"Unknown AI features: {sorted(unknown)}")
    import plans
    if "premium_only" in changes:
        unknown = set(changes["premium_only"]) - set(PREMIUM_ONLY_CHOICES)
        if unknown:
            raise HTTPException(status_code=400, detail=f"Unknown Premium features: {sorted(unknown)}")
    if "limits" in changes:
        clean = {}
        for key, row in changes["limits"].items():
            if key not in plans.default_limits() or not isinstance(row, dict):
                raise HTTPException(status_code=400, detail=f"Unknown limit: {key}")
            vals = {}
            for p in ("free", "premium"):
                v = row.get(p)
                if v is not None and (not isinstance(v, int) or isinstance(v, bool) or v < 0 or v > 100000):
                    raise HTTPException(status_code=400, detail=f"{key}.{p} must be a whole number or empty")
                vals[p] = v
            clean[key] = vals
        changes["limits"] = {**(await metering.get_settings(db))["limits_overrides"], **clean}
    current = await metering.get_settings(db)
    warn = changes.get("ai_warn_inr", current["ai_warn_inr"])
    stop = changes.get("ai_stop_inr", current["ai_stop_inr"])
    if warn > stop:
        raise HTTPException(status_code=400, detail="The warning has to be at or below the stop.")
    saved = await metering.save_settings(db, changes)
    await audit(db, admin, "settings", None, changes)
    return _with_choices(saved)


@admin_router.get("/audit")
async def audit_log(admin: dict = Depends(require_admin)):
    db = get_db()
    emails = {u["id"]: u.get("email") for u in await _users(db)}
    rows = await db.admin_audit.find({}, {"_id": 0}).sort("at", -1).to_list(length=100)
    return [{**r, "target": emails.get(r.get("target_user_id"), r.get("target_user_id"))} for r in rows]


# ---------------------------------------------------------------------------
# Invites
# ---------------------------------------------------------------------------

def _new_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))


def _norm(code: Optional[str]) -> str:
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())


async def _max_uses(db, inv: dict) -> int:
    if inv.get("kind") == "personal":
        return int((await metering.get_settings(db))["invites_per_person"])
    return int(inv.get("max_uses") or 0)


async def find_invite(db, code: Optional[str]) -> Optional[dict]:
    code = _norm(code)
    if not code:
        return None
    inv = await db.invites.find_one({"code": code, "active": True}, {"_id": 0})
    if not inv or inv.get("uses", 0) >= await _max_uses(db, inv):
        return None
    return inv


async def check_signup_invite(db, code: Optional[str]) -> Optional[dict]:
    """At sign-up: the invite (if any). While invite-only, no valid code or a full beta → 403."""
    s = await metering.get_settings(db)
    inv = await find_invite(db, code)
    if s["invite_only"]:
        if not inv:
            raise HTTPException(status_code=403, detail="Hymn is invite-only for now. Ask a friend who uses Hymn "
                                                        "for their invite code.")
        if await db.users.count_documents({}) >= int(s["beta_cap"]):
            raise HTTPException(status_code=403, detail="The beta is full right now. We'll let you know when "
                                                        "there's room.")
    return inv


async def use_invite(db, inv: dict) -> None:
    await db.invites.update_one({"code": inv["code"]}, {"$inc": {"uses": 1}})


async def _personal(db, user: dict) -> dict:
    inv = await db.invites.find_one({"created_by": user["id"], "kind": "personal"}, {"_id": 0})
    if inv:
        return inv
    while True:
        inv = {"code": _new_code(), "kind": "personal", "created_by": user["id"], "cohort": user.get("cohort"),
               "uses": 0, "active": True, "created_at": _now().isoformat()}
        try:
            await db.invites.insert_one(dict(inv))
            return inv
        except Exception:      # a clash with an existing code: try another
            if await db.invites.find_one({"created_by": user["id"], "kind": "personal"}):
                return await db.invites.find_one({"created_by": user["id"], "kind": "personal"}, {"_id": 0})


@invites_router.get("/mine")
async def my_invite(current_user: dict = Depends(get_current_user)):
    db = get_db()
    inv = await _personal(db, current_user)
    s = await metering.get_settings(db)
    left = max(0, int(s["invites_per_person"]) - inv.get("uses", 0))
    base = os.environ.get("HYMN_INVITE_LINK", "").strip()
    return {"code": inv["code"], "used": inv.get("uses", 0), "left": left,
            "link": f"{base}?invite={inv['code']}" if base else None, "invite_only": s["invite_only"]}


@invites_router.get("/check")
async def check_invite(code: str = Query(max_length=40)):
    db = get_db()
    s = await metering.get_settings(db)
    full = s["invite_only"] and await db.users.count_documents({}) >= int(s["beta_cap"])
    return {"valid": bool(await find_invite(db, code)), "invite_only": s["invite_only"], "beta_full": full}


class NewInvites(BaseModel):
    count: int = Field(default=1, ge=1, le=50)
    max_uses: int = Field(default=1, ge=1, le=1000)
    cohort: str = Field(default="", max_length=40)


@admin_router.get("/invites")
async def list_invites(admin: dict = Depends(require_admin)):
    db = get_db()
    emails = {u["id"]: u.get("email") for u in await _users(db)}
    out = []
    for inv in await db.invites.find({}, {"_id": 0}).sort("created_at", -1).to_list(length=1000):
        out.append({"code": inv["code"], "kind": inv.get("kind"), "cohort": inv.get("cohort"),
                    "uses": inv.get("uses", 0), "max_uses": await _max_uses(db, inv), "active": inv.get("active"),
                    "from": "admin" if inv.get("created_by") == "admin" else emails.get(inv.get("created_by")),
                    "created_at": inv.get("created_at")})
    return out


@admin_router.post("/invites")
async def create_invites(body: NewInvites, admin: dict = Depends(require_admin)):
    db = get_db()
    codes = []
    while len(codes) < body.count:
        inv = {"code": _new_code(), "kind": "admin", "created_by": "admin", "cohort": body.cohort.strip() or None,
               "uses": 0, "max_uses": body.max_uses, "active": True, "created_at": _now().isoformat()}
        try:
            await db.invites.insert_one(dict(inv))
            codes.append(inv["code"])
        except Exception:
            continue
    await audit(db, admin, "create_invites", None, {"count": body.count, "cohort": body.cohort})
    return {"codes": codes}


@admin_router.post("/invites/{code}/off")
async def invite_off(code: str, admin: dict = Depends(require_admin)):
    db = get_db()
    r = await db.invites.update_one({"code": _norm(code)}, {"$set": {"active": False}})
    if not r.matched_count:
        raise HTTPException(status_code=404, detail="No such code")
    await audit(db, admin, "invite_off", None, {"code": _norm(code)})
    return {"code": _norm(code), "active": False}


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------

_PAGE = Path(__file__).resolve().parent / "admin_ui" / "index.html"
_CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; "
        "img-src data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")


@admin_page_router.get("/admin", include_in_schema=False)
async def admin_page():
    return FileResponse(_PAGE, media_type="text/html", headers={
        "Content-Security-Policy": _CSP, "Cache-Control": "no-store", "X-Robots-Tag": "noindex"})


async def ensure_admin_indexes(db) -> None:
    await db.invites.create_index("code", unique=True)
    await db.invites.create_index([("created_by", 1), ("kind", 1)])
    await db.admin_audit.create_index("at")
