"""Opt-in alerting: local guardrail log + critical-signal webhook.

Everything here is disabled by default and never raises. The guardrail log is
a bounded local JSONL (``$HERMES_HOME/signals-guardrail.jsonl``) kept separate
from the signals store so it never skews precision metrics. The webhook is a
single POST with compact, redacted content — only fires when
``HERMES_SIGNALS_WEBHOOK_URL`` is set AND a critical signal (e.g.
``secret-risk``) matched.
"""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = ["append_guardrail_log", "guardrail_log_path", "webhook_notify"]

_CRITICAL_SIGNALS = {"secret-risk"}


def _home(hermes_home: str | Path | None) -> Path:
    return Path(hermes_home or os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))


def guardrail_log_path(*, hermes_home: str | Path | None = None) -> Path:
    return _home(hermes_home) / "signals-guardrail.jsonl"


def append_guardrail_log(
    *,
    tool_name: str,
    action: str,
    matched: bool = True,
    session_id: str = "",
    hermes_home: str | Path | None = None,
) -> None:
    """Append one bounded guardrail record (never raises)."""
    record = {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "tool": str(tool_name)[:64],
        "action": action,
        "matched": bool(matched),
        "session_id": str(session_id or "")[:64],
    }
    try:
        path = guardrail_log_path(hermes_home=hermes_home)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # pragma: no cover - logging must never break the agent
        pass


def webhook_notify(
    url: str,
    payload: dict[str, Any],
    *,
    timeout: float = 5.0,
) -> bool:
    """POST a compact JSON payload to the configured webhook (never raises)."""
    if not url:
        return False
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 300
    except Exception:  # pragma: no cover - alerting is best-effort
        return False


def build_alert_payload(
    *,
    signal_ids: list[str],
    trace_id: str = "",
    session_id: str = "",
    platform: str = "",
) -> dict[str, Any]:
    """Compact, redacted alert payload (counts and ids only — no raw content)."""
    return {
        "event": "hermes-signals",
        "signals": [str(signal_id) for signal_id in signal_ids],
        "trace_id": str(trace_id)[:64],
        "session_id": str(session_id)[:64],
        "platform": str(platform)[:32],
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
    }
