"""Checklists for big life events: what must go right, what may stop it.

A template gives the planner a reviewed starting point instead of
improvising. It is data, not AI output: requirements and risks across all
areas, each with where it comes from. The AI personalises it (amounts,
dates) and may add to it, labelled as its own suggestion.

**Review gate.** Every template here is a *draft* until a person signs it
off (a doctor for health, a financial planner for money). Drafts are only
shown to the people listed in ``HYMN_TEMPLATE_PREVIEW_EMAILS``; reviewed
keys are listed in ``HYMN_REVIEWED_TEMPLATES`` (e.g. "house,wedding").
Nothing here is medical or investment advice.
"""
from __future__ import annotations

import os
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

from deps import get_current_user

plan_templates_router = APIRouter(prefix="/plan-templates", tags=["plan-templates"])


def _d(v: Any, default: str) -> Decimal:
    try:
        return Decimal(str(v)) if v not in (None, "") else Decimal(default)
    except InvalidOperation:
        return Decimal(default)


def _r(n: Decimal) -> str:
    return format(n.quantize(Decimal("1")), "f")


def house(p: dict) -> dict:
    price = _d(p.get("price"), "9000000")
    # RBI caps how much of a home's value a bank may lend (loan-to-value).
    ltv = Decimal("0.90") if price <= 3000000 else Decimal("0.80") if price <= 7500000 else Decimal("0.75")
    down = price * (1 - ltv)
    duty = price * _d(p.get("stamp_duty_percent"), "7") / 100
    interiors = _d(p.get("interiors"), "500000")
    return {
        "requirements": [
            {"area": "money", "kind": "money", "what": "Down payment (the part the bank won't lend)",
             "amount": _r(down), "source": "RBI loan-to-value limits: up to 90% (≤₹30L), 80% (₹30–75L), "
                                           "75% (above ₹75L) — RBI Master Circular, Housing Finance"},
            {"area": "money", "kind": "money", "what": "Stamp duty and registration",
             "amount": _r(duty), "source": "Varies by state, often 6–8% together; check your state's rates"},
            {"area": "money", "kind": "money", "what": "Interiors, furniture and moving", "amount": _r(interiors),
             "source": "Your estimate"},
            {"area": "money", "kind": "condition", "what": "All EMIs together stay under about half of take-home pay",
             "source": "Common bank lending practice (fixed obligations to income)"},
            {"area": "money", "kind": "condition", "what": "Credit score around 750 or more",
             "source": "Common bank lending practice"},
            {"area": "work", "kind": "condition", "what": "Stable job (banks usually look for about 2 years)",
             "source": "Common bank lending practice"},
            {"area": "family", "kind": "condition", "what": "Partner and family agree on area, size and budget",
             "source": "Hymn checklist"},
            {"area": "time", "kind": "time", "what": "Weekends for visits and paperwork", "amount": 600,
             "min_block": 180, "weekdays": ["saturday", "sunday"], "source": "Hymn checklist (about 10 hours)"},
        ],
        "risks": [
            {"area": "work", "what": "Changing jobs just before the loan", "likelihood": "medium",
             "early_warning": "Job change mentioned or new salary account", "mitigation": "Get the loan sanctioned first"},
            {"area": "money", "what": "Interest rates rise", "likelihood": "medium",
             "early_warning": "Bank rate changes", "mitigation": "Check the EMI at 1–2% higher before committing"},
            {"area": "money", "what": "Prices rise before you buy", "likelihood": "medium",
             "early_warning": "Shortlisted homes cost more on re-check", "mitigation": "Re-check prices every 6 months"},
            {"area": "health", "what": "A medical emergency uses up the fund", "likelihood": "low",
             "early_warning": "No health insurance on file", "mitigation": "Get health cover before saving hard"},
            {"area": "money", "what": "Under-construction delays", "likelihood": "medium",
             "early_warning": "Project not on the state's RERA site", "mitigation": "Only consider RERA-registered projects"},
        ],
    }


def wedding(p: dict) -> dict:
    budget = _d(p.get("budget"), "2500000")
    family_share = _d(p.get("family_contribution"), "0")
    return {
        "requirements": [
            {"area": "money", "kind": "money", "what": "Your share of the wedding budget",
             "amount": _r(max(budget - family_share, Decimal(0))), "source": "Your budget minus family contribution"},
            {"area": "money", "kind": "money", "what": "Buffer for overruns (about 20%)",
             "amount": _r(budget * Decimal("0.2")), "source": "Hymn checklist: weddings usually run over"},
            {"area": "family", "kind": "condition", "what": "Both families agree on budget, guest list and who pays",
             "source": "Hymn checklist"},
            {"area": "money", "kind": "condition", "what": "Venue booked 6–12 months ahead",
             "source": "Hymn checklist (popular dates fill early)"},
            {"area": "work", "kind": "condition", "what": "Leave approved for the wedding and after", "source": "Hymn checklist"},
            {"area": "time", "kind": "time", "what": "Planning time with your partner", "amount": 480,
             "min_block": 60, "source": "Hymn checklist (about 8 hours)"},
        ],
        "risks": [
            {"area": "money", "what": "Borrowing to pay for the wedding", "likelihood": "medium",
             "early_warning": "Savings behind plan 3 months out", "mitigation": "Trim the guest list or scale early"},
            {"area": "family", "what": "Disagreement on scale or spending", "likelihood": "medium",
             "early_warning": "Budget not agreed by both families", "mitigation": "Agree the budget in writing first"},
        ],
    }


