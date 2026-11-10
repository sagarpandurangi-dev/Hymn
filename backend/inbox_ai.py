"""Claude calls for the brain-dump inbox.

Two jobs, each a single structured-output request:

* ``sort_dump`` splits a raw stream of thoughts into items and labels
  each one task / reminder / idea / plan.
* ``summarise_patterns`` turns a week of inbox activity into themes and
  workflow suggestions.

Both raise :class:`claude_client.AssistantUnavailable` on any failure (no key, API
error, refusal, truncated output). Callers must already have persisted
whatever the user sent, so a failure here never loses anything.
"""
from __future__ import annotations

import logging
import os
from typing import List, Literal

import anthropic
from pydantic import BaseModel, Field, ValidationError

import claude_client
from claude_client import AssistantUnavailable

logger = logging.getLogger(__name__)

# Haiku is plenty for sorting and costs a fraction of Opus; override with
# HYMN_ASSISTANT_MODEL (e.g. claude-opus-5-5) if quality ever falls short.
MODEL = os.environ.get("HYMN_ASSISTANT_MODEL") or "claude-haiku-5-5"

_TONE = (
    "You are Hymn, the user's personal assistant. Your job is to take "
    "cognitive load off the user so that nothing actionable is lost. "
    "Tone: encouraging, concise, never preachy."
)

_SORT_SYSTEM = _TONE + """

The user sends a raw brain dump: unfiltered thoughts, possibly several in one
message, possibly a forwarded message. Split it into separate items, one per
distinct thought, and label each:

- task: a concrete action the user can do ("renew passport", "reply to Raj").
- reminder: something tied to a specific date or time ("Mom's birthday on 12
  Nov", "call the bank tomorrow at 10").
- idea: a possibility with no commitment yet ("maybe learn the guitar").
- plan: a larger intention that needs several steps or a decision ("travel to
  Norway this summer", "get fit").

Rules:
- Keep the user's own words, lightly cleaned up; one short line per item.
- Never invent items and never drop one. Feelings or worries become an item
  too if they point at something to act on.
- For reminders with a date or time, resolve it against the current local time
  given and put it in remind_at_local as YYYY-MM-DDTHH:MM (use 09:00 when only
  a day is given). Leave remind_at_local empty when no time is known.
- encouragement: at most 12 words acknowledging the dump. No questions."""

_PATTERNS_SYSTEM = _TONE + """

You receive a week of the user's brain-dump inbox: items captured, how they
were handled, and items the user keeps leaving open in daily reviews. Find:

- themes: up to 3 topics the user keeps returning to.
- avoidance: up to 3 items or kinds of task the user is avoiding, with a
  one-line guess at why (too big, unclear next step, not really wanted).
- suggestions: up to 3 small, specific changes to the user's workflow.
- summary: two short, encouraging sentences on how the week went.

Base everything on the data given. If there is little data, say so briefly
rather than inventing patterns."""


class SortedItem(BaseModel):
    text: str
    category: Literal["task", "reminder", "idea", "plan"]
    remind_at_local: str = Field(description="YYYY-MM-DDTHH:MM, or empty")


class SortedDump(BaseModel):
    items: List[SortedItem]
    encouragement: str


class WeeklyPatterns(BaseModel):
    themes: List[str]
    avoidance: List[str]
    suggestions: List[str]
    summary: str


async def _parse(system: str, user_content: str, output_format: type[BaseModel]):
    # A phone is waiting on the response; the raw dump is already saved,
    # so fail fast and let the user re-sort later.
    client = claude_client.get_client().with_options(timeout=45.0)
    try:
        response = await client.beta.messages.parse(
            model=MODEL,
            max_tokens=8000,
            system=system,
            messages=[{"role": "user", "content": user_content}],
            output_format=output_format,
            output_config={"effort": "low"},
            **claude_client.fallback_kwargs(MODEL),
        )
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
        raise claude_client.unavailable_from(exc) from exc
    except ValidationError as exc:
        logger.warning("assistant returned malformed output: %s", exc)
        raise AssistantUnavailable("malformed output") from exc

    if response.stop_reason != "end_turn" or response.parsed_output is None:
        logger.warning("assistant stopped early: %s", response.stop_reason)
        raise AssistantUnavailable(f"stop_reason={response.stop_reason}")
    return response.parsed_output


async def sort_dump(raw_text: str, *, now_local: str, tz_name: str) -> SortedDump:
    content = (
        f"Current local time: {now_local} ({tz_name})\n\n"
        f"<brain_dump>\n{raw_text}\n</brain_dump>"
    )
    result: SortedDump = await _parse(_SORT_SYSTEM, content, SortedDump)
    if not result.items:
        raise AssistantUnavailable("no items returned")
    return result


async def summarise_patterns(week_report: str) -> WeeklyPatterns:
    return await _parse(_PATTERNS_SYSTEM, week_report, WeeklyPatterns)
