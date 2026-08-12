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
import re
import urllib.request
from dataclasses import replace
from typing import Any

from hermes_signals.classifier import Signal, _redact

__all__ = ["escalate_signals", "escalation_config_from_env"]

_DEFAULT_TIMEOUT = 15
_DEFAULT_MAX_INPUT_CHARS = 2000
_VERDICT_RE = re.compile(r'"verdict"\s*:\s*"(confirm|reject|unknown)"', re.IGNORECASE)


def _build_prompt(signal: Signal, trace: dict[str, Any], max_input_chars: int) -> str:
    response = str(trace.get("final_response") or "")
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
        return {"confirm": True, "reject": False}.get(match.group(1).lower())
    try:
        data = json.loads(content)
        verdict = data.get("verdict")
        if verdict == "confirm":
            return True
        if verdict == "reject":
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
    import os

    env = environ if environ is not None else os.environ
    base_url = env.get("HERMES_SIGNALS_ESCALATION_BASE_URL", "").strip()
    model = env.get("HERMES_SIGNALS_ESCALATION_MODEL", "").strip()
    api_key = env.get("HERMES_SIGNALS_ESCALATION_API_KEY", "").strip()
    if not base_url or not model:
        return None
    return {"base_url": base_url, "model": model, "api_key": api_key}