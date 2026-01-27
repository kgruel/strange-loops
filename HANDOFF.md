# HANDOFF

Monorepo overview. Per-library details live in each lib's own HANDOFF.md.

## Library Handoffs

| Library | Handoff | Focus |
|---------|---------|-------|
| **peers** | `libs/peers/HANDOFF.md` | Scoped identity |
| **facts** | `libs/facts/HANDOFF.md` | Observation atom |
| **ticks** | `libs/ticks/HANDOFF.md` | Temporal infrastructure |
| **shapes** | `libs/shapes/HANDOFF.md` | Data contracts + fold rules |
| **cells** | `libs/cells/HANDOFF.md` | Terminal UI |

## Cross-cutting

### 2026-01-26
Project structure alignment across all five libs. Normalized to a single
canonical pattern: hatchling build backend, `[dependency-groups]` for dev
deps, `>=3.11` Python, identical `.gitignore` files, `py.typed` markers,
canonical `pyproject.toml` section ordering, `authors` field, and README
structure (Atom/Usage/API). Per-lib CLAUDE.md and HANDOFF.md files added
to each lib root.

Pipeline experiment reset: old pipeline.py deleted, new test_atoms.py with
14 tests validating full pipeline stage by stage. Fact->Shape bridge is a
3-line extraction function at the composition point.

Experiments archived into `experiments/archive/` (01_cells_demo,
02_spec_driven, 03_atomic_pipeline). All git mv, history preserved.

Container app (`experiments/containers.py`): first end-to-end wiring of
all five atoms. Docker polling -> Fact.of("container-health") -> Stream ->
Projection(fold=shape.apply) -> shape_lens -> Surface. Peer in the header.
Pipeline validated (all imports resolve, shape folds correctly, projection
wires). Needs Docker daemon (Colima) to run live.

External review response — six parallel changes merged:

- **Shape.apply() purity fix**: `dict(state)` → `copy.deepcopy(state)`.
  Collect and upsert folds were mutating nested containers in-place, breaking
  snapshot independence. Three new mutation-detection tests added.
- **Surface lifecycle hooks**: `on_start`/`on_stop` added as optional
  `LifecycleHook = Callable[[], Awaitable[None]]`. Unblocks containers.py
  demo (on_start now wirable for async setup like Docker polling).
- **Fact.ts → epoch float**: Removed all datetime machinery from facts.
  `ts` is now `time.time()` — no timezone handling, no isoformat. Display
  formatting is caller's problem.
- **UI kind namespacing**: Surface auto-emitted kinds renamed to `ui.key`,
  `ui.action`, `ui.resize`. Domain kinds stay bare.
- **Tooling normalization**: ruff + ty + pytest-cov + coverage config added
  to all five libs. Previously only facts had lint/type tooling.
- **Doc drift fixes**: Stale "Field/Form" refs → "Facet/Fold/Shape" in
  shapes README + pyproject.toml. Test counts updated across lib docs.
- **Ticks async cleanup**: `run_until_complete()` → `async def` + `await`
  in test_tick.py. Removed deprecated event loop usage.

Conventions codified in root CLAUDE.md (new section). See below.

### Patterns
- **Fact->Shape bridge**: documented as convention in CLAUDE.md. Thin
  extraction function (~3 lines) at the composition point. Intentionally
  not a library primitive — lives in integration layer.
- **Kind->Shape routing**: decided as weak convention. Name your Shape after
  the primary Fact kind it folds. Legibility only, not dispatch. If
  boilerplate accumulates, revisit as a thin convenience.
- **Kind namespacing**: infrastructure facts prefixed by origin (`ui.*` from
  cells). Domain facts stay bare. Convention, not enforcement.
- **"Personal semantic Kafka"**: Same plumbing (streams, projections, stores),
  reimagined for personal context without enterprise cruft.

### Deferred
- **CI**: no CI visible, no lockfile committed. Deferred until conventions
  stabilize.
- **Peer scope interpretation**: whether scope is documentary, stream filter,
  or capability routing. Needs more integration examples before deciding.
  NOTE: see "Peer horizon + potential" below — this has evolved.
- **Fact.kind == Shape.name auto-routing**: if manual wiring becomes
  boilerplate across multiple apps, build a thin dispatch convenience.

### 2026-01-26 — Semantic journey: naming, loops, and intersection

Extended conceptual session reworking the monorepo's identity, vocabulary,
and architectural model. No code changes to libs — all conceptual, with
docs and threads updated. One experiment (daemon primitive) implemented
via subtask.

