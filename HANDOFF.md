# Handoff: Interactive CLI Framework

## Summary

Built an interactive CLI framework pattern using Rich + reaktiv. Two working examples validate the pattern generalizes across domains.

## Current State

| Example | Lines | Status |
|---------|-------|--------|
| `examples/dashboard.py` | ~780 | Complete - reference implementation |
| `examples/http_logger.py` | ~990 | Complete - validates pattern with correlation |
| `examples/http_logger_v2.py` | 1399 | Complete - enhanced with histogram, endpoints, sliding window |

## The Pattern (Validated)

```
EventStore
└── version: Signal ─────────────────────────┐
                                             │
App                                          │
├── ui_state: Signal ────────────────────────┤
├── ui_state: Signal ────────────────────────┼──► Effect ──► Live.update()
│                                            │
└── metrics: Computed ◄──────────────────────┘
```

**One notification system.** All state is Signals. One Effect triggers render.

## What We Learned (HTTP Logger)

### Pattern Generality

| Component | Dashboard | HTTP Logger | Reusable? |
|-----------|-----------|-------------|-----------|
| EventStore + version Signal | ✓ | ✓ identical | **Yes** |
| KeyboardInput | ✓ | ✓ identical | **Yes** |
| Mode enum | VIEW/FILTER/SOURCES | VIEW/FILTER | **Yes** |
| Effect-driven render | ✓ | ✓ identical | **Yes** |
| Filter with history | ✓ | ✓ same pattern | **Yes** |
| Layout (main/status/help) | ✓ | ✓ same structure | **Yes** |

### Domain-Specific Adaptations

| Component | Dashboard | HTTP Logger |
|-----------|-----------|-------------|
| Event shape | `Event(source, type, level)` | `HttpEvent(request_id, kind, status)` |
| Filter logic | `field=value`, glob | Added comparison ops (`latency>500`), status classes (`2xx`) |
| Computed metrics | counts by level/source | **correlation** (request→response), latency stats |

### Key Finding: Correlation in Computed

EventStore stayed unchanged. Correlation happens entirely in Computed:

```python
def _compute_completed(self) -> list[CompletedRequest]:
    requests: dict[str, HttpEvent] = {}
    for event in self.store.events:
        if event.kind == "request":
            requests[event.request_id] = event
        elif event.kind == "response" and event.request_id in requests:
            req = requests.pop(event.request_id)
            # Derive latency from two events
            completed.append(CompletedRequest(..., latency_ms=(event.ts - req.ts) * 1000))
```

### Pane Types Taxonomy

We discovered four distinct pane types:

| Type | Example | Data Source | Updates When |
|------|---------|-------------|--------------|
| **List** | Requests | Computed from events | Event added |
| **Aggregate** | Metrics | Computed from events | Event added |
| **Live State** | Pending | Events + `time.time()` | Continuous (render refresh) |
| **Detail** | Selected request | Selection index + list | Selection changes |

### Selection Pattern

```python
self._selected_index: Signal[int | None] = Signal(None)
self.selected_request = Computed(lambda: self._compute_selected_request())
```

- `j`/`k` navigate selection
- Filter changes clear selection (avoids stale index)
- Detail pane replaces pending pane when selected
- Viewport scrolls to keep selection visible

## reaktiv Primitives

| Primitive | Role |
|-----------|------|
| `Signal` | Mutable state (version counter, UI state, selection) |
| `Computed` | Derived values (metrics, correlation, filtered lists) |
| `Effect` | Side effects (render to terminal) |

## V2 Improvements (Complete)

`http_logger_v2.py` adds:

1. **Latency histogram pane** - ASCII bar chart (`l` key)
2. **Endpoint breakdown pane** - per-path stats (`b` key)
3. **Sliding window metrics** - all time vs last 60s (`w` key)
4. **Enhanced percentiles** - p50, p90, p99
5. **Request rate** - req/sec over 10s window
6. **Filter enhancements** - `age>1000`, `id=*pattern*`
7. **Scroll indicators** - "↑ 5 more" / "↓ 12 more"
8. **Help overlay** - `?` key shows all shortcuts

## Run

```bash
# Dashboard
uv run examples/dashboard.py
# Keys: 1/2=pane  /=filter  e=errors  s=sources  t=tee  q=quit

# HTTP Logger
uv run examples/http_logger.py
# Keys: 1/2/3=pane  j/k=select  /=filter  e=errors  s=slow  p=pending  q=quit

# HTTP Logger v2 (enhanced)
uv run examples/http_logger_v2.py
# Keys: ?=help  l=histogram  b=breakdown  w=window  (plus all v1 keys)
```

## Next Steps

1. **Extract reusable components** - EventStore, KeyboardInput, base Filter could be a shared module
2. **Third example** - Build watcher (hierarchical state) or queue monitor (gauges/thresholds)
3. **Pattern documentation** - update `docs/interactive-cli-framework.md` with findings

## Key Files

```
examples/dashboard.py              # Reference implementation (~780 lines)
examples/http_logger.py            # Correlation validation (~990 lines)
examples/http_logger_v2.py         # Enhanced version (~1400 lines)
docs/interactive-cli-framework.md  # Pattern documentation
```
