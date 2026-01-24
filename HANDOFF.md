# Handoff: Render + Topology

## Summary

Two independent layers for building interactive terminal tools:

1. **`render/`** — Cell-buffer terminal rendering engine. Python equivalent of Ratatui (buffer+diff) + Lip Gloss (styled composition) + Bubbles (interactive components). Performance: 7.3ms avg frame at 2800+ items.

2. **`framework/`** — Typed event multiplexer. In-process stream processing with fan-in/fan-out. Sources emit events into Streams, Consumers receive them. The async equivalent of Unix `tee` + `grep` for typed events.

Layers are fully decoupled: `render/` has zero framework imports. `framework/` has zero render imports (except legacy debug pane).

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Apps (apps/)                                            │
│  extend RenderApp, read Projection.state, paint          │
├─────────────────────────────────────────────────────────┤
│  Render (render/)                                        │
│  Buffer, Cell, Style, Block, Line, Span                  │
│  Components: list_view, table, text_input, spinner        │
│  RenderApp: update/render/on_key at fps_cap              │
├─────────────────────────────────────────────────────────┤
│  Framework (framework/)                                  │
│  Stream[T]: typed async multiplexer (fan-in/fan-out)     │
│  Consumer[T]: protocol (async consume(event))            │
│  Projection[S,T]: fold events → state + version counter  │
│  EventStore[T]: persist + replay                         │
│  FileWriter[T]: JSONL recording                          │
│  Forward[T,U]: bridge between typed streams              │
└─────────────────────────────────────────────────────────┘
```

**Dependency structure:**
- `apps/` → `render/` only
- `render/` → nothing (zero imports, self-contained)
- `framework/` topology → nothing (Stream, Consumer, Projection, EventStore, FileWriter, Forward)
- `apps/` → `render/` + `framework/` topology

## Framework: Stream Topology

The core insight: EventStore is just one consumer, not the center. The Stream is the center.

```python
from framework import Stream, Consumer, Projection, EventStore, FileWriter, Forward

# Define your event type
@dataclass(frozen=True)
class HealthCheck:
    source: str
    stacks: dict[str, str]

# Create stream and attach consumers
stream: Stream[HealthCheck] = Stream()
stream.tap(store)                                       # persist
stream.tap(projection)                                  # fold → state
stream.tap(FileWriter(Path("log.jsonl"), serialize=asdict))  # record
stream.tap(webhook, filter=lambda e: "unhealthy" in e.stacks.values())

# Sources are just async functions that call emit
async def poll_health(stream: Stream[HealthCheck]):
    while True:
        result = await check_infrastructure()
        await stream.emit(HealthCheck(source="infra", stacks=result))
        await asyncio.sleep(30)

# Render reads projection state
class Dashboard(RenderApp):
    def update(self):
        if self._proj.version != self._last_version:
            self._last_version = self._proj.version
            self.mark_dirty()
    def render(self):
        state = self._proj.state  # plain value, no Signal
        # paint with render layer
```

### Core Primitives (3 types)

| Type | API | Role |
|------|-----|------|
| `Stream[T]` | `emit(event)`, `tap(consumer, filter?, transform?)`, `detach(tap)` | Fan-in/fan-out multiplexer |
| `Consumer[T]` | `async consume(event: T)` | Protocol — anything that eats events |
| `Tap[T]` | dataclass: consumer + filter + transform | Handle for detach |

### Battery Consumers

| Consumer | Role |
|----------|------|
| `Projection[S, T]` | Fold events → `.state` (value) + `.version` (counter). Also supports `advance(store)` for pull mode. |
| `EventStore[T]` | Append-only log. `.since(cursor)`, `.events`, `.version`. Optional JSONL persistence. |
| `FileWriter[T]` | Serialize to JSONL file. Takes path + serialize function. |
| `Forward[T, U]` | Transform and emit to another Stream. Bridges typed streams. |

### Design Constraints

- **No operator chains** — not Rx. No `stream.map().filter().merge()`.
- **No backpressure** — async/await naturally bounds.
- **No main loop ownership** — you own asyncio.
- **Sources are NOT a type** — just async functions that call `stream.emit()`.
- **No external reactivity library** — version counters, not Signals. Push topology handles invalidation.

## Render Layer

### Three-level composition vocabulary

- **Span** — styled text run (atom): `Span("text", Style(fg="cyan"))`
- **Line** — sequence of spans (workhorse, ~90%): `Line.plain("hello")`
- **Block** — 2D cell grid (escape hatch): borders, padding, joins

The paint boundary (Line.paint / Block.paint → BufferView) is where Cells get created — exactly once, in their final location.

### Components

Components accept `Line` for item content:

```python
items = [Line.plain(name) for name in names]
block = list_view(state, items, height, selected_style=Style(bg=237))

