"""Labeled regression corpus: the yardstick every policy change must pass.

Each trace file in ``corpus/`` has an expected signal set in ``labels.json``.
``hermes-signals corpus`` classifies every file deterministically and reports
pass/fail, so a policy edit that fixes one signal but breaks another is caught
before it ships.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from hermes_signals.classifier import classify_trace

__all__ = ["CorpusResult", "load_labels", "run_corpus"]


class CorpusResult:
    """One corpus entry verdict."""

    __slots__ = ("name", "expected", "actual", "passed")

    def __init__(self, name: str, expected: set[str], actual: set[str]) -> None:
        self.name = name
        self.expected = expected
        self.actual = actual
        self.passed = expected == actual


def _default_corpus_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "corpus"


def load_labels(corpus_dir: Path) -> dict[str, set[str]]:
    labels_path = corpus_dir / "labels.json"
    raw = json.loads(labels_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("labels.json must be a JSON object mapping trace name -> signal ids")
    return {str(name): set(str(signal) for signal in ids) for name, ids in raw.items()}


def run_corpus(
    corpus_dir: str | Path | None = None,
    *,
    classifier: Callable[[dict[str, Any]], list[Any]] = classify_trace,
) -> list[CorpusResult]:
    """Classify every corpus trace and compare against its labels."""
    directory = Path(corpus_dir or _default_corpus_dir())
    labels = load_labels(directory)
    results: list[CorpusResult] = []
    for trace_file in sorted(directory.glob("*.json")):
        if trace_file.name == "labels.json":
            continue
        name = trace_file.stem
        trace = json.loads(trace_file.read_text(encoding="utf-8"))
        actual = {signal.signal_id for signal in classifier(trace)}
        expected = labels.get(name, set())
        results.append(CorpusResult(name, expected, actual))
    return results


def corpus_summary(results: list[CorpusResult]) -> dict[str, Any]:
    return {
        "total": len(results),
        "passed": sum(1 for result in results if result.passed),
        "failed": sum(1 for result in results if not result.passed),
        "failures": [
            {
                "name": result.name,
                "expected": sorted(result.expected),
                "actual": sorted(result.actual),
            }
            for result in results
            if not result.passed
        ],
    }