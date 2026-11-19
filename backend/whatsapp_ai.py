"""Claude reads a forwarded or typed WhatsApp message and turns it into one task.

It only extracts (title, due date and time, area, people). It never answers
questions or chats: anything that isn't a task comes back as is_task=false and
the caller sends a fixed reply. Phone numbers are removed before the text
leaves Hymn (``redact``).
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import List, Literal, Tuple

import anthropic
from pydantic import BaseModel, Field, ValidationError

import claude_client
from claude_client import AssistantUnavailable

MODEL = os.environ.get("HYMN_WHATSAPP_MODEL") or "claude-haiku-5-5"

# Any run of 7+ digits, allowing spaces, dots, dashes and brackets inside and an
# optional + in front: +91 98450 12345, 080-2345 6789, (022) 2345-6789.
_PHONE = re.compile(r"\+?\(?\d[\d\s().-]{5,}\d")


def redact(text: str) -> str:
    """Remove phone numbers (anything with 7+ digits) before the text goes to the AI."""
    def repl(m: re.Match) -> str:
        return "[number]" if sum(c.isdigit() for c in m.group(0)) >= 7 else m.group(0)
    return _PHONE.sub(repl, text or "")


SYSTEM = """You turn a message someone forwarded or typed to Hymn into ONE task.
You only extract. You never answer questions, give advice, chat or write anything else.

- is_task: true only if the message asks for something to be done, remembered or
  attended (a bill to pay, a call to make, an appointment, an errand, a deadline).
  Questions to you, greetings, jokes, news, chain messages and general chat are false.
- title: a short task in the person's words, at most 60 characters, starting with a
  verb where natural ("Pay electricity bill", "Call Priya about the venue").
- due_date: YYYY-MM-DD only if the message says or clearly implies a day ("tomorrow",
  "on Friday", "by the 25th"), worked out from the current date given; else "".
- due_time: HH:MM (24-hour) only if a time is stated; else "".
- due_confidence: 0 to 1, how sure you are about the date.
- area: money, health, family, learning or work, or "" if unclear. Relationships and
  friends count as family.
- people: first names of people the task involves (never phone numbers).
- confidence: 0 to 1, how sure you are this is a task and the title is right."""


class TaskParse(BaseModel):
    is_task: bool
    title: str = Field(max_length=200)
    due_date: str
    due_time: str
    due_confidence: float
    area: Literal["money", "health", "family", "learning", "work", ""]
    people: List[str]
    confidence: float


_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _clean(p: TaskParse) -> TaskParse:
    """Code checks what the model returned; anything malformed is dropped, not guessed."""
    due_date = p.due_date if _DATE.match(p.due_date or "") else ""
    if due_date:
        try:
            datetime.strptime(due_date, "%Y-%m-%d")
        except ValueError:
            due_date = ""
    due_time = p.due_time if (due_date and _TIME.match(p.due_time or "")) else ""
    return p.model_copy(update={
        "title": " ".join((p.title or "").split())[:60],
        "due_date": due_date, "due_time": due_time,
        "due_confidence": min(1.0, max(0.0, p.due_confidence)),
        "confidence": min(1.0, max(0.0, p.confidence)),
        "people": [redact(x)[:40] for x in p.people[:5]],
    })


async def parse_task(text: str, timezone_name: str, now_local: datetime) -> Tuple[TaskParse, dict]:
    """Returns (parse, token usage). One retry on malformed output. Raises AssistantUnavailable."""
    client = claude_client.get_client().with_options(timeout=30.0)
    user = (f"Current date and time: {now_local.strftime('%A %Y-%m-%d %H:%M')} ({timezone_name}).\n\n"
            f"Message:\n{redact(text)[:4000]}")
    last: Exception = AssistantUnavailable("no attempt")
    for _ in range(2):
        try:
            response = await client.beta.messages.parse(
                model=MODEL, max_tokens=600,
                system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
                output_format=TaskParse,
                **claude_client.fallback_kwargs(MODEL),
            )
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
            raise claude_client.unavailable_from(exc) from exc
        except ValidationError as exc:
            last = AssistantUnavailable("malformed output")
            continue
        u = getattr(response, "usage", None)
        usage = {"input_tokens": getattr(u, "input_tokens", 0) or 0,
                 "output_tokens": getattr(u, "output_tokens", 0) or 0,
                 "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0}
        if response.stop_reason != "end_turn" or response.parsed_output is None:
            last = AssistantUnavailable(f"stop_reason={response.stop_reason}")
            continue
        return _clean(response.parsed_output), usage
    raise last
