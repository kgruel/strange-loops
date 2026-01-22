# ev: Comprehensive Conceptual Analysis

## Core Vision & Mental Model

**Primary Insight:**
> "Commands return verdicts. Events tell the story. Renderers decide how it looks."

The ev library establishes a fundamental separation of concerns for CLI output through three complementary layers:

1. **Result**: Authoritative verdict for automation (typed contract)
2. **Events**: Streaming telemetry facts (renderer-agnostic)
3. **Emitters**: Presentation logic (pluggable implementations)

## The Authority Model: Foundational Philosophy

ev's core principle solves a critical problem in Python CLIs: **automation cannot reliably determine success without a dedicated contract layer**.

**The Authority Rule:**
> "Automation must be able to ignore all Events entirely and still make correct decisions based on Result alone."

This divides information into three tiers:

### Tier 1: Truth (Result)
- For automation, control flow, CI pipelines
- Status: ok | error
- Code: exit code (0 for success)
- Data: structured payload for machine consumption
- Meta: interpretation context (timing, counts)

### Tier 2: Telemetry (Signals, Metrics, Progress, Artifacts)
- For humans watching execution
- For dashboards and monitoring systems
- For audit trails and replay
- Examples: `stack_status`, `deployment_duration`, `current=2/5`, file paths

### Tier 3: Narrative (Narrative Logs)
- For human explanation
- Suppressible with `--quiet`
- Unstable wording acceptable
- No machine should parse these for decisions

## Event System: Five Frozen Primitives

The event model is intentionally **minimal and frozen**. New kinds only added if renderers literally cannot function without them.

### Five Event Kinds:

1. **log** — Narrative prose for humans ("Starting backup...")
   - Factory: `Event.log("message", level="info")`
   - May be suppressed
   - Not machine-parseable

2. **log_signal** — Structured observations (within log kind)
   - Factory: `Event.log_signal("stack_status", stack="media", healthy=True)`
   - Stable identifier for filtering
   - Data is queryable attributes
   - Used for UX, dashboards, monitoring
   - Example topics: `signal:container_state`, `signal:deployment_started`

3. **progress** — Advancement toward completion
   - Factory: `Event.progress("Checking URLs", current=2, total=5)`
   - Quantified (step, percent, phase)
   - Renderer decides visualization (bar, spinner, text)
   - Not for "task started" (use log instead)

4. **artifact** — Durable outputs surviving process boundary
   - Factory: `Event.artifact("file", path="/tmp/report.pdf")`
   - Requires `type` as first positional argument for discrimination
   - Examples: files, URLs, resource IDs, deployment records
   - Enables UX upgrades (hyperlinks, icons) and automation (copying, uploading)
   - Standard types: `file`, `url`, `resource`
   - Domain-specific types allowed: `deployment_record`, `test_report`

5. **metric** — Quantitative facts for graphing/comparison
   - Factory: `Event.metric("duration", 2.3, unit="s")`
   - Named measurement with value and optional unit
   - For dashboards, performance tracking
   - Not for iteration counts (use progress)

6. **input** — Recorded user decisions (for audit/replay)
   - Factory: `Event.input("Continue?", response="yes")`
   - Records prompt + response
   - Enables replay and audit trails

### Event Levels (all kinds):
- `debug`: Verbose detail (off by default)
- `info`: Normal operation (default)
- `warn`: Concerning but not failed
- `error`: Something went wrong

## Result: The Contract Layer

**Invariants enforced:**
- `status="ok"` requires `code=0`
- `status="error"` requires `code != 0`

**Fields:**
- `status`: "ok" | "error"
- `code`: int (exit code)
- `summary`: Human sentence (not parsed programmatically)
- `data`: Domain output (what `--json` prints, what automation consumes)
- `meta`: Metadata (duration_s, counts, attempt number, host, versions)

**Key Distinction: data vs meta**
- **data**: The actual command output (IDs, lists, computed values)
- **meta**: Interpretation context (timing, counts, run IDs)

Rule: If removing it would break automation logic, it's `data`. If it's just helpful context, it's `meta`.

**Factories:**
- `Result.ok("summary", data={...}, meta={...})`
- `Result.error("summary", code=1, data={...}, meta={...})`

## Event Semantics: Decision Tree

