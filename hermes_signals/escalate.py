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
_BATCH_VERDICT_RE = re.compile(
    r'"([A-Za-z0-9\-]+)"\s*:\s*"(confirm(?:ed)?|reject(?:ed)?|unknown)"', re.IGNORECASE
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
        return _verdict_value(match.group(1))
    try:
        data = json.loads(content)
        verdict = str(data.get("verdict") or "").lower()
        return _verdict_value(verdict)
    except (TypeError, ValueError):
        pass
    return None


def _verdict_value(value: str | None) -> bool | None:
    if not value:
        return None
    normalized = str(value).strip().lower()
    if normalized in ("confirm", "confirmed"):
        return True
    if normalized in ("reject", "rejected"):
        return False
    return None


def _parse_batch(content: str | None, case_ids: list[str]) -> dict[str, bool | None]:
    """Parse a batch response into {case_id: verdict}. Tolerant of junk."""
    verdicts: dict[str, bool | None] = {case_id: None for case_id in case_ids}
    if not content:
        return verdicts
    for case_id, raw in _BATCH_VERDICT_RE.findall(content):
        if case_id in verdicts:
            verdicts[case_id] = _verdict_value(raw)
    try:
        data = json.loads(content)
    except (TypeError, ValueError):
        return verdicts
    if isinstance(data, dict):
        for case_id, raw in data.items():
            if case_id in verdicts:
                verdicts[case_id] = _verdict_value(str(raw) if raw is not None else None)
    return verdicts


def _build_batch_prompt(
    signals: list[Signal], trace: dict[str, Any], max_input_chars: int
) -> str:
    response = _assistant_text(
        [event for event in trace.get("events", []) if isinstance(event, dict)], trace
    )
    payload = {
        "task": (
            "You are a conservative reviewer for agent-behavior quality signals. "
            "The deterministic stage flagged these cases; confirm only when the "
            "evidence truly supports each signal."
        ),
        "final_response_excerpt": _redact(str(response))[:max_input_chars],
        "cases": [
            {
                "case_id": signal.signal_id,
                "signal": signal.to_dict(),
            }
            for signal in signals
        ],
        "question": "For every case, is the evidence enough to confirm the signal?",
        "reply": 'JSON object mapping each case_id to "confirm" | "reject" | "unknown".',
    }
    return json.dumps(payload, ensure_ascii=False)


def _build_double_check_prompt(signal: Signal, trace: dict[str, Any], max_input_chars: int) -> str:
    response = _assistant_text(
        [event for event in trace.get("events", []) if isinstance(event, dict)], trace
    )
    payload = {
        "task": (
            "Another reviewer rejected this agent-behavior signal. The deterministic "
            "stage disagrees. Be adversarial: is this rejection a true false positive, "
            "or did the first reviewer miss real evidence?"
        ),
        "final_response_excerpt": _redact(str(response))[:max_input_chars],
        "signal": signal.to_dict(),
        "reply": 'JSON object with "verdict": "confirm" | "reject" | "unknown" and a one-line "reason".',
    }
    return json.dumps(payload, ensure_ascii=False)


def _double_check_one(
    signal: Signal,
    trace: dict[str, Any],
    *,
    base_url: str,
    model: str,
    api_key: str,
    timeout: int,
    max_input_chars: int,
) -> bool | None:
    """Adversarial re-verification of a rejected signal.

    Disagreement (reject then confirm) resolves to None (unknown) rather than
    trusting either call alone.
    """
    try:
        prompt = _build_double_check_prompt(signal, trace, max_input_chars)
        content = _call_model(
            prompt,
            base_url=base_url,
            model=model,
            api_key=api_key,
            timeout=timeout,
        )
        second = _parse_verdict(content)
    except Exception:
        return None
    if second is False:
        return False
    return None  # confirm or unknown → disagreement/uncertainty → unknown


def escalate_signals(
    signals: list[Signal],
    trace: dict[str, Any],
    *,
    base_url: str,
    model: str,
    api_key: str,
    timeout: int = _DEFAULT_TIMEOUT,
    max_input_chars: int = _DEFAULT_MAX_INPUT_CHARS,
    batch: bool = True,
    double_check: bool = True,
) -> list[Signal]:
    """Confirm ambiguous signals via a cheap model; leave the rest untouched.

    Ambiguous signals are batched into a single call per trace (``batch``), and
    rejected verdicts are adversarially re-verified (``double_check``) so a
    single bad call cannot veto a real signal. Never raises: any transport or
    parse failure keeps candidates as-is with ``confirmed`` unset.
    """
    ambiguous = [signal for signal in signals if signal.ambiguous]
    if not ambiguous:
        return list(signals)

    if batch and len(ambiguous) > 1:
        verdicts: dict[str, bool | None] = {}
        try:
            prompt = _build_batch_prompt(ambiguous, trace, max_input_chars)
            content = _call_model(
                prompt,
                base_url=base_url,
                model=model,
                api_key=api_key,
                timeout=timeout,
            )
            verdicts = _parse_batch(content, [signal.signal_id for signal in ambiguous])
        except Exception:
            verdicts = {signal.signal_id: None for signal in ambiguous}
        escalated: list[Signal] = []
        for signal in signals:
            if not signal.ambiguous:
                escalated.append(signal)
                continue
            confirmed = verdicts.get(signal.signal_id)
            if double_check and confirmed is False:
                confirmed = _double_check_one(
                    signal,
                    trace,
                    base_url=base_url,
                    model=model,
                    api_key=api_key,
                    timeout=timeout,
                    max_input_chars=max_input_chars,
                )
            escalated.append(replace(signal, confirmed=confirmed, judge_model=model))
        return escalated

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
            if double_check and verdict is False:
                verdict = _double_check_one(
                    signal,
                    trace,
                    base_url=base_url,
                    model=model,
                    api_key=api_key,
                    timeout=timeout,
                    max_input_chars=max_input_chars,
                )
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
    """Read provider/model/base_url + api key from a Hermes profile.

    Resolution per provider: an explicit ``base_url`` in config.yaml wins; a
    provider without one is looked up in Hermes's own provider registry
    (``providers.get_provider_profile``) or the static catalog below, so
    providers like opencode-go, openrouter, dashscope, or any registered
    provider resolve to their real endpoint + key automatically. Keys come
    from the process env, then ``$HERMES_HOME/.env``, then ``auth.json``.
    """
    home = Path(hermes_home or environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
    model_section = _read_model_section(home)
    if not model_section:
        return None
    base_url = str(model_section.get("base_url") or "").strip()
    provider = str(model_section.get("provider") or "").strip()
    model = str(model_section.get("default") or "").strip()
    if base_url and model:
        return {"base_url": base_url, "model": model, "api_key": _auth_key(home, provider)}
    if provider:
        return _provider_config(provider, model, home, environ)
    return None


def _read_model_section(home: Path) -> dict[str, str]:
    """Parse the flat ``model:`` section of config.yaml.

    PyYAML first (present inside a Hermes install); a tiny regex parser as a
    standalone fallback so the CLI works on a bare Python without yaml.
    """
    try:
        import yaml

        raw = yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8")) or {}
        section = raw.get("model", {}) or {}
        if isinstance(section, dict):
            return {str(key): str(value) for key, value in section.items() if value is not None}
        return {}
    except ImportError:
        pass
    except Exception:
        return {}
    try:
        text = (home / "config.yaml").read_text(encoding="utf-8")
    except OSError:
        return {}
    section: dict[str, str] = {}
    in_model = False
    for line in text.splitlines():
        if re.match(r"^model\s*:", line):
            in_model = True
            continue
        if not in_model:
            continue
        if re.match(r"^\S", line):
            break  # next top-level key
        match = re.match(r"^\s+([A-Za-z0-9_]+)\s*:\s*(.*)$", line)
        if match:
            section[match.group(1)] = match.group(2).strip().strip("\"'")
    return section


def _env_file_values(home: Path) -> dict[str, str]:
    """Parse ``$HERMES_HOME/.env`` into a dict (values stay in-process)."""
    try:
        text = (home / ".env").read_text(encoding="utf-8")
    except OSError:
        return {}
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("\"'")
    return values


# Static catalog fallback for well-known OpenAI-compatible providers when the
# Hermes provider registry is not importable (standalone usage). Each entry:
# base_url, env var carrying the key, and a conservative cheap judge default.
_PROVIDER_CATALOG: dict[str, dict[str, str]] = {
    "opencode-go": {
        "base_url": "https://opencode.ai/zen/go/v1",
        "env_key": "OPENCODE_GO_API_KEY",
        "default_model": "glm-5",
    },
    "opencode-zen": {
        "base_url": "https://opencode.ai/zen/v1",
        "env_key": "OPENCODE_ZEN_API_KEY",
        "default_model": "gemini-3-flash",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "env_key": "OPENROUTER_API_KEY",
        "default_model": "deepseek/deepseek-chat",
    },
    "dashscope": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "env_key": "DASHSCOPE_API_KEY",
        "default_model": "qwen-turbo",
    },
    "hypercharm": {
        "base_url": "https://hyper.charm.land/v1",
        "env_key": "HYPERCHARM_API_KEY",
        "default_model": "deepseek-v4-flash",
    },
}


def _provider_config(
    provider: str, model: str, home: Path, environ: dict[str, str]
) -> dict[str, str] | None:
    """Resolve one provider to (base_url, model, api_key).

    Tries Hermes's live provider registry first (covers every registered
    provider: openrouter, anthropic, gemini, deepseek, nvidia, ...), then the
    static catalog. An explicit ``<PROVIDER>_BASE_URL`` env var overrides the
    endpoint. Returns None when the provider is unknown or has no key.
    """
    entry = _PROVIDER_CATALOG.get(provider)
    env_var = f"{provider.upper().replace('-', '_')}_BASE_URL"
    file_values = _env_file_values(home)

    def _value(name: str) -> str:
        return environ.get(name, "").strip() or file_values.get(name, "").strip()

    base_url = _value(env_var)
    api_key = ""
    default_model = ""

    try:
        from providers import get_provider_profile

        profile = get_provider_profile(provider)
        if profile is not None:
            base_url = base_url or str(getattr(profile, "base_url", "") or "")
            for candidate in getattr(profile, "env_vars", ()) or ():
                if _value(str(candidate)):
                    api_key = _value(str(candidate))
                    break
            default_model = str(getattr(profile, "default_aux_model", "") or "")
    except Exception:  # pragma: no cover - registry only exists inside Hermes
        pass

    if entry and not base_url:
        base_url = entry["base_url"]
    if not api_key and entry:
        api_key = _value(entry["env_key"])
    if not api_key:
        api_key = _auth_key(home, provider)
    if not base_url or not api_key:
        return None
    if not entry and not default_model:
        # Registry-only provider without a judge default: require an explicit model.
        return None
    return {
        "base_url": base_url,
        "model": model or (entry or {}).get("default_model", "") or default_model,
        "api_key": api_key,
    }


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


def _detect_env_providers(
    home: Path, environ: dict[str, str]
) -> dict[str, str] | None:
    """Last-resort: catalog providers whose API key is present.

    Key sources: the process env (Hermes loads ``~/.hermes/.env`` at startup),
    then the ``.env`` file directly for standalone CLI use. Model defaults are
    conservative cheap-judge picks.
    """
    file_values = _env_file_values(home)

    def _value(name: str) -> str:
        return environ.get(name, "").strip() or file_values.get(name, "").strip()

    for name, entry in _PROVIDER_CATALOG.items():
        key = _value(entry["env_key"])
        if not key:
            continue
        env_var = f"{name.upper().replace('-', '_')}_BASE_URL"
        base_url = _value(env_var) or entry["base_url"]
        return {
            "base_url": base_url,
            "model": entry["default_model"],
            "api_key": key,
        }
    return None


def resolve_escalation_config(
    *,
    hermes_home: str | Path | None = None,
    environ: dict[str, str] | None = None,
) -> dict[str, str] | None:
    """Resolve escalation config with zero configuration required.

    Order: explicit env vars → Hermes config.yaml (base_url, or any registered
    provider — opencode-go, openrouter, ... — resolved via the provider
    registry/catalog) → local endpoint detection (ollama keyless; CLIProxy when
    a key already exists) → catalog providers with a key in the env → None
    (deterministic-only, the graceful default).
    """
    env = environ if environ is not None else os.environ
    from_env = escalation_config_from_env(env)
    if from_env:
        return from_env
    from_hermes = _hermes_config(hermes_home, env)
    if from_hermes:
        return from_hermes
    local = _detect_local(env)
    if local:
        return local
    home = Path(hermes_home or env.get("HERMES_HOME") or (Path.home() / ".hermes"))
    return _detect_env_providers(home, env)


def escalation_source(
    *,
    hermes_home: str | Path | None = None,
    environ: dict[str, str] | None = None,
) -> tuple[str, dict[str, str] | None]:
    """Return (mode, config) where mode is env | hermes | local | env-provider | off."""
    env = environ if environ is not None else os.environ
    if escalation_config_from_env(env):
        return "env", escalation_config_from_env(env)
    if _hermes_config(hermes_home, env):
        return "hermes", _hermes_config(hermes_home, env)
    local = _detect_local(env)
    if local:
        return "local", local
    home = Path(hermes_home or env.get("HERMES_HOME") or (Path.home() / ".hermes"))
    env_provider = _detect_env_providers(home, env)
    if env_provider:
        return "env-provider", env_provider
    return "off", None