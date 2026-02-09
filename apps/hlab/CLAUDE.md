# CLAUDE.md — hlab

Homelab monitoring and management CLI. DSL defines status data flow, Python handles everything else.

## The Model

**Facts flow into Vertices. Vertices fold Facts through Specs. Boundaries emit Ticks. Ticks flow onward as Facts. The loop closes.**

Three truths:
- **Time is fundamental.** Facts are observations of what occurred. You are always in the present, observing an ordered past.
- **The observer is first-class.** Facts exist because someone observed them. The `observer` field carries attribution.
- **Everything is loops.** Facts flow in, accumulate into state, boundaries fire, ticks flow out. The end connects to the beginning.

Three atoms:
```
Fact    what happened           kind + ts + payload + observer
Spec    how state accumulates   fields + folds + boundary
Tick    what a period became    name + ts + payload + origin
```

## Run

```bash
uv run hlab                        # show help
uv run hlab status                 # stack container status
uv run hlab alerts                 # Prometheus alert status
uv run hlab logs <stack>           # stream docker compose logs
uv run hlab media audit            # scan for corrupt media files
uv run hlab media fix              # fix corrupt media files
uv run hlab sync uptime-kuma       # sync Uptime Kuma monitors
python -m hlab                     # alternative invocation
```

Common flags (all commands):
```
-q, --quiet     Minimal output (one-liner)
-v              Detailed output
-vv             Full detail
-i              Interactive TUI (where supported)
--json          JSON output
--plain         No ANSI codes
```

## Structure

```
apps/hlab/src/hlab/
├── main.py              # CLI entry point: argparse + command routing
├── __main__.py          # python -m hlab support
├── commands/
│   ├── status.py        # DSL load + fetch (make_fetcher, load, load_with_expected)
│   ├── alerts.py        # DSL load + fetch for Prometheus alerts
│   ├── logs.py          # Docker compose log streaming
│   ├── media_audit.py   # DSL load + fetch for media corruption scan
│   ├── media_fix.py     # Media corruption fix
│   └── sync_uptime_kuma.py  # Uptime Kuma monitor sync
├── lenses/
│   ├── status.py        # Zoom-based status rendering (status_view, render_plain, stack_lens, TUI panels)
│   ├── alerts.py        # Alert rendering
│   ├── media.py         # Media audit rendering
│   └── logs.py          # Log rendering
├── folds.py             # Fold overrides: health_fold only (others replaced by DSL parse/fold)
├── theme.py             # Icons, colors, Theme dataclass
├── tui.py               # Interactive Surface (HlabApp, two-panel layout)
├── infra.py             # Infrastructure helpers
├── inventory.py         # Host/stack inventory
├── radarr.py            # Radarr API client + parsing (parse_movies, parse_quality_definitions)
└── loops/
    ├── status.vertex    # DSL: sources + vertex for status command
    ├── alerts.vertex    # DSL: sources + vertex for alerts command
    ├── media_audit.vertex  # DSL: sources + vertex for media audit command
    ├── stacks/
    │   └── status.loop  # Template: docker compose ps per host
    ├── prometheus/
    │   ├── alerts.loop  # Template: Prometheus /api/v1/alerts
    │   ├── rules.loop   # Template: Prometheus /api/v1/rules
    │   └── targets.loop # Template: Prometheus /api/v1/targets
    └── radarr/
        ├── movies.loop  # Template: Radarr /api/v3/movie
        └── quality.loop # Template: Radarr /api/v3/qualitydefinition
```

## Two Command Patterns

### Fetch-then-render (most commands)

`make_fetcher` returns a zero-arg callable. `_run_command` in `main.py` handles the fidelity→format→output pipeline:

```
main.py routes command
  → make_fetcher(args) returns fetch()
  → _run_command(args, render_fn, fetch_fn)
    → parse fidelity (Zoom × OutputMode × Format)
    → fetch data
    → render_fn(ctx, data) → Block
    → print_block(block)
```

Commands using this: `status`, `alerts`, `media audit`.

### Streaming/interactive (run_X)

Some commands manage their own async lifecycle. `main.py` creates `CliContext` and passes it through:

```
main.py routes command
  → detect_context(zoom, mode, fmt) → CliContext
  → run_X(ctx, args) → int
```

