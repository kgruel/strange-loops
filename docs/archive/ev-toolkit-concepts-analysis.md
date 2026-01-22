# EV-Toolkit: Conceptual Analysis

## Executive Summary

**ev-toolkit** is a utilities library that implements the "composition layer" on top of **ev**, a minimal, stable CLI event contract. The toolkit's philosophy is to provide copy-paste-friendly building blocks that solve common problems without becoming a heavyweight framework. It bridges the gap between ev's frozen contract and real-world CLI development patterns.

---

## Core Philosophy & Design Principles

### The Two-Package Model

The ev ecosystem is deliberately split:

- **ev** (frozen, minimal): Defines the Event/Result/Emitter contract—the contract itself is the API
- **ev-toolkit** (evolving, practical): Provides convenience utilities, composition patterns, and integrations

This separation enables:
- **ev** to remain stable indefinitely (library authors depend on it)
- **ev-toolkit** to evolve with real-world patterns (application developers use it)

### Explicit Design Tenets

From the codebase:

1. **Composability over everything**: Utilities wrap naturally, enabling patterns like:
   ```python
   emitter = TimingEmitter(
       FilterEmitter(
           TeeEmitter(json_emitter, rich_emitter),
           lambda e: e.level != "debug"
       )
   )
   ```

2. **Copy-paste friendly**: Each utility is self-contained and simple enough to copy. No utility should force a dependency if you only need it once.

3. **Self-contained modules**: Every utility is designed to exist in isolation. You can read a single file and understand the complete behavior.

4. **Source as documentation**: The philosophy rejects over-abstraction. Code is expected to be readable enough to serve as the primary documentation.

5. **Simple by default, complex when justified**: The toolkit provides the 80% case with convenience functions (`get_emitter()`, `signal()`, `tee()`) while allowing deeper composition for advanced use cases.

---

## Mental Models & Conceptual Layers

### The Layered Emitter Architecture

ev-toolkit presents emitters as composable wrappers organized in logical layers:

#### Layer 1: Output Format Emitters (from ev core)
- **PlainEmitter**: ASCII-safe, no colors/control codes
- **JsonEmitter**: Machine-readable JSONL
- **RichEmitter**: Terminal styling with colors and formatting

#### Layer 2: Composition Wrappers (ev-toolkit)
- **TeeEmitter**: Broadcast to multiple emitters (the "splitter")
- **FilterEmitter**: Conditional event filtering by predicate
- **TimingEmitter**: Auto-track duration metadata
- **CountingEmitter**: Aggregate statistics during operation
- **QuietEmitter**: Suppress info/debug, keep only errors/warnings
- **VerbosityEmitter**: Filter based on verbosity level
- **RecordingEmitter**: Capture events for testing/inspection
- **FileEmitter**: Write events as JSONL for debugging or LLM consumption

#### Layer 3: Mode Detection & Convenience (ev-toolkit)
- **get_emitter()**: "Just make it work" function that auto-detects appropriate emitter
- **signal()**: Reduce boilerplate for emitting same signal type repeatedly
- **tee()**: Shorthand for TeeEmitter

The layering encodes a principle: **output format is separate from behavior**. You can independently choose what format to emit and how to process events.

### The Events-as-Data Philosophy

Unlike print-based CLIs, ev-toolkit treats all communication as structured data:

- **Events**: Semantic messages that flow to the emitter (not strings)
- **Result**: The final outcome with structured data (not exit codes)
- **Signals**: Domain-specific events carrying typed data

Key insight: **Events are what can be consumed by different backends**. A Rich emitter renders them prettily; a JSON emitter serializes them; a FileEmitter writes them for audit. The same events work everywhere.

### Output Mode Detection: Policy, Not Magic

The toolkit encodes shared CLI policy in `OutputMode` and `detect_mode()`:

```
Priority: --json > --plain > (non-TTY defaults to PLAIN) > NO_COLOR > RICH
```

This isn't magic—it's an explicit policy that CLI tools should follow. The enum and detection functions codify this as a convention, preventing each tool from reimplementing the same decision tree.

