"""Test isolation: never write to the real ~/.hermes/ profile.

Mirrors the parent repo's ``_isolate_hermes_home`` rule — every test redirects
HERMES_HOME to a per-test temp dir so store/backfill tests can never touch the
user's real signals stores.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_hermes_home(tmp_path, monkeypatch):
    isolated = tmp_path / ".hermes"
    isolated.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(isolated))
    return isolated
