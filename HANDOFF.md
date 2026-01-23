# Handoff: Context Observability Primitive

## Summary

Event-sourced reactive TUI pattern using Rich + reaktiv. Framework (`framework/`, ~500 lines) with persistence, debug tooling, simulator base, and debounced rendering. Profiling infrastructure validates performance characteristics. Pattern proven across domains; now focused on profiling/debug as the development workbench.

## Current State

| Component | Lines | Purpose |
|-----------|-------|---------|
| `framework/store.py` | ~80 | EventStore with JSONL persistence, persistent file handle |
| `framework/app.py` | ~115 | BaseApp, debounced render Effect, main loop |
| `framework/debug.py` | ~140 | DebugPane (metrics, rate control, pluggable actions) |
| `framework/sim.py` | ~140 | BaseSimulator (lifecycle, auto-restart, rate-aware crash) |
| `framework/instrument.py` | ~150 | Metrics collector (counters, timings, gauges) |
| `framework/keyboard.py` | ~47 | KeyboardInput |
| `framework/filter.py` | ~30 | FilterHistory |

| Example | Domain |
|---------|--------|
| `examples/dashboard.py` | Independent event aggregation |
| `examples/http_logger.py` | Correlated request/response pairs |
| `examples/http_logger_v2.py` | Same, enhanced |
| `examples/process_manager.py` | State machines + user actions + debug pane |

## The Pattern

```
EventStore (append-only log, optional JSONL persistence)
└── version: Signal ─────────────────────────┐
                                             │
App                                          │
├── ui_state: Signal (mode, filter, etc) ───┤
├── tick: Signal (periodic, for live state) ─┼──► Effect (marks dirty)
│                                            │         │
│                                            │    main loop (20fps)
│                                            │         │
└── derived: Computed ◄──────────────────────┘    render() ──► Live.update()
    (evaluates lazily at frame rate,                  ▲
     NOT at event rate)                               │
                                              Computeds evaluate here
```

Critical insight: `_render_dependencies()` reads only Signals, never Computeds. Computeds evaluate lazily in `render()`. This means Computeds run at frame rate (~20fps) regardless of event rate (tested to 80k events/sec).

## Performance Profile

Benchmarks in `bench/`:

| Metric | Value | Source |
|--------|-------|--------|
| Computed scaling | O(n), budget-breaking at ~500k events | `computed_scaling.py` |
| Max throughput (lazy Computeds) | ~80k events/sec | `integration.py` |
| Effect fires per frame | 500-4000x at high load (all just set dirty flag) | `integration.py` |
| Rich rendering | 7ms at 1000 rows (not a bottleneck) | `system_profile.py` |
| Memory | ~0.4 KB/event, never freed | `system_profile.py` |
| Persistence I/O (persistent handle) | ~820k writes/sec | `system_profile.py` |

Framework self-instruments via `framework/instrument.py` (zero-cost when disabled).

## What Was Proven

1. **Actions are just events.** User-triggered mutations add to the same EventStore.
2. **Per-entity state machines fall out naturally.** Shared store, Computed scans and groups.
3. **Composability via addition.** New features = new Computed + new pane. No refactoring.
4. **Framework generality.** Four examples, zero framework changes needed.
5. **Debounced lazy evaluation.** Effect fires per-event but Computeds evaluate per-frame. 26x throughput improvement over naive approach.
6. **Persistence/replay works.** Quit → restart → state reconstructed from event log.

## Deferred Roadmap

| Priority | Item | Depends on | Notes |
|----------|------|-----------|-------|
| 1 | **Widget primitives** | — | Sparkline, Temperature, Metric. First consumer: debug pane |
| 2 | **Incremental Computed** | Widgets (for observability) | Fold pattern: Computed carries state, processes only new events |
| 3 | **Windowed retention** | Incremental Computed | Evict old events, cap memory. Can't evict if Computed needs full history |
| — | **Real data sources** | Any of above | Actual subprocess/log/queue. Lateral move, same pattern |
| — | **Pane DSL** | Widgets | Declarative pane composition. Debug pane = first customer |

## Development Workbench

The debug pane is both product and forge:
- **Profiling infrastructure** (`bench/`, `framework/instrument.py`) — offline characterization
- **Debug pane** — live observability, runtime controls, rate adjustment
- **Simulator** (`framework/sim.py`) — configurable data source for iteration
- Development loop: add primitive → use in debug pane → profile → validate

## Run

```bash
uv run examples/process_manager.py    # Press D for debug pane, +/- for rate

# Benchmarks
uv run bench/computed_scaling.py
uv run bench/system_profile.py
uv run bench/integration.py
```

## Key Files

```
framework/                         # Framework (~500 lines)
├── store.py                       # EventStore + persistence
├── app.py                         # BaseApp + debounced render
├── debug.py                       # DebugPane (dev tool)
├── sim.py                         # BaseSimulator
├── instrument.py                  # Metrics collector
├── keyboard.py                    # KeyboardInput
└── filter.py                      # FilterHistory

bench/                             # Profiling infrastructure
├── computed_scaling.py            # Computed O(n) characterization
├── system_profile.py              # Fan-out, Rich, memory, I/O
└── integration.py                 # Full pipeline under load

examples/                          # Domain examples
├── dashboard.py                   # Independent events
├── http_logger.py                 # Correlated events
├── http_logger_v2.py              # Enhanced
└── process_manager.py             # State machines + debug pane
```

## See Also

`RETROSPECTIVE.md` contains the intellectual history, void analysis, and context systems architecture.
