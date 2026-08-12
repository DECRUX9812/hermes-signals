# Integration guide

## Standalone scanner

A trace is just JSON, so Signals can run in CI, a local audit script, or an
exported evaluator:

```bash
python -m hermes_signals.cli scan trace.json --output json > signals.json
```

A zero-signal result is still a successful scan. The CLI returns exit code 2
only when the input file cannot be read or is not a JSON object.

### Two-stage escalation (v0.2+)

`--escalate` confirms `ambiguous` candidates with a cheap model. Configuration
is **auto-discovered** — nothing to set up. Resolution order:

1. explicit env vars (`HERMES_SIGNALS_ESCALATION_BASE_URL` / `_MODEL` /
   `_API_KEY`);
2. Hermes `config.yaml` — an explicit `base_url`, or any registered provider
   (opencode-go, openrouter, gemini, …) resolved through Hermes' provider
   registry, with keys from `.env`/`auth.json`;
3. a local endpoint (Ollama keyless; CLIProxy when a key exists);
4. any catalog provider with a key in `.env` (OpenRouter, DashScope, …).

```bash
hermes-signals scan trace.json --escalate --strategy-sensitive   # zero config
```

`hermes signals status` / `hermes signals doctor` show which mode is active
(`env | hermes | local | env-provider | off`). Only ambiguous signals are sent
(compact, redacted excerpt). Verdicts appear as `[CONFIRMED]` / `[REJECTED]` /
`[UNCONFIRMED]`. Escalation is off by default and never raises. Rejects get an
adversarial double-check so a single bad call cannot veto a real signal.

### Set-and-forget (v0.4)

```bash
hermes signals setup     # one-shot: arm + backfill + weekly digest cron + status
hermes signals doctor    # self-check: store, corpus, escalation, digest cron
```

`setup` is idempotent (re-running never duplicates the cron job) and safe on a
fresh install (a missing session DB backfills as zero, never an error).

### Backfill (v0.3+)

Classify sessions you already have — no instrumentation needed:

```bash
hermes-signals backfill                          # hermes + opencode + claude
hermes-signals backfill --source opencode --max-sessions 50
```

Reads Hermes `state.db`, OpenCode `opencode.db`, and Claude Desktop JSONL
read-only, bounded, idempotently.

### Policy packs & regression corpus (v0.4)

```bash
hermes-signals scan trace.json --pack examples/packs/quiet.json
hermes-signals packs                            # list installed packs
hermes-signals corpus                           # labeled regression yardstick
```

Packs are local JSON/YAML severity/suppress overrides; the corpus ships with
the package and CI enforces it on every push.

### Guardrails (v0.5)

Pre-execution enforcement — the one capability hosted observability cannot
offer. The plugin registers a `pre_tool_call` hook that blocks credential-like
material before a tool call executes:

```bash
HERMES_SIGNALS_GUARDRAIL_ACTION=block   # default: block | warn | off
hermes-signals guardrail --tool terminal --args '{"command": "echo token=sk-..."}'
```

`block` returns a `pre_tool_call` directive (the call never runs; the agent
sees the reason and self-corrects). `warn` records to
`$HERMES_HOME/signals-guardrail.jsonl` and proceeds. Fail-open: scan errors
never block.

### Circuit breakers (v0.6)

Session-scoped mid-run enforcement: block the agent before it wastes more.

```bash
hermes-signals breaker --calls 6 --args '{"command": "pytest -q"}'   # simulate
HERMES_SIGNALS_BREAKER_RETRY_N=5      # block Nth identical (tool, args) call (0=off)
HERMES_SIGNALS_BREAKER_MAX_CALLS=0    # hard session tool-call ceiling (0=off)
```

The 5th identical call in a session returns a `pre_tool_call` block directive
("stop repeating this call and change strategy"); the cost ceiling blocks once
a session exceeds the budget. State is process-local, per-session, bounded;
fail-open; actions follow `HERMES_SIGNALS_GUARDRAIL_ACTION`.

### Webhook alerts (v0.5, opt-in)

Set `HERMES_SIGNALS_WEBHOOK_URL` and critical signals (e.g. `secret-risk`)
POST a compact, redacted alert — counts and ids only, no raw content:

```bash
hermes-signals webhook --url https://hooks.example/alert   # test delivery
```

### Feedback & precision (v0.3)

Labels map to Discord reactions (✅ correct, ❌ false_positive, 🛠️ policy):

