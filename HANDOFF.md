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

## Extraction (Complete)

Reusable components extracted to `cli_framework/` (214 lines total):

| Module | Component | Lines |
|--------|-----------|-------|
| `store.py` | `EventStore[T]` | 33 |
| `keyboard.py` | `KeyboardInput` | 47 |
| `filter.py` | `FilterHistory` | 30 |
| `app.py` | `Mode`, `BaseApp` | 104 |

Key design decisions:
- `BaseApp._render_dependencies()` hook lets subclasses declare reactive deps without managing Effect directly
- Effect creation deferred to `set_live()` to avoid init-ordering issues
- Filter *matching logic* stays domain-specific (only history management extracted)
- Verdict: **shared module, not framework**. The pattern knowledge matters more than code savings.

## Next Example: Process Manager

### Why this example?

Both dashboard and http_logger are **observe-only**—user watches events flow and filters views. Process Manager introduces **user-initiated actions** that mutate state.

| Aspect | Dashboard | HTTP Logger | Process Manager |
|--------|-----------|-------------|-----------------|
| Events | Independent | Correlated pairs | State transitions |
| User role | Observer + filter | Observer + select | **Actor** (start/stop/restart) |
| Data model | Flat events | Request→Response | Entity state machines |
| Key metric | Counts | Latency | Uptime, restart count |
| Time | Event timestamps | Derived latency | Duration in state |

### What it tests

1. **State machines** - Processes transition through states (stopped → starting → running → stopping → stopped/crashed)
2. **User actions** - Keypresses that cause side effects, not just filter views
3. **Per-entity log streams** - Each process has its own log tail
4. **Entity lifecycle** - Create, destroy, not just observe
5. **Action confirmation** - "Are you sure?" for destructive ops (new mode?)

### Questions to answer

1. **Actions vs. view-only:** How do user-triggered mutations interact with the reactive layer? Does the action just `signal.set()` and let Effect re-render, or is there more?
2. **Per-entity state:** Each process has its own state machine. Signal per process? Or single Signal containing all process states?
3. **Log streams:** Each process produces logs. One EventStore per process, or one shared store with process_id field?
4. **Confirmation patterns:** Stop/kill are destructive. How does confirmation mode interact with the existing Mode enum?

### Sketch

```python
class ProcessState(Enum):
    STOPPED = auto()
    STARTING = auto()
    RUNNING = auto()
    STOPPING = auto()
    CRASHED = auto()

@dataclass
class Process:
    pid: str
    name: str
    command: str
    state: ProcessState
    started_at: float | None
    restart_count: int

@dataclass(frozen=True)
class ProcessEvent:
    pid: str
    kind: Literal["state_change", "log", "metric"]
    payload: dict
    ts: float

# Computed from events:
process_states = Computed(lambda: ...)      # {pid: Process}
process_logs = Computed(lambda: ...)        # {pid: [log_lines]}
uptime = Computed(lambda: ...)              # {pid: duration} (live, like pending age)

# User actions (these ADD events, not just filter):
def start_process(pid): store.add(ProcessEvent(pid, "state_change", {"to": "starting"}))
def stop_process(pid): store.add(ProcessEvent(pid, "state_change", {"to": "stopping"}))
```

### Panes

| Pane | Type | Content |
|------|------|---------|
| **Process list** | List + live state | All processes with state, uptime, restart count |
| **Logs** | List (filtered) | Log output for selected/all processes |
| **Detail** | Detail | Selected process full info |
| **Actions** | New type | Available actions for selected process |

### Open design questions

- Should process definitions be static (config) or dynamic (user can add/remove)?
- How to render state transitions visually (color pulse? status column?)
- Log pane: tail -f style or scrollable history?

## Key Files

```
cli_framework/                     # Shared module (214 lines)
examples/dashboard.py              # Example 1: independent events (~780 lines)
examples/http_logger.py            # Example 2: correlated events (~990 lines)
examples/http_logger_v2.py         # Example 2 enhanced (~1400 lines)
examples/extract_demo.py           # Minimal cli_framework usage (~207 lines)
docs/interactive-cli-framework.md  # Pattern documentation
```
