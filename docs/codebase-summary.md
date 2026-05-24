# Codebase Summary

A file-level map of the strange-loops monorepo: what each package is, the key
modules inside it, and the dependencies that hold it together. For the conceptual
view see [`system-architecture.md`](system-architecture.md); for the paradigm see
[`project-overview-pdr.md`](project-overview-pdr.md).

- **Scale:** ~35K LOC of Python across 8 workspace packages (5 libs + 3 apps).
- **Layout:** uv workspace; Python ≥3.11; MIT; distributed on PyPI as `strange-loops`.
- **Rendering** is the external [`painted`](https://github.com/kgruel/painted) package.

```
libs/   atoms · lang · engine · sign · store
apps/   loops (sl/loops CLI) · hlab (homelab) · tasks (orchestration)
docs/   deep-dives + generated doc set
tests/  test_architecture.py (import-boundary enforcement)
benchmarks/  benchmark_emit_path.py · benchmark_read.py
bin/    sub (submodule push harness)
```

---

## Libraries (`libs/`)

### atoms — data primitives (~2.4K LOC, zero external deps)

The three shapes and the ingress vocabulary. Dependency-free and import-cheap
(lazy `__getattr__`, manual `__slots__` on `Fact`).

| Module | Role |
|--------|------|
| `fact.py` | `Fact` — immutable observation (`kind`, `ts`, `payload`, `observer`, `origin`); factories `Fact.of()`, `Fact.tick()`. |
| `spec.py` | `Spec` — fold contract; `initial_state()`, `apply()` (pure), `replay()` (bulk). |
| `facet.py` | `Field` — typed field (`str`/`int`/`float`/`bool`/`dict`/`list`/`set`/`datetime`, `"int?"` optional syntax). |
| `source.py` | `Source` — shell-command adapter; formats `lines`/`json`/`ndjson`/`blob`; async `collect()`. |
| `parse.py` | Parse ops: `Skip`, `Split`, `Pick`, `Rename`, `Transform`, `Coerce`, `Select`, `Explode`, `Project`, `Where`, `Flatten`. |
| `fold.py` | Fold ops: `Latest`, `Count`, `Sum`, `Collect`, `Upsert`, `TopN`, `Min`, `Max`, `Avg`, `Window`. |
| `fold_state.py` | `FoldItem`, `FoldSection`, `FoldState` — typed fold output (nestable sections). |
| `boundary.py` | `Boundary` — cycle-completion trigger (`when`/`after`/`every` + conditions). |
| `ticks.py` | `TickWindow` — density/depth summary for a temporal window. |
| `engine.py` | `build_fold_fns` — compiles declarative fold ops to executable closures. |
| `protocol.py` / `sequential.py` | `SourceProtocol` async-iterator interface; `SequentialSource`. |
| `types.py` | `ValidationError`, `coerce_value`, `type_matches`. |

### lang — KDL DSL parser (~2.9K LOC, dep: `ckdl`)

Pure grammar for `.loop` (source defs) and `.vertex` (vertex config) files. No
`atoms`/`engine` imports — portable across domains.

| Module | Role |
|--------|------|
| `ast.py` | 40+ frozen AST dataclasses: `LoopFile`, `VertexFile`, `Duration`, ParseStep variants, `FoldOp` variants, `Boundary` variants, `TemplateSource`/`PopulationRow`. |
| `loader.py` | `parse_loop_file` / `parse_vertex_file` — KDL → AST (defers `ckdl` import). |
| `validator.py` | Semantic validation: shape inference (`STRING→LIST→DICT`), flow checks, cross-references. |
| `population.py` | `resolve_vertex`, `resolve_template`, `read_population`, `kdl_insert/remove_with_row`. |
| `errors.py` | `DSLError`, `ParseError`, `ValidationError`, `LexError`, `Location`. |

### engine — runtime, persistence, identity (~6.6K LOC, deps: `python-ulid`; `atoms`/`lang`)

The Vertex pattern plus its store and identity model. Imports `atoms` only under
`TYPE_CHECKING`.

| Module | Role |
|--------|------|
| `vertex.py` | `Vertex` — routes facts by kind, fires ticks, enforces grants. |
| `loop.py` | `Loop` — named fold + boundary semantics. |
| `projection.py` | `Projection[S,T]` — incremental fold engine with state versioning. |
| `tick.py` | `Tick[T]` — frozen snapshot (`name`, `ts`, `payload`, `origin`, `since`, `run`). |
| `store.py` | `Store` protocol + in-memory `EventStore`. |
| `sqlite_store.py` | `SqliteStore` — WAL, ULID PK, kind/ts indices. |
| `store_reader.py` | `StoreReader` — read-only inspector (`PRAGMA query_only`). |
| `file_store.py` / `file_writer.py` / `tailer.py` | `FileStore` (JSONL) + writer/tailer. |
| `peer.py` | `Peer` (`name`, `horizon`, `potential`) + `Grant` policy. |
| `observer.py` | Observer name matching (bare vs namespaced). |
| `stream.py` / `forward.py` | Async `Stream[T]` multiplexer + `Forward[T,U]` bridge. |
| `lens.py` | `Lens` — rendering params (`zoom`, `scope`); not access control. |
| `program.py` | `VertexProgram` — frozen composition of vertex + sources + cadences. |
| `executor.py` | `Executor` — evaluates cadences, builds dependency graph, runs sources. |
| `compiler.py` | Maps DSL AST → runtime types (recursively compiles child vertices). |
| `cadence.py` | `Cadence` — store predicate (`elapsed`/`triggered`/`always`). |
| `vertex_reader.py` / `replay.py` | Query-time replay + state materialization (`ATTACH DATABASE`). |
| `builder.py` | Fluent programmatic `Vertex` construction. |

### sign — JWT/JWKS attestation (~0.3K LOC, deps: `pyjwt[crypto]`, `cryptography`, `python-ulid`)

Independent utility for federated attestation; **not** part of the loops protocol.
Pure functions, no HTTP framework. `keys.py` (`KeyStore`, `load_or_generate` RSA-2048,
`kid = SHA256(DER)[:16]`), `jwt.py` (`mint`/`verify` RS256), `jwks.py` (`build_document`
RFC 7517, `build_openid_configuration`, `parse`). Caller validates claim content;
the lib verifies the envelope only.

### store — store maintenance ops (~0.7K LOC, dep: `engine` type hints only)

Stateless bulk operations over SQLite vertex DBs (`facts`/`ticks` schema), all
SQL-side via `ATTACH DATABASE`. `slice_store` (filtered export), `merge_store`
(dedup on id PK), `receive_store` (create-or-merge), `compact_store` (`VACUUM`),
`push_store`/`pull_store` over a pluggable `Transport` (`LocalTransport`). Frozen
result dataclasses (`SliceResult`, `MergeResult`, …) carry counts.

---

## Applications (`apps/`)

### loops — the `sl` / `loops` CLI (~13.5K LOC) — primary surface

Emit/read/fold/stream/store across vertices. Three-tier dispatch with lazy view
loading; all output through a single `painted` boundary.

| Area | Modules |
|------|---------|
| Dispatch | `cli/app.py` (tier 1–3 routing), `cli/registry.py` (`VERBS`/`COMMANDS`/`POPULATION_OPS`). |
| Operation IR | `cli/operation.py` (`Operation`), `cli/dispatch.py` (action/interactive/live/static). |
| Output boundary | `cli/output.py` (`Reporter`, `PaintedReporter`, `BufferReporter`), `cli/live.py` (`run_live`). |
| Lens resolution | `cli/lens.py` (3-tier), `lens_resolver.py` (4-tier file search), `cli/fidelity.py`. |
| Views | `cli/views/*.py` — `read.py` (router), `fold.py` (largest), `emit`, `cite`, `store`, `stream`, `ticks`, `population`. |
| Commands (shims) | `commands/*.py` — `fetch`, `emit`, `resolve`, `init`, `ls`/`add`/`rm`/`export`, `sync`, `ticks`, `devtools`, `store`, `whoami`. |
| Lenses (render) | `lenses/*.py` — `fold.py` (namespace grouping + salience), `stream`, `trace`, `ticks`, `validate`, `store`, … |

Display commands render via a lens; action commands (`emit` default, `close`,
`sync`, `init`, `ls`/`add`/`rm`/`export`, `whoami`) return a receipt. → [`api-reference.md`](api-reference.md), [`CLI-CHEATSHEET.md`](CLI-CHEATSHEET.md).

### hlab — homelab monitor (~4.2K LOC, deps: `httpx`, `pyyaml`) — archived experiment

DSL-driven container/stack status, Prometheus alerts, media audit, Uptime-Kuma
sync. Commands: `status`, `alerts`, `logs`, `media audit|fix`, `sync uptime-kuma`.
Vertices declare SSH `.loop` sources; `health_fold` computes healthy/total at
query time. No tests (archived).

### tasks — task orchestration (~3.8K LOC, deps: `lang`, `atoms`, `engine`, `painted`)

Tasks modelled as loops; workers run in git worktrees and coordinate through a
shared SQLite WAL store (no IPC). Entry `strange_loops.cli`. Commands span
`session`, `task` (`create`/`assign`/`send`/`run`/`merge`/`close`/`stop`), `note`,
`dashboard`, `project`. State is **derived** at read time (`vertex_read → fold →
extract_task`), not stored. Two stores: `tasks.db`, `project.db`. Harnesses are
`.loop` files (`shell`, `sonnet`, `opus`, `codex`, `gemini-flash`).

---

## Dependencies

### Internal dependency graph

```
atoms (0 internal deps)
lang  → (ckdl)
engine ← atoms (TYPE_CHECKING) + lang ; → python-ulid
store  ← engine (type hints only)
apps/{loops,hlab,tasks} ← atoms + engine + lang + painted
sign  (independent)
```

Enforced by `tests/test_architecture.py`. → [`code-standards.md`](code-standards.md).

### Key external dependencies

| Package | Version | Purpose | Used by | Type |
|---------|---------|---------|---------|------|
| `painted` | ≥0.1.8 | Terminal rendering (`Block`, `Style`, `Zoom`, `run_cli`, lenses) | all apps | runtime |
| `ckdl` | ≥1.0 | KDL document parser | `lang` | runtime |
| `python-ulid` | ≥3.0 | Time-sortable IDs (store primary keys) | `engine`, `sign` | runtime |
| `pyjwt[crypto]` | ≥2.9 | JWT mint/verify | `sign` | runtime |
| `cryptography` | ≥43 | RSA key primitives | `sign` | runtime |
| `typing_extensions` | ≥4.0 | Type-hint backports | root | runtime |
| `httpx` | ≥0.27 | HTTP client (Prometheus/Radarr) | `hlab` | runtime |
| `pyyaml` | ≥6.0 | Ansible inventory parsing | `hlab` | runtime |
| `pytest` | — | Test runner | all | dev |
| `pytest-cov` | — | Branch coverage | all | dev |
| `pytest-asyncio` | — | Async tests (`asyncio_mode = auto`) | `atoms`, `engine` | dev |
| `ruff` | — | Lint + format (line-length 100, py311) | all | dev |
| `ty` | — | Type validation | all | dev |
| `rich` | — | Colorized dev output | several | dev |

---

## Tests, benchmarks, scripts

- **`tests/test_architecture.py`** — AST-based import-boundary enforcement.
- **Per-package `tests/`** — pytest, golden snapshots in `apps/loops` and `apps/tasks`.
- **`benchmarks/`** — `benchmark_emit_path.py`, `benchmark_read.py`.
- **`bin/sub`** — submodule commit/push harness.

→ How to run everything: [`testing-guide.md`](testing-guide.md).

---

*See also: [system-architecture.md](system-architecture.md) · [project-overview-pdr.md](project-overview-pdr.md) · [api-reference.md](api-reference.md) · [code-standards.md](code-standards.md)*
