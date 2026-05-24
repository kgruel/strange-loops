# Scout Context — strange-loops monorepo

**Scouted:** 2026-05-24 13:36 | **Mode:** init | **Scope:** everything | **Depth:** deep
**Scale:** 455 files, ~35K LOC Python, 8 workspace packages (5 libs + 3 apps)
**Last code commit:** 2026-05-19 | **HEAD:** 33937f6

---

## Project Paradigm (STRANGE-LOOPS.md / ARCHITECTURE.md)

strange-loops: a Python system for focusing attention through structured observation loops.
Paradigm: **three shapes, four properties, one pattern**.

- **Three Shapes (atoms):** Fact (immutable observation: kind + ts + payload + observer),
  Spec (fold contract: fields + folds + boundary), Tick (frozen snapshot at boundary).
- **Four Properties:** Immutable (facts never change; state derived by replay),
  Append-only (no deletion), Unidirectional (facts in → state → ticks out),
  Observer-attributed (every fact carries who observed it).
- **One Pattern (the Vertex):** routes facts by kind to fold engines, accumulates
  state via Specs, produces Ticks at boundaries; Ticks flow out as facts into other
  vertices or back into the same one.

Version 0.3.1, Python >=3.11, MIT. uv workspace. Rendering lives in external `painted` (PyPI >=0.1.8).

---

## libs/atoms — data primitives (2372 LOC, zero external deps)

Data layer for observations, contracts, ingress. Lazy imports to keep import ~13ms.

**Key modules:** fact.py (Fact, manual __slots__), spec.py (Spec contract), source.py
(Source shell adapter: lines/json/ndjson/blob), parse.py (Parse ops), fold.py (Fold ops),
fold_state.py (FoldItem/FoldSection), boundary.py (Boundary triggers), ticks.py (TickWindow),
facet.py (Field), types.py (ValidationError, coerce), engine.py (build_fold_fns),
protocol.py (SourceProtocol async iterator), sequential.py (SequentialSource).

**Core types:**
- `Fact(kind, ts, payload, observer, origin)` — immutable. Factories: Fact.of(), Fact.tick().
- `Spec(name, about, input_fields, state_fields, folds, boundary)` — methods initial_state(),
  apply() (pure fold), replay() (bulk mutate).
- `Field(name, kind, optional)` — kinds: str/int/float/bool/dict/list/set/datetime; "int?" syntax.
- `Source(command, kind, observer, format, parse, origin, env)` — async collect()→AsyncIterator[Fact].
- `Boundary(kind, count, mode, reset, match, conditions, run)` — modes: when/after/every.
- `TickWindow(...)` — density/depth window summary, newest-first.
- `FoldItem(payload, ts, observer, origin, id, n, refs)`; `FoldSection(kind, items, sections, ...)`.
- Parse ops: Skip, Split, Pick, Rename, Transform, Coerce, Select, Explode, Project, Where, Flatten.
- Fold ops: Latest, Count, Sum, Collect, Upsert, TopN, Min, Max, Avg, Window.

Patterns: frozen dataclasses, pure fold fns, MappingProxyType immutability, lazy __getattr__.
Tests: pytest asyncio_mode=auto, per-module test files.

## libs/lang — KDL DSL parser (2933 LOC, dep: ckdl>=1.0)

Pure grammar layer for .loop (source defs) and .vertex (vertex config) files. No atoms/engine imports.

**Key modules:** ast.py (40+ frozen AST dataclasses), loader.py (parse_loop_file/parse_vertex_file),
validator.py (shape inference STRING→LIST→DICT, flow/xref checks), errors.py (DSLError/Location),
population.py (resolve_vertex, resolve_template, read_population, kdl_insert/remove_with_row).

**Core AST:** LoopFile(command, kind, observer, format, every, parse, trigger);
Duration (Go-style "5s"/"1m30s"); ParseStep variants; VertexFile(name, store, loops, sources,
discover, vertices, routes); LoopDef/FoldDecl; FoldOp variants (FoldBy/Count/Sum/Latest/Collect/
Max/Min/Avg/Window); Boundary variants (When/After/Every) + BoundaryCondition; TemplateSource/
SourceParams/PopulationRow for template population.

