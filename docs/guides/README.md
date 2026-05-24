# Operational Guides — the strange-loops ladder

A progressive, hands-on path through strange-loops. Each guide is a **rung**: it
assumes the rung below it and adds one layer. Climb from a bare `Fact` in a Python
REPL up to a federated, identity-gated `loops` CLI deployment.

If the [deep dives](#related-reading) explain *what each concept is*, these guides
explain *how you actually use them, in order*.

## The ladder

The rungs follow the system's abstraction chain — but **bottom-up**, the way you
learn it, not the way you call it:

```
                                              ┌─────────────────────────────┐
  Rung 10  Identity & Federation              │ who may observe / attest    │
  Rung 09  Store Maintenance & Transport      │ move & reconcile facts      │
  Rung 08  Sources & Cadence                  │ ingest the outside world    │
  Rung 07  Reading Deeply                     │ zoom · keys · lenses        │  CLI
  Rung 06  The Fact Graph                     │ refs · cites · salience     │  (use)
  Rung 05  The loops CLI                      │ emit · read · fold          │
  ──────────────────────────────────────────────────────────────────────────
  Rung 04  Declaring Vertices in KDL          │ config declares             │  config
  ──────────────────────────────────────────────────────────────────────────
  Rung 03  Persistence & Replay               │ durable state by replay     │
  Rung 02  Vertices & Loops                   │ route · fold · fire ticks   │  engine
  Rung 01  Atoms                              │ Fact · Spec · fold ops      │  (atoms)
                                              └─────────────────────────────┘
```

The pivot is **Rung 04**: everything below it you build by hand in Python;
everything above it you declare once and drive from the command line.

## Rungs

| # | Rung | You'll be able to… | Time |
|---|------|--------------------|------|
| 01 | [Atoms: the data layer](01-atoms-the-data-layer.md) | Build a `Fact`, define a `Spec`, fold a sequence by hand | ~10 min |
| 02 | [Vertices & Loops: the runtime](02-engine-vertices-and-loops.md) | Register loops on a `Vertex`, receive facts, fire `Tick`s at boundaries | ~12 min |
| 03 | [Persistence & Replay](03-persistence-and-replay.md) | Back a vertex with `SqliteStore`, rebuild state via `replay()` | ~10 min |
| 04 | [Declaring Vertices in KDL](04-declaring-vertices-in-kdl.md) | Move from Python construction to `.vertex`/`.loop` declarations | ~12 min |
| 05 | [The loops CLI: emit, read, fold](05-the-loops-cli-basics.md) | Install `loops`/`sl`, scaffold a vertex, emit and read facts | ~12 min |
| 06 | [The Fact Graph: refs & cites](06-the-fact-graph-refs-and-cites.md) | Link facts with `ref=`, bump priors with `cite`, earn salience | ~12 min |
| 07 | [Reading Deeply: zoom, keys & lenses](07-reading-and-lenses.md) | Navigate with `--key`, switch zoom, resolve and write lenses | ~15 min |
| 08 | [Sources & Cadence](08-sources-and-cadence.md) | Author `.loop` sources, gate them with cadence, `sync` the world in | ~15 min |
| 09 | [Store Maintenance & Transport](09-store-maintenance-and-transport.md) | Slice, merge, compact, and push/pull facts across stores | ~12 min |
| 10 | [Identity & Federation](10-identity-and-federation.md) | Attribute observers, gate with `Grant`s, reason about the scope lattice | ~15 min |

## How to use this series

- **New to strange-loops?** Start at [Rung 01](01-atoms-the-data-layer.md) and climb. The
  first three rungs give you the mental model (immutable facts → folded state → durable
  replay) before any config or CLI enters the picture.
- **Already comfortable with the concepts, here to use the tool?** Jump to
  [Rung 05](05-the-loops-cli-basics.md) and read upward as needed; rungs 01–04 are the
  "why it works this way" backfill.
- **Looking up one capability?** Each rung is self-contained enough to read alone, and
  the [CLI cheatsheet](../CLI-CHEATSHEET.md) and [API reference](../api-reference.md) are
  the fast lookups once the model has landed.

Every rung ends with a **Next** link and a **See also** pointing into the deep dives, so
you can descend into theory exactly where curiosity strikes.

## Related reading

The guides are the *path*; these are the *territory*:

- **Concepts** — [VERTEX](../VERTEX.md) (routing/folding/boundaries),
  [TEMPORAL](../TEMPORAL.md) (semantic time, tick lifecycle),
  [PERSISTENCE](../PERSISTENCE.md) (durable vs ephemeral, replay),
  [IDENTITY](../IDENTITY.md) (observer, grants),
  [SCOPE-LATTICE](../SCOPE-LATTICE.md) (delegation algebra),
  [CADENCE](../CADENCE.md) (source vs cadence),
  [LENSES](../LENSES.md) (pure rendering).
- **Reference** — [API reference](../api-reference.md) ·
  [CLI cheatsheet](../CLI-CHEATSHEET.md) ·
  [configuration guide](../configuration-guide.md)
- **Orientation** — [project overview](../project-overview-pdr.md) ·
  [system architecture](../system-architecture.md)