**When choosing an event kind:**

```
Is it a durable output (file, URL, ID)?
  → artifact

Is it a number you'd graph or compare?
  → metric

Is it advancement toward completion?
  → progress

Is it a user decision being recorded?
  → input

None of the above?
  → log (narrative) or log_signal (structured)
```

### log vs log_signal Decision:

| Use `log` when... | Use `log_signal` when... |
|---|---|
| Writing prose for humans | Emitting structured data |
| Message wording might change | Signal name is stable |
| No machine will parse it | Dashboards/monitors consume it |
| Narrative ("Starting...") | Observation ("container X is Y") |

## Output Streams Convention

**Streaming Emitters:**
- Write to **stderr**
- Output appears as events occur
- Good for long operations (user sees progress)
- Each event independent

**Batch Emitters:**
- Write to **stdout** (usually)
- Collect events, render once on `finish()`
- Can compose complex layouts (tables, trees)
- Can aggregate and reorder

**Unix Principle:**
```
my_command | jq .          # Pipe just result (stdout)
my_command 2>/dev/null     # Suppress events, just result
my_command 2>&1 | tee log  # Capture everything
```

## The Emitter Protocol: Minimal Interface

```python
class Emitter(Protocol):
    def emit(self, event: Event) -> None: ...
    def finish(self, result: Result) -> None: ...
    def __enter__(self) -> "Emitter": ...
    def __exit__(self, exc_type, exc_val, exc_tb) -> None: ...
```

**Invariants:**
- `emit()` may be called zero or more times
- `finish()` must be called exactly once
- `emit()` must not be called after `finish()`

**Reference Implementations:**
- `ListEmitter`: Collects for testing/inspection
- `NullEmitter`: Discards everything
- `JsonEmitter`: Outputs Result JSON to stdout, optionally streams Events as JSONL to stderr
- `PlainEmitter`: Minimal line-oriented output

**Philosophy:**
Reference emitters are **working examples**, not reusable building blocks. For production, you write **domain-specific emitters** that understand your event shapes and rendering needs.

## Emitter Archetypes: Two Patterns

### Streaming Archetype
```python
class StreamingEmitter:
    def emit(self, event: Event) -> None:
        # Render and write immediately
        line = self._format(event)
        self._file.write(line + "\n")
        self._file.flush()

    def finish(self, result: Result) -> None:
        # Final summary only
        self._file.write(f"Done: {result.summary}\n")
```

Best for: Long operations, need live feedback

### Batch Archetype
```python
class BatchEmitter:
    def emit(self, event: Event) -> None:
        # Collect, don't render yet
        if self._should_collect(event):
            self._items.append(event.data)

    def finish(self, result: Result) -> None:
        # Now render everything together
        output = self._compose(self._items, result)
        self._file.write(output)
```

Best for: Quick commands, rich output (tables, trees)

**Hybrid approaches** valid: Stream progress events, batch and render artifacts on finish.

## Composition Patterns

### Aggregating Wrapper Pattern
Wrap an emitter to accumulate state while delegating rendering:

```python
class CountingEmitter:
    def __init__(self, inner: Emitter, predicate: Callable[[Event], bool]):
        self._inner = inner
        self._predicate = predicate
        self.count = 0

    def emit(self, event: Event) -> None:
        if self._predicate(event):
            self.count += 1
        self._inner.emit(event)

    def finish(self, result: Result) -> None:
        self._inner.finish(result)
```

Purpose: Count successful/failed items, accumulate totals while streaming output.

### Command Context Pattern
Bundle CLI concerns into a single injection point:

```python
@dataclass
class CommandContext:
    config: ConfigSource
    mode: OutputMode
    verbosity: int

    @contextmanager
    def emitter(self) -> Iterator[Emitter]:
        """Create appropriate emitter for mode."""
        em = create_emitter(self.mode, self.verbosity)
        with em:
            yield em
```

Benefit: Commands become minimal; one injection point instead of 5+.

## Signal Lifecycle Pattern

For multi-stage operations, emit structured signals at each stage:

```python
# Stage starting
Event.log_signal("deploy.stage_started", stage="rsync", stack="media")

# ... do work ...

# Stage completed (success)
Event.log_signal("deploy.stage_completed", stage="rsync", duration_ms=2340)

# OR stage failed
Event.log_signal("deploy.stage_failed", stage="rsync", error="Connection refused")
```