Public API: parse_loop_file, parse_vertex_file, validate*, resolve_vertex, resolve_template.
Tests: test_loader, test_validator, test_population, test_kdl_splice.

## libs/engine — runtime + persistence + identity (6556 LOC, deps: atoms TYPE_CHECKING, lang, python-ulid)

Runtime for temporal state accumulation + identity gating. Sync core; external scheduling drives heartbeat.

**Key modules:** tick.py (Tick), vertex.py (Vertex: routes by kind, fires Ticks, enforces grants),
loop.py (Loop: fold + boundary), projection.py (Projection: incremental fold + versioning),
store.py (Store protocol + EventStore), sqlite_store.py (SqliteStore: WAL, ULID PK), store_reader.py
(read-only inspector, query_only pragma), file_store.py (FileStore JSONL), peer.py (Peer + Grant),
observer.py (name matching, bare vs namespaced), stream.py (async Stream[T] multiplexer),
forward.py (Forward bridge), lens.py (Lens: zoom + scope), program.py (VertexProgram),
executor.py (cadence eval, dependency graph, _sync facts), compiler.py (AST→runtime),
cadence.py (Cadence: elapsed/triggered/always), vertex_reader.py (query-time replay, ATTACH DATABASE),
replay.py (replay()), file_writer.py, tailer.py, builder.py (fluent Vertex construction).

**Core types:** Tick[T](name, ts, payload, origin, since, run); Vertex; Loop(name, state, fold,
boundary_*, reset); Projection[S,T]; Store protocol (append/since/between/latest_by_kind/...);
EventStore; SqliteStore[T] (WAL, ULID PK); FileStore; StoreReader; Peer(name, horizon, potential);
Grant(horizon, potential); Stream[T]; Lens(zoom, scope); VertexProgram; Cadence; Forward[T,U].

**Runtime mechanics:**
1. Fact→Tick→Cascade: Vertex.receive(fact, grant) routes by kind (exact > fnmatch) to a Loop;
   Loop folds payload; if boundary fires → Tick snapshot (optional reset); child Vertices receive
   Ticks-as-Facts (origin stamped) → cascading aggregation.
2. Vertex=routing, Loop=fold-and-fire, Projection=incremental state advance.
3. Store append-only; ULID PK (python-ulid, time-sortable) enables cross-store merge dedup + chrono interleave.
4. Replay: replay(vertex, store) re-feeds facts in order, boundaries suppressed (_replaying);
   Tick carries since/ts → store.between() retrieves contributing facts.
5. Boundary fires after fold; triggers: kind / count / state-conditions.
6. Grant gating: fact.kind ∈ grant.potential; observer-state kinds enforce observer match;
   None=unrestricted, frozenset()=locked out; restrict/grant narrow delegation.
7. Async bridge: Vertex sync, Stream async, Forward is the consumer bridge.

Patterns: frozen Tick/Peer/Grant/Lens/Cadence; lazy __getattr__; engine→atoms TYPE_CHECKING only.
Tests: 30+ files; conftest fixtures (event_store, stream, projections); vertex_test_sdk.py reusable builder.

## libs/sign — JWT/JWKS attestation (305 LOC, deps: pyjwt[crypto], cryptography, python-ulid)

Utility lib for JWT mint/verify + JWKS publication. Pure functions, no HTTP framework. NOT part of loops protocol.
Modules: keys.py (KeyStore, PublicKey, load_or_generate RSA-2048, kid=SHA256(DER)[:16]),
jwt.py (mint/verify RS256), jwks.py (build_document RFC7517, build_openid_configuration, parse).
Caller validates claim content; lib verifies envelope only. Tests: test_keys/jwt/jwks.

## libs/store — store maintenance ops (720 LOC, dep: engine type-hint only)

