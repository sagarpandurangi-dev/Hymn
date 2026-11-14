"""One call per screen: everything a screen shows, in a single round trip.

The phone pays for each request it makes; a screen that needs four answers
should ask once. These endpoints bundle what the screens read today, and
reuse the per-request memo so the bundle costs about as much as its largest
part.
"""
from __future__ import annotations

from datetime import date as date_type

from fastapi import APIRouter, Depends

import planned_money
from deps import get_current_user, get_db

screens_router = APIRouter(prefix="/screens", tags=["screens"])


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
    return {"dashboard": dashboard, "planned_upcoming": [planned_money.public(i) for i in upcoming],
            "planned_this_month": totals}