columns = [Column(header=Line.plain("Name"), width=12)]
rows = [[Line.plain("Alice")], [Line.plain("Bob")]]
block = table(state, columns, rows, height)
```

### RenderApp Lifecycle

```python
class MyApp(RenderApp):
    def layout(self, width, height): ...   # regions
    def update(self): ...                   # async state, mark_dirty()
    def render(self): ...                   # paint into self._buf
    def on_key(self, key): ...              # input handling
```

- Drains ALL available keys per frame
- Adaptive sleep: 1ms when keys/dirty, 33ms (1/fps) when idle

### Performance

7.3ms avg frame at 2800+ items (Line path). Profiling via `FrameTimer`, debug overlay with `d` key, `--profile PATH` for JSONL dump.

## Broader Context

This project exists within a larger ecosystem:

| Package | Role | Status |
|---------|------|--------|
| **ev** | Event vocabulary (Event, Result, Emitter) | Stable, frozen |
| **ev-toolkit** | CLI script harness (run, signal, detect_mode) | Stable |
| **framework/** (here) | Stream topology (fan-in/fan-out) | New — topology primitives done |
| **render/** (here) | Terminal display (buffer, composition, components) | Done |

**The conceptual model:**
- ev defines *what things are* (Event, Result, Emitter)
- framework routes *where things go* (Stream, Consumer, Tap)
- render determines *how things look* (Buffer, Line, Block)
- ev-toolkit is the *script harness* for fire-once CLI operations

**Positioned as:** a typed event multiplexer — the in-process equivalent of pub-sub with typed channels. Simpler than Rx (no operator zoo), more structured than Unix pipes (typed events, not bytes).

## Current State

| Component | Purpose |
|-----------|---------|
| `framework/stream.py` | **Stream, Consumer, Tap**: core topology primitives |
| `framework/projection.py` | **Projection**: fold events → state + version counter |
| `framework/store.py` | **EventStore**: append-only log, persistence, Consumer |
| `framework/file_writer.py` | **FileWriter**: JSONL recording Consumer |
| `framework/forward.py` | **Forward**: bridge between typed streams |
| `apps/demo.py` | Progressive demo — 7-stage walkthrough, animated finale |
| `apps/logs.py` | First real app — streaming SSH log viewer |
| `render/span.py` | Span + Line: description layer, paint boundary |
| `render/app.py` | RenderApp: adaptive sleep, drain-all-keys, lifecycle |
| `render/cell.py` | Cell, Style, EMPTY_CELL |
| `render/buffer.py` | Buffer, BufferView, diff |
| `render/writer.py` | ANSI output, Mode 2026, alt screen |
| `render/block.py` | Block, Wrap modes |
| `render/compose.py` | join_horizontal, join_vertical, pad, border, truncate |
| `render/components/` | list_view, table, spinner, progress, text_input |
| `render/keyboard.py` | KeyboardInput: cbreak, CSI/SS3, UTF-8 |
| `render/timer.py` | FrameTimer: profiling, debug overlay, JSONL dump |
| `render/theme.py` | Named style constants |
| `apps/` | Live apps using render layer + framework topology. |

## Known Contracts

### Subprocess stdin isolation
Any RenderApp that spawns subprocesses MUST use `stdin=asyncio.subprocess.DEVNULL`.

### Keyboard API
`KeyboardInput.get_key()` returns named strings (`"up"`, `"down"`, `"enter"`, etc.) or single characters. Escape sequences parsed atomically (5ms timeout), fully drained.

### Paint boundary
`Line.paint(view, x, y)` and `Block.paint(view, x, y)` create Cells. Style merge: span fields override Line's base style when non-None/non-False.

### Projection → Render bridge
No reactive Signals. Render loop checks `proj.version` each frame. If changed since last seen, `mark_dirty()` and repaint. State is just `proj.state` (a plain value).

## Next Steps

1. **First dashboard app** — Status pane using topology: Source (poll script) → Stream → Projection → RenderApp display.

2. **ev integration** — Connect ev-toolkit's Emitter output to framework's Stream. Emitter.emit() feeds stream.emit().

3. **Network consumers** — WebhookConsumer, SSE consumer, remote-terminal-forwarding consumer. These are just more Consumer implementations.

4. **Network consumers** — WebhookConsumer, SSE consumer, remote-terminal-forwarding consumer.

## Run

```bash
# Demo walkthrough (start here)
uv run python -m apps.demo

# Real apps
uv run python -m apps.logs infra --host 192.168.1.30 -i ~/.ssh/homelab_deploy

# Topology tests
uv run pytest tests/test_stream.py -v

# Render layer demos
uv run -m render.demo_app
uv run -m render.demo_components

# App demos
uv run apps/demo.py
```

## See Also

- `CLAUDE.md` — project conventions and branching workflow
- `docs/render-layer.md` — render layer reference (primitives, data flow, contracts)
- `docs/composition-journey.md` — profiling → Layer 3 design decisions
- `docs/composition-research.md` — Ratatui, Lip Gloss, Rich/Textual comparison
