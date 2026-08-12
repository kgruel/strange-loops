# ARCHITECTURE

The implementation of the strange-loops paradigm in Python. The paradigm is
three shapes (Fact, Spec, Fold), four properties (append-only, participatory,
boundary-driven, compositional), one pattern: facts flow in, folds accumulate,
boundaries resolve, ticks flow out. This document is how and why those are
instantiated as software. (Paradigm root statement:
`observation:paradigm/strange-loops-root-statement` in the project store.)

## Loops as protocol

Loops is a **protocol** — a shape (`Fact`, `Tick`, `Cascade`, `Observer`,
`Grant`) with operational properties (participatory observation, append-only
storage, fold-derived state, boundary-driven ticks) — that any implementation
can honor. This Python codebase is one instantiation; it is not the
definition. The definition lives in the shape and the properties.

Two consequences fall out:

- **Same-language consumers** import the libraries directly. They share the
  Python implementation, the conventions, the test infrastructure. The
  protocol holds because the code holds.
- **Cross-language consumers** implement the protocol over the wire — Facts
  serialized as JSON, traversal verbs as a documented API, storage and
  transport as their own concern. They share the shape without sharing
  implementation. The protocol holds because the shape is portable.

Both are valid; neither is privileged. Multiple implementations are expected
in any sufficiently durable ecosystem — peer homelabs in different stacks,
embedded subsystems with different constraints, alternate runtimes for
research and replay. The shape survives across them because the shape is
small, the substrate is thin, and the trust attaches to the fact-stream
rather than to any specific implementation's enforcement.

This framing is what makes the system trivially portable in a deeper sense
than "the language is portable." The paradigm is portable; the paradigm is
what matters. (The operational consequences are worked out in the
trust-as-substrate essay, `docs/dev/essays/2026-05-13-on-trust-as-substrate.md`
— a local dev note, not tracked here.)

## Why Python

Not because Python is fast, or because the ecosystem demands it. Because the
developer can see the shape of the code and fold out expectations without
reading it. Python is readable at a glance — the structure of a frozen
dataclass, the signature of a pure function, the flow of a pipeline. When
you're building a system for focusing attention, the implementation language
needs to not fight the focus. Python gets out of the way.

This also means the system is trivially portable. Everything is immutable,
append-only, unidirectional. There's no mutable state to coordinate, no
concurrency model baked in, no framework coupling. The Python is one
instantiation. The paradigm is what matters.

## Libraries

Six libraries in `libs/`. Each owns one concern. The runtime dependency graph is
`_LIB_ALLOWED_RUNTIME` in `tests/test_architecture.py` — everything not listed
there is forbidden, and the test is the authority:

```
atoms    ──→ ()
lang     ──→ ()
sign     ──→ ()
engine   ──→ lang, atoms
store    ──→ engine
custody  ──→ sign, engine
```

`X ──→ Y` reads *X imports Y at runtime*. painted is not in this graph — it
lives in its own repo and arrives as a versioned PyPI dependency (see below).

**atoms** — The ingress shapes as code. Fact and Spec as frozen dataclasses; the
third shape, Tick, lives in engine, because a Tick is a runtime output rather
than something you configure. Source as ingress configuration. Parse vocabulary (11 ops: Split, Pick, Rename, Coerce...) for
shaping raw input. Fold vocabulary (10 ops: Latest, Count, Sum, Collect,
Upsert...) for accumulating state. `Spec.apply(state, payload) → state` is pure
— deep copies, folds, returns. Zero external dependencies, stdlib only
(enforced by Rule 6).

**engine** — The pattern as code. Vertex routes facts by kind to fold engines.
Loop executes Spec.apply, tracks state, fires at boundaries. SqliteStore provides
durable append-only persistence, the tick hash chain, and the signing injection
points (`tick_signer`, `fact_signer`, `verify_chain`/`verify_facts` — callables
in, never an import of the crypto). StoreReader provides read-only inspection.
Peer/Grant provides identity and gating policy (implemented; no in-repo consumer
yet — vouch is the forcing function). The compiler translates lang AST into
runtime vertices. Engine imports lang at module scope for AST types and atoms
through function-local lazy imports.

**lang** — Configuration as code. KDL parser for `.loop` files (source
definitions) and `.vertex` files (vertex configurations). Pure grammar — no
runtime types, no execution. Produces frozen AST dataclasses. Validates shape
inference through parse pipelines. The only external dependency is `ckdl`.

**store** — Maintenance as code. Slice, merge, receive, compact, transport
(push/pull), and rebirth for vertex store databases. Operates on the same SQLite
databases that engine writes; it imports engine for `tick_row_hash` so chain
hashing stays single-sourced. ULID primary keys make cross-database dedup trivial
— same fact in two stores has the same ID, merge is `INSERT OR IGNORE`. Search is
*not* here: FTS5 lives behind engine's vertex read interface.