Stateless bulk ops over SQLite vertex DBs (facts/ticks schema). Engine writes; this maintains.
Modules: _conn.py (schema DDL, WAL), slice.py (slice_store filtered export via ATTACH+INSERT...SELECT),
merge.py (merge_store dedup on id PK, INSERT OR IGNORE), receive.py (create-or-merge),
compact.py (VACUUM + optimize), transport.py (Transport protocol, push/pull), _transport_local.py (LocalTransport).
Result dataclasses: SliceResult, MergeResult, ReceiveResult, CompactResult, PushResult, PullResult.
Schema: facts(id PK ULID, kind, ts, observer, origin, payload json), ticks(id PK, name, ts, since, origin, payload json).
All cross-DB via ATTACH DATABASE (no Python row loop). Tests: test_slice/merge/receive/transport/compact.

---

## apps/loops — the loops/sl CLI (13450 LOC) — biggest component

CLI for emit/read/fold/stream/store across vertices. Renders via painted through single boundary.

**Entry:** loops.cli.app.main(). Three-tier dispatch:
1. Verbs (registry.VERBS): read, emit, close, sync, cite, store
2. Commands (registry.COMMANDS): test, compile, validate, init, whoami, ls, add, rm, export
3. Vertex-first shorthand: `loops <vertex> [op] [args]` via _vertex_first()
Lazy view loading (registry._view) avoids argparse at import.

**Rendering:** Fetch → Lens → Block → Reporter. Lenses are pure (data, zoom, width, **kwargs)→Block.
No raw print; all via Reporter.print_block()/show(). Zoom: MINIMAL(0)/SUMMARY(1)/DETAILED(2)/FULL(3).
CliContext carries vertex_path, observer, Reporter. Operation IR (fn, params, render_lens, fidelity,
mode static/live/interactive); dispatch() branches action/interactive/live/static.

**Key modules:** cli/app.py (dispatch), cli/registry.py (VERBS/COMMANDS maps), cli/context.py (CliContext),
cli/operation.py (Operation IR), cli/dispatch.py, cli/output.py (Reporter Protocol, PaintedReporter +
BufferReporter, single painted boundary), cli/live.py (run_live InPlaceRenderer), cli/lens.py (3-tier
lens resolution: --lens flag > vertex lens{} decl > built-in), cli/fidelity.py, cli/views/*.py
(read.py router, fold.py the big one, emit/cite/store/stream/ticks/population), commands/*.py (legacy
shims: fetch, emit, resolve, init, ls/add/rm/export, sync, ticks, devtools, store, whoami),
lenses/*.py (fold.py 37K namespace grouping + salience, stream, trace, ticks, validate, store, etc.),
lens_resolver.py (4-tier file search: vertex-local > project > user-global > built-in), main.py (back-compat shim).

**Display vs action:** display (lens) = read/fold, emit --facts, cite, store, stream, ticks, test/compile/validate.
action (no lens) = emit default, close, sync, init, ls, add, rm, export, whoami.

Tests: pytest golden snapshots keyed by module+fn+zoom; invoked via app.main(argv, reporter=BufferReporter());
--update-goldens. conftest: loops_home, simple/project/autoresearch_vertex, populated_store.
Notable: slashed names kind/key, vertex resolution chain, lens 4-tier, config-template dissolution,
fidelity→zoom mapping, Operation IR refactor partial (fold+emit converted, rest legacy shims).

## apps/hlab — homelab monitor (4204 LOC, deps: atoms, engine, painted, httpx, pyyaml) — ARCHIVED experiment

DSL-driven container/stack status, Prometheus alerts, media audit, Uptime-Kuma sync.
Commands: status [stack] / alerts / logs <stack> / media audit|fix / sync uptime-kuma.
Modules: main.py (dispatcher), commands/{status,alerts,logs,media_audit,enrichment}.py,
lenses/{status,alerts,logs,media}.py, theme.py, folds.py (health_fold healthy/total), config.py,
inventory.py (Ansible), infra.py (SSH), tui.py (painted Surface), docker_parse.py, radarr.py.
Domain: vertex declares SSH .loop sources; health_fold computes healthy/total at query time; status→tick.
No tests (archived).

## apps/tasks — task orchestration (3815 LOC, deps: lang, atoms, engine, painted) — "strange-loops" CLI

Tasks are loops; workers run in git worktrees, communicate via SQLite WAL store (no IPC).
Entry: strange_loops.cli.main(). Action commands (argparse) + display commands (run_cli).
Commands: session start|end|status|log; task create|assign|send|run|status|list|log|diff|merge|close|stop;
note; dashboard [--live]; project emit|status|log|bridge.
Modules: cli.py (dispatch, _DISPLAY_SUB), lifecycle.py (fold_task_state/fold_all_tasks, derive state at read),
store.py (emit_fact/emit_tick, parse_duration), harness.py (run_harness loads .loop, substitutes
{{prompt}}/{{command}}, emits worker.output facts, auto-commits), worktree.py (git worktree wrappers),
commands/{task,session,project,dashboard}.py, lenses/{task,session,project}.py.
Domain: state derived (not stored) via vertex_read→fold→extract_task; kind-prefixed facts (task.*/worker.*/
session.*/decision.*); lifecycle created→assigned(worktree)→sent(harness)→completed/merged/closed.
Two stores: tasks.db, project.db. Harnesses: shell/sonnet/opus/codex/gemini-flash .loop files.
Tests: pytest, test_snapshots golden, conftest fixtures (home, workspace, git_repo).

