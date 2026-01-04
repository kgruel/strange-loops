---
status: in-progress
updated: 2026-01-04
---

# ev Trifecta Alignment

Resolving conceptual conflicts across ev, ev-present, and ev-runtime.

## Feedback Items

| # | Issue | Decision | Status |
|---|-------|----------|--------|
| 2 | Exit code: `Result.code` vs `is_ok` only | Make `Result.code` authoritative | pending |
| 3 | TTY detection: stdout vs stderr | Split detection | pending |
| 4 | Lock in seam responsibilities | Document explicitly | pending |
| 5 | Adapter layer naming | Name and bless | pending |
| 6 | Progress identity/hierarchy | Keep minimal; hierarchy in ev-toolkit | done |
| 7 | Schema versioning | Rejected — versioning at emitter layer | done |
| 8 | Validation tests | Emitters moved to ev-toolkit | done |

---

## Item 2: Exit Code Policy

### Current State

**ev** (`types.py`):
```python
@dataclass(frozen=True)
class Result:
    code: int = 0  # exit code
    # Invariants: ok requires code=0, error requires code!=0
```

**ev-runtime** (`context.py:58-66`):
```python
def exit_code(self, result: Any) -> int:
    return 0 if getattr(result, "is_ok", False) else 1  # ignores Result.code!
```

### Conflict

ev defines `Result.code` as authoritative with documented special codes (10=timeout, 20=auth).
ev-runtime ignores it entirely.

### Decision: Make Result.code Authoritative

**ev-runtime change**:
```python
def exit_code(self, result: Any) -> int:
    """Map result to Unix exit code.

    If result.code is set (non-default), use it directly.
    Otherwise: ok → 0, error → 1.
    """
    code = getattr(result, "code", None)
    if code is not None:
        return code
    return 0 if getattr(result, "is_ok", False) else 1
```

**Rationale**: Result.code already enforces invariants (ok requires 0, error requires nonzero).
Respecting it allows domain ops to signal standard codes (2=usage, 130=SIGINT, etc.).

---

## Item 3: TTY Detection - stdout vs stderr

### Current State

**ev-runtime** (`mode.py:49`):
```python
if is_tty is None:
    is_tty = sys.stdout.isatty()
```

### Problem

ev's recommended stream policy:
- Events → stderr (live/rich UI)
- Result → stdout (structured output)

But TTY detection checks stdout. Live UI capability depends on stderr.

### Decision: Split Detection

Add two detection helpers:

```python
def detect_mode(
    *,
    json_flag: bool = False,
    plain_flag: bool = False,
    is_tty_out: bool | None = None,   # for result formatting
    is_tty_err: bool | None = None,   # for live/rich UI
    no_color_env: bool | None = None,
) -> OutputMode:
    if is_tty_out is None:
        is_tty_out = sys.stdout.isatty()
    if is_tty_err is None:
        is_tty_err = sys.stderr.isatty()

    # Mode selection uses is_tty_err (where events go)
    # But we expose both for apps that need them
```

**Alternative**: Keep single `is_tty` but document that callers should pass `sys.stderr.isatty()` for event-driven UIs.

**Recommendation**: Start with documentation + sensible default, add split if real apps need it.

---

## Item 4: Lock in Seam Responsibilities

### ev responsibilities (freeze)

- Value types: `Event`, `Result`
- Minimal event kinds: log, progress, artifact, metric, input
- Serialization: `to_dict()` / `from_dict()` (JSON-safe)
- Emitter protocol: `emit(event)`, `finish(result)`, context manager
- Stream policy: recommendation only (events→stderr, result→stdout)

### ev-present responsibilities (freeze)

- Display models: `LogLine` (and future models)
- IR: `Segment`, `Line` with stability tiers
- Config (frozen) + State (mutable)
- Rendering functions: model → IR
- **No ev import** (duck-typed normalizers)

### ev-runtime responsibilities (freeze)

