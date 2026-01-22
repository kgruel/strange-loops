# Reaktiv Codebase - Code-Only Analysis

## Architecture Overview

Reaktiv is a fine-grained reactive state management library built on an **edge-based directed graph** for automatic dependency tracking. It consists of 13 core modules implementing a Signal-based reactive system inspired by Angular Signals and SolidJS.

---

## Core Module Breakdown

### 1. graph.py - Reactive Graph Core

- **Edge Structure**: Doubly-linked edges connecting producers (Signals) to consumers (Effects/ComputeSignals)
- **Global State**: `active_consumer` (contextvars), `global_version`, `batch_depth`, `batched_effect_head`
- **Bit Flags**: RUNNING, NOTIFIED, OUTDATED, DISPOSED, HAS_ERROR, TRACKING
- **Key Functions**: `add_dependency()`, `prepare_sources()`, `cleanup_sources()`, `needs_to_recompute()`
- The cleanup mechanism is sophisticated: sources marked with `version == -1` are unsubscribed

### 2. signal.py - Signal Hierarchy

Three signal types:

**Signal[T]**: Writable base signal with optional custom equality check
- `get()` creates dependency edges
- `set()` checks equality, bumps version, notifies targets
- `_set_internal()` handles actual mutation and target notification
- Creates RLock if thread safety enabled
- `as_readonly()` returns cached ReadonlySignal wrapper

**ReadonlySignal[T]**: Thin wrapper exposing only `get()`/`__call__()`
- Cached on Signal to ensure reference equality

**ComputeSignal[T]**: Lazy computed signal, extends Signal, implements consumer protocol
- Only computes on access, caches result
- Thread-local `_thread_local.is_running` flag for cycle detection
- `_refresh()` algorithm: Check cycle → Fast path (cached) → Prepare sources → Execute function under active_consumer context → Cleanup sources → Check equality → Bump version only if changed
- Sticky errors: HAS_ERROR flag persists until successful recompute
- Lazy subscription: Subscribes to sources only when first watched

### 3. effect.py - Side Effect System

- Implements consumer protocol for side effects
- Runs immediately and re-runs when dependencies change
- **Dual Mode**:
  - Sync: Inspects signature, passes `on_cleanup` callback or accepts return value
  - Async: Marked via `asyncio.iscoroutinefunction()`, prevents concurrent runs with `_executing` flag
- **Lifecycle**: Init → notify() → enqueue → batch_depth 0 triggers flush
- Cleanup supports both return function and on_cleanup parameter
- Creates asyncio task with done callback to prevent "pending task" warnings
- Garbage collection aware: requires reference retention

### 4. scheduler.py - Batching & Effect Flushing

- **Batch Context**: `batch_depth` counter with early return if > 0
- **Deferred Queue**: `_deferred_computed_queue` for ComputeSignal recomputations
  - Deduplicates by id(comp)
  - Preserves order of last occurrence
  - Processes in reverse (FIFO)
- **Effect Flush Loop**: Cycle guard with MAX_BATCH_ITERATIONS = 100
- **Enqueueing**: LIFO linked list via `_next_batched_effect`
- Effects only run when batch_depth reaches 0

### 5. linked.py - LinkedSignal (Writable Computed)

- Extends ComputeSignal, implements both producer and consumer
- **Two Patterns**:
  1. Simple: `LinkedSignal(lambda: source())`
  2. Advanced: `LinkedSignal(source=signal, computation=func)` with `PreviousState`
- **PreviousState**: Container with `value` (previous LinkedSignal value) and `source` (previous source value)
- Manual `set()` holds value until source changes, then recomputes
- `_set_internal()` bypass allows mutation despite ComputeSignal immutability
- Advanced pattern uses `untracked()` inside computation to prevent extra dependencies

### 6. context.py - Untracked Execution

- **Dual Interface**: Context manager or function wrapper
- Sets `active_consumer` to None temporarily
- Prevents dependency edges from forming
- Critical for LinkedSignal computation function

### 7. resource.py - Async Resource Management

- **Status Enum**: IDLE, LOADING, RELOADING, RESOLVED, ERROR, LOCAL
- Requires running asyncio event loop (`asyncio.get_running_loop()`)
- Uses ComputeSignal for params, Signal for state (value, error, status, is_loading)
- **Watch Pattern**: Effect monitors param changes, triggers `_start_load()`
- **Cancellation**: Uses `asyncio.Event()` not `task.cancel()`
- Loader can check `cancellation.is_set()` for graceful exit
- Task callback consumes result, `__del__` cleanup
- Properties expose: `value`, `error`, `is_loading`, `status`, `snapshot()`
- Methods: `reload()`, `set()`, `update()`, `destroy()`

### 8. thread_safety.py - Global Thread Safety Configuration

