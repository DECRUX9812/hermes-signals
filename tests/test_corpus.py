"""Tests for the labeled regression corpus."""

from __future__ import annotations

import json

from hermes_signals.corpus import corpus_summary, load_labels, run_corpus


def _write_corpus(tmp_path) -> None:
    (tmp_path / "good.json").write_text(
        json.dumps(
            {
                "events": [
                    {"type": "tool_call", "id": "1", "name": "deploy", "arguments": {}},
                    {"type": "tool_result", "tool_call_id": "1", "status": "ok", "content": "done"},
                    {"type": "assistant", "content": "Deployment completed successfully."},
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "bad.json").write_text(
        json.dumps(
            {
                "events": [
                    {"type": "tool_call", "id": "1", "name": "update_record", "arguments": {"id": 1}},
                    {"type": "tool_result", "tool_call_id": "1", "status": "error", "content": "timeout"},
                    {"type": "assistant", "content": "The record was successfully updated."},
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "labels.json").write_text(
        json.dumps({"good": [], "bad": ["false-success"]}), encoding="utf-8"
    )


def test_run_corpus_reports_pass_and_fail(tmp_path) -> None:
    _write_corpus(tmp_path)
    results = run_corpus(tmp_path)
    by_name = {result.name: result for result in results}
    assert by_name["good"].passed is True
    assert by_name["bad"].passed is True
    summary = corpus_summary(results)
    assert summary["total"] == 2
    assert summary["passed"] == 2
    assert summary["failed"] == 0


def test_run_corpus_catches_regression(tmp_path) -> None:
    _write_corpus(tmp_path)
    # Wrong label: good trace now expected to flag false-success → must FAIL.
    labels = json.loads((tmp_path / "labels.json").read_text(encoding="utf-8"))
    labels["good"] = ["false-success"]
    (tmp_path / "labels.json").write_text(json.dumps(labels), encoding="utf-8")
    results = run_corpus(tmp_path)
    summary = corpus_summary(results)
    assert summary["failed"] == 1
    assert summary["failures"][0]["name"] == "good"


def test_load_labels_requires_object(tmp_path) -> None:
    (tmp_path / "labels.json").write_text("[1,2]", encoding="utf-8")
    try:
        load_labels(tmp_path)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for non-object labels.json")


def test_shipped_corpus_passes() -> None:
    """The regression corpus shipped with the package must be green."""
    results = run_corpus()
    assert results, "corpus should contain at least one trace"
    summary = corpus_summary(results)
    assert summary["failed"] == 0, summary["failures"]