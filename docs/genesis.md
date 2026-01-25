# Genesis: rill

## The Inciting Problem

It started with a queue dashboard. A developer needed to watch events stream through message queues at work — a quick script with Rich that connects, subscribes, and updates a table as messages flow in. It worked. Then another script. Then another. Each time: stand up the same patterns, the same state management, the same recording logic.

The friction wasn't the domain logic — it was the infrastructure around it. Every streaming CLI tool needed:
- An append-only event store
- Filtering without losing data
- Recording for replay and audit
- UI that updates as events arrive
- Graceful shutdown

The question: what's the minimal set of primitives that makes "build a streaming event viewer" trivially composable?

## Thread 1: The Reactive Detour

The first attempt reached for reactive primitives. The insight seemed obvious: FRP (functional reactive programming) was built for exactly this — state changes flow through derivations to outputs. Angular Signals, SolidJS, the pattern was proven in frontend.

A Python Signals library (`reaktiv`) provided the primitives: `Signal` (mutable cell), `Computed` (derived value), `Effect` (side effect). The architecture:

```
Signal (state) → Computed (derived) → Effect (side effect)
                                         ↓
                                    Rich Live update
```

Four examples validated the pattern progressively:

| Example | Domain | Question answered |
|---------|--------|-------------------|
| Dashboard | Independent events | Does reactive + Rich work at all? |
| HTTP Logger | Correlated events | Can Computed handle derived state? |
| HTTP Logger v2 | More panes | Do features compose without refactoring? |
| Process Manager | User actions | Does the pattern hold when users cause events? |

The answers were all yes. The pattern worked. But something was wrong.

## The O(n²) Wall

The problem surfaced during benchmarking. The core loop was:

```python
lines = Signal([])
visible = Computed(lambda: lines()[-20:])  # Bounded view

# On each new event:
lines.update(lambda ls: [*ls, new_line])  # O(n) copy every time
```

For streaming data, this was O(n²) in the number of events. At 1000 events/second, it became noticeable. At 10,000, it was unusable.

The insight: **Signals optimize for interconnected state with fine-grained updates. Append-only logs are a different shape.** You don't need dependency tracking when the only operation is "add to end."

## Thread 2: The Events-Primary Pivot

The observation that triggered the shift came in conversation:

> "It seems... off that our UI is handled off to the side, separate from the event system."

In the reactive model, UI and events were parallel side effects of the same Signal state — siblings, not parent-child. You couldn't replay the UI. Recording was a parallel concern, not an intrinsic one.

The events-primary architecture inverted this:

```
Input → EventBus → Subscribers
              ├─→ UISubscriber (renders)
              ├─→ FileSubscriber (records all)
              ├─→ FilteredFileSubscriber (errors only)
              └─→ StatsSubscriber (aggregates)
```

The EventBus became the spine. Everything flows through it. Subscribers derive their own state from the event stream. Replay became trivial — feed the JSONL back and you get the exact same renders.

The performance comparison was decisive:

| Aspect | Signals | Events-Primary |
|--------|---------|----------------|
| Source of truth | Signals | Event stream |
| Append cost | O(n) copy | O(1) |
| Recording | Parallel concern | Just another subscriber |
| Replay | Can't reconstruct | Full replay |

This sealed the direction.

## Thread 3: The Stream Topology

The deeper realization came next: **EventStore is just one consumer, not the center. The Stream is the center.**

```python
stream: Stream[HealthCheck] = Stream()
stream.tap(store)           # persist
stream.tap(projection)      # fold → state
stream.tap(FileWriter(...)) # record
stream.tap(webhook, filter=lambda e: "unhealthy" in e.status)
```

The topology primitives crystallized:

- `Stream[T]` — typed async broadcast
- `Consumer[T]` — protocol for anything that eats events
- `Tap[T]` — handle for detach
- `Projection[S,T]` — incremental fold (materialized view)
- `EventStore[T]` — append-only log
- `FileWriter[T]` — JSONL persistence
- `Tailer[T]` — byte-offset reader for replay
- `Forward[T,U]` — bridge between typed streams

Design constraints were deliberate negations:

- No operator chains (not Rx)
- No backpressure (async/await naturally bounds)
- No main loop ownership
- Sources are NOT a type (just async functions that call `stream.emit()`)
- No external reactivity library — version counters, not Signals

The push topology handles invalidation. The reactive model served its purpose — it proved the pattern — but the streaming topology subsumed its role.

## The File-as-Broker Insight

The final conceptual piece: **the file IS the broker.**

```
FileWriter writes:  {"type": "log", "msg": "...", "ts": 1234}
                    {"type": "log", "msg": "...", "ts": 1235}
                    ↓
                    byte offset 0
                    byte offset 47
                    byte offset 94
                    ↓
Tailer reads from:  offset 47 → returns events after that point
```

This is a Kafka partition at personal scale. JSONL + byte offset gives you:
- Append-only durability
- Consumer position tracking
- Replay from any point
- Multiple independent consumers

No broker process. No network protocol. Just files. The filesystem handles durability, atomicity (within reasonable constraints), and access control.

## The Extraction

With the topology proven, the extraction was straightforward. The primitives totaled ~440 lines with zero external dependencies:

```
rill/
├── stream.py      # 75 lines  — Stream[T], Tap, Consumer
├── store.py       # 125 lines — EventStore[T]
├── projection.py  # 83 lines  — Projection[S,T]
├── file_writer.py # 39 lines  — FileWriter[T]
├── tailer.py      # 91 lines  — Tailer[T]
└── forward.py     # 27 lines  — Forward[T,U]
```

Metrics/instrumentation was stripped — consumers can add their own observability. The version counter pattern replaced Signals — a simple integer that bumps on mutation, enabling poll-based change detection without dependency graphs.

## What rill Is

**rill** is personal-scale event infrastructure. Kafka concepts — append-only logs, offset-tracking consumers, materialized views — at individual/homelab scale, using files instead of brokers.

The name fits: a rill is a small stream. Personal scale. The primitives are portable; the philosophy is opinionated.

```
Typed event → Stream → Consumers (fan-out)
                 ↓
            FileWriter → JSONL file
                 ↓
              Tailer → replay from any offset
                 ↓
            Projection → derived state (fold)
```

## What Was Learned

1. **Signals optimize for the wrong shape.** Fine-grained reactivity shines for interconnected state. Append-only streams need different primitives.

2. **Events are primary, state is derived.** The log is truth. State = fold(events). This inverts the usual model where state is primary and events are notifications.

3. **The file IS the broker.** JSONL + byte offset = partition semantics without broker overhead. Good enough for personal scale.

4. **Version counters beat dependency tracking** for simple invalidation. Poll the version, recompute if changed. No graph traversal.

5. **Zero dependencies is a feature.** The primitives use only stdlib. Consumers add what they need.

## The Arc

```
Rich Live scripts (ad hoc)
         ↓
Signals/Computed/Effect (reaktiv)
         ↓
O(n²) wall hit
         ↓
Events-primary (EventBus → Subscribers)
         ↓
Stream topology (Stream → Consumer fan-out)
         ↓
File-as-broker (FileWriter + Tailer)
         ↓
rill extraction (440 lines, zero deps)
```

The reactive detour wasn't wasted — it proved the pattern and found the boundary. Different shapes of state need different primitives. rill is the primitive set for append-only event streams at personal scale.

## See Also

- `~/Code/experiments` — homelab orchestration using rill
- `~/Code/cells` — TUI rendering layer (separate concern)
- The `ev` vocabulary — Event/Result/Emitter for CLI operations
