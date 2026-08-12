"""Tests for the install self-check ("armed" marker) and status report."""

from __future__ import annotations

import json

from hermes_signals.status import arm_if_needed, status_report
from hermes_signals.store import record_feedback, record_turn

FALSE_SUCCESS_MESSAGES = [
    {
        "role": "assistant",
        "tool_calls": [
            {"id": "call-1", "function": {"name": "update_record", "arguments": '{"id": 42}'}}
        ],
    },
    {"role": "tool", "tool_call_id": "call-1", "content": "request timed out"},
]


def test_arm_happens_once_per_install(tmp_path) -> None:
    assert arm_if_needed(hermes_home=tmp_path) is True
    assert arm_if_needed(hermes_home=tmp_path) is False
    marker = json.loads((tmp_path / "signals-armed.json").read_text(encoding="utf-8"))
    assert marker["armed_at"]
    assert marker["version"]


def test_status_report_counts_stores(tmp_path) -> None:
    arm_if_needed(hermes_home=tmp_path)
    record_turn(
        FALSE_SUCCESS_MESSAGES,
        final_response="The record was successfully updated.",
        path=tmp_path / "signals.jsonl",
    )
    record_turn(
        FALSE_SUCCESS_MESSAGES,
        final_response="The record was successfully updated.",
        path=tmp_path / "signals.jsonl",
    )
    record_feedback("t1", "false-success", "correct", path=tmp_path / "signals-feedback.jsonl")

    report = status_report(hermes_home=tmp_path)
    assert report["armed"] is True
    assert report["signals_recorded"] == 2
    assert report["feedback_recorded"] == 1
    assert report["signals_by_type"] == {"false-success": 2}
    assert report["escalation"]["mode"] in ("env", "hermes", "local", "off")


def test_status_report_before_arming(tmp_path) -> None:
    report = status_report(hermes_home=tmp_path)
    assert report["armed"] is False
    assert report["signals_recorded"] == 0