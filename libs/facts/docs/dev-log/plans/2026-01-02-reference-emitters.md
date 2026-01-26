---
status: completed
updated: 2026-01-02
prereqs:
  - core-contract-v1: done
---

# Reference Emitters

Implement JSON, Plain, and Rich emitters that satisfy the Emitter protocol.

## Understanding Summary

### Key Design Decision: Renderers ARE Emitters

Instead of a separate Renderer protocol, rendering emitters implement the same `Emitter` protocol. This gives us:
- One interface, not two
- No wiring step between collection and rendering
- Streaming-friendly (Rich can show spinners as events arrive)
- Composable (TeeEmitter, FilteringEmitter, etc. come later)

### The Emitter Family

| Emitter | Purpose | Dependencies |
|---------|---------|--------------|
| `ListEmitter` | Collect for testing | None (exists) |
| `NullEmitter` | Discard (no-op) | None (exists) |
| `JsonEmitter` | Machine-readable output | None |
| `PlainEmitter` | Minimal text output | None |
| `RichEmitter` | Beautiful terminal output | Rich (optional) |

### Output Stream Policy (Opinionated)

- **Events → stderr**: narrative, "what's happening"
- **Result → stdout**: authoritative answer

For JSON specifically:
- Result as JSON → stdout (always)
- Events as JSONL → stderr (optional, configurable)

Plain and Rich write to stderr; result accessible via stdout or return value.

## Scope

### In Scope
1. **JsonEmitter** — Result to stdout, optional JSONL events to stderr
2. **PlainEmitter** — Simple text to stderr
3. **RichEmitter** — Beautiful output to stderr (thin v1, proves the concept)

### Out of Scope
- TeeEmitter, FilteringEmitter, ThrottlingEmitter (future)
- Full-featured Rich (progress bars, trees, panels) — keep v1 thin
- Async variants

## Implementation

### File Structure
```
src/ev/
├── __init__.py
├── types.py
├── emitter.py          # Emitter protocol, ListEmitter, NullEmitter (exists)
├── emitters/
│   ├── __init__.py     # Exports JsonEmitter, PlainEmitter
│   ├── json.py         # JsonEmitter
│   └── plain.py        # PlainEmitter
└── py.typed

# Rich is optional, could be:
# Option A: src/ev/emitters/rich.py (with optional import)
# Option B: separate package (ev-rich)
```

### Step 1: JsonEmitter

```python
class JsonEmitter:
    """Emitter that outputs JSON to stdout, optional JSONL events to stderr."""

    def __init__(
        self,
        stdout: TextIO = sys.stdout,
        stderr: TextIO = sys.stderr,
        include_events: bool = True,   # Include events in final output
        stream_events: bool = False,   # Also stream events as JSONL to stderr
    ) -> None: ...

    def emit(self, event: Event) -> None:
        # Buffer event if include_events
        # If stream_events, also write event.to_dict() as JSON line to stderr
        ...

    def finish(self, result: Result) -> None:
        # Output to stdout:
        # - If include_events: {"events": [...], "result": {...}}
        # - Otherwise: just result.to_dict()
        ...
```

**Tests:**
- Default: outputs `{"events": [...], "result": {...}}` to stdout
- With `include_events=False`: outputs only result to stdout
- With `stream_events=True`: also streams JSONL to stderr
- Proper JSON formatting (valid JSON, newline at end)
- Handles empty events list

### Step 2: PlainEmitter

```python
class PlainEmitter:
    """Emitter that outputs plain text to stderr."""

    def __init__(
        self,
        file: TextIO = sys.stderr,
        show_level: bool = True,      # Prefix with [INFO], [WARN], etc.
        show_timestamp: bool = False,  # Prefix with timestamp
    ) -> None: ...

    def emit(self, event: Event) -> None:
        # Format and print based on event kind
        # log: just message
        # progress: "step X/Y" or "X%"
        # artifact: "Created: path"
        # metric: "name: value unit"
        # input: "Q: ... A: ..."
        ...

    def finish(self, result: Result) -> None:
        # Print summary line
        # "OK: summary" or "ERROR: summary"
        ...
```

**Tests:**
- Log events print message
- Progress events format step/percent
- Artifact events show path/URL
- Metric events show name/value
- Result prints summary with status
- Level prefix when enabled
- Output goes to stderr by default

### Step 3: RichEmitter (thin v1)

```python
class RichEmitter:
    """Emitter that outputs beautiful Rich text to stderr."""

    def __init__(
        self,
        console: Console | None = None,  # Uses stderr by default
    ) -> None: ...

    def emit(self, event: Event) -> None:
        # Thin v1: just styled text, no live widgets
        # log: print with level-based color
        # progress: print step/phase
        # artifact: print with icon
        # metric: print name: value
        # input: print Q/A
        ...

    def finish(self, result: Result) -> None:
        # Print styled summary
        # ✓ summary (green) or ✗ summary (red)
        ...
```

**Tests:**
- Events render with appropriate styling
- Result shows checkmark/X based on status
- Console can be injected for testing
- Defaults to stderr

### Step 4: Update exports

```python
# In src/ev/__init__.py
from ev.emitters import JsonEmitter, PlainEmitter

# RichEmitter is optional import
try:
    from ev.emitters.rich import RichEmitter
except ImportError:
    pass  # Rich not installed
```

Or cleaner: keep Rich in emitters/ but document it requires `pip install ev[rich]`.

## Verification

```bash
uv run pytest                  # All tests pass, 100% coverage
uv run ruff check .            # No lint errors
uv run ruff format --check .   # Formatted
```

Manual verification:
- Run a sample command with each emitter
- Verify stdout/stderr separation with piping

## Decisions

1. **JsonEmitter output modes**:
   - Default: buffer events, output `{"events": [...], "result": {...}}` to stdout
   - Optional `stream_events=True`: also stream events as JSONL to stderr as they arrive
   - Optional `include_events=False`: discard events, output only result
2. **PlainEmitter defaults** — Show level prefix, no timestamps. Keep it minimal.
3. **RichEmitter scope** — Thin v1. Just styled text, no live progress bars or spinners. Prove the concept first.
4. **Rich dependency** — Optional extra via `pip install ev[rich]`. Set up pyproject.toml extras now.

## Success Criteria

- [x] JsonEmitter outputs valid JSON to stdout
- [x] JsonEmitter optionally streams JSONL events to stderr
- [x] PlainEmitter outputs readable text to stderr
- [x] RichEmitter outputs styled text to stderr
- [x] All emitters satisfy the Emitter protocol
- [x] 100% test coverage maintained
- [x] All checks pass
- [x] stdout/stderr separation works correctly with pipes
