"""Tests for the weekly digest and its cron installer."""

from __future__ import annotations

import sys
import types

from hermes_signals.digest import build_digest_markdown, cron_install
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


def _seed(tmp_path) -> None:
    record_turn(
        FALSE_SUCCESS_MESSAGES,
        final_response="The record was successfully updated.",
        path=tmp_path / "signals.jsonl",
    )
    record_feedback("t1", "false-success", "correct", path=tmp_path / "signals-feedback.jsonl")


def test_digest_markdown_contains_real_numbers(tmp_path) -> None:
    _seed(tmp_path)
    markdown = build_digest_markdown(hermes_home=tmp_path)
    assert "# Hermes Signals" in markdown
    assert "false-success" in markdown
    assert "Precision" in markdown
    assert "correct" in markdown.lower()
    assert "100" in markdown  # 1 correct / 0 fp = 100%


def test_digest_is_bounded_and_has_no_raw_content(tmp_path) -> None:
    _seed(tmp_path)
    markdown = build_digest_markdown(hermes_home=tmp_path)
    assert "request timed out" not in markdown
    assert len(markdown) < 4000


def test_cron_install_registers_no_agent_job(tmp_path) -> None:
    fake = types.ModuleType("cron")
    fake_jobs = types.ModuleType("cron.jobs")
    fake_jobs.create_job = lambda **kw: {"id": "job-weekly", **kw}
    fake.jobs = fake_jobs
    sys.modules["cron"] = fake
    sys.modules["cron.jobs"] = fake_jobs
    try:
        result = cron_install(hermes_home=tmp_path)
    finally:
        sys.modules.pop("cron", None)
        sys.modules.pop("cron.jobs", None)

    assert result["installed"] is True
    assert result["job_id"] == "job-weekly"
    script = tmp_path / "scripts" / "signals-weekly-digest.py"
    assert script.exists()
    assert "build_digest_markdown" in script.read_text(encoding="utf-8")


def test_cron_install_fallback_when_hermes_absent(tmp_path) -> None:
    sys.modules.pop("cron", None)
    result = cron_install(hermes_home=tmp_path)
    assert result["installed"] is False
    assert "hermes cron add" in result["manual"]