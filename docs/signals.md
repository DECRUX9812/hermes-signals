# Signals policy guide

This guide explains what each built-in policy means in practical Hermes work.
It is intentionally written for operators and contributors, not just code
readers.

## 1. False success

### Example

```text
Tool: update_record(id=42)
Result: timeout
Assistant: “The record was successfully updated.”
```

### Match conditions

Signals matches when all of these are true:

1. at least one tool result is clearly failed;
2. no tool result in the trace is successful;
3. the final answer uses completion language; and
4. the final answer does not admit the failure.

### Non-match conditions

These should not alert:

- a failed first attempt followed by a successful retry;
- an answer that clearly says the operation failed;
- a successful operation whose final answer says it completed.

### Why it is high severity

False success can cause a user to trust a record, deployment, payment, file,
or notification that never happened. It is the strongest first signal because
the evidence is usually concrete and cross-surface.

## 2. Retry loop

### Example

```text
patch(app.py) → timeout
patch(app.py) → timeout
patch(app.py) → timeout
```

Signals canonicalizes arguments before comparing them. It only counts repeated
attempts when they are associated with failure. A changed path, changed
arguments, or a successful result is not automatically a loop.

Two refinements keep the signal honest:

- **Eventual success exempts.** If any attempt for the same tool name
  ultimately succeeded, repeated failures are treated as persistence, not a
  stuck loop — the rd-signal-2 "eventual-success exempt" interpretation.
- **Strategy-sensitive mode (opt-in).** With `strategy_sensitive=True` (or
  `--strategy-sensitive` on the CLI), the signal also fires when only the
  argument *values* changed while the tool and argument *shape* stayed the
  same — the "arguments changed slightly but the strategy did not" case.
  These matches are marked `ambiguous` and become escalation candidates.

This signal is a review candidate, not proof of a bug. Retries can be correct
for transient network failures. A future policy pack can add exemptions for
known retry-safe operations and rate-limit backoff.

## 3. Unverified change

### Example

```text
Tool: patch(app.py)
Result: patched
Assistant: “The fix is complete.”
```

The signal asks whether the trace shows a mutation and then visible evidence of
verification, such as a test, build, lint, readback, `git diff`, or file stat.
It does not claim that a change is wrong; it identifies “changed but not
verified” as a quality boundary.

This policy intentionally uses a small tool-name and verification vocabulary.
Projects can add their own policy pack later rather than making the default
heuristic silently broader.

## 4. Secret risk

### Example

```text
Tool arguments: curl -H 'Authorization: Bearer ...'
```

The classifier checks both event text and structured arguments. It reports a
count of secret-bearing events, never the matched value. The built-in patterns
cover common GitHub, OpenAI-style, AWS, Slack, and generic key/token forms.

Treat this as an audit signal, not an automatic revocation system. Test keys,
redacted examples, and prose can still produce false positives. For that
reason, the Hermes plugin records it locally but does not send Discord alerts
by default.

## 5. Subagent handoff loss

### Example

```text
Tool: delegate_task(goal="fix the login bug")
Result: success — "subagent completed the fix and tests pass"
Assistant: "The subagent finished the fix, but I couldn't verify it in time."
```

### Match conditions

Signals matches when all of these are true:

1. a subagent-family tool (`delegate_task`, `subagent`, `codex`, ...) is called;
2. its result is successful (the delegated work actually completed); and
3. the final response uses abandonment language ("couldn't", "gave up",
   "unable to", ...) about the task the subagent completed.

### Non-match conditions

These should not alert:

- the subagent itself failed (no completed work to lose);
- the final response acknowledges the subagent's completion;
- the response abandons only a *separate* subtask the subagent never did.

When the response mixes completion and abandonment language (ambiguous), the
signal is marked `ambiguous` and becomes a two-stage escalation candidate.
This exact case — "subagent finished, I couldn't verify" — was rejected by a
live Gemini judge during v0.2 testing: the agent acknowledged the handoff, so
the honest caveat is not handoff loss. Escalation is how that judgment gets
made locally without shipping a broader heuristic.

## 6. Two-stage escalation (ambiguous candidates)

The deterministic stage is free and always runs. A tiny set of signals is
marked `ambiguous` because the evidence genuinely cuts both ways:

- strategy-sensitive retry loops (same shape, different values);
- subagent handoff loss with mixed completion/abandonment language.

When escalation is enabled, only those candidates are sent to a cheap model
with a compact, redacted excerpt — "model calls should scale with uncertainty,
not traffic". The verdict is attached as `confirmed: true | false | null`.
Unambiguous signals never touch the model. Escalation is off by default and
never raises: a transport failure leaves the candidate unconfirmed, exactly as
if escalation were disabled.

## Building a new signal

A good signal has:

- a precise behavioral sentence;
- deterministic preconditions that avoid calling a model on most traces;
- compact evidence safe to store and display;
- explicit non-match examples;
- a focused test fixture; and
- a clear severity rationale.

Prefer a new policy module or policy-pack interface over adding a broad regex
to an existing signal. The goal is an inspectable quality layer, not a growing
black box.
