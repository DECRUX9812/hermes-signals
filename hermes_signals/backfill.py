"""Backfill signals from existing session stores.

The plug-and-forget value moment: on install (or any time), scan the session
history the user already has — Hermes ``state.db``, OpenCode ``opencode.db``,
Claude Desktop JSONL — classify each session, and seed ``signals.jsonl`` so the
report is about real agent behavior from day one.

Guarantees:

- sources are opened read-only and never mutated;
- re-runs are idempotent (records are deduplicated by content trace id);
- every source/session is bounded (``max_sessions``, ``max_messages``);
- a broken session or missing store never aborts the whole backfill.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hermes_signals.classifier import classify_trace, stable_trace_id, trace_from_conversation
from hermes_signals.store import append_payload, default_store_path, read_signals

__all__ = [
    "backfill_sources",
    "iter_claude_jsonl",
    "iter_hermes_messages",
    "iter_opencode_sessions",
]

_DEFAULT_MAX_SESSIONS = 200
_DEFAULT_MAX_MESSAGES = 2000
_SESSION_TUPLE = tuple[list[dict[str, Any]], str]


def _hermes_home() -> Path:
    import os

    return Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))


def _normalize_tool_calls(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw, list):
        return []
    normalized: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        function = entry.get("function", entry)
        if not isinstance(function, dict):
            continue
        args = function.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = function.get("arguments")
        normalized.append(
            {
                "id": str(entry.get("id", entry.get("call_id", ""))),
                "function": {"name": str(function.get("name", "")), "arguments": args},
            }
        )
    return normalized


def iter_hermes_messages(
    db_path: str | Path,
    *,
    max_sessions: int = _DEFAULT_MAX_SESSIONS,
    max_messages: int = _DEFAULT_MAX_MESSAGES,
) -> Iterator[_SESSION_TUPLE]:
    """Yield (openai_messages, session_id) per recent Hermes session."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        rows = cur.execute(
            "SELECT id FROM sessions ORDER BY started_at DESC LIMIT ?", (max_sessions,)
        ).fetchall()
        for (session_id,) in rows:
            yield _hermes_session(cur, session_id, max_messages)
    finally:
        con.close()


def _hermes_session(cur: sqlite3.Cursor, session_id: str, max_messages: int) -> _SESSION_TUPLE:
    rows = cur.execute(
        "SELECT role, content, tool_call_id, tool_calls FROM messages "
        "WHERE session_id = ? ORDER BY id",
        (session_id,),
    ).fetchall()
    messages: list[dict[str, Any]] = []
    final_response = ""
    for role, content, tool_call_id, tool_calls in rows:
        if role == "assistant" and tool_calls:
            messages.append(
                {"role": "assistant", "tool_calls": _normalize_tool_calls(tool_calls)}
            )
        elif role == "tool":
            messages.append(
                {"role": "tool", "tool_call_id": str(tool_call_id or ""), "content": str(content or "")}
            )
        elif role == "user" and content:
            messages.append({"role": "user", "content": str(content)})
        elif role == "assistant" and content:
            final_response = str(content)
            messages.append({"role": "assistant", "content": final_response})
    return messages[-max_messages:], session_id


