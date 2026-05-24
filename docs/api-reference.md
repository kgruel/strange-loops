# API Reference

Reference for the strange-loops monorepo — the `loops`/`sl` CLI command catalog
and the public Python API of each workspace library. For the paradigm and design
rationale, see [system-architecture.md](system-architecture.md) and the deep-dive
docs. For CLI syntax depth and worked examples, see
[CLI-CHEATSHEET.md](CLI-CHEATSHEET.md) — this page is the catalog; the cheatsheet
is the field guide.

The repo is a `uv` workspace: 5 libraries (`atoms`, `lang`, `engine`, `sign`,
`store`) and 3 applications (`loops`, `hlab`, `tasks`). Rendering lives in the
external [`painted`](https://github.com/kgruel/painted) package.

---

# Part 1 — CLI Reference (`loops` / `sl`)

The CLI installs as two names — `loops` (long) and `sl` (shorthand). Entry point:
`loops.cli.app.main`. Output is rendered through `painted` via a single reporter
boundary; no command prints raw text.

## Three-tier dispatch

Dispatch resolves an op token in `cli/app.py`, then routes through one of three
tiers (registered in `loops.cli.registry`):

```
loops <verb>    [vertex] [args]   # tier 1 — primary verbs (registry.VERBS)
loops <command> [args]            # tier 2 — dev/setup commands (registry.COMMANDS)
loops <vertex>  [op] [args]       # tier 3 — vertex-first shorthand (_vertex_first)
```

- **Verb-first** is the primary path: a verb names the operation, an optional
  vertex names the target.
- **Command** tier handles dev/setup actions that need no vertex resolution.
- **Vertex-first shorthand**: `loops project` is implicit `loops read project`;
  `loops project emit ...` dispatches a vertex-first op from `registry.VERTEX_OPS`.

Vertex resolution chain: `.loops/<name>.vertex` > `cwd/<name>.vertex` >
`~/.config/loops/<name>/<name>.vertex`. See CLI-CHEATSHEET for full detail.

## Tier 1 — Verbs (`registry.VERBS`)

| Verb | Syntax | Purpose |
|------|--------|---------|
| `read` | `loops read <vertex> [flags]` | Show vertex state — folded (default), `--facts`, or `--ticks`. Thin router into the `fold` IR. |
| `emit` | `loops emit <vertex> <kind> [KEY=VAL …] [msg]` | Append a fact to a vertex store. |
| `close` | `loops close <vertex> [flags]` | Fire a boundary — snapshot fold state into a Tick. |
| `sync` | `loops sync [flags]` | Run vertex sources (poll commands, ingest facts). No observer arg. |
| `cite` | `loops cite REF1 REF2 -m "…"` | Emit a ref-only `cite` fact bumping inbound counts on prior facts. |
| `store` | `loops store <db-path> [flags]` | Inspect a store database (also a command). |

`read` defaults to folded state. `--facts` switches to event history, `--ticks`
to tick history. `read`/`cite` are thin routers that delegate into the `fold` and
`emit` Operation-IR views.

## Tier 2 — Commands (`registry.COMMANDS`)

| Command | Syntax | Purpose |
|---------|--------|---------|
| `test` | `loops test <file.loop> [--input F]` | Run a `.loop` source, preview emitted facts (and parse pipeline). |
| `compile` | `loops compile <file.vertex>` | Compile DSL to runtime types; show the result. |
| `validate` | `loops validate <file>` | Syntax + shape-inference check of a `.loop`/`.vertex`. |
| `init` | `loops init [name]` | Scaffold a vertex from a config-level template instance. |
| `whoami` | `loops whoami` | Show resolved observer identity. |
| `ls` | `loops ls [vertex]` | Top-level: list discovered vertices. Vertex-first: list template population rows. |
| `add` | `loops add <vertex> <row…>` | Add a template population row to a vertex. |
| `rm` | `loops rm <vertex> <key>` | Remove a template population row. |
| `export` | `loops export <vertex>` | Export a vertex's inline population to an external `.list` file. |
| `store` | `loops store <db-path>` | Inspect a store database (shared with the verb tier). |

`ls`/`add`/`rm`/`export` are dual-registered: top-level (`registry.COMMANDS`) and
vertex-first (`registry.POPULATION_OPS`). Top-level `ls` lists vertices; the
vertex-first `loops <vertex> ls` lists that vertex's population rows.

## Tier 3 — Vertex-first shorthand

`registry.VERTEX_OPS` is the set dispatchable as `loops <vertex> <op>`:
`read`, `emit`, `close`, `sync`, `cite`, `store`, `ls`, `add`, `rm`, `export`.
A bare `loops <vertex>` with no op is implicit `read`.

## Global flags

Flags fall into two groups. `--observer` is a true global (peeled in `cli/app.py`
before the view parser runs). The rest are parsed per-view; the table below
reflects the `fold`/`read`/`emit` views, which carry the bulk of them.

| Flag | Applies to | Effect |
|------|-----------|--------|
| `-q`, `--quiet` | display, emit | Minimal output — counts only (display); suppress success receipt (emit). |
| `-v`, `-vv`, `--verbose` | display | Increase zoom — `-v` DETAILED, `-vv` FULL (count action). |
| `--kind <K>` | read/fold | Filter by fact kind. |
| `--key <prefix>` | read/fold | Filter by fold key; trailing `/` does a prefix scan. |
| `--facts` | read | Show fact event history instead of folded state. |
| `--ticks` | read | Show tick history instead of folded state. |
| `--since <window>` | read | Time window (`7d`, `24h`, `1h`). |
| `--diff` | read/fold | Show fold delta. |
| `--lens <name>` | display | Override lens resolution with a named lens. |
| `--observer <name>` | global | Set observer identity (or `all` to override vertex scope). |
| `--plain` | display | Plain text — no color. |
| `--json` | display | JSON output. |
| `--live` | display | Live-updating render. |
| `--static` | display | Force static render (no live updates). |
| `-i`, `--interactive` | display | Interactive TUI explorer. |
| `--stdin FIELD` | emit | Read stdin into the named payload field. |
| `--file FIELD=PATH` | emit | Read a file into the named field (repeatable). |
| `--dry-run` | emit | Print the fact JSON without storing. |
| `--strict` | emit | Refuse on validation failures (unknown kind, missing fold key, unresolved ref). |
| `--max-chars N`, `--max-lines N` | display | Truncate output. |

Zoom levels: MINIMAL (0) / SUMMARY (1, default) / DETAILED (2) / FULL (3).
Display commands render through a lens `(data, zoom, width, **kwargs) -> Block`;
lens resolution is 4-tier (vertex-local > project > user-global > built-in), with
`--lens` overriding all tiers. See
[CLI-CHEATSHEET.md](CLI-CHEATSHEET.md) for syntax depth, emit fold-key discipline,
ref syntax, and worked examples.

---

# Part 2 — Python Library API

Each library re-exports its public surface from its package `__init__.py` (most
use lazy `__getattr__` to keep import time low). The tables below list what is
declared in `__all__`. Symbols that are lazily importable but **not** in `__all__`
are marked *(semi-public)* — callable via `from <lib> import X`, but not part of
the promised surface. Deprecated aliases are marked *(deprecated)*.

## atoms — data primitives

Zero external dependencies. `from atoms import Fact, Spec, Source`.

### Core types

| Symbol | Signature / shape | Brief |
|--------|-------------------|-------|
| `Fact` | `Fact(kind, ts, payload=None, observer="", origin="")` | Immutable observation atom. Manual `__slots__`; `payload` dicts wrapped in `MappingProxyType`. Factories: `Fact.of(kind, observer, *, origin="", ts=None, **data)`, `Fact.tick(name, observer, …)`; `to_dict()`/`from_dict()`. |
| `Spec` | `Spec(name, about, input_fields, state_fields, folds, boundary)` | Fold contract. Methods: `initial_state()`, `apply(state, payload)` (pure fold), `replay(payloads)` (bulk). |
| `Field` | `Field(name, kind, optional=False)` | A named, typed spec field. `kind` ∈ str/int/float/bool/dict/list/set/datetime. `Field.from_type_str(name, "int?")` parses the `?` optional syntax. |
| `Boundary` | `Boundary(kind=None, count=None, mode="when", reset=True, match=(), conditions=(), run=None)` | Tick trigger. `mode` ∈ when / after / every. `run` = shell command fired on boundary. |
| `Source` | `Source(command, kind, observer, format="lines", parse=None, origin="", env=None)` | Shell ingress adapter. `format` ∈ lines/json/ndjson/blob. `async collect()` → `AsyncIterator[Fact]`. |
| `SourceError` | exception | Raised on source command failure. |
| `ValidationError` | exception | Raised by spec/coerce validation. |

### Fold output contract

| Symbol | Brief |
|--------|-------|
| `FoldItem` | One folded item: `payload, ts, observer, origin, id, n, refs`. |
| `FoldSection` | A named group of items/sub-sections: `kind, items, sections, …`. |
| `FoldState` | The complete folded view returned by a fold pass. |
| `TickWindow` | Density/depth window summary over ticks (newest-first). |
| `WalkedItem` | Item produced while walking a fold tree. |

### Parse ops (`atoms.parse`)

Pipeline ops that shape raw source output into fact payloads:
`Skip`, `Split`, `Pick`, `Rename`, `Transform`, `Coerce`, `Select`, `Explode`,
`Project`, `Where`, `Flatten`. Helpers: `run_parse`, `run_parse_many`,
`has_explode`, `resolve_path`.

### Fold ops (`atoms.fold`)

Accumulation vocabulary, base class `FoldOp`:
`Latest`, `Count`, `Sum`, `Collect`, `Upsert`, `TopN`, `Min`, `Max`, `Avg`,
`Window`.

### Ingress

`SequentialSource`, `SourceProtocol` (async-iterator protocol).

### Deprecated / semi-public

| Symbol | Status |
|--------|--------|
| `Shape` | *(deprecated)* alias of `Spec` (`atoms.spec:130`). |
| `Facet` | *(deprecated)* alias of `Field` (`atoms.facet:34`). |
| `CommandSource` | *(deprecated)* alias of `Source` (`atoms.source:231`). |

## lang — KDL DSL parser

Pure grammar for `.loop` (source definitions) and `.vertex` (vertex config) files.
Only external dep: `ckdl`. No `atoms`/`engine` imports.

### Loader & validator

| Symbol | Signature | Brief |
|--------|-----------|-------|
| `parse_loop_file` | `(path) -> LoopFile` | Parse a `.loop` file. |
| `parse_loop` | `(text) -> LoopFile` | Parse `.loop` text. |
| `parse_vertex_file` | `(path) -> VertexFile` | Parse a `.vertex` file. |
| `parse_vertex` | `(text) -> VertexFile` | Parse `.vertex` text. |
| `validate` | `(ast)` | Validate any AST; raises `ValidationError`. |
| `validate_loop` | `(loop_ast)` | Validate a `.loop` AST (shape inference). |
| `validate_vertex` | `(vertex_ast)` | Validate a `.vertex` AST (routes/folds/xrefs). |

### Population management (`lang.population`)

| Symbol | Brief |
|--------|-------|
| `resolve_vertex(name, home)` | Resolve a (possibly slashed) vertex name to its `.vertex` path. |
| `resolve_template(vertex_ast)` | Find the template source within a vertex. |
| `read_population(vertex_ast, template, base_dir)` | Read parameter rows → `PopulationInfo`. |
| `template_name(...)` | Derive a template's name. |
| `PopulationRow` | One template parameter row. |
| `PopulationInfo` | `header, rows, storage` ("file"/"inline"/"both"). |

### AST types (`lang.ast`)

Frozen dataclasses describing parsed files.

| Group | Types |
|-------|-------|
| Loop file | `LoopFile`, `Duration`, `Trigger` |
| Parse steps | `ParseStep`, `Skip`, `Split`, `Pick`, `Transform`, `TransformOp`, `Strip`, `LStrip`, `RStrip`, `Replace`, `Coerce`, `Explode`, `Project`, `Where`, `Flatten` |
| Vertex file | `VertexFile`, `LoopDef`, `FoldDecl` |
| Fold ops | `FoldOp`, `FoldBy`, `FoldCount`, `FoldSum`, `FoldLatest`, `FoldCollect`, `FoldMax`, `FoldMin`, `FoldAvg`, `FoldWindow` |
| Boundaries | `Boundary`, `BoundaryWhen`, `BoundaryAfter`, `BoundaryEvery`, `BoundaryCondition` |
| Sources | `InlineSource`, `SourcesBlock`, `SourceEntry`, `SourceParams`, `TemplateSource`, `FromFile`, `FromSource` |
| Declarations | `LensDecl`, `ObserverDecl`, `GrantDecl`, `CombineEntry` |

### Errors (`lang.errors`)

`DSLError`, `LexError`, `ParseError`, `ValidationError`, `Location`.

> Note: `Rename` and `Select` are atoms-level parse ops, not lang AST nodes —
> lang's parse-step vocabulary uses `Transform`/`Coerce` and the ops listed above.

## engine — runtime, persistence, identity

Sync core; external scheduling drives the heartbeat. Depends on `atoms`
(TYPE_CHECKING only), `lang`, `python-ulid`. `from engine import Tick, Vertex,
Peer, Grant`.

### Core temporal types

| Symbol | Signature / shape | Brief |
|--------|-------------------|-------|
| `Tick` | `Tick(name, ts, payload, origin="", since=None, run=None)` | Frozen snapshot at a boundary. `since`→`ts` is the period it summarizes. Generic `Tick[T]`. |
| `Vertex` | `Vertex(name, store=None)` | Routes facts by kind to folds. Key methods: `register(kind, initial, fold, boundary=…)`, `register_loop(loop)`, `receive(fact, grant=…)`, `state(kind)`, `tick(name, ts)`. |
| `Loop` | `Loop(name, initial, fold, boundary_kind=None, boundary_count=None, boundary_mode="when", boundary_match=(), boundary_conditions=(), boundary_run=None, reset=True)` | Explicit fold-and-fire unit registered on a Vertex. |
| `Stream` | `Stream[T]` | Async multiplexer. |
| `Tap`, `Consumer` | — | Stream attachment / consumer helpers. |
| `Forward` | `Forward[T, U]` | Async bridge from a sync Vertex to a Stream consumer. |
| `Lens` | `Lens(zoom, scope)` | Frozen view descriptor (zoom + scope). |
| `Cadence` | `Cadence` | Scheduling policy — elapsed / triggered / always. |

> `Projection` lives in `engine.projection` and is **not** re-exported from the
> package root. It is the internal incremental-fold engine — callers register
> folds via `Vertex.register()` rather than constructing a `Projection` directly.

### Persistence

| Symbol | Signature / shape | Brief |
|--------|-------------------|-------|
| `Store` | `Protocol` | Append-only store contract: `append(event, *, id_override=None)`, `since(cursor)`, `between(start, end)`, `latest_by_kind(kind)`, `latest_by_kind_where(kind, key, value)`, `close()`. |
| `EventStore` | `EventStore[T]` | In-memory store (optional JSONL); tests / ephemeral. |
| `SqliteStore` | `SqliteStore[T]` | SQLite (WAL mode), ULID PK; production / concurrent reads. |
| `FileStore` | — | JSONL-backed persistence. |
| `FileWriter` | — | JSONL append writer. |
| `Tailer` | — | Follows a file store for new events. |
| `gen_id` | `() -> str` | Generate a 26-char ULID. |
| `replay` | `replay(vertex, store, *, from_cursor=0) -> int` | Re-feed stored facts through a vertex (boundaries suppressed); returns count. |
| `StoreReader` | `StoreReader(db_path)` *(semi-public)* | Read-only inspector — `summary()`, `recent_facts(n)`, `recent_ticks(n)`. In `_LAZY_IMPORTS` but not `__all__`; used by the CLI read path. |

### Identity & policy (`engine.peer`)

| Symbol | Signature / shape | Brief |
|--------|-------------------|-------|
| `Peer` | `Peer(name, horizon=None, potential=None)` | Identity + capability. `None` = unrestricted; `frozenset()` = locked out. |
| `Grant` | `Grant(horizon=None, potential=None)` | Policy separated from identity; gates `receive`. |
| `grant` | `grant(...)` | Union / expand capabilities. |
| `restrict` | `restrict(...)` | Intersection / narrow. |
| `delegate` | `delegate(peer, name, *, horizon=None, potential=None)` | Create a narrowed child peer. |
| `grant_of`, `expand_grant`, `restrict_grant` | — | Grant algebra helpers. |
| `observer_leaf`, `observer_matches` | — | Observer-name matching (bare vs namespaced). |

### Compiler (DSL → runtime, `engine.compiler`)

| Symbol | Signature | Brief |
|--------|-----------|-------|
| `compile_vertex` | `(vertex: VertexFile) -> dict[str, Spec]` | Compile a vertex AST to Specs. |
| `compile_loop` | `(loop: LoopFile) -> Source` | Compile a `.loop` AST to a runtime Source. |
| `compile_vertex_recursive` | `(...)` | Compile a vertex and its children. |
| `compile_source`, `compile_sources`, `compile_sources_block` | — | Source compilation helpers. |
| `instantiate_template`, `materialize_vertex`, `substitute_vars` | — | Template instantiation / variable substitution. |
| `collect_all_sources`, `collect_search_fields` | — | Source/field collection. |
| `CompiledVertex` | dataclass | Compiled vertex result. |
| `FoldOverride` | — | Per-loop fold override passed to compile/load. |
| `CircularVertexError` | exception | Raised on a vertex inclusion cycle. |

### Executor (`engine.executor`)

| Symbol | Signature | Brief |
|--------|-----------|-------|
| `Executor` | — | Evaluates cadences, builds the source dependency graph, runs `_sync`. |
| `validate_dependency_graph` | `(sources: list[tuple[Source, Cadence]]) -> None` | Detect cyclic source dependencies. |
| `SyncResult` | dataclass | Result of a sync pass. |
| `SkippedSource` | dataclass | A source skipped this pass. |
| `CyclicDependencyError` | exception | Raised on a cyclic dependency graph. |

### Program & vertex read path

| Symbol | Signature | Brief |
|--------|-----------|-------|
| `VertexProgram` | — | Loaded vertex program. Methods: `receive(...)`, `sync(...)`, `async sync_async(...)`, props `name`, `has_store`. |
| `load_vertex_program` | `(vertex_path, *, vars=None, fold_overrides=None, default_fold_override=None, validate_ast=True)` | Parse + compile + wire a `.vertex` into a `VertexProgram`. |
| `vertex_read` | `(vertex_path, *, observer=None) -> dict[str, dict]` | Read folded state (parse → compile → replay). |
| `vertex_fold` | `(vertex_path, *, observer=None, kind=None, retain_facts=False)` | Folded view, optionally per-kind. |
| `vertex_tick_fold` | `(vertex_path, …)` | Fold over the tick stream. |
| `vertex_facts` | `(vertex_path, since_ts, until_ts, kind=None, observer=None) -> list[dict]` | Raw facts in a time range. |
| `vertex_ticks` | `(vertex_path, since_ts, until_ts, name=None) -> list` | Ticks in a time range. |
| `vertex_fact_by_id` | `(vertex_path, …)` | Single fact by ULID / prefix. |
| `vertex_search` | `(vertex_path, query, *, kind=None, since=None, until=None, limit=100)` | Full-text search over facts. |
| `vertex_summary` | `(vertex_path) -> dict` | Store summary (counts, kinds, names). |
| `emit_topology` | `(vertex_path) -> None` | Emit the vertex topology. |

### Source protocol

`VertexSource` (lazy alias of `engine.source_protocol.Source`), `ClosableSource`.

## sign — JWT / JWKS attestation

Utility lib (not part of the loops protocol). Pure functions; consumers wrap
outputs in their own HTTP layer. Deps: `pyjwt[crypto]`, `cryptography`,
`python-ulid`. Flat or namespaced imports both public.

| Symbol | Signature | Brief |
|--------|-----------|-------|
| `KeyStore` | — | Owns one RSA-2048 keypair. Public method: `public_keys() -> list[PublicKey]`. Internal attrs underscore-prefixed (no contract). |
| `PublicKey` | `PublicKey(kid, alg, key)` | Frozen verify-side input shape. |
| `load_or_generate` | `(dir) -> KeyStore` | Load keys from dir, or generate a fresh RSA-2048 pair if empty. |
| `mint` | `mint(*, keystore, issuer, claims, ttl_seconds, jti=None) -> (token, jti)` | RS256 mint; lib injects `iss`/`iat`/`exp`/`jti`, caller owns claim contents. |
| `verify` | `verify(token, *, public_keys, issuer, audience) -> claims_dict` | Look up key by `kid`, validate iss/aud/exp/signature. `audience` required. |
| `build_document` | `(keystore) -> dict` | JWKS document (RFC 7517). |
| `build_openid_configuration` | `(issuer, *, jwks_uri, **extra) -> dict` | OIDC discovery doc; extra fields pass through verbatim. |
| `parse` | `(jwks_dict) -> list[PublicKey]` | Inverse of `build_document` for remote verify. |

Claim-content validation (`sub` non-empty, RFC 8693 `act` shape, scope) is the
caller's responsibility — the library verifies only the envelope.

## store — store maintenance operations

Stateless bulk ops over SQLite vertex DBs (facts/ticks schema). Engine writes;
this maintains. Cross-DB work via `ATTACH DATABASE` (no Python row loop). Dep:
`engine` (type hints only).

| Symbol | Signature | Brief |
|--------|-----------|-------|
| `slice_store` | `(source, target, *, kinds=…, since=…, before=…, observers=…, origins=…, dry_run=False) -> SliceResult` | Extract a filtered subset into a new DB (target must not exist). |
| `merge_store` | `(target, source, *, dry_run=False) -> MergeResult` | Merge a source DB into target (ULID dedup, `INSERT OR IGNORE`; idempotent). |
| `receive_store` | `(target, source) -> ReceiveResult` | Create-or-merge with SQLite validation; status "created"/"merged". |
| `compact_store` | `(path) -> CompactResult` | `VACUUM` + `PRAGMA optimize`. |
| `push_store` | `(local_path, transport, *, remote_path, …) -> PushResult` | Slice local → transport → remote receive. |
| `pull_store` | `(local_path, transport, *, remote_path, …) -> PullResult` | Remote → transport → local receive. |
| `Transport` | `Protocol` | `push(local_path, *, remote_path)`, `pull(remote_path, *, local_path)`. |
| `LocalTransport` | — | Same-machine file-copy transport implementation. |

Result dataclasses (frozen, with counts): `SliceResult`, `MergeResult`,
`ReceiveResult`, `CompactResult`, `PushResult`, `PullResult`. Slice filters
(`since`, `before`, `kinds` exact+prefix, `observers`, `origins`) also apply to
push/pull. Cursor tracking is the caller's responsibility — store is stateless.

---

## See also

- [../README.md](../README.md) — project overview and quickstart
- [system-architecture.md](system-architecture.md) — why it's built this way
- [codebase-summary.md](codebase-summary.md) — module-by-module inventory
- [CLI-CHEATSHEET.md](CLI-CHEATSHEET.md) — CLI syntax depth, fold-key discipline, ref syntax