#### The naming arc

Started from an external conversation proposing "loops" as the monorepo
name. Pushed back: "loops" is a CS primitive (event loops, game loops,
for-loops), accurate but not distinctive, would collide with every
programming tutorial. Explored alternatives systematically, looking for
a name that carries four properties: feedback is first-class, append-only
accumulation, closed causal circuit, observation is participation.

Candidates explored with trade-off analysis:
- **loops**: accurate, generic, collides with CS primitives
- **turn**: semantically precise, flat as brand, "turns/facts" verb clash
- **coil**: accumulation through circulation, no observation property
- **gyre**: self-sustaining current, distinctive but obscure
- **helix**: loop that advances, DNA brand, Helix editor collision
- **reverb**: hits all four properties, audio-library assumption
- **volta**: turn that changes meaning (poetry/music), literary+scientific
  depth, distinctive, low collision

Tentatively settled on **volta** — developed full conceptual framing
(atoms table, vocabulary, data flow diagrams). Then the conversation
continued and circled back.

**The argument that brought it back to loops**: The atoms provide
specificity (Fact, Peer, Shape, Cell, Tick). The container provides
universality. Naming the medium after what it IS rather than what it
EVOKES is the honest choice. Loops is ontology, not brand.

The case for loops (from first principles, not vocabulary utility):
- Everything is loops, from Planck scale to Big Bang
- One-way time + entropy = loops occur naturally at every scale
- The "genericness" IS the feature — it reframes what people already know
- "The election loop" is immediately graspable even if unfamiliar
- Your life is a loop (birth → death) nested in greater loops
- Spiraling is a loop with decreasing tick interval
- The atoms discriminate; the container universalizes

**Current state**: actively reconsidering loops. Volta captured in
THREADS.md as alternative. Decision not yet made.

#### The pivot concept

Identified that the volta/loop has two halves separated by shaped state:

    facts, ticks, peers, shapes    ← below (universal)
    ───────────────────────────
          shaped state (dict)      ← the pivot
    ───────────────────────────
    surface (cells, html, api)     ← above (paradigm-specific)

Four atoms are universal. Cell is the first surface specialization, not
the fifth universal atom. This reframes cells as "the first surface" and
opens the door for future surfaces (web, API, docs).

#### Cells architecture analysis

Explored the cells dependency graph in detail. Finding: the terminal-
specific code is exactly three files (writer.py, keyboard.py, app.py).
Nothing else in the lib imports from them. Everything else — Cell, Style,
Block, Buffer, Span, Lens, Layer, compose, components — is terminal-
agnostic.

Block is the natural serialization boundary. Added two threads to cells
THREADS.md: "Block serialization — multi-format output" and "Grid surface
vs terminal adapter." The rendering side is fully portable today. The
interaction side (Layer assumes key:str input) would need an event
abstraction to generalize.

#### Strata as temporal accumulator

Connected strata (~/Code/strata, personal LLM analytics engine) to the
conceptual model. strata embodies the same philosophy: observation is
first-class, append-only, meaning derived at query time.

Key insight: **volta/loops is always real-time.** Not because facts are
new, but because the observer is always in the present. Replaying a
stored session IS starting a new loop — your observation creates new
meaning. strata bridges loops across time by archiving facts from past
loops and making them re-enterable.

Direction: strata is part of the flow, not separate from it. Integration
is protocol adoption (emit facts, register as peer), not absorption.

Tagged origin conversations in strata: `origin:prism-monorepo`
(01KFXBA6WMEM, 01KFXBA8CQQ3, 01KFXBA5B1B2).

#### The unique contribution (crystallized)

After extensive iteration, identified what this system uniquely provides:

**Immutable time is what makes loop intersection possible.**

If facts could be mutated, loops couldn't safely share them. Because
the past already happened, a loop's boundary output can safely enter
another loop as input. No coordination, no locking, no conflict. The
append-only nature of facts IS the concurrency model.

The synthesis no existing framework provides:
- FRP: signals/reactive updates, but signals are mutable
- DES: event-driven state, but events consumed not accumulated
- Event sourcing: append-only history, but storage pattern not loop model
- OODA: observe-act recursion, but decision framework not temporal system

This system: facts immutable + grounded in time + projections fold to
state + observer is participant + loops intersect at boundaries. The
combination enables loop intersection as a first-class concept with
concurrency for free.

