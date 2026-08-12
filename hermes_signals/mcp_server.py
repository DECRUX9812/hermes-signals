"""Model Context Protocol (MCP) server for Hermes Signals.

Exposes the deterministic classifier as tools over MCP so it works in any
harness that speaks the protocol: Hermes Agent, OpenCode, Vercel AI SDK,
Claude Desktop, Cursor, VS Code, ChatGPT, and more.

The core handler functions (``scan_trace``, ``scan_trace_file``, ``demo``)
are plain Python and importable without the ``mcp`` SDK, so tests and other
integrators can call them directly. The SDK is imported lazily inside
:func:`build_server` to keep the base package dependency-free.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from hermes_signals.classifier import classify_trace, stable_trace_id
from hermes_signals.store import precision_report, record_feedback

__all__ = [
    "build_server",
    "demo",
    "feedback",
    "main",
    "precision",
    "scan_trace",
    "scan_trace_file",
]

_VERSION = "0.2.0"

_DEMO_TRACE: dict[str, Any] = {
    "events": [
        {"type": "tool_call", "id": "1", "name": "update_record", "arguments": {"id": 42}},
        {
            "type": "tool_result",
            "tool_call_id": "1",
            "status": "error",
            "content": "request timed out",
        },
        {"type": "assistant", "content": "The record was successfully updated."},
    ]
}


def _payload(trace: dict[str, Any]) -> dict[str, Any]:
    """Classify one trace into a compact, redacted payload."""
    return {
        "trace_id": stable_trace_id(trace),
        "signals": [signal.to_dict() for signal in classify_trace(trace)],
    }


def _dump(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False)


def _load(text: str) -> dict[str, Any]:
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("trace JSON must contain a JSON object at the top level")
    return value


async def scan_trace(trace_json: str) -> str:
    """Classify a JSON trace envelope describing an agent run.

    Returns deterministic behavior-quality signals (false-success, retry-loop,
    unverified-change, secret-risk) as JSON. Evidence is redacted; no raw
    conversation content or suspected secrets are returned. Pass the trace as
    a JSON object string.
    """
    try:
        trace = _load(trace_json)
    except (json.JSONDecodeError, ValueError) as exc:
        return _dump({"error": f"invalid trace JSON: {exc}"})
    return _dump(_payload(trace))


async def scan_trace_file(path: str) -> str:
    """Classify a trace JSON file on disk.

    Reads the file at ``path`` and returns the same redacted signals as
    ``scan_trace``. Pass an absolute or relative file path to a JSON trace
    envelope.
    """
    try:
        trace = _load(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return _dump({"error": f"cannot scan trace file {path!r}: {exc}"})
    return _dump(_payload(trace))


async def demo() -> str:
    """Run the built-in example trace and return the detected signals.

    The example is a tool failure (update_record timed out) followed by an
    unearned success claim, which the classifier flags as false-success. Useful
    for a quick smoke test of the server.
    """
    return _dump(_payload(_DEMO_TRACE))


async def feedback(trace_id: str, signal_id: str, label: str, source: str = "") -> str:
    """Record a human label for one signal.

    Labels: ``correct`` (✅), ``false_positive`` (❌), or ``policy`` (🛠️ policy
    should change). Appends a bounded record to the local feedback store; never
    sends data anywhere.
    """
    try:
        record = record_feedback(trace_id, signal_id, label, source=source)
    except ValueError as exc:
        return _dump({"error": str(exc)})
    return _dump(record)


async def precision() -> str:
    """Return per-signal precision from recorded feedback.

    Computes correct / (correct + false_positive) per signal over the local
    feedback store. Deterministic and fully local.
    """
    return _dump(precision_report())


def build_server() -> Any:
    """Build an :class:`~mcp.server.mcpserver.MCPServer` exposing the tools."""
    from mcp.server.mcpserver import MCPServer

    server = MCPServer(
        name="hermes-signals",
        version=_VERSION,
        description="Local-first deterministic behavior-quality signals for AI agents.",
    )
    server.tool(
        name="scan_trace",
        description=(
            "Classify a JSON trace envelope describing an agent run and return "
            "deterministic behavior-quality signals (false-success, retry-loop, "
            "unverified-change, secret-risk) with redacted evidence."
        ),
    )(scan_trace)
    server.tool(name="scan_trace_file", description="Classify a trace JSON file on disk.")(scan_trace_file)
    server.tool(name="demo", description="Run the built-in example trace and return detected signals.")(demo)
    server.tool(
        name="feedback",
        description=(
            "Record a human label (correct, false_positive, or policy) for one "
            "signal id and trace id into the local feedback store."
        ),
    )(feedback)
    server.tool(
        name="precision",
        description="Return per-signal precision metrics from recorded feedback.",
    )(precision)
    return server


def main(argv: list[str] | None = None) -> int:
    """Run the MCP server (stdio by default).

    Requires the optional dependency: ``pip install 'hermes-signals[mcp]'``.
    """
    parser = argparse.ArgumentParser(prog="hermes-signals-mcp")
    parser.add_argument(
        "--transport",
        choices=("stdio", "sse", "streamable-http"),
        default="stdio",
        help="MCP transport (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Bind host for streamable-http/sse (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Bind port for streamable-http/sse (default: 8000)",
    )
    args = parser.parse_args(argv)
    server = build_server()
    kwargs: dict[str, Any] = {}
    if args.host is not None:
        kwargs["host"] = args.host
    if args.port is not None:
        kwargs["port"] = args.port
    server.run(transport=args.transport, **kwargs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())