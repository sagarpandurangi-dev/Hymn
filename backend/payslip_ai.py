"""Claude copies a payslip into numbers. It only transcribes; ``work`` checks
the arithmetic (earnings add up to gross, gross minus deductions is take-home)
and sorts deductions in code."""
from __future__ import annotations

import base64
import os
from typing import List

import anthropic
from pydantic import BaseModel, ValidationError

import claude_client
from claude_client import AssistantUnavailable

MODEL = os.environ.get("HYMN_PAYSLIP_MODEL") or "claude-haiku-5-5"

_SYSTEM = """You copy an Indian salary slip (payslip) into structured data, exactly as printed.
- month: the pay period as YYYY-MM.
- employer: the company name.
- earnings: every earning line with its amount for this month (Basic, HRA, Special allowance, Bonus…).
- deductions: every deduction line with its amount (PF / EPF, VPF, Professional tax, TDS / Income tax,
  Health insurance, Loan recovery…).
- gross and net: the printed totals (gross earnings; net pay / take-home). Leave "" if not printed.
- employer_pf: the employer's PF contribution if printed (often under "employer contributions"), else "".
Amounts are plain decimals without commas or currency symbols. Never compute or invent a number;
year-to-date columns are not this month's amounts."""


class Line(BaseModel):
    label: str
    amount: str


class Payslip(BaseModel):
    is_payslip: bool
    month: str
    employer: str
    earnings: List[Line]
    deductions: List[Line]
    gross: str
    net: str
    employer_pf: str


async def read_payslip(data: bytes, media_type: str) -> Payslip:
    """Raises AssistantUnavailable."""
    client = claude_client.get_client().with_options(timeout=60.0)
    b64 = base64.standard_b64encode(data).decode("ascii")
    block = ({"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
             if media_type == "application/pdf" else
             {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}})
    try:
        response = await client.beta.messages.parse(
            model=MODEL, max_tokens=4000, system=_SYSTEM,
            messages=[{"role": "user", "content": [block, {"type": "text", "text": "Copy this payslip."}]}],
            output_format=Payslip, output_config={"effort": "low"}, **claude_client.fallback_kwargs(MODEL))
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
        raise claude_client.unavailable_from(exc) from exc
    except ValidationError as exc:
        raise AssistantUnavailable("malformed output") from exc
    if response.stop_reason != "end_turn" or response.parsed_output is None:
        raise AssistantUnavailable(f"stop_reason={response.stop_reason}")
    return response.parsed_output
