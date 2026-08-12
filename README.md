# Hermes Signals

> **Your agent says "done." Is it lying?**

[![Tests](https://github.com/DECRUX9812/hermes-signals/actions/workflows/ci.yml/badge.svg)](https://github.com/DECRUX9812/hermes-signals/actions/workflows/ci.yml)
[![Corpus](https://github.com/DECRUX9812/hermes-signals/actions/workflows/signals-review.yml/badge.svg)](https://github.com/DECRUX9812/hermes-signals/actions/workflows/signals-review.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![No API key](https://img.shields.io/badge/no%20API%20key-required-00C853.svg)](README.md)
[![No telemetry](https://img.shields.io/badge/no%20telemetry-ever-00C853.svg)](README.md)

**Hermes Signals is a local-first, deterministic quality layer for AI agents.** It
catches the failures agents are really bad at reporting — claiming success after
a tool failed, repeating the same broken action forever, editing files without
verifying them, leaking credentials, losing subagent results — **without a
single model call, GPU, API key, or byte of outbound telemetry.**

```text
update_record(id=42)  →  TIMEOUT
update_record(id=42)  →  TIMEOUT
final answer: "The record was successfully updated."   ← 🔴 false-success
```

A single event never contains the whole failure. The **trace** does. Signals
turns trace relationships into cheap, inspectable policies that run everywhere.

> Signals is a diagnostic layer, not an autonomous judge. A match is a useful
> review candidate — not proof that an agent failed.

## The problem is real

> *"I rotate between 18 agents daily. None of them know this dashboard exists."*
> — [My AI Agents Lie About Their Status, So I Built a Hidden Monitor](https://kaylarosemathisen.substack.com/p/my-ai-agents-lie-about-their-status),
> Kayla Mathisen, Mar 2026 ([HN](https://news.ycombinator.com/item?id=47249964))

A YC Chief of Staff running 18 agents had to build a **hidden** monitor because
agent self-reports couldn't be trusted. Most people don't get that far — they
just find out later that the "done" was a lie. Signals is that hidden monitor,
open-sourced: it inspects what the agent *actually did* (tool calls, results,
retries, verification) and reports what it *claimed*, deterministically.

This is no longer an anecdote — it's a category:

- [Ask HN: "The agent lied to you, how will you handle it?"](https://news.ycombinator.com/item?id=43512740) —
  an agent pushed a customer's phone-number update as if it were proceeding
  normally, even though the ID check had failed.
- [MIT Technology Review, Aug 2026](https://www.technologyreview.com/2026/08/03/1141009/heres-why-ai-agents-lie-and-cheat-to-reach-their-goals/) —
  "Why AI agents lie and cheat to reach their goals" treats agent deception as
  an established, named problem.
- Mistral's Leanstral launch ("open-source agent for **trustworthy** coding",
  ~780 HN points) — trust is the differentiator founders are now positioning
  against.

Most of the industry's answer is another dashboard. Signals' answer is a
**deterministic pre-flight check** that runs on the traces you already have —
no instrumentation, no model calls, no signup.

## Install (set and forget)

```bash
hermes plugins install DECRUX9812/hermes-signals --enable
hermes signals setup
```

That's it. `setup` arms monitoring, backfills your recent session history into
the first report (so it's about **your** agents, not a demo), installs a weekly
digest cron, and prints a status summary. You never touch it again:

- every Hermes turn is scanned locally after it completes — zero model calls
- a weekly digest lands on its own (numbers only, no raw content)
- label what you see and precision improves over time:
  `hermes signals feedback <trace> <signal> correct|false_positive|policy`

```bash
hermes signals demo      # prove it works in 2 seconds
hermes signals doctor    # self-check: store, corpus, escalation, cron
hermes signals report    # per-signal precision from your labels
hermes signals digest    # the weekly report, on demand
```

Remove it any time: `hermes plugins disable hermes-signals`.

![Hermes Signals — launch poster](assets/discord/hermes-signals-discord.png)

## What it catches

| Signal | Severity | Detects |
|---|---:|---|
| 🔴 `false-success` | high | Claims completion after failed tool results |
| 🟠 `retry-loop` | medium | Same tool + same args, failing, no strategy change |
| 🟠 `unverified-change` | medium | Reports a change with no test/readback/build evidence |
| 🟣 `secret-risk` | critical | Credential-like material in a trace (output redacted) |
| 🟠 `subagent-handoff-loss` | medium | Delegated work succeeded but the result was abandoned |
| 🟠 `hallucinated-evidence` | medium | Success claim cites artifacts absent from the trace |
| 🟠 `instruction-drift` | medium | Long session whose final answer left the topic |
| 🟠 `cost-runaway` | medium | Long failing grind, no successful outcome, admitted failure |

Every signal ships with compact evidence (counts and booleans — never raw
content) and a versioned behavior test. Policies intentionally prefer **false
negatives over noisy alerts**.

## How it works

```text
cheap deterministic filter → compact evidence → human review
```

1. **Stage 1 — deterministic** (always, free, instant): pattern-match the trace
   against the signal policies. No model, no network, no GPU.
2. **Stage 2 — optional judge** (only for *ambiguous* candidates): a cheap model
   confirms or rejects, batched per trace, with an adversarial double-check on
   rejects so one bad call can't veto a real signal.
3. **Human review**: feedback labels (✅ correct / ❌ false_positive / 🛠️ policy)
   drive the precision report. Model calls scale with **uncertainty**, not traffic.

The judge auto-discovers whatever your machine already has — **zero setup**:

- Hermes config provider (opencode-go, openrouter, gemini, … resolved through
  Hermes' own provider registry; keys from `.env`/`auth.json`)
- a local endpoint (Ollama keyless, CLIProxy with an existing key)
- any catalog provider with a key in `.env` (OpenRouter, DashScope, …)

Prefer local first, fall back gracefully; escalation is off by default and
never raises.

## Why not LangSmith / Langfuse / AgentOps / Phoenix?

The observability giants are **runtime instrumentation + hosted dashboards +
LLM-as-judge evals**. That's a different job: tracing what your agent does live,
at scale, in a team dashboard. Signals occupies the corner they don't:

| | Signals | LangSmith / Langfuse / AgentOps | Arize Phoenix |
|---|---|---|---|
| Detection style | **Deterministic rules** | LLM-judge evals (mostly) | LLM-judge evals (mostly) |
| Integration | **None** — reads existing traces | SDK wrapper around the LLM call | SDK / OTel instrumentation |
| Works on old sessions | **Yes — backfill** (`state.db`, OpenCode, Claude JSONL) | No — needs instrumentation first | No |
| Hosted / API key | **No — local file** | Yes | Self-hosted service |
| Cost | **$0, always** | Per-token evals / seats | Infrastructure + model evals |
| Telemetry | **Zero outbound** | Trace upload by design | Self-hosted |
| Failure-mode signals (false-success, retry-loop, …) | **Built-in, 8 signals** | Bring-your-own evaluator | Bring-your-own evaluator |

Signals is the *pre-flight check* layer: cheap, local, deterministic, and it
works on traces you already have — no SDK changes, no migration, no signup.

## Works in any harness

- **Hermes plugin** — observes completed turns via `post_llm_call`
- **CLI** — `hermes signals scan trace.json`, or standalone:
  `python -m hermes_signals.cli scan trace.json`
- **MCP server** — `scan_trace`, `scan_trace_file`, `feedback`, `precision` for
  any MCP-capable harness (OpenCode, Cursor, VS Code, Claude Desktop, …)
- **Library** — `from hermes_signals import classify_trace`

```bash
pip install 'hermes-signals[mcp]'
hermes-signals-mcp            # stdio (default)
```

Backfill reads **read-only, bounded, idempotently**:

```bash
hermes signals backfill                          # hermes + opencode + claude
hermes signals backfill --source opencode --max-sessions 50
```

## Policy packs & regression corpus

- **Packs** — local, versioned, user-tunable overrides (severity, suppress,
  `suppress_when`) as JSON/YAML, without forking code:
  `hermes signals scan trace.json --pack ~/.hermes/signals-packs/quiet.json`
- **Corpus** — a labeled regression yardstick ships with the package; every
  policy change must keep it green (`hermes signals corpus`, and CI runs it on
  every push). **12/12 traces currently pass.**

## Privacy & safety

- No network requests, no LLM calls, no outbound telemetry — ever.
- Evidence contains counts and booleans, not raw content.
- Credential-like matches are replaced with `[REDACTED_SECRET]`.
- Stable trace IDs are short SHA-256 prefixes of the local trace shape.
- The plugin is a fail-open observer: it cannot break an agent turn.

## Development

```bash
git clone https://github.com/DECRUX9812/hermes-signals.git
cd hermes-signals
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest -q && ruff check . && python -m hermes_signals.cli corpus
```

120+ tests cover policy behavior, eventual success, secret redaction, JSONL
privacy, backfill adapters, escalation resolution, and the plugin contract.
CI runs Python 3.11–3.13 plus the regression-corpus gate.

## Roadmap

- [x] Deterministic classifier (8 signals, v0.4)
- [x] Hermes plugin + CLI + MCP server
- [x] Backfill from Hermes / OpenCode / Claude stores
- [x] Two-stage escalation with batched judging + double-check
- [x] Feedback labels, precision report, weekly digest cron
- [x] Policy packs + regression corpus + CI gate
- [x] One-shot `setup` and `doctor` self-check (set-and-forget)
- [ ] Webhook/Discord reporter (disabled by default)
- [ ] More backfill sources (Cline, Aider, LangChain JSONL)
- [ ] Per-policy false-positive budget alerts in the digest

## Contributing

Start with a failing behavior test. Keep policies deterministic and
explainable. No telemetry, no hosted dependencies, no core Hermes changes. Every
new signal documents: what it detects, the evidence required, non-match
boundaries, privacy behavior, and a focused test fixture.

## Community

- **Give feedback** — label what you see: `hermes signals feedback <trace> <signal> correct|false_positive|policy`. Every label improves the precision report and the next policy version.
- **Report a false positive** — that's the most valuable bug report we can get: open a [GitHub issue](https://github.com/DECRUX9812/hermes-signals/issues/new) with the trace (secrets redacted) or drop the trace file in the [Discussions](https://github.com/DECRUX9812/hermes-signals/discussions) tab.
- **Find us where the agent people hang out** — Nous Research Discord, `#plugins-skills-and-skins` (Hermes plugin hub).
- **Share the gotcha** — the retro poster in `assets/discord/` is sized for Discord and ready to drop.

## License

MIT. See [LICENSE](LICENSE).
