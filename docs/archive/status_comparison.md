# Status Script: Imperative vs Reactive Comparison

## The Key Architectural Shift

### BEFORE (Imperative) - status.py

```
┌─────────────────────────────────────────────────────────────┐
│                     StatusLiveEmitter                       │
│                                                             │
│   _results: dict[str, dict] ────────┐                      │
│   _progress: dict[str, dict] ───────┼──► _build_tree()     │
│                                     │         │            │
│   emit(event) ──► update state ─────┘         │            │
│                         │                      │            │
│                         └──► _update() ◄──────┘            │
│                                  │                          │
│                                  ▼                          │
│                           live.update()                     │
└─────────────────────────────────────────────────────────────┘

State changes → manual _update() call → rebuild tree → render
Events received → manually parsed → update state → manual _update()
```

**The code:**
```python
# In StatusLiveEmitter.emit()
def emit(self, event: Event) -> None:
    if event.is_signal and event.signal_name == "status.stack":
        stack = str(event.data.get("stack") or "unknown")
        self._results[stack] = dict(event.data)      # Update state
        self._progress.pop(stack, None)
        self._update()                                # ← MANUAL

    if event.is_signal and event.signal_name == "container.state":
        stack = str(event.data.get("stack") or "unknown")
        service = str(event.data.get("service") or "unknown")
        self._progress.setdefault(stack, {})[service] = dict(event.data)
        self._update()                                # ← MANUAL

# In the operation
emit_status(**data)                                   # ← MANUAL event emission
emit_container_state(**svc)                           # ← MANUAL event emission
```

**Pain points:**
1. Every state change needs a manual `_update()` call
2. Events are manually emitted at specific points
3. State is mutable dicts, easy to have inconsistencies
4. If you forget `_update()`, UI is stale
5. Emitter knows about signal names (`"status.stack"`, `"container.state"`)

---

### AFTER (Reactive) - status_reactive.py

```
┌─────────────────────────────────────────────────────────────┐
│                     State Layer (Signals)                   │
│                                                             │
│   stacks: Signal[dict[str, StackResult]]                   │
│   checking_services: Signal[dict[str, list]]               │
│                          │                                  │
│                          ▼                                  │
│              merged: Computed[dict[str, StackResult]]       │
│                          │                                  │
├──────────────────────────┼──────────────────────────────────┤
│                          ▼                                  │
│   ┌─────────────────────────────────────────────────────┐  │
│   │              UI Layer (Component)                    │  │
│   │   StatusTreeComponent.render() reads merged()        │  │
│   │                          │                           │  │
│   │                          ▼                           │  │
│   │              Effect(render) ───► live.update()       │  │
│   └─────────────────────────────────────────────────────┘  │
│                                                             │
│   ┌─────────────────────────────────────────────────────┐  │
│   │              Event Layer (Bridges)                   │  │
│   │   watch_notable(stacks, ...) ───► emit(Event)        │  │
│   │   watch_each(stacks, ...) ───► emit(Event)           │  │
│   └─────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘

Signal changes → Effect auto-runs → UI updates
Signal changes → Watcher auto-runs → Event emitted
```

**The code:**
```python
# State is Signals
stacks = Signal[dict[str, StackResult]]({...})

# UI reads Signals (dependency tracked automatically)
def render(self) -> Tree:
    stacks = self._stacks()  # ← Tracked read
    # ... build tree from stacks

# Effect auto-rerenders when stacks changes
rem.set_ui(tree_component.render)  # Effect created internally

# Events auto-emit when state matches criteria
rem.watch_notable(
    lambda: [r for r in stacks().values() if r.status == "unhealthy"],
    "status.unhealthy_stacks",
    is_notable=lambda lst: len(lst) > 0,
    to_data=lambda lst: {"count": len(lst), "stacks": [r.name for r in lst]},
)

# State update - that's it, no manual _update() or emit()
stacks.update(lambda s: {**s, name: result})
```

**Benefits:**
1. No manual `_update()` calls - Effects handle it
2. No manual event emission - Watchers handle it
3. State is immutable (frozen dataclasses)
4. Can't forget to update - it's automatic
5. Emitter doesn't know signal names - bridges are declarative

---

## Side-by-Side: Completing a Stack Check

### BEFORE (Imperative)

```python
# In _check_stack()
async def _check_stack(stack, ..., emitter):
    # ... do SSH, parse output ...

    # Emit events for each service (manual)
    for row in rows:
        svc = {...}
        emit_container_state(**svc)  # ← Manual event

    # Build result
    data = {"stack": stack, "status": status, ...}
    emit_status(**data)              # ← Manual event
    return data

# In StatusLiveEmitter.emit()
def emit(self, event):
    if event.signal_name == "status.stack":
        self._results[stack] = dict(event.data)
        self._update()               # ← Manual UI update
```

### AFTER (Reactive)

```python
# In check_one()
async def check_one(name: str):
    # Mark as checking (state change → UI auto-updates)
    stacks.update(lambda s: {**s, name: StackResult(name=name, status="checking")})

    # Services found during check (state change → UI auto-updates)
    def on_service(svc):
        checking_services.update(lambda cs: {**cs, name: [*cs.get(name, []), svc]})

    result = await check_stack_mock(name, on_service)

    # Mark as complete (state change → UI auto-updates, events auto-emit)
    stacks.update(lambda s: {**s, name: result})

# That's it. No manual emit(), no manual _update().
# The reactive system handles propagation.
```

---

## Code Comparison

| Aspect | Imperative (status.py) | Reactive (status_reactive.py) |
|--------|------------------------|-------------------------------|
| State | Mutable dicts | Immutable Signals |
| UI updates | Manual `_update()` | Automatic via Effect |
| Event emission | Manual `emit_*()` | Automatic via Watchers |
| Emitter coupling | Knows signal names | Decoupled (bridges) |
| Lines of emitter code | ~170 (StatusLiveEmitter) | ~50 (ReactiveEmitter) |
| State → UI flow | Imperative | Declarative |

---

## The Pattern

```
                    ┌─────────────┐
                    │   Signal    │
                    │  (source)   │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
              ▼            ▼            ▼
        ┌─────────┐  ┌─────────┐  ┌─────────┐
        │Computed │  │Computed │  │ Effect  │
        │  (UI)   │  │(derived)│  │(watcher)│
        └────┬────┘  └────┬────┘  └────┬────┘
             │            │            │
             ▼            │            ▼
        ┌─────────┐       │       ┌─────────┐
        │ Effect  │       │       │ Emitter │
        │(render) │       │       │  (ev)   │
        └────┬────┘       │       └─────────┘
             │            │
             ▼            ▼
        ┌─────────┐  ┌─────────┐
        │Terminal │  │ Result  │
        │  (Rich) │  │  data   │
        └─────────┘  └─────────┘
```

One source of truth (Signals), multiple automatic outputs (UI, Events, Result).

---

## What This Enables

1. **Testability**: Mock the Signals, assert on final state
2. **Consistency**: Can't have stale UI - updates are automatic
3. **Composition**: Components are just functions that read Signals
4. **Debugging**: State changes are traceable through the reactive graph
5. **Multiple outputs**: Same state drives UI, events, and result
