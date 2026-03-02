# loops — the CLI

The primary interface to the loops system. Display commands render through painted; action commands mutate stores. Start at Level 0. Only escalate when you hit a trigger.

**You are here** in the abstraction chain:

```
atoms (data)  →  engine (runtime)  →  lang (grammar)  →  loops (CLI)
Fact, Spec        Tick, Vertex         .loop/.vertex      emit/status/log/run
```

Below: `libs/engine/` runs vertex programs and persists facts. `libs/lang/` parses the DSL files. `libs/atoms/` defines the data primitives. `libs/painted/` renders everything.

---

## Level 0 — Use the CLI

**Trigger**: I need to query, emit, or run something.

```bash
# Query a vertex store
loops status project                    # decisions, threads, tasks, changes
loops log project --since 7d --kind decision  # filtered log

# Emit a fact
loops emit project decision topic="auth" "JWT over sessions"
loops emit project thread name="store-ops" status="open"

# Run DSL files
loops validate disk.loop                # syntax check
loops start status.vertex               # run vertex, render ticks
loops run disk.loop                     # execute, print facts

# Inspect a store
loops store data/project.db             # store contents
loops store data/project.db -i          # interactive TUI explorer

# Manage template populations
loops ls reading                        # list parameter rows
loops add reading lobsters https://lobste.rs/rss
loops rm reading lobsters
```

Common flags: `-q` (minimal), `-v` (detailed), `-vv` (full), `--json`, `--plain`.

**Don't reach for yet**: Lenses, commands/, main.py internals.

---

## Level 1 — Understand the architecture

**Trigger**: I need to modify a command or add a new one.

**Two command patterns:**

**Display commands** (9) — fetch data, render through painted:
```
main.py routes command
  → fetch(args) → data           # commands/*.py
  → lens(data, zoom, width) → Block  # lenses/*.py
  → run_cli() handles zoom/json/plain/width
```

Commands: `status`, `log`, `store`, `start`, `compile`, `validate`, `test`, `ls`, `run`.

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
3. `main.py` — add to `_display` dict, wire subparser

**Adding an action command:**
1. Handler in `main.py` or `commands/` — parse args, do work, render confirmation
2. Wire in `create_parser()` + command dispatch

**Don't reach for yet**: Store resolution internals, vertex template system, TUI.

---

## Level 2 — Store and vertex resolution

**Trigger**: I need to understand how `loops status project` finds the right database.

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

**Init system** (from vertex template system):
- `loops init` — root.vertex in LOOPS_HOME
- `loops init --template session` — local vertex in cwd
- `loops init project` — aggregation vertex in LOOPS_HOME + local instance
- `loops init dev/project --template session` — namespaced vertex in LOOPS_HOME

Templates: `_SESSION_VERTEX`, `_TASKS_VERTEX`, `_PROJECT_VERTEX`, `_AGGREGATION_VERTEX`.

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
