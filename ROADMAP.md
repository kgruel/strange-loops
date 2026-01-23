# ROADMAP

This repo is converging on a reusable package for building **interactive, streaming CLI tools** using:
- **Event sourcing** (append-only log as source of truth)
- **reaktiv** (Signals / Computeds / Effects)
- **Rich** (rendering + layout)

See also: `HANDOFF.md` (current state) and `RETROSPECTIVE.md` (why/what was proven).

---

## Vision

Build a small, sharp library that makes it easy to create “observability-grade” terminal tools:
- ingest high-rate streams (logs/events)
- keep UI responsive (debounced rendering)
- derive multiple views cheaply (reactive projections)
- support replay, persistence, and “capture this slice” workflows

## Non-goals

- Compete with full TUI frameworks (Textual-style focus/scroll/mouse/editor widgets).
- Build a generic state management library (reaktiv is the engine; this repo is the pattern + CLI ergonomics).

---

## Core Contracts (keep these true)

1. **Event log is truth.** Everything derives from the append-only store; user actions are events too.
2. **Computeds are pure.** No mutation, no I/O, no “append to deque” inside Computed bodies.
3. **Effects establish dependencies, not workload.** Effects should read *Signals* and mark the UI dirty; Computeds should be evaluated in `render()` at frame rate.
4. **Batch UI mutations.** If a keypress updates multiple Signals, use `reaktiv.batch()` so the system reacts once.
5. **Bounded memory story.** If the tool can run forever, you need retention/windowing/snapshots or incremental projections.

---

## Milestone 0: Consolidate pattern + correctness

**Goal:** make the “blessed” architecture a single path through the codebase.

Deliverables:
- All examples use `framework/` primitives (no per-example EventStore/render loops).
- No Computed side effects; no Effects that force per-event Computed evaluation.

Work items:
- Migrate `examples/http_logger*.py` onto `framework.BaseApp` (debounced render loop).
- Fix “stateful-in-Computed” patterns (e.g. request-rate tracking) by moving state into:
  - a Signal updated by ingestion, or
  - an incremental projection object updated on new events.
- Replace “list-copy updates” with version-signal pattern everywhere (already done in `framework/EventStore`).
- Add a lightweight “reactive contract” doc to `docs/` (what goes in Signal vs Computed vs Effect).

---

## Milestone 2: Projections (incremental Computed / folds)

**Goal:** scale derived state without re-scanning the full event list.

Deliverables:
- A first-class “projection” primitive that processes only new events since last frame.
- Optional retention/windowing that doesn’t break projections.
- Optional snapshotting for fast startup.

Work items:
- Design a `Projection`/`Fold` API (state + `apply(event)` + `snapshot()`).
- Provide a few built-in projections you already need:
  - per-entity state machine index
  - “last N logs per entity”
  - windowed counters / rates
- Add store retention policies:
  - “keep last N events”
  - “keep last T seconds”
  - “keep by predicate” (e.g. always keep errors)
- Add snapshot + replay helpers (write snapshot periodically; replay from snapshot + tail).

---

## Milestone 3: UI primitives (widgets + interaction)

**Goal:** make “tool ergonomics” reusable without turning into a TUI framework.

Deliverables:
- A small widget set you can compose in panes:
  - metric table, sparkline, histogram, log viewer, help overlay, status bar
- A consistent interaction model:
  - modes, selection, filter input, confirmation flows

Work items:
- Extract common pane patterns from examples into reusable render helpers.
- Standardize keyboard handling and input buffers (including help overlays).
- Decide what you will *not* build (scrolling within panes, mouse, rich text editor) and document the boundaries.

---

## Milestone 4: Real tool adapters (prove usefulness)

**Goal:** ship at least one real tool that relies on the library and stresses it.

Candidate adapters:
- subprocess supervisor / process manager (real processes)
- file tailer with structured parsing
- HTTP capture/correlation (proxy middleware)

Work items:
- Provide ingestion helpers that emit typed events.
- Use `reaktiv.Resource` for async data loads (if/when you have “select → fetch detail” workflows).
- Add “capture this slice” UX (filter → tee → replay) as a first-class feature.

---

## Milestone 5: Docs + releases

**Goal:** make it easy to pick up and use repeatedly.

Deliverables:
- “How to build a tool” guide + 1–2 minimal templates.
- A stable API policy and versioning strategy.
- Performance notes (what scales, what doesn’t, and why).

Work items:
- Write a short cookbook:
  - “new tool skeleton”
  - “add a projection”
  - “add a pane”
  - “persistence + replay”
  - “batch UI updates”
- Add a "pitfalls" section (Computed purity, Effect dependency hygiene, retention gotchas).

---

## Milestone 6: Package MVP (installable, testable)

**Goal:** turn `framework/` into a reusable package you can depend on from real tools.

Deliverables:
- Root `pyproject.toml` for this package (name TBD) and a `src/` layout.
- Examples runnable via `python -m ...` / console scripts without `sys.path.insert(...)`.
- Basic test suite (pytest) that locks down the critical contracts.

Work items:
- Choose package name and public API surface (`EventStore`, `BaseApp`, `KeyboardInput`, `FilterHistory`, `DebugPane`, `Projection`, `metrics`).
- Add tests for:
  - `EventStore` persistence/replay ordering
  - Projection advance + cursor + retention
  - debounced rendering contract (Effect may fire at event-rate, render runs at frame-rate)
  - "no Computed side effects" (convention + a couple targeted regression tests)
- Add CI (lint + typecheck + tests) once the package exists.