---

## Key Conceptual Capabilities

### 1. Runtime Harness: Three-Line Script Pattern

The toolkit provides a "3-line script pattern" via `run()` that wires:

```python
def operation(emitter, args) -> Result:
    # Your business logic
    return Result.ok("done")

if __name__ == "__main__":
    raise SystemExit(run(operation))
```

This pattern automatically provides:
- **Flag wiring**: `--json`, `--plain`, `-q`, `-v`, `--record` for free
- **Proper arg parsing**: argparse with `--help`
- **Exception handling**: Built-in, structured
- **Output mode**: Auto-detected, respects environment

The mental model: **Scripts are operations that return Results, not processes that call sys.exit()**. This makes them testable, composable, and scriptable.

### 2. Composition: The Wrapper Pattern

Each wrapper follows the same composition pattern:

```python
class {X}Emitter:
    def __init__(self, inner: Emitter):
        self._inner = inner

    def emit(self, event: Event) -> None:
        # Possibly modify/filter event
        self._inner.emit(event)

    def finish(self, result: Result) -> None:
        # Possibly modify/wrap result
        self._inner.finish(result)
```

This enables arbitrary nesting. More importantly, it establishes a **clear interface contract**—if you understand one wrapper, you understand all of them.

### 3. Event Collection & Aggregation: Streaming Processing

The toolkit provides a **layered collection API** for post-hoc analysis:

#### Level 1: Functional utilities
```python
collector = SignalCollector()
for event in events:
    collector.collect(event)

status_events = collector.signals("status.stack")
by_context = collector.by_context()
```

#### Level 2: Collector base class with query API
```python
collector = ContainerCollector()
# Access collected signals and build aggregates
```

#### Level 3: Streaming with `handle()` method
```python
class StackAggregator(Collector):
    def handle(self, event):
        self.collect(event)
        if self._stack_complete(event):
            return Context(kind="status", ...)  # Signal: render now
        return None  # Don't render yet
```

The key insight: **Collectors enable rendering-on-demand**. Instead of buffering all events then rendering, you can process events as they arrive and decide what to render based on complete information.

### 4. Backend-Neutral Rendering: Semantic IR

The **present** submodule provides semantic IR (intermediate representation) for terminal output:

- **Role-based semantics**: "source", "level", "message", "timestamp", "separator"
- **Hints over prescriptions**: Segments carry presentation suggestions, not colors
- **Backend independence**: Different backends (Rich, plain text, web) consume the same IR

Example:
```python
# Semantic IR
line = Line(segments=(
    Segment(role="icon", text="✓", hint="green"),
    Segment(role="content", text=" 3/3 healthy"),
))

# Plain text rendering
print(line.plain())  # "✓ 3/3 healthy"

# Rich rendering (in app)
text = Text()
for seg in line.segments:
    style = theme.get(seg.role) or seg.hint
    text.append(seg.text, style=style)
```

This design separates **what to show** (IR) from **how to show it** (backend rendering).

### 5. Resource Resolution with Helpful Errors

The `NotFoundError` and `Resolver` pattern encodes a UX principle:

```python
class NotFoundError(CLIError):
    @property
    def message(self) -> str:
        return f"{self.resource_kind.capitalize()} not found: {self.name!r}"

    @property
    def suggestion(self) -> str:
        if not self.available:
            return f"No {self.resource_kind}s available."
        return f"Available {self.resource_kind}s: {', '.join(self.available)}"
```

The pattern: **When something isn't found, the error should always suggest alternatives**. This is codified as a protocol and error type so apps inherit this behavior.

---

## Use Cases & Problem Domains

### Problem 1: "My print-based script is growing—how do I add proper output modes?"

**Solution**: The print-to-ev migration pattern shows a concrete transformation:

```python
# Before
print(f"[CREATE] {name}")
print(f"Summary: {created} created, {updated} updated")

# After
emit_sync(action="CREATE", name=name, id=monitor_id)
return Result.ok(
    f"{created} created, {updated} updated",
    data={"created": created, "updated": updated, "skipped": skipped}
)
```

