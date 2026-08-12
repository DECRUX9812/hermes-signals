"""Command-line interface for Hermes Signals."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from hermes_signals.classifier import classify_trace, stable_trace_id

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


def _load_trace(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("trace JSON must contain an object at the top level")
    return value


def _payload(trace: dict[str, Any]) -> dict[str, Any]:
    return {
        "trace_id": stable_trace_id(trace),
        "signals": [signal.to_dict() for signal in classify_trace(trace)],
    }


def _print_text(payload: dict[str, Any]) -> None:
    signals = payload["signals"]
    print(f"Hermes Signals · trace {payload['trace_id']}")
    if not signals:
        print("✅ no deterministic signals")
        return
    for signal in signals:
        print(f"{signal['severity'].upper():8} {signal['signal_id']}: {signal['summary']}")
        for evidence in signal["evidence"]:
            print(f"         · {evidence}")


def register_cli(subparser: argparse.ArgumentParser) -> None:
    """Attach Signals subcommands to a Hermes plugin CLI parser."""
    subs = subparser.add_subparsers(dest="signals_action")
    scan = subs.add_parser("scan", help="Classify a JSON trace file")
    scan.add_argument("path", help="Path to a JSON trace envelope")
    scan.add_argument("--output", choices=("text", "json"), default="text")

    demo = subs.add_parser("demo", help="Run the built-in false-success example")
    demo.add_argument("--output", choices=("text", "json"), default="text")
    subparser.set_defaults(func=signals_command)


def signals_command(args: argparse.Namespace) -> int:
    """Handle the command parser used by Hermes and the standalone CLI."""
    action = getattr(args, "signals_action", None)
    if action == "demo":
        trace = _DEMO_TRACE
    else:
        try:
            trace = _load_trace(args.path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"hermes-signals: cannot read trace: {exc}")
            return 2

    payload = _payload(trace)
    if args.output == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_text(payload)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run ``hermes-signals scan`` or the built-in demo."""
    parser = argparse.ArgumentParser(prog="hermes-signals")
    register_cli(parser)
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 2
    return args.func(args)


__all__ = ["main", "register_cli", "signals_command"]


if __name__ == "__main__":
    raise SystemExit(main())
