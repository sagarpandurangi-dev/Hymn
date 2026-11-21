"""Premium: trials, the beta pass, promo codes and paid subscriptions.

Everything ends in one place: ``refresh`` works out ``users.premium_until`` (and
``premium_source``) as the latest of
- the 14-day trial every new person gets (``trial_until``; ``trial_days`` in settings),
- the beta pass (``beta_until``: people who sign up before ``beta_premium_until``,
  who are also "founding members" with a lower first-year price),
- promo codes (``promo_until``: free Premium days),
- paid subscriptions (``subscriptions``: access until the paid period ends; after a
  failed payment, ``grace_days`` more while the payment is retried).
``plans.user_plan`` then only compares a date. A manual choice on the admin page
(``users.plan``) still wins over all of this.

Payments:
- Website: Razorpay subscriptions (UPI AutoPay, cards). ``POST /api/billing/checkout``
  creates one (keys in Railway: RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET); Razorpay's
  webhook (RAZORPAY_WEBHOOK_SECRET, signature checked) keeps it up to date.
  Razorpay issues the invoices.
- Google Play and the App Store: through RevenueCat (its webhook, with
  REVENUECAT_WEBHOOK_AUTH as the Authorization header). The app identifies the
  person to RevenueCat by their Hymn user id.
Nothing is charged until those keys exist; until then checkout answers "not set up yet".
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import math
import os
import re
import secrets
import uuid
from datetime import datetime, time, timedelta, timezone
from typing import Optional

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

import metering
import plans
from deps import get_current_user, get_db

logger = logging.getLogger(__name__)

billing_router = APIRouter(prefix="/billing", tags=["billing"])
billing_admin_router = APIRouter(prefix="/admin/billing", tags=["admin"])

ACCESS_STATUSES = ("active", "grace", "cancelling")
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.astimezone(timezone.utc).isoformat() if dt else None


def _parse(ts) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts) if isinstance(ts, str) else ts
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _from_unix(sec) -> Optional[datetime]:
    try:
        return datetime.fromtimestamp(int(sec), timezone.utc) if sec else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Working out Premium
# ---------------------------------------------------------------------------

async def refresh(db, user_id: str, now: Optional[datetime] = None) -> dict:
    """Recompute premium_until / premium_source from trial, beta, promos and subscriptions."""
    now = now or _now()
    user = await db.users.find_one({"id": user_id}, {"_id": 0}) or {}
    best: tuple = (None, None)

    def consider(until, source):
        nonlocal best
        dt = _parse(until)
        if dt and (best[0] is None or dt > best[0]):
            best = (dt, source)

    consider(user.get("trial_until"), "trial")
    consider(user.get("beta_until"), "beta")
    consider(user.get("promo_until"), "promo")
    async for sub in db.subscriptions.find({"user_id": user_id, "status": {"$in": list(ACCESS_STATUSES)}}, {"_id": 0}):
        consider(sub.get("access_until"), "subscription")
    until, source = best
    await db.users.update_one({"id": user_id}, {"$set": {"premium_until": _iso(until), "premium_source": source}})
    return {"premium_until": _iso(until), "premium_source": source}


async def on_signup(db, user: dict, now: Optional[datetime] = None) -> None:
    """New people get the trial; before the beta date they also get the beta pass and founding price."""
    now = now or _now()
    s = await metering.get_settings(db)
    upd = {}
    if int(s.get("trial_days") or 0) > 0:
        upd["trial_until"] = _iso(now + timedelta(days=int(s["trial_days"])))
    beta = s.get("beta_premium_until")
    if beta:
        try:
            end = datetime.combine(datetime.fromisoformat(beta).date(), time(23, 59, 59), tzinfo=timezone.utc)
        except ValueError:
            end = None
        if end and now <= end:
            upd.update({"beta_until": _iso(end), "founding_member": True})
    if upd:
        await db.users.update_one({"id": user["id"]}, {"$set": upd})
    await refresh(db, user["id"], now)


# ---------------------------------------------------------------------------
# Subscription records
# ---------------------------------------------------------------------------

async def _event_seen(db, provider: str, event_id: Optional[str], kind: str, user_id: Optional[str], now) -> bool:
    """Store the event once; True when it was already handled (webhooks are retried)."""
    if not event_id:
        event_id = f"noid-{uuid.uuid4()}"
    try:
        await db.billing_events.insert_one({"provider": provider, "event_id": event_id, "type": kind,
                                            "user_id": user_id, "at": _iso(now)})
        return False
    except DuplicateKeyError:
        return True


async def _upsert_sub(db, provider: str, ref: str, user_id: str, fields: dict, now) -> dict:
    await db.subscriptions.update_one(
        {"provider": provider, "provider_ref": ref},
        {"$set": {**fields, "user_id": user_id, "updated_at": _iso(now)},
         "$setOnInsert": {"id": str(uuid.uuid4()), "created_at": _iso(now)}}, upsert=True)
    await refresh(db, user_id, now)
    return await db.subscriptions.find_one({"provider": provider, "provider_ref": ref}, {"_id": 0})


async def _plan_kind(db, plan_id: str) -> str:
    s = await metering.get_settings(db)
    for kind in ("monthly", "yearly", "founding"):
        if plan_id and plan_id == s.get(f"razorpay_plan_{kind}"):
            return kind
    return "unknown"


# ---------------------------------------------------------------------------
# Razorpay (website)
# ---------------------------------------------------------------------------

def razorpay_ready() -> bool:
    return bool(os.environ.get("RAZORPAY_KEY_ID") and os.environ.get("RAZORPAY_KEY_SECRET"))


def razorpay_request(method: str, path: str, body: Optional[dict] = None) -> dict:
    """Call Razorpay's API (tests replace this)."""
    r = requests.request(method, f"https://api.razorpay.com/v1{path}", json=body, timeout=20,
                         auth=(os.environ.get("RAZORPAY_KEY_ID", ""), os.environ.get("RAZORPAY_KEY_SECRET", "")))
    r.raise_for_status()
    return r.json()


