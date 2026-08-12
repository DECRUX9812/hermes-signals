"""Command-line interface for Hermes Signals."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from hermes_signals.backfill import backfill_sources
from hermes_signals.classifier import classify_trace, stable_trace_id
from hermes_signals.corpus import corpus_summary, run_corpus
from hermes_signals.digest import build_digest_markdown, cron_install
from hermes_signals.doctor import run_doctor
from hermes_signals.escalate import escalate_signals, resolve_escalation_config
from hermes_signals.packs import apply_pack, installed_packs, load_pack
from hermes_signals.status import arm_if_needed, status_report
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


def _apply_pack_if_requested(signals, pack_path: str | None):
    if pack_path:
        return apply_pack(signals, load_pack(pack_path))
    return signals


def _payload(
    trace: dict[str, Any],
    strategy_sensitive: bool = False,
    pack_path: str | None = None,
) -> dict[str, Any]:
    signals = _apply_pack_if_requested(
        classify_trace(trace, strategy_sensitive=strategy_sensitive), pack_path
    )
    return {
        "trace_id": stable_trace_id(trace),
        "signals": [signal.to_dict() for signal in signals],
    }


def _escalated_payload(
    trace: dict[str, Any],
    strategy_sensitive: bool = False,
    pack_path: str | None = None,
) -> dict[str, Any]:
    config = resolve_escalation_config()
    if config is None:
        print(
            "hermes-signals: --escalate requested but no model config found; "
            "running deterministic-only (set HERMES_SIGNALS_ESCALATION_* or "
            "start ollama / CLIProxy to enable)",
            file=sys.stderr,
        )
        return _payload(trace, strategy_sensitive=strategy_sensitive, pack_path=pack_path)
    signals = escalate_signals(
        _apply_pack_if_requested(
            classify_trace(trace, strategy_sensitive=strategy_sensitive), pack_path
        ),
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
    scan.add_argument("--pack", default=None, help="Apply a policy pack (JSON/YAML) before reporting")

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

    backfill = subs.add_parser(
        "backfill",
        help="Classify recent sessions from existing stores (hermes/opencode/claude)",
    )
    backfill.add_argument(
        "--source",
        action="append",
        choices=("hermes", "opencode", "claude"),
        help="Store to scan (repeatable; default: all)",
    )
    backfill.add_argument("--max-sessions", type=int, default=200)
    backfill.add_argument("--dry-run", action="store_true", help="Report what would be scanned without writing")

    subs.add_parser("status", help="Show armed state, store counts, and escalation mode")

    digest = subs.add_parser(
        "digest",
        help="Print the weekly markdown digest (or install a weekly cron job)",
    )
    digest.add_argument("--out", default=None, help="Write markdown to a file instead of stdout")
    digest.add_argument(
        "--cron-install",
        action="store_true",
        help="Register a weekly no-agent cron job that delivers the digest",
    )

    corpus = subs.add_parser(
        "corpus",
        help="Run the labeled regression corpus (policy safety check)",
    )
    corpus.add_argument("--dir", default=None, help="Corpus directory (default: shipped corpus/)")

    subs.add_parser("packs", help="List installed policy packs")

    setup = subs.add_parser(
        "setup",
        help="One-shot install: backfill history, arm monitoring, install the weekly digest",
    )
    setup.add_argument(
        "--source",
        action="append",
        choices=("hermes", "opencode", "claude"),
        help="Store to backfill (repeatable; default: hermes)",
    )
    setup.add_argument("--max-sessions", type=int, default=100)
    setup.add_argument("--no-backfill", action="store_true", help="Skip the history backfill")
    setup.add_argument("--no-cron", action="store_true", help="Skip installing the weekly digest cron")
    setup.add_argument("--dry-run", action="store_true", help="Print the plan without changing anything")

    subs.add_parser("doctor", help="Self-check: store, corpus, escalation, digest cron")
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
    if action == "backfill":
        sources = args.source or ["hermes", "opencode", "claude"]
        summary = backfill_sources(
            sources,
            max_sessions=args.max_sessions,
            dry_run=args.dry_run,
        )
        if args.dry_run:
            print("(dry run — nothing written)")
        for source, stats in summary.items():
            print(
                f"{source:<10} scanned={stats['sessions_scanned']:<4} "
                f"signals={stats['signals_recorded']:<3} dupes={stats['skipped_duplicates']}"
            )
        return 0
    if action == "status":
        report = status_report()
        print(f"Hermes Signals v{report['version']} — {'ARMED' if report['armed'] else 'not armed'}")
        print(f"signals recorded:  {report['signals_recorded']}  ({report['signals_store']})")
        print(f"feedback labels:  {report['feedback_recorded']}")
        print(f"signals by type:  {report['signals_by_type']}")
        esc = report["escalation"]
        print(
            f"escalation:       {esc['mode']}"
            + (f" ({esc.get('model')} @ {esc.get('base_url')})" if esc.get("model") else "")
        )
        return 0
    if action == "digest":
        if args.cron_install:
            result = cron_install()
            if result["installed"]:
                print(f"✅ weekly digest cron installed (job {result['job_id']})")
            else:
                print(f"⚠ could not register cron: {result.get('error')}")
                print(f"  run manually: {result['manual']}")
            return 0
        markdown = build_digest_markdown()
        if args.out:
            Path(args.out).write_text(markdown, encoding="utf-8")
            print(f"digest written to {args.out}")
        else:
            print(markdown)
        return 0
    if action == "corpus":
        results = run_corpus(args.dir)
        summary = corpus_summary(results)
        for result in results:
            marker = "PASS" if result.passed else "FAIL"
            print(
                f"[{marker}] {result.name}: expected={sorted(result.expected)} "
                f"actual={sorted(result.actual)}"
            )
        print(f"\ncorpus: {summary['passed']}/{summary['total']} passed")
        return 0 if summary["failed"] == 0 else 1
    if action == "packs":
        packs = installed_packs()
        if not packs:
            print("no policy packs installed (~/.hermes/signals-packs/)")
            return 0
        for pack in packs:
            version = f"v{pack['version']}" if pack.get("version") else "unversioned"
            print(f"{pack['name']} ({version}) — {pack['path']}")
        return 0
    if action == "setup":
        return _run_setup(args)
    if action == "doctor":
        return _run_doctor()
    if action == "demo":
        trace = _DEMO_TRACE
    else:
        try:
            trace = _load_trace(args.path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"hermes-signals: cannot read trace: {exc}")
            return 2

    strategy_sensitive = getattr(args, "strategy_sensitive", False)
    pack_path = getattr(args, "pack", None)
    payload = (
        _escalated_payload(trace, strategy_sensitive=strategy_sensitive, pack_path=pack_path)
        if getattr(args, "escalate", False)
        else _payload(trace, strategy_sensitive=strategy_sensitive, pack_path=pack_path)
    )
    if args.output == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_text(payload)
    return 0


def _run_setup(args: argparse.Namespace) -> int:
    """One-shot set-and-forget install: arm, backfill history, weekly digest."""
    if args.dry_run:
        print("setup plan (dry run — nothing changed):")
        print("  1. arm monitoring (one-time marker under HERMES_HOME)")
        if not args.no_backfill:
            sources = args.source or ["hermes"]
            print(
                f"  2. backfill {', '.join(sources)} "
                f"(max {args.max_sessions} sessions per source)"
            )
        if not args.no_cron:
            print("  3. install weekly digest cron (Sundays 09:00 · no-agent · local delivery)")
        print("  4. print status report")
        return 0

    if arm_if_needed():
        print("✅ armed — monitoring this Hermes install from now on")
    else:
        print("ℹ️  already armed (monitoring active)")

    if not args.no_backfill:
        sources = args.source or ["hermes"]
        summary = backfill_sources(sources, max_sessions=args.max_sessions)
        for source, stats in summary.items():
            print(
                f"   backfill {source:<8} scanned={stats['sessions_scanned']:<4} "
                f"signals={stats['signals_recorded']:<3} dupes={stats['skipped_duplicates']}"
            )

    if not args.no_cron:
        result = cron_install()
        if result["installed"]:
            verb = "already installed" if result.get("already") else "installed"
            print(f"✅ weekly digest cron {verb} (job {result['job_id']})")
        else:
            print(f"⚠ could not register cron: {result.get('error')}")
            print(f"  run manually: {result['manual']}")

    report = status_report()
    print(f"\nHermes Signals v{report['version']} — {'ARMED' if report['armed'] else 'not armed'}")
    print(f"signals recorded:  {report['signals_recorded']}  ({report['signals_store']})")
    esc = report["escalation"]
    print(
        f"escalation:       {esc['mode']}"
        + (f" ({esc.get('model')} @ {esc.get('base_url')})" if esc.get("model") else "")
    )
    print()
    print("You're set. From now on:")
    print("  · every Hermes turn is scanned locally — zero model calls, zero telemetry")
    print("  · the weekly digest lands on its own (Sundays)")
    print(
        "  · label what you see: hermes signals feedback <trace> <signal> "
        "correct|false_positive|policy"
    )
    print("  · anytime: hermes signals doctor · hermes signals report · hermes signals digest")
    return 0


def _run_doctor() -> int:
    """Print the self-check table; fail only on required checks."""
    checks = run_doctor()
    failed = 0
    for check in checks:
        marker = "✓" if check.ok else "✗"
        tag = "" if check.required else " (optional)"
        print(f"{marker} {check.name:<12} {check.detail}{tag}")
        if check.required and not check.ok:
            failed += 1
    print()
    if failed:
        print(f"doctor: {failed} required check(s) failed — run `hermes signals setup` to repair")
        return 1
    print("doctor: all required checks pass")
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
