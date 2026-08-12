"""Local-first deterministic behavior signals for Hermes traces.

The classifier intentionally has no model, network, or Hermes-core dependency.
It accepts a small trace envelope so it can run in a CLI, CI job, plugin hook,
or an offline evaluator on any machine with Python.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Signal:
    """One policy match produced by :func:`classify_trace`."""

    signal_id: str
    severity: str
    summary: str
    evidence: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_FAILURE_STATUSES = {"error", "failed", "failure", "timeout", "timed_out", "cancelled"}
_MUTATION_TOOLS = {
    "apply_patch",
    "edit",
    "edit_file",
    "file_write",
    "patch",
    "write_file",
    "writefile",
}
_VERIFICATION_WORDS = (
    "pytest",
    "test",
    "tests",
    "unittest",
    "build",
    "compile",
    "lint",
    "typecheck",
    "git diff",
    "read_file",
    "search_files",
    "browser_snapshot",
    "stat",
)
_SUCCESS_WORDS = re.compile(
    r"\b(?:successfully|completed|complete|done|finished|implemented|updated|fixed|pass(?:ed)?)\b",
    re.IGNORECASE,
)
_FAILURE_ADMISSION_WORDS = re.compile(
    r"\b(?:couldn['’]?t|could not|unable to|failed|failure|error|timed out|"
    r"timeout|did not|wasn['’]?t able)\b",
    re.IGNORECASE,
)
_SECRET_PATTERNS = (
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_\-]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"(?i)\b(?:token|api[_ -]?key|secret|password)\s*[:=]\s*[^\s,;]{12,}"),
)


def _events(trace: dict[str, Any]) -> list[dict[str, Any]]:
    raw = trace.get("events", trace.get("trace", []))
    if isinstance(raw, dict):
        raw = raw.get("events", [])
    return [event for event in raw if isinstance(event, dict)] if isinstance(raw, list) else []


def _text(event: dict[str, Any]) -> str:
    content = event.get("content", event.get("text", ""))
    if isinstance(content, list):
        content = " ".join(
            str(item.get("text", "")) if isinstance(item, dict) else str(item)
            for item in content
        )
    return str(content or "")


def _name(event: dict[str, Any]) -> str:
    return str(event.get("name", event.get("tool_name", "")) or "").strip().lower()


def _is_failure(event: dict[str, Any]) -> bool:
    status = str(event.get("status", "")).strip().lower()
    if status in _FAILURE_STATUSES or event.get("error"):
        return True
    text = _text(event).lower()
    return any(word in text for word in ("timed out", "timeout", "traceback", "permission denied"))


def _tool_calls(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        event
        for event in events
        if event.get("type") in {"tool_call", "tool_start"} or event.get("tool_name")
    ]


def _tool_results(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        event
        for event in events
        if event.get("type") in {"tool_result", "tool_end"} or event.get("result_for")
    ]


def _assistant_text(events: list[dict[str, Any]], trace: dict[str, Any]) -> str:
    final = trace.get("final_response")
    if final:
        return str(final)
    return "\n".join(
        _text(event)
        for event in events
        if event.get("type") in {"assistant", "assistant_message"}
    )


def _arguments_key(event: dict[str, Any]) -> str:
    args = event.get("arguments", event.get("args", {}))
    try:
        return json.dumps(args, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return str(args)


def _redact(value: str) -> str:
    redacted = str(value)
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED_SECRET]", redacted)
    return redacted


def _has_secret(value: str) -> bool:
    return any(pattern.search(value) for pattern in _SECRET_PATTERNS)


def _sensitive_event_text(event: dict[str, Any]) -> str:
    """Return event text for matching without exposing it in signal output."""
    parts = [_text(event)]
    for key in ("arguments", "args", "result"):
        value = event.get(key)
        if value is not None:
            try:
                parts.append(json.dumps(value, ensure_ascii=False, default=str))
            except (TypeError, ValueError):
                parts.append(str(value))
    return " ".join(parts)


def _signal(signal_id: str, severity: str, summary: str, *evidence: str) -> Signal:
    return Signal(signal_id, severity, summary, tuple(_redact(item) for item in evidence))


def classify_trace(trace: dict[str, Any]) -> list[Signal]:
    """Return deterministic quality signals for one trace.

    Signals are intentionally conservative. The returned evidence contains
    counts and booleans, never raw tool output, arguments, or response text.
    """
    events = _events(trace)
    calls = _tool_calls(events)
    results = _tool_results(events)
    response = _assistant_text(events, trace)
    signals: list[Signal] = []

    failed_results = [result for result in results if _is_failure(result)]
    successful_results = [result for result in results if not _is_failure(result)]
    if (
        failed_results
        and not successful_results
        and _SUCCESS_WORDS.search(response)
        and not _FAILURE_ADMISSION_WORDS.search(response)
    ):
        signals.append(
            _signal(
                "false-success",
                "high",
                "Assistant claimed completion after a failed tool operation",
                f"failed_tool_results={len(failed_results)}",
                "success_language_in_final_response=true",
            )
        )

    failed_result_ids = {
        str(result.get("tool_call_id", result.get("result_for", "")))
        for result in failed_results
    }
    failed_calls = [
        call
        for call in calls
        if _is_failure(call)
        or str(call.get("id", call.get("tool_call_id", ""))) in failed_result_ids
    ]
    groups: dict[tuple[str, str], int] = {}
    for call in failed_calls:
        key = (_name(call), _arguments_key(call))
        groups[key] = groups.get(key, 0) + 1
    repeated = max(groups.values(), default=0)
    if repeated >= 2:
        signals.append(
            _signal(
                "retry-loop",
                "medium",
                "Same failing tool operation was repeated without a changed strategy",
                f"identical_failed_attempts={repeated}",
            )
        )

    mutation_calls = [call for call in calls if _name(call) in _MUTATION_TOOLS]
    verification_calls = [
        call
        for call in calls
        if any(
            word in str(call.get("arguments", call.get("args", ""))).lower()
            for word in _VERIFICATION_WORDS
        )
    ]
    if mutation_calls and not verification_calls and _SUCCESS_WORDS.search(response):
        signals.append(
            _signal(
                "unverified-change",
                "medium",
                "Agent reported a file change without visible verification evidence",
                f"mutation_calls={len(mutation_calls)}",
            )
        )

    secret_events = [event for event in events if _has_secret(_sensitive_event_text(event))]
    if secret_events:
        signals.append(
            _signal(
                "secret-risk",
                "critical",
                "Credential-like material appeared in a trace event",
                f"secret_bearing_events={len(secret_events)}",
            )
        )

    return signals


def trace_from_conversation(
    messages: Iterable[dict[str, Any]], final_response: str = ""
) -> dict[str, Any]:
    """Adapt OpenAI-shaped Hermes conversation messages into a trace envelope."""
    events: list[dict[str, Any]] = []
    pending_names: dict[str, str] = {}
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role == "assistant" and message.get("tool_calls"):
            for tool_call in message["tool_calls"]:
                if not isinstance(tool_call, dict):
                    continue
                function = tool_call.get("function", tool_call)
                name = str(function.get("name", ""))
                raw_args = function.get("arguments", function.get("args", {}))
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except (TypeError, ValueError):
                    args = raw_args
                call_id = str(tool_call.get("id", ""))
                pending_names[call_id] = name
                events.append({"type": "tool_call", "id": call_id, "name": name, "arguments": args})
        elif role == "tool":
            call_id = str(message.get("tool_call_id", ""))
            content = _text(message)
            status = (
                "error"
                if message.get("error") or _is_failure({"content": content})
                else "success"
            )
            events.append(
                {
                    "type": "tool_result",
                    "tool_call_id": call_id,
                    "name": pending_names.get(call_id, ""),
                    "status": status,
                    "content": content,
                }
            )
        elif role == "assistant" and _text(message):
            events.append({"type": "assistant", "content": _text(message)})
    return {"events": events, "final_response": final_response}


def stable_trace_id(trace: dict[str, Any]) -> str:
    """Return a short deterministic identifier without storing trace contents."""
    payload = json.dumps(trace, sort_keys=True, ensure_ascii=False, default=str).encode()
    return hashlib.sha256(payload).hexdigest()[:12]


__all__ = ["Signal", "classify_trace", "stable_trace_id", "trace_from_conversation"]
