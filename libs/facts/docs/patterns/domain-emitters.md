# Domain Emitters

*You'll write your own. That's the point.*

## The Expectation

ev provides reference emitters (`PlainEmitter`, `JsonEmitter`) as **working examples of the protocol**, not as reusable building blocks for all use cases. For Rich terminal output and composition utilities, see ev-toolkit.

For production CLIs, you'll typically write **domain-specific emitters** that understand your event shapes and rendering needs.

This is by design. The `Emitter` protocol is intentionally minimal:

```python
class Emitter(Protocol):
    def emit(self, event: Event) -> None: ...
    def finish(self, result: Result) -> None: ...
```

That's it. What you do inside those methods is entirely up to you.

## Why Domain Emitters Are the Norm

### 1. Event Shapes Are Domain-Specific

Your events carry domain-specific data:

```python
Event.artifact(
    type="stack_status",
    stack="media",
    healthy=True,
    services=["plex", "jellyfin", "sonarr"]
)
```

A generic `PlainEmitter` can't know how to render `stack_status` meaningfully. It just sees `data` as an opaque dict.

Your domain emitter knows:
- What `type="stack_status"` means
- How to format the service list
- Whether to show healthy/unhealthy differently

### 2. Rendering Requirements Vary

Different CLIs need different output structures:

| CLI | Plain Output Need |
|-----|-------------------|
| `hlab status` | Table of stacks with health icons |
| `deploy` | Step-by-step progress with timing |
| `backup` | File list with sizes |

One `PlainEmitter` can't serve all these. But one `Emitter` protocol can.

### 3. Output Modes Are Per-Domain

A typical CLI might have:

```python
class MyPlainEmitter:    # Human-readable, maybe colored
class MyJsonEmitter:     # Machine-readable, structured
class MyLiveEmitter:     # Rich Live display with spinners
class MyQuietEmitter:    # Minimal, errors only
```

Each understands your event shapes and renders appropriately.

## What Reference Emitters Are For

The reference emitters serve as:

1. **Protocol examples** — Show how to implement `emit()` and `finish()`
2. **Quick prototyping** — Get something working before writing domain emitters
3. **Generic fallbacks** — When you don't need domain-specific rendering
4. **Test utilities** — `ListEmitter` and `NullEmitter` are genuinely reusable

## Domain Emitter Template

Here's a starting point for batch-style domain emitters:

```python
from dataclasses import dataclass, field
from typing import TextIO
from ev import Event, Result

@dataclass
class MyDomainEmitter:
    """Batch emitter that collects events and renders on finish()."""

    file: TextIO | None = None
    verbosity: int = 1

    _items: list[dict] = field(default_factory=list, init=False)
    _finished: bool = field(default=False, init=False)

    def emit(self, event: Event) -> None:
        if self._finished:
            return

        # Filter/collect events you care about
        if event.kind == "artifact" and event.data.get("type") == "my_type":
            self._items.append(dict(event.data))

    def finish(self, result: Result) -> None:
        if self._finished:
            return
        self._finished = True
        self._render(result)

    def _render(self, result: Result) -> None:
        # Compose and output your domain-specific format
        ...
```

For streaming-style, see [emitter-archetypes.md](emitter-archetypes.md).

## Testing Domain Emitters

Test your emitters by feeding them known events:

```python
def test_my_emitter_renders_healthy_stacks():
    output = StringIO()
    emitter = MyPlainEmitter(file=output)

    emitter.emit(Event.artifact(type="stack_status", stack="media", healthy=True))
    emitter.finish(Result.ok("1 stack healthy"))

    assert "media" in output.getvalue()
    assert "healthy" in output.getvalue()
```

Use `ListEmitter` to test your domain logic separately:

```python
def test_check_stack_emits_correct_events():
    emitter = ListEmitter()

    check_stack("media", emitter)
    emitter.finish(Result.ok())

    # Assert on the events, not the rendering
    assert any(
        e.is_kind("artifact") and e.data.get("stack") == "media"
        for e in emitter.events
    )
```

## Summary

| Component | Purpose |
|-----------|---------|
| `Emitter` protocol | The contract your domain code programs against |
| Reference emitters | Examples and utilities |
| Domain emitters | What you build for production |

The protocol is stable. Your emitters are yours to evolve.
