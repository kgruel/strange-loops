# log

*A non-authoritative, human-facing narrative annotation about a CLI run.*

## The Danger

If `log` is underspecified, it eats the whole system.
If it's overspecified, it becomes useless.

So this one needs the strictest boundaries.

## What It Represents

A log event is a **narrative annotation** — a human-visible statement of fact that does not materially change the outcome of the run.

It exists to:
- Explain
- Contextualize
- Narrate
- Annotate

It does **not**:
- Decide
- Measure
- Produce
- Progress
- Persist

That distinction is the entire game.

## Why Log Exists

You might ask: "If we have input, progress, artifact, metric… why do we need log?"

Because not everything is:
- A decision
- A number
- A durable output
- A measurable advancement

Some things are just:
- Explanations
- Warnings
- Clarifications
- Context

If you don't allow some escape hatch, people will:
- Abuse metrics
- Overload artifacts
- Invent fake progress
- Bypass the system entirely

**Log is the pressure release valve.**

## Examples

```python
Event(
    kind="log",
    level="info",
    message="Using cached credentials",
    data={"source": "auth", "cache_hit": True}
)
```

Typical log messages:
- "Using cached credentials"
- "Skipping optional step X"
- "No changes detected"
- "Falling back to default config"
- "Retrying due to timeout"

These matter to humans. They often don't matter to machines. They should still be recorded as facts.

Important characteristics:
- `message` is primary
- `data` is optional context
- Nothing downstream depends on it

## The "Log Smell" Test

Before emitting a log event, ask:

> **If this log disappeared, would the run become misleading or incorrect?**

- If **yes** → it probably deserves another primitive
- If **no** → log is appropriate

| Statement | Correct Primitive |
|-----------|-------------------|
| "Processed 512 files" | `metric` |
| "Wrote backup.tar.gz" | `artifact` |
| "Are you sure?" (with response) | `input` |
| "Downloading files" | `progress` |
| "Using cached credentials" | `log` |

## Log vs Logging: The Critical Distinction

**This is NOT a logging framework.**

Log events are NOT:
- Stack traces
- Debug dumps
- Internal state
- Developer diagnostics
- Trace spans

Those belong to:
- Logging libraries
- OpenTelemetry
- Debug files
- stderr

A good rule:

> **If it helps a developer debug code, it is not a log event.**
> **If it helps a user understand behavior, it might be.**

## Why Log Must Be Intentionally Weak

Log must not be able to do these things:

- ❌ Control flow
- ❌ Define success/failure
- ❌ Encode structured results
- ❌ Represent durable outputs
- ❌ Represent metrics
- ❌ Represent progress

If people can depend on logs, they will.

So you must design log to be:
- Ignorable
- Suppressible
- Non-authoritative

## Log Levels

Levels exist only to support:
- Verbosity filtering
- Grouping
- Renderer decisions

Minimal viable set:

```
debug | info | warn | error
```

**Key rule: Log level does not affect outcome.**

An `error` log:
- Does NOT mean the run failed
- Does NOT imply exit code
- Does NOT replace `Result.status`

That separation is sacred.

## Containing Log Abuse

Left unchecked, people will:
- Put structured data in logs
- Encode state in text
- Rely on wording stability
- Break JSON output
- Break renderers

To prevent that:

### Rule 1: Logs are advisory, not contractual

- Wording may change
- Order may change
- Presence may change

### Rule 2: Logs are renderer-optional

- JSON renderer may drop them
- CI renderer may suppress them
- Quiet mode may erase them

### Rule 3: Logs never define "what happened"

Only these define what happened:
- `Result`
- `input`
- `artifact`
- `metric`

## Log and Result Interaction

Logs **can**:
- Explain why a Result is what it is

Logs **cannot**:
- Substitute for `Result.summary`
- Change `Result.status`
- Add required information

Think of logs as footnotes, not the abstract.

## Why Log Is Still Essential

Without log:
- CLIs feel robotic
- Users don't trust automation
- Silent behavior feels broken
- Errors feel unexplained

Log is how you communicate intent and reasoning. But only narratively.

## The System Guardrail

This rule must be written in stone:

> **If users can solve their problem by parsing logs, the contract has failed.**

Logs are comfort.
The contract is truth.

## Signals: Structured Observations Within Log

While narrative logs are for prose, sometimes you need **structured, machine-readable observations** that don't fit other primitives.

For these, use `log_signal`:

```python
Event.log_signal("stack_status", stack="media", healthy=True)
Event.log_signal("connection_established", host="db.local")
Event.log_signal("cache_invalidated", key="user:123")
```

Signals are stored as logs with a `"signal"` key in data. Renderers detect them via:

```python
if event.is_signal:
    # structured observation (topic: "signal:stack_status")
else:
    # narrative prose (topic: "log")
```

Use `event.topic` for filtering: signals have topic `signal:<name>`, narrative logs have topic `log`.

This creates **two lanes** within log:
1. **Narrative** — human-first prose, suppressible, non-authoritative
2. **Signal** — machine-first observations, stable identifiers, structured attributes

For full details, see [signal.md](signal.md).

**Important:** Before using signals, check if another primitive fits better:
- Durable output? → `artifact`
- Number to graph/compare? → `metric`
- Advancement? → `progress`
- Human decision? → `input`

## The Complete System

Each primitive has a unique responsibility with no overlap in authority:

| Primitive | Role |
|-----------|------|
| `input` | Decisions |
| `progress` | Advancement |
| `artifact` | Durable outputs |
| `metric` | Quantitative facts |
| `log` | Narrative context |
| `log_signal` | Structured observations (within log) |
| `Result` | Authoritative outcome |

That's why this doesn't collapse into mush.
