"""Tests for zero-config escalation auto-detection.

Resolution order: explicit env vars → Hermes config.yaml + auth.json → local
endpoint detection (ollama keyless; CLIProxy when a key already exists) → off.
All network probing is mocked; no live calls in tests.
"""

from __future__ import annotations

import json
import urllib.request
from unittest.mock import patch

from hermes_signals.escalate import resolve_escalation_config


def test_env_config_wins(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_SIGNALS_ESCALATION_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("HERMES_SIGNALS_ESCALATION_MODEL", "env-model")
    monkeypatch.setenv("HERMES_SIGNALS_ESCALATION_API_KEY", "env-key")
    monkeypatch.setenv("CLIPROXY_API_KEY", "local-key")

    config = resolve_escalation_config()
    assert config == {"base_url": "https://env.example/v1", "model": "env-model", "api_key": "env-key"}


def _install_fake_yaml(raw: dict):
    import sys
    import types

    fake = types.ModuleType("yaml")
    fake.safe_load = lambda text: raw
    sys.modules["yaml"] = fake


def test_hermes_config_used_when_base_url_and_key_present(tmp_path, monkeypatch) -> None:
    home = tmp_path / ".hermes"
    home.mkdir(exist_ok=True)
    (home / "config.yaml").write_text(
        "model:\n  provider: acme\n  default: acme-mini\n  base_url: https://acme.example/v1\n",
        encoding="utf-8",
    )
    (home / "auth.json").write_text(
        json.dumps({"providers": {"acme": {"api_key": "secret-acme-key"}}}), encoding="utf-8"
    )
    _install_fake_yaml(
        {"model": {"provider": "acme", "default": "acme-mini", "base_url": "https://acme.example/v1"}}
    )
    try:
        config = resolve_escalation_config(hermes_home=home)
    finally:
        import sys

        sys.modules.pop("yaml", None)
    assert config == {
        "base_url": "https://acme.example/v1",
        "model": "acme-mini",
        "api_key": "secret-acme-key",
    }


def test_ollama_detection_is_keyless(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("HERMES_SIGNALS_ESCALATION_BASE_URL", raising=False)
    monkeypatch.delenv("HERMES_SIGNALS_ESCALATION_MODEL", raising=False)
    monkeypatch.delenv("CLIPROXY_API_KEY", raising=False)

    def fake_urlopen(request, timeout=None, **kwargs):
        assert request.full_url.startswith("http://127.0.0.1:11434")
        body = {"models": [{"name": "llama3.2:3b"}]}
        return _response(json.dumps(body))

    with patch("urllib.request.urlopen", fake_urlopen):
        config = resolve_escalation_config()
    assert config["base_url"] == "http://127.0.0.1:11434/v1"
    assert config["model"] == "llama3.2:3b"
    assert config["api_key"] == ""


def test_cliproxy_detection_uses_existing_key(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("HERMES_SIGNALS_ESCALATION_BASE_URL", raising=False)
    monkeypatch.delenv("HERMES_SIGNALS_ESCALATION_MODEL", raising=False)
    monkeypatch.setenv("CLIPROXY_API_KEY", "local-key")

    def fake_urlopen(request, timeout=None, **kwargs):
        if "11434" in request.full_url:
            raise urllib.error.URLError("no ollama")
        body = {"data": [{"id": "gemini-3.6-flash-high"}, {"id": "claude-sonnet-4-6"}]}
        return _response(json.dumps(body))

    with patch("urllib.request.urlopen", fake_urlopen):
        config = resolve_escalation_config()
    assert config["base_url"] == "http://127.0.0.1:8317/v1"
    assert config["model"] == "gemini-3.6-flash-high"
    assert config["api_key"] == "local-key"


def test_nothing_detected_returns_none(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("HERMES_SIGNALS_ESCALATION_BASE_URL", raising=False)
    monkeypatch.delenv("HERMES_SIGNALS_ESCALATION_MODEL", raising=False)
    monkeypatch.delenv("CLIPROXY_API_KEY", raising=False)
    for key in ("OPENROUTER_API_KEY", "OPENCODE_GO_API_KEY", "OPENCODE_ZEN_API_KEY",
                "DASHSCOPE_API_KEY", "HYPERCHARM_API_KEY"):
        monkeypatch.delenv(key, raising=False)

    def fake_urlopen(request, timeout=None, **kwargs):
        raise urllib.error.URLError("connection refused")

    with patch("urllib.request.urlopen", fake_urlopen):
        config = resolve_escalation_config()
    assert config is None


# --- catalog / registry provider resolution (config.yaml without base_url) ---


def test_config_provider_without_base_url_uses_catalog(tmp_path, monkeypatch) -> None:
    home = tmp_path / ".hermes"
    home.mkdir(exist_ok=True)
    (home / "config.yaml").write_text(
        "model:\n  provider: opencode-go\n  default: deepseek-v4-flash\n",
        encoding="utf-8",
    )
    _install_fake_yaml({"model": {"provider": "opencode-go", "default": "deepseek-v4-flash"}})
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "go-key")
    monkeypatch.delenv("CLIPROXY_API_KEY", raising=False)
    for key in ("OPENROUTER_API_KEY", "OPENCODE_ZEN_API_KEY", "DASHSCOPE_API_KEY",
                "HYPERCHARM_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    try:
        config = resolve_escalation_config(hermes_home=home)
    finally:
        import sys

        sys.modules.pop("yaml", None)

    assert config == {
        "base_url": "https://opencode.ai/zen/go/v1",
        "model": "deepseek-v4-flash",  # config model wins over the catalog default
        "api_key": "go-key",
    }


def test_config_provider_without_key_returns_none(tmp_path, monkeypatch) -> None:
    home = tmp_path / ".hermes"
    home.mkdir(exist_ok=True)
    (home / "config.yaml").write_text(
        "model:\n  provider: opencode-go\n  default: deepseek-v4-flash\n",
        encoding="utf-8",
    )
    _install_fake_yaml({"model": {"provider": "opencode-go", "default": "deepseek-v4-flash"}})
    monkeypatch.delenv("OPENCODE_GO_API_KEY", raising=False)
    monkeypatch.delenv("CLIPROXY_API_KEY", raising=False)
    for key in ("OPENROUTER_API_KEY", "OPENCODE_ZEN_API_KEY", "DASHSCOPE_API_KEY",
                "HYPERCHARM_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    try:
        def _refused(request, timeout=None, **kwargs):
            raise urllib.error.URLError("connection refused")

        with patch("urllib.request.urlopen", _refused):
            config = resolve_escalation_config(hermes_home=home)
    finally:
        import sys

        sys.modules.pop("yaml", None)
    assert config is None


def test_config_provider_uses_hermes_registry(tmp_path, monkeypatch) -> None:
    """A provider Hermes registers (but the static catalog misses) resolves too."""
    import sys
    import types

    profile = types.SimpleNamespace(
        name="nvidia",
        base_url="https://integrate.api.nvidia.com/v1",
        env_vars=("NVIDIA_API_KEY",),
        default_aux_model="deepseek-ai/deepseek-r1-distill-qwen-14b",
    )
    providers = types.ModuleType("providers")
    providers.get_provider_profile = lambda name: profile if name == "nvidia" else None
    sys.modules["providers"] = providers

    home = tmp_path / ".hermes"
    home.mkdir(exist_ok=True)
    (home / "config.yaml").write_text(
        "model:\n  provider: nvidia\n  default: custom-judge\n",
        encoding="utf-8",
    )
    _install_fake_yaml({"model": {"provider": "nvidia", "default": "custom-judge"}})
    monkeypatch.setenv("NVIDIA_API_KEY", "nv-key")
    monkeypatch.delenv("CLIPROXY_API_KEY", raising=False)
    for key in ("OPENROUTER_API_KEY", "OPENCODE_GO_API_KEY", "OPENCODE_ZEN_API_KEY",
                "DASHSCOPE_API_KEY", "HYPERCHARM_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    try:
        config = resolve_escalation_config(hermes_home=home)
    finally:
        sys.modules.pop("providers", None)
        sys.modules.pop("yaml", None)

    assert config == {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "model": "custom-judge",  # explicit config model beats registry default
        "api_key": "nv-key",
    }


def test_env_provider_detection_fires_last(tmp_path, monkeypatch) -> None:
    """With no config and no local endpoint, a keyed catalog provider resolves."""
    import sys

    sys.modules.pop("yaml", None)
    monkeypatch.delenv("HERMES_SIGNALS_ESCALATION_BASE_URL", raising=False)
    monkeypatch.delenv("HERMES_SIGNALS_ESCALATION_MODEL", raising=False)
    monkeypatch.delenv("CLIPROXY_API_KEY", raising=False)
    monkeypatch.delenv("OPENCODE_GO_API_KEY", raising=False)
    monkeypatch.delenv("OPENCODE_ZEN_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")

    def fake_urlopen(request, timeout=None, **kwargs):
        raise urllib.error.URLError("connection refused")

    with patch("urllib.request.urlopen", fake_urlopen):
        from hermes_signals.escalate import escalation_source

        mode, config = escalation_source(hermes_home=tmp_path)
    assert mode == "env-provider"
    assert config["base_url"] == "https://openrouter.ai/api/v1"
    assert config["model"] == "deepseek/deepseek-chat"
    assert config["api_key"] == "or-key"


def test_env_provider_base_url_override(tmp_path, monkeypatch) -> None:
    import sys

    sys.modules.pop("yaml", None)
    monkeypatch.delenv("HERMES_SIGNALS_ESCALATION_BASE_URL", raising=False)
    monkeypatch.delenv("HERMES_SIGNALS_ESCALATION_MODEL", raising=False)
    monkeypatch.delenv("CLIPROXY_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENCODE_GO_API_KEY", raising=False)
    monkeypatch.delenv("OPENCODE_ZEN_API_KEY", raising=False)
    monkeypatch.delenv("HYPERCHARM_API_KEY", raising=False)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "ds-key")
    monkeypatch.setenv("DASHSCOPE_BASE_URL", "https://proxy.example/v1")

    def fake_urlopen(request, timeout=None, **kwargs):
        raise urllib.error.URLError("connection refused")

    with patch("urllib.request.urlopen", fake_urlopen):
        from hermes_signals.escalate import escalation_source

        mode, config = escalation_source(hermes_home=tmp_path)
    assert mode == "env-provider"
    assert config["base_url"] == "https://proxy.example/v1"


def _response(body: str):
    return type(
        "FakeResponse",
        (),
        {
            "__enter__": lambda self: self,
            "__exit__": lambda *a: None,
            "read": lambda self: body.encode(),
            "status": 200,
        },
    )()