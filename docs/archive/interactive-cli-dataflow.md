# Interactive CLI Dataflow

The middle layer between CLI scripts and full TUI.

## Core Architecture

```mermaid
flowchart TB
    subgraph Sources["Event Sources (async)"]
        queue["Queue Consumer"]
        logs["Log Stream"]
        poller["Status Poller"]
        webhook["Webhook Listener"]
    end

    subgraph Store["EventStore (source of truth)"]
        events["events: list[Event]"]
        record["FileRecorder\n(JSONL)"]
        subs["subscribers"]
    end

    subgraph View["Interactive View"]
        filter["ViewFilter\n(mutable)"]
        query["query(filter, limit)"]
        render["Rich Live\n(Table/Panel)"]
    end

    subgraph Input["User Input"]
        keys["Keystrokes\na/e/w/q/1-5"]
    end

    Sources -->|"store.add(event)"| events
    events --> record
    events -->|"notify"| subs
    subs --> query
    filter --> query
    query --> render
    keys -->|"change filter"| filter
    filter -.->|"triggers re-render"| render
```

## Data Flow Sequence

```mermaid
sequenceDiagram
    participant Src as Event Source
    participant Store as EventStore
    participant File as FileRecorder
    participant View as InteractiveView
    participant User as User (keystrokes)

    Note over Store: Always records everything

    loop Streaming
        Src->>Store: add(event)
        Store->>File: write JSONL
        Store->>View: notify(event)
        View->>View: query(filter) → render
    end

    User->>View: keystroke 'e'
    View->>View: filter.level = "error"
    View->>Store: query(filter)
    Store-->>View: filtered events
    View->>View: render (errors only)

    Note over File: Full record unchanged
```

## Component Responsibilities

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            EventStore                                   │
├─────────────────────────────────────────────────────────────────────────┤
│ Owns:                                                                   │
│   - All events (append-only list)                                       │
│   - Recording to file                                                   │
│   - Subscriber notification                                             │
│                                                                         │
│ Does NOT own:                                                           │
│   - Filtering (that's View's job)                                       │
│   - Rendering (that's View's job)                                       │
│   - Event creation (that's Source's job)                                │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                            ViewFilter                                   │
├─────────────────────────────────────────────────────────────────────────┤
│ Owns:                                                                   │
│   - Current filter state (level, queue, time range, etc.)               │
│   - Filter predicates                                                   │
│                                                                         │
│ Mutable: Yes (keystrokes change it)                                     │
│ Persisted: No (transient UI state)                                      │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                          InteractiveView                                │
├─────────────────────────────────────────────────────────────────────────┤
│ Owns:                                                                   │
│   - Rich Live instance                                                  │
│   - Keystroke handling                                                  │
│   - Render logic (Table layout, colors)                                 │
│                                                                         │
│ Queries:                                                                │
│   - EventStore (with current filter)                                    │
│                                                                         │
│ Updates when:                                                           │
│   - New event arrives (subscriber callback)                             │
│   - Filter changes (keystroke)                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## State Ownership

```
┌──────────────────┬─────────────────┬─────────────────┬─────────────────┐
│ State            │ Owner           │ Mutability      │ Persistence     │
├──────────────────┼─────────────────┼─────────────────┼─────────────────┤
│ events[]         │ EventStore      │ Append-only     │ JSONL file      │
│ filter           │ ViewFilter      │ Mutable         │ None (session)  │
│ visible_events   │ Derived         │ Re-computed     │ None            │
│ render output    │ View            │ Re-rendered     │ None            │
└──────────────────┴─────────────────┴─────────────────┴─────────────────┘
```

## Where Signals Could Fit

```mermaid
flowchart LR
    subgraph "Current (imperative)"
        filter1["filter (mutable obj)"]
        change1["keystroke → filter.level = 'error'"]
        render1["manual: view.render()"]
    end

    subgraph "With Signals (reactive)"
        filter2["filter_level: Signal"]
        change2["keystroke → filter_level.set('error')"]
        render2["Effect auto-triggers render"]
    end
```

Signals would help when:
- Multiple derived views from same filter
- Complex filter interdependencies
- Need to track "previous filter" for transitions

For simple single-view case: imperative is fine.

## Composability

```python
# Reusable components
from interactive_cli import EventStore, ViewFilter, InteractiveView

# Your specific script
@dataclass
class OrderEvent:
    order_id: str
    status: str
    amount: float
    ts: float

class OrderView(InteractiveView):
    def render_event(self, event: OrderEvent) -> Text:
        # Custom rendering for your domain
        ...

# Wire it up
store = EventStore(record_path=args.record)
view = OrderView(store, filter=ViewFilter(level="warn"))

async with KafkaConsumer(args.topic) as consumer:
    async for msg in consumer:
        store.add(parse_order_event(msg))
```

## The Pattern in One Picture

```
                    ┌─────────────────────────────────────┐
                    │         Your Script (PEP723)        │
                    │                                     │
                    │  ┌─────────────────────────────┐    │
   Event Source ───▶│  │        EventStore          │    │
   (queue, logs,    │  │  ┌─────────┐  ┌─────────┐  │    │
    poller, etc)    │  │  │ events  │  │ record  │  │    │
                    │  │  │  [ ]    │  │ (file)  │  │    │
                    │  │  └────┬────┘  └─────────┘  │    │
                    │  └───────┼───────────────────┘    │
                    │          │                         │
                    │          ▼                         │
                    │  ┌─────────────────────────────┐   │
                    │  │     InteractiveView         │   │
                    │  │  ┌─────────┐  ┌─────────┐   │   │
   Keystrokes ─────▶│  │  │ filter  │  │  Rich   │   │──▶ Display
   (a/e/w/q)        │  │  │(mutable)│  │  Live   │   │
                    │  │  └─────────┘  └─────────┘   │   │
                    │  └─────────────────────────────┘   │
                    │                                     │
                    └─────────────────────────────────────┘

   Recording happens regardless of view filter.
   View is just a window into the event stream.
```

## Key Principles

1. **Events are primary** - everything that happens becomes an event
2. **Store is append-only** - never lose data
3. **Recording is automatic** - not a separate concern
4. **Filter is transient** - UI state, not persisted
5. **View is derived** - query(store, filter) → render
6. **Keystrokes mutate filter** - not events, not store
