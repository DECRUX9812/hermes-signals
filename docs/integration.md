# Integration guide

## Standalone scanner

A trace is just JSON, so Signals can run in CI, a local audit script, or an
exported evaluator:

```bash
python -m hermes_signals.cli scan trace.json --output json > signals.json
```

A zero-signal result is still a successful scan. The CLI returns exit code 2
only when the input file cannot be read or is not a JSON object.

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
