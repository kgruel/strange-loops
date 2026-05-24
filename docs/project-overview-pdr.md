# Project Overview & Product Design Rationale

> **strange-loops** — a system for focusing attention.
> Observations flow in, accumulate into state, boundaries resolve, conclusions
> flow out. The conclusions re-enter as new observations. The loop closes
> through the observer.

This document orients a new reader: what the project is, the design rationale
behind its shape, and where to go next. For the conceptual paradigm in full see
[`../STRANGE-LOOPS.md`](../STRANGE-LOOPS.md); for the architectural decomposition
see [`../ARCHITECTURE.md`](../ARCHITECTURE.md) and [`system-architecture.md`](system-architecture.md).

> **Status caveat (from the repo README):** this codebase is shared candidly as
> work-in-progress, not as a polished release. Treat it as a working substrate,
> not a finished product.

---

## What it is

strange-loops is a Python monorepo implementing a small, opinionated runtime for
**temporal state accumulation**. Raw observations (`Fact`s) are routed by kind
into fold loops, accumulate into derived state, and — when a semantic *boundary*
fires — collapse into a `Tick` snapshot. Ticks can flow back in as new facts,
closing the loop. The same accumulated data can be viewed by different observers
through different *lenses* at different depths.

The system is delivered primarily as a CLI (`loops`, aliased `sl`) plus a set of
reusable libraries. Most user-facing work is **configuration, not code**: you
declare `.vertex` and `.loop` files in a KDL dialect and the CLI runs them.

```
config (declare)  →  loops CLI (use)  →  engine (runtime)  →  atoms (data)
~/.config/loops/     emit/fold/stream    Vertex, Store        Fact, Spec
```

## The paradigm in one screen — three shapes, four properties, one pattern

**Three shapes** (the data atoms, in [`libs/atoms`](../libs/atoms)):

| Shape | What it is |
|-------|-----------|
| **Fact** | An immutable observation: `kind` + `ts` + `payload` + `observer` (+ `origin`). |
| **Spec** | A fold contract: input/state fields, fold rules, and a boundary declaration. |
| **Tick** | A frozen snapshot produced when a boundary fires: `name` + `ts` + `payload` + `origin` + `since`. |

**Four properties** (the invariants that make the model tractable):

1. **Immutable** — facts never change; state is *derived* by replaying facts.
2. **Append-only** — observations accumulate forever; nothing is deleted.
3. **Unidirectional** — facts in → state → ticks out. The loop closes through the
   *observer* re-emitting, not through hidden mutation.
4. **Observer-attributed** — every fact carries *who* observed it, enabling
   identity-scoped views and federated trust.

**One pattern** (the runtime, in [`libs/engine`](../libs/engine)): the **Vertex**.
A Vertex routes facts by kind to fold loops, accumulates state through Specs, and
emits Ticks at boundaries. Ticks flow out as facts into other vertices — or back
into the same one. The "strangeness" is that multiple observers focus on the same
substrate through their own lenses, and conclusions re-enter as observations.

## Design rationale — why it's built this way

| Decision | Rationale |
|----------|-----------|
| **Immutable facts + replay over mutable state** | Auditability and time-travel come for free; state is always reconstructable, so persistence is an append-only log. See [`PERSISTENCE.md`](PERSISTENCE.md). |
| **Semantic boundaries, not clock ticks** | "When does a cycle complete?" is a domain question (a session ends, N events arrive, a threshold is crossed), not a wall-clock one. Boundaries make time *meaningful*. See [`TEMPORAL.md`](TEMPORAL.md). |
| **Observer as a first-class field, not auth metadata** | Identity is *participatory* — it shapes what you see and attribute — rather than a gate bolted on top. Grants narrow scope via a capability lattice. See [`IDENTITY.md`](IDENTITY.md), [`SCOPE-LATTICE.md`](SCOPE-LATTICE.md). |
| **KDL config as the primary surface** | The common case (declare a source, a fold, a boundary) should not require Python. The DSL is a pure grammar layer with no runtime coupling. See [`configuration-guide.md`](configuration-guide.md). |
| **Rendering split out (lenses + external `painted`)** | The same vertex is viewed at MINIMAL/SUMMARY/DETAILED/FULL fidelity by different observers; rendering is a pure function of data, never entangled with accumulation. See [`LENSES.md`](LENSES.md). |
| **ULID primary keys** | Time-sortable IDs let independent stores merge by `INSERT OR IGNORE` and interleave chronologically with `ORDER BY id`. Federation is a property of the key, not a protocol. |
| **Strict library boundaries** | `atoms` has zero deps; `engine` depends on `atoms` (type-checking only) + `lang`. The boundary is enforced by an AST test (`tests/test_architecture.py`), keeping the data layer pure and portable. |

## Who it's for / use cases

- **Self-tracking knowledge work** — the monorepo *dogfoods* loops: architectural
  decisions, threads, frictions, and hypotheses accumulate in project vertices
  across sessions (see [`../CLAUDE.md`](../CLAUDE.md)).
- **Homelab monitoring** ([`apps/hlab`](../apps/hlab)) — DSL-driven container/stack
  status, Prometheus alerts, media audits (early experiment, archived).
- **Task orchestration** ([`apps/tasks`](../apps/tasks)) — tasks modelled as loops;
  workers run in git worktrees and coordinate through a shared SQLite fact store.

## Repository at a glance

```
libs/
  atoms/   Fact, Spec, Source, Parse, Fold — the three shapes and ingress
  lang/    KDL loader + validator for .loop/.vertex files
  engine/  Vertex, Loop, Tick, Store, Peer, Grant — the pattern and persistence
  sign/    JWKS + signature primitives for federated attestation
  store/   Store operations — slice, merge, search, transport
apps/
  loops/   CLI — emit, fold, stream, read, store across vertices (sl / loops)
  hlab/    Homelab monitoring — DSL-driven status, alerts, media
  tasks/   Task orchestration — tasks as loops, workers in worktrees
docs/      Deep dives + this generated doc set
```

~35K LOC of Python across 8 workspace packages. Python ≥3.11, MIT-licensed,
distributed on PyPI as `strange-loops`. Terminal rendering lives in the separate
[`painted`](https://github.com/kgruel/painted) package.

## Where to start

| Intent | Go to |
|--------|-------|
| Understand the paradigm | [`../STRANGE-LOOPS.md`](../STRANGE-LOOPS.md) |
| Understand the architecture | [`system-architecture.md`](system-architecture.md), [`../ARCHITECTURE.md`](../ARCHITECTURE.md) |
| Map the code | [`codebase-summary.md`](codebase-summary.md) |
| Query or emit (CLI) | [`CLI-CHEATSHEET.md`](CLI-CHEATSHEET.md), [`api-reference.md`](api-reference.md) |
| Write `.vertex` / `.loop` config | [`configuration-guide.md`](configuration-guide.md) |
| Conventions & how to contribute | [`code-standards.md`](code-standards.md) |
| Run the tests | [`testing-guide.md`](testing-guide.md) |
| Deep concept dives | [`VERTEX.md`](VERTEX.md), [`TEMPORAL.md`](TEMPORAL.md), [`PERSISTENCE.md`](PERSISTENCE.md), [`IDENTITY.md`](IDENTITY.md), [`LENSES.md`](LENSES.md) |

---

*See also: [system-architecture.md](system-architecture.md) · [codebase-summary.md](codebase-summary.md) · [code-standards.md](code-standards.md)*