```bash
hermes-signals feedback <trace-id> <signal-id> correct --source discord
hermes-signals report
```

Feedback appends bounded records to `$HERMES_HOME/signals-feedback.jsonl`
(never sent anywhere); `report` aggregates per-signal precision from
`signals.jsonl` + feedback. Both are available as MCP tools (`feedback`,
`precision`).

## Hermes plugin

The root `__init__.py` is the Hermes adapter. Hermes loads it, calls
`register(ctx)`, and receives:

- one `post_llm_call` observer;
- one `hermes signals` command with `demo` and `scan` subcommands.

The observer receives Hermes' completed-turn payload:

```python
{
    "session_id": "...",
    "turn_id": "...",
    "assistant_response": "...",
    "conversation_history": [...],
    "model": "...",
    "platform": "...",
}
```

Only `conversation_history`, `assistant_response`, `session_id`, and `platform`
are needed. The classifier adapts OpenAI-shaped messages into its small trace
envelope and writes bounded results to `$HERMES_HOME/signals.jsonl`.

## Offline evaluation

For a local sample or regression corpus:

```python
import json
from pathlib import Path

from hermes_signals import classify_trace

for path in Path("traces").glob("*.json"):
    trace = json.loads(path.read_text())
    signals = classify_trace(trace)
    print(path.name, [signal.signal_id for signal in signals])
```

Keep evaluation corpora local if they contain user data. Do not commit raw
transcripts or credentials to this repository.

## Run in any harness (Model Context Protocol)

Signals ships an **MCP server** so the same three tools are available to any
harness that speaks the Model Context Protocol — Hermes Agent, OpenCode, Vercel
AI SDK, Claude Desktop, Cursor, VS Code, ChatGPT, and others.

Install the optional dependency once:

```bash
pip install 'hermes-signals[mcp]'
# or with uv:  uv tool install 'hermes-signals[mcp]'
```

Run it over **stdio** (the default, for local tools):

```bash
hermes-signals-mcp
```

The server exposes:

| Tool | Purpose |
|---|---|
| `scan_trace` | Classify a JSON trace envelope (string) and return signals |
| `scan_trace_file` | Classify a trace JSON file on disk |
| `demo` | Run the built-in false-success example |

All responses are deterministic, bounded, and redacted: the classifier never
returns raw conversation text or suspected secrets.

### OpenCode

OpenCode loads MCP servers from `opencode.json` / `opencode.jsonc`. Point the
`mcp` block at the server command (see `examples/opencode.jsonc`):

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "hermes-signals": {
      "type": "local",
      "command": ["hermes-signals-mcp"],
      "enabled": true
    }
  }
}
```

OpenCode automatically exposes the `scan_trace`, `scan_trace_file`, and `demo`
tools to the model alongside its built-ins. For a per-project install, drop the
same block into `.opencode/` config. (OpenCode also supports native JS/TS hook
plugins via `tool.execute.after`; the MCP route is the recommended, no-code
path.)

### Vercel AI SDK

Vercel's AI SDK connects to any MCP server through `createMCPClient`. For a
local server use **stdio**; for a deployed instance use **Streamable HTTP**:

```ts
import { createMCPClient } from "@ai-sdk/mcp";
import { generateText } from "ai";

const mcp = createMCPClient({
  transport: { type: "stdio", command: "hermes-signals-mcp" },
});

const { text } = await generateText({
  model: yourModel,
  tools: await mcp.tools(),
  prompt: "scan this agent trace and report any quality signals:\n" + traceJson,
});

await mcp.close();
```

For a remote deployment use Streamable HTTP (`transport: { type: "http",
url: "https://your-host/mcp" }`). See the
[AI SDK MCP docs](https://ai-sdk.dev/docs/ai-sdk-core/mcp-tools).

### Other clients

Any MCP-capable client can connect over stdio: `uvx hermes-signals[mcp]` (or
`hermes-signals-mcp`) launches a local server that Claude Desktop, Cursor, VS
Code, and ChatGPT can be pointed at. No network, model, or GPU is used at any
step.

## Future Discord reporting

A Discord reporter can be built as a separate optional integration, but it
should remain off by default. A safe design would:

1. read only the bounded JSONL signal records;
2. send high-severity matches only after explicit opt-in;
3. omit trace contents and suspected secrets;
4. include a local trace ID for investigation; and
5. accept reactions as labels without treating them as truth automatically.

The core plugin intentionally does not send messages or add a Discord
credential requirement.
