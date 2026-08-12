"""Weekly digest: a set-and-forget markdown report of Signals health.

The last plug-and-forget piece: ``hermes signals digest`` prints a bounded
markdown report (numbers only — no raw trace content), and ``--cron-install``
best-effort registers a weekly Hermes cron job (``no_agent`` script mode) so
the report shows up on its own every Sunday. On non-Hermes installs the helper
prints the manual ``hermes cron add`` command instead.
"""

from __future__ import annotations

import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hermes_signals.status import status_report
from hermes_signals.store import judge_agreement, precision_report, read_signals

__all__ = ["build_digest_markdown", "cron_install"]

_DIGEST_SCRIPT = """\
#!/usr/bin/env python3
\"\"\"Weekly Hermes Signals digest (installed by `hermes signals digest --cron-install`).\"\"\"
import os
import sys

for candidate in (os.path.expanduser("~/.hermes/plugins"), os.path.expanduser("~/.hermes")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

try:
    from hermes_signals.digest import build_digest_markdown

    print(build_digest_markdown())
except Exception as exc:  # noqa: BLE001 - a broken digest must never kill the cron tick silently
    print(f"signals weekly digest failed: {exc}")
    sys.exit(1)
"""


def _home(hermes_home: str | Path | None) -> Path:
    return Path(hermes_home or os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))


def _fmt_precision(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def build_digest_markdown(*, hermes_home: str | Path | None = None) -> str:
    """Build a bounded markdown digest from the local stores (numbers only)."""
    home = _home(hermes_home)
    status = status_report(hermes_home=home)
    report = precision_report(
        signals_path=home / "signals.jsonl",
        feedback_path=home / "signals-feedback.jsonl",
    )
    agreement = judge_agreement(
        signals_path=home / "signals.jsonl",
        feedback_path=home / "signals-feedback.jsonl",
    )
    when = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Hermes Signals — weekly digest",
        "",
        f"Generated {when} · v{status['version']}",
        "",
        "## Precision by signal",
        "",
        "| Signal | Matched | Correct | FP | Policy | Precision |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for signal_id, row in report["signals"].items():
        lines.append(
            f"| `{signal_id}` | {row['matched']} | {row['correct']} | "
            f"{row['false_positive']} | {row['policy']} | {_fmt_precision(row['precision'])} |"
        )
    lines.extend(
        [
            "",
            "## Escalation",
            "",
            f"- mode: `{status['escalation']['mode']}`"
            + (
                f" · model `{status['escalation']['model']}`"
                if status["escalation"].get("model")
                else ""
            ),
            "",
            "## Recently flagged traces",
            "",
        ]
    )
    if agreement["judged"]:
        lines.extend(
            [
                "## Judge agreement",
                "",
                f"- {agreement['agreed']}/{agreement['judged']} verdicts matched human labels "
                f"({_fmt_percent(agreement['agreement'])})",
                "",
            ]
        )
    trend = _trend_section(home / "signals.jsonl")
    if trend:
        lines.extend([trend, ""])
    records = read_signals(home / "signals.jsonl")
    for payload in records[-5:]:
        ids = ", ".join(s.get("signal_id", "") for s in payload.get("signals", []))
        lines.append(f"- `{payload.get('trace_id', '?')}` ({payload.get('platform', '?')}): {ids}")
    lines.extend(
        [
            "",
            "## What to do",
            "",
            "- Label a result: `hermes signals feedback <trace> <signal> correct|false_positive|policy`",
            "  (Discord reactions ✅ correct · ❌ false_positive · 🛠️ policy map 1:1)",
            "- Drill in: `hermes signals scan <trace-file> --escalate`",
            "- This digest: `hermes signals digest`",
            "",
        ]
    )
    return "\n".join(lines)


def _fmt_percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def _trend_section(signals_path: Path) -> str:
    """Per-signal this-week vs last-week counts with a drift flag."""
    from datetime import UTC, timedelta

    now = datetime.now(UTC)
    week_counts: dict[str, Counter] = {}
    for payload in read_signals(signals_path):
        ts = payload.get("ts")
        if not ts:
            continue
        try:
            stamp = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except ValueError:
            continue
        if not (now - timedelta(days=14)) <= stamp <= now:
            continue
        bucket = "this" if (now - stamp).days < 7 else "prev"
        for signal in payload.get("signals", []):
            signal_id = str(signal.get("signal_id") or "")
            if signal_id:
                week_counts.setdefault(signal_id, Counter())[bucket] += 1
    lines: list[str] = []
    for signal_id in sorted(week_counts):
        counts = week_counts[signal_id]
        this_week = counts.get("this", 0)
        prev_week = counts.get("prev", 0)
        if this_week == 0:
            continue  # only surface signals with recent (this-week) activity
        drift = this_week >= 3 and (this_week >= 2 * prev_week if prev_week else this_week >= 5)
        lines.append(
            f"- `{signal_id}`: this week {this_week} · last week {prev_week}"
            + (" ⚠ drift" if drift else "")
        )
    if not lines:
        return ""
    return "## Trend (last 14 days)\n\n" + "\n".join(lines) + "\n"


def cron_install(
    *,
    hermes_home: str | Path | None = None,
    schedule: str = "0 9 * * 0",
) -> dict[str, Any]:
    """Best-effort register a weekly no-agent digest cron job in Hermes.

    Idempotent: when a job named ``signals-weekly-digest`` already exists the
    stored script is refreshed and the existing job is reported — never a
    duplicate. On non-Hermes installs the helper prints the manual command.
    """
    home = _home(hermes_home)
    scripts_dir = home / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    script = scripts_dir / "signals-weekly-digest.py"
    script.write_text(_DIGEST_SCRIPT, encoding="utf-8")
    try:
        from cron.jobs import create_job

        existing = digest_cron_status(hermes_home=home)
        if existing:
            return {
                "installed": True,
                "job_id": existing["job_id"],
                "already": True,
            }
        job = create_job(
            prompt="",
            schedule=schedule,
            name="signals-weekly-digest",
            deliver="local",
            script="signals-weekly-digest.py",
            no_agent=True,
        )
        return {"installed": True, "job_id": str(job.get("id", "")), "already": False}
    except Exception as exc:  # pragma: no cover - depends on Hermes presence
        return {
            "installed": False,
            "error": str(exc),
            "manual": (
                f"hermes cron add --schedule '{schedule}' --name signals-weekly-digest "
                "--no-agent --script signals-weekly-digest.py"
            ),
        }


def digest_cron_status(
    *,
    hermes_home: str | Path | None = None,
) -> dict[str, Any] | None:
    """Return ``{job_id, enabled}`` when the weekly digest cron is installed."""
    try:
        from cron.jobs import list_jobs
    except Exception:  # pragma: no cover - depends on Hermes presence
        return None
    try:
        jobs = list_jobs(include_disabled=True)
    except Exception:  # pragma: no cover - store may be absent
        return None
    for job in jobs:
        if str(job.get("name", "")) == "signals-weekly-digest":
            return {
                "job_id": str(job.get("id", "")),
                "enabled": bool(job.get("enabled", True)),
            }
    return None