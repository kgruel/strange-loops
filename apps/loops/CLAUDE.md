# loops — the CLI

The primary interface to the loops system. Most work is configuration, not code — declaring vertices and writing lenses. Start at Level 0. Only escalate when you hit a trigger.

**You are here** in the abstraction chain:

```
config (declare)  →  loops CLI (use)  →  engine (runtime)  →  atoms (data)
~/.config/loops/     read/emit/close     Vertex, Store        Fact, Spec
```

Below: `libs/engine/` runs vertex programs and persists facts. `libs/lang/` parses the DSL files. `libs/atoms/` defines the data primitives. `libs/painted/` renders everything.
Above: `~/.config/loops/` holds vertex declarations, lenses, and hooks. See its CLAUDE.md for the progressive guide to configuration.

---

## Level 0 — Use the CLI

**Trigger**: I need to query, emit, or run something.

```bash
# Read vertex state
loops ls                                        # all discovered vertices
loops read project                              # current folded state
loops read project --kind decision              # just decisions
loops read meta --facts --since 7d --kind thread  # filtered event history

# Emit a fact
loops emit project decision topic="auth" "JWT over sessions"
loops emit project thread name="store-ops" status="open"

# Run DSL files
loops validate disk.loop                        # syntax check
loops test disk.loop                            # run command, preview facts
loops test disk.loop --input sample.txt         # test parse pipeline

# Inspect a store
loops store data/project.db                     # store contents
loops store data/project.db -i                  # interactive TUI explorer

# Manage template populations
loops ls reading                                # list parameter rows
loops add reading lobsters https://lobste.rs/rss
loops rm reading lobsters
```

Common flags: `-q` (minimal), `-v` (detailed), `-vv` (full), `--json`, `--plain`.

**Don't reach for yet**: Vertex files, lenses, command internals.

---

## Level 1 — Configure, don't code

**Trigger**: I need a new data domain, a custom view, or different fold behavior.

**Most work resolves in configuration, not app source.** Before modifying this app, check whether what you need is:

- **A new vertex** — declare it in `~/.config/loops/<name>/<name>.vertex` (KDL)
- **A custom view** — write a lens in `~/.config/loops/lenses/<name>.py` (pure function)
- **Different fold behavior** — change the `loops {}` block in the vertex file
- **A new source** — write a `.loop` file with command + parse pipeline

See `~/.config/loops/CLAUDE.md` for the full progressive guide to each of these.

**When to go deeper**: You need to modify this app when the CLI itself is missing a command, when the built-in lens resolution needs new behavior, or when the display/action command pattern needs extension. That's Level 2.

**Don't reach for yet**: commands/, lenses/, main.py internals.

---

## Level 2 — Understand the command architecture

**Trigger**: I need to modify a command, add a new one, or change how the CLI wires things.

**Entry point**: `loops.cli.app.main`. The legacy `loops.main.main` is now a 63-LOC back-compat re-export shim that delegates to `cli.app.main` and re-exports `_run_*` symbols from `loops.commands.*` so tests and the registry's `_legacy_view` wrapper keep working.

**Three-tier dispatch** (in `cli/app.py`):

1. **Verbs** — `loops <verb> [vertex] …` — `registry.VERBS`
2. **Commands** — `loops <command> …` — `registry.COMMANDS`
3. **Vertex shorthand** — `loops <vertex> [op] …` — implicit `read` or a vertex-first op from `registry.VERTEX_OPS`

**Verbs / commands are registered in `loops.cli.registry`** (`VERBS`, `COMMANDS`, `POPULATION_OPS`). Each entry is a `View` — `(argv, ctx) -> int` — that resolves lazily on first call.

**Each verb is a view**: `loops/cli/views/<name>.py` exposing `run(argv, ctx) -> int`.

**Two patterns inside views:**

**(a) Full Operation IR** — the view parses argv into an `Operation` and calls `dispatch(op, reporter=ctx.reporter)`. Used by **`fold` and `emit` only** (pilot surfaces; `read` and `cite` are thin routers that delegate into them).

**(b) Legacy shim** — the view delegates to `loops.commands._run_<name>`. Used by `stream`, `store`, `ticks`, `close`, `sync`, and the `population.*` ops (ls/add/rm/export).

