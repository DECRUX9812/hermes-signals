"""JSONL reporting for local Signals runs."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from hermes_signals.classifier import classify_trace, stable_trace_id, trace_from_conversation

_LOCK = threading.Lock()


def default_store_path() -> Path:
    """Return Hermes' profile-aware local report path when Hermes is installed."""
    try:
        from hermes_constants import get_hermes_home

        return get_hermes_home() / "signals.jsonl"
    except Exception:
        return Path.home() / ".hermes" / "signals.jsonl"


def record_turn(
    messages: Iterable[dict[str, Any]],
    final_response: str = "",
    *,
    path: Path | None = None,
    session_id: str = "",
    platform: str = "",
) -> dict[str, Any]:
    """Classify one turn and append only bounded metadata to a local JSONL file."""
    trace = trace_from_conversation(messages, final_response=final_response)
    signals = classify_trace(trace)
    payload = {
        "trace_id": stable_trace_id(trace),
        "session_id": str(session_id or "")[:128],
        "platform": str(platform or "")[:32],
        "signals": [signal.to_dict() for signal in signals],
    }
    destination = Path(path or default_store_path())
    destination.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        with destination.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    return payload


__all__ = ["default_store_path", "record_turn"]
