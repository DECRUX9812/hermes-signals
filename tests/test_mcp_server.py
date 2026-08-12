"""Tests for the MCP server tool handlers.

The handlers are plain async functions importable without the optional ``mcp``
SDK. These tests exercise the real classifier through the MCP tool interface
via ``asyncio.run`` so no extra test dependency (and no running MCP client) is
needed.
"""

from __future__ import annotations

import asyncio
import json

from hermes_signals.mcp_server import demo, scan_trace, scan_trace_file

TRUE_SUCCESS = json.dumps(
    {
        "events": [
            {"type": "tool_call", "id": "1", "name": "deploy", "arguments": {}},
            {"type": "tool_result", "tool_call_id": "1", "status": "ok", "content": "done"},
            {"type": "assistant", "content": "Deployment completed successfully."},
        ]
    }
)

FALSE_SUCCESS = json.dumps(
    {
        "events": [
            {"type": "tool_call", "id": "1", "name": "update_record", "arguments": {"id": 42}},
            {
                "type": "tool_result",
                "tool_call_id": "1",
                "status": "error",
                "content": "request timed out",
            },
            {"type": "assistant", "content": "The record was successfully updated."},
        ]
    }
)


def _run(coro):
    return asyncio.run(coro)


def test_scan_trace_returns_serializable_payload() -> None:
    payload = json.loads(_run(scan_trace(TRUE_SUCCESS)))
    assert isinstance(payload["trace_id"], str)
    assert payload["signals"] == []


def test_scan_trace_detects_false_success() -> None:
    payload = json.loads(_run(scan_trace(FALSE_SUCCESS)))
    ids = {s["signal_id"] for s in payload["signals"]}
    assert "false-success" in ids


def test_scan_trace_rejects_non_object() -> None:
    payload = json.loads(_run(scan_trace("[1,2,3]")))
    assert "error" in payload


def test_scan_trace_rejects_invalid_json() -> None:
    payload = json.loads(_run(scan_trace("not json")))
    assert "error" in payload


def test_demo_detects_false_success() -> None:
    payload = json.loads(_run(demo()))
    assert any(s["signal_id"] == "false-success" for s in payload["signals"])


def test_scan_trace_file_reads_trace(tmp_path) -> None:
    trace_file = tmp_path / "trace.json"
    trace_file.write_text(FALSE_SUCCESS, encoding="utf-8")
    payload = json.loads(_run(scan_trace_file(str(trace_file))))
    assert any(s["signal_id"] == "false-success" for s in payload["signals"])


def test_scan_trace_file_missing_path(tmp_path) -> None:
    payload = json.loads(_run(scan_trace_file(str(tmp_path / "does-not-exist.json"))))
    assert "error" in payload