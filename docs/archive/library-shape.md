# Interactive CLI Library - Reusable Shape

## The Core Insight

After exploring signals-only, emitters-only, and hybrid approaches, the pattern that emerged:

```
Events are facts (always recorded)
Filters are lenses (transient UI state)
Views are derived (query + render)
```

## Concept Map

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│   ┌─────────────┐     ┌─────────────┐     ┌─────────────┐                  │
│   │   reaktiv   │     │     ev      │     │    rich     │                  │
│   │             │     │             │     │             │                  │
│   │ Signal      │     │ Event       │     │ Live        │                  │
│   │ Computed    │     │ Emitter     │     │ Table       │                  │
│   │ Effect      │     │ Result      │     │ Panel       │                  │
│   └──────┬──────┘     └──────┬──────┘     └──────┬──────┘                  │
│          │                   │                   │                          │
│          │    ┌──────────────┴───────────────────┘                          │
│          │    │                                                             │
│          ▼    ▼                                                             │
│   ┌─────────────────────────────────────────────────────────────┐          │
│   │                    interactive-cli                           │          │
│   │                                                              │          │
│   │  EventStore    Filter/Query    View    SourceManager         │          │
│   │                                                              │          │
│   └─────────────────────────────────────────────────────────────┘          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Where Each Concept Fits

### ev: Event Definition + Recording

```python
# ev provides the event primitives
from ev import Event, Result

# We use ev for:
# 1. Structured event types (log_signal pattern)
# 2. Recording to JSONL (FileEmitter or similar)
# 3. Final Result of an operation
# 4. Multiple output formats (JSON, plain, rich)

# ev is the "what happened" layer
```

**ev's role:** Event schema, serialization, recording, output modes.

### reaktiv: Complex Derived State (Optional)

```python
# reaktiv is useful when:
# 1. Filter has interdependent parts
# 2. Need aggregations that auto-update
# 3. Multiple views derive from same state

# Example: dashboard with multiple computed metrics
error_count = Computed(lambda: sum(1 for e in store.events if e.level == "error"))
error_rate = Computed(lambda: error_count() / max(1, len(store.events)))

# reaktiv is the "derived state" layer
# NOT needed for simple append-only + filter
```

**reaktiv's role:** Optional. Use for complex derivations, skip for simple streaming.

### rich: Rendering

```python
# rich provides:
# 1. Live updating display
# 2. Tables, Panels, Text styling
# 3. The visual layer

# rich is the "how it looks" layer
```

**rich's role:** Pure rendering. No state management.

### interactive-cli (new): The Glue

```python
# This library provides:
# 1. EventStore - append-only, always records, queryable
# 2. Filter/Query - predicate language over events
# 3. View - Rich Live + keyboard handling + modes
# 4. SourceManager - dynamic async sources

# This is the "interactive streaming" layer
```

## Library Structure

```
interactive_cli/
├── __init__.py          # Public API
├── store.py             # EventStore
├── filter.py            # FilterQuery, predicates
├── view.py              # InteractiveView base class
├── sources.py           # SourceManager, async source protocol
├── keyboard.py          # KeyboardInput, cross-platform
└── recording.py         # Integration with ev for JSONL recording
```

## API Sketch

### EventStore

```python
from interactive_cli import EventStore

# Generic over event type
store = EventStore[MyEvent](
    record_path=Path("events.jsonl"),  # Optional: auto-record
)

# Add events (from any source)
store.add(event)

# Query with filter
events = store.query(filter, limit=50)

# Subscribe to new events
store.subscribe(lambda e: print(e))

# Properties
store.total  # Total event count
store.events  # All events (for iteration)
```

### FilterQuery

```python
from interactive_cli import FilterQuery

# Parse from string (user input)
f = FilterQuery.parse("level=error type=*failed payload.amount>100")

# Programmatic construction
f = FilterQuery().where("level", "=", "error").where("type", "~", ".*failed")

# Check if event matches
if f.matches(event):
    ...

# Combine filters
f = f1.and_(f2)
f = f1.or_(f2)
```

### View

```python
from interactive_cli import InteractiveView, Mode

class MyView(InteractiveView[MyEvent]):
    """Custom view for your event type."""

    def render_event(self, event: MyEvent) -> Text:
        """How to render a single event row."""
        ...

    def render_header(self) -> Text:
        """Optional: custom header."""
        ...

    def handle_custom_key(self, key: str) -> bool:
        """Optional: extend key handling."""
        if key == "x":
            self.do_something()
            return True  # Handled
        return False  # Not handled, use default

# Usage
view = MyView(store, max_visible=20)
await view.run()  # Blocks until quit
```

### SourceManager