- Default enabled: `_THREAD_SAFETY_ENABLED = True`
- Signal/ComputeSignal: Creates `threading.RLock()` if enabled
- Signal: Protects `get()` and `_set_internal()`
- ComputeSignal: `_thread_local` for cycle detection, locks `_refresh()`
- Thread-local `is_running` flag prevents circular dependencies per thread

### 9. protocols.py - Type Protocols

- **ReadableSignal[T]**: `__call__() -> T`, `get() -> T` (covariant T)
- **WritableSignal[T_inv]**: Extends Readable, adds `set()` and `update()` (invariant T_inv)
- **DependencyTracker**: `add_dependency(signal) -> None`
- **Subscriber**: `notify() -> None`

### 10. utils.py - Utility Functions

- **to_async_iter()**: Converts signal to async iterator
  - Creates Effect pushing values to asyncio.Queue
  - `initial=True` yields current value immediately
  - `initial=False` skips first value, only yields on changes
  - Disposes effect in finally block

### 11. _debug.py - Debug Logging

- Global `_debug_enabled` flag
- `debug_log()` prints "[REAKTIV DEBUG]" prefix if enabled
- Used throughout for tracing execution

### 12. types.py - Type Definitions (lightweight)

### 13. __init__.py - Public API

Exports: Signal, ReadonlySignal, ComputeSignal, Computed, LinkedSignal, Linked, PreviousState, Effect, untracked, batch, to_async_iter, Resource, ResourceStatus, ResourceLoaderParams, ResourceSnapshot, PreviousResourceState, set_thread_safety, is_thread_safety_enabled

---

## Key Patterns & Design Decisions

1. **Edge-Based Graph**: Doubly-linked edges enable efficient cleanup after recomputation
2. **Lazy Evaluation**: ComputeSignals compute only on access
3. **Batched Updates**: Effects run once at batch end with final values
4. **Sticky Errors**: ComputeSignal errors persist until successful recompute
5. **Custom Equality**: Per-signal equality check, exception = changed
6. **Thread-Local Cycle Detection**: Per-signal running flag supports concurrent execution
7. **Untracked Contexts**: Via contextvars, critical for breaking dependency chains
8. **Async Resource Management**: Event-based cancellation, not task.cancel()
9. **LinkedSignal Bidirectionality**: Writable while computed
10. **Readonly Wrapper Caching**: Signal.as_readonly() ensures reference equality

---

## Data Flow Summary

### Read Flow
```
signal() or signal.get()
  -> (if thread safe) acquire lock
  -> graph.add_dependency(self)
    -> if active_consumer exists:
      -> create/reuse Edge(source=self, target=active_consumer)
      -> if active_consumer tracking: subscribe edge
  -> return _value
```

### Write Flow
```
signal.set(value)
  -> (if thread safe) acquire lock
  -> Check: if active_consumer is ComputeSignal: raise RuntimeError
  -> Check equality (custom or identity)
  -> if same: return (no change)
  -> _value = value
  -> _version += 1
  -> global_version += 1
  -> start_batch()
  -> Iterate targets (linked list):
    -> node.target._notify()
  -> end_batch()
    -> if batch_depth == 0:
      -> _flush_effects()
        -> _process_deferred_computed()
        -> Run effects in batched_effect_head list
```

### Compute Flow
```
computed.get()
  -> (if thread safe) acquire lock
  -> _refresh()
    -> Check thread-local cycle guard
    -> Fast path: if tracking && not outdated && same global_version: return True
    -> prepare_sources() - mark all sources version = -1
    -> set_active_consumer(self)
    -> Execute _fn()
      -> Dependent signals tracked via add_dependency()
    -> cleanup_sources() - unsubscribe unused
    -> set_active_consumer(prev)
    -> Check equality, bump version if changed
  -> edge = add_dependency(self)
  -> return _value (or raise if HAS_ERROR)
```

### Effect Flow
```
Effect created
  -> _notify() -> enqueue_effect() -> batched_effect_head = effect
  -> if batch_depth == 0: flush_now()

Scheduler._flush_effects()
  -> _process_deferred_computed() for computed signals first
  -> Traverse batched_effect_head linked list
  -> For each effect:
    -> _run_callback()
      -> _start(): prepare_sources(), set_active_consumer(self)
      -> Execute function
        -> Signals read within establish dependencies
      -> Collect cleanups
      -> _end(): cleanup_sources(), set_active_consumer(prev)
  -> After effects: _process_deferred_computed() again
```

---

## Error Handling Patterns

### Signal.set() from ComputeSignal
```python
active = graph.active_consumer.get()
if active is not None and isinstance(active, ComputeSignal):
    raise RuntimeError("Side effect detected: Cannot set Signal from within ComputeSignal")
```

### Circular Dependency Detection (Thread-Safe)
```python
def _is_running_in_current_thread(self) -> bool:
    try:
        return getattr(self._thread_local, "is_running", False)
    except AttributeError:
        return False

if self._is_running_in_current_thread():
    raise RuntimeError("Circular dependency detected")
```

