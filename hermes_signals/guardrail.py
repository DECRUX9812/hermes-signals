"""Pre-execution guardrails: gate credential-like tool arguments mid-run.

The one capability hosted observability cannot offer: a deterministic policy
layer that enforces BEFORE a tool call executes. ``evaluate_guardrail`` is pure
(no I/O) and returns a ``pre_tool_call`` directive for the Hermes plugin:

    {"action": "block", "message": "..."}   # call is blocked, agent sees why
    None                                     # call may proceed

Action is configurable per process via ``HERMES_SIGNALS_GUARDRAIL_ACTION``:

- ``block`` (default) — credential-like arguments are blocked before execution
- ``warn``  — the call proceeds; the plugin records a local guardrail log entry
- ``off``   — guardrail disabled

Only the first ~8 KiB of serialized arguments are scanned, so huge payloads
(write_file contents) stay cheap; the post-hoc classifier still scans full
traces. The guardrail never raises: any failure lets the call proceed.
"""

from __future__ import annotations

import json
import os
from typing import Any

from hermes_signals.classifier import contains_secret

__all__ = ["evaluate_guardrail", "guardrail_action", "guardrail_scan_text"]

_SCAN_LIMIT = 8192  # characters of serialized args scanned per call


def guardrail_action(environ: dict[str, str] | None = None) -> str:
    """Resolve the configured action (block | warn | off; default block)."""
    env = environ if environ is not None else os.environ
    action = env.get("HERMES_SIGNALS_GUARDRAIL_ACTION", "").strip().lower()
    if action not in ("block", "warn", "off"):
        return "block"
    return action


def guardrail_scan_text(args: dict[str, Any] | None) -> str:
    """Serialize tool arguments to the bounded scan window (never raises)."""
    if not args:
        return ""
    try:
        text = json.dumps(args, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return ""
    return text[:_SCAN_LIMIT]


def evaluate_guardrail(
    tool_name: str,
    args: dict[str, Any] | None,
    *,
    environ: dict[str, str] | None = None,
) -> dict[str, str] | None:
    """Return a ``pre_tool_call`` directive for one tool call, or None.

    Pure and fail-open: scanning errors or unknown tools never block.
    """
    action = guardrail_action(environ)
    if action == "off":
        return None
    text = guardrail_scan_text(args)
    if not text or not contains_secret(text):
        return None
    message = (
        f"hermes-signals guardrail: credential-like material detected in "
        f"{tool_name} arguments. Do not inline secrets — use an environment "
        f"variable or a secret file, then retry."
    )
    if action == "block":
        return {"action": "block", "message": message}
    return {"action": "warn", "message": message}
