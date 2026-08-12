from __future__ import annotations

import importlib.util
import json
from pathlib import Path


class Context:
    def __init__(self) -> None:
        self.hooks: dict[str, object] = {}
        self.commands: dict[str, dict] = {}

    def register_hook(self, name, callback) -> None:
        self.hooks[name] = callback

    def register_cli_command(self, **kwargs) -> None:
        self.commands[kwargs["name"]] = kwargs


def load_root_plugin():
    root = Path(__file__).parents[1]
    module_name = "hermes_plugins.hermes_signals_test"
    spec = importlib.util.spec_from_file_location(
        module_name,
        root / "__init__.py",
        submodule_search_locations=[str(root)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    module.__package__ = module_name
    module.__path__ = [str(root)]
    spec.loader.exec_module(module)
    return module


def test_root_module_registers_hermes_hook_and_cli() -> None:
    plugin = load_root_plugin()
    ctx = Context()

    plugin.register(ctx)

    assert "post_llm_call" in ctx.hooks
    assert "signals" in ctx.commands
    assert callable(ctx.commands["signals"]["setup_fn"])
    assert callable(ctx.commands["signals"]["handler_fn"])


def test_root_plugin_hook_writes_local_bounded_record(tmp_path) -> None:
    plugin = load_root_plugin()
    ctx = Context()
    plugin.register(ctx)

    secret = "ghp_123456789012345678901234567890"
    callback = ctx.hooks["post_llm_call"]
    # The callback uses the default store in production. Import the underlying
    # store and point it at a temporary path for this contract test.
    import hermes_signals.store as store

    original = store.default_store_path
    store.default_store_path = lambda: tmp_path / "signals.jsonl"
    try:
        callback(
            conversation_history=[
                {"role": "tool", "tool_call_id": "1", "content": f"token={secret}"},
                {"role": "assistant", "content": "I found a token."},
            ],
            assistant_response="I found a token.",
            session_id="session-1",
            platform="test",
        )
    finally:
        store.default_store_path = original

    saved = (tmp_path / "signals.jsonl").read_text(encoding="utf-8")
    assert secret not in saved
    payload = json.loads(saved)
    assert payload["platform"] == "test"
    assert payload["signals"][0]["signal_id"] == "secret-risk"


def test_manifest_declares_standalone_cross_platform_plugin() -> None:
    manifest = (Path(__file__).parents[1] / "plugin.yaml").read_text(encoding="utf-8")

    assert "name: hermes-signals" in manifest
    assert "kind: standalone" in manifest
    assert all(platform in manifest for platform in ("linux", "macos", "windows"))