- Mode + verbosity detection helpers
- Resolver protocol + "not found with suggestions" UX
- Emitter factory wiring + lifecycle management
- Exit code mapping policy
- **No ev-present import** (wires, doesn't translate)

### Key Invariant

```
ev-runtime ─────┐
                │ wires
                ▼
    domain ops (emits ev.Event/Result)
                │
                │ adapter (app layer)
                ▼
    ev-present (renders display models)
```

---

## Item 5: Adapter Layer Naming

### Current State

`ev-present/normalize.py` has:
- `from_event(event: object) -> LogLine`
- `supports(obj: object) -> bool`

This is effectively the adapter, but unnamed.

### Decision: Bless and Name

**Option A**: Keep in ev-present as `ev_present.normalize` module (current)
- Pro: Already works, no new package
- Con: Name doesn't communicate "this is THE ev adapter"

**Option B**: Create `ev-present-ev` or `ev_adapt` package
- Pro: Explicit boundary
- Con: Another package to manage for ~50 lines of code

**Recommendation**: Option A with better naming. Rename module:

```
ev_present/
  adapters/
    __init__.py      # re-exports
    ev_adapter.py    # from_event, supports (for ev.Event)
    docker.py        # future: from_docker_line
    systemd.py       # future: from_journal_entry
```

Then:
```python
from ev_present.adapters import ev_adapter
from ev_present.adapters.ev_adapter import from_event, supports
```

---

## Item 6: Progress Identity/Hierarchy

### Current State

`Event.progress()` accepts any kwargs in `data`:
```python
Event.progress("Downloading", current=37, total=100)
Event.progress("Build phase", phase="build", status="complete")
```

No standardized identity/hierarchy fields.

### Decision: Keep ev Minimal — Hierarchy in ev-toolkit

**Rejected approach**: Adding `id`/`parent_id` to ev's recommended fields.

**Why rejected**:

1. Most CLIs don't need hierarchy — adding it bloats the 90% case for the 10%
2. ev's design rule: "Only add a primitive if a renderer capability cannot be reliably implemented without it"
3. Apps that need hierarchy can add `id`/`parent_id` to `data` without ev blessing it

**Recommended fields in ev** (kept minimal):

| Field | Type | Description |
|-------|------|-------------|
| `current` | int/float | Current value |
| `total` | int/float | Total value (for percentage) |
| `unit` | str | What's being counted ("files", "bytes", etc.) |
| `phase` | str | Named phase identifier |
| `status` | str | "running" / "ok" / "error" |

**For hierarchical progress**: See `ProgressTree` pattern in ev-toolkit. Apps add `id`/`parent_id` to `Event.data`, and `ProgressTree` tracks the tree structure for renderers.

---

## Item 7: Schema Versioning

### Current State

No version field. Extensibility via `data` dict.

### Decision: No schema in `to_dict()` — versioning belongs at emitter layer

**Rejected approach**: Adding `_schema` field to `Event.to_dict()` and `Result.to_dict()`.

**Why rejected**:

1. **Seam confusion** — `to_dict()` is a data transformation ("convert to dict"). Schema stamping is a serialization concern ("mark this output with provenance"). Mixing them conflates responsibilities.

2. **ev is frozen** — The library philosophy is "Black-style: frozen, opinionated, minimal." If the schema rarely changes, versioning in the core types is premature.

3. **Lock-in without clear benefit** — Adding `_schema` to output forces a decision about `from_dict()` behavior (validate? ignore? store?). The "lenient reader" pattern (ignore unknown keys) is correct for forward-compat, but documenting that contract adds maintenance burden for unclear gain.

4. **Better seam exists** — Emitters are the serialization boundary. Domain-specific emitters (HlabJsonEmitter, LldapJsonEmitter) will evolve independently. Versioning at that layer is more flexible:
   - `JsonEmitter` can stamp `ev-json@1` if needed
   - Domain emitters can stamp `hlab:event@2`
   - Emitters that don't need versioning can omit it entirely

**If versioning is needed later**: Add it to emitters, not to `to_dict()`. The emitter owns its output format.

---

## Item 8: Validation Tests

### Decision: Utility Emitters Moved to ev-toolkit

The following emitters were removed from ev core and now live in ev-toolkit:

| Emitter | Purpose | ev-toolkit location |
|---------|---------|---------------------|
| `TeeEmitter` | Broadcast to multiple emitters | `ev_toolkit.wrappers` |
| `FileEmitter` | JSONL output for debugging | `ev_toolkit.wrappers` |
| `RichEmitter` | Rich terminal output | `ev_toolkit.rich_emitter` |
| `RecordingEmitter` | Test capture with `Run` | `ev_toolkit.wrappers` |

This keeps ev core minimal (just `PlainEmitter`, `JsonEmitter`, `ListEmitter`) while ev-toolkit provides batteries-included utilities.

### Golden Test (lives in ev-toolkit)

```python
from ev import Event, Result
from ev_toolkit import RecordingEmitter
from ev_present import from_event, render_log_line, LogLineConfig, RenderState

def test_full_pipeline_golden():
    """Validates ev → adapter → IR → output stability."""
    recorder = RecordingEmitter()

    with recorder:
        recorder.emit(Event.log("Starting operation"))
        recorder.emit(Event.progress("Processing", current=1, total=3))
        recorder.emit(Event.artifact("file", path="/out/result.json"))
        recorder.emit(Event.metric("duration", 1.234, unit="s"))
        recorder.finish(Result.ok("Completed", data={"items": 3}))

    run = recorder.run()

    # Assert Run structure
    assert len(run.events) == 4
    assert run.result.is_ok

    # Assert adapter → LogLine
    log_line = from_event(run.events[0])
    assert log_line.message == "Starting operation"

    # Assert LogLine → IR
    line = render_log_line(log_line, LogLineConfig(), RenderState())
    assert any(seg.role == "message" for seg in line.segments)

    # Assert serialization round-trip
    event_dict = run.events[0].to_dict()
    assert event_dict["kind"] == "log"
    assert event_dict["message"] == "Starting operation"
```

---

## Implementation Order (Revised)

1. ~~Schema versioning~~ — Rejected (versioning at emitter layer if needed)
2. **Exit code policy** (ev-runtime) - fixes real bug - pending
3. ~~Progress data conventions~~ — Done (kept minimal, hierarchy in ev-toolkit)
4. **Adapter naming** (ev-present) - refactor, no behavior change - pending
5. **TTY detection** (ev-runtime) - document first, split if needed - pending
6. ~~Validation tests~~ — Done (emitters moved to ev-toolkit)

---

## Current State

Items 6, 7, 8 completed. Remaining items (2, 3, 4, 5) are ev-runtime/ev-present changes.
