# Handoff: Personal Event Infrastructure

## The Concept

This project is building **personal-scale event infrastructure** — the same concepts as Kafka (append-only logs, offset-tracking consumers, materialized views) but at individual/homelab scale, using files instead of brokers.

The pattern is always:

```
Typed fact → Append-only log → Derived views (projections)
```

This applies across all contexts — homelab monitoring, work alerting, cognitive effort capture, tool automation, research triggers. The common shape was discovered through iterative exploration of reaktiv/Signals, events-primary architecture, stream topology, and render primitives.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Producers                                               │
│  Scripts, hooks, collectors — anything that emits facts   │
│  Write via: FileWriter, ev Emitter, direct JSONL append  │
├─────────────────────────────────────────────────────────┤
│  The Log                                                 │
│  JSONL files. One file = one topic. Append-only.         │
│  The filesystem IS the broker.                           │
├─────────────────────────────────────────────────────────┤
│  Consumers                                               │
│  Tailer (offset-tracking reader) → Projection (fold)     │
│  In-process: Stream → direct fan-out (fast path)         │
│  Cross-process: file → Tailer → Projection (general)     │
├─────────────────────────────────────────────────────────┤
│  Display                                                 │
│  RenderApp checks Projection.version, paints on change   │
│  Cell-buffer TUI: Buffer+diff, styled composition        │
└─────────────────────────────────────────────────────────┘
```

**Two paths, same Projection interface:**

- **In-process** — Stream[T] fans out to consumers in the same event loop. Zero IO, synchronized.
- **Persistent** — Producer writes JSONL via FileWriter. Consumer uses Tailer to read, feeds Projection. Survives process boundaries. Tap in/out at will.

## Current State

### Framework (topology primitives)

| File | Type | Role |
|------|------|------|
| `stream.py` | Stream[T] | In-process typed fan-out |
| `projection.py` | Projection[S,T] | Fold events → state + version counter |
| `store.py` | EventStore[T] | In-memory append-only log (Consumer protocol) |
| `file_writer.py` | FileWriter[T] | JSONL append (producer side) |
| `tailer.py` | Tailer[T] | JSONL reader with offset tracking (consumer side) |
| `forward.py` | Forward[T,U] | Bridge between typed streams |

**The key pair: FileWriter + Tailer.** FileWriter appends typed events to a JSONL file. Tailer reads from a byte offset, returns new events on poll(). The file is the decoupling — producer and consumer don't know about each other. Tailer can replay from zero (catch up) or resume from checkpoint (tap in).

### Render (cell-buffer TUI engine)

Novel for Python. No curses dependency, pure ANSI. Performance: 7.3ms avg frame at 2800+ items.

- **Primitives:** Cell, Style, Buffer (width×height grid), BufferView, diff
- **Composition:** Block.text(), join_horizontal/vertical, pad, border, truncate
- **Components:** list_view, table, text_input, spinner, progress
- **App lifecycle:** RenderApp with update/render/on_key, adaptive sleep, SIGWINCH

### Apps

| App | What it does |
|-----|-------------|
| `apps/demo.py` | Progressive walkthrough of render layer |
| `apps/logs.py` | Streaming SSH log viewer |
| `apps/producer.py` | Simulates container events → writes JSONL |
| `apps/tail_dashboard.py` | Tails JSONL → Projection → live dashboard |

**producer + tail_dashboard** is the proof-of-concept: two processes communicating through a JSONL file. Producer writes, dashboard tails, replays history on start, follows live updates.

## Broader Ecosystem

| Package | Role | Relationship |
|---------|------|-------------|
| **ev** | Event vocabulary (Event, Result, Emitter protocol) | Defines the typed fact shape |
| **ev-toolkit** | CLI script harness (run, signal, lifecycle) | Producer pattern for scripts |
| **gruel.network/scripts** | Homelab tools (status, logs, media-audit) | Concrete producers |
| **tbd-v2** | Conversation analytics (ingest, FTS5, embeddings) | Cognitive context consumer |
| **experiments/framework** | Stream topology + Tailer | Routing + persistent consumption |
| **experiments/render** | Cell-buffer TUI | Display consumer |

**The full loop:**
```
ev-toolkit script (e.g. status-v2.py)
  → emits typed events via Emitter
    → FileWriter appends JSONL
      → Tailer reads in dashboard process
        → Projection folds → RenderApp displays
                           → also: persist, alert, forward
```

## What Was Learned

1. **Signals/reaktiv were wrong** — too fine-grained, too coupled, UI-oriented. Version counters + polling do the same job for event streams.

2. **Events are primary, state is derived** — append-only log is the truth. Current state = fold(events). This enables replay, filter, tee.

3. **The file IS the broker** — no need for message infrastructure. JSONL + byte offset = Kafka partition at personal scale. Tailer = consumer with offset tracking.

4. **Render layer was a side discovery** — emerged while replacing Rich. Novel for Python, useful, but orthogonal to the event infrastructure question.

5. **The pattern is universal** — same shape applies to homelab monitoring, work alerting, tool installs, meeting transcripts, research triggers. The "personal event bus" framing unifies them.

## In Flight

- **genesis docs** — subtask running: uses tbd to research prior conversations, produces `docs/genesis.md` (narrative history) and `docs/tbd-feedback.md` (tool feedback)

## Open Questions / Next Steps

1. **Log location convention** — Where do events of type X land? `~/.local/share/streams/{type}/`? Per-project `.events/`? Needs a decision.

2. **StreamEmitter** — Bridge from sync ev Emitter to async Stream (for in-process case). May not be needed if persistent path is primary — the file IS the decoupling.

3. **Checkpoint persistence** — Tailer tracks offset in memory. For restart-resilient consumers, offset should persist somewhere (dotfile? SQLite? sidecar `.offset` file?).

4. **The dashboard as ev consumer** — Can we tail a gruel.network script's output directly? `status-v2.py --record /tmp/status.jsonl` → dashboard tails it.

5. **The "scripts in panels" question** — Multiple producers, one dashboard with panels per stream. The render layer's spatial composition supports this; the wiring pattern needs design.

## Run

```bash
# Producer/consumer demo (two terminals)
uv run python -m apps.producer              # writes /tmp/events.jsonl
uv run python -m apps.tail_dashboard        # tails and renders

# Tests
uv run pytest tests/ -v                     # 49 tests, 0.04s

# Render demos
uv run python -m apps.demo
uv run python -m render.demo_app
```

## See Also

- `CLAUDE.md` — branching, subtask workflow, conventions
- `RETROSPECTIVE.md` — intellectual genealogy, what was proven, the void
- `docs/render-layer.md` — render layer reference
- `docs/genesis.md` — (pending) full narrative history via tbd research