This gains:
- Testability (no mocking print/exit)
- Machine-readability (`--json` flag)
- Audit trails (`--record` flag)
- Proper error handling (Result instead of sys.exit)

### Problem 2: "I need to emit many signals of the same type without repetitive code"

**Solution**: The `signal()` helper reduces boilerplate:

```python
# Instead of writing this 10 times:
emitter.emit(Event.log_signal("monitor_synced",
    message=f"[{action}] {name}",
    action=action, name=name, id=id, ...))

# Write once:
emit_sync = signal(emitter, "monitor_synced", "[{action}] {name}")

# Then:
emit_sync(action="CREATE", name=name, id=monitor_id)
emit_sync(action="UPDATE", name=name, id=monitor_id, differences=...)
```

The mental model: **Signal emission is a repetitive pattern; codify it**.

### Problem 3: "I need output for humans (Rich), for automation (JSON), and to record for LLM review"

**Solution**: Compose emitters:

```python
emitter = TeeEmitter(
    RichEmitter(),           # Human-readable stderr
    JsonEmitter(),           # Machine-readable stdout
    FileEmitter("run.jsonl") # Record for review
)
```

Each event flows to all three destinations simultaneously.

### Problem 4: "How do I aggregate events as they arrive and decide when to render?"

**Solution**: Collectors with `handle()`:

```python
class StackAggregator(Collector):
    def handle(self, event):
        self.collect(event)
        if self._complete():
            return Context(kind="status", ...)  # Render now
        return None  # Wait for more

aggregator = StackAggregator()
for event in events:
    ctx = aggregator.handle(event)
    if ctx:
        renderer.render(ctx)
```

This enables **streaming aggregation**—buffer just enough to make sense, then render.

---

## Relationship to ev Core

### What ev-toolkit Adds

| Aspect | ev (core, frozen) | ev-toolkit (utilities, evolving) |
|--------|-------------------|----------------------------------|
| **Contract** | Event, Result, Emitter protocol | How to use them effectively |
| **Output formats** | PlainEmitter, JsonEmitter | RichEmitter, FileEmitter |
| **Composition** | None | TeeEmitter, FilterEmitter, etc. |
| **Convenience** | None | get_emitter(), signal(), tee() |
| **Mode detection** | None | OutputMode, detect_mode() |
| **Collection** | None | Collector, SignalCollector, etc. |
| **Rendering** | None | present submodule (semantic IR) |
| **Runtime wiring** | None | run(), add_standard_args() |

### Learning Progression

1. **Understand ev**: Event, Result, Emitter protocol—the contract
2. **Use ev-toolkit basics**: get_emitter(), signal(), composition
3. **Use ev-toolkit advanced**: Collectors, present module, aggregation
4. **Write custom emitters/collectors**: Implement protocols directly

---

## Design Patterns & Principles Encoded

### 1. Protocol Over Inheritance

ev-toolkit uses Protocols extensively (`Emitter`, `CollectorProtocol`, `Resolver`), not ABC/inheritance. This enables:
- Custom implementations without coupling
- Duck typing with type safety
- Composition over inheritance

### 2. Layered APIs

Most features provide multiple abstraction levels:
- **Functional**: One-off analysis (collect_signals)
- **Class-based**: Stateful operations (Collector)
- **Protocol-based**: Full customization (CollectorProtocol)

This allows users to start simple and go deeper without rewriting.

### 3. Explicit Configuration Over Magic

Mode detection and other decisions are **explicit and inspectable**:
```python
detect_mode(json_flag=args.json, plain_flag=args.plain)
```

Not magic environment detection. The logic is visible.

### 4. Self-Contained Modules

Each module can be read, understood, and copied independently. No module depends on implementation details of another.

### 5. Data Over Process

Events are data. Emitters process data. Collectors aggregate data. Renderers display data. This functional orientation makes everything composable.

---

