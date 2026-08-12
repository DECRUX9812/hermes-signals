"""Self-check for a Signals installation (``hermes signals doctor``).

Deterministic and local: verifies the store is writable, the shipped regression
corpus still passes, and reports the (optional) escalation and digest-cron
configuration. Hard checks fail the command; soft checks are informational.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from hermes_signals import __version__
from hermes_signals.corpus import corpus_summary, run_corpus
from hermes_signals.digest import digest_cron_status
from hermes_signals.escalate import escalation_source

__all__ = ["Check", "run_doctor"]


@dataclass
class Check:
    """One doctor result."""

    name: str
    ok: bool
    detail: str
    required: bool = True


def _home(hermes_home: str | Path | None) -> Path:
    return Path(hermes_home or os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))


def run_doctor(*, hermes_home: str | Path | None = None) -> list[Check]:
    """Return the ordered self-check results (never raises)."""
    home = _home(hermes_home)
    checks: list[Check] = []

    # Hard: package is importable and versioned.
    checks.append(Check("package", True, f"hermes-signals {__version__}"))

    # Hard: the signals store is writable (append-open creates it if absent).
    store = home / "signals.jsonl"
    try:
        store.parent.mkdir(parents=True, exist_ok=True)
        with store.open("a", encoding="utf-8"):
            pass
        checks.append(Check("store", True, f"writable: {store}"))
    except OSError as exc:
        checks.append(Check("store", False, f"not writable: {exc}"))

    # Hard: the shipped regression corpus still passes (policy safety).
    try:
        summary = corpus_summary(run_corpus())
        checks.append(
            Check(
                "corpus",
                summary["failed"] == 0,
                f"{summary['passed']}/{summary['total']} traces match labels",
            )
        )
    except Exception as exc:  # pragma: no cover - corpus is package data
        checks.append(Check("corpus", False, f"could not run: {exc}"))

    # Soft: escalation (optional model confirmation) configuration.
    mode, config = escalation_source(hermes_home=home)
    detail = f"mode={mode}"
    if config:
        detail += f" · {config['model']} @ {config['base_url']}"
    checks.append(Check("escalation", True, detail, required=False))

    # Soft: weekly digest cron job.
    cron = digest_cron_status(hermes_home=home)
    if cron:
        state = "enabled" if cron["enabled"] else "disabled"
        checks.append(
            Check(
                "digest-cron",
                True,
                f"weekly job {cron['job_id']} ({state})",
                required=False,
            )
        )
    else:
        checks.append(
            Check(
                "digest-cron",
                False,
                "not installed — run `hermes signals setup`",
                required=False,
            )
        )

    return checks
