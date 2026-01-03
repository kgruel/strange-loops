# ev: CLI Event Contract

## The Problem

CLI applications lack a standard **ViewModel layer** between domain logic and rendering.

We have:
- **Parsers** (Click, Typer, Cappa, argparse)
- **Renderers** (Rich, Textual, plain print)

We don't have:
- A shared semantic contract describing **what happened**

This leads to:
- Duplication (each output mode reimplements verbosity logic)
- Tight coupling (domain code imports Rich directly)
- Untestable presentation (mocking renderers, not verifying facts)
- Inconsistent UX (each command invents its own patterns)

## The Solution

A thin contract layer that describes CLI behavior semantically:

```
Domain Logic
  └─ emits facts
        ↓
ev (Contract Layer)
  ├─ Event stream (what's happening)
  └─ Result (what happened)
        ↓
Renderers
  ├─ Rich (styled, live updates)
  ├─ JSON (machine-readable)
  ├─ Plain (ASCII, CI-friendly)
  └─ Future (TUI, Web, audit log)
```

## Core Insight

**Events are facts, not instructions.**

```python
# This is a fact:
Event.progress("Checking stack", stack="media", healthy=True)

# This is an instruction (NOT what ev does):
print_green_checkmark("media is healthy")
```

The renderer decides how to present facts. The domain just reports them.

## What ev Provides

### Event (streaming)

Facts emitted during execution. Use factory methods:

```python
Event.log("Connecting to server...")
Event.log_signal("stack_status", stack="media", healthy=True)  # structured observation
Event.progress("Syncing", step=2, of=5)
Event.artifact("file", "Config saved", path="/tmp/config.json")  # type required
Event.metric("duration", 2.3, unit="s")
Event.input("Continue?", response="yes")
```

Every event gets a timestamp (`ts`) automatically at creation. See [factories.md](factories.md) for details on factory methods vs raw constructors.

### Result (final)

The outcome when execution completes. Use factory methods:

```python
Result.ok("3/3 healthy", data={"stacks": [...]}, meta={"duration": 2.3})
Result.error("Connection failed", data={"host": "media"})
```

**Invariants:** `ok` requires `code=0`, `error` requires `code != 0`.

### Event Kinds (frozen)

| Kind | Meaning | Details |
|------|---------|---------|
| `log` | Human-visible message | [log.md](log.md) |
| `progress` | Progress as fact (%, step, phase) | [progress.md](progress.md) |
| `artifact` | Something produced (file, URL) | [artifact.md](artifact.md) |
| `metric` | Numeric fact (duration, count) | [metric.md](metric.md) |
| `input` | Input interaction occurred | [input.md](input.md) |

These are frozen. New kinds require proving a renderer cannot work without them.

### Signals (structured observations)

For machine-readable observations that don't fit other primitives, use `log_signal`:

```python
Event.log_signal("stack_status", stack="media", healthy=True)
```

Signals are a convention within the `log` kind, not a new primitive. See [signal.md](signal.md).

### Result (final verdict)

The authoritative outcome when execution completes. See [result.md](result.md) for full details.

## What ev Does NOT Provide

- **Parsing** - Use Click, Typer, Cappa
- **Rendering** - Build your own, or use a companion library
- **Themes** - Renderer concern
- **Logging** - Events are user facts, not diagnostics
- **Workflow** - ev describes, doesn't execute

## Design Philosophy

### Black-Style Opinionation

ev is intentionally minimal and frozen. Like Black for formatting:
- Few options
- Strong opinions
- Stability over flexibility

### Serializable by Default

Events and Results are JSON-serializable. This enables:
- Machine-readable output
- Audit logging
- Test assertions on data
- Replay and debugging