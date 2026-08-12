"""JSONL reporting for local Signals runs."""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hermes_signals.classifier import classify_trace, stable_trace_id, trace_from_conversation

_LOCK = threading.Lock()
_LABELS = {"correct", "false_positive", "policy"}


def _fallback_home() -> Path:
    """Profile-aware home when running standalone (hermes_constants unavailable)."""
    return Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))


def default_store_path() -> Path:
    """Return Hermes' profile-aware local report path when Hermes is installed."""
    try:
        from hermes_constants import get_hermes_home

        return get_hermes_home() / "signals.jsonl"
    except Exception:
        return _fallback_home() / "signals.jsonl"


def default_feedback_path() -> Path:
    """Return the profile-aware feedback label store path."""
    try:
        from hermes_constants import get_hermes_home

        return get_hermes_home() / "signals-feedback.jsonl"
    except Exception:
        return _fallback_home() / "signals-feedback.jsonl"


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


def record_feedback(
    trace_id: str,
    signal_id: str,
    label: str,
    *,
    path: Path | None = None,
    source: str = "",
) -> dict[str, Any]:
    """Append one human feedback label for a signal to the local JSONL store.

    Labels map to Discord reactions: ✅ -> correct, ❌ -> false_positive,
    🛠️ -> policy (a suggestion that the matching policy should change).
    """
    label = str(label).strip().lower()
    if label not in _LABELS:
        raise ValueError(f"label must be one of {sorted(_LABELS)}, got {label!r}")
    record = {
        "trace_id": str(trace_id or "")[:64],
        "signal_id": str(signal_id or "")[:64],
        "label": label,
        "source": str(source or "")[:32],
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    destination = Path(path or default_feedback_path())
    destination.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        with destination.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    return record


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                records.append(value)
    return records


def precision_report(
    *,
    signals_path: Path | None = None,
    feedback_path: Path | None = None,
) -> dict[str, Any]:
    """Aggregate feedback labels into per-signal precision metrics.

    ``precision`` = correct / (correct + false_positive); None when no
    correctness feedback exists yet. The ``policy`` label is counted but is not
    a correctness verdict, so it never changes precision.
    """
    feedback = _read_jsonl(Path(feedback_path or default_feedback_path()))
    by_signal: dict[str, dict[str, int]] = {}
    for record in feedback:
        signal_id = str(record.get("signal_id") or "")
        label = str(record.get("label") or "")
        if not signal_id or label not in _LABELS:
            continue
        row = by_signal.setdefault(signal_id, {"correct": 0, "false_positive": 0, "policy": 0})
        row[label] += 1

    signals_file = Path(signals_path or default_store_path())
    matched_counts: dict[str, int] = {}
    for payload in _read_jsonl(signals_file):
        for signal in payload.get("signals", []):
            signal_id = str(signal.get("signal_id") or "")
            if signal_id:
                matched_counts[signal_id] = matched_counts.get(signal_id, 0) + 1

    signals_report: dict[str, Any] = {}
    for signal_id in sorted(set(matched_counts) | set(by_signal)):
        feedback_row = by_signal.get(signal_id, {"correct": 0, "false_positive": 0, "policy": 0})
        correct = feedback_row["correct"]
        false_positive = feedback_row["false_positive"]
        denominator = correct + false_positive
        signals_report[signal_id] = {
            "matched": matched_counts.get(signal_id, 0),
            "correct": correct,
            "false_positive": false_positive,
            "policy": feedback_row["policy"],
            "precision": round(correct / denominator, 4) if denominator else None,
        }
    return {"signals": signals_report, "total_feedback": len(feedback)}


__all__ = [
    "default_feedback_path",
    "default_store_path",
    "precision_report",
    "record_feedback",
    "record_turn",
]
