# Why ev?

> Commands return verdicts. Events tell the story. Renderers decide how it looks.

## The Problem

Every Python CLI eventually faces the same questions:

**"How do I make this work in CI?"**
```python
# Your beautiful Rich output breaks in GitHub Actions
# So you add --json, but now you have two code paths
# And they drift apart over time
```

**"How do I know if it actually worked?"**
```python
# Exit code 0... but did it actually deploy?
# The output says "Done" but the logs show warnings
# You're parsing stdout with grep to check success
```

**"How do I test this without mocking print()?"**
```python
# Your domain logic is tangled with Rich imports
# Tests either mock everything or test nothing
# Refactoring output breaks unrelated tests
```

## The Root Cause

Most CLIs conflate three different things:

| Concern | What it answers | Who cares |
|---------|-----------------|-----------|
| **Verdict** | Did it work? What's the answer? | Automation, scripts, CI |
| **Telemetry** | What happened along the way? | Humans watching, dashboards |
| **Presentation** | How should it look? | The specific terminal/context |

Traditional approaches mix these:
- `print()` is presentation pretending to be verdict
- `logging` is telemetry pretending to be presentation
- Exit codes are verdicts with no structured data

## The ev Model

ev separates these concerns with a simple contract:

```
Run
 ├── Event[]   # streaming telemetry during execution
 └── Result    # authoritative final verdict
```

**Result** is the contractual truth:
```python
Result.ok("Deployed 3 services", data={"services": ["web", "api", "db"]})
Result.error("Connection failed", code=1, data={"host": "prod-db"})
```

**Events** are the narrative:
```python
Event.log("Connecting to database...")
Event.progress("Deploying", current=2, total=3)
Event.log_signal("service.deployed", service="web", duration=1.2)
```

**The key insight:**

> Automation must be able to ignore all Events entirely and still make correct decisions based on Result alone.

Events are for humans. Result is for machines. They're different things.

## What This Enables

**Same code, multiple outputs:**
```python
def deploy(emitter: Emitter) -> Result:
    emitter.emit(Event.log("Starting deployment..."))
    # ... do work ...
    return Result.ok("Deployed", data={"count": 3})

# Rich terminal UI
with RichEmitter() as e:
    result = deploy(e)

# JSON for automation
with JsonEmitter() as e:
    result = deploy(e)

# Plain text for pipes
with PlainEmitter() as e:
    result = deploy(e)

# All three at once
with TeeEmitter(rich, json, plain) as e:
    result = deploy(e)
```

**Testable without mocking output:**
```python
def test_deploy_returns_service_count():
    emitter = ListEmitter()
    result = deploy(emitter)

    assert result.is_ok
    assert result.data["count"] == 3
    # No mocking Rich, no capturing stdout
```

**CI that actually knows what happened:**
```bash
# result.json has structured data, not parsed strings
deploy --json | jq -e '.status == "ok"'
deploy --json | jq '.data.services[]'
```

## The Contract

**Result** (final verdict):
- `status`: ok | error
- `code`: exit code (0 for ok, non-zero for error)
- `summary`: human-readable sentence
- `data`: structured payload for automation
- `meta`: timing, counts, metadata

**Event** (streaming telemetry):
- `kind`: log | progress | artifact | metric | input
- `level`: debug | info | warn | error
- `message`: human-facing text
- `data`: structured payload

**Emitter** (output sink):
- `emit(event)`: receive streaming events
- `finish(result)`: receive final verdict

That's the whole contract. ~500 lines of code. Zero dependencies.

## What ev Is NOT

- Not a CLI framework (no argument parsing)
- Not a renderer (no Rich, no colors)
- Not logging (Events are user telemetry, not diagnostics)
- Not a workflow engine (describes output, doesn't control execution)

ev composes with your existing tools:
- Click/Typer/Cappa for parsing
- Rich for rendering
- structlog for internal logging (separate from ev Events)

## When to Use ev

**Good fit:**
- Infrastructure tools (deploy, sync, check)
- Automation-heavy CLIs
- Tools that need both human and machine output
- Anything where "did it work?" needs a real answer

**Overkill:**
- One-off scripts with only human users
- Tools where exit code 0/1 is sufficient
- Pure TUI applications (ev is for CLIs, not apps)

## Getting Started

```python
from ev import Event, Result, Emitter
from ev.emitters import PlainEmitter

def my_command(emitter: Emitter) -> Result:
    emitter.emit(Event.log("Starting..."))

    for i, item in enumerate(items):
        emitter.emit(Event.progress(f"Processing {item}", current=i, total=len(items)))
        process(item)

    return Result.ok(f"Processed {len(items)} items", data={"count": len(items)})

if __name__ == "__main__":
    with PlainEmitter() as emitter:
        result = my_command(emitter)
        emitter.finish(result)
    raise SystemExit(result.code)
```

For richer functionality (multiple outputs, verbosity filtering, Rich UI), see **ev-toolkit**.

## The Mental Model

> Commands return verdicts. Events tell the story. Renderers decide how it looks.

Result is truth. Events are telemetry. That's the whole idea.