RAZORPAY_STATUS = {          # Razorpay subscription status → ours
    "created": "pending", "authenticated": "pending", "active": "active", "pending": "grace",
    "halted": "expired", "cancelled": "cancelled", "completed": "expired", "expired": "expired",
    "paused": "paused", "resumed": "active",
}


async def handle_razorpay(db, event: dict, event_id: Optional[str], now: Optional[datetime] = None) -> str:
    now = now or _now()
    kind = event.get("event") or ""
    sub = ((event.get("payload") or {}).get("subscription") or {}).get("entity") or {}
    if not sub.get("id"):
        return "ignored"
    existing = await db.subscriptions.find_one({"provider": "razorpay", "provider_ref": sub["id"]}, {"_id": 0})
    user_id = ((sub.get("notes") or {}).get("user_id")) or (existing or {}).get("user_id")
    if not user_id or not await db.users.find_one({"id": user_id}, {"_id": 1}):
        logger.warning("billing: razorpay event for an unknown person")
        return "unknown_user"
    if await _event_seen(db, "razorpay", event_id, kind, user_id, now):
        return "duplicate"
    s = await metering.get_settings(db)
    status = RAZORPAY_STATUS.get(sub.get("status") or "", "pending")
    period_end = _from_unix(sub.get("current_end"))
    fields = {"plan": await _plan_kind(db, sub.get("plan_id") or ""), "plan_ref": sub.get("plan_id"),
              "current_period_end": _iso(period_end), "last_event": kind}
    payment = ((event.get("payload") or {}).get("payment") or {}).get("entity") or {}
    if payment.get("amount"):
        fields["last_amount_inr"] = round(int(payment["amount"]) / 100, 2)
    if status == "active":
        fields.update(status="active", access_until=_iso(period_end), cancel_at_period_end=False)
    elif status == "grace":
        fields.update(status="grace", access_until=_iso(max(filter(None, [
            period_end, now + timedelta(days=int(s["grace_days"]))]))))
    elif status == "cancelled":
        # Cancelled: Premium stays until the end of what was paid for.
        if period_end and period_end > now:
            fields.update(status="cancelling", access_until=_iso(period_end), cancel_at_period_end=True)
        else:
            fields.update(status="cancelled", access_until=_iso(now))
    elif status in ("expired", "paused"):
        fields.update(status=status, access_until=_iso(now))
    else:
        fields.update(status="pending")
    await _upsert_sub(db, "razorpay", sub["id"], user_id, fields, now)
    return fields["status"]


# ---------------------------------------------------------------------------
# RevenueCat (Google Play, App Store)
# ---------------------------------------------------------------------------

