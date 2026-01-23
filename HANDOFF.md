# Handoff: Event-Sourced Reactive CLI Framework

## Summary

Event-sourced reactive TUI framework using Rich + reaktiv. Framework (`framework/`) with persistence, debug tooling, simulator base, debounced rendering, incremental projections, and reusable render helpers. Baseline profiling snapshot captured. Currently iterating on M3 (UI primitives).

## Milestone Status

| Milestone | Status | Notes |
|-----------|--------|-------|
| M0: Consolidate pattern | **Done** | All examples on BaseApp, impure Computeds fixed, batch everywhere |
| M2: Projections | **Done** | `Projection` base class, `store.since()`, retention via watermark |
| M3: UI primitives | **Active** | Render helpers extracted, filter handler in BaseApp, iterating |
| M4: Real tool adapters | Not started | Subprocess, file tailer, HTTP capture |
| M5: Docs + releases | Partial | Reactive contracts + projections docs done, roadmap exists |
| M6: Package MVP | Not started | pyproject.toml, src/ layout, tests, CI (deferred) |

See `ROADMAP.md` for full milestone details.

## Current State

| Component | Purpose |
|-----------|---------|
| `framework/store.py` | EventStore with JSONL persistence, `since(n)`, `evict_below(n)` |
| `framework/app.py` | BaseApp: render loop, projection registry, filter handler |
| `framework/projection.py` | Projection base class (incremental fold over events) |
| `framework/ui.py` | Render helpers: `app_layout`, `focus_panel`, `event_table`, `metrics_panel`, `help_bar`, `status_parts` |
| `framework/debug.py` | DebugPane (metrics, rate control, pluggable actions) |
| `framework/sim.py` | BaseSimulator (lifecycle, auto-restart, rate-aware crash) |
| `framework/instrument.py` | Metrics collector (counters, timings, gauges) |
| `framework/keyboard.py` | KeyboardInput |
| `framework/filter.py` | FilterHistory |

## The Pattern

```
EventStore (append-only log, optional JSONL persistence)
├── version: Signal ─────────────────────────┐
│                                             │
│   store.since(cursor) → new events          │
│         │                                   │
│         ▼                                   │
│   Projection.advance()                      │
│     apply(state, e1), apply(state, e2)...   │
│     state.set(accumulated)                  │
│         │                                   │
App       │                                   │
├── ui_state: Signal (mode, filter, etc) ────┤
├── projections: [registered] ───────────────┤
│         │                                   │
│    frame tick (20fps):                      │
│      1. advance projections                 │
│      2. render() reads .state + Computeds   │
│      3. live.update(layout)                 │
│                                            │
└── Effect (reads Signals → marks dirty) ────┘

Render helpers (framework/ui.py):
  app_layout(main, status, help) → Layout
  focus_panel(content, title, focused) → Panel
  event_table(rows, columns, max_rows) → (Table, ScrollInfo)
  metrics_panel(sections) → Text
  help_bar(bindings) → Text
  status_parts(*parts) → Text
```

## Key Contracts

See `docs/reactive-contracts.md` for full rationale.

1. Effects establish dependencies, not workload (just set dirty flag)
2. Computeds evaluate at frame rate, not event rate
3. `_render_dependencies()` reads only Signals, never Computeds
4. Computeds are pure (no mutation, no I/O)
5. Batch multi-Signal mutations with `batch()`
6. Projections advance at frame rate (O(new) not O(all))
7. Retention: `min(cursor)` watermark, `store.evict_below(n)`

## Baseline Performance

Snapshot: `bench/results/snapshots/baseline.md` (git SHA `9823e35`)

| Metric | Value |
|--------|-------|
| Pipeline throughput | ~210k events/sec |
| Render (1000 rows) | 7ms |
| Computed scaling (500k) | 107ms (O(n), breaks frame budget) |
| Memory | 0.41 KB/event |
| Persistence I/O | ~830k writes/sec (batched) |

Compare against baseline: `uv run bench/snapshot.py --name current --seed 0 --compare baseline`

## M3 Status: UI Primitives

**Done:**
- `framework/ui.py` — 6 render helpers + `ColumnSpec`/`ScrollInfo` types
- `BaseApp._handle_filter_key()` — shared filter keyboard handler
- `examples/dashboard.py` — migrated to use all helpers (proof of concept)

**What's left (domain-specific, per-app):**
- Column definitions + row styling logic
- Filter parser (domain-specific field names/syntax)
- Pane visibility conditions
- Metrics section categories
- Mode enums beyond VIEW/FILTER

**Framing:** After extraction, an app is a BaseApp subclass that provides schema (columns, filter, modes) + projections. The framework handles rendering mechanics, keyboard plumbing, and projection lifecycle.

## Run

```bash
uv run examples/process_manager.py    # Press D for debug pane, +/- for rate
uv run examples/dashboard.py          # Multi-source event aggregation

# Benchmarks
uv run bench/snapshot.py --name current --seed 0 --compare baseline
uv run bench/harness.py --scenario narrow --profile narrow_high_rate
```

## Key Files

```
framework/
├── store.py                       # EventStore + persistence + since() + evict_below()
├── app.py                         # BaseApp + render loop + projection registry + filter handler
├── projection.py                  # Projection base class (incremental fold)
├── ui.py                          # Render helpers (pure functions → Rich renderables)
├── debug.py                       # DebugPane (dev tool)
├── sim.py                         # BaseSimulator
├── instrument.py                  # Metrics collector
├── keyboard.py                    # KeyboardInput
└── filter.py                      # FilterHistory

bench/
├── snapshot.py                    # Unified bench suite runner
├── harness.py                     # Parameterized reactive pipeline bench
├── profiles.py                    # Scenario profiles
├── scenarios.py                   # Event shape scenarios
├── computed_scaling.py            # Computed O(n) characterization
├── system_profile.py              # Fan-out, Rich, memory, I/O
└── results/snapshots/             # Saved baselines

examples/                          # Domain examples (all on BaseApp)
├── dashboard.py                   # Independent events (uses render helpers)
├── http_logger.py                 # Correlated events
├── http_logger_v2.py              # Enhanced
├── extract_demo.py                # EventStore + KeyboardInput demo
└── process_manager.py             # State machines + projections + debug pane

docs/
├── reactive-contracts.md          # Reactive contracts (what goes where and why)
└── projections.md                 # Projection primitive (M2)
```

## See Also

- `ROADMAP.md` — full milestone plan with deliverables and work items
- `RETROSPECTIVE.md` — intellectual history, void analysis, context systems architecture
- `docs/reactive-contracts.md` — Signal vs Computed vs Effect vs Projection
- `bench/results/snapshots/baseline.md` — baseline performance numbers