**The refactor is paused as a pilot.** Two surfaces use the IR; ten do not. Adding a *new* verb in the IR shape (parse → Operation → dispatch) is the preferred path forward. Converting an existing legacy shim is opportunistic — do it when a touch-point justifies the work, not as a sweep.

**Painted-boundary caveat:** within `cli/`, only `output.py`, `live.py`, and `help.py` import painted at runtime (`operation.py` has a TYPE_CHECKING import). `help.py` is scheduled to retire alongside the legacy help renderer. The `commands/` modules (devtools, emit, resolve, pop, sync, ticks, init, whoami, stream, store, population) still import painted directly — the "single painted boundary" applies inside `cli/`, not `commands/`. Reporter injection is the target shape; it is not the current invariant outside `cli/`.

**Adding a new verb (IR shape — preferred):**
1. `cli/views/<verb>.py` — define `run(argv, ctx)`: parse argv with `argparse`, build an `Operation`, call `dispatch(op, reporter=ctx.reporter)`.
2. Register in `cli/registry.py` via `_view("loops.cli.views.<verb>")`.
3. If display, add a lens in `lenses/<name>.py` — `(data, zoom, width) -> Block` (pure function).

**Adding a new verb (legacy shim shape):**
1. `loops/commands/<verb>.py` — `_run_<verb>(argv, *, vertex_path=None, observer=None) -> int`. May call painted directly.
2. Re-export from `loops/main.py` for back-compat.
3. `cli/views/<verb>.py` — thin `run(argv, ctx)` that delegates to `_run_<verb>`.
4. Register in `cli/registry.py` via `_view(...)` (or `_legacy_view(...)` to point straight at `loops.main`).

**Don't reach for yet**: Store resolution internals, vertex template system, lens resolver implementation.

---

## Level 3 — Resolution and wiring internals

**Trigger**: I need to understand how `loops read project` finds the right database, or how lens resolution works.

**Vertex resolution chain** (`_resolve_named_store`):
1. Try `resolve_vertex(name, LOOPS_HOME)` → `~/.config/loops/{name}/{name}.vertex`
2. Parse the vertex file to extract its `store` path
3. Resolve store path relative to vertex file location
4. Return `StoreReader(resolved_db_path)`

**Local vertex resolution** (`_resolve_local_store`):
1. Look for `*.vertex` in cwd
2. Fallback to `LOOPS_HOME/session/session.vertex`
3. Extract store path, return StoreReader

**Emit resolution**: `loops emit project decision ...` resolves the vertex, opens its SqliteStore, creates a Fact, calls `vertex.receive()`.

**Lens resolution** (4-tier search, first match wins):
1. Vertex-local: `<vertex_dir>/lenses/<name>.py`
2. Project-local: `<cwd>/lenses/<name>.py`
3. User-global: `~/.config/loops/lenses/<name>.py`
4. Built-in: `loops.lenses.<name>`

`--lens` CLI flag overrides all tiers. Vertex `lens {}` declaration overrides tiers 3-4.

**Init system** (vertex templates):
- `loops init` — .vertex in LOOPS_HOME
- `loops init project` — aggregation vertex in LOOPS_HOME + local instance
- `loops init dev/project` — namespaced vertex in LOOPS_HOME

Templates dissolved: `loops init <name>` finds an existing config-level instance vertex and replicates it. No hardcoded template strings — the live instances ARE the templates.

---

## Key conventions

- Display commands route through painted `run_cli`. Zero raw `print()`.
- 4 zoom levels: MINIMAL (counts), SUMMARY (default), DETAILED (bodies), FULL (timestamps).
- Lenses are pure: `(data, zoom, width) -> Block`. No IO, no state.
- `cli/app.py` is the entry point; `main.py` is a 63-LOC back-compat shim. The refactor that extracted dispatch into `cli/` is paused — `fold` and `emit` use the full Operation IR, the other verbs are entry-point shims over `commands/_run_*`.
- Golden snapshot tests lock output across all 4 zoom levels. Run `--update-goldens` to regenerate.

## Build & test

```bash
uv run --package loops pytest apps/loops/tests
uv run --package loops pytest apps/loops/tests/golden  # snapshot tests only
```
