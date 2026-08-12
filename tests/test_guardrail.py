"""Tests for the pre-execution guardrail and opt-in alerting (notify)."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from unittest.mock import patch

from hermes_signals.guardrail import evaluate_guardrail, guardrail_action, guardrail_scan_text
from hermes_signals.notify import (
    append_guardrail_log,
    build_alert_payload,
    guardrail_log_path,
    webhook_notify,
)

TOKEN = "K9xQm2Vp7LzR4tW8cB1nF3jH5sD6gY0a"  # high-entropy generic secret


def _env(**overrides) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items()}
    env.pop("HERMES_SIGNALS_GUARDRAIL_ACTION", None)
    env.update(overrides)
    return env


# --- guardrail action resolution ---------------------------------------------


def test_guardrail_action_defaults_to_block() -> None:
    assert guardrail_action(_env()) == "block"


def test_guardrail_action_accepts_warn_and_off() -> None:
    assert guardrail_action(_env(HERMES_SIGNALS_GUARDRAIL_ACTION="warn")) == "warn"
    assert guardrail_action(_env(HERMES_SIGNALS_GUARDRAIL_ACTION="off")) == "off"
    assert guardrail_action(_env(HERMES_SIGNALS_GUARDRAIL_ACTION="banana")) == "block"


# --- block / pass behavior ----------------------------------------------------


def test_blocks_github_token_in_command() -> None:
    directive = evaluate_guardrail(
        "terminal",
        {"command": f"git push && echo token={TOKEN}"},
        environ=_env(),
    )
    assert directive is not None
    assert directive["action"] == "block"
    assert "credential-like" in directive["message"]


def test_blocks_sk_prefix_even_with_repeated_chars() -> None:
    directive = evaluate_guardrail(
        "terminal",
        {"command": "ghp_aaaaaaaaaaaaaaaaaaaaaa"},
        environ=_env(),
    )
    assert directive is not None
    assert directive["action"] == "block"


def test_blocks_bearer_header_token() -> None:
    directive = evaluate_guardrail(
        "terminal",
        {"command": f'curl -H "Authorization: Bearer {TOKEN}" https://api.example.com'},
        environ=_env(),
    )
    assert directive is not None
    assert directive["action"] == "block"


def test_passes_low_entropy_bearer() -> None:
    assert (
        evaluate_guardrail(
            "terminal",
            {"command": "curl -H 'Authorization: Bearer aaaaaaaaaaaaaaaaaaaa' url"},
            environ=_env(),
        )
        is None
    )


def test_passes_low_entropy_values() -> None:
    assert (
        evaluate_guardrail(
            "terminal",
            {"command": "token=aaaaaaaaaaaaaaaaaaaa"},
            environ=_env(),
        )
        is None
    )
    assert (
        evaluate_guardrail(
            "write_file",
            {"path": "test.txt", "content": "token=00000000000000000000"},
            environ=_env(),
        )
        is None
    )


def test_passes_clean_arguments() -> None:
    assert (
        evaluate_guardrail(
            "terminal",
            {"command": "pytest -q && ruff check ."},
            environ=_env(),
        )
        is None
    )


def test_passes_empty_or_missing_args() -> None:
    assert evaluate_guardrail("terminal", None, environ=_env()) is None
    assert evaluate_guardrail("terminal", {}, environ=_env()) is None


def test_off_disables_guardrail() -> None:
    assert (
        evaluate_guardrail(
            "terminal",
            {"command": f"echo token={TOKEN}"},
            environ=_env(HERMES_SIGNALS_GUARDRAIL_ACTION="off"),
        )
        is None
    )


def test_warn_mode_returns_warn_directive() -> None:
    directive = evaluate_guardrail(
        "terminal",
        {"command": f"echo token={TOKEN}"},
        environ=_env(HERMES_SIGNALS_GUARDRAIL_ACTION="warn"),
    )
    assert directive is not None
    assert directive["action"] == "warn"


# --- scan window --------------------------------------------------------------


def test_scan_is_bounded_to_first_8k_chars() -> None:
    # A secret buried beyond the scan window is not seen (documented cap; the
    # post-hoc classifier still scans full traces).
    big = "x" * 20000 + f" token={TOKEN}"
    assert (
        evaluate_guardrail("write_file", {"content": big}, environ=_env()) is None
    )
    near = "x" * 1000 + f" token={TOKEN}"
    assert (
        evaluate_guardrail("write_file", {"content": near}, environ=_env()) is not None
    )


def test_guardrail_scan_text_never_raises_on_bad_args() -> None:
    assert guardrail_scan_text(None) == ""
    assert guardrail_scan_text({"weird": object()})  # default=str covers it


# --- notify -------------------------------------------------------------------


def test_guardrail_log_append_is_bounded_and_local(tmp_path) -> None:
    append_guardrail_log(
        tool_name="terminal",
        action="block",
        session_id="s1",
        hermes_home=tmp_path,
    )
    path = guardrail_log_path(hermes_home=tmp_path)
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["tool"] == "terminal"
    assert record["action"] == "block"
    assert record["session_id"] == "s1"
    assert "ts" in record


def test_guardrail_log_never_raises(tmp_path) -> None:
    append_guardrail_log(
        tool_name="terminal",
        action="block",
        hermes_home=tmp_path / "missing" / "home",
    )  # parent created on demand


def test_webhook_notify_posts_json_and_returns_true() -> None:
    captured: dict = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout=None, **kwargs):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["headers"] = request.headers
        return FakeResponse()

    with patch("urllib.request.urlopen", fake_urlopen):
        ok = webhook_notify("https://hooks.example.test/alert", {"event": "test"})

    assert ok is True
    assert captured["url"] == "https://hooks.example.test/alert"
    assert captured["body"] == {"event": "test"}
    assert captured["headers"]["Content-type"] == "application/json"


def test_webhook_notify_false_on_error() -> None:
    def fake_urlopen(request, timeout=None, **kwargs):
        raise OSError("boom")

    with patch("urllib.request.urlopen", fake_urlopen):
        assert webhook_notify("https://hooks.example.test/alert", {"a": 1}) is False


def test_webhook_notify_false_without_url() -> None:
    assert webhook_notify("", {"a": 1}) is False


def test_alert_payload_has_no_raw_content() -> None:
    payload = build_alert_payload(
        signal_ids=["secret-risk", "false-success"],
        trace_id="abc123",
        session_id="sess",
        platform="discord",
    )
    assert payload["signals"] == ["secret-risk", "false-success"]
    assert payload["trace_id"] == "abc123"
    assert "ts" in payload


# --- plugin hook wiring -------------------------------------------------------


def _load_root_plugin():
    root = Path(__file__).parents[1]
    spec = importlib.util.spec_from_file_location(
        "hermes_plugins.hermes_signals_guardrail_test",
        root / "__init__.py",
        submodule_search_locations=[str(root)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "hermes_plugins.hermes_signals_guardrail_test"
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


def test_plugin_registers_pre_tool_call_guardrail_hook() -> None:
    plugin = _load_root_plugin()
    ctx = _Context()
    plugin.register(ctx)
    assert "pre_tool_call" in ctx.hooks
    assert "post_llm_call" in ctx.hooks


def test_plugin_pre_tool_call_hook_blocks_secret_and_passes_clean(tmp_path) -> None:
    plugin = _load_root_plugin()
    ctx = _Context()
    plugin.register(ctx)
    callback = ctx.hooks["pre_tool_call"]

    directive = callback("terminal", {"command": f"echo token={TOKEN}"}, session_id="s1")
    assert directive is not None
    assert directive["action"] == "block"

    assert callback("terminal", {"command": "pytest -q"}) is None
    assert callback("terminal", None) is None


def test_plugin_pre_tool_call_hook_never_raises() -> None:
    plugin = _load_root_plugin()
    ctx = _Context()
    plugin.register(ctx)
    callback = ctx.hooks["pre_tool_call"]

    class WeirdArgs:
        pass

    assert callback("terminal", {"bad": WeirdArgs()}, session_id="x") is None
