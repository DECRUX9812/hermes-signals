"""Local-first deterministic behavior signals for Hermes Agent."""

from .classifier import Signal, classify_trace, stable_trace_id, trace_from_conversation

__version__ = "0.3.0"

__all__ = ["Signal", "classify_trace", "stable_trace_id", "trace_from_conversation"]