---

## Existing docs/ (12 hand-written deep-dives — DO NOT overwrite in init mode)

VERTEX.md (routing/folding/boundaries), TEMPORAL.md (semantic time, nesting, tick lifecycle),
PERSISTENCE.md (durable vs ephemeral, ULID, store types, replay), SDK.md (proposed loops.sdk layer),
IDENTITY.md (observer field, Grant horizon/potential, participatory stance), SCOPE-LATTICE.md
(capability algebra for delegation), CADENCE.md (Source vs Cadence separation), LENSES.md (pure render,
fidelity levels), NAMED_SESSIONS.md (named scoped sessions design), CLI-CHEATSHEET.md (three-tier
dispatch, fold keys), SDK-EMIT-PLAN.md (emit SDK extraction), orchestration-agent-seed.md (agent identity).
docs/autoresearch/ — coverage campaign #215 data (98.4% line cov, 218 experiments).
docs/scratch/ — session scratch notes.

## CI / Release (.github/workflows/release.yml)

Trigger: GitHub release published. Steps: checkout → install uv → uv build →
pypa/gh-action-pypi-publish (OIDC, env pypi). Publishes strange-loops wheel to PyPI.

## Dependencies

External: painted>=0.1.8 (render), ckdl>=1.0 (KDL), pyjwt[crypto]>=2.9, cryptography>=43,
python-ulid>=3.0, typing_extensions>=4.0, httpx>=0.27 (hlab), pyyaml>=6.0 (hlab).
Dev: pytest, pytest-cov, pytest-asyncio, ruff (line-length 100, py311, [E,F,I,UP,B,SIM,PTH]), ty, rich.

Internal dep graph:
```
atoms (0 deps)
  ↓
lang (ckdl) ────┐
                ↓
engine ← atoms(TYPE_CHECKING) + lang + python-ulid
  ↓
store ← engine (type hints)
  ↓
apps: loops / hlab / tasks  ← atoms + engine + lang + painted
sign (independent: pyjwt/cryptography/ulid)
painted (external repo, PyPI)
```

## tests/ (root) + benchmarks/ + bin/

tests/test_architecture.py — AST-based import boundary enforcement (atoms 0 deps,
engine→atoms TYPE_CHECKING only, no cycles).
benchmarks/: benchmark_emit_path.py, benchmark_read.py.
bin/sub: submodule commit/push harness.
