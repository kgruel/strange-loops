# Python CLI Contract Layer

> **Structured, user-facing output for Python CLIs — like structured logging, but for humans *and* automation.**

This library defines a **minimal, opinionated contract** between CLI command logic and how results are rendered (Rich, JSON, plain text). It fills the gap between argument parsing (Typer / Click / Cappa) and rendering (Rich), enabling consistent UX, theming, and automation-friendly output without becoming a framework.

---

## What This Is

* A **Python-native contract layer** for CLI runs
* A small set of **semantic primitives** (`Result` + `Event`s)
* A way to describe **what happened**, not **how it looks**
* A foundation for **beautiful Rich output**, **stable JSON**, and **plain output**

Think: *structured logging, but user-facing.*

---

## What This Is NOT

* ❌ Not a CLI framework (no parsing, no commands)
* ❌ Not a TUI framework (no layout engine, no widget system)
* ❌ Not a theme system (no colors, no layout choices in the core contract)
* ❌ Not logging (this is user-facing, not diagnostics)
* ❌ Not a workflow engine or state machine

It composes with existing tools instead of replacing them. The reference renderers are optional helpers, not the contract itself.

---

## The Core Model

Every CLI run produces:

```
Run
 ├─ Event[]   # streaming facts during execution
 └─ Result    # final authoritative outcome
```

### Result (final outcome)

```
Result
 ├─ status   : ok | error
 ├─ code     : int           # exit code
 ├─ summary  : str           # short human sentence
 ├─ data     : dict          # structured command output
 └─ meta     : dict?         # duration, counts, misc
```

`Result` is the **contractual truth** of the run. Automation should rely on it.

---

### Event (streaming facts)

```
Event
 ├─ kind     : log | progress | artifact | metric | input
 ├─ level    : debug | info | warn | error (optional)
 ├─ message  : str?           # human-facing text
 ├─ data     : dict?          # structured payload
 └─ ts       : datetime?      # optional timestamp
```

Events describe *what occurred* as the run unfolds. They are renderer-agnostic and serializable.

---

## Event Kinds (Minimal & Frozen)

* **log**      – narrative context (non-authoritative)
* **progress** – work advancement as fact (%, steps)
* **artifact** – durable outputs (files, URLs, IDs)
* **metric**   – quantitative facts (duration, counts)
* **input**    – recorded user decisions (not prompts)

> New primitives are only added if a renderer cannot be implemented without them.

---

## Why This Exists

Python CLIs today:

* mix printing with logic
* bolt on JSON late
* duplicate output patterns per command
* make theming and testing painful

This contract layer lets you:

* return structured results
* emit meaningful run facts
* swap renderers freely
* add Rich UX *without* sacrificing automation

---

## Emitters (Reference Implementations)

The core contract is renderer-agnostic, but the package ships **reference emitters** to make adoption easy and to provide canonical examples.

An *Emitter* is any sink that receives `Event`s during execution and a final `Result` at completion. Rendering is just one possible emission strategy.

Included reference emitters:

* **JsonEmitter** (canonical): writes `Result` and optionally streams `Event`s as JSON / JSONL for automation and CI
* **PlainEmitter**: minimal, line-oriented output for pipes and dumb terminals

For Rich terminal output, composition utilities (`TeeEmitter`, `FileEmitter`), and more, see **ev-toolkit**.

Emitters live outside the core types so the contract stays clean, but they all consume the **same contract** and implement the same `Emitter` protocol.

---

## Design Principles

* **Minimal**: smallest useful primitive set
* **Opinionated**: Black-style, take-it-or-leave-it
* **Composable**: generic primitives, rich conventions
* **Serializable**: JSON-safe by default
* **Python-first**: great ergonomics, strong typing
* **Effectively Immutable**: Events and Results are values; payloads are treated as immutable once emitted. Recorders may enforce deep immutability/canonicalization for audit and replay.

---

## Output Streams (stdout / stderr)

An opinionated policy for well-behaved CLI output:

* **Events → stderr**: The narrative ("what's happening") goes to stderr
* **Result → stdout**: The authoritative answer goes to stdout

This enables clean Unix-style composition:

```bash
my_command | jq .          # Pipe just the result
my_command 2>/dev/null     # Suppress events, just result
my_command 2>&1 | tee log  # Capture everything
```

For JSON output specifically:
* `Result` as JSON → stdout (always)
* `Event`s as JSONL → stderr (optional, for streaming visibility)

Plain and Rich emitters write presentation to stderr; the structured result remains accessible via stdout or the return value.

---

## Quick Example

```python
from ev import Event, Result, Emitter

def check_health(emitter: Emitter) -> Result:
    emitter.emit(Event.log("Checking services..."))

    for service in ["web", "db", "cache"]:
        emitter.emit(Event.progress(f"Checking {service}", service=service))
        # ... do actual check ...
        emitter.emit(Event.artifact("health", service=service, healthy=True))

    emitter.emit(Event.metric("duration", 1.2, unit="s"))

    return Result.ok("All services healthy", data={"checked": 3})
```

## Intended Usage

* Works with Typer / Click / Cappa
* Ideal for infra tools, homelabs, automation-heavy CLIs
* Scales from one-off scripts to plugin-based tools

---

## Status

Early design / experimental.
The contract shape is intentionally small and expected to stabilize quickly through real usage.

---

## Mental Model

> **Commands return facts. Renderers decide how those facts look.**

That’s the whole idea.
