# The Reactive Data Visualization Ecosystem

How the temporal (ticks/rill) and spatial (cells) layers work together.

## Naming: Where and When

```
cells  = spatial atoms  (where)  → characters in a grid
ticks  = temporal atoms (when)   → events in a sequence
```

| | cells | ticks (rill) |
|---|-------|--------------|
| Atomic unit | Cell (char + style) | Tick/Event (timestamp + data) |
| Collection | Block (2D cells) | Stream (sequence of ticks) |
| Accumulation | Buffer (mutable grid) | Store (append-only log) |
| Transform | Lens (state → Block) | Projection (ticks → state) |
| Output | Writer (ANSI) | FileWriter (JSONL) |

The ev library's Event IS a tick - a timestamped fact with context:
```python
Event(kind="progress", ts=1609459200.123, data={"current": 50})
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    TEMPORAL LAYER (ticks/rill)                  │
│  Stream → Projection → Store → Tailer                           │
│  "ticks flow, state derives"                                    │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                     CONTRACT LAYER (specs)                      │
│  Event shapes → Fold ops → State shapes                         │
│  "declare what, derive how"                                     │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                       VISUAL LAYER (cells)                      │
│  State → Lens → Block → Buffer → Writer                         │
│  "state shapes render by convention"                            │
└─────────────────────────────────────────────────────────────────┘
```

## The Full Pipeline

```
Ticks → Stream → Projection → State → Lens → Block
         (tap)     (fold)              (map)
                    ↑                    ↑
                fold ops             zoom level
               (temporal)            (spatial)
```

**ticks** handles the temporal dimension: events flow, accumulate, derive state
**cells** handles the spatial dimension: state renders, composes, displays

## Design Principles

| Principle | Expression |
|-----------|------------|
| **Explicit over implicit** | Types, shapes, contracts visible |
| **Simple by default** | Minimal primitives, extend only when proven |
| **Patterns over point solutions** | General forms you can specialize |
| **Convention over primitive** | Reserved keys before new types |
| **Vocabulary IS API** | Naming choices define the mental model |

## ticks Vocabulary (temporal/data flow)

| Primitive | Signature | Verb |
|-----------|-----------|------|
| Tick/Event | timestamp + data | (atomic unit) |
| Stream | fan-out to consumers | emit, tap |
| Projection | `(State, Tick) → State` | apply, advance |
| Store | append-only log | add, since, evict |
| Tailer | offset-tracking reader | poll, reset |
| FileWriter | JSONL persistence | (consumer) |
| Forward | stream bridge | transform |

Core concepts: **emit**, **tap**, **fold**, **advance**, **version**

Connection to ev: ev's Event is a tick - timestamped fact with kind + data.
The emitter protocol streams ticks, then finishes with authoritative Result.

## cells Vocabulary (visual)

| Primitive | Signature | Verb |
|-----------|-----------|------|
| Cell | char + style | (atomic) |
| Block | 2D cell rectangle | paint, text |
| Buffer | mutable grid | fill, put_text |
| BufferView | clipped region | (delegate) |
| Lens | `(State, zoom) → Block` | render |
| Layer | modal stacking | push, pop |

Core concepts: **paint**, **compose**, **render**, **zoom**

## The Connection Point

```
rill Projection ──→ State ──→ cells Lens
     (derives)                 (renders)
```

State is the handoff. Projection produces it, Lens consumes it.

## Spec Layer (contracts)

The spec layer declares shapes without code:

```kdl
projection "process_status" {
  event {
    pid "int"
    state "string"
  }
  state {
    processes "dict"
  }
  fold {
    upsert "processes" key="pid" value="state"
  }
}
```

- Event spec: what shapes are valid input
- State spec: what shape is derived
- Fold ops: how events become state (upsert, latest, collect, count)
- Rendering: derived from state shape (dict→table, list→list-view)

## What This Enables

1. **No custom projection code** - fold ops cover 90% of cases
2. **No custom render code** - shape conventions handle it
3. **Replay** - EventStore + Projections give you time travel
4. **Hot reload** - change spec, see result immediately
5. **Agent-friendly** - simple enough for agents to wire up

## Direction for cells

cells should remain focused on the visual layer:
- Primitives for composition (Block, join_*, border, pad)
- Primitives for interaction (Layer, Search, FocusRing)
- Primitives for projection (Lens, ShapeLens)
- Output modes (RenderApp for TUI, print_block for CLI)

The Lens primitive bridges to rill's state. cells doesn't need to know about events or projections - it just renders state at zoom levels.
