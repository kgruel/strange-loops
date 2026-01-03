# Emitter Archetypes: Streaming vs Batch

*Two ways to render events, with different tradeoffs.*

## The Two Archetypes

| Archetype | Behavior | Best For |
|-----------|----------|----------|
| **Streaming** | Render each event as it arrives | Live feedback, long-running ops |
| **Batch** | Collect events, render once on `finish()` | Composed output, tables, summaries |

Both are valid implementations of the `Emitter` protocol. The difference is *when* output happens.

## Streaming Emitters

Streaming emitters write output immediately in `emit()`:

```python
class StreamingEmitter:
    def __init__(self, file: TextIO = sys.stderr):
        self._file = file

    def emit(self, event: Event) -> None:
        # Render and write immediately
        line = self._format(event)
        self._file.write(line + "\n")
        self._file.flush()

    def finish(self, result: Result) -> None:
        # Final summary only
        self._file.write(f"Done: {result.summary}\n")
```

**Characteristics:**
- Output appears as events occur
- Good for long-running operations (user sees progress)
- Each event is independent (can't reference others)
- Output order matches event order

**ev's reference emitters:**
- `PlainEmitter` — streaming to stderr
- `RichEmitter` — streaming to stderr

### Output Stream Convention

For streaming emitters, **stderr** is conventional:
- Events are narrative ("what's happening")
- stdout stays clean for structured result
- Pipes work: `mycli | jq` gets JSON, human sees progress on stderr

## Batch Emitters

Batch emitters collect events and render once in `finish()`:

```python
class BatchEmitter:
    def __init__(self, file: TextIO = sys.stdout):
        self._file = file
        self._items: list[dict] = []

    def emit(self, event: Event) -> None:
        # Collect, don't render yet
        if self._should_collect(event):
            self._items.append(event.data)

    def finish(self, result: Result) -> None:
        # Now render everything together
        output = self._compose(self._items, result)
        self._file.write(output)
```

**Characteristics:**
- No output until `finish()`
- Can compose complex layouts (tables, trees, grouped sections)
- Can aggregate across events (counts, totals)
- Can reorder or filter based on full event stream

**ev's reference emitters:**
- `JsonEmitter` — batch to stdout (buffers events, writes JSON object)

### Output Stream Convention

For batch emitters, **stdout** is often appropriate:
- The composed output *is* the result
- No incremental progress to show
- Clean JSON or structured text

But stderr is fine too if you're separating from machine-readable output.

## Choosing an Archetype

| Scenario | Archetype | Why |
|----------|-----------|-----|
| Long operation with phases | Streaming | User needs feedback |
| Quick command, rich output | Batch | Compose tables/trees |
| JSON for automation | Batch | Single valid JSON object |
| Debug/verbose logging | Streaming | See events as they occur |
| Summary with counts | Batch | Need to aggregate |

## Hybrid Approaches

Some emitters do both:

```python
class HybridEmitter:
    def emit(self, event: Event) -> None:
        # Stream progress events for feedback
        if event.kind == "progress":
            self._stream_progress(event)
        # Collect artifacts for final summary
        elif event.kind == "artifact":
            self._artifacts.append(event)

    def finish(self, result: Result) -> None:
        # Render collected artifacts as a table
        self._render_artifact_table()
```

## Common Pitfall: stdout/stderr Confusion

If you write a **batch** emitter but default to **stderr** (copying from streaming examples), tests expecting stdout will fail.

Think about what your emitter is producing:
- Incremental narrative → stderr
- Final composed output → stdout (or stderr, but be intentional)

## Example: Streaming Plain

```python
class MyStreamingPlain:
    """Shows each event as it happens."""

    def __init__(self, file: TextIO = sys.stderr):
        self._file = file

    def emit(self, event: Event) -> None:
        if event.kind == "progress":
            self._file.write(f"... {event.message}\n")
        elif event.kind == "artifact":
            self._file.write(f"Created: {event.data.get('path')}\n")
        self._file.flush()

    def finish(self, result: Result) -> None:
        icon = "OK" if result.status == "ok" else "ERROR"
        self._file.write(f"{icon}: {result.summary}\n")
```

## Example: Batch Plain

```python
class MyBatchPlain:
    """Collects events, renders a composed summary."""

    def __init__(self, file: TextIO = sys.stdout):
        self._file = file
        self._stacks: list[dict] = []

    def emit(self, event: Event) -> None:
        if event.kind == "artifact" and event.data.get("type") == "stack_status":
            self._stacks.append(dict(event.data))

    def finish(self, result: Result) -> None:
        # Render as table
        self._file.write("Stack Status\n")
        self._file.write("-" * 40 + "\n")
        for stack in self._stacks:
            icon = "OK" if stack.get("healthy") else "FAIL"
            self._file.write(f"{icon}  {stack.get('stack')}\n")
        self._file.write("-" * 40 + "\n")
        self._file.write(f"{result.summary}\n")
```

## Summary

| Archetype | emit() | finish() | Typical Stream |
|-----------|--------|----------|----------------|
| Streaming | Writes immediately | Final line | stderr |
| Batch | Collects | Composes & writes | stdout |

Neither is better. Choose based on your UX needs.
