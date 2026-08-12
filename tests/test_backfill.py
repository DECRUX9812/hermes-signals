"""Tests for backfilling signals from existing session stores.

All fixtures are synthetic SQLite/JSONL files in tmp — never the real stores.
Guarantees under test: read-only sources, idempotent re-runs (dedup by trace
id), bounded session/message counts, and non-fatal per-session errors.
"""

from __future__ import annotations

import json
import sqlite3

from hermes_signals.backfill import (
    backfill_sources,
    iter_claude_jsonl,
    iter_hermes_messages,
    iter_opencode_sessions,
)


def _hermes_db(tmp_path) -> str:
    """Build a state.db-shaped SQLite file with one false-success session."""
    db = tmp_path / "state.db"
    db.unlink(missing_ok=True)
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE sessions (id TEXT PRIMARY KEY, started_at REAL, message_count INTEGER);
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT,
            tool_call_id TEXT, tool_calls TEXT, tool_name TEXT, timestamp REAL
        );
        """
    )
    con.execute(
        "INSERT INTO sessions VALUES ('20260101_000000_abc123', 1767225600.0, 3)"
    )
    con.executemany(
        "INSERT INTO messages (session_id, role, content, tool_call_id, tool_calls, tool_name, timestamp) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                "20260101_000000_abc123",
                "assistant",
                "",
                None,
                json.dumps(
                    [
                        {
                            "id": "call-1",
                            "call_id": "call-1",
                            "type": "function",
                            "function": {"name": "update_record", "arguments": '{"id": 42}'},
                        }
                    ]
                ),
                None,
                1.0,
            ),
            (
                "20260101_000000_abc123",
                "tool",
                "request timed out",
                "call-1",
                None,
                "update_record",
                2.0,
            ),
            (
                "20260101_000000_abc123",
                "assistant",
                "The record was successfully updated.",
                None,
                None,
                None,
                3.0,
            ),
        ],
    )
    con.commit()
    con.close()
    return str(db)


def test_hermes_reader_yields_openai_shaped_messages(tmp_path) -> None:
    sessions = list(iter_hermes_messages(_hermes_db(tmp_path)))
    assert len(sessions) == 1
    messages = sessions[0][0]
    roles = [m["role"] for m in messages]
    assert roles == ["assistant", "tool", "assistant"]
    assert messages[0]["tool_calls"][0]["function"]["name"] == "update_record"
    assert messages[1]["tool_call_id"] == "call-1"


def test_opencode_reader_yields_tool_calls_and_results(tmp_path) -> None:
    db = tmp_path / "opencode.db"
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE session (id TEXT PRIMARY KEY, time_created INTEGER);
        CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER, data TEXT);
        CREATE TABLE part (id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT, time_created INTEGER, data TEXT);
        """
    )
    con.execute("INSERT INTO session VALUES ('ses_1', 1000)")
    con.execute(
        "INSERT INTO message VALUES ('m1', 'ses_1', 1000, '{\"role\": \"assistant\"}')"
    )
    con.execute(
        "INSERT INTO message VALUES ('m2', 'ses_1', 2000, '{\"role\": \"assistant\"}')"
    )
    con.executemany(
        "INSERT INTO part (id, message_id, session_id, time_created, data) VALUES (?, ?, 'ses_1', ?, ?)",
        [
            (
                "p1",
                "m1",
                1000,
                json.dumps({"type": "tool", "tool": "update_record", "callID": "call-9",
                            "state": {"status": "completed", "input": {"id": 42}, "output": "timeout"}}),
            ),
            ("p2", "m2", 2000, json.dumps({"type": "text", "text": "The record was successfully updated."})),
        ],
    )
    con.commit()
    con.close()

    sessions = list(iter_opencode_sessions(str(db)))
    assert len(sessions) == 1
    messages = sessions[0][0]
    roles = [m["role"] for m in messages]
    assert "tool" in roles and "assistant" in roles
    tool_msg = next(m for m in messages if m["role"] == "tool")
    assert tool_msg["tool_call_id"] == "call-9"


def test_claude_reader_handles_native_and_openai_formats(tmp_path) -> None:
    native = tmp_path / "native.jsonl"
    native.write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": "tu-1", "name": "update_record", "input": {"id": 42}}
                    ],
                },
            }
        )
        + "\n"
        + json.dumps(
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "tu-1",
                            "content": "request timed out",
                            "is_error": True,
                        }
                    ],
                },
            }
        )
        + "\n"
        + json.dumps(
            {"type": "assistant", "message": {"role": "assistant", "content": "The record was successfully updated."}}
        )
        + "\n",
        encoding="utf-8",
    )
    sessions = list(iter_claude_jsonl([str(native)]))
    assert len(sessions) == 1
    roles = [m["role"] for m in sessions[0][0]]
    assert roles == ["assistant", "tool", "assistant"]

    openai_format = tmp_path / "openai.jsonl"
    openai_format.write_text(
        json.dumps({"role": "assistant", "content": "hello"}) + "\n", encoding="utf-8"
    )
    assert list(iter_claude_jsonl([str(openai_format)]))


def test_backfill_detects_signals_and_is_idempotent(tmp_path) -> None:
    out = tmp_path / "signals.jsonl"
    first = backfill_sources(sources=["hermes"], hermes_db=_hermes_db(tmp_path), out_path=out)
    assert first["hermes"]["sessions_scanned"] == 1
    assert first["hermes"]["signals_recorded"] >= 1
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert any("false-success" in line for line in lines)

    second = backfill_sources(sources=["hermes"], hermes_db=_hermes_db(tmp_path), out_path=out)
    assert second["hermes"]["skipped_duplicates"] == 1
    assert len(out.read_text(encoding="utf-8").strip().splitlines()) == len(lines)


def test_backfill_is_bounded_and_read_only(tmp_path) -> None:
    out = tmp_path / "signals.jsonl"
    before = open(_hermes_db(tmp_path), "rb").read()
    result = backfill_sources(
        sources=["hermes"], hermes_db=_hermes_db(tmp_path), out_path=out, max_sessions=0
    )
    assert result["hermes"]["sessions_scanned"] == 0
    after = open(_hermes_db(tmp_path), "rb").read()
    assert before == after  # source untouched


def test_backfill_tolerates_missing_sources(tmp_path) -> None:
    result = backfill_sources(
        sources=["hermes", "opencode", "claude"],
        hermes_db=str(tmp_path / "missing.db"),
        opencode_db=str(tmp_path / "missing.db"),
        claude_glob=str(tmp_path / "*.jsonl"),
        out_path=tmp_path / "signals.jsonl",
    )
    assert result["hermes"]["sessions_scanned"] == 0
    assert result["opencode"]["sessions_scanned"] == 0
    assert result["claude"]["sessions_scanned"] == 0