"""Words and numbers the way a person says them (the design guide: docs/DESIGN.md).

- Money: ₹12,450 (Indian grouping), ₹1.84 L, ₹2.5 Cr; no ".00"; other currencies
  keep their code ("USD 1,250").
- Days: "Today", "Tomorrow", "Yesterday", a weekday within the coming week
  ("Tuesday"), else "24 Nov", with the year only when it isn't this year.
- Durations: "45 min", "3h", "3h 20m".
"""
from __future__ import annotations

from datetime import date as date_type
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Optional, Union

Number = Union[int, float, str, Decimal, None]


def _dec(v: Number) -> Optional[Decimal]:
    try:
        return Decimal(str(v)) if v is not None and str(v).strip() != "" else None
    except (InvalidOperation, ValueError):
        return None


def _indian(n: int) -> str:
    """12,34,567 grouping."""
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return ("-" if n < 0 else "") + s


def _trim(d: Decimal, places: int) -> str:
    q = d.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    s = f"{q:f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def money(amount: Number, currency: Optional[str] = "INR", short: bool = True, sign: bool = False) -> str:
    """₹12,450 · ₹1.84 L · ₹2.5 Cr (short) · USD 1,250. ``sign`` adds + for positive amounts."""
    d = _dec(amount)
    if d is None:
        return ""
    neg = d < 0
    a = abs(d)
    cur = (currency or "INR").upper()
    if cur == "INR":
        if short and a >= Decimal(10_000_000):
            body = f"₹{_trim(a / Decimal(10_000_000), 2)} Cr"
        elif short and a >= Decimal(100_000):
            body = f"₹{_trim(a / Decimal(100_000), 2)} L"
        else:
            whole = int(a.quantize(Decimal(1), rounding=ROUND_HALF_UP)) if a >= 100 else None
            body = f"₹{_indian(whole)}" if whole is not None else f"₹{_trim(a, 2)}"
    else:
        whole = int(a.quantize(Decimal(1), rounding=ROUND_HALF_UP))
        body = f"{cur} {whole:,}" if a >= 100 else f"{cur} {_trim(a, 2)}"
    if neg:
        return "− " + body
    return ("+ " + body) if sign and d > 0 else body


def day(value: Union[str, date_type, None], today: date_type) -> str:
    if not value:
        return ""
    d = value if isinstance(value, date_type) else date_type.fromisoformat(str(value)[:10])
    gap = (d - today).days
    if gap == 0:
        return "Today"
    if gap == 1:
        return "Tomorrow"
    if gap == -1:
        return "Yesterday"
    if 1 < gap < 7:
        return d.strftime("%A")
    label = f"{d.day} {d.strftime('%b')}"
    return label if d.year == today.year else f"{label} {d.year}"


def duration(minutes: Optional[int]) -> str:
    m = int(minutes or 0)
    if m < 60:
        return f"{m} min"
    h, r = divmod(m, 60)
    return f"{h}h" if r == 0 else f"{h}h {r}m"


def greeting(hour: int, name: Optional[str]) -> str:
    part = "Good morning" if 4 <= hour < 12 else "Good afternoon" if 12 <= hour < 17 else "Good evening"
    first = (name or "").strip().split(" ")[0]
    return f"{part}, {first}" if first else part
