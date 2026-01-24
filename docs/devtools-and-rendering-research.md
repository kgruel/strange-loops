# Research: DevTools, Instrumentation, and Rendering

Session research on debug panel design, instrumentation patterns, and rendering architecture.

## DevTools Patterns Across Frameworks

### The Universal Split

Every framework separates **vital signs** (minimal, embedded) from **deep inspection** (separate surface):

| Framework | Vital signs | Deep inspection | Separation |
|-----------|-------------|-----------------|------------|
| Flutter | 2-bar overlay (UI + raster thread) | Separate browser window | Engine-painted overlay |
| React | Nothing in-app | Component tree + profiler | Browser drawer |
| Redux | Action list (event stream) | State diffs, time-travel | Browser drawer |
| Textual | Nothing (TUI constraint) | Event log in separate terminal | Separate process (WebSocket) |
| Vue | Component tree | Timeline, dependency graph | Browser drawer |

### Key Insight

For event-sourced systems (Redux, our framework), the natural primary debugging axis is the **event stream** with state diffs — not component trees or widget inspectors.

### Our Approach (Decided)

- **Vital signs overlay** (D toggle): frame budget bar, event rate. Minimal, one-glance.
- **Deep inspection**: future full-screen debug mode — event stream, projection state diffs, timing breakdown.
- **Instrumentation core**: Metrics (counters, timings, gauges, windowed rates, timing samples) is the foundation all surfaces consume.

## Instrumentation: What We Instrument

### Framework-Level (must-have, implemented)

| Metric | Type | Location |
|--------|------|----------|
| Frame budget | timing("render") | app.py |
| Frame breakdown | timing("projections") vs timing("render") | app.py |
| Projection advance time | timing("proj.{name}.advance") | projection.py |
| Events folded per projection | count("proj.{name}.events_folded") | projection.py |
| Projection cursor lag | gauge("proj.{name}.lag") | app.py |
| Store size | gauge("store_size") | store.py |
| Persistence write time | timing("store_write") | store.py |
| Effect fires | count("effect_fires") | app.py |
| Frames rendered | count("frames_rendered") | app.py |
| Events added | count("events_added") | store.py |
| RSS | gauge("rss_mb") | debug.py |
| Debounce ratio | derived: effect_fires / frames_rendered | debug.py |

### Nice-to-have (causality, not yet implemented)

- Dirty trigger source (which Signal changed)
- Computed evaluation count per frame
- Signal write frequency (which are noisy)

### Deferred (need time-series primitives first)

- Event type distribution
- Store growth rate trends
- Dependency graph visualization

## UI Primitives (Greenhouse)

Born through debug panel needs, available to all apps:

| Primitive | Location | Purpose |
|-----------|----------|---------|
| `compact_bar(value, max, width, thresholds)` | framework/ui.py | Horizontal fill gauge |
| `sparkline(values, width, max_value)` | framework/ui.py | Time-series micro-chart (Unicode blocks) |

## Rendering Architecture Comparison

### The Pipeline

Every TUI system: State → Frame description → Terminal bytes → Display

### How Each Splits It

| System | Frame unit | Diffing | Output |
|--------|-----------|---------|--------|
| Rich Live | Rich renderables | None (full overwrite) | Cursor-home + rewrite |
| Textual | Segments → compositor | Region-based (render map diff) | Mode 2026, single write |
| Bubbletea | String | Line-by-line | Minimal line rewrites |
| Ratatui | Cell buffer (2D grid) | Cell-by-cell | Minimal cell writes |

### Our Current Stack

```
State:  EventStore → Projections → Signals → Computeds  (ours)
Frame:  Rich renderables (Table, Panel, Layout)           (Rich)
Write:  Live.update() → internal thread → full overwrite  (Rich Live)
```

### Decision: Stay on Rich Live

Value is in the state layer (event sourcing + signals + projections), not rendering.
Rich Live is adequate. Upgrade path if needed: own the output, use Rich only for frame building.

### Textual's Key Rendering Innovations

1. **Idle-gated timer** — render timer paused when clean, resumed on dirty (zero CPU when idle)
2. **Spatial map** — grid-based acceleration for visibility culling (O(1) regardless of widget count)
3. **Render map diffing** — symmetric difference of dict.items() for changed regions (C-level set ops)
4. **Mode 2026** — synchronized output for atomic frame display
5. **Single stdout write** — accumulate entire frame, write once
6. **Compositor** — handles overlapping regions, z-order, occlusion

### What Our Framework Does Better Than Textual

1. **Version-counter invalidation** — explicit change detection vs Textual's "invalidate all computes"
2. **Event sourcing** — append-only log, replay, incremental projections (Textual has nothing comparable)
3. **Lightweight** — no per-widget asyncio tasks, no CSS engine, no DOM

## Idle-Gated Rendering (Subtask in progress)

Switch from `asyncio.sleep(0.05)` polling to `asyncio.Event`-based wake-on-dirty.
Matches Textual's approach: zero CPU when idle, immediate response on state change.
