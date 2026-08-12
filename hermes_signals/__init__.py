"""Local-first deterministic behavior signals for Hermes Agent."""

from .classifier import Signal, classify_trace, stable_trace_id, trace_from_conversation

try:
    from importlib.metadata import version as _pkg_version

    __version__ = _pkg_version("hermes-signals")
except Exception:  # pragma: no cover - not pip-installed (e.g. plugin sys.path load)
    __version__ = "0.5.0"  # keep in sync with pyproject.toml

__all__ = ["Signal", "classify_trace", "stable_trace_id", "trace_from_conversation"]
