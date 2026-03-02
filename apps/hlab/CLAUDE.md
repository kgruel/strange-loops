# hlab — homelab monitoring

DSL-driven homelab monitoring and management. Start at Level 0. Only escalate when you hit a trigger.

**You are here** in the abstraction chain:

```
atoms (data)  →  engine (runtime)  →  lang (grammar)  →  hlab (app)
Fact, Spec        Tick, Vertex         .loop/.vertex      status/alerts/media
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

## Level 1 — Understand the command patterns

**Trigger**: I need to modify a command or add a new one.

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

## Level 2 — Work with the DSL pipeline

**Trigger**: I need to understand how data flows from SSH/curl to rendered output.

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

```
apps/hlab/loops/
  status.vertex        # 4 stacks from 1 template
  alerts.vertex        # Prometheus alerts pipeline
  media_audit.vertex   # Radarr media audit pipeline
  stacks/status.loop   # Template: docker compose ps per host
  prometheus/*.loop    # Templates: Prometheus API endpoints
  radarr/*.loop        # Templates: Radarr API endpoints
```

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
