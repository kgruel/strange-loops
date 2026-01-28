# CLAUDE.md

This file provides guidance to Claude Code when working with the prism monorepo.

## Build & Test Commands

```bash
# Install all workspace dependencies
uv sync

# Run tests for a specific package
uv run --package peers pytest libs/peers/tests
uv run --package facts pytest libs/facts/tests
uv run --package ticks pytest libs/ticks/tests
uv run --package shapes pytest libs/shapes/tests
uv run --package cells pytest libs/cells/tests

# Run a single test file
uv run --package cells pytest libs/cells/tests/test_span.py
```

## Architecture

`prism` is a uv workspace monorepo. Five core libraries, each with one atom.

### Atoms

| Package | Atom | Structure | Question | Metaphor |
|---------|------|-----------|----------|----------|
| **peers** | Peer | name + horizon + potential | *who* | social |
| **facts** | Fact | kind + ts + payload | *what* | narrative |
| **ticks** | Tick | ts + payload | *when* | temporal |
| **shapes** | Shape | facets + folds + apply | *how* | geometric |
| **cells** | Cell | char + style | *where* | spatial |

### Data Flow

The system is loops. You are a Peer in one.

    ┌──────────────────────────────────────────────────────┐
    │  You (Peer) — your choices become new Facts          │
    │                                                      │
    ▼                                                      │
  Fact(kind, ts, payload)                                  │
    │                                                      │
    ▼                                                      │
  Vertex ── routes by kind to fold engines                 │
    │         optionally backed by Store                   │
    ▼                                                      │
  Fold engine (Shape.apply)                                │
    │                                                      │
    ├── live state ──→ Lens → Block → You ─────────────────┘
    │                              cells
    │
    └── boundary ──→ Tick(name, ts, payload)
                         │
                         ▼
                    next Vertex
                    (folds Ticks — same primitive, next level)

A Peer observes a Fact. The Fact arrives at a Vertex, which routes
it by kind to fold engines. A Shape folds facts into state. You see
state through a Lens rendered as Cells. Your choices become new
Facts — the loop continues.

At a temporal boundary, the folded state becomes a Tick — a frozen
snapshot. Ticks are a level above Facts: temporal groupings that can
enter another loop as atomic input. The receiving vertex folds Ticks,
not Facts. Same primitive at every level. Loops nest.

### Feedback Loop (Surface → Facts)

Surface (cells) is the bidirectional boundary — renders state outward,
emits interactions inward. Facts enter the loop from two sources:
external observations (a deploy happened) and your own interactions
(you pressed a key, selected an item). Both are Fact. Both arrive
at the same Vertex. The loop doesn't distinguish.

Surface emits at three strata:

    Stratum        Auto?   Kind       Example payload
    ────────────────────────────────────────────────────────
    Raw input      yes     "ui.key"      {key: "j"}
    UI structure   yes     "ui.action"   {action: "pop", layer: "confirm"}
                   yes     "ui.resize"   {width: 80, height: 24}
    Domain         no      (any)         {item: "deploy-prod"}

`Emit = Callable[[str, dict], None]` — cells defines the callback type,
the integration layer wires it to `Fact.of()` + `Stream.emit()`. No
cross-lib imports. The loop closes.

### Core Libraries (libs/)

| Package | Atom | Purpose |
|---------|------|---------|
| **peers** | Peer | Identity: name + horizon + potential. None = unrestricted; constraints emerge through delegation. The hierarchy encodes participation level (direct, delegated, automated). |
| **facts** | Fact | Observation atom: kind + ts + payload. An intentional observation — something that happened at a specific time. Kind is an open string for routing; payload structure comes from Shape. |
| **ticks** | Tick | Temporal envelope: name + ts + payload. Infrastructure: Vertex (kind routing + fold engines), Store protocol (EventStore, FileStore), Stream, Projection, FileWriter, Tailer. A Tick is a frozen snapshot at a temporal boundary — the output of folding facts through a Shape over a period. |
| **shapes** | Shape | Data contracts: Facet (name + kind), Fold (op + target), Boundary (kind + reset), Shape (facets + folds + boundary + apply). Shape.apply(state, payload) executes folds — pure dict→dict, no cross-lib imports. |
| **cells** | Cell | Terminal UI: Cell, Block, Buffer, Span, Layer, Lens, Surface |

All libraries are independent — no lib imports another. They compose in experiments.

Each lib has its own `CLAUDE.md` with detailed API, invariants, and source layout.
Each lib has its own `HANDOFF.md` with change log and open threads.

### Peer Participation

A Peer's level of participation is encoded in the delegation hierarchy,
not as a separate type. The root peer is unrestricted (None); children
act on behalf of the root with narrower horizon and potential.

    You (Peer: "kyle")                      → unrestricted (None)
      ├─ delegate("kyle/deploy-agent")      → autonomous, narrower potential
      ├─ delegate("kyle/backup-cron")       → automated, narrowest potential
      └─ delegate("kyle/subtask-worker")    → delegated, task-scoped

Stance (direct, guided, delegated, automated, observing) is an emergent
property of the topology — which peer observed the fact tells you the
participation level. No enum needed; the identity is the stance.

### experiments/

Integration layer that wires the libraries together. Contains `fleet.py` (three-level vertex hierarchy — proves tick nesting), `boundary.py` (data-driven boundaries — three semantics from one mechanism), `observe.py` (feedback loop — user interactions are Facts), `review.py` (peer actions trigger temporal boundaries — None=unrestricted peers), `daemon/` (mill — the daemon primitive), `capability.py` (capability-as-fact pattern), `archive/` (earlier experiments), and `tests/`.

### demos/cells/

Standalone demo scripts and teaching materials extracted from the cells library.

## Key Patterns

- All libs use `src/` layout with hatchling
- Workspace dependencies use `{ workspace = true }` in `[tool.uv.sources]`
- Each lib has its own pyproject.toml, tests/, and build config
- Immutable by default: frozen dataclasses, pure functions, compose don't mutate
- Shape is the contract at every boundary — describes what data looks like and how to fold it
- Projection accepts a fold callable: `Projection(initial, fold=shape.apply)` — no bridge class needed
- Facts go in, Ticks come out: Fact is the raw observation (input), Tick is the derived snapshot (output)

## Conventions

Composition conventions for wiring the atoms together. Not enforced by code —
these are patterns that keep independently-authored integrations legible and
compatible.

### Kind namespacing

Infrastructure facts auto-emitted by a lib are prefixed by origin:

    ui.key, ui.action, ui.resize     ← cells (Surface)

Domain facts (user/integration-defined) stay bare: `"container-health"`,
`"deploy"`, whatever makes sense in context. The rule: if a lib emits it
automatically, it gets a prefix. If you define it, you name it.

### Kind → Shape naming

Name your Shape after the primary Fact kind it folds. A Shape called
`"container-health"` folds Facts with `kind="container-health"`. This is a
legibility convention, not a dispatch mechanism — routing is still explicit
in your wiring code.

If boilerplate accumulates around this pattern (registering shapes, matching
kinds, auto-routing), that's the signal to add a thin convenience. Not yet.

### Fact → Shape bridge

Every Projection folding Facts through a Shape needs a thin extraction
function (~3 lines) at the composition point: pull the dict payload, add
timestamp, call `shape.apply()`. This is intentionally not a library
primitive — it lives in the integration layer because it touches both Fact
and Shape, and the atoms don't import each other.
