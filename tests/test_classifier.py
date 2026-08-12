from __future__ import annotations

from hermes_signals.classifier import classify_trace, stable_trace_id, trace_from_conversation


def ids(trace: dict) -> set[str]:
    return {signal.signal_id for signal in classify_trace(trace)}


def test_clean_verified_trace_has_no_signals() -> None:
    trace = {
        "events": [
            {"type": "tool_call", "id": "1", "name": "write_file", "arguments": {"path": "app.py"}},
            {"type": "tool_result", "tool_call_id": "1", "status": "success", "content": "written"},
            {"type": "tool_call", "id": "2", "name": "terminal", "arguments": {"command": "pytest -q"}},
            {"type": "tool_result", "tool_call_id": "2", "status": "success", "content": "3 passed"},
            {"type": "assistant", "content": "Implemented and verified the change; tests pass."},
        ]
    }

    assert ids(trace) == set()


def test_detects_false_success_after_failed_tool_call() -> None:
    trace = {
        "events": [
            {"type": "tool_call", "id": "1", "name": "update_record", "arguments": {"id": 42}},
            {"type": "tool_result", "tool_call_id": "1", "status": "error", "content": "request timed out"},
            {"type": "assistant", "content": "The record was successfully updated."},
        ]
    }

    signals = classify_trace(trace)
    false_success = next(signal for signal in signals if signal.signal_id == "false-success")
    assert false_success.severity == "high"
    assert false_success.evidence
    assert all("timed out" not in item for item in false_success.evidence)


def test_ignores_failure_when_assistant_admits_it() -> None:
    trace = {
        "events": [
            {"type": "tool_call", "id": "1", "name": "update_record", "arguments": {"id": 42}},
            {"type": "tool_result", "tool_call_id": "1", "status": "error", "content": "request timed out"},
            {"type": "assistant", "content": "I couldn't update the record because the request timed out."},
        ]
    }

    assert "false-success" not in ids(trace)


def test_eventual_success_is_not_false_success() -> None:
    trace = {
        "events": [
            {"type": "tool_call", "id": "1", "name": "update_record", "arguments": {"id": 42}},
            {"type": "tool_result", "tool_call_id": "1", "status": "error", "content": "timeout"},
            {"type": "tool_call", "id": "2", "name": "update_record", "arguments": {"id": 42}},
            {"type": "tool_result", "tool_call_id": "2", "status": "success", "content": "updated"},
            {"type": "assistant", "content": "The record was successfully updated."},
        ]
    }

    assert "false-success" not in ids(trace)


def test_detects_repeated_identical_failed_tool_attempts() -> None:
    trace = {
        "events": [
            {"type": "tool_call", "id": "1", "name": "update_record", "arguments": {"id": 42}},
            {"type": "tool_result", "tool_call_id": "1", "status": "error", "content": "timeout"},
            {"type": "tool_call", "id": "2", "name": "update_record", "arguments": {"id": 42}},
            {"type": "tool_result", "tool_call_id": "2", "status": "error", "content": "timeout"},
            {"type": "assistant", "content": "I was unable to complete the operation."},
        ]
    }

    assert "retry-loop" in ids(trace)


def test_changed_strategy_is_not_a_retry_loop() -> None:
    trace = {
        "events": [
            {"type": "tool_call", "id": "1", "name": "update_record", "arguments": {"id": 42}},
            {"type": "tool_result", "tool_call_id": "1", "status": "error", "content": "timeout"},
            {"type": "tool_call", "id": "2", "name": "update_record", "arguments": {"id": 42, "retry": True}},
            {"type": "tool_result", "tool_call_id": "2", "status": "error", "content": "timeout"},
            {"type": "assistant", "content": "I was unable to complete the operation."},
        ]
    }

    assert "retry-loop" not in ids(trace)


def test_detects_unverified_file_change() -> None:
    trace = {
        "events": [
            {"type": "tool_call", "id": "1", "name": "patch", "arguments": {"path": "app.py"}},
            {"type": "tool_result", "tool_call_id": "1", "status": "success", "content": "patched"},
            {"type": "assistant", "content": "The code change is complete."},
        ]
    }

    assert "unverified-change" in ids(trace)


def test_secret_signal_redacts_evidence_and_arguments() -> None:
    secret = "sk-abcdefghijklmnopqrstuvwxyz1234"
    trace = {
        "events": [
            {"type": "tool_call", "name": "terminal", "arguments": {"command": f"token={secret}"}},
        ]
    }

    signals = classify_trace(trace)
    secret_signal = next(signal for signal in signals if signal.signal_id == "secret-risk")
    assert secret not in repr(secret_signal)
    assert secret_signal.severity == "critical"


def test_low_entropy_values_are_not_secret_risk() -> None:
    trace = {
        "events": [
            {
                "type": "tool_call",
                "name": "update_record",
                "arguments": {"mode": "api", "secret": "000000000000"},
            },
        ]
    }

    assert "secret-risk" not in ids(trace)


def test_repeated_low_entropy_value_is_not_secret_risk() -> None:
    trace = {
        "events": [
            {
                "type": "tool_call",
                "name": "terminal",
                "arguments": {"command": "token=aaaaaaaaaaaaaaaaaaaa"},
            },
        ]
    }

    assert "secret-risk" not in ids(trace)


def test_high_entropy_generic_secret_still_fires() -> None:
    trace = {
        "events": [
            {
                "type": "tool_call",
                "name": "terminal",
                "arguments": {"command": "token=K9xQm2Vp7LzR4tW8cB1nF3jH5sD6gY0a"},
            },
        ]
    }

    assert "secret-risk" in ids(trace)


def test_strong_prefix_token_always_fires_regardless_of_entropy() -> None:
    trace = {
        "events": [
            {
                "type": "tool_call",
                "name": "terminal",
                "arguments": {"command": "ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
            },
        ]
    }

    assert "secret-risk" in ids(trace)


def test_trace_adapter_maps_tool_calls_and_failures() -> None:
    messages = [
        {
            "role": "assistant",
            "tool_calls": [
                {"id": "call-1", "function": {"name": "deploy", "arguments": "{\"env\": \"prod\"}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "call-1", "content": "request timeout"},
    ]

    trace = trace_from_conversation(messages, final_response="Deployment completed successfully.")
    assert "false-success" in ids(trace)


def test_stable_trace_id_is_deterministic_and_short() -> None:
    trace = {"events": [{"type": "assistant", "content": "hello"}]}

    assert stable_trace_id(trace) == stable_trace_id(trace)
    assert len(stable_trace_id(trace)) == 12
