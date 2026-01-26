# ROADMAP

Two parallel tracks: the **app framework** (event-sourced reactive state) and the **render layer** (cell-buffer terminal output with composable components). They integrate at Phase R4 but are independently useful before that.

See also: `HANDOFF.md` (current state), `RETROSPECTIVE.md` (why/what was proven), `docs/devtools-and-rendering-research.md` (rendering research).

---

## Why the Render Layer

Python's CLI component gap:
- **Rich** — passive renderables, no interactivity, monolithic (styling + rendering + display inseparable)
- **Textual** — full browser-in-terminal (DOM, CSS, per-widget asyncio tasks, 50k+ lines)
- **Nothing in the middle** — composable interactive components, lightweight, pick-and-choose

Go has this (Bubbletea + Lip Gloss + Bubbles). Rust has this (Ratatui + ecosystem). Python doesn't.

The render layer fills this gap: cell-buffer rendering with composable styling and interactive components, without a DOM or widget lifecycle. Each layer is independently useful.

---

## Core Contracts (keep these true)

### App Framework Contracts
1. **Event log is truth.** Everything derives from the append-only store; user actions are events too.
2. **Projections are pure folds.** No mutation, no I/O, no side effects inside apply().
3. **Version counters drive invalidation.** Render loop checks version, repaints when changed.
4. **Push topology.** Stream.emit() pushes to consumers — no polling, no batch signals.
5. **Bounded memory story.** Retention/windowing/projections for long-running tools.

### Render Layer Contracts
6. **Components are value objects.** No lifecycle, no asyncio tasks, no message queues. Just state (Signals) + render (pure function) + input handling.
7. **Styling is immutable and composable.** Styles compose via merge; assignment creates copies.
8. **Buffer is the single rendering target.** Components paint into buffer regions. No direct terminal writes.
9. **Diff is the output strategy.** Only changed cells are written. Full redraws are a bug.
10. **Layers are independent.** Style works without Buffer. Components work without the framework. Each layer is useful alone.

---

## Track 1: App Framework (existing)

### M0: Consolidate pattern — DONE
All examples on BaseApp, impure Computeds fixed, batch everywhere.

### M2: Projections — DONE
Projection base class, `store.since()`, retention via watermark.

### M3: UI primitives — DONE
All helpers + SelectionTracker, all examples migrated.

### M3.1: Debug instrumentation — DONE
- Per-projection timing, events folded, cursor lag
- Frame budget breakdown (projections vs render)
- Windowed rates (5s window, drops to 0 when idle)
- UI primitives: `compact_bar`, `sparkline`
- Store breakdown (in-memory, evicted, total, disk size)
- Debounce efficiency ratio

### M3.2: Idle-gated rendering — DONE
asyncio.Event-based wake-on-dirty. Zero CPU when idle.

### M4: Real tool adapters — NOT STARTED
Subprocess supervisor, file tailer, HTTP capture. Proves the framework on real data.
This is where direct-to-buffer rendering becomes necessary (log viewers, large subprocess output).

---

## Track 2: Render Layer (new)

### R1: Buffer + Diff + Writer — DONE
`Cell`, `Style`, `Buffer`, `BufferView`, `diff()`, `Writer`, Mode 2026.

### R2: Styling + Composition — DONE
`StyledBlock`, `join_horizontal`, `join_vertical`, `pad`, `border` (with title), `truncate`, `Align`.

### R3: Components — DONE
Frozen state + transitions + render: Spinner, Progress, List, TextInput, Table.

### R4: Framework Integration — DONE
RenderApp, FocusRing, Region, update/render/on_key lifecycle.

---

### R4.5: Port existing UIs — IN PROGRESS

**Goal:** Prove the render layer by migrating Rich-dependent UIs to render primitives. Surfaces ergonomic friction and validates the composition model on real code.

**Approach:** Composition-first (StyledBlock trees). Each port removes Rich from one more file.

**Deliverables:**
- [x] Debug panel — `framework/debug.py` returns `StyledBlock` instead of Rich `Panel`
- [ ] Process manager UI — first full app on the render layer
- [ ] Framework examples (dashboard, etc.)

**What to watch for:**
- Verbosity of `join_horizontal` for mixed-style lines — if it hurts, that's the signal for a `span()` or `line()` convenience
- Any layout that needs content-driven sizing (measure-then-place) — that's the signal for a layout helper
- Performance on large content — that's the signal for direct-to-buffer escape hatch

---

### R5: Theming — NOT STARTED (after multiple apps on render layer)

---

### R5: Theming

**Goal:** Customizable appearance without touching component logic. Only worthwhile once multiple apps share a visual language.

### R6: Direct-to-buffer components — NOT STARTED (when M4 demands it)

**Goal:** Escape hatch for performance-critical widgets (log viewer, large tables).

**When:** M4 brings real data — subprocess output, file tailing, large datasets. Composition hits its wall when visible content is a small window into thousands of rows.

**Approach:** Components accept `BufferView` directly and paint only visible rows. No intermediate StyledBlock tree. Coexists with composition — caller decides which path per component.

**What this enables that composition can't:**
- Viewport scrolling without materializing off-screen content
- O(visible) rendering instead of O(total)
- Overlapping/layered content (modals, popups)
- Cursor positioning that knows final screen coordinates

---

## Integration Point: Framework + Render Layer

Once R4 is complete, the stack looks like:

```
EventStore → Projections → Signals → Components → Buffer → Diff → Writer
     ↑                                    ↑                          ↑
  (domain)                          (reactive UI)            (terminal output)
```

At this point, `framework/` provides the state layer and `render/` provides the display layer. A tool author:
1. Defines event types and projections (domain logic)
2. Picks components and binds them to projection signals (UI logic)
3. Arranges components in a layout (composition)
4. The framework handles: event ingestion, projection advancement, component re-rendering, cell diffing, terminal output

---

## Non-goals (explicit)

- **CSS parsing/selectors** — Textual's path. Too complex, wrong abstraction for CLI tools.
- **Mouse support initially** — keyboard-first. Mouse can come later as optional.
- **Widget lifecycle/mounting** — Textual/React pattern. Components are simple objects, not managed entities.
- **Per-widget asyncio tasks** — Textual's path. Single render context.
- **Accessibility beyond terminal** — terminals have their own accessibility story.
- **Rich compatibility layer** — clean break. Rich is useful as reference, not as dependency for render/.

---

## Decision Log

| Decision | Chosen | Over | Why |
|----------|--------|------|-----|
| Rendering approach | Cell buffer (Ratatui) | String diff (Bubbletea), Compositor (Textual) | Minimal writes, simple model, no DOM needed |
| Component model | Signals + render() | TEA (Model/Update/View), Widget lifecycle | Direct reactive bindings, no message passing overhead |
| Styling | Immutable Style objects | CSS classes, Rich markup | Composable, no parser, no cascade |
| Layout | Explicit sizing first | Flex/constraint solver | Simpler to implement and reason about |
| Rich dependency | None in render/ | Reuse Rich's Style/Segment | Clean separation, independently useful |
| Current display | Stay on Rich Live | Own output now | Value is in state layer; render layer grows in parallel |
| Rendering default | Composition (StyledBlock tree) | Direct-to-buffer first | Inspectable, transformable, flexible layout; direct-to-buffer is escape hatch for large datasets |
| Port strategy | Composition-first, usage-driven convenience | Design abstractions up front | Let real ports reveal what ergonomic shortcuts are needed |
