"""Two-stage escalation: confirm ambiguous signals with a cheap model.

Implements the rd-signal-2 pattern: deterministic filtering runs first
(stage 1) and only *ambiguous* candidates consume a model call (stage 2) —
"model calls should scale with uncertainty, not traffic".

Zero-dependency: speaks OpenAI-compatible ``/chat/completions`` over stdlib
``urllib``. Escalation is opt-in; when disabled or misconfigured, ambiguous
signals pass through unchanged with ``confirmed`` left unset.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import replace
from pathlib import Path
from typing import Any

from hermes_signals.classifier import Signal, _assistant_text, _redact

__all__ = [
    "escalate_signals",
    "escalation_config_from_env",
    "escalation_source",
    "resolve_escalation_config",
]

_DEFAULT_TIMEOUT = 15
_DEFAULT_MAX_INPUT_CHARS = 2000
_VERDICT_RE = re.compile(
    r'"verdict"\s*:\s*"(confirm(?:ed)?|reject(?:ed)?|unknown)"', re.IGNORECASE
)


def _build_prompt(signal: Signal, trace: dict[str, Any], max_input_chars: int) -> str:
    response = _assistant_text(
        [event for event in trace.get("events", []) if isinstance(event, dict)], trace
    )
    payload = {
        "task": (
            "You are a conservative reviewer for one agent-behavior quality signal. "
            "The deterministic stage already flagged this trace as a candidate; "
            "confirm only when the evidence truly supports the signal."
        ),
        "signal": signal.to_dict(),
        "final_response_excerpt": _redact(response)[:max_input_chars],
        "question": "Is the evidence enough to confirm this signal, or is it a false positive?",
        "reply": 'JSON object with "verdict": "confirm" | "reject" | "unknown" and a one-line "reason".',
    }
    return json.dumps(payload, ensure_ascii=False)


def _call_model(
    prompt: str,
    *,
    base_url: str,
    model: str,
    api_key: str,
    timeout: int,
) -> str | None:
    url = base_url.rstrip("/") + "/chat/completions"
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 120,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            return None
        data = json.loads(response.read().decode("utf-8", errors="ignore"))
    return data["choices"][0]["message"]["content"]


def _parse_verdict(content: str | None) -> bool | None:
    """Return True (confirm), False (reject), or None (unknown)."""
    if not content:
        return None
    match = _VERDICT_RE.search(content)
    if match:
        return {
            "confirm": True,
            "confirmed": True,
            "reject": False,
            "rejected": False,
        }.get(match.group(1).lower())
    try:
        data = json.loads(content)
        verdict = str(data.get("verdict") or "").lower()
        if verdict in ("confirm", "confirmed"):
            return True
        if verdict in ("reject", "rejected"):
            return False
    except (TypeError, ValueError):
        pass
    return None


def escalate_signals(
    signals: list[Signal],
    trace: dict[str, Any],
    *,
    base_url: str,
    model: str,
    api_key: str,
    timeout: int = _DEFAULT_TIMEOUT,
    max_input_chars: int = _DEFAULT_MAX_INPUT_CHARS,
) -> list[Signal]:
    """Confirm ambiguous signals via a cheap model; leave the rest untouched.

    Never raises: any transport or parse failure keeps the candidate as-is
    with ``confirmed`` unset, so escalation cannot break the deterministic
    stage.
    """
    escalated: list[Signal] = []
    for signal in signals:
        if not signal.ambiguous:
            escalated.append(signal)
            continue
        try:
            prompt = _build_prompt(signal, trace, max_input_chars)
            content = _call_model(
                prompt,
                base_url=base_url,
                model=model,
                api_key=api_key,
                timeout=timeout,
            )
            verdict = _parse_verdict(content)
        except Exception:
            verdict = None
            content = None
        escalated.append(
            replace(
                signal,
                confirmed=verdict,
                judge_model=model if content is not None else signal.judge_model,
            )
        )
    return escalated


def escalation_config_from_env(environ: dict[str, str] | None = None) -> dict[str, str] | None:
    """Read escalation config from environment; None when not fully configured."""
    env = environ if environ is not None else os.environ
    base_url = env.get("HERMES_SIGNALS_ESCALATION_BASE_URL", "").strip()
    model = env.get("HERMES_SIGNALS_ESCALATION_MODEL", "").strip()
    api_key = env.get("HERMES_SIGNALS_ESCALATION_API_KEY", "").strip()
    if not base_url or not model:
        return None
    return {"base_url": base_url, "model": model, "api_key": api_key}


def _hermes_config(hermes_home: str | Path | None, environ: dict[str, str]) -> dict[str, str] | None:
    """Read provider/model/base_url + api key from a Hermes profile."""
    try:
        import yaml  # soft dependency: only present inside a Hermes install
    except ImportError:
        return None
    home = Path(hermes_home or environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
    try:
        raw = yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8")) or {}
        model_section = raw.get("model", {}) or {}
        base_url = str(model_section.get("base_url") or "").strip()
        provider = str(model_section.get("provider") or "").strip()
        model = str(model_section.get("default") or "").strip()
        if not base_url or not model:
            return None
        api_key = _auth_key(home, provider)
        return {"base_url": base_url, "model": model, "api_key": api_key}
    except Exception:
        return None


def _auth_key(home: Path, provider: str) -> str:
    try:
        auth = json.loads((home / "auth.json").read_text(encoding="utf-8"))
    except Exception:
        return ""
    for section in ("providers", "credential_pool"):
        entry = (auth.get(section) or {}).get(provider)
        if isinstance(entry, dict):
            key = entry.get("api_key") or entry.get("key")
            if key:
                return str(key)
    return ""


def _probe_json(url: str, api_key: str = "", timeout: float = 1.5) -> Any | None:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                return None
            return json.loads(response.read().decode("utf-8", errors="ignore"))
    except Exception:
        return None


def _detect_local(environ: dict[str, str]) -> dict[str, str] | None:
    # Ollama: keyless, real model list.
    tags = _probe_json("http://127.0.0.1:11434/api/tags")
    if isinstance(tags, dict):
        models = tags.get("models") or []
        if models and isinstance(models[0], dict) and models[0].get("name"):
            return {
                "base_url": "http://127.0.0.1:11434/v1",
                "model": str(models[0]["name"]),
                "api_key": "",
            }
    # CLIProxy (Antigravity local): only when a key already exists in env.
    local_key = (
        environ.get("CLIPROXY_API_KEY", "").strip()
        or environ.get("CLIPROXYAPI_API_KEY", "").strip()
    )
    if local_key:
        data = _probe_json("http://127.0.0.1:8317/v1/models", api_key=local_key)
        if isinstance(data, dict):
            models = data.get("data") or []
            model = _pick_model_id([m.get("id") for m in models if isinstance(m, dict)])
            if model:
                return {
                    "base_url": "http://127.0.0.1:8317/v1",
                    "model": model,
                    "api_key": local_key,
                }
    return None


def _pick_model_id(candidates: list[Any]) -> str:
    """Pick a cheap classification-suitable model id from a provider list.

    Excludes agent/image/thinking/opus variants (they do not reliably return
    compact JSON verdicts or are too expensive) and prefers flash-tier models.
    """
    excluded = ("agent", "image", "thinking", "opus", "pro")
    usable = [
        str(candidate)
        for candidate in candidates
        if str(candidate) and not any(token in str(candidate).lower() for token in excluded)
    ]
    if not usable:
        return ""
    flash = [model for model in usable if "flash" in model.lower()]
    if flash:
        return flash[0]
    return usable[0]


def resolve_escalation_config(
    *,
    hermes_home: str | Path | None = None,
    environ: dict[str, str] | None = None,
) -> dict[str, str] | None:
    """Resolve escalation config with zero configuration required.

    Order: explicit env vars → Hermes config.yaml (provider/model/base_url +
    auth.json key) → local endpoint detection (ollama keyless; CLIProxy when a
    key already exists) → None (deterministic-only, the graceful default).
    """
    env = environ if environ is not None else os.environ
    from_env = escalation_config_from_env(env)
    if from_env:
        return from_env
    from_hermes = _hermes_config(hermes_home, env)
    if from_hermes:
        return from_hermes
    return _detect_local(env)


def escalation_source(
    *,
    hermes_home: str | Path | None = None,
    environ: dict[str, str] | None = None,
) -> tuple[str, dict[str, str] | None]:
    """Return (mode, config) where mode is env | hermes | local | off."""
    env = environ if environ is not None else os.environ
    if escalation_config_from_env(env):
        return "env", escalation_config_from_env(env)
    if _hermes_config(hermes_home, env):
        return "hermes", _hermes_config(hermes_home, env)
    local = _detect_local(env)
    if local:
        return "local", local
    return "off", None