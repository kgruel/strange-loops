# LOG

Session history for the monorepo. What happened when. Per-experiment insights
live in `experiments/LOG.md`.

---

## 2026-01-31 — DSL experiment: end-to-end proof

**The experiment.** Created real .loop/.vertex files for system monitoring,
ran `loop start`, watched facts flow through folds into ticks. The DSL works.

**What was built:**

- `experiments/monitors/disk.loop` — parses `df -h` into structured disk facts
- `experiments/monitors/proc.loop` — parses `ps` into top-10 process facts
- `experiments/monitors/system.vertex` — wires sources with Upsert/Collect folds

**Issues discovered and fixed:**

1. **Parser comma handling** — source commands like `ps -eo pcpu,pmem` were
   being reconstructed as `pcpu , pmem`. Fixed to preserve punctuation adjacency.

2. **Completion facts** — boundaries need a signal to fire. Source now emits
   `{kind}.complete` facts after each command execution. Data-driven boundaries.

3. **MappingProxyType in folds** — Fact payloads are wrapped in MappingProxyType
   for immutability. Collect/Upsert were storing these directly, breaking deepcopy
   on subsequent folds. Fixed to convert to dict before storing.

4. **CLI output buffering** — ticks weren't visible until process exit. Added
   `flush=True` for real-time output.

**The proof:**

```
$ loop start experiments/monitors/system.vertex
Discovered: disk.loop
Discovered: proc.loop
Starting system with 2 source(s)...
[disk] {'mounts': {'/': {'pct': 24}, '/dev': {'pct': 100}, ...}, 'updated': ...}
[proc] {'procs': [{'cmd': 'claude', 'cpu': 41.7}, ...], 'updated': ...}
```

Facts flow through parse pipelines → fold into state → trigger ticks on boundaries.
The declarative DSL compiles to runtime types and executes correctly.

514 tests passing (data: 245, vertex: 165, dsl: 104).

---

## 2026-01-29 — Framework collapse: peer-aware Vertex + Lens

**The collapse.** Experiments converged, patterns validated. Moved from exploration
to framework: `Vertex.receive(fact: Fact, peer: Peer) -> Tick | None`.

**What was implemented:**

1. **Lens in ticks** — `Lens(zoom, scope)` dataclass. Pairs with Projection
   (write-side vs read-side). Factory methods: `minimal()`, `summary()`, `detail()`,
   `verbose()`. Fluent: `with_zoom()`, `with_scope()`.

2. **Peer-aware Vertex** — `receive(fact, peer)` signature. Two gates:
   - Potential check: `fact.kind` must be in `peer.potential`
   - Observer-state ownership: `focus.kyle` can only be updated by kyle

3. **Per-peer focus pattern** — `{kind}.{peer}` for observer state. Concurrent
   peers don't conflict. ObserverState/ObserverActions protocols.

4. **Network concerns as facts** — discovery, failure, ordering, backpressure
   all map to fact kinds. Policy is composition-layer. Primitives unchanged.

**Key insight:** The signature change `receive(Fact, Peer)` makes the model
explicit. Origin (recorded provenance) vs peer (live context for gating).
On live input they match. On replay they might differ.

**New experiments:**
- `peer_focus.py` — per-peer observer state, no conflicts
- `lens_code.py` — Lens placement analysis
- `network_boundary_extended.py` — four network scenarios
- `peer_aware_vertex.py` — full model demonstration

131 ticks tests passing.

---

## 2026-01-28 — Loops model crystallized + persistence exploration

Explored adding persistence to experiments. The exploration dissolved multiple
concepts back into existing atoms:

| Concept | Dissolved into | Why |
|---------|---------------|-----|
| Sink | Fold state | Loops have no terminals |
| Store | Durable fold | Storage is a property, not a type |
| Witness | Peer + Vertex | Just a peer whose job is to observe and emit |
| Tap | Vertex | Emission from storage is vertex behavior |
| Memory | Boundary-less fold | Silent accumulation is a fold that never ticks |

**Key insight:** The atoms are complete. New requirements don't require new
primitives — they're configurations of existing ones.

Created `LOOPS.md` as the fundamental model document. Four satellite docs
added: `docs/VERTEX.md`, `docs/TEMPORAL.md`, `docs/PERSISTENCE.md`, `docs/PEERS.md`.
Each unpacks one aspect and references back to LOOPS.md.

Fixed Enter key bug in keyboard.py (handle LF 0x0A same as CR 0x0D).

Open naming tensions noted but deferred:
- "Peer" implies equality but delegation is hierarchical
- "Tick" implies clock time but boundaries are semantic

---

## 2026-01-28 — Peer-driven boundaries + None=unrestricted + lens distinction

`review.py`: two loops through one vertex. Health ticks at timer cadence
(passive). Review ticks when peer acks all containers (active — composition
layer sends `review.complete` sentinel).

**Peer model change**: `horizon` and `potential` default to `None` (unrestricted)
instead of `frozenset()` (empty). Constraints emerge through `delegate()`, not
upfront enumeration.

**Debug is a lens, not a horizon.** The None model exposed a category error:
"debug" was a horizon string alongside container names, but it's a rendering
mode, not a data domain. Debug panel is now a lens toggle available to any peer.

---

## 2026-01-27 — Boundary triggering implemented

Implemented boundary triggering on Vertex. `Projection.reset()` added.
`register()` gains `boundary: str | None` and `reset: bool`. `receive()`
returns `Tick | None`. Fold-before-boundary, optional reset, boundary kind
uniqueness enforced.

Vertex is sync by design — async bridge lives at composition point.
122 ticks tests.

---

## 2026-01-27 — Feedback loop closed, experiment log established

`experiments/observe.py`: first experiment that closes the feedback loop.
User interactions (j/k/enter) are Facts through the same `vertex.receive()`
as external observations.

Emergent insights captured in `experiments/LOG.md`: debug as horizon (not
infrastructure), meta-actions outside the loop, thin composition layer.

---

## 2026-01-27 — Genesis document + strata semantic tagging

Reconstructed project origin story via strata. Synthesized into `docs/GENESIS.md`.
Applied semantic tags to 58 conversations across workspaces.

---

## 2026-01-27 — Tick-to-Fact dissolved, fleet experiment

Built `experiments/fleet.py`: three-level vertex hierarchy (4 VMs → 2 regions
→ global). Ticks are a level above Facts — temporal groupings, not peers.
The question dissolved. Same primitive at every level.

Tick gained `origin` field. Vertex gained `name` parameter.

---

## 2026-01-27 — Architecture crystallization

Replaced Stream concept with Vertex (intersection of loops). Explored and
rejected Tick-into-Fact collapse. Tick gained `name` field. Full narrative
in `ARCHITECTURE-JOURNEY.md`.

---

## 2026-01-26 — Semantic journey

Monorepo naming exploration (loops vs volta vs prism). Pivot concept
crystallized (four universal atoms + cell as first surface). Peer refactored
to horizon + potential.

---

## 2026-01-26 — Structure alignment

Project structure normalized across all five libs. Per-lib CLAUDE.md and
HANDOFF.md added. Six parallel fixes merged.
