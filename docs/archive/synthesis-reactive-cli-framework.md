# Synthesis: Toward a Reactive CLI/TUI Framework

## The Pattern You're Circling

You've independently reconstructed the frontend reactive paradigm for CLI:

| Frontend Concept | Your CLI Equivalent | What It Does |
|------------------|---------------------|--------------|
| State (useState, signals) | reaktiv Signal | Source of truth |
| Derived state (useMemo, computed) | reaktiv Computed | Transformations |
| Side effects (useEffect) | reaktiv Effect | React to changes |
| Virtual DOM | ev-toolkit present (Line/Segment) | Semantic IR |
| DOM | Terminal (Rich, plain text) | Actual output |
| Events (onClick, etc.) | ev Event/Result | Structured communication |
| Components | ? (StatusRenderer, live_tree) | Reusable UI patterns |
| Reconciliation | ? | Diffing/updating |

The insight: **ev is the event contract, reaktiv is the state engine, and you need the glue layer that makes them work together as a reactive rendering system.**

---

## What Each Piece Brings

### ev (The Contract Layer)
```
Event → Emitter → Output
Result → Emitter → Final State
```

**Strengths:**
- Clean separation: Truth (Result) vs Telemetry (Events) vs Narrative (logs)
- Multiple output modes from same logic
- Testable (ListEmitter captures everything)
- Serializable (JSON round-trip)

**What it lacks:**
- No concept of *reactive* state
- Events are fire-and-forget, not derived from state
- Emitter has no memory—it just receives and outputs

### ev-toolkit (The Composition Layer)
```
Events → Collectors → Aggregated State
Aggregated State → present IR → Rendered Output
```

**Strengths:**
- Semantic IR (Line/Segment/Context) separates meaning from presentation
- Collectors enable aggregation patterns
- Wrappers compose (Tee, Filter, Timing, etc.)
- Mode detection encodes policy

**What it lacks:**
- No reactive bindings—you poll state, not subscribe
- `handle()` is close to an Effect, but manual
- No automatic re-rendering when state changes

### reaktiv (The Reactivity Engine)
```
Signal → Computed → Effect
         ↓
    Automatic dependency tracking
    Batched updates
    Lazy evaluation
```

**Strengths:**
- Fine-grained reactivity (only affected parts recompute)
- Automatic dependency tracking (no manual subscriptions)
- Batched updates (multiple changes → one render)
- Resource for async data loading with status

**What it lacks:**
- No rendering layer
- No structured event/result contract
- No terminal-specific patterns

---

## The Unified Model

Here's how they compose:

```
┌─────────────────────────────────────────────────────────────────┐
│                     APPLICATION LOGIC                           │
│   (Your domain code: check_stacks(), fetch_media(), etc.)      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    REACTIVE STATE LAYER                         │
│                         (reaktiv)                               │
│                                                                 │
│   Signal[List[Stack]]  ──►  Computed[List[StackStatus]]        │
│   Signal[FilterText]   ──►  Computed[FilteredStacks]           │
│   Resource[HealthData] ──►  (.value, .status, .error)          │
│                                                                 │
│   State changes automatically propagate through the graph       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    COMPONENT LAYER (new)                        │
│                                                                 │
│   Components are functions: Signal[T] → Line[]                  │
│                                                                 │
│   StatusTable(stacks: Signal[List[Stack]]) → Line[]            │
│   ProgressBar(current: Signal[int], total: int) → Line[]       │
│   Tree(items: Signal[List[Item]], renderer) → Line[]           │
│                                                                 │
│   Components are Computed values—they only recompute when       │
│   their input signals change                                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    SEMANTIC IR LAYER                            │
│                  (ev-toolkit present)                           │
│                                                                 │
│   Line(segments=[                                               │
│       Segment(role="icon", text="✓", hint="green"),            │
│       Segment(role="label", text="media"),                      │
│       Segment(role="count", text="3/3"),                        │
│   ], context=Context(kind="status", state="healthy"))          │
│                                                                 │
│   Backend-neutral representation of what to display             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    REACTIVE EMITTER LAYER (new)                 │
│                                                                 │
│   ReactiveEmitter wraps an inner Emitter and subscribes to      │
│   a Signal[List[Line]] or Computed[List[Line]]                  │
│                                                                 │
│   Effect(lambda: emitter.render(ui_lines()))                    │
│                                                                 │
│   When signals change → Effect runs → Emitter re-renders        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    OUTPUT LAYER                                 │
│                      (ev emitters)                              │
│                                                                 │
│   RichEmitter  → Terminal with styling                          │
│   PlainEmitter → ASCII text                                     │
│   JsonEmitter  → Machine-readable                               │
│   TeeEmitter   → Multiple outputs                               │
└─────────────────────────────────────────────────────────────────┘
```

---

## The Missing Pieces

### 1. Reactive Emitter Bridge

Connect reaktiv Effects to ev Emitters:

