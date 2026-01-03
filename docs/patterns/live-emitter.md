# Live Display Emitter Pattern

*Wrapping Rich Live displays as ev emitters.*

Live emitters typically respond to **signals** — structured observations about transient state changes. For example, `Event.log_signal("stack_status", stack="media", healthy=True)` drives a live tree display. See [signal.md](../concept/signal.md) for the signal concept.

## The Pattern

Rich's `Live` context manager provides real-time updating displays (spinners, progress bars, trees). To integrate with ev, wrap the live display in an emitter that's also a context manager:

```python
from rich.live import Live
from ev import Event, Result

class LiveEmitter:
    """Emitter that updates a Rich Live display."""

    def __init__(self, display: Live):
        self._display = display

    def __enter__(self):
        self._display.__enter__()
        return self

    def __exit__(self, *args):
        self._display.__exit__(*args)

    def emit(self, event: Event) -> None:
        # Convert event to renderable, update display
        renderable = self._event_to_renderable(event)
        self._display.update(renderable)

    def finish(self, result: Result) -> None:
        # Final update before context exits
        pass

    def _event_to_renderable(self, event: Event):
        # Domain-specific: convert event to Rich renderable
        ...
```

## Why Context Manager?

Rich `Live` requires entering/exiting a context to:
- Start the live display thread
- Clear the display on exit
- Handle terminal cleanup

By making your emitter a context manager that wraps `Live`, the lifecycle is explicit:

```python
with LiveEmitter(Live(tree)) as emitter:
    do_work(emitter)
    emitter.finish(result)
# Display cleaned up automatically
```

## Example: Stack Status Tree

A live-updating tree showing stack health:

```python
from rich.console import Console
from rich.live import Live
from rich.tree import Tree
from ev import Event, Result

class StackLiveEmitter:
    """Live tree display of stack status."""

    def __init__(self, console: Console | None = None):
        self._console = console or Console()
        self._tree = Tree("Stacks")
        self._live = Live(self._tree, console=self._console, refresh_per_second=4)
        self._nodes: dict[str, Any] = {}

    def __enter__(self):
        self._live.__enter__()
        return self

    def __exit__(self, *args):
        self._live.__exit__(*args)

    def emit(self, event: Event) -> None:
        if event.signal_name != "stack_status":
            return

        stack = event.data.get("stack", "unknown")
        healthy = event.data.get("healthy", False)

        icon = "[green]✓[/green]" if healthy else "[red]✗[/red]"
        label = f"{icon} {stack}"

        if stack in self._nodes:
            # Update existing node (Rich trees don't support this directly,
            # so you might rebuild or use a different approach)
            pass
        else:
            self._nodes[stack] = self._tree.add(label)

        self._live.update(self._tree)

    def finish(self, result: Result) -> None:
        # Could add a summary node
        icon = "[green]✓[/green]" if result.status == "ok" else "[red]✗[/red]"
        self._tree.add(f"{icon} {result.summary}")
        self._live.update(self._tree)
```

Usage:

```python
with StackLiveEmitter() as emitter:
    for stack in stacks:
        # Emit signal for each stack status
        emitter.emit(Event.log_signal("stack_status", stack=stack.name, healthy=stack.is_healthy))
    emitter.finish(Result.ok("3/3 healthy"))
```

## Example: Progress Spinner

For operations with phases:

```python
from rich.console import Console
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text

class SpinnerEmitter:
    """Spinner with current phase text."""

    def __init__(self, console: Console | None = None):
        self._console = console or Console()
        self._spinner = Spinner("dots", text="Starting...")
        self._live = Live(self._spinner, console=self._console)

    def __enter__(self):
        self._live.__enter__()
        return self

    def __exit__(self, *args):
        self._live.__exit__(*args)

    def emit(self, event: Event) -> None:
        if event.kind == "progress" and event.message:
            self._spinner.text = Text(event.message)
            self._live.update(self._spinner)

    def finish(self, result: Result) -> None:
        # Replace spinner with final status
        icon = "✓" if result.status == "ok" else "✗"
        self._live.update(Text(f"{icon} {result.summary}"))
```

## Separating Display Logic

Keep your Live display logic separate from the emitter wrapper:

```python
# display.py - Pure Rich display logic
class StackStatusDisplay:
    def __init__(self):
        self.tree = Tree("Stacks")
        self.live = Live(self.tree)

    def update(self, stack: str, healthy: bool):
        icon = "[green]✓[/green]" if healthy else "[red]✗[/red]"
        self.tree.add(f"{icon} {stack}")
        self.live.update(self.tree)

    def __enter__(self):
        self.live.__enter__()
        return self

    def __exit__(self, *args):
        self.live.__exit__(*args)


# emitter.py - ev integration
class StackLiveEmitter:
    def __init__(self, display: StackStatusDisplay):
        self._display = display

    def __enter__(self):
        self._display.__enter__()
        return self

    def __exit__(self, *args):
        self._display.__exit__(*args)

    def emit(self, event: Event) -> None:
        if event.signal_name == "stack_status":
            self._display.update(
                event.data.get("stack"),
                event.data.get("healthy")
            )

    def finish(self, result: Result) -> None:
        pass
```

This separation lets you:
- Test the display logic independently
- Reuse the display in non-ev contexts
- Keep the emitter thin

## finish() vs __exit__

Two places for cleanup:

| Method | When Called | Use For |
|--------|-------------|---------|
| `finish()` | Explicitly by caller | Final status update |
| `__exit__` | On context exit | Terminal cleanup |

Typically:
- `finish()` updates the display one last time (show final status)
- `__exit__` delegates to Rich Live for terminal cleanup

Don't put display updates in `__exit__` — it's for cleanup, not rendering.

## Testing Live Emitters

Live emitters are tricky to test because they involve terminal state. Options:

1. **Mock the Live display:**
```python
def test_live_emitter_updates_display():
    mock_display = Mock()
    emitter = StackLiveEmitter(mock_display)

    emitter.emit(Event.log_signal("stack_status", stack="media", healthy=True))

    mock_display.update.assert_called()
```

2. **Test the display separately**, use `NullEmitter` for integration tests

3. **Capture console output** with Rich's `Console(record=True)`

## When to Use Live Emitters

| Scenario | Live Emitter? |
|----------|---------------|
| Long operation with parallel tasks | Yes - show live tree |
| Quick command | No - streaming or batch |
| CI/headless | No - use plain/JSON |
| Interactive terminal | Yes |

Check if the terminal supports live updates:
```python
if console.is_terminal:
    emitter = LiveEmitter(...)
else:
    emitter = PlainEmitter(...)
```

## Summary

Live emitter pattern:
1. Wrap a Rich Live display
2. Implement context manager (delegate to Live)
3. Convert events to renderables in `emit()`
4. Final update in `finish()`, cleanup in `__exit__`

Keep display logic separate from ev integration for testability.
