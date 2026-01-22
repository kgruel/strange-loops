# Interactive CLI Framework

A pattern for building interactive, streaming CLI tools using Rich and reaktiv.

## The Space

```
CLI scripts ──────► interactive-cli ──────► TUI (Textual)
                    (this pattern)

- Rich Live           - modes, panes        - scroll position
- keystrokes          - derived state       - focusable widgets
- streaming data      - filtering           - mouse interaction
```

**interactive-cli handles:** streaming display, hotkeys, mode switching, text input, multiple panes, derived metrics.

**Needs TUI for:** scrollable lists within panes, focusable widgets, mouse, complex editing.

## Core Architecture

```
EventStore
└── version: Signal ─────────────────────────┐
                                             │
Dashboard                                    │
├── _focused_pane: Signal ───────────────────┤
├── _mode: Signal ───────────────────────────┼──► Effect ──► Live.update()
├── _filter: Signal ─────────────────────────┤
├── _input_buffer: Signal ───────────────────┤
│                                            │
├── metric_a: Computed ◄─────────────────────┤
├── metric_b: Computed ◄─────────────────────┘
└── by_category: Computed
```

**One notification system.** All state is Signals. One Effect triggers render.

## reaktiv Primitives

| Primitive | Role |
|-----------|------|
| `Signal` | Mutable state (version counter, UI state) |
| `Computed` | Derived values (metrics, aggregations) |
| `Effect` | Side effects (render to terminal) |

## The Version Signal Pattern

Problem: `Signal.update(lambda ls: [*ls, item])` copies the entire list → O(n²) for n appends.

Solution: Keep events in a mutable list, use a version signal for dependency tracking.

```python
class EventStore:
    def __init__(self):
        self._events: list[Event] = []
        self.version = Signal(0)

    def add(self, event: Event) -> None:
        self._events.append(event)           # O(1) mutable append
        self.version.update(lambda v: v + 1) # O(1) signal bump
```

Computed signals depend on version:

```python
error_count = Computed(lambda:
    store.version() and sum(1 for e in store.events if e.level == "error") or 0
)
```

This gives reaktiv's auto-invalidation without O(n²) list copying.

## Key Components

### EventStore

Append-only fact store with version signal.

```python
class EventStore:
    def __init__(self):
        self._events: list[Event] = []
        self.version = Signal(0)

    def add(self, event: Event) -> None:
        self._events.append(event)
        self.version.update(lambda v: v + 1)

    @property
    def events(self) -> list[Event]:
        return self._events
```

### Dashboard

All UI state as Signals. One Effect for rendering.

```python
class Dashboard:
    def __init__(self, store: EventStore):
        self.store = store
        self._live: Live | None = None

        # UI state as Signals
        self._running = Signal(True)
        self._focused_pane = Signal("logs")
        self._mode = Signal(Mode.VIEW)
        self._filter = Signal(FilterQuery())
        self._input_buffer = Signal("")

        # Computed metrics
        self.error_count = Computed(lambda:
            store.version() and sum(1 for e in store.events if e.level == "error") or 0
        )

        # Effect: render when any dependency changes
        self._render_effect = Effect(lambda: self._do_render())

    def _do_render(self) -> None:
        # Read all dependencies
        self.store.version()
        self._focused_pane()
        self._mode()
        self._filter()
        self._input_buffer()

        # Side effect
        if self._live:
            self._live.update(self.render())
```

### Key Handlers

Mutate signals. No manual refresh needed—Effect handles it.

```python
def _handle_view_key(self, key: str) -> bool:
    if key == "q":
        self._running.set(False)
        return False
    elif key == "1":
        self._focused_pane.set("logs")
    elif key == "/":
        self._mode.set(Mode.FILTER)
        self._input_buffer.set("")
    # No refresh call - Effect triggers automatically
    return True
```

### Keyboard Input

Raw terminal mode for non-blocking keystroke capture.

```python
class KeyboardInput:
    def __enter__(self):
        self._old_settings = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())
        return self

    def __exit__(self, *args):
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self._old_settings)

    def get_key(self) -> str | None:
        if select.select([sys.stdin], [], [], 0)[0]:
            return sys.stdin.read(1)
        return None
```

## Layout Pattern

Rich Layout for multi-pane arrangement.

```python
def render(self) -> Layout:
    layout = Layout()

    layout.split_column(
        Layout(name="main", ratio=1),
        Layout(self._render_status(), name="status", size=1),
        Layout(self._render_help(), name="help", size=1),
    )

    layout["main"].split_row(
        Layout(self._render_left_pane(), name="left"),
        Layout(self._render_right_pane(), name="right"),
    )

    return layout
```

## Mode Pattern

Enum for UI modes, context-sensitive key handling.

```python
class Mode(Enum):
    VIEW = auto()
    FILTER = auto()
    # Add more as needed

def handle_key(self, key: str) -> bool:
    if self._mode() == Mode.VIEW:
        return self._handle_view_key(key)
    elif self._mode() == Mode.FILTER:
        return self._handle_filter_key(key)
```

## Main Loop

```python
async def run():
    store = EventStore()
    dashboard = Dashboard(store)

    generator = asyncio.create_task(generate_events(store))

    try:
        with KeyboardInput() as keyboard:
            with Live(console=console, refresh_per_second=10) as live:
                dashboard.set_live(live)

                while dashboard.running:
                    key = keyboard.get_key()
                    if key:
                        dashboard.handle_key(key)
                    await asyncio.sleep(0.05)
    finally:
        generator.cancel()
```

## Dependencies

```toml
dependencies = [
    "rich",      # Terminal rendering
    "reaktiv",   # Reactive state
]
```

## When to Use This Pattern

**Good fit:**
- Log viewers / tail -f replacements
- Queue watchers
- Status monitors
- Metric dashboards
- Any "streaming data + filtering + keyboard control"

**Use Textual instead when you need:**
- Scrolling within a pane
- Mouse interaction
- Focusable input widgets
- Complex nested layouts

## Reference Implementation

See `examples/dashboard.py` for a complete working example with:
- Two panes (logs + metrics)
- Filter mode with text input
- Quick filter hotkeys
- reaktiv-computed metrics
- Focus switching between panes