```python
from interactive_cli import SourceManager, Source

# Define a source
class KafkaSource(Source[MyEvent]):
    def __init__(self, topic: str):
        self.topic = topic

    async def stream(self) -> AsyncIterator[MyEvent]:
        async with KafkaConsumer(self.topic) as consumer:
            async for msg in consumer:
                yield parse_event(msg)

# Manage sources
sources = SourceManager(store)
sources.register("orders", KafkaSource("orders-topic"))
sources.register("payments", KafkaSource("payments-topic"))

# Toggle at runtime
await sources.toggle("orders")  # Start
await sources.toggle("orders")  # Stop
```

### Recording (ev integration)

```python
from interactive_cli import EventStore
from interactive_cli.recording import EvRecorder

# Option 1: Built-in JSONL recording
store = EventStore(record_path=Path("events.jsonl"))

# Option 2: ev Emitter integration
from ev import TeeEmitter, FileEmitter

recorder = EvRecorder(
    emitter=TeeEmitter(
        FileEmitter(Path("all.jsonl")),
        FilteredEmitter(FileEmitter(Path("errors.jsonl")), level="error"),
    )
)
store = EventStore(recorder=recorder)
```

## Putting It Together

```python
#!/usr/bin/env python3
"""My queue watcher - PEP723 script."""

# /// script
# dependencies = ["interactive-cli", "aiokafka"]
# ///

from interactive_cli import EventStore, InteractiveView, SourceManager, Source
from dataclasses import dataclass

@dataclass(frozen=True)
class OrderEvent:
    order_id: str
    status: str
    amount: float
    ts: float

class OrderSource(Source[OrderEvent]):
    async def stream(self):
        async with KafkaConsumer("orders") as c:
            async for msg in c:
                yield OrderEvent(**json.loads(msg.value))

class OrderView(InteractiveView[OrderEvent]):
    def render_event(self, event: OrderEvent) -> Text:
        style = "red" if event.status == "failed" else "green"
        return Text(f"{event.order_id}: {event.status} ${event.amount}", style=style)

async def main():
    store = EventStore(record_path=Path("orders.jsonl"))
    sources = SourceManager(store)
    sources.register("orders", OrderSource())

    view = OrderView(store)
    await sources.start("orders")
    await view.run()

asyncio.run(main())
```

## Decision Tree: When to Use What

```
┌─────────────────────────────────────────────────────────────────┐
│ What are you building?                                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
        ┌─────────────────────────────────────────┐
        │ Streaming events with live display?     │
        └─────────────────────────────────────────┘
                    │                    │
                   Yes                   No
                    │                    │
                    ▼                    ▼
    ┌───────────────────────┐    ┌───────────────────────┐
    │ Use interactive-cli   │    │ Use ev directly       │
    │ (EventStore + View)   │    │ (Emitter + Result)    │
    └───────────────────────┘    └───────────────────────┘
                    │
                    ▼
        ┌─────────────────────────────────────────┐
        │ Complex derived state / aggregations?   │
        └─────────────────────────────────────────┘
                    │                    │
                   Yes                   No
                    │                    │
                    ▼                    ▼
    ┌───────────────────────┐    ┌───────────────────────┐
    │ Add reaktiv           │    │ Plain mutable state   │
    │ Signal/Computed for   │    │ is fine               │
    │ derived values        │    │                       │
    └───────────────────────┘    └───────────────────────┘
                    │
                    ▼
        ┌─────────────────────────────────────────┐
        │ Need scrolling, focus, mouse, complex   │
        │ layouts?                                │
        └─────────────────────────────────────────┘
                    │                    │
                   Yes                   No
                    │                    │
                    ▼                    ▼
    ┌───────────────────────┐    ┌───────────────────────┐
    │ Graduate to Textual   │    │ interactive-cli is    │
    │ (full TUI)            │    │ sufficient            │
    └───────────────────────┘    └───────────────────────┘
```

## Relationship Summary

| Concept | Role | When to Use |
|---------|------|-------------|
| **ev** | Event schema, recording, Result | Always (defines "what happened") |
| **reaktiv** | Automatic derived state | Complex derivations, optional |
| **rich** | Visual rendering | Always (defines "how it looks") |
| **interactive-cli** | Streaming + interactivity | Live-updating tools with filtering |
| **Textual** | Full TUI | When interactive-cli isn't enough |

## The Key Principles

1. **Events are primary** - Everything that happens is an event
2. **Record everything** - EventStore captures all, views filter
3. **Filters are transient** - UI state, not persisted
4. **Views are derived** - query(store, filter) → render
5. **Reactivity is optional** - Add reaktiv when derivations get complex
6. **ev for structure** - Use ev types for schema, recording, output modes
