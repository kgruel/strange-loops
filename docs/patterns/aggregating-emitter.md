# Aggregating Emitter Pattern

*Wrap an emitter to accumulate state while delegating rendering.*

## The Pattern

Sometimes you need to track aggregates (counts, totals, summaries) across events while still delegating to another emitter for rendering.

```python
class CountingEmitter:
    """Wraps an emitter to count matching events."""

    def __init__(self, inner: Emitter, predicate: Callable[[Event], bool]):
        self._inner = inner
        self._predicate = predicate
        self.count = 0

    def emit(self, event: Event) -> None:
        if self._predicate(event):
            self.count += 1
        self._inner.emit(event)

    def finish(self, result: Result) -> None:
        self._inner.finish(result)
```

The wrapper:
1. Intercepts events
2. Updates its own state
3. Delegates to the inner emitter unchanged

## When to Use This

- Counting successful/failed items across parallel operations
- Accumulating totals while streaming output
- Tracking metrics that span multiple events
- Building summaries without modifying the rendering emitter

## Example: Counting Healthy Stacks

```python
class HealthCountingEmitter:
    """Counts healthy stacks while delegating to inner emitter."""

    def __init__(self, inner: Emitter):
        self._inner = inner
        self.healthy_count = 0
        self.total_count = 0

    def emit(self, event: Event) -> None:
        if event.kind == "artifact" and event.data.get("type") == "stack_status":
            self.total_count += 1
            if event.data.get("healthy"):
                self.healthy_count += 1
        self._inner.emit(event)

    def finish(self, result: Result) -> None:
        self._inner.finish(result)
```

Usage:

```python
def check_all_stacks(emitter: Emitter) -> Result:
    counter = HealthCountingEmitter(emitter)

    for stack in get_stacks():
        check_stack(stack, counter)

    return Result(
        status="ok" if counter.healthy_count == counter.total_count else "error",
        summary=f"{counter.healthy_count}/{counter.total_count} healthy",
        data={"healthy": counter.healthy_count, "total": counter.total_count}
    )
```

## Generic Version

If you find yourself writing many counting wrappers:

```python
from typing import Callable
from ev import Event, Result, Emitter

class PredicateCounter:
    """Generic wrapper that counts events matching a predicate."""

    def __init__(
        self,
        inner: Emitter,
        predicate: Callable[[Event], bool],
        name: str = "count"
    ):
        self._inner = inner
        self._predicate = predicate
        self.name = name
        self.count = 0

    def emit(self, event: Event) -> None:
        if self._predicate(event):
            self.count += 1
        self._inner.emit(event)

    def finish(self, result: Result) -> None:
        self._inner.finish(result)
```

Usage:

```python
is_healthy = lambda e: (
    e.kind == "artifact" and
    e.data.get("type") == "stack_status" and
    e.data.get("healthy")
)

counter = PredicateCounter(emitter, is_healthy, "healthy_stacks")
# ... emit events ...
print(f"Healthy: {counter.count}")
```

## Multi-Counter

For tracking multiple aggregates:

```python
class MultiCounter:
    """Track multiple named counts."""

    def __init__(
        self,
        inner: Emitter,
        counters: dict[str, Callable[[Event], bool]]
    ):
        self._inner = inner
        self._predicates = counters
        self.counts = {name: 0 for name in counters}

    def emit(self, event: Event) -> None:
        for name, predicate in self._predicates.items():
            if predicate(event):
                self.counts[name] += 1
        self._inner.emit(event)

    def finish(self, result: Result) -> None:
        self._inner.finish(result)
```

Usage:

```python
counter = MultiCounter(emitter, {
    "healthy": lambda e: e.data.get("healthy"),
    "unhealthy": lambda e: e.data.get("healthy") == False,
    "total": lambda e: e.kind == "artifact",
})

# After emitting...
print(f"{counter.counts['healthy']}/{counter.counts['total']} healthy")
```

## Composition with Other Wrappers

Wrappers compose naturally:

```python
# Log events → Count → Render
logged = LoggingEmitter(rich_emitter)
counted = HealthCountingEmitter(logged)
do_work(counted)
```

Each wrapper in the chain sees events, does its thing, and passes along.

## Why Not Build This Into ev?

This pattern is simple and varies by domain:
- What to count differs per CLI
- Predicates are domain-specific
- The 10-line wrapper is often clearer than a generic utility

Document the pattern, copy when needed.

## Testing Aggregating Emitters

```python
def test_counter_counts_healthy():
    inner = ListEmitter()
    counter = HealthCountingEmitter(inner)

    counter.emit(Event.artifact(type="stack_status", healthy=True))
    counter.emit(Event.artifact(type="stack_status", healthy=False))
    counter.emit(Event.artifact(type="stack_status", healthy=True))
    counter.finish(Result.ok())

    assert counter.healthy_count == 2
    assert counter.total_count == 3
    assert len(inner.events) == 3  # All passed through
```

## Summary

The aggregating wrapper pattern:
1. Wraps an existing emitter
2. Intercepts `emit()` to update state
3. Delegates unchanged to inner emitter
4. Exposes aggregates for use after events complete

Simple, composable, domain-specific.