async def handle_revenuecat(db, event: dict, now: Optional[datetime] = None) -> str:
    now = now or _now()
    kind = event.get("type") or ""
    if kind == "TEST":
        return "test"
    user_id = event.get("app_user_id")
    if not user_id or not await db.users.find_one({"id": user_id}, {"_id": 1}):
        logger.warning("billing: revenuecat event for an unknown person")
        return "unknown_user"
    if await _event_seen(db, "revenuecat", event.get("id"), kind, user_id, now):
        return "duplicate"
    s = await metering.get_settings(db)
    ref = str(event.get("original_transaction_id") or f"{user_id}:{event.get('product_id')}")
    expires = datetime.fromtimestamp(int(event["expiration_at_ms"]) / 1000, timezone.utc) \
        if event.get("expiration_at_ms") else None
    product = (event.get("product_id") or "").lower()
    fields = {"plan": "yearly" if ("year" in product or "annual" in product) else "monthly",
              "plan_ref": event.get("product_id"), "store": event.get("store"),
              "current_period_end": _iso(expires), "last_event": kind,
              "sandbox": event.get("environment") == "SANDBOX"}
    if event.get("price_in_purchased_currency") is not None and event.get("currency") == "INR":
        fields["last_amount_inr"] = float(event["price_in_purchased_currency"])
    if kind in ("INITIAL_PURCHASE", "RENEWAL", "UNCANCELLATION", "PRODUCT_CHANGE", "NON_RENEWING_PURCHASE",
                "SUBSCRIPTION_EXTENDED", "TRANSFER"):
        fields.update(status="active", access_until=_iso(expires), cancel_at_period_end=False)
    elif kind == "CANCELLATION":
        fields.update(status="cancelling" if expires and expires > now else "cancelled",
                      access_until=_iso(expires or now), cancel_at_period_end=True)
    elif kind == "BILLING_ISSUE":
        grace = event.get("grace_period_expiration_at_ms")
        until = datetime.fromtimestamp(int(grace) / 1000, timezone.utc) if grace \
            else now + timedelta(days=int(s["grace_days"]))
        fields.update(status="grace", access_until=_iso(max(filter(None, [expires, until]))))
    elif kind in ("EXPIRATION", "SUBSCRIPTION_PAUSED"):
        fields.update(status="expired" if kind == "EXPIRATION" else "paused", access_until=_iso(now))
    else:
        return "ignored"
    await _upsert_sub(db, "revenuecat", ref, user_id, fields, now)
    return fields["status"]


# ---------------------------------------------------------------------------
# The app's side
# ---------------------------------------------------------------------------

def _feature_table(s: dict) -> dict:
    return {"premium_only": s["premium_only"],
            "limits": [{"key": k, "name": plans.LIMIT_NAMES.get(k, k), "free": v.get("free"),
                        "premium": v.get("premium")} for k, v in s["limits"].items()]}


@billing_router.get("/plans")
async def public_plans():
    """Prices and what Premium includes (for the paywall and the website; no sign-in needed)."""
    s = await metering.get_settings(get_db())
    return {"currency": "INR", "monthly": s["price_monthly_inr"], "yearly": s["price_yearly_inr"],
            "founding_yearly": s["price_founding_yearly_inr"], "trial_days": s["trial_days"],
            **_feature_table(s)}


async def _active_sub(db, user_id: str) -> Optional[dict]:
    subs = await db.subscriptions.find({"user_id": user_id, "status": {"$in": list(ACCESS_STATUSES)}},
                                       {"_id": 0}).sort("access_until", -1).to_list(length=5)
    return subs[0] if subs else None


@billing_router.get("")
async def my_billing(current_user: dict = Depends(get_current_user)):
    db = get_db()
    now = _now()
    s = await metering.get_settings(db)
    user = await db.users.find_one({"id": current_user["id"]}, {"_id": 0})
    sub = await _active_sub(db, user["id"])
    trial_end = _parse(user.get("trial_until"))
    in_trial = user.get("premium_source") == "trial" and trial_end is not None and trial_end > now
    return {
        "plan": plans.user_plan(user), "premium_until": user.get("premium_until"),
        "source": "manual" if user.get("plan") else user.get("premium_source"),
        "in_trial": in_trial,
        "trial_days_left": math.ceil((trial_end - now).total_seconds() / 86400) if in_trial else 0,
        "founding_member": bool(user.get("founding_member")),
        "subscription": {"provider": sub["provider"], "plan": sub.get("plan"), "status": sub["status"],
                         "renews_on": None if sub.get("cancel_at_period_end") else sub.get("current_period_end"),
                         "ends_on": sub.get("current_period_end") if sub.get("cancel_at_period_end") else None,
                         "store": sub.get("store")} if sub else None,
        "prices": {"monthly": s["price_monthly_inr"], "yearly": s["price_yearly_inr"],
                   "founding_yearly": s["price_founding_yearly_inr"] if user.get("founding_member") else None},
        "can_buy_on_web": razorpay_ready(),
        "limits": {k: plans.limit(user, k) for k in s["limits"]},
    }


