"""Install self-check and status reporting.

The "value in 60 seconds" surface: the first time the plugin loads it writes an
``armed`` marker and logs a welcome line; ``hermes signals status`` summarizes
stores, signals, and escalation mode at a glance.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hermes_signals import __version__
from hermes_signals.escalate import escalation_source
from hermes_signals.store import read_signals

__all__ = ["arm_if_needed", "status_report"]

_ARMED_FILENAME = "signals-armed.json"


def _home(hermes_home: str | Path | None) -> Path:
    return Path(hermes_home or os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))


def arm_if_needed(*, hermes_home: str | Path | None = None) -> bool:
    """Write the one-time armed marker; True only on the first install."""
    marker = _home(hermes_home) / _ARMED_FILENAME
    if marker.exists():
        return False
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps(
            {
                "armed_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "version": __version__,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return True


def status_report(*, hermes_home: str | Path | None = None) -> dict[str, Any]:
    """Return a bounded snapshot of the local Signals installation."""
    home = _home(hermes_home)
    marker = home / _ARMED_FILENAME
    armed_at = None
    if marker.exists():
        try:
            armed_at = json.loads(marker.read_text(encoding="utf-8")).get("armed_at")
        except (OSError, json.JSONDecodeError):
            armed_at = None

    signals = read_signals(home / "signals.jsonl")
    by_type: Counter[str] = Counter()
    for payload in signals:
        for signal in payload.get("signals", []):
            signal_id = str(signal.get("signal_id") or "")
            if signal_id:
                by_type[signal_id] += 1
    feedback_count = 0
    feedback_path = home / "signals-feedback.jsonl"
    if feedback_path.exists():
        try:
            feedback_count = sum(1 for line in feedback_path.read_text(encoding="utf-8").splitlines() if line.strip())
        except OSError:
            feedback_count = 0

    mode, config = escalation_source(hermes_home=home)
    escalation: dict[str, str] = {"mode": mode}
    if config:
        escalation["model"] = config["model"]
        escalation["base_url"] = config["base_url"]

    return {
        "armed": armed_at is not None,
        "armed_at": armed_at,
        "version": __version__,
        "signals_store": str(home / "signals.jsonl"),
        "signals_recorded": len(signals),
        "feedback_recorded": feedback_count,
        "signals_by_type": dict(sorted(by_type.items())),
        "escalation": escalation,
    }