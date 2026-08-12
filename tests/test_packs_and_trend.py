"""Tests for policy packs (severity overrides, suppression) and digest trend."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from hermes_signals.classifier import Signal
from hermes_signals.digest import _trend_section
from hermes_signals.packs import apply_pack, installed_packs, load_pack
from hermes_signals.store import append_payload

PACK = {
    "name": "quiet",
    "version": 1,
    "policies": [
        {"signal_id": "secret-risk", "severity": "low"},
        {"signal_id": "retry-loop", "suppress": True},
        {"signal_id": "subagent-handoff-loss", "suppress_when": ["subagent_tool=codex"]},
    ],
}


def test_apply_pack_severity_override() -> None:
    signals = [Signal("secret-risk", "critical", "s", ("e",))]
    applied = apply_pack(signals, PACK)
    assert applied[0].severity == "low"


def test_apply_pack_suppresses_signal() -> None:
    signals = [Signal("retry-loop", "medium", "s", ("e",))]
    assert apply_pack(signals, PACK) == []


def test_apply_pack_suppress_when_matches_evidence() -> None:
    signals = [Signal("subagent-handoff-loss", "medium", "s", ("subagent_tool=codex",))]
    assert apply_pack(signals, PACK) == []
    signals2 = [Signal("subagent-handoff-loss", "medium", "s", ("subagent_tool=delegate_task",))]
    assert len(apply_pack(signals2, PACK)) == 1


def test_apply_pack_leaves_unlisted_signals_alone() -> None:
    signals = [Signal("false-success", "high", "s", ("e",))]
    assert apply_pack(signals, PACK) == signals


def test_apply_pack_rejects_bad_severity() -> None:
    signals = [Signal("secret-risk", "critical", "s", ("e",))]
    try:
        apply_pack(signals, {"policies": [{"signal_id": "secret-risk", "severity": "extreme"}]})
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")


def test_load_and_installed_packs(tmp_path) -> None:
    pack_dir = tmp_path / ".hermes" / "signals-packs"
    pack_dir.mkdir(parents=True)
    (pack_dir / "quiet.json").write_text(json.dumps(PACK), encoding="utf-8")
    (pack_dir / "broken.json").write_text("not json", encoding="utf-8")

    loaded = load_pack(pack_dir / "quiet.json")
    assert loaded["name"] == "quiet"
    packs = installed_packs(hermes_home=tmp_path / ".hermes")
    assert len(packs) == 1
    assert packs[0]["name"] == "quiet"


def _record(trace_id: str, signal_id: str, ts: str, path) -> None:
    append_payload(
        {
            "trace_id": trace_id,
            "session_id": "s",
            "platform": "test",
            "ts": ts,
            "signals": [{"signal_id": signal_id, "severity": "medium", "summary": "s", "evidence": []}],
        },
        path,
    )


def test_trend_section_counts_weeks_and_flags_drift(tmp_path) -> None:
    path = tmp_path / "signals.jsonl"
    # This week (5 secret-risk) vs last week (1) → drift.
    now = datetime.now(UTC)
    for i in range(5):
        _record(f"t{i}", "secret-risk", (now - timedelta(days=1)).isoformat(), path)
    _record("old", "secret-risk", (now - timedelta(days=8)).isoformat(), path)
    _record("old2", "retry-loop", (now - timedelta(days=8)).isoformat(), path)

    section = _trend_section(path)
    assert "secret-risk" in section
    assert "5" in section  # this week count
    assert "⚠" in section  # drift flagged
    assert "retry-loop" not in section  # no recent retry-loop records


def test_trend_section_empty_without_timestamps(tmp_path) -> None:
    path = tmp_path / "signals.jsonl"
    append_payload(
        {
            "trace_id": "x",
            "session_id": "s",
            "platform": "test",
            "signals": [{"signal_id": "secret-risk", "severity": "medium", "summary": "s", "evidence": []}],
        },
        path,
    )
    assert _trend_section(path) == ""