### Effect Cycle Guard
```python
iterations = 0
while graph.batched_effect_head is not None:
    iterations += 1
    if iterations > graph.MAX_BATCH_ITERATIONS:
        raise RuntimeError("Reactive cycle detected (effect iterations exceeded)")
```

### Exception Propagation in ComputeSignal
```python
except BaseException as err:
    self._last_error = err
    self._flags |= graph.HAS_ERROR
    self._value = err  # for debug
    self._version += 1

# On get():
if self._flags & graph.HAS_ERROR:
    assert self._last_error is not None
    raise self._last_error
```

### Resource Loading Error
```python
except asyncio.CancelledError:
    raise  # Re-raise to mark task as cancelled
except Exception as e:
    if not cancellation.is_set():
        with untracked():
            error_signal.set(e)
            status_signal.set(ERROR)
```

---

## Type System Usage

### Generic Type Variables
- `T = TypeVar("T")` - Covariant for read (ReadableSignal)
- `T_inv = TypeVar("T_inv")` - Invariant for write (WritableSignal)
- `U = TypeVar("U")` - Separate type for LinkedSignal source

### Overloads for Computed
```python
@overload
def Computed(func: Callable[[], T], /) -> ComputeSignal[T]: ...

@overload
def Computed(func: Callable[[], T], /, *, equal: Callable[[T, T], bool]) -> ComputeSignal[T]: ...

@overload
def Computed(*, equal: Callable[[T, T], bool]) -> Callable[[Callable[[], T]], ComputeSignal[T]]: ...
```

Supports three patterns with proper type inference.

### Protocol Variance
```python
class ReadableSignal(Protocol[T]):  # T is covariant
class WritableSignal(ReadableSignal[T_inv], Protocol[T_inv]):  # T_inv invariant
```

Allows proper subtyping for read-only vs writable contexts.

---

## Internal Utilities

### Debug Logging
```python
_debug_enabled = False

def set_debug(enabled: bool):
    global _debug_enabled
    _debug_enabled = enabled

def debug_log(msg: str):
    if _debug_enabled:
        print(f"[REAKTIV DEBUG] {msg}")
```

Optional debug tracing throughout library.

### Contextvars Usage
```python
active_consumer: contextvars.ContextVar[Optional["_Consumer"]]
```

Uses contextvars for async-safe context propagation.

### Slots Optimization
All classes use `__slots__` for memory efficiency:
- Signal: 7 slots
- ComputeSignal: 8 additional slots
- Effect: 8 slots

Prevents dynamic attribute creation.

---

## Public API Surface

### Main Exports (__init__.py)
```python
# Signals
Signal
ReadonlySignal
ComputeSignal
Computed
LinkedSignal
Linked
PreviousState

# Effects
Effect

# Utilities
untracked
batch
to_async_iter

# Resources
Resource
ResourceStatus
ResourceLoaderParams
ResourceSnapshot
PreviousResourceState

# Thread Safety
set_thread_safety
is_thread_safety_enabled

# Protocols
ReadableSignal
WritableSignal
```

---

## Entry Points

### Creating Signals
```python
s = Signal(0)                    # Writable
c = Computed(lambda: s() * 2)   # Computed (immutable)
l = LinkedSignal(lambda: s())   # Writable computed
r = s.as_readonly()             # Read-only wrapper
```

### Creating Effects
```python
effect = Effect(lambda: print(s()))  # Sync
effect = Effect(async_func)          # Async (experimental)
effect.dispose()                      # Cleanup
```

### Batching
```python
with batch():
    s1.set(1)
    s2.set(2)
    s3.set(3)
# All effects run once here
```

### Resources
```python
async def main():
    resource = Resource(
        params=lambda: selected_id(),
        loader=async_load_data
    )
    # Use resource.value, resource.status, etc.
```

### Context Control
```python
with untracked():
    value = signal()  # No dependency

untracked(lambda: signal())  # Alternative syntax
```

---

## Notable Implementation Details

- **No circular imports**: graph.py is core, others depend on it; TYPE_CHECKING for static imports
- **Minimal scheduler**: Linked list for effects, no queue/priority system
- **Memory**: Cached readonly wrappers, Effects need reference retention, Resources cleanup in `__del__`
- **Global state**: batch_depth and graph state are global (not thread-local), contextvars for active_consumer
- **Cycle guards**: Iteration count (100 max) and thread-local running flags

---

## Summary

Reaktiv is a well-engineered reactive system prioritizing **correctness** over performance. Core innovations:

1. **Lazy ComputeSignal** with version-based change detection
2. **Batched effect scheduling** with cycle guards
3. **Untracked contexts** for selective dependency breaking
4. **LinkedSignal** combining computed and writable semantics
5. **Resource** for async/await integration with status tracking
6. **Thread-safe** via optional global toggle and RLocks
7. **Custom equality** per signal for value-based change detection

The implementation emphasizes preventing side effects, detecting cycles, and handling errors gracefully.
