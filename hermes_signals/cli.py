"""Command-line interface for Hermes Signals."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from hermes_signals.classifier import classify_trace, stable_trace_id
from hermes_signals.escalate import escalate_signals, escalation_config_from_env
from hermes_signals.store import precision_report, record_feedback

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


def _payload(trace: dict[str, Any], strategy_sensitive: bool = False) -> dict[str, Any]:
    return {
        "trace_id": stable_trace_id(trace),
        "signals": [
            signal.to_dict()
            for signal in classify_trace(trace, strategy_sensitive=strategy_sensitive)
        ],
    }


def _escalated_payload(trace: dict[str, Any], strategy_sensitive: bool = False) -> dict[str, Any]:
    config = escalation_config_from_env()
    if config is None:
        raise SystemExit(
            "hermes-signals: --escalate requires HERMES_SIGNALS_ESCALATION_BASE_URL, "
            "HERMES_SIGNALS_ESCALATION_MODEL (and optionally "
            "HERMES_SIGNALS_ESCALATION_API_KEY) to be set."
        )
    signals = escalate_signals(
        classify_trace(trace, strategy_sensitive=strategy_sensitive),
        trace,
        base_url=config["base_url"],
        model=config["model"],
        api_key=config["api_key"],
    )
    return {"trace_id": stable_trace_id(trace), "signals": [s.to_dict() for s in signals]}


def _print_text(payload: dict[str, Any]) -> None:
    signals = payload["signals"]
    print(f"Hermes Signals · trace {payload['trace_id']}")
    if not signals:
        print("✅ no deterministic signals")
        return
    for signal in signals:
        marker = ""
        if signal.get("confirmed") is True:
            marker = " [CONFIRMED]"
        elif signal.get("confirmed") is False:
            marker = " [REJECTED]"
        elif signal.get("ambiguous"):
            marker = " [UNCONFIRMED]"
        print(
            f"{signal['severity'].upper():8} {signal['signal_id']}: "
            f"{signal['summary']}{marker}"
        )
        for evidence in signal["evidence"]:
            print(f"         · {evidence}")


def register_cli(subparser: argparse.ArgumentParser) -> None:
    """Attach Signals subcommands to a Hermes plugin CLI parser."""
    subs = subparser.add_subparsers(dest="signals_action")
    scan = subs.add_parser("scan", help="Classify a JSON trace file")
    scan.add_argument("path", help="Path to a JSON trace envelope")
    scan.add_argument("--output", choices=("text", "json"), default="text")
    scan.add_argument(
        "--escalate",
        action="store_true",
        help=(
            "Confirm ambiguous signals with a cheap model (requires "
            "HERMES_SIGNALS_ESCALATION_* env vars)"
        ),
    )
    scan.add_argument(
        "--strategy-sensitive",
        action="store_true",
        help=(
            "Flag retry loops where only argument values changed while the "
            "strategy (tool + argument shape) stayed the same"
        ),
    )

    demo = subs.add_parser("demo", help="Run the built-in false-success example")
    demo.add_argument("--output", choices=("text", "json"), default="text")

    feedback = subs.add_parser(
        "feedback",
        help="Record a human label for a signal (✅ correct / ❌ false_positive / 🛠️ policy)",
    )
    feedback.add_argument("trace_id", help="Trace id from a scan or record")
    feedback.add_argument("signal_id", help="Signal id, e.g. false-success")
    feedback.add_argument("label", choices=("correct", "false_positive", "policy"))
    feedback.add_argument("--source", default="", help="Where the label came from (e.g. discord)")

    report = subs.add_parser("report", help="Show per-signal precision from recorded feedback")
    report.add_argument("--output", choices=("text", "json"), default="text")
    subparser.set_defaults(func=signals_command)


def signals_command(args: argparse.Namespace) -> int:
    """Handle the command parser used by Hermes and the standalone CLI."""
    action = getattr(args, "signals_action", None)
    if action == "feedback":
        try:
            record = record_feedback(
                args.trace_id,
                args.signal_id,
                args.label,
                source=args.source,
            )
        except ValueError as exc:
            print(f"hermes-signals: {exc}")
            return 2
        print(f"✅ recorded {record['label']} for {record['signal_id']} ({record['trace_id']})")
        return 0
    if action == "report":
        report = precision_report()
        if args.output == "json":
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0
        print(f"Hermes Signals · precision report ({report['total_feedback']} feedback labels)")
        header = f"{'SIGNAL':<24}{'MATCHED':>9}{'CORRECT':>9}{'FP':>5}{'POLICY':>8}{'PRECISION':>12}"
        print(header)
        for signal_id, row in report["signals"].items():
            precision = "n/a" if row["precision"] is None else f"{row['precision']:.2%}"
            print(
                f"{signal_id:<24}{row['matched']:>9}{row['correct']:>9}"
                f"{row['false_positive']:>5}{row['policy']:>8}{precision:>12}"
            )
        return 0
    if action == "demo":
        trace = _DEMO_TRACE
    else:
        try:
            trace = _load_trace(args.path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"hermes-signals: cannot read trace: {exc}")
            return 2

    strategy_sensitive = getattr(args, "strategy_sensitive", False)
    payload = (
        _escalated_payload(trace, strategy_sensitive=strategy_sensitive)
        if getattr(args, "escalate", False)
        else _payload(trace, strategy_sensitive=strategy_sensitive)
    )
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
