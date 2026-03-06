# loops — the CLI

The primary interface to the loops system. Most work is configuration, not code — declaring vertices and writing lenses. Start at Level 0. Only escalate when you hit a trigger.

**You are here** in the abstraction chain:

```
config (declare)  →  loops CLI (use)  →  engine (runtime)  →  atoms (data)
~/.config/loops/     emit/status/fold    Vertex, Store        Fact, Spec
```

Below: `libs/engine/` runs vertex programs and persists facts. `libs/lang/` parses the DSL files. `libs/atoms/` defines the data primitives. `libs/painted/` renders everything.
Above: `~/.config/loops/` holds vertex declarations, lenses, and hooks. See its CLAUDE.md for the progressive guide to configuration.

---

## Level 0 — Use the CLI

**Trigger**: I need to query, emit, or run something.

```bash
# Query a vertex store
loops vertices                                  # all discovered vertices
loops fold project                              # current folded state
loops fold project --kind decision              # just decisions
loops stream meta --since 7d --kind thread      # filtered event history

# Emit a fact
loops emit project decision topic="auth" "JWT over sessions"
loops emit project thread name="store-ops" status="open"

# Run DSL files
loops validate disk.loop                        # syntax check
loops start status.vertex                       # run vertex, render ticks
loops run disk.loop                             # execute, print facts

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

**Two command patterns:**

**Display commands** (9) — fetch data, render through painted:
```
main.py routes command
  → fetch(args) → data           # commands/*.py
  → lens(data, zoom, width) → Block  # lenses/*.py
  → run_cli() handles zoom/json/plain/width
```

Commands: `fold`, `stream`, `store`, `start`, `compile`, `validate`, `test`, `ls`, `vertices`.

**Action commands** (5) — parse args, mutate, exit:
```
main.py routes command
  → parse args
  → act (write to store, create file, etc.)
  → show(Block.text()) for confirmation
```

Commands: `init`, `emit`, `add`, `rm`, `export`.

**Adding a display command:**
1. `commands/your_cmd.py` — `fetch_*(args) -> dict` (data retrieval, no rendering)
2. `lenses/your_cmd.py` — `your_view(data, zoom, width) -> Block` (pure function)
3. `main.py` — add to command dispatch, wire subparser

**Adding an action command:**
1. Handler in `main.py` or `commands/` — parse args, do work, render confirmation
2. Wire in `create_parser()` + command dispatch

**Key wiring — `run_cli()`:**
```python
def fetch():
    return fetch_status(vertex_path, kind=known.kind)

def render(ctx, data):
    return render_fn(data, ctx.zoom, ctx.width)

return run_cli(rest, fetch=fetch, render=render, help_args=[...])
```

`run_cli` handles zoom resolution, output mode (static/live/interactive), format (ANSI/plain/JSON), and TTY detection. Display commands provide `fetch` and `render`, framework handles the rest.

**Don't reach for yet**: Store resolution internals, vertex template system, lens resolver implementation.

---

## Level 3 — Resolution and wiring internals

**Trigger**: I need to understand how `loops fold project` finds the right database, or how lens resolution works.

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
- `loops init` — root.vertex in LOOPS_HOME
- `loops init project` — aggregation vertex in LOOPS_HOME + local instance
- `loops init dev/project` — namespaced vertex in LOOPS_HOME

Templates dissolved: `loops init <name>` finds an existing config-level instance vertex and replicates it. No hardcoded template strings — the live instances ARE the templates.

---

## Key conventions

- 9 display commands route through painted `run_cli`. Zero raw `print()`.
- 4 zoom levels: MINIMAL (counts), SUMMARY (default), DETAILED (bodies), FULL (timestamps).
- Lenses are pure: `(data, zoom, width) -> Block`. No IO, no state.
- `main.py` is the monolith (~1200 lines). Commands/ and lenses/ are extracted concerns.
- Golden snapshot tests lock output across all 4 zoom levels. Run `--update-goldens` to regenerate.

## Build & test

```bash
uv run --package loops pytest apps/loops/tests
uv run --package loops pytest apps/loops/tests/golden  # snapshot tests only
```
