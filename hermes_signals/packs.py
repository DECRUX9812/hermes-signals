"""Policy packs: local, versioned, user-tunable signal overrides.

A pack is a JSON (or YAML, when PyYAML is available) file declaring per-signal
``severity`` overrides, whole-signal ``suppress``, or evidence-based
``suppress_when`` rules. Defaults stay conservative; packs are how power users
tune the classifier without forking code — the local, open alternative to
Raindrop's hosted Signal Builder.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

from hermes_signals.classifier import Signal

__all__ = ["apply_pack", "installed_packs", "load_pack"]

_KNOWN_SEVERITIES = {"low", "medium", "high", "critical"}


def _home(hermes_home: str | Path | None) -> Path:
    return Path(hermes_home or os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))


def load_pack(path: str | Path) -> dict[str, Any]:
    """Load a pack file (JSON, or YAML when PyYAML is importable)."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml
        except ImportError as exc:
            raise ValueError(f"pack {path} is not valid JSON and PyYAML is unavailable") from exc
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("pack must be a JSON/YAML object")
    return data


def apply_pack(signals: list[Signal], pack: dict[str, Any]) -> list[Signal]:
    """Apply pack policy overrides to a signal list (never mutates inputs)."""
    policies = pack.get("policies", [])
    if not isinstance(policies, list):
        raise ValueError("pack.policies must be a list")
    by_id: dict[str, dict[str, Any]] = {}
    for policy in policies:
        if not isinstance(policy, dict):
            continue
        signal_id = str(policy.get("signal_id") or "").strip()
        if signal_id:
            by_id[signal_id] = policy

    applied: list[Signal] = []
    for signal in signals:
        policy = by_id.get(signal.signal_id)
        if not policy:
            applied.append(signal)
            continue
        if policy.get("suppress"):
            continue
        suppress_when = policy.get("suppress_when") or []
        if any(sub in item for item in signal.evidence for sub in suppress_when):
            continue
        severity = policy.get("severity")
        if severity:
            severity = str(severity).lower()
            if severity not in _KNOWN_SEVERITIES:
                raise ValueError(f"unknown severity {severity!r} for {signal.signal_id}")
            signal = replace(signal, severity=severity)
        applied.append(signal)
    return applied


def installed_packs(hermes_home: str | Path | None = None) -> list[dict[str, Any]]:
    """List packs under ``$HERMES_HOME/signals-packs/`` (skips broken files)."""
    packs_dir = _home(hermes_home) / "signals-packs"
    packs: list[dict[str, Any]] = []
    if not packs_dir.is_dir():
        return packs
    for path in sorted(packs_dir.glob("*.json")) + sorted(
        packs_dir.glob("*.yaml")
    ) + sorted(packs_dir.glob("*.yml")):
        try:
            data = load_pack(path)
        except (OSError, ValueError):
            continue
        packs.append(
            {
                "name": str(data.get("name") or path.stem),
                "version": data.get("version"),
                "path": str(path),
            }
        )
    return packs