---
status: completed
updated: 2026-01-02
---

# Core Contract v1

Implement the minimal viable ev contract: types with immutability, serialization, and the Emitter protocol with a reference implementation.

## Understanding Summary

### What ev Is
- A semantic contract layer between CLI domain logic and renderers
- Five event kinds (log, progress, artifact, metric, input) — frozen, no new kinds without proving necessity
- Result as the authoritative verdict of a run
- "Facts not instructions" — events describe what happened, renderers decide presentation

### Design Decisions Made
1. **Immutability**: Level 1 (copy + MappingProxyType) — effectively immutable, ~50ns overhead per event
2. **Emitter**: Protocol-based, not type aliases — more explicit, better discoverability
3. **Naming**: `finish()` not `complete()` — avoids confusion with futures
4. **Serialization**: `to_dict()`/`from_dict()` — structural conversion only, renderers handle further transforms

### Invariants
- `emit()` called zero or more times
- `finish()` called exactly once
- No `emit()` after `finish()`

## Scope

### In Scope
1. **Event** — update with copy+proxy immutability, add `to_dict()`/`from_dict()`
2. **Result** — update with copy+proxy immutability, add `to_dict()`/`from_dict()`
3. **Emitter** — Protocol with `emit(Event)` and `finish(Result)`
4. **ListEmitter** — Reference implementation, collects transcript, enforces invariants
5. **NullEmitter** — No-op sink (optional, include if trivial)

### Out of Scope (for this plan)
- Renderers (JSON, Rich, Plain) — separate plan
- Async variants
- Event correlation/IDs
- Deep immutability (Level 2)

## Implementation

### File Structure
```
src/ev/
├── __init__.py      # Public API: Event, Result, Emitter, ListEmitter
├── types.py         # Event, Result (updated)
├── emitter.py       # Emitter Protocol, ListEmitter, NullEmitter
└── py.typed
```

### Step 1: Update Event with immutability + serialization

**Changes to `types.py`:**
- Add `__post_init__` to wrap `data` in `MappingProxyType(dict(...))`
- Add `to_dict()` method (unwraps proxy)
- Add `from_dict()` classmethod

**Tests:**
- Existing tests still pass
- New: mutation of original dict doesn't affect event
- New: direct mutation of event.data raises TypeError
- New: `to_dict()` returns plain dict
- New: `from_dict()` round-trips correctly

### Step 2: Update Result with immutability + serialization

**Same pattern as Event:**
- `__post_init__` wraps both `data` and `meta`
- `to_dict()` / `from_dict()`

**Tests:**
- Mirror Event tests for Result

### Step 3: Add Emitter Protocol

**New file `emitter.py`:**
```python
from typing import Protocol
from ev.types import Event, Result

class Emitter(Protocol):
    def emit(self, event: Event) -> None: ...
    def finish(self, result: Result) -> None: ...
```

**Tests:**
- Protocol is structural (any object with emit/finish satisfies it)

### Step 4: Add ListEmitter

**In `emitter.py`:**
```python
class ListEmitter:
    """Reference emitter that collects events and result."""

    def __init__(self) -> None:
        self.events: list[Event] = []
        self.result: Result | None = None
        self._finished: bool = False

    def emit(self, event: Event) -> None:
        if self._finished:
            raise RuntimeError("Cannot emit after finish()")
        self.events.append(event)

    def finish(self, result: Result) -> None:
        if self._finished:
            raise RuntimeError("finish() already called")
        self._finished = True
        self.result = result
```

**Tests:**
- Collects events in order
- Stores result
- Raises on emit after finish
- Raises on double finish

### Step 5: Add NullEmitter (if trivial)

```python
class NullEmitter:
    """No-op emitter for when you don't care about events."""

    def emit(self, event: Event) -> None:
        pass

    def finish(self, result: Result) -> None:
        pass
```

**Tests:**
- Accepts events without error
- Satisfies Emitter protocol

### Step 6: Update exports

**In `__init__.py`:**
```python
from ev.types import Event, Result
from ev.emitter import Emitter, ListEmitter, NullEmitter

__all__ = ["Event", "Result", "Emitter", "ListEmitter", "NullEmitter"]
```

## Verification

```bash
uv run pytest                  # All tests pass, 100% coverage
uv run ruff check .            # No lint errors
uv run ruff format --check .   # Formatted
```

## Decisions

1. **ListEmitter query methods** — Keep minimal for v1 (just `.events` and `.result`). Add queries later if we feel the pain.
2. **NullEmitter state tracking** — Truly no-op, no invariant enforcement. If you're using NullEmitter you don't care.

## Success Criteria

- [x] Event is effectively immutable (copy + proxy)
- [x] Result is effectively immutable (copy + proxy)
- [x] `to_dict()`/`from_dict()` round-trip correctly
- [x] Emitter Protocol defined
- [x] ListEmitter enforces invariants
- [x] 100% test coverage maintained
- [x] All checks pass
