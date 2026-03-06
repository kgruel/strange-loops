# hlab — homelab monitoring

DSL-driven homelab monitoring and management. Most work is in the `.vertex` and `.loop` files, not app source. Start at Level 0. Only escalate when you hit a trigger.

**You are here** in the abstraction chain:

```
.vertex/.loop (declare)  →  hlab (app)  →  engine (runtime)  →  atoms (data)
status.vertex, *.loop       status/alerts    Tick, Vertex         Fact, Spec, Parse
```

Below: `libs/engine/` runs vertex programs (`.vertex` → ticks). `libs/lang/` parses the DSL. `libs/atoms/` defines facts and parse/fold ops. `libs/painted/` renders everything.

---

## Level 0 — Use it

**Trigger**: I need to check homelab status or run a command.

```bash
uv run hlab status                 # stack container status
uv run hlab alerts                 # Prometheus alert status
uv run hlab logs <stack>           # stream docker compose logs
uv run hlab media audit            # scan for corrupt media files
uv run hlab media fix              # fix corrupt media files
uv run hlab sync uptime-kuma       # sync Uptime Kuma monitors
```

Common flags: `-q` (one-liner), `-v` (detailed), `-vv` (full), `-i` (interactive TUI), `--json`, `--plain`.

**Don't reach for yet**: DSL files, lenses, command internals.

---

## Level 1 — Configure, don't code

**Trigger**: I need to add a host, change monitoring, or adjust what data is collected.

**Most hlab work is DSL configuration, not Python.** The data pipeline is:

```
.loop file (command + parse)  →  .vertex file (fold + boundary)  →  lens (render)
```

Before touching app source, check whether what you need is:

- **A new monitored host** — add a `with` row or template parameter to the `.vertex` file
- **Different data extraction** — modify the `parse` block in the `.loop` file
- **Different aggregation** — change the `fold` block in the `.vertex` file
- **A new data source** — write a `.loop` file (command + format + parse pipeline)

**DSL files live in the app:**
```
src/hlab/loops/
  status.vertex        # 4 stacks from 1 template — container health
  alerts.vertex        # Prometheus alerts pipeline
  media_audit.vertex   # Radarr media audit pipeline
  stacks/status.loop   # Template: docker compose ps per host
  prometheus/*.loop    # Templates: Prometheus API endpoints
  radarr/*.loop        # Templates: Radarr API endpoints
```

See `libs/atoms/` Level 2 (Parse) and Level 3 (Source) for the primitives these files use. See `libs/lang/` for the KDL grammar.

**Don't reach for yet**: Python commands, lenses, fold overrides.

---

## Level 2 — Understand the command patterns

**Trigger**: I need to modify a Python command or add a new one.

**Two patterns:**

**Fetch-then-render** (status, alerts, media audit):
```
main.py routes command
  → make_fetcher(args) returns fetch()
  → _run_command(args, render_fn, fetch_fn)
    → parse fidelity (Zoom × OutputMode × Format)
    → fetch data
    → render_fn(ctx, data) → Block
    → print_block(block)
```

**Streaming/interactive** (logs, media fix, sync uptime-kuma, status -i):
```
main.py routes command
  → detect_context(zoom, mode, fmt) → CliContext
  → run_X(ctx, args) → int
```

**Adding a fetch-then-render command:**
1. `commands/your_cmd.py` — `make_fetcher(args)` returns a zero-arg callable
2. `lenses/your_cmd.py` — `view_fn(data, zoom, width, theme) → Block`
3. `main.py` — wire subparser and route

**Adding a streaming command:**
1. `commands/your_cmd.py` — `run_X(ctx, args) → int`
2. `main.py` — wire with `detect_context()` pass-through

**Don't reach for yet**: DSL internals, fold overrides, TUI surface.

---

## Level 3 — The DSL pipeline

**Trigger**: I need to understand how data flows from SSH/curl to rendered output, or work with fold overrides.

**Three DSL commands** (status, alerts, media audit) use `.vertex` files:

```
.vertex file
  → load_vertex_program(path) → VertexProgram(vertex, sources, expected_ticks)
  → program.collect(rounds=1) → {tick_name: payload}
  → lens renders at zoom level
```

Each source emits facts with its own kind, then `{kind}.complete`. The `.complete` fact triggers that source's boundary. N sources = N loops = N ticks. **tick.name IS the stack name** — no re-grouping needed.

**Parse extracts, fold accumulates, lens presents:**
- `.loop` file `parse` block: full extraction pipeline (where, explode, project)
- `.vertex` file `fold` block: how facts accumulate (collect, latest)
- `lenses/` Python: zoom-aware rendering of tick payloads

**Only `status` uses a Python fold override.** `health_fold` computes derived metrics (healthy/total) not expressible as a single fold op. Everything else is DSL-native.

---

## Key conventions

- Boundaries are semantic — fire when data says so, not on timers.
- Tick payload has pre-computed metrics (status only). Access directly, don't recompute.
- One tick per stack, not one aggregated tick.
- Run first, then code — print actual tick payloads before writing render logic.
- DSL is source of truth — no hardcoded config duplicating the `.vertex` file.

## Build & test

```bash
uv run --package hlab pytest apps/hlab/tests
```
