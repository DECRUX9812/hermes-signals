"""Tests for the set-and-forget surface: setup, doctor, idempotent cron install."""

from __future__ import annotations

import sys
import types
from argparse import Namespace

from hermes_signals.cli import _run_doctor, _run_setup
from hermes_signals.digest import cron_install, digest_cron_status
from hermes_signals.doctor import run_doctor


def _fake_cron_module(created: list[dict]) -> None:
    """Install a fake ``cron.jobs`` module backed by a mutable job list."""
    fake = types.ModuleType("cron")
    jobs = types.ModuleType("cron.jobs")

    def list_jobs(include_disabled: bool = False):
        return list(created)

    def create_job(**kw):
        job = {"id": f"job{len(created) + 1}", "enabled": True, **kw}
        created.append(job)
        return job

    jobs.list_jobs = list_jobs
    jobs.create_job = create_job
    fake.jobs = jobs
    sys.modules["cron"] = fake
    sys.modules["cron.jobs"] = jobs


def _clear_fake_cron() -> None:
    sys.modules.pop("cron", None)
    sys.modules.pop("cron.jobs", None)


# --- idempotent cron install ------------------------------------------------


def test_cron_install_second_call_reuses_existing_job(tmp_path) -> None:
    created: list[dict] = []
    _fake_cron_module(created)
    try:
        first = cron_install(hermes_home=tmp_path)
        second = cron_install(hermes_home=tmp_path)
    finally:
        _clear_fake_cron()

    assert first["installed"] is True
    assert first["already"] is False
    assert second["installed"] is True
    assert second["already"] is True
    assert second["job_id"] == first["job_id"]
    assert len(created) == 1  # never a duplicate


def test_digest_cron_status_finds_existing_job(tmp_path) -> None:
    created = [{"id": "abc123", "name": "signals-weekly-digest", "enabled": True}]
    _fake_cron_module(created)
    try:
        status = digest_cron_status(hermes_home=tmp_path)
    finally:
        _clear_fake_cron()

    assert status == {"job_id": "abc123", "enabled": True}


def test_digest_cron_status_none_when_absent(tmp_path) -> None:
    _fake_cron_module([])
    try:
        status = digest_cron_status(hermes_home=tmp_path)
    finally:
        _clear_fake_cron()
    assert status is None


def test_cron_install_refreshes_script_even_when_job_exists(tmp_path) -> None:
    created = [{"id": "abc123", "name": "signals-weekly-digest", "enabled": True}]
    _fake_cron_module(created)
    try:
        cron_install(hermes_home=tmp_path)
    finally:
        _clear_fake_cron()
    script = tmp_path / "scripts" / "signals-weekly-digest.py"
    assert script.exists()
    assert "build_digest_markdown" in script.read_text(encoding="utf-8")


# --- doctor ------------------------------------------------------------------


def test_doctor_required_checks_pass_on_fresh_install(tmp_path) -> None:
    checks = run_doctor(hermes_home=tmp_path)
    by_name = {check.name: check for check in checks}
    assert by_name["package"].ok
    assert by_name["store"].ok
    assert by_name["corpus"].ok
    # Optional checks never fail the doctor, even when absent.
    assert by_name["digest-cron"].ok is False
    assert by_name["digest-cron"].required is False
    assert all(check.ok for check in checks if check.required)


def test_doctor_exit_zero_when_only_optional_checks_fail(tmp_path, capsys) -> None:
    _clear_fake_cron()
    exit_code = _run_doctor()
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "all required checks pass" in out


def test_doctor_reports_unwritable_store(tmp_path) -> None:
    blocked = tmp_path / "blocked"
    blocked.write_text("i am a file", encoding="utf-8")
    checks = run_doctor(hermes_home=blocked)
    by_name = {check.name: check for check in checks}
    assert by_name["store"].ok is False


# --- setup --------------------------------------------------------------------


def _setup_args(**overrides) -> Namespace:
    defaults = {
        "dry_run": False,
        "no_backfill": False,
        "no_cron": False,
        "source": None,
        "max_sessions": 100,
    }
    defaults.update(overrides)
    return Namespace(**defaults)


def test_setup_dry_run_writes_nothing(tmp_path, capsys) -> None:
    _clear_fake_cron()
    exit_code = _run_setup(_setup_args(dry_run=True))
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "nothing changed" in out
    assert not (tmp_path / ".hermes" / "signals-armed.json").exists()
    assert not (tmp_path / ".hermes" / "scripts").exists()


def test_setup_full_run_arms_backfills_and_installs_cron(tmp_path, capsys) -> None:
    created: list[dict] = []
    _fake_cron_module(created)
    try:
        exit_code = _run_setup(_setup_args())
    finally:
        _clear_fake_cron()

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "armed" in out
    assert "weekly digest cron installed" in out
    assert "You're set" in out
    assert len(created) == 1
    marker = tmp_path / ".hermes" / "signals-armed.json"
    assert marker.exists()
    # Backfill found no real sessions in the isolated home but must not fail.
    assert "backfill hermes" in out


def test_setup_second_run_is_idempotent(tmp_path, capsys) -> None:
    created: list[dict] = []
    _fake_cron_module(created)
    try:
        _run_setup(_setup_args())
        capsys.readouterr()  # discard first run output
        exit_code = _run_setup(_setup_args())
        out = capsys.readouterr().out
    finally:
        _clear_fake_cron()

    assert exit_code == 0
    assert "already installed" in out
    assert len(created) == 1  # still exactly one job