class Checkout(BaseModel):
    plan: str = Field(pattern="^(monthly|yearly)$")


@billing_router.post("/checkout")
async def checkout(body: Checkout, current_user: dict = Depends(get_current_user)):
    db = get_db()
    s = await metering.get_settings(db)
    kind = body.plan
    if kind == "yearly" and current_user.get("founding_member") and s.get("razorpay_plan_founding"):
        kind = "founding"
    plan_id = s.get(f"razorpay_plan_{kind}")
    if not razorpay_ready() or not plan_id:
        raise HTTPException(status_code=503, detail="Payments aren't set up yet.")
    if await db.subscriptions.find_one({"user_id": current_user["id"], "status": {"$in": ["active", "grace"]}}):
        raise HTTPException(status_code=409, detail="You already have Premium.")
    try:
        sub = await asyncio.to_thread(razorpay_request, "POST", "/subscriptions", {
            "plan_id": plan_id, "total_count": 120 if kind == "monthly" else 10, "customer_notify": 1,
            "notes": {"user_id": current_user["id"]}})
    except (requests.RequestException, ValueError) as exc:
        logger.warning("billing: razorpay checkout failed: %s", exc)
        raise HTTPException(status_code=502, detail="The payment page couldn't be opened. Please try again.")
    now = _now()
    await db.subscriptions.update_one(
        {"provider": "razorpay", "provider_ref": sub["id"]},
        {"$set": {"user_id": current_user["id"], "status": "pending", "plan": kind, "plan_ref": plan_id,
                  "updated_at": _iso(now)}, "$setOnInsert": {"id": str(uuid.uuid4()), "created_at": _iso(now)}},
        upsert=True)
    price = {"monthly": s["price_monthly_inr"], "yearly": s["price_yearly_inr"],
             "founding": s["price_founding_yearly_inr"]}[kind]
    return {"subscription_id": sub["id"], "key_id": os.environ.get("RAZORPAY_KEY_ID"),
            "short_url": sub.get("short_url"), "plan": kind, "amount_inr": price}


@billing_router.post("/cancel")
async def cancel(current_user: dict = Depends(get_current_user)):
    db = get_db()
    sub = await _active_sub(db, current_user["id"])
    if not sub:
        raise HTTPException(status_code=404, detail="You don't have a subscription to cancel.")
    if sub["provider"] != "razorpay":
        where = "the App Store" if sub.get("store") == "APP_STORE" else "Google Play"
        raise HTTPException(status_code=409, detail=f"This subscription was bought in {where}; cancel it there "
                                                    "(Subscriptions in the store app).")
    if sub.get("cancel_at_period_end"):
        return {"detail": "Already cancelled.", "ends_on": sub.get("current_period_end")}
    try:
        await asyncio.to_thread(razorpay_request, "POST", f"/subscriptions/{sub['provider_ref']}/cancel",
                                {"cancel_at_cycle_end": 1})
    except (requests.RequestException, ValueError) as exc:
        logger.warning("billing: razorpay cancel failed: %s", exc)
        raise HTTPException(status_code=502, detail="Couldn't cancel right now. Please try again.")
    await db.subscriptions.update_one({"provider": "razorpay", "provider_ref": sub["provider_ref"]},
                                      {"$set": {"cancel_at_period_end": True, "status": "cancelling",
                                                "updated_at": _iso(_now())}})
    return {"detail": "Cancelled. Premium stays until the end of the period you paid for.",
            "ends_on": sub.get("current_period_end")}


class Redeem(BaseModel):
    code: str = Field(min_length=3, max_length=40)


def _norm(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())


