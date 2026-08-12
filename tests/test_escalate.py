"""Tests for the two-stage escalation stage (rd-signal-2 pattern).

The escalation stage sends *only ambiguous* signals to a cheap model for
confirmation — "model calls scale with uncertainty, not traffic". All HTTP is
mocked; no network in tests.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from hermes_signals.classifier import Signal, classify_trace
from hermes_signals.escalate import escalate_signals

CFG = {
    "base_url": "https://llm.example.com/v1",
    "model": "deepseek-v4-flash",
    "api_key": "test-key",
}


def _ambiguous_trace() -> dict:
    # subagent-handoff-loss with mixed success+abandonment language → ambiguous.
    return {
        "events": [
            {"type": "tool_call", "id": "1", "name": "delegate_task", "arguments": {"goal": "fix"}},
            {"type": "tool_result", "tool_call_id": "1", "status": "success", "content": "done"},
            {
                "type": "assistant",
                "content": "The subagent finished the fix, but I couldn't verify it in time.",
            },
        ]
    }


def _fake_openai(content: str):
    """Return a urlopen mock that responds with an OpenAI chat completion."""

    def fake_urlopen(request, timeout=None, **kwargs):
        body = {
            "choices": [{"message": {"role": "assistant", "content": content}}],
        }
        response = type(
            "FakeResponse",
            (),
            {
                "__enter__": lambda self: self,
                "__exit__": lambda *a: None,
                "read": lambda self: json.dumps(body).encode(),
                "status": 200,
            },
        )()
        return response

    return fake_urlopen


def test_only_ambiguous_signals_are_escalated() -> None:
    trace = _ambiguous_trace()
    signals = classify_trace(trace)
    assert [s.signal_id for s in signals] == ["subagent-handoff-loss"]
    assert signals[0].ambiguous is True

    with patch("urllib.request.urlopen") as mock:
        mock.side_effect = _fake_openai('{"verdict": "confirm"}')
        escalated = escalate_signals(signals, trace, **CFG)

    mock.assert_called_once()
    confirmed = [s for s in escalated if s.signal_id == "subagent-handoff-loss"]
    assert confirmed[0].confirmed is True
    assert confirmed[0].judge_model == CFG["model"]


def test_confirm_verdict_is_applied() -> None:
    signals = [Signal("x", "low", "s", ("e",), ambiguous=True)]
    with patch("urllib.request.urlopen", _fake_openai('{"verdict": "confirm"}')):
        escalated = escalate_signals(signals, {}, **CFG)
    assert escalated[0].confirmed is True


def test_reject_verdict_is_applied() -> None:
    signals = [Signal("x", "low", "s", ("e",), ambiguous=True)]
    with patch("urllib.request.urlopen", _fake_openai('{"verdict": "reject"}')):
        escalated = escalate_signals(signals, {}, **CFG)
    assert escalated[0].confirmed is False


def test_unknown_verdict_leaves_confirmation_unset() -> None:
    signals = [Signal("x", "low", "s", ("e",), ambiguous=True)]
    with patch("urllib.request.urlopen", _fake_openai("I think this is fine")):
        escalated = escalate_signals(signals, {}, **CFG)
    assert escalated[0].confirmed is None
    assert escalated[0].judge_model == CFG["model"]


def test_rejected_tense_inside_markdown_fence_is_parsed() -> None:
    from hermes_signals.escalate import _parse_verdict

    content = '```json\n{\n  "verdict": "rejected",\n  "reason": "no evidence"\n}\n```'
    assert _parse_verdict(content) is False
    assert _parse_verdict('{"verdict": "confirmed"}') is True


def test_prompt_includes_assistant_text_from_events() -> None:
    from hermes_signals.escalate import _build_prompt

    trace = {
        "events": [
            {"type": "assistant", "content": "The subagent finished, but I couldn't verify it."}
        ]
    }
    signal = Signal("subagent-handoff-loss", "medium", "s", ("e",), ambiguous=True)
    prompt = _build_prompt(signal, trace, 2000)
    assert "The subagent finished" in prompt


def test_unambiguous_signals_never_touch_the_network() -> None:
    signals = [Signal("y", "high", "s", ("e",), ambiguous=False)]
    with patch("urllib.request.urlopen") as mock:
        escalated = escalate_signals(signals, {}, **CFG)
    mock.assert_not_called()
    assert escalated == signals


def test_http_failure_keeps_signal_and_never_raises() -> None:
    signals = [Signal("x", "low", "s", ("e",), ambiguous=True)]

    def broken(request, timeout=None, **kwargs):
        raise ConnectionError("network down")

    with patch("urllib.request.urlopen", broken):
        escalated = escalate_signals(signals, {}, **CFG)
    assert escalated[0].confirmed is None


def test_prompt_never_contains_raw_secrets() -> None:
    secret = "sk-abcdefghijklmnopqrstuvwxyz1234"
    trace = {
        "events": [
            {"type": "tool_call", "id": "1", "name": "terminal", "arguments": {"command": f"token={secret}"}},
            {"type": "tool_result", "tool_call_id": "1", "status": "success", "content": "ok"},
        ],
        "final_response": f"done with {secret}",
    }
    signals = [Signal("x", "low", "s", ("e",), ambiguous=True)]
    captured: list[bytes] = []

    def capture(request, timeout=None, **kwargs):
        captured.append(request.data)
        return _fake_openai('{"verdict": "confirm"}')(request)

    with patch("urllib.request.urlopen", capture):
        escalate_signals(signals, trace, **CFG)

    assert captured, "expected an HTTP call"
    assert secret not in captured[0].decode("utf-8", errors="ignore")