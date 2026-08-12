"""Tests for Tier 3 signals: cost-runaway, hallucinated-evidence, instruction-drift."""

from __future__ import annotations

from hermes_signals.classifier import classify_trace, trace_from_conversation


def ids(trace: dict, **kw) -> set[str]:
    return {signal.signal_id for signal in classify_trace(trace, **kw)}


def _grind_trace(n_calls: int = 12, n_fails: int = 8, eventual_success: bool = False) -> dict:
    events: list[dict] = []
    for i in range(n_calls):
        status = "error" if i < n_fails else ("success" if eventual_success else "error")
        events.append({"type": "tool_call", "id": str(i), "name": "deploy", "arguments": {"env": "prod"}})
        events.append(
            {
                "type": "tool_result",
                "tool_call_id": str(i),
                "status": status,
                "content": "ok" if status == "success" else "timeout",
            }
        )
    events.append({"type": "assistant", "content": "I was unable to complete the deployment."})
    return {"events": events}


# --- cost-runaway ------------------------------------------------------------

def test_cost_runaway_fires_on_long_failing_grind() -> None:
    signal = next(s for s in classify_trace(_grind_trace()) if s.signal_id == "cost-runaway")
    assert signal.severity == "medium"
    assert any(item.startswith("failed_results=") for item in signal.evidence)


def test_cost_runaway_ignores_short_trace() -> None:
    assert "cost-runaway" not in ids(_grind_trace(n_calls=3, n_fails=2))


def test_cost_runaway_exempts_eventual_success() -> None:
    assert "cost-runaway" not in ids(_grind_trace(eventual_success=True))


# --- hallucinated-evidence ---------------------------------------------------

def test_hallucinated_evidence_fires_on_missing_citation() -> None:
    trace = {
        "events": [
            {"type": "tool_call", "id": "1", "name": "terminal", "arguments": {"command": "pytest"}},
            {"type": "tool_result", "tool_call_id": "1", "status": "success", "content": "collected 2 items"},
            {"type": "assistant", "content": "All done — 12 tests passed in tests/test_auth.py."},
        ]
    }
    signal = next(s for s in classify_trace(trace) if s.signal_id == "hallucinated-evidence")
    assert signal.ambiguous is True


def test_hallucinated_evidence_clean_when_citation_present() -> None:
    trace = {
        "events": [
            {"type": "tool_call", "id": "1", "name": "terminal", "arguments": {"command": "pytest"}},
            {
                "type": "tool_result",
                "tool_call_id": "1",
                "status": "success",
                "content": "12 passed in tests/test_auth.py",
            },
            {"type": "assistant", "content": "All done — 12 tests passed in tests/test_auth.py."},
        ]
    }
    assert "hallucinated-evidence" not in ids(trace)


def test_hallucinated_evidence_clean_with_no_citations() -> None:
    trace = {
        "events": [
            {"type": "tool_call", "id": "1", "name": "deploy", "arguments": {}},
            {"type": "tool_result", "tool_call_id": "1", "status": "success", "content": "deployed"},
            {"type": "assistant", "content": "Deployment completed successfully."},
        ]
    }
    assert "hallucinated-evidence" not in ids(trace)


# --- instruction-drift -------------------------------------------------------

def _drift_trace(instruction: str, response: str, turns: int = 6) -> dict:
    events: list[dict] = [{"type": "user", "content": instruction}]
    for i in range(turns):
        events.append({"type": "assistant", "content": f"Working on step {i}."})
    events.append({"type": "assistant", "content": response})
    return {"events": events}


def test_instruction_drift_fires_on_diverged_response() -> None:
    trace = _drift_trace(
        "Refactor the authentication module to use OAuth2",
        "The database indexes were optimized and the backup completed.",
    )
    signal = next(s for s in classify_trace(trace) if s.signal_id == "instruction-drift")
    assert signal.ambiguous is True


def test_instruction_drift_clean_when_on_topic() -> None:
    trace = _drift_trace(
        "Refactor the authentication module to use OAuth2",
        "I migrated the authentication module to OAuth2 as requested.",
    )
    assert "instruction-drift" not in ids(trace)


def test_instruction_drift_needs_enough_turns() -> None:
    trace = _drift_trace(
        "Refactor the authentication module to use OAuth2",
        "The database indexes were optimized.",
        turns=2,
    )
    assert "instruction-drift" not in ids(trace)


# --- envelope ----------------------------------------------------------------

def test_trace_adapter_collects_instructions() -> None:
    messages = [
        {"role": "user", "content": "Refactor the auth module"},
        {"role": "assistant", "content": "On it."},
    ]
    trace = trace_from_conversation(messages, final_response="Done.")
    assert trace["instructions"] == ["Refactor the auth module"]


def test_hermes_reader_carries_user_messages_as_instructions(tmp_path) -> None:
    import sqlite3

    from hermes_signals.backfill import iter_hermes_messages

    db = tmp_path / "state.db"
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE sessions (id TEXT PRIMARY KEY, started_at REAL, message_count INTEGER);
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT,
            tool_call_id TEXT, tool_calls TEXT, tool_name TEXT, timestamp REAL
        );
        """
    )
    con.execute("INSERT INTO sessions VALUES ('s1', 1.0, 2)")
    con.executemany(
        "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
        [("s1", "user", "build the thing", 1.0), ("s1", "assistant", "done", 2.0)],
    )
    con.commit()
    con.close()

    (messages, _) = next(iter_hermes_messages(str(db)))
    assert "instructions" not in {m["role"] for m in messages}  # user text stays out of messages
    trace = trace_from_conversation(messages, final_response="done")
    assert trace["instructions"] == ["build the thing"]