@billing_router.post("/redeem")
async def redeem(body: Redeem, current_user: dict = Depends(get_current_user)):
    db = get_db()
    now = _now()
    code = _norm(body.code)
    promo = await db.promo_codes.find_one({"code": code, "active": True}, {"_id": 0})
    if not promo or promo.get("uses", 0) >= promo.get("max_uses", 1) or \
            (promo.get("expires") and _parse(promo["expires"]) < now):
        raise HTTPException(status_code=400, detail="That code isn't valid.")
    try:
        await db.promo_redemptions.insert_one({"code": code, "user_id": current_user["id"], "at": _iso(now)})
    except DuplicateKeyError:
        raise HTTPException(status_code=400, detail="You've already used that code.")
    r = await db.promo_codes.update_one({"code": code, "uses": {"$lt": promo.get("max_uses", 1)}},
                                        {"$inc": {"uses": 1}})
    if not r.modified_count:
        await db.promo_redemptions.delete_one({"code": code, "user_id": current_user["id"]})
        raise HTTPException(status_code=400, detail="That code isn't valid.")
    user = await db.users.find_one({"id": current_user["id"]}, {"_id": 0})
    start = max(filter(None, [now, _parse(user.get("promo_until"))]))
    await db.users.update_one({"id": user["id"]},
                              {"$set": {"promo_until": _iso(start + timedelta(days=int(promo["days"])))}})
    state = await refresh(db, user["id"], now)
    return {"detail": f"{promo['days']} days of Premium added.", **state}


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------

