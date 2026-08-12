"""Tests for v0.3 feedback ingestion and precision reporting.

Feedback labels map to Discord reactions: ✅ → correct, ❌ → false_positive,
🛠️ → policy (the label is a policy suggestion, not a correctness verdict).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes_signals.store import (
    default_feedback_path,
    precision_report,
    record_feedback,
    record_turn,
)

FALSE_SUCCESS_MESSAGES = [
    {
        "role": "assistant",
        "tool_calls": [
            {"id": "call-1", "function": {"name": "update_record", "arguments": '{"id": 42}'}}
        ],
    },
    {"role": "tool", "tool_call_id": "call-1", "content": "request timed out"},
]


def test_record_feedback_validates_label(tmp_path) -> None:
    with pytest.raises(ValueError):
        record_feedback("abc", "false-success", "maybe", path=tmp_path / "fb.jsonl")


def test_record_feedback_appends_and_returns_record(tmp_path) -> None:
    path = tmp_path / "fb.jsonl"
    record = record_feedback("trace-1", "false-success", "correct", path=path, source="discord")

    assert record["trace_id"] == "trace-1"
    assert record["signal_id"] == "false-success"
    assert record["label"] == "correct"
    assert record["source"] == "discord"
    assert record["ts"]
    assert path.read_text(encoding="utf-8").count("\n") == 1


def test_record_feedback_is_append_only(tmp_path) -> None:
    path = tmp_path / "fb.jsonl"
    record_feedback("t1", "retry-loop", "false_positive", path=path)
    record_feedback("t2", "retry-loop", "correct", path=path)
    assert path.read_text(encoding="utf-8").count("\n") == 2


def test_precision_report_empty_feedback(tmp_path) -> None:
    signals_path = tmp_path / "signals.jsonl"
    record_turn(
        FALSE_SUCCESS_MESSAGES,
        final_response="The record was successfully updated.",
        path=signals_path,
    )
    report = precision_report(signals_path=signals_path, feedback_path=tmp_path / "fb.jsonl")

    row = report["signals"]["false-success"]
    assert row["matched"] == 1
    assert row["correct"] == 0
    assert row["false_positive"] == 0
    assert row["precision"] is None


def test_precision_report_computes_correct_math(tmp_path) -> None:
    fb_path = tmp_path / "fb.jsonl"
    record_feedback("t1", "false-success", "correct", path=fb_path)
    record_feedback("t2", "false-success", "correct", path=fb_path)
    record_feedback("t3", "false-success", "false_positive", path=fb_path)
    record_feedback("t4", "false-success", "policy", path=fb_path)

    report = precision_report(signals_path=tmp_path / "signals.jsonl", feedback_path=fb_path)
    row = report["signals"]["false-success"]
    assert row["correct"] == 2
    assert row["false_positive"] == 1
    assert row["policy"] == 1
    assert abs(row["precision"] - 2 / 3) < 1e-3


def test_precision_report_aggregates_per_signal(tmp_path) -> None:
    fb_path = tmp_path / "fb.jsonl"
    record_feedback("t1", "false-success", "correct", path=fb_path)
    record_feedback("t1", "retry-loop", "false_positive", path=fb_path)

    report = precision_report(signals_path=tmp_path / "signals.jsonl", feedback_path=fb_path)
    assert report["signals"]["false-success"]["correct"] == 1
    assert report["signals"]["retry-loop"]["false_positive"] == 1


def test_default_feedback_path_is_profile_aware() -> None:
    path = default_feedback_path()
    assert path.name == "signals-feedback.jsonl"


def test_fallback_honors_hermes_home_env(monkeypatch) -> None:
    import os

    from hermes_signals.store import default_feedback_path, default_store_path

    monkeypatch.setenv("HERMES_HOME", "/tmp/custom-hermes-home")
    assert default_store_path() == Path("/tmp/custom-hermes-home") / "signals.jsonl"
    assert default_feedback_path() == Path("/tmp/custom-hermes-home") / "signals-feedback.jsonl"
    monkeypatch.delenv("HERMES_HOME")
    # Unset: falls back under the real home dir.
    assert str(default_store_path()).endswith(f"{os.sep}.hermes{os.sep}signals.jsonl")