**Signal Naming Convention:** `domain.subject` format
- `deploy.stage_started`
- `deploy.stage_completed`
- `deploy.stage_failed`

**Ephemeral vs Durable Signals:**
- Ephemeral (`*.started`, `*.connecting`): Transient state
- Durable (`*.completed`, `*.failed`): Facts worth persisting

Different emitters treat them differently: Batch ignores ephemeral, Live shows spinners for ephemeral.

## Mental Models for Users

### The Run Structure:
```
Run
 ├─ Event[]   # streaming facts during execution
 └─ Result    # final authoritative outcome
```

### Three Audiences, One Logic:

| Stream | Audience | Content |
|--------|----------|---------|
| PlainEmitter (stderr) | Human (terminal) | Clean narrative |
| LoggingEmitter | Ops (log aggregator) | Structured events |
| Result (stdout/exit code) | Automation (CI/scripts) | Verdict + data |

Same operation, three outputs. No code duplication.

### Testing Without Mocking:
```python
def test_check_urls():
    emitter = ListEmitter()
    result = check_urls(["http://a", "http://b"], emitter)
    emitter.finish(result)

    # Assert on result
    assert result.is_ok
    assert result.data["checked"] == 2

    # Assert on events
    signals = [e for e in emitter.events if e.is_signal]
    assert len(signals) == 2
```

No stdout capture. No string parsing. Structured assertions.

## Use Cases & Problem Domains

**Ideal For:**
- Infrastructure automation tools
- Homelab management CLIs
- Multi-stage deployment/sync operations
- Tools combining human UX with machine automation
- Infra-heavy CLIs where instrumentation matters

**Scaling Model:**
From one-off scripts → plugin-based tools (same abstraction throughout)

## Design Principles

1. **Minimal**: Smallest useful primitive set (frozen at 5 kinds)
2. **Opinionated**: Black-style (take-it-or-leave-it)
3. **Composable**: Generic primitives with rich conventions
4. **Serializable**: JSON-safe by default
5. **Python-first**: Great ergonomics, strong typing
6. **Effectively Immutable**: Events/Results are values; payloads immutable once emitted

## No Boundaries (What It Explicitly Is NOT)

- ❌ Not a CLI framework (no parsing, no commands)
- ❌ Not a renderer library (no Rich, ANSI — emitter's job)
- ❌ Not logging (Events are user-facing telemetry, not diagnostics)
- ❌ Not a workflow engine (describes output, doesn't control execution)

**Composable with:**
- Click/Typer for parsing
- Rich for rendering
- structlog for diagnostics

## Conceptual Positioning

**Solves the "Three Problems":**

1. **No Authoritative Verdict**
   - Problem: Exit codes unreliable, JSON bolted on late
   - Solution: Result is typed contract

2. **Telemetry/Truth Tangled**
   - Problem: Logs mix user narrative with automation data
   - Solution: Events separate from Result

3. **Tight Coupling**
   - Problem: Domain code imports Rich directly, untestable
   - Solution: Emitter protocol plugs in any renderer

## Key Terminology & Conventions

- **Emitter**: Any sink receiving Events + Result
- **Signal**: Structured observation within log kind
- **Topic**: Canonical identifier for tooling (`signal:stack_status`, `artifact:file`)
- **domain-emitters**: Your own emitters (the norm)
- **Streaming emitter**: Renders immediately in emit()
- **Batch emitter**: Collects, renders on finish()
- **Effective immutability**: Data treated immutable after emission
- **Authority Rule**: The foundational contract

## Conclusion

**ev presents a coherent mental model** where CLI output is understood through three complementary lenses:

1. What happened (Result) — for automation
2. How it happened (Events) — for humans and monitoring
3. How to show it (Emitters) — pluggable presentation

This separation enables:
- Clean testing without stdout mocking
- Multiple output formats from one codebase
- Instrumentation without coupling
- Reliable automation that doesn't parse text

The library is intentionally minimal (5 frozen event kinds, minimal Emitter protocol) while providing rich documentation and patterns for production use. It positions itself as the **contract layer between domain logic and rendering**, not as a framework or logging library.