@billing_router.post("/webhooks/razorpay")
async def razorpay_webhook(request: Request):
    secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(status_code=404, detail="Not set up")
    raw = await request.body()
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(request.headers.get("X-Razorpay-Signature", "").encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Bad signature")
    try:
        event = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Not JSON")
    result = await handle_razorpay(get_db(), event, request.headers.get("X-Razorpay-Event-Id"))
    return {"ok": True, "result": result}


@billing_router.post("/webhooks/revenuecat")
async def revenuecat_webhook(request: Request):
    expected = os.environ.get("REVENUECAT_WEBHOOK_AUTH", "")
    if not expected:
        raise HTTPException(status_code=404, detail="Not set up")
    if not hmac.compare_digest(request.headers.get("Authorization", "").encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Bad authorization")
    try:
        body = json.loads(await request.body())
    except ValueError:
        raise HTTPException(status_code=400, detail="Not JSON")
    result = await handle_revenuecat(get_db(), body.get("event") or {})
    return {"ok": True, "result": result}


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

def _require_admin():
    from admin import require_admin
    return require_admin


@billing_admin_router.get("")
async def admin_billing(admin: dict = Depends(_require_admin())):
    db = get_db()
    now = _now()
    s = await metering.get_settings(db)
    subs = await db.subscriptions.find({}, {"_id": 0}).to_list(length=None)
    live = [x for x in subs if x.get("status") in ACCESS_STATUSES and not x.get("sandbox")]
    monthly_value = 0.0
    for x in live:
        if x.get("status") == "cancelling":
            continue
        price = x.get("last_amount_inr") or {"monthly": s["price_monthly_inr"], "yearly": s["price_yearly_inr"],
                                             "founding": s["price_founding_yearly_inr"]}.get(x.get("plan"), 0)
        monthly_value += price if x.get("plan") == "monthly" else price / 12
    since = _iso(now - timedelta(days=30))
    users = await db.users.find({}, {"_id": 0, "id": 1, "email": 1, "trial_until": 1, "premium_source": 1,
                                     "premium_until": 1, "founding_member": 1, "plan": 1}).to_list(length=None)
    emails = {u["id"]: u.get("email") for u in users}
    events = await db.billing_events.find({}, {"_id": 0}).sort("at", -1).to_list(length=30)
    promos = await db.promo_codes.find({}, {"_id": 0}).sort("created_at", -1).to_list(length=200)
    by = {}
    for x in live:
        key = f"{x.get('provider')}:{x.get('plan')}"
        by[key] = by.get(key, 0) + 1
    return {
        "subscribers": len([x for x in live if x["status"] != "cancelling"]),
        "monthly_revenue_inr": round(monthly_value),
        "by_provider_plan": [{"key": k, "count": v} for k, v in sorted(by.items())],
        "in_grace": len([x for x in live if x["status"] == "grace"]),
        "cancelling": len([x for x in live if x["status"] == "cancelling"]),
        "new_30_days": len([x for x in subs if (x.get("created_at") or "") >= since and x.get("status") != "pending"]),
        "ended_30_days": len([x for x in subs if x.get("status") in ("cancelled", "expired")
                              and (x.get("updated_at") or "") >= since]),
        "on_trial": len([u for u in users if u.get("premium_source") == "trial" and plans.premium_until_active(u)]),
        "on_beta_pass": len([u for u in users if u.get("premium_source") == "beta" and plans.premium_until_active(u)]),
        "founding_members": len([u for u in users if u.get("founding_member")]),
        "premium_now": len([u for u in users if plans.user_plan(u) == "premium"]),
        "events": [{**e, "email": emails.get(e.get("user_id"))} for e in events],
        "promos": promos,
        "payments_ready": {"razorpay": razorpay_ready(), "razorpay_webhook": bool(os.environ.get(
            "RAZORPAY_WEBHOOK_SECRET")), "revenuecat": bool(os.environ.get("REVENUECAT_WEBHOOK_AUTH"))},
    }


class NewPromos(BaseModel):
    days: int = Field(ge=1, le=365)
    count: int = Field(default=1, ge=1, le=50)
    max_uses: int = Field(default=1, ge=1, le=10000)
    expires_days: Optional[int] = Field(default=None, ge=1, le=730)


@billing_admin_router.post("/promos")
async def make_promos(body: NewPromos, admin: dict = Depends(_require_admin())):
    from admin import audit
    db = get_db()
    now = _now()
    codes = []
    while len(codes) < body.count:
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
        try:
            await db.promo_codes.insert_one({"code": code, "days": body.days, "max_uses": body.max_uses, "uses": 0,
                                             "active": True, "created_at": _iso(now), "expires": _iso(
                                                 now + timedelta(days=body.expires_days)) if body.expires_days else None})
            codes.append(code)
        except DuplicateKeyError:
            continue
    await audit(db, admin, "create_promos", None, {"count": body.count, "days": body.days})
    return {"codes": codes}


@billing_admin_router.post("/promos/{code}/off")
async def promo_off(code: str, admin: dict = Depends(_require_admin())):
    from admin import audit
    db = get_db()
    r = await db.promo_codes.update_one({"code": _norm(code)}, {"$set": {"active": False}})
    if not r.matched_count:
        raise HTTPException(status_code=404, detail="No such code")
    await audit(db, admin, "promo_off", None, {"code": _norm(code)})
    return {"code": _norm(code), "active": False}


class BetaPass(BaseModel):
    until: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    apply_to_everyone_now: bool = False


@billing_admin_router.post("/beta")
async def beta_pass(body: BetaPass, admin: dict = Depends(_require_admin())):
    """Premium for testers until a date. New sign-ups before it get it (and the founding price); optionally
    everyone already signed up too."""
    from admin import audit
    db = get_db()
    await metering.save_settings(db, {"beta_premium_until": body.until})
    applied = 0
    if body.until and body.apply_to_everyone_now:
        end = _iso(datetime.combine(datetime.fromisoformat(body.until).date(), time(23, 59, 59), tzinfo=timezone.utc))
        async for u in db.users.find({}, {"_id": 0, "id": 1}):
            await db.users.update_one({"id": u["id"]}, {"$set": {"beta_until": end, "founding_member": True}})
            await refresh(db, u["id"])
            applied += 1
    await audit(db, admin, "beta_pass", None, {"until": body.until, "applied_to": applied})
    return {"beta_premium_until": body.until, "applied_to": applied}


async def cancel_on_delete(db, user_id: str) -> None:
    """Deleting an account stops its website subscription (store ones must be cancelled in the store)."""
    async for sub in db.subscriptions.find({"user_id": user_id, "provider": "razorpay",
                                            "status": {"$in": ["active", "grace", "pending"]}}, {"_id": 0}):
        try:
            await asyncio.to_thread(razorpay_request, "POST", f"/subscriptions/{sub['provider_ref']}/cancel",
                                    {"cancel_at_cycle_end": 0})
        except Exception as exc:
            logger.warning("billing: couldn't cancel a subscription for a deleted account: %s", exc)


async def ensure_billing_indexes(db) -> None:
    await db.subscriptions.create_index([("provider", 1), ("provider_ref", 1)], unique=True)
    await db.subscriptions.create_index([("user_id", 1), ("status", 1)])
    await db.billing_events.create_index([("provider", 1), ("event_id", 1)], unique=True)
    await db.promo_codes.create_index("code", unique=True)
    await db.promo_redemptions.create_index([("code", 1), ("user_id", 1)], unique=True)