**Semantic time**: time structured by meaning, not clocks. Boundaries are
"the agent finished" or "the deploy succeeded," not "1000ms elapsed."
How you think about time away from a screen — episodes with meaning,
overlapping, nesting, fuzzy at edges.

#### Re-envisioned atoms

From "loops that intersect at immutable boundaries," re-derived every atom:

| Atom | Refined definition | Role |
|------|-------------------|------|
| **Fact** | kind + ts + payload. Immutable. | What makes intersection safe. |
| **Peer** | name + horizon + potential. | Who's in the loop. What they see, what they can do. |
| **Shape** | facets + folds + apply. Pure. | How facts become meaning. The loop's fold. |
| **Cell** | char + style. Bidirectional. | Where the loop touches human reality. First surface. |
| **Tick** | A boundary Fact. | Where loops intersect. One loop's exhale, another's inhale. |

Key refinements:
- **Peer: horizon + potential** replaces "scope." Horizon = what you can
  see in history. Potential = what you can emit/do. Delegation = share a
  slice of your potential. More precise than overloaded "scope."
- **Tick as boundary Fact**: a Tick is a Fact that a Projection emits.
  Not a separate type — a fact with a special role. Makes the system
  fractal: no difference between high-level and low-level logic.
- **Capability-as-Fact**: a capability is an immutable Fact that grants
  a Peer potential. Authorization is event-sourced. Granting = emitting
  a capability fact. Revocation = emitting a revocation fact. Shape folds
  both into current potential. Complete audit trail for free.

#### "Stream" vocabulary questioned

The "stream" metaphor doesn't fit the loops model. Streams imply flow
(A→B, pipeline). In loops, there are no pipelines — there are loops that
touch at boundary points. Facts circulate within a loop and occasionally
cross into other loops at boundaries.

Current ticks lib vocabulary needs review:
- Stream → loop intersection (where loops receive facts from other loops)
- Projection → loop fold (how a loop accumulates meaning)
- Store → loop memory (where boundaries are persisted)
- Tailer → loop replay (re-entering past boundaries as new facts)

The ticks library is "where loops meet" — the intersection library. Open
question: is "ticks" still the right name, or does it need to shift?

#### Daemon primitive (subtask: daemon/open-projection)

Implemented via subtask. Status: review. Files:
- `experiments/daemon/mill.py` — stdin facts → fold via shape → stdout ticks
- `experiments/daemon/README.md` — what it is, why it's atomic, composability
- `experiments/daemon/examples/` — counter.shape.json, sum.shape.json

The daemon IS a loop: receive → fold → emit → repeat. A Unix filter that
never exits. Composes via pipes (chain mills, fan out, persist with tee).
Merge pending review.

#### Integration vision

Full workflow vision captured in THREADS.md: you sit down, a tick starts,
you connect to event streams, Claude delegates agents, background events
are recorded but not projected into your lens, your surface lets you
toggle streams on/off, everything feeds back.

Key concepts:
- "Bring X into your loop" = protocol adoption (emit facts, register as
  peer), not absorption
- Stream selectivity: everything is recorded, your lens shows what YOUR
  tick is focused on
- Tick lifecycle: clean close, dirty close, implicit close
- Ticks daemon: long-running process that maintains loops (the missing
  infrastructure)

### Open questions for next session

1. **Monorepo name**: loops vs volta vs keep prism. The argument for
   loops is ontological (it's what reality is). The argument for volta
   is brand (distinctive, story). Decision pending.

2. **Peer: horizon + potential**: ✅ Resolved. `Scope(see, do, ask)` replaced
   with `horizon` + `potential` directly on `Peer`. `ask` collapsed into
   `potential`. `grant`/`restrict` operate on `Peer`. See `libs/peers/`.

3. **Capability-as-Fact**: Direction demonstrated in `experiments/capability.py`.
   `peer-potential` Shape folds grant/revoke facts into current potential.
   Revocation = fact with `granted=False`. Full audit trail via collect fold.

4. **Ticks identity**: Is "ticks" still the right name for the library
   that provides loop intersection infrastructure? The Tick data type
   may collapse into Fact. The library is about how loops operate and
   connect, not about "ticks" per se.

5. **Daemon primitive merge**: Review experiments/daemon/ from subtask
   daemon/open-projection. Merge if it looks right.

6. **Ticks daemon architecture**: What does the real daemon look like
   beyond the mill primitive? Process model, connectivity, peer
   registration, tick boundary management.
