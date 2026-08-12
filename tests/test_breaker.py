"""Tests for the session-scoped circuit breaker."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from hermes_signals.breaker import (
    args_key,
    breaker_config,
    breaker_directive,
    new_state,
    note_call,
)

ARGS = {"command": "pytest -q"}


def _env(**overrides) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items()}
    for name in (
        "HERMES_SIGNALS_GUARDRAIL_ACTION",
        "HERMES_SIGNALS_BREAKER_RETRY_N",
        "HERMES_SIGNALS_BREAKER_MAX_CALLS",
    ):
        env.pop(name, None)
    env.update(overrides)
    return env


def _run_calls(state, session: str, n: int, args=ARGS, start: int = 1, **env_kw) -> int | None:
    """Simulate n identical calls from absolute call ``start``; return the absolute block call."""
    blocked = None
    for call in range(start, start + n):
        directive = breaker_directive(state, session, "terminal", args, environ=_env(**env_kw))
        if directive and directive.get("action") == "block":
            blocked = call
            break
        note_call(state, session, args)
    return blocked


def test_blocks_fifth_identical_call_by_default() -> None:
    state = new_state()
    assert _run_calls(state, "s1", 4) is None
    assert _run_calls(state, "s1", 1, start=5) == 5


def test_different_args_do_not_accumulate() -> None:
    state = new_state()
    for i in range(20):
        breaker_directive(state, "s1", "terminal", {"command": f"cmd {i}"}, environ=_env())
        note_call(state, "s1", {"command": f"cmd {i}"})
    # No single args key reached the threshold.
    assert breaker_directive(state, "s1", "terminal", {"command": "cmd 0"}, environ=_env()) is None


def test_sessions_are_isolated() -> None:
    state = new_state()
    _run_calls(state, "s1", 10)
    # A different session starts fresh.
    assert breaker_directive(state, "s2", "terminal", ARGS, environ=_env()) is None


def test_retry_n_zero_disables() -> None:
    state = new_state()
    assert _run_calls(state, "s1", 20, **{"HERMES_SIGNALS_BREAKER_RETRY_N": "0"}) is None


def test_retry_n_custom_threshold() -> None:
    state = new_state()
    assert _run_calls(state, "s1", 2, **{"HERMES_SIGNALS_BREAKER_RETRY_N": "3"}) is None
    assert _run_calls(state, "s1", 1, start=3, **{"HERMES_SIGNALS_BREAKER_RETRY_N": "3"}) == 3


def test_max_calls_ceiling() -> None:
    state = new_state()
    config = {"HERMES_SIGNALS_BREAKER_RETRY_N": "0", "HERMES_SIGNALS_BREAKER_MAX_CALLS": "3"}
    for call in range(1, 4):
        assert breaker_directive(state, "s1", "terminal", {"command": f"c{call}"}, environ=_env(**config)) is None
        note_call(state, "s1", {"command": f"c{call}"})
    directive = breaker_directive(state, "s1", "terminal", {"command": "c4"}, environ=_env(**config))
    assert directive is not None
    assert "exceeded 3 tool calls" in directive["message"]


def test_warn_action_reports_without_blocking() -> None:
    state = new_state()
    blocked = None
    directive = None
    for call in range(1, 6):
        directive = breaker_directive(
            state, "s1", "terminal", ARGS,
            environ=_env(HERMES_SIGNALS_GUARDRAIL_ACTION="warn"),
        )
        note_call(state, "s1", ARGS)
        if directive:
            blocked = call
    assert blocked == 5
    assert directive["action"] == "warn"


def test_off_action_disables() -> None:
    state = new_state()
    assert _run_calls(state, "s1", 20, **{"HERMES_SIGNALS_GUARDRAIL_ACTION": "off"}) is None


def test_state_is_bounded() -> None:
    state = new_state()
    for i in range(100):
        note_call(state, f"session-{i}", ARGS)
    assert len(state) <= 64


def test_args_key_order_insensitive_and_bounded() -> None:
    assert args_key({"a": 1, "b": 2}) == args_key({"b": 2, "a": 1})
    big = {"content": "x" * 10000}
    assert len(args_key(big)) <= 200
    assert args_key(None) == ""


def test_breaker_config_defaults() -> None:
    config = breaker_config(_env())
    assert config == {"retry_n": 5, "max_calls": 0}


def test_breaker_config_parses_env() -> None:
    config = breaker_config(_env(HERMES_SIGNALS_BREAKER_RETRY_N="7", HERMES_SIGNALS_BREAKER_MAX_CALLS="50"))
    assert config == {"retry_n": 7, "max_calls": 50}


# --- plugin hook wiring -------------------------------------------------------


def _load_root_plugin():
    root = Path(__file__).parents[1]
    spec = importlib.util.spec_from_file_location(
        "hermes_plugins.hermes_signals_breaker_test",
        root / "__init__.py",
        submodule_search_locations=[str(root)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "hermes_plugins.hermes_signals_breaker_test"
    module.__path__ = [str(root)]
    spec.loader.exec_module(module)
    return module


class _Context:
    def __init__(self) -> None:
        self.hooks: dict[str, object] = {}

    def register_hook(self, name, callback) -> None:
        self.hooks[name] = callback

    def register_cli_command(self, **kwargs) -> None:
        pass


def test_plugin_hook_trips_breaker_on_identical_calls() -> None:
    plugin = _load_root_plugin()
    ctx = _Context()
    plugin.register(ctx)
    callback = ctx.hooks["pre_tool_call"]
    plugin._BREAKER_STATE.clear()

    results = []
    for _ in range(6):
        directive = callback("terminal", {"command": "pytest -q"}, session_id="trip-test")
        results.append(directive)
    assert results[:4] == [None, None, None, None]
    assert results[4] is not None
    assert results[4]["action"] == "block"
    assert "circuit breaker" in results[4]["message"]
    # After a block, still blocked.
    assert callback("terminal", {"command": "pytest -q"}, session_id="trip-test")["action"] == "block"


def test_plugin_hook_allows_varied_calls() -> None:
    plugin = _load_root_plugin()
    ctx = _Context()
    plugin.register(ctx)
    callback = ctx.hooks["pre_tool_call"]
    plugin._BREAKER_STATE.clear()

    for i in range(10):
        assert callback("terminal", {"command": f"pytest -k test_{i}"}) is None
