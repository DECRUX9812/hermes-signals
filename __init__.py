"""Hermes plugin adapter for the standalone Signals library.

The reusable classifier lives in the sibling ``hermes_signals`` package. This
root module is what Hermes loads when the repository is installed as a plugin.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Hermes loads a Git plugin under a synthetic namespace without adding the
# plugin directory to sys.path. Make the bundled library importable in that
# loader, while keeping normal package imports untouched.
_PLUGIN_DIR = str(Path(__file__).resolve().parent)
if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)

from hermes_signals.cli import register_cli, signals_command  # noqa: E402
from hermes_signals.status import arm_if_needed  # noqa: E402
from hermes_signals.store import record_turn  # noqa: E402

logger = logging.getLogger(__name__)


def _on_post_llm_call(**kwargs) -> None:
    """Persist local signal metadata after a completed Hermes turn."""
    try:
        record_turn(
            kwargs.get("conversation_history") or [],
            final_response=str(kwargs.get("assistant_response") or ""),
            session_id=str(kwargs.get("session_id") or ""),
            platform=str(kwargs.get("platform") or ""),
        )
    except Exception:
        logger.debug("Hermes Signals post-turn recording failed", exc_info=True)


def register(ctx) -> None:
    """Register the observer and ``hermes signals`` CLI command."""
    if arm_if_needed():
        logger.info(
            "Hermes Signals armed — monitoring this session's tool calls. "
            "Run `hermes signals setup` once to backfill history and install the "
            "weekly digest, or `hermes signals demo` for a sample trace."
        )
    ctx.register_hook("post_llm_call", _on_post_llm_call)
    ctx.register_cli_command(
        name="signals",
        help="Detect common agent behavior failures in a trace",
        setup_fn=register_cli,
        handler_fn=signals_command,
        description=(
            "Run local-first Hermes Signals against a JSON trace. "
            "No network, model, or GPU is required."
        ),
    )


__all__ = ["register"]
