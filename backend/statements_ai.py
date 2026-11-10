"""Claude reads one chunk of a statement PDF into structured lines.

The rule is the same for every bank, card and wallet: the debit column is
money out of that account, the credit column is money into it. Claude only
transcribes; classification (spend vs transfer) happens later, and the
arithmetic checks in ``statements`` catch misreads.
"""
from __future__ import annotations

import base64
import os
from typing import List, Literal

import anthropic
from pydantic import BaseModel, ValidationError

import claude_client
from claude_client import AssistantUnavailable

# Transcription is mechanical and verified by arithmetic afterwards, so the
# cheapest model does it; HYMN_STATEMENT_MODEL overrides.
MODEL = os.environ.get("HYMN_STATEMENT_MODEL") or "claude-haiku-5-5"

_SYSTEM = """You transcribe financial statements (bank accounts, credit cards,
wallets such as PhonePe or Google Pay, loans) into structured data. You will
see some or all pages of one statement.

Rules:
- Transcribe exactly what is printed. Never invent, merge, split or skip
  transactions. Skip only headers, page totals and summary rows.
- Every transaction goes in `lines`, in printed order. Put the amount from the
  debit / withdrawal / "Dr" column (or a "Dr" suffix) in `debit`, and from the
  credit / deposit / "Cr" column (or a "Cr" suffix) in `credit`; leave the other
  empty. On a card statement purchases are debits and payments or refunds are
  credits.
- Amounts are plain decimals: no currency symbols, no thousands separators,
  no signs (e.g. "12450.50").
- Dates are YYYY-MM-DD; use the statement's day/month order to read them.
- `balance` is the running balance printed on that line, if any.
- `reference` is the UPI / cheque / transaction reference printed, if any.
- Statement-level fields come from the pages you see; leave a field empty if
  it isn't on these pages. For cards and loans, opening and closing balances
  are amounts owed."""


class StatementLine(BaseModel):
    date: str
    description: str
    reference: str
    debit: str
    credit: str
    balance: str


class StatementChunk(BaseModel):
    institution: str
    account_kind: Literal["bank", "credit_card", "wallet", "loan", "investment", "other"]
    account_last4: str
    currency: str
    period_start: str
    period_end: str
    opening_balance: str
    closing_balance: str
    lines: List[StatementLine]


async def extract_chunk(pdf_bytes: bytes, part: int, parts: int) -> StatementChunk:
    """Read one unencrypted PDF chunk. Raises AssistantUnavailable."""
    client = claude_client.get_client()
    content = [
        {"type": "document", "source": {
            "type": "base64", "media_type": "application/pdf",
            "data": base64.standard_b64encode(pdf_bytes).decode("ascii"),
        }},
        {"type": "text", "text": f"These are pages from part {part} of {parts} of one statement."},
    ]
    try:
        response = await client.beta.messages.parse(
            model=MODEL,
            max_tokens=16000,
            system=_SYSTEM,
            messages=[{"role": "user", "content": content}],
            output_format=StatementChunk,
            output_config={"effort": "low"},
            **claude_client.fallback_kwargs(MODEL),
        )
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
        raise claude_client.unavailable_from(exc) from exc
    except ValidationError as exc:
        raise AssistantUnavailable("malformed output") from exc
    if response.stop_reason != "end_turn" or response.parsed_output is None:
        raise AssistantUnavailable(f"stop_reason={response.stop_reason}")
    return response.parsed_output
