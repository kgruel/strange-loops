# Handoff: Interactive CLI Framework

## Summary

Built an interactive CLI framework pattern using Rich + reaktiv. The dashboard example demonstrates streaming data, multiple panes, filtering, and derived metrics—all with a pure reactive architecture.

## Current Focus

**Validating pattern generality** with a second example: HTTP request logger.

The dashboard proved the pattern works. Now we need to test it on a different domain to identify what's truly reusable vs dashboard-specific.

## Key Artifacts

```
examples/dashboard.py              # Reference implementation (~750 lines)
docs/interactive-cli-framework.md  # Pattern documentation
```

## The Pattern

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

## reaktiv Primitives

| Primitive | Role |
|-----------|------|
| `Signal` | Mutable state (version counter, UI state) |
| `Computed` | Derived values (metrics, aggregations) |
| `Effect` | Side effects (render to terminal, write to file) |

## Version Signal Pattern

```python
class EventStore:
    def __init__(self):
        self._events: list[Event] = []
        self.version = Signal(0)

    def add(self, event: Event) -> None:
        self._events.append(event)           # O(1)
        self.version.update(lambda v: v + 1) # O(1)
```

## Next Example: HTTP Request Logger

### Why this example?

| Aspect | Dashboard | HTTP Logger |
|--------|-----------|-------------|
| Event shape | Single event | Paired (request → response) |
| Key metric | Counts by level/source | Latency, status codes |
| Time relationship | Independent events | Correlated by request ID |
| Filtering | level=error | status=5xx, path=/api/* |

### Questions to answer

1. **Correlated events:** Request and response are separate but linked. How does this affect EventStore?
2. **Computed latency:** Response time is derived from two events. Does Computed handle this cleanly?
3. **Different panes:** Request list, response detail, latency histogram? What layout emerges?
4. **Filtering:** By status code, path pattern, latency threshold. Same FilterQuery or new?

### Sketch

```python
@dataclass
class HttpEvent:
    request_id: str
    kind: Literal["request", "response"]
    method: str
    path: str
    status: int | None  # None for request
    ts: float
    headers: dict
    body_size: int

# Computed: match requests to responses, calculate latency
pending_requests = Computed(lambda: ...)  # requests without response
completed_requests = Computed(lambda: ...)  # request+response pairs with latency
avg_latency = Computed(lambda: ...)
status_counts = Computed(lambda: ...)  # {200: 45, 404: 3, 500: 2}
```

### Other candidates considered

| Example | What it tests | Why not first |
|---------|---------------|---------------|
| File tail | Single stream, search | Too similar to dashboard |
| Build watcher | Hierarchical state | More complex, do later |
| Git log viewer | Static data, navigation | Not streaming |
| Queue depth monitor | Gauges, thresholds | Numeric focus only |

## Run

```bash
# Dashboard
uv run examples/dashboard.py

# Keys: 1/2=pane  /=filter  e=errors  s=sources  t=tee  q=quit
```

## Archived

- Previous exploration docs: `docs/archive/`
- Previous examples: `examples/archive/`