## Recipes: Copy-Paste Patterns

The toolkit acknowledges that some patterns are **too domain-specific for the main API** but **valuable as starting points**. The recipes module includes:

- **ProgressTracker**: Track progress for known-length iterations
- **VerbosityFilter**: Filter by verbosity level
- **BatchCollector**: Base for batch-style emitters
- **ContextEmitter**: Use emitters as context managers

The philosophy: **Not everything belongs in the core API**. Recipes are documented patterns you read, copy, and adapt.

---

## Code Generation & KDL Specs

The toolkit includes a **KDL-based code generator** (`ev_toolkit.gen`) for scaffolding CLI tools.

### What Works
- **Simple CRUD commands**: Request → signals → result pattern
- **Documentation**: Spec format as contract before implementation
- **Schema enforcement**: Validate signal emissions match declarations

### What Doesn't Work
- **Streaming commands**: Live displays, tailing
- **Interactive CLIs**: User prompts, confirmations
- **Complex orchestration**: Multi-phase operations

### Philosophy
Generated code should **look almost identical to hand-written code**. If you're heavily rewriting scaffolds, the generator isn't capturing your patterns. Better to encode patterns as library code (like ProgressTracker) that your hand-written code uses.

---

## Mental Model Summary: The Three-Layer Stack

```
┌─────────────────────────────────────────┐
│  Application Layer                      │
│  (Your business logic, domain code)     │
├─────────────────────────────────────────┤
│  ev-toolkit Layer                       │
│  (Emitters, collectors, convenience)    │
├─────────────────────────────────────────┤
│  ev Core Layer                          │
│  (Event, Result, Emitter protocol)      │
├─────────────────────────────────────────┤
│  I/O Layer                              │
│  (Files, stdout, stderr, networking)    │
└─────────────────────────────────────────┘
```

**The contract**: Application code calls `emitter.emit(Event)` and returns `Result`. Everything else is composition and routing.

---

## Conceptual Takeaways

1. **Events are data, not strings**: Enables composition and multiple output formats
2. **Emitters are middleware**: Each wrapper adds behavior without modifying the contract
3. **Results are structured**: Enable machine-readable output and proper error handling
4. **Output mode is policy**: Encode conventions for TTY, JSON, plain text
5. **Collection enables streaming**: Process events as they arrive, decide when to render
6. **Rendering is separate from logic**: Semantic IR allows backend independence
7. **Composition is the core principle**: Everything stacks naturally

---

## Relationship to Other Systems

### Compared to print()
- Print is unstructured; events are data
- Print has no output modes; events compose to different formats
- Print is untestable; events can be recorded and replayed
- Print goes to one place; events can be tee'd to multiple destinations

### Compared to logging frameworks (Python's logging, spdlog, etc.)
- Logging is often hierarchical; ev is flat but structured
- Logging is about capturing what happened; ev is about reporting status and results
- Logging has levels (debug, info, warn, error); ev extends this with signals, progress, artifacts, metrics
- Logging is unidirectional (to files); ev is composable (tee to multiple emitters)

### Compared to CLI frameworks (Click, Typer, Cappa)
- Those frameworks handle CLI parsing; ev-toolkit handles output
- ev-toolkit works with any CLI framework (compatible with argparse, Click, Typer, etc.)
- Those frameworks focus on input; ev focuses on output

---

## Conclusion

**ev-toolkit** is not a framework—it's a collection of battle-tested patterns for bridging the ev contract to real-world CLI needs. It provides:

- **Composable building blocks** that solve real problems (TeeEmitter, collectors, mode detection)
- **Copy-paste friendly code** that you can read and understand completely
- **Layered APIs** that let you start simple and go deeper
- **Encoded conventions** for how CLI tools should behave (output modes, error messages, etc.)
- **Semantic rendering** that separates logic from presentation

The philosophy is **explicit over implicit, simple by default, composable always**. Whether you're migrating from print-based scripts or building complex interactive tools, the toolkit provides the conceptual model and building blocks to structure your code around the ev contract.
