# Hermes Signals

[![Tests](https://github.com/DECRUX9812/hermes-signals/actions/workflows/ci.yml/badge.svg)](https://github.com/DECRUX9812/hermes-signals/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Hermes Agent](https://img.shields.io/badge/Hermes%20Agent-plugin-8A2BE2)](https://github.com/NousResearch/hermes-agent)

**Local-first behavior quality signals for Hermes Agent.**

Hermes Signals detects a small set of high-value agent failure patterns from
existing traces:

- 🔴 **False success** — the agent claims an operation completed after tool failure.
- 🟠 **Retry loop** — the agent repeats the same failing operation without changing strategy.
- 🟠 **Unverified change** — the agent reports a file change without visible test, readback, or build evidence.
- 🟣 **Secret risk** — credential-like material appeared in a trace event; output is redacted.

It is deliberately small and boring at runtime: **pure Python, deterministic,
local-only, no GPU, no hosted service, no model call, and no outbound telemetry.**

> Signals is a diagnostic layer, not an autonomous judge. A match is a useful
> review candidate—not proof that an agent failed.

## Why this exists

Agent failures are often relationships between events rather than one bad
message. For example:

```text
update_record(...) → timeout
update_record(...) → timeout
final answer: “The record was successfully updated.”
```

A single event does not contain the whole failure. The useful unit is the
trace: tool calls, results, retries, verification, and the final claim.

Hermes Signals turns those relationships into cheap, inspectable policies that
can run across every Hermes installation. It follows a simple production
pattern:

```text
cheap deterministic filter → compact evidence → human review
```

A future version may add an optional classifier for ambiguous candidates. The
current version does not need an API key or an inference backend.

## Install as a Hermes plugin

Hermes plugins are opt-in. Install the repository and enable it:

```bash
hermes plugins install DECRUX9812/hermes-signals --enable
hermes signals demo
```

The plugin observes completed turns through Hermes' `post_llm_call` hook and
writes bounded metadata to the active profile's local store:

```text
$HERMES_HOME/signals.jsonl
```

Signals never stores raw conversation text, raw tool arguments, or raw tool
results in that report file. A classifier exception is fail-open and cannot
break the Hermes agent loop.

Disable or remove it at any time:

```bash
hermes plugins disable hermes-signals
hermes plugins remove hermes-signals
```

## Use standalone

The classifier has no Hermes runtime dependency. Clone the repo and run:

```bash
python -m hermes_signals.cli demo
python -m hermes_signals.cli demo --output json
python -m hermes_signals.cli scan examples/false-success.json
```

Or use it as a library:

```python
from hermes_signals import classify_trace

signals = classify_trace({
    "events": [
        {"type": "tool_call", "id": "1", "name": "deploy", "arguments": {}},
        {"type": "tool_result", "tool_call_id": "1", "status": "timeout"},
        {"type": "assistant", "content": "Deployment completed successfully."},
    ]
})

for signal in signals:
    print(signal.signal_id, signal.severity)
```

## Run in any harness (MCP)

Signals also ships as a **Model Context Protocol (MCP) server**, so the same
`scan_trace`, `scan_trace_file`, and `demo` tools work in any MCP-capable
harness — OpenCode, Vercel AI SDK, Claude Desktop, Cursor, VS Code, ChatGPT, or
Hermes' own native MCP client.

```bash
pip install 'hermes-signals[mcp]'
hermes-signals-mcp            # stdio (default)
hermes-signals-mcp --transport streamable-http --host 0.0.0.0 --port 8000
```

OpenCode: add an `mcp` block to `opencode.json` (see `examples/opencode.jsonc`).
Vercel AI SDK: connect with `createMCPClient` over stdio (local) or Streamable
HTTP (deployed). Full wiring is in `docs/integration.md`.

## Signal catalog

| Signal | Severity | Match policy | Why it matters |
|---|---:|---|---|
| `false-success` | high | Failed tool result(s), no successful result, success language, and no failure admission in the final response | Prevents silent lies about writes, deployments, records, and deliveries |
| `retry-loop` | medium | At least two failed calls with the same tool name and canonicalized arguments | Finds wasted turns and rate-limit amplification |
| `unverified-change` | medium | Mutation tool call plus success language, but no visible verification command or readback | Separates “edited” from “verified” |
| `secret-risk` | critical | Credential-like pattern in event text, arguments, or results | Creates a local review signal without persisting the suspected secret |

The policies intentionally prefer false negatives over noisy alerts. They are
also versioned by behavior through tests, not by freezing a catalog snapshot.

## Trace format

Signals accepts a small JSON object with an `events` list:

```json
{
  "trace_id": "optional-source-id",
  "events": [
    {
      "type": "tool_call",
      "id": "call-1",
      "name": "update_record",
      "arguments": {"id": 42}
    },
    {
      "type": "tool_result",
      "tool_call_id": "call-1",
      "status": "error",
      "content": "request timed out"
    },
    {
      "type": "assistant",
      "content": "The record was successfully updated."
    }
  ]
}
```

Supported compatibility aliases include `trace` for `events`, `tool_name` for
`name`, `args` for `arguments`, and `result_for` for `tool_call_id`.

For Hermes conversation messages, use:

```python
from hermes_signals import trace_from_conversation

trace = trace_from_conversation(messages, final_response="...")
```

## Privacy and safety

- No network requests are made by the classifier.
- No LLM calls are made by the classifier.
- Stable trace IDs are short SHA-256 prefixes of the local trace shape.
- Signal evidence contains counts and booleans, not raw content.
- Credential-like matches are replaced with `[REDACTED_SECRET]`.
- The Hermes plugin writes only bounded metadata to a local JSONL file.
- The plugin is an observer: it does not modify prompts, tool calls, or results.
- The plugin catches its own errors so diagnostics cannot interrupt an agent turn.

## Development

```bash
git clone https://github.com/DECRUX9812/hermes-signals.git
cd hermes-signals
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
pytest -q
ruff check .
python -m hermes_signals.cli demo --output json
```

The test suite covers policy behavior, eventual success, secret redaction,
JSONL privacy, CLI output, manifest shape, and the Hermes plugin registration
contract. The CI matrix runs on Python 3.11, 3.12, and 3.13.

## Roadmap

- [x] Deterministic local classifier library
- [x] Offline JSON trace scanner
- [x] Hermes `post_llm_call` plugin
- [x] Bounded local JSONL reports
- [x] Redacted secret-risk evidence
- [ ] Pluggable signal policy packs
- [ ] Optional Discord or webhook reporter, disabled by default
- [ ] Feedback labels (`correct`, `false-positive`, `policy`) for local evaluation
- [ ] Optional cheap-model review only for ambiguous candidates
- [ ] Drift and regression report across policy versions

## Relationship to Raindrop Signals

Raindrop's Signals product is a hosted production platform for building and
running task-specific classifiers at scale. Hermes Signals is not a replacement
for that infrastructure. It applies the useful architectural idea—deterministic
context selection before semantic review—to a portable, local-first Hermes
plugin that any user can inspect and run.

## Contributing

Start with a failing behavior test. Keep policies deterministic and explainable.
Do not add telemetry, secrets, hosted dependencies, or core Hermes changes.
Every new signal should document:

1. the behavior it detects;
2. the evidence required to match it;
3. important non-matches and false-positive boundaries;
4. privacy behavior; and
5. a focused test fixture.

## License

MIT. See [LICENSE](LICENSE).
