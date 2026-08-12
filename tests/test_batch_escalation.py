"""Tests for batch escalation, judge double-check, and agreement tracking."""

from __future__ import annotations

import json
from unittest.mock import patch

from hermes_signals.classifier import Signal
from hermes_signals.escalate import escalate_signals
from hermes_signals.store import judge_agreement, record_feedback

CFG = {"base_url": "https://llm.example.com/v1", "model": "deepseek-v4-flash", "api_key": "k"}


def _fake_urlopen(responses: list[str]):
    """Return a urlopen mock replaying responses in order (each an OpenAI completion)."""
    calls = {"count": 0}

    def fake(request, timeout=None, **kwargs):
        body = {"choices": [{"message": {"role": "assistant", "content": responses[calls["count"]]}}]}
        calls["count"] += 1
        return type(
            "FakeResponse",
            (),
            {
                "__enter__": lambda self: self,
                "__exit__": lambda *a: None,
                "read": lambda self: json.dumps(body).encode(),
                "status": 200,
            },
        )()

    return fake, calls


def test_batch_escalation_uses_one_call_for_many_signals() -> None:
    signals = [
        Signal("a", "low", "s", ("e",), ambiguous=True),
        Signal("b", "low", "s", ("e",), ambiguous=True),
    ]
    # Batch call + adversarial double-check for the rejected "b" case.
    fake, calls = _fake_urlopen(['{"a": "confirm", "b": "reject"}', '{"verdict": "reject"}'])
    with patch("urllib.request.urlopen", fake):
        escalated = escalate_signals(signals, {}, **CFG)
    assert calls["count"] == 2
    by_id = {s.signal_id: s for s in escalated}
    assert by_id["a"].confirmed is True
    assert by_id["b"].confirmed is False


def test_batch_parse_failure_leaves_all_unconfirmed_but_judged() -> None:
    signals = [
        Signal("a", "low", "s", ("e",), ambiguous=True),
        Signal("b", "low", "s", ("e",), ambiguous=True),
    ]
    fake, _ = _fake_urlopen(["I have no structured opinion"])
    with patch("urllib.request.urlopen", fake):
        escalated = escalate_signals(signals, {}, **CFG)
    assert all(s.confirmed is None for s in escalated)
    assert all(s.judge_model == CFG["model"] for s in escalated)


def test_double_check_rejects_reconfirmed_to_unknown() -> None:
    signal = [Signal("a", "low", "s", ("e",), ambiguous=True)]
    fake, calls = _fake_urlopen(['{"verdict": "reject"}', '{"verdict": "confirm"}'])
    with patch("urllib.request.urlopen", fake):
        escalated = escalate_signals(signal, {}, **CFG, double_check=True)
    assert calls["count"] == 2
    assert escalated[0].confirmed is None  # disagreement → unknown


def test_double_check_confirmed_reject_stays_rejected() -> None:
    signal = [Signal("a", "low", "s", ("e",), ambiguous=True)]
    fake, calls = _fake_urlopen(['{"verdict": "reject"}', '{"verdict": "reject"}'])
    with patch("urllib.request.urlopen", fake):
        escalated = escalate_signals(signal, {}, **CFG, double_check=True)
    assert calls["count"] == 2
    assert escalated[0].confirmed is False


def test_double_check_disabled_makes_one_call() -> None:
    signal = [Signal("a", "low", "s", ("e",), ambiguous=True)]
    fake, calls = _fake_urlopen(['{"verdict": "reject"}'])
    with patch("urllib.request.urlopen", fake):
        escalated = escalate_signals(signal, {}, **CFG, double_check=False)
    assert calls["count"] == 1
    assert escalated[0].confirmed is False


def test_unambiguous_signals_never_call_again() -> None:
    signals = [Signal("y", "high", "s", ("e",), ambiguous=False)]
    fake, calls = _fake_urlopen(["{}"])
    with patch("urllib.request.urlopen", fake):
        escalated = escalate_signals(signals, {}, **CFG)
    assert calls["count"] == 0
    assert escalated == signals


def test_judge_agreement_matches_human_labels(tmp_path) -> None:
    signals_path = tmp_path / "signals.jsonl"
    feedback_path = tmp_path / "signals-feedback.jsonl"
    from hermes_signals.classifier import classify_trace, stable_trace_id, trace_from_conversation
    from hermes_signals.store import append_payload

    messages = [
        {
            "role": "assistant",
            "tool_calls": [
                {"id": "c1", "function": {"name": "update_record", "arguments": '{"id": 1}'}}
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "timed out"},
    ]
    trace = trace_from_conversation(messages, final_response="The record was successfully updated.")
    payload = {
        "trace_id": stable_trace_id(trace),
        "session_id": "s1",
        "platform": "test",
        "signals": [{**signal.to_dict(), "confirmed": True} for signal in classify_trace(trace)],
    }
    append_payload(payload, signals_path)
    trace_id = payload["trace_id"]
    # Judge said confirm; human says correct → agreement.
    record_feedback(trace_id, "false-success", "correct", path=feedback_path)

    report = judge_agreement(signals_path=signals_path, feedback_path=feedback_path)
    assert report["judged"] == 1
    assert report["agreed"] == 1
    assert report["agreement"] == 1.0