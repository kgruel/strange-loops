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
- **Fact.kind == Shape.name auto-routing**: if manual wiring becomes
  boilerplate across multiple apps, build a thin dispatch convenience.