```python
class ReactiveEmitter:
    """Emitter that re-renders when source signals change."""

    def __init__(
        self,
        inner: Emitter,
        ui: Callable[[], Iterable[Line]],  # A Computed or function reading Signals
        console: Console | None = None,
    ):
        self._inner = inner
        self._ui = ui
        self._console = console or Console(stderr=True)
        self._live: Live | None = None
        self._effect: Effect | None = None

    def __enter__(self):
        self._live = Live(console=self._console, refresh_per_second=10)
        self._live.__enter__()

        # Effect automatically tracks dependencies and re-runs
        self._effect = Effect(self._render)
        return self

    def _render(self):
        """Called automatically when any dependency changes."""
        lines = self._ui()
        renderable = lines_to_rich(lines)
        self._live.update(renderable)

    def emit(self, event: Event) -> None:
        # Events still flow to inner emitter (for recording, JSON, etc.)
        self._inner.emit(event)

    def finish(self, result: Result) -> None:
        if self._effect:
            self._effect.dispose()
        if self._live:
            self._live.__exit__(None, None, None)
        self._inner.finish(result)
```

### 2. Component Model

Components as functions that read signals and return Lines:

```python
# A component is just a function that reads signals and returns Lines
def StatusRow(
    label: str,
    status: ReadableSignal[str],
    counts: ReadableSignal[tuple[int, int]],
) -> Line:
    """Reactive status row—automatically updates when signals change."""
    healthy, total = counts()
    state = status()

    return Line(segments=(
        Segment(role="icon", text=STATE_ICONS[state], hint=STATE_COLORS[state]),
        Segment(role="label", text=f" {label}"),
        Segment(role="separator", text=" "),
        Segment(role="count", text=f"{healthy}/{total}"),
    ), context=Context(kind="status", state=state))


def StatusTable(stacks: ReadableSignal[list[StackResult]]) -> list[Line]:
    """Reactive status table—recomputes only when stacks change."""
    return [
        StatusRow(
            label=s.name,
            # These could be derived signals if you want finer granularity
            status=Computed(lambda s=s: s.status),
            counts=Computed(lambda s=s: (s.healthy, s.total)),
        )
        for s in stacks()
    ]
```

But wait—this creates new Computed on every call. Better pattern:

```python
class StatusTable:
    """Reactive status table component."""

    def __init__(self, stacks: ReadableSignal[list[StackResult]]):
        self._stacks = stacks
        # Computed that produces Lines—only recomputes when stacks changes
        self.lines: ComputeSignal[list[Line]] = Computed(self._render)

    def _render(self) -> list[Line]:
        return [self._row(s) for s in self._stacks()]

    def _row(self, stack: StackResult) -> Line:
        return Line(segments=(
            Segment(role="icon", text=STATE_ICONS[stack.status]),
            Segment(role="label", text=f" {stack.name}"),
            Segment(role="count", text=f"{stack.healthy}/{stack.total}"),
        ))
```

### 3. Resource → Signal Integration

reaktiv's Resource already does this! But we need patterns for status display:

```python
async def main():
    # Resource automatically reloads when selected_stack changes
    health_data = Resource(
        params=lambda: selected_stack(),
        loader=fetch_stack_health,
    )

    # UI derived from resource state
    ui_lines = Computed(lambda: [
        *header_lines(),
        *match health_data.status():
            case ResourceStatus.LOADING: [loading_spinner()]
            case ResourceStatus.ERROR: [error_display(health_data.error())]
            case ResourceStatus.RESOLVED: StatusTable(health_data.value).lines()
    ])

    # Reactive emitter renders whenever ui_lines changes
    with ReactiveEmitter(JsonEmitter(), ui=ui_lines) as emitter:
        # Run until done
        await asyncio.sleep(10)
        return Result.ok("done", data=health_data.value())
```

### 4. Event/Signal Bridge

When should you emit an ev Event vs update a Signal?

**Use Signals for:**
- State that affects UI rendering
- Data that changes over time
- Values that other computations depend on

**Use Events for:**
- Audit trail (what happened during execution)
- Machine-readable output (for automation)
- Structured logs (for LLM review, debugging)

**The bridge pattern:**

```python
# Effect that emits events when notable state changes
def emit_on_notable_change(
    emitter: Emitter,
    signal: ReadableSignal[T],
    signal_name: str,
    is_notable: Callable[[T], bool],
    to_data: Callable[[T], dict],
):
    """Emit ev Event when signal value is notable."""
    prev_notable = [False]

    def check():
        value = signal()
        notable = is_notable(value)

        if notable and not prev_notable[0]:
            emitter.emit(Event.log_signal(signal_name, **to_data(value)))

        prev_notable[0] = notable

    return Effect(check)


# Usage
emit_on_notable_change(
    emitter,
    stack_status,
    signal_name="stack.unhealthy",
    is_notable=lambda s: s.status == "unhealthy",
    to_data=lambda s: {"stack": s.name, "healthy": s.healthy, "total": s.total},
)
```