Commands using this: `logs`, `media fix`, `sync uptime-kuma`, and `status -i` (TUI).

## DSL Scope

**`status`, `alerts`, and `media audit` use the DSL.** Each `.vertex` file defines sources (SSH/curl → JSON/ndjson) and fold boundaries. Other commands are direct Python — they fetch data from APIs or run shell commands without the DSL pipeline.

All three use `load_vertex_program()` from `engine` to compile and materialize the vertex. This replaces the manual parse → compile → merge → materialize ceremony.

## Data Flow (DSL commands)

```
.vertex file
  → load_vertex_program(path) → VertexProgram(vertex, sources, expected_ticks)

VertexProgram.run()  or  VertexProgram.collect()
  → async for tick in program.run():
      result[tick.name] = tick.payload

view_fn(result, zoom, width, theme) → Block
```

Each source emits facts with its own kind, then `{kind}.complete`. The `.complete` fact triggers that source's boundary. N sources = N loops = N ticks.

## Parse → Fold → Lens

**Parse extracts, fold accumulates, lens presents.**

Most commands use DSL-native parse pipelines and fold declarations — no Python overrides needed.
The `.loop` file's `parse` block declares the full extraction pipeline (`where`, `explode`, `project`),
and the `.vertex` file's `fold` block declares how facts accumulate (`collect`, `latest`, etc.).

**Only `status` uses a Python fold override.** `health_fold` computes derived metrics (healthy/total)
that aren't expressible as a single fold op:

```python
# status: Python fold override for derived computation
program = load_vertex_program(VERTEX_FILE, default_fold_override=(HEALTH_INITIAL, health_fold))

# alerts, media_audit: DSL-native parse + fold, no Python overrides
program = load_vertex_program(VERTEX_FILE)
```

```
Source emits structured facts (via parse pipeline)
  → DSL fold accumulates (collect/latest)  OR  Python fold computes derived state
    → Tick payload = accumulated state
      → Lens renders at zoom level
```

## Fidelity

Zoom × OutputMode × Format from `cells.fidelity`:

- **Zoom**: MINIMAL (one-liner) → SUMMARY (tree) → DETAILED (bordered tree) → FULL (TUI)
- **OutputMode**: AUTO (detect), STATIC, INTERACTIVE
- **Format**: ANSI, PLAIN, JSON

`add_cli_args(parser)` adds the standard flags. `detect_context(zoom, mode, fmt)` produces `CliContext` with resolved width, zoom, mode, format.

## Adding a Command

1. Create `commands/your_command.py` with `make_fetcher(args)` (fetch-then-render) or `run_X(ctx, args)` (streaming).
2. Create `lenses/your_command.py` with a view function: `(data, zoom, width, theme) → Block`.
3. Wire in `main.py`: add subparser, import, route.

Follow the fetch-then-render pattern unless you need streaming or interactive control.

## Boundaries: Semantic Time

Boundaries fire on domain semantics, not clocks. The question isn't "how much time has passed?" but "what just happened that gives meaning to everything before it?"

In hlab: each source emits facts with its own kind (`infra`, `media`, `dev`, `minecraft`), then `{kind}.complete`. The `.complete` fact triggers that stack's boundary.

## Gotchas

- **tick.name IS the stack name.** No re-grouping needed in render — state is already per-stack.
- **Tick payload has pre-computed metrics** (status only). `payload = {containers: [...], healthy: N, total: M}`. Access directly, don't recompute.
- **One tick per stack, not one aggregated tick.** Each source fires its own boundary.
- **Boundaries are semantic.** They fire when data says so, not on timers.
- **Parse extracts, fold accumulates.** `.loop` parse blocks define the full extraction pipeline. Only `health_fold` remains as a Python override — everything else is DSL-native.
- **alerts_count bridge.** `rules.loop` projects `alerts` (a list), but `AlertRule` expects `alerts_count: int`. The conversion happens in `commands/alerts.py` consumption code.

## Working Here

1. **Run first, then code** — Print actual tick payloads before writing render logic.
2. **DSL is source of truth** — No hardcoded config that duplicates the `.vertex` file.
3. **Trace data, not code** — When debugging, feed facts and print state.
4. **Fidelity is render-side** — DSL doesn't know about zoom levels; that's cells' job.
5. **Boundaries are semantic** — They fire when data says so, not on timers.
