# The ev Trifecta: Boundary Reference

The ev ecosystem is four packages with distinct responsibilities. This document defines the boundaries.

## The Stack

```
┌─────────────────────────────────────────────────────────┐
│                    Your CLI App                         │
│         (domain logic, commands, workflows)             │
└─────────────────────┬───────────────────────────────────┘
                      │ uses
┌─────────────────────▼───────────────────────────────────┐
│                   ev-toolkit                            │
│    Utilities: TeeEmitter, RichEmitter, RecordingEmitter │
│    Conveniences: get_emitter(), Run                     │
│    Recipes: ProgressTracker, VerbosityFilter            │
└─────────────────────┬───────────────────────────────────┘
                      │ depends on
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
┌───────────┐  ┌─────────────┐  ┌──────────────┐
│    ev     │  │ ev-present  │  │  ev-runtime  │
│ Contract  │  │  Display    │  │   Wiring     │
└───────────┘  └─────────────┘  └──────────────┘
```

## Package Responsibilities

### ev — Contract Layer (Frozen)

**Question**: How does an operation describe what happened?

**Owns**:
- `Event` — semantic facts (log, progress, artifact, metric, input)
- `Result` — operation outcome (status, code, summary, data, meta)
- `Emitter` protocol — emit(event), finish(result)
- Basic emitters: PlainEmitter, JsonEmitter, ListEmitter, NullEmitter

**Does NOT own**:
- Parsing, commands, framework integration
- Themes, colors, styling
- Composition utilities (TeeEmitter → ev-toolkit)
- Rich integration (RichEmitter → ev-toolkit)

**Stability**: Event kinds frozen. Result contract frozen. "Only add a primitive if a renderer capability cannot be reliably implemented without it."

---

### ev-present — Display Layer (Stable IR)

**Question**: How does content render semantically?

**Owns**:
- `LogLine` — display model for log-like content
- `Segment` / `Line` — semantic IR with stability guarantees
- `Normalizer` protocol — contract for adapters
- `from_event()` — duck-typed convenience for event-like objects
- Config (frozen layout) vs State (mutable assignments)

**Does NOT own**:
- Actual rendering to terminals (that's backend's job)
- ev.Event (duck-types, doesn't import)
- Themes or colors (hints are suggestions, not requirements)

**Stability**: `Segment.role` and `Segment.tags` are STABLE. `Segment.hint` is UNSTABLE (presentation only).

**Key insight**: Layout is structural. Styling is interpretive.

---

### ev-runtime — Wiring Layer (Stable)

**Question**: How does a CLI prepare and run an operation?

**Owns**:
- `RuntimeContext` — assembled CLI context
- `detect_mode()` — output mode from flags/environment
- `detect_verbosity()` — verbosity from flags/TTY
- `Resolver` protocol — resource lookup with suggestions
- `exit_code()` — Result → Unix exit code mapping

**Does NOT own**:
- CLI parsing (use cappa/Typer/Click)
- Emitter implementations
- ev-present (no dependency, wires but doesn't translate)
- Domain logic

**Stability**: Mode detection priority frozen. Exit code respects Result.code.

---

### ev-toolkit — Utilities Layer (Evolving)

**Question**: What utilities speed up emitter composition?

**Owns**:
- Composition: `TeeEmitter`, `FilterEmitter`, `TimingEmitter`, `CountingEmitter`
- Recording: `RecordingEmitter`, `Run`
- Integration: `RichEmitter` (uses ev-present pipeline)
- Conveniences: `get_emitter()`, `FileEmitter`
- Recipes: `ProgressTracker`, `VerbosityFilter`, `BatchCollector`

**Does NOT own**:
- Core contract (that's ev)
- Display primitives (that's ev-present)
- CLI wiring (that's ev-runtime)

**Stability**: Can evolve faster than core. Copy-paste friendly design.

---

## Dependency Rules

```
ev-toolkit
    ├── ev (required)
    ├── ev-present (optional, for RichEmitter)
    └── rich (optional, for RichEmitter)

ev-runtime
    └── (none - duck-types on ev)

ev-present
    └── (none - duck-types on ev)

ev
    └── (none)
```

**Key invariant**: ev-runtime does NOT depend on ev-present. It wires emitters; it doesn't translate events to display models. That translation happens in ev-toolkit's RichEmitter.

---

## The Seam Philosophy

> "Two consumers reveal the seam. Extract what's shared, leave what's specific."

The ev ecosystem exists because:
1. **hlab** needed structured CLI output
2. **lldap-invite** revealed the same patterns
3. The shared abstraction was extracted

Each package answers one question. If you're unsure where something belongs, ask: "What question does this answer?"

---

## Output Stream Convention

```
Events → stderr (the narrative: "what's happening")
Result → stdout (the answer: structured output for pipes)
```

This enables Unix composition: `mycli deploy --json | jq .data.url`

---

## Adding New Primitives

Before adding to ev or ev-present, apply the design rule:

> "Only add a primitive if a renderer capability cannot be reliably implemented without it."

If the capability can live in `Event.data` or `Segment.tags`, it doesn't need a new primitive.
