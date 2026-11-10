"""Shared Claude client: pause_turn resumption, failures, planning history."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx2
import pytest

import anthropic
import claude_client
import planning_engine


def _text(t):
    return SimpleNamespace(type="text", text=t)


def _response(stop_reason, *blocks):
    return SimpleNamespace(stop_reason=stop_reason, content=list(blocks))


class _FakeMessages:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _install(monkeypatch, messages):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(claude_client, "_client", SimpleNamespace(beta=SimpleNamespace(messages=messages)))


def _complete(**overrides):
    kwargs = {"model": "claude-opus-5-5", "system": "s",
              "messages": [{"role": "user", "content": "plan my week"}]}
    kwargs.update(overrides)
    return asyncio.run(claude_client.complete_text(**kwargs))


def test_returns_joined_text_and_sends_fallbacks_for_opus(monkeypatch):
    messages = _FakeMessages(_response("end_turn", SimpleNamespace(type="thinking"), _text("Hello "), _text("there")))
    _install(monkeypatch, messages)
    assert _complete() == "Hello there"
    assert messages.calls[0]["fallbacks"] == "default"
    assert messages.calls[0]["output_config"] == {"effort": "medium"}


def test_no_fallbacks_for_haiku(monkeypatch):
    messages = _FakeMessages(_response("end_turn", _text("ok")))
    _install(monkeypatch, messages)
    _complete(model="claude-haiku-5-5")
    assert "fallbacks" not in messages.calls[0]
    assert "betas" not in messages.calls[0]


def test_paused_turn_is_resumed_with_its_content(monkeypatch):
    paused_block = SimpleNamespace(type="server_tool_use")
    messages = _FakeMessages(
        _response("pause_turn", paused_block),
        _response("end_turn", _text("found it")),
    )
    _install(monkeypatch, messages)
    assert _complete(tools=[planning_engine._WEB_SEARCH_TOOL]) == "found it"
    second = messages.calls[1]["messages"]
    assert second[-1] == {"role": "assistant", "content": [paused_block]}
    assert messages.calls[1]["tools"] == [planning_engine._WEB_SEARCH_TOOL]


def test_endless_pausing_gives_up(monkeypatch):
    messages = _FakeMessages(*[_response("pause_turn") for _ in range(claude_client.MAX_CONTINUATIONS + 1)])
    _install(monkeypatch, messages)
    with pytest.raises(claude_client.AssistantUnavailable):
        _complete()


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_unfinished_answers_are_unavailable(monkeypatch, stop_reason):
    _install(monkeypatch, _FakeMessages(_response(stop_reason, _text("partial"))))
    with pytest.raises(claude_client.AssistantUnavailable):
        _complete()


def test_api_error_is_unavailable(monkeypatch):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    error = anthropic.InternalServerError("boom", response=httpx2.Response(529, request=request), body=None)
    _install(monkeypatch, _FakeMessages(error))
    with pytest.raises(claude_client.AssistantUnavailable):
        _complete()


def test_missing_key_is_unavailable(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(claude_client, "_client", None)
    with pytest.raises(claude_client.AssistantUnavailable):
        _complete()


# ---------------------------------------------------------------------------
# Planning history
# ---------------------------------------------------------------------------

def test_planning_history_sends_latest_message_once_and_strips_proposals():
    history = [
        {"role": "assistant", "content": "Welcome!"},  # leading assistant turn dropped
        {"role": "user", "content": "Help me run a 10k"},
        {"role": "assistant", "content": "Sure. <<<HYMN_PROPOSAL>>> {\"a\": 1} <<<END>>>"},
        {"role": "user", "content": "Make it 3 days a week"},
    ]
    assert planning_engine._llm_messages(history) == [
        {"role": "user", "content": "Help me run a 10k"},
        {"role": "assistant", "content": "Sure."},
        {"role": "user", "content": "Make it 3 days a week"},
    ]


def test_planning_history_merges_consecutive_turns_of_one_role():
    history = [
        {"role": "user", "content": "first"},
        {"role": "user", "content": "second"},
    ]
    assert planning_engine._llm_messages(history) == [{"role": "user", "content": "first\n\nsecond"}]


def test_planning_turn_reports_unavailable_as_502(monkeypatch):
    from fastapi import HTTPException

    async def unavailable(**_):
        raise claude_client.AssistantUnavailable("connection error")

    monkeypatch.setattr(claude_client, "complete_text", unavailable)
    ctx = {"target_type": "goal", "target": {"id": "g1", "title": "Run a 10k"}}
    monkeypatch.setattr(planning_engine, "_context_prelude", lambda ctx: "ctx")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(planning_engine._call_llm([{"role": "user", "content": "hi"}], ctx))
    assert exc.value.status_code == 502
