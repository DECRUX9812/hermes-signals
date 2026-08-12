from __future__ import annotations

import json

from hermes_signals.cli import main
from hermes_signals.store import record_turn


def test_demo_json_is_machine_readable(capsys) -> None:
    assert main(["demo", "--output", "json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["trace_id"]
    assert "false-success" in {item["signal_id"] for item in payload["signals"]}


def test_scan_prints_actionable_redacted_summary(tmp_path, capsys) -> None:
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(
        json.dumps(
            {
                "events": [
                    {"type": "tool_call", "id": "1", "name": "update_record", "arguments": {"id": 42}},
                    {"type": "tool_result", "tool_call_id": "1", "status": "error", "content": "timeout"},
                    {"type": "assistant", "content": "The record was successfully updated."},
                ]
            }
        ),
        encoding="utf-8",
    )

    assert main(["scan", str(trace_path)]) == 0
    output = capsys.readouterr().out
    assert "false-success" in output
    assert "HIGH" in output
    assert "timeout" not in output


def test_scan_bad_json_returns_usage_error(tmp_path, capsys) -> None:
    path = tmp_path / "bad.json"
    path.write_text("not json", encoding="utf-8")

    assert main(["scan", str(path)]) == 2
    assert "cannot read trace" in capsys.readouterr().out


def test_record_turn_persists_only_bounded_signal_data(tmp_path) -> None:
    secret = "ghp_123456789012345678901234567890"
    payload = record_turn(
        messages=[
            {"role": "tool", "tool_call_id": "1", "content": f"token={secret}"},
            {"role": "assistant", "content": "I found a token."},
        ],
        final_response="I found a token.",
        path=tmp_path / "signals.jsonl",
    )

    saved = (tmp_path / "signals.jsonl").read_text(encoding="utf-8")
    assert payload["signals"][0]["signal_id"] == "secret-risk"
    assert secret not in saved
    assert secret not in json.dumps(payload)
