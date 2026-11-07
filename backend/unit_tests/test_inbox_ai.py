"""inbox_ai turns every failure mode into AssistantUnavailable."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx2
import pytest

import anthropic
import inbox_ai


class _FakeMessages:
    def __init__(self, result=None, exc=None):
        self.result, self.exc, self.kwargs = result, exc, None

    async def parse(self, **kwargs):
        self.kwargs = kwargs
        if self.exc:
            raise self.exc
        return self.result


def _install(monkeypatch, messages):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(inbox_ai, "_client", SimpleNamespace(beta=SimpleNamespace(messages=messages)))


def _sort():
    return asyncio.run(inbox_ai.sort_dump("renew passport", now_local="2026-10-28T09:00", tz_name="UTC"))


def test_missing_key_is_unavailable(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(inbox_ai.AssistantUnavailable):
        _sort()


def test_success_returns_parsed_output_and_sends_expected_request(monkeypatch):
    parsed = inbox_ai.SortedDump(
        items=[inbox_ai.SortedItem(text="renew passport", category="task", remind_at_local="")],
        encouragement="Got it.",
    )
    messages = _FakeMessages(SimpleNamespace(stop_reason="end_turn", parsed_output=parsed))
    _install(monkeypatch, messages)
    assert _sort() == parsed
    assert messages.kwargs["model"] == inbox_ai.MODEL
    assert messages.kwargs["output_format"] is inbox_ai.SortedDump
    assert messages.kwargs["fallbacks"] == "default"
    assert "renew passport" in messages.kwargs["messages"][0]["content"]


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_unfinished_answers_are_unavailable(monkeypatch, stop_reason):
    _install(monkeypatch, _FakeMessages(SimpleNamespace(stop_reason=stop_reason, parsed_output=None)))
    with pytest.raises(inbox_ai.AssistantUnavailable):
        _sort()


def test_empty_split_is_unavailable(monkeypatch):
    parsed = inbox_ai.SortedDump(items=[], encouragement="")
    _install(monkeypatch, _FakeMessages(SimpleNamespace(stop_reason="end_turn", parsed_output=parsed)))
    with pytest.raises(inbox_ai.AssistantUnavailable):
        _sort()


def _status_error(cls, code):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("boom", response=httpx2.Response(code, request=request), body=None)


@pytest.mark.parametrize("exc", [
    _status_error(anthropic.RateLimitError, 429),
    _status_error(anthropic.InternalServerError, 529),
    anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com")),
])
def test_api_errors_are_unavailable(monkeypatch, exc):
    _install(monkeypatch, _FakeMessages(exc=exc))
    with pytest.raises(inbox_ai.AssistantUnavailable):
        _sort()
