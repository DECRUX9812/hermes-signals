"""Session-scoped circuit breakers: stop an agent mid-run before it wastes more.

Deterministic, local, harness-agnostic — the layer the hosted vendors leave
unoccupied. Two rules, both configurable via env:

- ``HERMES_SIGNALS_BREAKER_RETRY_N`` (default 5; ``0`` disables) — block the
  Nth identical (tool, canonical args) call within one session. Same tool +
  same arguments repeated N times means the agent is looping, not adapting.
- ``HERMES_SIGNALS_BREAKER_MAX_CALLS`` (default ``0`` = disabled) — block when
  a session exceeds this many tool calls (a hard cost ceiling).

Actions follow ``HERMES_SIGNALS_GUARDRAIL_ACTION`` (``block`` | ``warn`` |
``off``; default ``block``). State is process-local and bounded; the breaker
never raises — a state error lets the call proceed.
"""

from __future__ import annotations

import json
import os
from typing import Any

from hermes_signals.guardrail import guardrail_action

__all__ = ["args_key", "breaker_directive", "breaker_config", "note_call", "new_state"]

_MAX_SESSIONS = 64
_MAX_COUNT = 1000
_ARGS_KEY_LIMIT = 200  # chars of canonicalized args kept per key


def new_state() -> dict[str, Any]:
    """A fresh breaker state container: {session_id: {"calls": {}, "total": n}}."""
    return {}


def breaker_config(environ: dict[str, str] | None = None) -> dict[str, int]:
    """Resolve retry_n / max_calls from the environment (0 = disabled)."""
    env = environ if environ is not None else os.environ

    def _int(name: str, default: int) -> int:
        try:
            return max(0, int(env.get(name, "").strip() or default))
        except (TypeError, ValueError):
            return default

    return {
        "retry_n": _int("HERMES_SIGNALS_BREAKER_RETRY_N", 5),
        "max_calls": _int("HERMES_SIGNALS_BREAKER_MAX_CALLS", 0),
    }


def args_key(args: dict[str, Any] | None) -> str:
    """Canonical, order-insensitive, bounded key for one call's arguments."""
    if not args:
        return ""
    try:
        text = json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(args)
    return text[:_ARGS_KEY_LIMIT]


def _session(state: dict[str, Any], session_id: str) -> dict[str, Any]:
    entry = state.get(session_id)
    if entry is None:
        # Bound the number of tracked sessions (drop the oldest).
        while len(state) >= _MAX_SESSIONS:
            oldest = next(iter(state))
            del state[oldest]
        entry = {"calls": {}, "total": 0}
        state[session_id] = entry
    return entry


def breaker_directive(
    state: dict[str, Any],
    session_id: str,
    tool_name: str,
    call_args: dict[str, Any] | None,
    *,
    environ: dict[str, str] | None = None,
) -> dict[str, str] | None:
    """Return a guardrail directive if this call trips a breaker, else None.

    Pure except for the injected ``state`` dict (mutated only by :func:`note_call`).
    """
    action = guardrail_action(environ)
    if action == "off":
        return None
    config = breaker_config(environ)
    key = args_key(call_args)
    entry = state.get(session_id)
    upcoming = {"calls": {}, "total": 0}
    if entry is not None:
        upcoming = entry

    count = upcoming["calls"].get(key, 0) + 1
    total = upcoming["total"] + 1

    message = ""
    if config["retry_n"] and count >= config["retry_n"]:
        message = (
            f"hermes-signals circuit breaker: {tool_name} called with identical "
            f"arguments {count} times in this session. Stop repeating this call "
            f"and change strategy."
        )
    elif config["max_calls"] and total > config["max_calls"]:
        message = (
            f"hermes-signals circuit breaker: session exceeded {config['max_calls']} "
            f"tool calls. Stop and summarize what you have instead of continuing."
        )
    else:
        return None
    return {"action": action, "message": message}


def note_call(
    state: dict[str, Any],
    session_id: str,
    call_args: dict[str, Any] | None,
) -> None:
    """Record one executed call (called only when the call actually proceeds)."""
    try:
        entry = _session(state, session_id)
        key = args_key(call_args)
        entry["calls"][key] = min(entry["calls"].get(key, 0) + 1, _MAX_COUNT)
        entry["total"] = min(entry["total"] + 1, _MAX_COUNT)
    except Exception:  # pragma: no cover - state tracking must never break the agent
        pass