**sign** — Cryptographic primitives as code. RSA `KeyStore` with
`load_or_generate`, JWT `mint`/`verify`, JWKS and OpenID-configuration document
building, and `sign.ed25519` for detached digest signatures with domain
separation. Deliberately loops-agnostic — it knows nothing of Fact, Tick, or
vertices, which is what lets vouch, pile, and comms share it. Depends on
`cryptography`, `pyjwt`, `python-ulid`; no internal loops deps.

**custody** — Signing composition as code. One module, and the place where sign
meets engine's injection points. Owns the domain-separation constants
`loops-tick-v1`/`loops-fact-v1` (string-pinned here by Rule 8 — import them,
never re-hardcode); the `keys/` custody layout co-located with the store it
signs; `ensure_signing_key` as the single minting entry point; and the
signer/verifier builders engine's callables expect. Engine never imports custody
— injection, not import. Apps compose the two.

**painted** — Lenses as code, and no longer in this repo. Terminal rendering
primitives (Cell, Span, Line, Block, Style), composition (join, pad, border,
truncate), and the `run_cli` harness that wires zoom levels and output modes into
a standard CLI pattern. Lenses are functions: `(data, zoom, width) → Block`. It
lives at [painted](https://github.com/kgruel/painted) and is consumed as a
versioned PyPI dependency, pinned in the root `pyproject.toml`. Rendering changes
happen upstream, not here.

## Layers — the instrument families

The libraries group into layers by **role** — which part of the communication
problem each serves. The mapping follows Weaver's three levels of the
communication problem (instrument-family survey, 2026-07-26; see
`design:architecture/surfacing-layer-charter` in the project store):

| Layer | Weaver level | Concern | Lib members |
|-------|--------------|---------|-------------|
| **record** | A — technical | What happened: accuracy of capture, storage, replay | atoms, lang, engine, store |
| **view** | A — technical | Faithful presentation of what happened | painted (external repo) |
| **surfacing** | C — effectiveness | Conduct and authority: host orchestration, coordination, attestation | sign, custody |
| **relevance** | B — semantic | What matters: judgment over the record | *deliberately none — see below* |

A layer is a **designation, not a package** — the record layer is four
libraries, not one. Membership lives in this table and in the import DAG
(`tests/test_architecture.py`, Rule 11); a new library must declare its
layer or the suite fails. Apps take no layer assignment — they are
compositions by construction (the loops CLI hosts record reads through view
lenses under surfacing conduct). App-side surfacing occupants (the TUI
shell, cross-implementation protocol artifacts) belong to the layer by role
without being libs.

**Why the record layer can make correctness claims:** it keeps Shannon's
discipline of excluding semantics. FTS matches, it does not rank. Folds
project, they do not judge. Accuracy is provable in the record layer
precisely because meaning is out of scope there.

**Surfacing is relational, not correct.** Host shells, protocol
coordination, signing — these are reliable-or-not, conducted-well-or-not;
they make claims about conduct and authority, not about truth. The layer
exists as a *name* because its absence caused misfilings: with only record
and view built, relation-shaped code got filed into the nearest substance —
`run_cli`/`add_cli_args` into painted (a view home), signing composition
into the CLI app before `custody` was carved out. The filing function
failed for lack of a name; the name is the fix.

**Relevance is deliberately homeless.** Judgments about what matters
(ranking, staleness, salience) have so far dissolved into the substrate as
*declarations* the record layer executes — lifecycle declarations were the
first. Whether relevance becomes a package or stays a declaration
vocabulary is decided on evidence, after the third declaration-executed
judgment lands, not before. Until then nothing claims the relevance name.

Two rules of motion:

- **Record never imports surfacing.** Level A stays pure of Level C,
  enforced structurally (Rule 11). Surfacing imports record freely — that
  is the direction conduct faces the record.
- **Relocation-on-pull.** Code moves into a layer's package when a consumer
  pulls on the seam, never as a guilty refactor. The CLI-host extraction
  from painted happens when the TUI shell pulls on it, gated as its own
  painted-major coordination.

## The Concrete Data Flow

The paradigm says: observation → vertex → accumulate → boundary → tick. Here's
what that looks like in this implementation:

```
Shell command (df -h, curl, docker ps, ...)
      │
      ▼
   Source (atoms)
      command → stdout → format (lines/json/ndjson/blob)
      → parse pipeline [Split, Pick, Rename, Coerce]
      → Fact(kind="disk", ts=now, payload={fs: "/dev/sda1", use: 50}, observer="monitor")
      │
      ▼
   Vertex (engine)
      │
      ├── SqliteStore.append(fact)        # durable if configured
      │
      ├── route by fact.kind
      │     ├── "disk"   → disk Loop     (Spec.apply, fold state)
      │     ├── "health" → health Loop   (Spec.apply, fold state)
      │     └── "deploy" → deploy Loop   (Spec.apply, fold state)
      │
      └── boundary check
            │
            ├── data-driven: fact.kind == boundary.kind → fire
            ├── count-driven: N facts accumulated → fire
            └── manual: vertex.tick("name", now) → fire all
                  │
                  ▼
               Tick(name="disk", ts=now, payload={...}, origin="status")
                  │
                  ├── SqliteStore.append(tick)
                  ├── downstream vertex (tick.payload becomes fact.payload,
                  │                      tick.origin becomes fact.observer)
                  └── observer sees via lens → acts via fact emission
```

## Configuration: KDL

`.loop` files define sources. `.vertex` files define vertices. KDL is the surface
syntax — structured enough to express routing, folds, and parse pipelines;
readable enough that the configuration is self-documenting.

```kdl
// status.vertex
vertex "status" {
    store "./data/status.db"

    loop "health" {
        fold "events" collect max=10
        boundary when="health.close" reset=true
    }

    source "disk.loop"
    source "health.loop"
}
```

```kdl
// disk.loop
source {
    command "df -h"
    kind "disk"
    observer "monitor"
    format "lines"
    every 60

    parse {
        skip startswith="Filesystem"
        split
        pick 0 4
        rename 0="filesystem" 1="use_pct"
        coerce use_pct="int"
    }
}
```

Lang parses these into frozen AST dataclasses. Engine's compiler translates AST
into runtime vertices. The separation means lang is portable — it could target
a different runtime without changing the grammar.

## Persistence: SQLite

Append-only SQLite with WAL mode. The schema:

```sql
facts(id TEXT PK, kind, ts, observer, origin, payload JSON, signature)
ticks(id TEXT PK, name, ts, since, origin, payload JSON,
      prev_hash, window_start, fact_cursor, window_hash, signature)
```

Indexes on `facts(kind)`, `facts(ts)`, `ticks(name)`, `ticks(ts)`. A
`store_meta(key, value)` table carries per-store markers (own lineage, and
similar), and a `facts_fts` FTS5 virtual table is a derived index written
*only* by the explicit `sl store reindex` verb — reads never write, provably
(byte-identity pinned since 0.9.0; a stale or missing index is disclosed with
a substring fallback, never a silent empty result). The trailing columns on
both tables are the attestation era: `signature`
holds the detached Ed25519 signature over the row's canonical digest, and
`prev_hash`/`window_start`/`fact_cursor`/`window_hash` are the tick chain — each
tick commits to its predecessor and to the fact window it summarizes. All of them
are nullable, which is what makes the pre-signature era honest rather than
broken. Canonical form is JCS (RFC 8785).

**Why SQLite:** Embeddable (no server), concurrent reads via WAL, FTS5 for
full-text search, battle-tested durability. The store is just a file — copy it,
merge it, slice it, push it to another machine.

**Why ULID:** Globally unique, time-sortable, deterministic for the same fact.
Makes cross-database merge trivial — `INSERT OR IGNORE` on the primary key. Ids
are supplied by the writer (python-ulid) on every insert; `id` declares no
`DEFAULT`. The schema once carried `DEFAULT (ulid())`, which required the
sqlite-ulid C extension and existed only to cover inserts that omitted an id —
removed 2026-05-16 once every path supplied one.

**Why append-only:** The paradigm requires it. Facts don't change. State is
derived by replaying facts through folds. No updates, no deletes. Correction
by re-emission (latest-per-key fold resolves conflicts).

**State is never stored.** Fold state is always derived. Replay the facts through
the spec, get the state. This means spec changes are safe — replay with the
new shape, get updated state. No migrations.

Three store implementations serve different needs:

| Store | Backing | Use case |
|-------|---------|----------|
| `SqliteStore` | SQLite (WAL) | Production — concurrent reads, durable |
| `EventStore` | In-memory + optional JSONL | Tests, ephemeral workloads |
| `FileStore` | JSONL | Append-heavy, memory-constrained |

## Rendering: painted

The terminal is the shared focal plane — the surface where human and AI
observers can both focus attention on the same data at the fidelity level
that matters to each.

painted provides the primitives, from its own repo — change them there, not here:

**Composition stack:** Cell → Span → Line → Block. Each level composes from
the level below. Block is the primary unit lenses produce.

**Lens pattern:** `(data, zoom, width) → Block`. Same function signature
everywhere. The data is vertex state. The zoom is fidelity level. The width
is the terminal. The output is styled text.

**Fidelity levels:** MINIMAL (single line — counts, summary stat), SUMMARY
(enough to orient, not drown), DETAILED (metadata, well-known keys), FULL
(everything, expanded). Progressive disclosure of attention.

**run_cli harness:** Wires a lens to a CLI command. Handles zoom flag, output
mode (text/JSON/plain), terminal width detection, error display. Every display
command in every app uses this — fetch data, apply lens, render.

**Why terminal-native:** Not aesthetic preference. The terminal is where the
collaboration happens. Both observers — human reading styled output, AI parsing
structured output — use the same tool on the same data. JSON output mode means
the same lens serves both. The terminal is the lowest-common-denominator focal
plane that works for everyone in the loop.

## Identity: Peer/Grant

Implemented in engine. The current shape (Peer-as-convenience-bundle with
horizon/potential; Observer-as-string on Fact; Grant separated as policy at
Vertex) is the result of the Jan 27–30 dissolution in the prism workspace
that broke up the original bundled Peer atom. The evolution and the delegation
algebra are recorded in the project store
(`observation:architecture/identity-peer-as-atom-history`,
`observation:architecture/scope-lattice-narrowing-algebra`).

**Observer** is a string on every Fact. Naming hierarchy encodes participation
level by convention: `kyle` (direct), `kyle/claude-session-123` (delegated),
`kyle/deploy-agent` (automated). The identity is part of the observation.

**Grant** attaches policy at the vertex level:
- **horizon:** what kinds the observer can see (field of view)
- **potential:** what kinds the observer can emit (ability to direct attention)
- **None** = unrestricted. **frozenset()** = locked out.

**Delegation** narrows — you can give a collaborator a focused view and a
constrained voice. `delegate(peer, "child", potential={"health"})` creates
a child peer that can only emit health observations.

**The default stance is participatory, not authenticative.** Observer carries
who-asserts, and trust attaches to the accumulated fact-stream. Nothing in the
paradigm requires a signature for a fact to count.

**Cryptographic attestation is a shipped opt-in layer on top of that stance.**
libs/sign holds the primitives, libs/custody the composition, and engine takes
signers as injected callables — so the record layer never imports the crypto.
What that buys, per store: per-fact Ed25519 signatures verified against the
observer-key registry in the vertex declaration; ticks that are both chained
(`prev_hash` plus a hash of the fact window they summarize) and signed;
`sl seal`, which emits a `seal` fact so the vertex's declared `boundary
when="seal"` fires and the minted tick *is* the attestation; and `sl store
verify`, which walks the chain and checks both tick and fact signatures against
the declared keys. Opt-in is structural, not a flag: no key material means no
signer, which means unsigned rows — the honest pre-signature era. Once a store
has minted a chained signed tick it is in the signed era, and that is a floor:
appending an unsigned tick afterward is refused, because it would break
era-monotonicity.

**Peer/Grant is the part still waiting on a consumer.** No app in this repo
gates on a Grant today. vouch (homelab agent IdP) is the *forcing function* for
any further recast — `Peer.iss` for federation, lifting `Grant` to `kind=grant`
Facts, the `VertexPolicy` interface — and those land here when its exercise
produces them, not before. That work now lives in the `agent-attestation`
vertex.

## Conventions

- **Immutable by default.** Frozen dataclasses, `MappingProxyType` for payloads,
  pure functions. The paradigm requires immutability; Python makes it visible
  with `frozen=True`.
- **Cross-lib imports follow the DAG, and the DAG is a test.** Allowed runtime
  edges live in `_LIB_ALLOWED_RUNTIME` (`tests/test_architecture.py`); anything
  else fails the suite. Each lib is independently testable.
- **Errors are facts.** Source failures emit `Fact(kind="source.error", ...)`
  instead of raising. The loop continues.
- **./dev check must pass.** Each lib and app with a dev script gates on:
  type checking + formatting → unit tests → golden snapshot tests.

## Build & Test

```bash
uv sync                                                # install all workspace packages
uv run --package <name> pytest libs/<name>/tests       # test one lib
uv run --package <name> pytest apps/<name>/tests       # test one app
```

## References

| Doc | Scope |
|-----|-------|
| [RATCHETS.md](docs/RATCHETS.md) | Construction-vs-detection — how invariants become structural |
| [CLI-CHEATSHEET.md](docs/CLI-CHEATSHEET.md) | CLI syntax reference |
| [UPGRADING.md](docs/UPGRADING.md) | Release-coupled upgrade notes |
| Lib/app CLAUDE.md files | Progressive guides — the authoritative reference chain |

The 2026-08-12 ground-up docs rebuild deleted the deep-dive corpus
(VERTEX/TEMPORAL/PERSISTENCE/IDENTITY/SCOPE-LATTICE/CADENCE and the paradigm
root); their durable rationale lives in the project store under
`observation:architecture/*` and `observation:paradigm/strange-loops-root-statement`,
full text in git history. New deep-dives are born only from a real reader-path
(`decision:practice/docs-ground-up-rebuild`).