---

## The Framework Shape

```
reaktiv-cli (working name)
├── core/
│   ├── __init__.py
│   ├── signals.py      # Re-export reaktiv (or vendor it)
│   └── bridge.py       # ReactiveEmitter, Event/Signal bridge
│
├── components/
│   ├── __init__.py
│   ├── base.py         # Component protocol/base class
│   ├── status.py       # StatusRow, StatusTable
│   ├── progress.py     # ProgressBar, Spinner
│   ├── tree.py         # Tree, TreeNode
│   ├── table.py        # Table, TableRow
│   └── layout.py       # Horizontal, Vertical, Panel
│
├── present/            # Lift from ev-toolkit
│   ├── __init__.py
│   ├── ir.py           # Line, Segment, Context
│   ├── semantic.py     # Semantic types
│   └── render.py       # Line → Rich/Plain converters
│
├── runtime/
│   ├── __init__.py
│   ├── harness.py      # run() with reactive support
│   └── args.py         # Standard arg handling
│
└── compat/
    ├── __init__.py
    └── ev.py           # ev Event/Result/Emitter integration
```

---

## What This Enables

### Before (imperative, manual updates):

```python
async def status_command(emitter, args):
    console = Console(stderr=True)

    with Live(console=console) as live:
        results = {}

        async def check_stack(stack):
            result = await fetch_health(stack)
            results[stack] = result
            # Manual re-render
            live.update(render_table(results))

        await asyncio.gather(*[check_stack(s) for s in STACKS])

    # Manual event emission
    for name, result in results.items():
        if result.status == "unhealthy":
            emitter.emit(Event.log_signal("stack.unhealthy", ...))

    return Result.ok("done", data={"stacks": list(results.values())})
```

### After (reactive, automatic updates):

```python
async def status_command(emitter, args):
    # State
    stacks = Signal({})

    # Derived UI (automatically updates when stacks changes)
    ui = StatusTable(Computed(lambda: list(stacks().values())))

    # Auto-emit events for notable changes
    emit_on_unhealthy = emit_on_notable_change(
        emitter, stacks, "stack.unhealthy",
        is_notable=lambda s: any(r.status == "unhealthy" for r in s.values()),
        to_data=lambda s: {"unhealthy": [n for n, r in s.items() if r.status == "unhealthy"]},
    )

    # Reactive rendering
    with ReactiveEmitter(emitter, ui=ui.lines) as rem:
        async def check_stack(stack):
            result = await fetch_health(stack)
            stacks.update(lambda s: {**s, stack: result})  # Triggers re-render

        await asyncio.gather(*[check_stack(s) for s in STACKS])

    return Result.ok("done", data={"stacks": list(stacks().values())})
```

**What changed:**
- No manual `live.update()` calls—Effect handles it
- No manual event emission loops—bridge handles it
- State changes propagate automatically
- UI is derived, not manually constructed

---

## The Deeper Pattern

You're building toward **declarative CLI applications**:

1. **Declare state** (Signals)
2. **Derive UI** (Computed → Lines)
3. **React to changes** (Effects → Events, Rendering)
4. **Return result** (Result with final state)

This is the same pattern as:
- React: State → Virtual DOM → DOM
- Solid: Signals → JSX → DOM
- SwiftUI: @State → View → UIKit

But for terminals:
- **reaktiv-cli**: Signals → Lines → Terminal

---

## Open Questions

1. **Reconciliation**: Should we diff Lines and only update changed parts? Rich's Live does full re-render, which is fine for small UIs but may flicker for large ones.

2. **Component identity**: When a list changes, how do we track which rows changed? (Keyed vs unkeyed, like React's `key` prop)

3. **Layout**: How do components compose spatially? Flexbox-like? Fixed regions?

4. **Input**: How do we handle user input (keyboard, mouse) reactively? Signal for input events?

5. **Testing**: How do we test reactive components? Snapshot the Line output?

6. **Async boundaries**: Where do async operations live? Resource handles data fetching, but what about user prompts, confirmations?

---

## Next Steps

1. **Prototype the bridge**: ReactiveEmitter that connects reaktiv Effects to ev-toolkit rendering
2. **Port one gruel script**: Take status.py and rewrite it with the reactive pattern
3. **Extract components**: Identify reusable patterns (StatusTable, ProgressBar, Tree)
4. **Formalize the component protocol**: What interface do components implement?
5. **Consider vendoring vs depending**: Should reaktiv be a dependency or vendored?

---

## The Vision

**A Python CLI/TUI framework where:**

- State is reactive (Signals, Computed)
- UI is derived (Components → Lines)
- Output is structured (Events, Results)
- Rendering is automatic (Effects)
- Multiple modes work (Rich, Plain, JSON)

This is **Solid.js for the terminal**—fine-grained reactivity, no virtual DOM diffing, direct updates to the parts that changed.

The pieces exist. They need to be composed.