def iter_opencode_sessions(
    db_path: str | Path,
    *,
    max_sessions: int = _DEFAULT_MAX_SESSIONS,
    max_messages: int = _DEFAULT_MAX_MESSAGES,
) -> Iterator[_SESSION_TUPLE]:
    """Yield (openai_messages, session_id) per recent OpenCode session."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        rows = cur.execute(
            "SELECT id FROM session ORDER BY time_created DESC LIMIT ?", (max_sessions,)
        ).fetchall()
        for (session_id,) in rows:
            yield _opencode_session(cur, session_id, max_messages)
    finally:
        con.close()


def _opencode_session(cur: sqlite3.Cursor, session_id: str, max_messages: int) -> _SESSION_TUPLE:
    messages: list[dict[str, Any]] = []
    message_rows = cur.execute(
        "SELECT id, data FROM message WHERE session_id = ? ORDER BY time_created", (session_id,)
    ).fetchall()
    for message_id, data in message_rows:
        try:
            meta = json.loads(data)
        except json.JSONDecodeError:
            meta = {}
        role = meta.get("role", "")
        parts = cur.execute(
            "SELECT data FROM part WHERE message_id = ? ORDER BY time_created", (message_id,)
        ).fetchall()
        assistant_text: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        for (part_data,) in parts:
            try:
                part = json.loads(part_data)
            except json.JSONDecodeError:
                continue
            kind = part.get("type")
            if kind == "text" and part.get("text"):
                assistant_text.append(str(part["text"]))
            elif kind == "tool":
                state = part.get("state", {}) or {}
                call_id = str(part.get("callID", ""))
                tool_calls.append(
                    {
                        "id": call_id,
                        "function": {
                            "name": str(part.get("tool", "")),
                            "arguments": state.get("input", {}),
                        },
                    }
                )
                status = state.get("status", "completed")
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": str(state.get("output", "")),
                        "error": status not in ("completed", "success"),
                    }
                )
        if role == "assistant":
            if assistant_text:
                messages.append({"role": "assistant", "content": " ".join(assistant_text)})
            if tool_calls:
                messages.append({"role": "assistant", "tool_calls": tool_calls})
        elif role == "user" and assistant_text:
            messages.append({"role": "user", "content": " ".join(assistant_text)})
    return messages[-max_messages:], session_id


def iter_claude_jsonl(
    paths: list[str | Path],
    *,
    max_sessions: int = _DEFAULT_MAX_SESSIONS,
    max_messages: int = _DEFAULT_MAX_MESSAGES,
) -> Iterator[_SESSION_TUPLE]:
    """Yield (openai_messages, source_name) per Claude Desktop session file.

    Tolerates both Claude's native envelope and plain OpenAI-format JSONL.
    """
    for path in paths[:max_sessions]:
        messages: list[dict[str, Any]] = []
        try:
            with Path(path).open(encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    adapted = _adapt_claude_item(item)
                    if adapted:
                        messages.extend(adapted)
        except OSError:
            continue
        if messages:
            yield messages[-max_messages:], str(path)


def _adapt_claude_item(item: dict[str, Any]) -> list[dict[str, Any]]:
    if "role" in item:
        # Plain OpenAI-style line.
        return [item] if isinstance(item.get("content"), str) or item.get("tool_calls") else []
    message = item.get("message")
    if not isinstance(message, dict):
        return []
    role = message.get("role")
    content = message.get("content")
    if not isinstance(content, list):
        text = message.get("content")
        return [{"role": role, "content": str(text)}] if role == "assistant" and text else []
    adapted: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    if role == "assistant":
        for block in content:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "text" and block.get("text"):
                adapted.append({"role": "assistant", "content": str(block["text"])})
            elif kind == "tool_use":
                tool_calls.append(
                    {
                        "id": str(block.get("id", "")),
                        "function": {
                            "name": str(block.get("name", "")),
                            "arguments": block.get("input", {}),
                        },
                    }
                )
        if tool_calls:
            adapted.append({"role": "assistant", "tool_calls": tool_calls})
    elif role == "user":
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_result":
                body = block.get("content")
                if isinstance(body, list):
                    body = " ".join(
                        str(part.get("text", "")) for part in body if isinstance(part, dict)
                    )
                adapted.append(
                    {
                        "role": "tool",
                        "tool_call_id": str(block.get("tool_use_id", "")),
                        "content": str(body or ""),
                        "error": bool(block.get("is_error")),
                    }
                )
            elif block.get("type") == "text" and block.get("text"):
                adapted.append({"role": "user", "content": str(block["text"])})
    return adapted


def _default_sources() -> dict[str, str]:
    return {
        "hermes": str(_hermes_home() / "state.db"),
        "opencode": str(Path.home() / ".local" / "share" / "opencode" / "opencode.db"),
        "claude": str(Path.home() / ".claude" / "projects" / "*" / "*.jsonl"),
    }


def backfill_sources(
    sources: list[str] | None = None,
    *,
    hermes_db: str | Path | None = None,
    opencode_db: str | Path | None = None,
    claude_glob: str | None = None,
    out_path: str | Path | None = None,
    max_sessions: int = _DEFAULT_MAX_SESSIONS,
    max_messages: int = _DEFAULT_MAX_MESSAGES,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Classify recent sessions from the requested stores and seed the store.

    Returns a per-source summary. Never mutates the source stores.
    """
    sources = list(sources or ["hermes", "opencode", "claude"])
    defaults = _default_sources()
    paths: dict[str, str] = {
        "hermes": str(hermes_db or defaults["hermes"]),
        "opencode": str(opencode_db or defaults["opencode"]),
        "claude": claude_glob or defaults["claude"],
    }
    destination = Path(out_path or default_store_path())
    existing = {str(record.get("trace_id")) for record in read_signals(destination)}

    iterators: dict[str, Callable[[], Iterator[_SESSION_TUPLE]]] = {
        "hermes": lambda: iter_hermes_messages(
            paths["hermes"], max_sessions=max_sessions, max_messages=max_messages
        ),
        "opencode": lambda: iter_opencode_sessions(
            paths["opencode"], max_sessions=max_sessions, max_messages=max_messages
        ),
        "claude": lambda: iter_claude_jsonl(
            sorted(Path(Path(paths["claude"]).parent).glob(Path(paths["claude"]).name)),
            max_sessions=max_sessions,
            max_messages=max_messages,
        ),
    }

    summary: dict[str, Any] = {}
    for source in sources:
        summary[source] = {"sessions_scanned": 0, "signals_recorded": 0, "skipped_duplicates": 0}
        if source not in iterators:
            continue
        try:
            session_iter = iterators[source]()
        except Exception:
            continue
        try:
            for messages, session_id in session_iter:
                summary[source]["sessions_scanned"] += 1
                try:
                    final_response = next(
                        (str(m["content"]) for m in reversed(messages) if m.get("content")), ""
                    )
                    trace = trace_from_conversation(messages, final_response=final_response)
                    trace_id = stable_trace_id(trace)
                    if trace_id in existing:
                        summary[source]["skipped_duplicates"] += 1
                        continue
                    signals = classify_trace(trace)
                    if not signals:
                        continue
                    payload = {
                        "trace_id": trace_id,
                        "session_id": str(session_id)[:128],
                        "platform": source,
                        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
                        "signals": [signal.to_dict() for signal in signals],
                    }
                    if not dry_run:
                        append_payload(payload, destination)
                        existing.add(trace_id)
                    summary[source]["signals_recorded"] += 1
                except Exception:
                    continue
        except Exception:
            # Source-level failure (missing/corrupt store): report zero scanned
            # rather than aborting the whole backfill.
            summary[source]["sessions_scanned"] = 0
            continue
    return summary