def first_child(p: dict) -> dict:
    delivery = _d(p.get("delivery_cost"), "200000")
    monthly = _d(p.get("monthly_child_cost"), "15000")
    return {
        "requirements": [
            {"area": "health", "kind": "condition",
             "what": "Pre-pregnancy check-up for both partners, a few months before trying",
             "source": "Ask your doctor; DRAFT pending a doctor's review"},
            {"area": "health", "kind": "condition",
             "what": "Ask your doctor about folic acid and vaccinations before trying",
             "source": "WHO: periconceptional folic acid; DRAFT pending a doctor's review"},
            {"area": "money", "kind": "condition",
             "what": "Health insurance with maternity cover, bought early enough to pass its waiting period",
             "source": "Maternity waiting periods are often 2–4 years; check the policy wording"},
            {"area": "money", "kind": "money", "what": "Delivery and hospital costs not covered by insurance",
             "amount": _r(delivery), "source": "Your estimate; varies by city and hospital"},
            {"area": "money", "kind": "money", "what": "First 6 months of child costs", "amount": _r(monthly * 6),
             "source": "Your monthly estimate × 6"},
            {"area": "work", "kind": "condition", "what": "Know your maternity / paternity leave and pay",
             "source": "Maternity Benefit (Amendment) Act 2017: 26 weeks for the first two children; "
                       "paternity leave is company policy"},
            {"area": "family", "kind": "condition", "what": "Partner aligned, and help with childcare arranged",
             "source": "Hymn checklist"},
            {"area": "learning", "kind": "condition", "what": "Childbirth / parenting classes chosen", "source": "Hymn checklist"},
        ],
        "risks": [
            {"area": "health", "what": "It takes longer than planned", "likelihood": "medium",
             "early_warning": "Trying for a year (6 months if over 35) without success",
             "mitigation": "See a doctor at that point; DRAFT pending a doctor's review"},
            {"area": "money", "what": "Maternity costs fall inside the insurance waiting period", "likelihood": "medium",
             "early_warning": "No maternity cover on file", "mitigation": "Buy cover now"},
            {"area": "money", "what": "Income dips during leave", "likelihood": "high",
             "early_warning": "Emergency fund under 6 months of costs", "mitigation": "Build the fund before"},
        ],
    }


TEMPLATES = {
    "house": {"title": "Buy a house", "fill": house, "params": ["price", "stamp_duty_percent", "interiors"]},
    "wedding": {"title": "Wedding", "fill": wedding, "params": ["budget", "family_contribution"]},
    "first_child": {"title": "First child", "fill": first_child, "params": ["delivery_cost", "monthly_child_cost"]},
}


def reviewed(key: str) -> bool:
    return key in {k.strip() for k in os.environ.get("HYMN_REVIEWED_TEMPLATES", "").split(",") if k.strip()}


def visible_to(user: dict, key: str) -> bool:
    preview = {e.strip().lower() for e in os.environ.get("HYMN_TEMPLATE_PREVIEW_EMAILS", "").split(",") if e.strip()}
    return reviewed(key) or (user.get("email") or "").lower() in preview


def fill(user: dict, key: str, params: Optional[dict] = None) -> Optional[dict]:
    if key not in TEMPLATES or not visible_to(user, key):
        return None
    t = TEMPLATES[key]
    out = t["fill"](params or {})
    return {"key": key, "title": t["title"], "reviewed": reviewed(key), **out}


def available(user: dict) -> List[Dict[str, Any]]:
    return [{"key": k, "title": t["title"], "params": t["params"], "reviewed": reviewed(k)}
            for k, t in TEMPLATES.items() if visible_to(user, k)]


@plan_templates_router.get("")
async def list_templates(current_user: dict = Depends(get_current_user)):
    return available(current_user)


@plan_templates_router.post("/{key}")
async def fill_template(key: str, params: Dict[str, Any], current_user: dict = Depends(get_current_user)):
    out = fill(current_user, key, params)
    if out is None:
        raise HTTPException(status_code=404, detail="No such checklist")
    return out
