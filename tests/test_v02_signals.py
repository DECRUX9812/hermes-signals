"""v0.2 signal tests: subagent-handoff-loss, strategy-aware retry, escalation candidacy.

These cover the deterministic stage of the two-stage design from the rd-signal-2
article: deterministic filters flag candidates; ambiguous candidates are marked
for optional cheap-model confirmation (tested separately in test_escalate.py).
"""

from __future__ import annotations

from hermes_signals.classifier import Signal, classify_trace


def find(trace: dict, signal_id: str, **kw) -> Signal | None:
    for signal in classify_trace(trace, **kw):
        if signal.signal_id == signal_id:
            return signal
    return None


# --- subagent-handoff-loss ---------------------------------------------------

def test_subagent_success_ignored_by_final_response() -> None:
    trace = {
        "events": [
            {"type": "tool_call", "id": "1", "name": "delegate_task", "arguments": {"goal": "fix bug"}},
            {
                "type": "tool_result",
                "tool_call_id": "1",
                "status": "success",
                "content": "subagent completed the fix and tests pass",
            },
            {"type": "assistant", "content": "I couldn't get the fix done in time."},
        ]
    }

    signal = find(trace, "subagent-handoff-loss")
    assert signal is not None
    assert signal.severity == "medium"
    assert "subagent_tool=delegate_task" in signal.evidence


def test_subagent_success_acknowledged_is_clean() -> None:
    trace = {
        "events": [
            {"type": "tool_call", "id": "1", "name": "delegate_task", "arguments": {"goal": "fix bug"}},
            {
                "type": "tool_result",
                "tool_call_id": "1",
                "status": "success",
                "content": "subagent completed the fix",
            },
            {"type": "assistant", "content": "The fix is complete thanks to the subagent."},
        ]
    }

    assert find(trace, "subagent-handoff-loss") is None


def test_subagent_failure_is_not_handoff_loss() -> None:
    trace = {
        "events": [
            {"type": "tool_call", "id": "1", "name": "delegate_task", "arguments": {"goal": "fix bug"}},
            {
                "type": "tool_result",
                "tool_call_id": "1",
                "status": "error",
                "content": "subagent hit a blocker",
            },
            {"type": "assistant", "content": "I couldn't get the fix done in time."},
        ]
    }

    assert find(trace, "subagent-handoff-loss") is None


def test_ambiguous_handoff_marks_candidate_for_escalation() -> None:
    trace = {
        "events": [
            {"type": "tool_call", "id": "1", "name": "delegate_task", "arguments": {"goal": "fix bug"}},
            {
                "type": "tool_result",
                "tool_call_id": "1",
                "status": "success",
                "content": "subagent completed the fix",
            },
            {
                "type": "assistant",
                "content": "The subagent finished the fix, but I couldn't verify it in time.",
            },
        ]
    }

    signal = find(trace, "subagent-handoff-loss")
    assert signal is not None
    assert signal.ambiguous is True


# --- strategy-aware retry ----------------------------------------------------

def test_eventual_success_suppresses_retry_loop() -> None:
    trace = {
        "events": [
            {"type": "tool_call", "id": "1", "name": "update_record", "arguments": {"id": 42}},
            {"type": "tool_result", "tool_call_id": "1", "status": "error", "content": "timeout"},
            {"type": "tool_call", "id": "2", "name": "update_record", "arguments": {"id": 42}},
            {"type": "tool_result", "tool_call_id": "2", "status": "error", "content": "timeout"},
            {"type": "tool_call", "id": "3", "name": "update_record", "arguments": {"id": 42}},
            {"type": "tool_result", "tool_call_id": "3", "status": "success", "content": "updated"},
            {"type": "assistant", "content": "The record was successfully updated."},
        ]
    }

    assert find(trace, "retry-loop") is None
    assert find(trace, "false-success") is None


def test_strategy_sensitive_default_off_preserves_changed_args_behavior() -> None:
    trace = {
        "events": [
            {"type": "tool_call", "id": "1", "name": "update_record", "arguments": {"id": 42}},
            {"type": "tool_result", "tool_call_id": "1", "status": "error", "content": "timeout"},
            {"type": "tool_call", "id": "2", "name": "update_record", "arguments": {"id": 42, "retry": True}},
            {"type": "tool_result", "tool_call_id": "2", "status": "error", "content": "timeout"},
            {"type": "assistant", "content": "I was unable to complete the operation."},
        ]
    }

    assert find(trace, "retry-loop") is None


def test_strategy_sensitive_detects_changed_values_same_strategy() -> None:
    trace = {
        "events": [
            {"type": "tool_call", "id": "1", "name": "update_record", "arguments": {"id": 42, "mode": "sync"}},
            {"type": "tool_result", "tool_call_id": "1", "status": "error", "content": "timeout"},
            {"type": "tool_call", "id": "2", "name": "update_record", "arguments": {"id": 43, "mode": "sync"}},
            {"type": "tool_result", "tool_call_id": "2", "status": "error", "content": "timeout"},
            {"type": "assistant", "content": "I was unable to complete the operation."},
        ]
    }

    signal = find(trace, "retry-loop", strategy_sensitive=True)
    assert signal is not None
    assert signal.ambiguous is True
    assert "strategy_unchanged_attempts=2" in signal.evidence


def test_strategy_sensitive_still_exempts_structural_change() -> None:
    trace = {
        "events": [
            {"type": "tool_call", "id": "1", "name": "update_record", "arguments": {"id": 42}},
            {"type": "tool_result", "tool_call_id": "1", "status": "error", "content": "timeout"},
            {"type": "tool_call", "id": "2", "name": "update_record", "arguments": {"id": 42, "mode": "api"}},
            {"type": "tool_result", "tool_call_id": "2", "status": "error", "content": "timeout"},
            {"type": "assistant", "content": "I was unable to complete the operation."},
        ]
    }

    assert find(trace, "retry-loop", strategy_sensitive=True) is None


def test_strategy_sensitive_exempts_eventual_success() -> None:
    trace = {
        "events": [
            {"type": "tool_call", "id": "1", "name": "update_record", "arguments": {"id": 42}},
            {"type": "tool_result", "tool_call_id": "1", "status": "error", "content": "timeout"},
            {"type": "tool_call", "id": "2", "name": "update_record", "arguments": {"id": 42, "retry": True}},
            {"type": "tool_result", "tool_call_id": "2", "status": "success", "content": "updated"},
            {"type": "assistant", "content": "The record was successfully updated."},
        ]
    }

    assert find(trace, "retry-loop", strategy_sensitive=True) is None