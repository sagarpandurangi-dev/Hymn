"""Shared Claude API access for every Hymn feature.

One AsyncAnthropic client, one place that knows which models take the
server-side refusal fallback, and a text-completion helper that resumes
server-tool turns (web search) when the API pauses them.

All failures surface as :class:`AssistantUnavailable`; callers decide how
to degrade (keep the raw dump, return a friendly error, use a fallback plan).
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import anthropic

logger = logging.getLogger(__name__)

# On a policy decline these models can re-run the request on Anthropic's
# recommended fallback model instead of returning the refusal. Haiku has
# no server-side fallback; its refusals surface as AssistantUnavailable.
_FALLBACK_MODELS = frozenset({"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"})
_FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Server tools run a sampling loop that can pause; resume at most this often.
MAX_CONTINUATIONS = 5


class AssistantUnavailable(Exception):
    """The model could not produce a usable answer."""


_client: Optional[anthropic.AsyncAnthropic] = None


def get_client() -> anthropic.AsyncAnthropic:
    global _client
    if not os.environ.get("ANTHROPIC_API_KEY"):
        logger.warning("assistant unavailable: ANTHROPIC_API_KEY is not configured")
        raise AssistantUnavailable("ANTHROPIC_API_KEY is not configured")
    if _client is None:
        # Someone is waiting in the app; fail fast rather than hang.
        _client = anthropic.AsyncAnthropic(timeout=120.0, max_retries=1)
    return _client


def fallback_kwargs(model: str) -> Dict[str, Any]:
    if model in _FALLBACK_MODELS:
        return {"betas": [_FALLBACK_BETA], "fallbacks": "default"}
    return {}


def unavailable_from(exc: Exception) -> AssistantUnavailable:
    """Log an SDK error and wrap it."""
    if isinstance(exc, anthropic.APIStatusError):
        logger.warning("assistant API error %s: %s", exc.status_code, exc.message)
        return AssistantUnavailable(f"API error {exc.status_code}")
    if isinstance(exc, anthropic.APIConnectionError):
        logger.warning("assistant unreachable: %s", exc)
        return AssistantUnavailable("connection error")
    logger.warning("assistant failed: %s", exc)
    return AssistantUnavailable(type(exc).__name__)


async def complete_text(
    *,
    model: str,
    system: str,
    messages: List[Dict[str, Any]],
    max_tokens: int = 16000,
    effort: str = "medium",
    tools: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Run one assistant turn and return its text.

    ``messages`` alternate user/assistant and end with a user message.
    Paused server-tool turns (``pause_turn``) are resumed automatically.
    """
    client = get_client()
    convo = list(messages)
    extra: Dict[str, Any] = {"tools": tools} if tools else {}
    for _ in range(MAX_CONTINUATIONS + 1):
        try:
            response = await client.beta.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=convo,
                output_config={"effort": effort},
                **extra,
                **fallback_kwargs(model),
            )
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
            raise unavailable_from(exc) from exc
        if response.stop_reason == "pause_turn":
            convo = convo + [{"role": "assistant", "content": response.content}]
            continue
        if response.stop_reason not in ("end_turn", "stop_sequence"):
            logger.warning("assistant stopped early: %s", response.stop_reason)
            raise AssistantUnavailable(f"stop_reason={response.stop_reason}")
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        if not text:
            raise AssistantUnavailable("empty answer")
        return text
    logger.warning("assistant kept pausing after %d continuations", MAX_CONTINUATIONS)
    raise AssistantUnavailable("too many continuations")
